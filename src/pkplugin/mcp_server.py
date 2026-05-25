"""
pk-copilot MCP server.

Exposes the v0.1 NCA computational kernel as MCP tools. The server is
launched by ``.mcp.json``::

    uv run python -m pkplugin.mcp_server

All tools are JSON-serialisable, deterministic, and emit a JSON-of-record
audit entry on every invocation (see :mod:`pkplugin.audit`).

Refs: docs/06-mcp-server.md
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

import pandas as pd

from pkplugin import __version__ as PKPLUGIN_VERSION
from pkplugin.audit import (
    AuditEntry,
    audit_dir_default,
    collect_dependency_versions,
    collect_os_info,
    file_sha256,
    new_entry,
    new_run_id,
)
from pkplugin.ingest import (
    IngestReport,
    load_dataset,
    to_concentration_records,
    to_dose_records,
)
from pkplugin.nca.engine import calculate_nca
from pkplugin.schemas import NCAConfig
from pkplugin.version import DEFAULTS, WNVersion

# ---------------------------------------------------------------------------
# Part 11 chain-emission helper
# ---------------------------------------------------------------------------

def _emit_chain_entry(
    run_dir: Path,
    action: str,
    user: dict[str, str] | None,
    reason: str,
    run_id: str,
    after: dict[str, Any] | None = None,
) -> None:
    """Best-effort audit chain emission.

    When PKPLUGIN_PART11_ENABLED=1 is set, emits an entry to the run's
    audit chain.  If the compliance module is unavailable or chain emission
    fails for any reason, silently continues so v1.x behaviour is preserved.
    """
    if os.environ.get("PKPLUGIN_PART11_ENABLED", "0") != "1":
        return
    try:
        from pkplugin.compliance.audit_chain import AuditChain

        effective_user: dict[str, str] = user or {
            "id": "anonymous",
            "auth_method": "anonymous",
        }
        chain = AuditChain.open(run_dir)
        chain.append(
            action=action,
            user=effective_user,
            reason=reason,
            run_id=run_id,
            after=after,
        )
    except Exception as _exc:
        logger.warning("_emit_chain_entry failed for action=%r run_id=%r: %s", action, run_id, _exc)


# Compartmental imports — resolved lazily inside each impl to avoid hard
# failures when the module is imported without all optional deps present.
# (These are always available in a normal pkplugin install.)
_COMP_AVAILABLE: bool | None = None


def _check_comp_available() -> bool:
    global _COMP_AVAILABLE
    if _COMP_AVAILABLE is None:
        try:
            import pkplugin.comp.fitting  # noqa: F401
            _COMP_AVAILABLE = True
        except ImportError:
            _COMP_AVAILABLE = False
    return bool(_COMP_AVAILABLE)


# ---------------------------------------------------------------------------
# Implementation functions (testable independently of fastmcp)
# ---------------------------------------------------------------------------


def _serialise_for_json(value: Any) -> Any:
    """Convert numpy/pandas values to plain Python primitives."""
    if value is None:
        return None
    if isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, list | tuple):
        return [_serialise_for_json(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialise_for_json(v) for k, v in value.items()}
    return str(value)


def impl_validate_dataset(
    input_file: str,
    schema_type: str = "auto",
    column_mapping: dict[str, str] | None = None,
    units: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Inspect a concentration dataset; return mapping + units + counts.

    Refs: docs/06-mcp-server.md §1
    """
    path = Path(input_file).resolve()
    if not path.is_file():
        return {
            "status": "error",
            "error": f"File not found: {path}",
        }

    from pkplugin.ingest import ColumnMapping

    user_mapping: ColumnMapping | None = None
    if column_mapping is not None:
        user_mapping = ColumnMapping(**column_mapping)

    try:
        df, report = load_dataset(path, column_mapping=user_mapping)
    except Exception as exc:  # pragma: no cover - surface to MCP client
        return {"status": "error", "error": str(exc)}

    needs_confirmation: list[str] = []
    if not report.inferred_units.get("time"):
        needs_confirmation.append("time_unit")
    if not report.inferred_units.get("concentration"):
        needs_confirmation.append("concentration_unit")
    if units is not None:
        # caller supplied units — clear confirmations they covered
        for key in list(needs_confirmation):
            short = key.replace("_unit", "")
            if short in units:
                needs_confirmation.remove(key)

    status = "needs_user_input" if needs_confirmation else "ok"

    return {
        "status": status,
        "mapped_columns": {
            "subject_id": report.column_mapping.subject_id,
            "time": report.column_mapping.time,
            "concentration": report.column_mapping.concentration,
            "analyte": report.column_mapping.analyte,
            "period": report.column_mapping.period,
            "treatment": report.column_mapping.treatment,
            "sequence": report.column_mapping.sequence,
            "bloq_flag": report.column_mapping.bloq_flag,
        },
        "units_detected": dict(report.inferred_units),
        "n_rows": report.n_rows,
        "n_subjects": report.n_subjects,
        "n_bloq": report.n_bloq,
        "lloq_candidates": report.lloq_candidates,
        "raw_bloq_patterns_seen": report.raw_bloq_patterns_seen,
        "warnings": report.warnings,
        "needs_confirmation": needs_confirmation,
        "file_sha256": file_sha256(path),
    }


def impl_run_nca(
    dataset_path: str,
    config: dict[str, Any] | None = None,
    dose_path: str | None = None,
    subjects: list[str] | None = None,
    analytes: list[str] | None = None,
    audit_dir: str | None = None,
) -> dict[str, Any]:
    """Run NCA + write audit + produce executable re-run script.

    Refs: docs/06-mcp-server.md §2
    """
    ds_path = Path(dataset_path).resolve()
    if not ds_path.is_file():
        return {"status": "error", "error": f"Dataset not found: {ds_path}"}

    cfg_dict: dict[str, Any] = config or {}
    nca_cfg = NCAConfig(**cfg_dict)

    df, _ = load_dataset(ds_path)
    if subjects is not None:
        df = df[df["subject_id"].isin(subjects)]
    if analytes is not None:
        df = df[df["analyte"].isin(analytes)]

    from pkplugin.schemas import DoseRecord as _DoseRecord

    conc_records = to_concentration_records(df)

    dose_records: list[_DoseRecord] = []
    dose_path_resolved: Path | None = None
    if dose_path is not None:
        dose_path_resolved = Path(dose_path).resolve()
        if not dose_path_resolved.is_file():
            return {"status": "error", "error": f"Dose file not found: {dose_path_resolved}"}
        dose_df, _ = load_dataset(dose_path_resolved)
        dose_records = to_dose_records(dose_df)
    elif "dose" in df.columns:
        # Synthesize one IV bolus dose record per subject from the inline dose column.
        from pkplugin.schemas import DoseRecord

        for sid, sub in df.groupby("subject_id"):
            dose_val = sub["dose"].dropna()
            if dose_val.empty:
                continue
            dose_records.append(
                DoseRecord(
                    subject_id=str(sid),
                    time=0.0,
                    amount=float(dose_val.iloc[0]),
                    route="oral",
                )
            )

    results = calculate_nca(conc_records, dose_records, nca_cfg)

    # Build parameter table
    rows: list[dict[str, Any]] = []
    for r in results:
        for prow in r.parameter_rows:
            rows.append(
                {
                    "subject_id": prow.subject_id,
                    "period": prow.period,
                    "treatment": prow.treatment,
                    "analyte": prow.analyte,
                    "parameter": prow.parameter,
                    "value": prow.value,
                    "unit": prow.unit,
                    "method": prow.method,
                    "winnonlin_version": prow.winnonlin_version,
                    "flags": ";".join(prow.flags),
                    "comment": prow.comment,
                }
            )
    pdf = pd.DataFrame(rows)

    # Build audit entry first (it generates run_id internally).
    input_paths: list[str | Path] = [ds_path]
    if dose_path_resolved is not None:
        input_paths.append(dose_path_resolved)

    entry: AuditEntry = new_entry(
        tool="run_nca",
        config=_serialise_for_json(nca_cfg.model_dump()),
        input_paths=input_paths,
        winnonlin_compat=nca_cfg.winnonlin_version,
    )
    run_id = entry.run_id

    audit_base = Path(audit_dir) if audit_dir else audit_dir_default()
    # B4: AuditEntry.write() appends run_id internally, so pass audit_base not run_dir.
    run_dir = audit_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    csv_path = run_dir / "parameters.csv"
    pdf.to_csv(csv_path, index=False)

    script_path = run_dir / "nca_script.py"
    script_path.write_text(_render_nca_script(ds_path, dose_path_resolved, nca_cfg, subjects, analytes))

    all_warnings: list[str] = []
    for r in results:
        for w in r.warnings:
            if w not in all_warnings:
                all_warnings.append(w)

    # B5: Expand audit results to include per-subject parameter details and diagnostics.
    parameters_by_subject: dict[str, dict[str, object]] = {}
    lambda_z_diagnostics: dict[str, dict[str, object]] = {}
    for r in results:
        sid = r.subject_id
        parameters_by_subject[sid] = {
            k: _serialise_for_json(v) for k, v in r.parameters.items()
        }
        lz = r.lambda_z_result
        lambda_z_diagnostics[sid] = _serialise_for_json({
            "t_start": lz.t_start,
            "t_end": lz.t_end,
            "n_points": lz.n_points,
            "r2": lz.r_squared,
            "adj_r2": lz.adjusted_r_squared,
            "span_ratio": lz.span_ratio,
            "method": lz.method,
            "warnings": lz.warnings,
        })

    entry.results = {
        "n_results": len(results),
        "subjects": sorted({r.subject_id for r in results}),
        "parameters_by_subject": parameters_by_subject,
        "lambda_z_diagnostics": lambda_z_diagnostics,
        "resolved_config": _serialise_for_json(nca_cfg.resolved()),
    }
    entry.warnings = all_warnings
    entry.artifacts = [
        {"name": "parameters.csv", "path": str(csv_path), "sha256": file_sha256(csv_path)},
        {"name": "nca_script.py", "path": str(script_path), "sha256": file_sha256(script_path)},
    ]
    # B4: pass audit_base so write() creates audit_base/run_id/audit.json (not double-nested)
    audit_json_path = entry.write(audit_base)

    # Part 11 chain emission (best-effort, no-op when PKPLUGIN_PART11_ENABLED != 1)
    _emit_chain_entry(
        run_dir=run_dir,
        action="run_nca",
        user=None,
        reason="NCA analysis run",
        run_id=run_id,
        after={"run_state": "draft", "n_subjects": len(results)},
    )

    # Summary of headline parameters per subject for the chat response
    parameter_summary: list[dict[str, Any]] = []
    headline_keys = ("Cmax", "Tmax", "AUClast", "AUCINF_obs", "HL_Lambda_z")
    for r in results:
        parameter_summary.append(
            {
                "subject_id": r.subject_id,
                "period": r.period,
                "treatment": r.treatment,
                "analyte": r.analyte,
                **{k: _serialise_for_json(r.parameters.get(k)) for k in headline_keys},
            }
        )

    return {
        "status": "ok",
        "run_id": run_id,
        "audit_path": str(audit_json_path),
        "results_csv_path": str(csv_path),
        "script_path": str(script_path),
        "parameter_summary": parameter_summary,
        "warnings": all_warnings,
    }


def _render_nca_script(
    dataset: Path,
    dose: Path | None,
    cfg: NCAConfig,
    subjects: list[str] | None = None,
    analytes: list[str] | None = None,
) -> str:
    # B2: Use repr() on the config dict so the output is valid Python
    # (json.dumps emits null/true/false which are not Python literals).
    cfg_repr = repr(cfg.model_dump())
    dose_block = ""
    if dose is not None:
        dose_block = (
            f"dose_df, _ = load_dataset(Path({str(dose)!r}))\n"
            f"dose_records = to_dose_records(dose_df)\n"
        )
    else:
        dose_block = (
            "from pkplugin.schemas import DoseRecord\n"
            "dose_records = []\n"
            "if 'dose' in df.columns:\n"
            "    for sid, sub in df.groupby('subject_id'):\n"
            "        amount = float(sub['dose'].dropna().iloc[0])\n"
            "        dose_records.append(DoseRecord(subject_id=str(sid), time=0.0, "
            "amount=amount, route='oral'))\n"
        )

    # Build optional subject/analyte filter lines.
    filter_block = ""
    if subjects is not None:
        filter_block += f"df = df[df['subject_id'].isin({subjects!r})]\n"
    if analytes is not None:
        filter_block += f"df = df[df['analyte'].isin({analytes!r})]\n"

    return (
        f"# Auto-generated reproducible NCA script\n"
        f"# pk-copilot {PKPLUGIN_VERSION}\n"
        f"from pathlib import Path\n"
        f"from pkplugin.ingest import load_dataset, to_concentration_records, to_dose_records\n"
        f"from pkplugin.schemas import NCAConfig\n"
        f"from pkplugin.nca.engine import calculate_nca\n"
        f"\n"
        f"df, _ = load_dataset(Path({str(dataset)!r}))\n"
        f"{filter_block}"
        f"conc_records = to_concentration_records(df)\n"
        f"{dose_block}"
        f"config = NCAConfig(**{cfg_repr})\n"
        f"results = calculate_nca(conc_records, dose_records, config)\n"
        f"for r in results:\n"
        f"    print(r.subject_id, r.parameters)\n"
    )


def impl_run_be(
    parameter_dataset_path: str,
    endpoint: str = "AUC0_t",
    design: str = "crossover_2x2",
    test_label: str | None = None,
    reference_label: str | None = None,
    be_window_low: float = 80.0,
    be_window_high: float = 125.0,
    winnonlin_version: str = "6.4",
    audit_dir: str | None = None,
) -> dict[str, Any]:
    """Run bioequivalence analysis + emit audit.

    Loads a subject-level parameter table (CSV) and computes Average
    Bioequivalence statistics.  Writes ``be_result.csv`` and ``audit.json``
    to the run directory.

    Refs: docs/06-mcp-server.md §3
    """
    from pkplugin.nca.bioequivalence import BEDesign, run_bioequivalence

    ds_path = Path(parameter_dataset_path).resolve()
    if not ds_path.is_file():
        return {"status": "error", "error": f"Parameter dataset not found: {ds_path}"}

    try:
        df = pd.read_csv(ds_path)
    except Exception as exc:
        return {"status": "error", "error": f"Failed to read CSV: {exc}"}

    # Validate required columns
    required_base = {"subject_id", "treatment", endpoint}
    if design == "crossover_2x2":
        required_base |= {"period", "sequence"}
    missing = required_base - set(df.columns)
    if missing:
        return {
            "status": "error",
            "error": f"Missing required columns: {sorted(missing)}",
        }

    be_window: tuple[float, float] = (be_window_low, be_window_high)

    try:
        result = run_bioequivalence(
            parameters=df,
            endpoint=endpoint,
            design=design,  # type: ignore[arg-type]
            test_label=test_label,
            reference_label=reference_label,
            be_window=be_window,
            winnonlin_version=winnonlin_version,
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    be_result_dict: dict[str, Any] = {
        "design": result.design,
        "endpoint": result.endpoint,
        "transformation": result.transformation,
        "n_subjects": result.n_subjects,
        "n_completers": result.n_completers,
        "test_label": result.test_label,
        "reference_label": result.reference_label,
        "ls_mean_test": _serialise_for_json(result.ls_mean_test),
        "ls_mean_reference": _serialise_for_json(result.ls_mean_reference),
        "difference_log": _serialise_for_json(result.difference_log),
        "gmr_pct": _serialise_for_json(result.gmr_pct),
        "ci_90_low_pct": _serialise_for_json(result.ci_90_low_pct),
        "ci_90_high_pct": _serialise_for_json(result.ci_90_high_pct),
        "be_window": list(result.be_window),
        "be_demonstrated": result.be_demonstrated,
        "within_subject_cv_pct": _serialise_for_json(result.within_subject_cv_pct),
        "df": _serialise_for_json(result.df),
        "anova_table": _serialise_for_json(result.anova_table),
        "method": result.method,
        "warnings": result.warnings,
    }

    # Build audit entry
    entry: AuditEntry = new_entry(
        tool="run_be",
        config={
            "endpoint": endpoint,
            "design": design,
            "test_label": test_label,
            "reference_label": reference_label,
            "be_window_low": be_window_low,
            "be_window_high": be_window_high,
            "winnonlin_version": winnonlin_version,
        },
        input_paths=[ds_path],
        winnonlin_compat=winnonlin_version,
    )
    run_id = entry.run_id

    audit_base = Path(audit_dir) if audit_dir else audit_dir_default()
    run_dir = audit_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Write single-row summary CSV
    be_csv_path = run_dir / "be_result.csv"
    be_summary_row: dict[str, Any] = {
        "run_id": run_id,
        "design": result.design,
        "endpoint": result.endpoint,
        "transformation": result.transformation,
        "n_subjects": result.n_subjects,
        "n_completers": result.n_completers,
        "test_label": result.test_label,
        "reference_label": result.reference_label,
        "gmr_pct": result.gmr_pct,
        "ci_90_low_pct": result.ci_90_low_pct,
        "ci_90_high_pct": result.ci_90_high_pct,
        "be_window_low": result.be_window[0],
        "be_window_high": result.be_window[1],
        "be_demonstrated": result.be_demonstrated,
        "within_subject_cv_pct": result.within_subject_cv_pct,
        "df": result.df,
        "method": result.method,
    }
    pd.DataFrame([be_summary_row]).to_csv(be_csv_path, index=False)

    entry.results = be_result_dict
    entry.warnings = result.warnings
    entry.artifacts = [
        {
            "name": "be_result.csv",
            "path": str(be_csv_path),
            "sha256": file_sha256(be_csv_path),
        }
    ]
    audit_json_path = entry.write(audit_base)

    # Part 11 chain emission
    _emit_chain_entry(
        run_dir=run_dir,
        action="run_be",
        user=None,
        reason="BE analysis run",
        run_id=run_id,
        after={"run_state": "draft", "be_demonstrated": result.be_demonstrated},
    )

    return {
        "status": "ok",
        "run_id": run_id,
        "audit_path": str(audit_json_path),
        "be_result": be_result_dict,
        "warnings": result.warnings,
    }


def impl_summarize_nca(
    nca_run_id: str | None = None,
    parameter_dataset_path: str | None = None,
    group_by: list[str] | None = None,
    parameters: list[str] | None = None,
    audit_dir: str | None = None,
) -> dict[str, Any]:
    """Descriptive statistics across NCA results.

    Two input modes:
      - nca_run_id: re-load parameters from a previous run's parameters.csv
      - parameter_dataset_path: explicit CSV path (long-format)

    Refs: docs/06-mcp-server.md §3
    """
    from pkplugin.nca.stats import DEFAULT_PARAMETERS, summarize_values

    if nca_run_id is None and parameter_dataset_path is None:
        return {
            "status": "error",
            "error": "Provide either nca_run_id or parameter_dataset_path.",
        }

    # Resolve the CSV path
    audit_base = Path(audit_dir) if audit_dir else audit_dir_default()
    csv_path: Path
    if nca_run_id is not None:
        csv_path = audit_base / nca_run_id / "parameters.csv"
    else:
        assert parameter_dataset_path is not None
        csv_path = Path(parameter_dataset_path).resolve()

    if not csv_path.is_file():
        return {"status": "error", "error": f"Parameters CSV not found: {csv_path}"}

    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:
        return {"status": "error", "error": f"Failed to read CSV: {exc}"}

    # Determine group-by columns (use those present in the DataFrame)
    default_group_by = ["treatment", "period", "analyte"]
    effective_group_by = group_by if group_by is not None else default_group_by
    group_cols = [c for c in effective_group_by if c in df.columns]

    # Determine parameters to summarise
    default_params: list[str] = list(DEFAULT_PARAMETERS)
    if parameters is not None:
        param_list = parameters
    else:
        # If dataframe has a 'parameter' column, use its unique values (long format)
        if "parameter" in df.columns:
            param_list = sorted(df["parameter"].dropna().unique().tolist())
        else:
            param_list = default_params

    # Build summary groups
    summary_rows: list[dict[str, Any]] = []

    if "parameter" in df.columns:
        # Long-format table (from run_nca output): pivot before grouping
        # Group by group_cols + subject_id, then pivot parameter → value
        id_cols = [c for c in (group_cols + ["subject_id"]) if c in df.columns]
        if id_cols and "value" in df.columns:
            try:
                wide = df.pivot_table(
                    index=id_cols,
                    columns="parameter",
                    values="value",
                    aggfunc="first",
                ).reset_index()
            except Exception:
                wide = df.copy()
        else:
            wide = df.copy()
    else:
        # Already wide format
        wide = df.copy()

    # Group and summarise
    if group_cols:
        present_group_cols = [c for c in group_cols if c in wide.columns]
        if present_group_cols:
            grouped = wide.groupby(present_group_cols, dropna=False)
        else:
            grouped = [(({},), wide)]  # type: ignore[assignment]
    else:
        grouped = [(({},), wide)]  # type: ignore[assignment]

    def _groups_iter(
        df_wide: pd.DataFrame,
        gcols: list[str],
    ) -> list[tuple[dict[str, str], pd.DataFrame]]:
        if not gcols:
            return [({}, df_wide)]
        result_groups: list[tuple[dict[str, str], pd.DataFrame]] = []
        for keys, sub in df_wide.groupby(gcols, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            gk: dict[str, str] = {
                col: (str(k) if k is not None and str(k) != "nan" else "<unspecified>")
                for col, k in zip(gcols, keys)
            }
            result_groups.append((gk, sub))
        return result_groups

    present_group_cols = [c for c in group_cols if c in wide.columns]
    for group_keys_dict, sub_df in _groups_iter(wide, present_group_cols):
        n_subjects = int(sub_df["subject_id"].nunique()) if "subject_id" in sub_df.columns else len(sub_df)
        by_parameter: dict[str, Any] = {}
        for param in param_list:
            if param in sub_df.columns:
                vals: list[float | None] = [
                    float(v) if v is not None and str(v) not in ("nan", "NaN", "") else None
                    for v in sub_df[param].tolist()
                ]
                summary = summarize_values(vals, parameter=param)
                by_parameter[param] = {
                    "n": summary.n,
                    "n_missing": summary.n_missing,
                    "mean": _serialise_for_json(summary.mean),
                    "sd": _serialise_for_json(summary.sd),
                    "cv_pct": _serialise_for_json(summary.cv_pct),
                    "geo_mean": _serialise_for_json(summary.geo_mean),
                    "geo_cv_pct": _serialise_for_json(summary.geo_cv_pct),
                    "median": _serialise_for_json(summary.median),
                    "min": _serialise_for_json(summary.min),
                    "max": _serialise_for_json(summary.max),
                    "q1": _serialise_for_json(summary.q1),
                    "q3": _serialise_for_json(summary.q3),
                }
            else:
                by_parameter[param] = {
                    "n": 0,
                    "n_missing": 0,
                    "mean": None,
                    "sd": None,
                    "cv_pct": None,
                    "geo_mean": None,
                    "geo_cv_pct": None,
                    "median": None,
                    "min": None,
                    "max": None,
                    "q1": None,
                    "q3": None,
                }
        summary_rows.append(
            {
                "group_keys": group_keys_dict,
                "n_subjects": n_subjects,
                "by_parameter": by_parameter,
            }
        )

    # Emit audit entry
    entry = new_entry(
        tool="summarize_nca",
        config={
            "nca_run_id": nca_run_id,
            "parameter_dataset_path": str(csv_path),
            "group_by": group_cols,
            "parameters": param_list,
        },
        input_paths=[csv_path],
    )
    run_id = entry.run_id
    entry.results = {"n_groups": len(summary_rows)}
    audit_json_path = entry.write(audit_base)

    return {
        "status": "ok",
        "run_id": run_id,
        "audit_path": str(audit_json_path),
        "summary": summary_rows,
    }


def impl_list_pk_models() -> dict[str, Any]:
    """Return all available PK model names, WinNonlin numbers, and parameters.

    Refs: docs/03-algorithms/08-compartmental-models.md §1
    """
    from pkplugin.comp.models import REGISTRY

    models: list[dict[str, Any]] = []
    for name, spec in REGISTRY.items():
        models.append(
            {
                "name": spec.name,
                "winnonlin_model_id": spec.winnonlin_model_id,
                "n_compartments": spec.n_compartments,
                "route": spec.route.value,
                "parameter_names": list(spec.parameter_names),
                "has_michaelis_menten": spec.has_michaelis_menten,
                "has_lag": spec.has_lag,
            }
        )
    return {
        "status": "ok",
        "models": models,
        "n_models": len(models),
    }


def _ode_only_models() -> frozenset[str]:
    """Return the set of ODE-only MM model names supported by comp.ode."""
    from pkplugin.comp.ode import MODEL_REQUIRED_PARAMS
    from pkplugin.comp.models import REGISTRY
    return frozenset(MODEL_REQUIRED_PARAMS) - frozenset(REGISTRY)


def _all_supported_models() -> frozenset[str]:
    """Combined set: REGISTRY linear models + ODE-only MM models (H6)."""
    from pkplugin.comp.models import REGISTRY
    return frozenset(REGISTRY) | _ode_only_models()


def _parse_dose_csv(
    dose_path: "Path",
    subject_id: "str | None" = None,
) -> "list[Any]":
    """Parse a dose CSV and return a list of DosingEvent objects.

    M3: Filters rows by subject_id when provided so that each subject's
    dosing uses only their own rows.

    Expected columns: time, amount, route (optional), infusion_duration (optional).
    """
    from pkplugin.comp.ode import DosingEvent

    dose_df = pd.read_csv(dose_path)
    # H7 / M3: filter by subject when the column is present
    if subject_id is not None and "subject_id" in dose_df.columns:
        dose_df = dose_df[dose_df["subject_id"].astype(str) == str(subject_id)]

    ev_list: list[DosingEvent] = []
    for _, row in dose_df.iterrows():
        route_str = str(row.get("route", "iv_bolus")).lower().replace(" ", "_")
        if route_str not in ("iv_bolus", "iv_infusion", "oral"):
            route_str = "iv_bolus"
        infusion_dur: float | None = None
        if route_str == "iv_infusion" and "infusion_duration" in dose_df.columns:
            infusion_dur = float(row["infusion_duration"])
        ev_list.append(
            DosingEvent(
                time=float(row.get("time", 0.0)),
                amount=float(row["amount"]),
                route=route_str,  # type: ignore[arg-type]
                infusion_duration=infusion_dur,
            )
        )
    return ev_list


def impl_simulate_pk_model(
    model_name: str,
    params: dict[str, float],
    dose: float,
    times: list[float],
    infusion_duration: float | None = None,
    tlag: float = 0.0,
    F: float = 1.0,
) -> dict[str, Any]:
    """Forward simulation returning predicted concentrations.

    Uses the closed-form analytic solution for linear models when available
    (or ODE if the model requires it).  Also accepts ODE-only MM models
    (cmt1_iv_mm, cmt2_iv_mm, cmt1_po_mm).

    Refs: docs/03-algorithms/08-compartmental-models.md §2–§3
    """
    from pkplugin.comp.models import REGISTRY

    # H6: validate against combined set (REGISTRY + ODE-only MM models)
    all_supported = _all_supported_models()
    if model_name not in all_supported:
        return {
            "status": "error",
            "error": (
                f"Unknown model: {model_name!r}. "
                f"Available: {sorted(all_supported)}"
            ),
        }

    try:
        # For ODE-only MM models, route through simulate_ode directly
        if model_name not in REGISTRY:
            from pkplugin.comp.ode import DosingEvent, simulate_ode, simulate_ode_with_tlag
            import numpy as np

            # Infer route from model name
            if "po" in model_name:
                route_str: Any = "oral"
            else:
                route_str = "iv_bolus"
            dosing_ev = [DosingEvent(time=0.0, amount=dose, route=route_str,
                                     infusion_duration=infusion_duration)]
            if tlag > 0.0:
                conc = simulate_ode_with_tlag(
                    model_name, params, dosing_ev, times, tlag=tlag
                )
            else:
                conc = simulate_ode(model_name, params, dosing_ev, times)
        else:
            from pkplugin.comp.analytic import predict

            conc = predict(
                model=model_name,
                params=params,
                times=times,
                dose=dose,
                infusion_duration=infusion_duration,
                tlag=tlag,
                F=F,
            )
        return {
            "status": "ok",
            "model_name": model_name,
            "times": _serialise_for_json(list(times)),
            "concentrations": _serialise_for_json(conc.tolist()),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def impl_fit_pk_model(
    dataset_path: str,
    model_name: str,
    initial_params: dict[str, float],
    dose: float | None = None,
    dose_path: str | None = None,
    weighting: str = "1_over_y_squared",
    residual_error: str = "proportional",
    use_ode: bool = False,
    winnonlin_version: str = "6.4",
    audit_dir: str | None = None,
) -> dict[str, Any]:
    """Fit a PK compartmental model and emit audit + write fit artifacts.

    Loads the dataset CSV (requires columns: time, concentration, and
    optionally dose/subject_id), infers a single-dose IV bolus event if
    *dose* is supplied, then delegates to
    :func:`pkplugin.comp.fitting.fit_pk_model`.

    Returns a dict with:
      - status: "ok" | "error"
      - run_id, audit_path, fit_csv_path, script_path
      - parameters: {name -> {estimate, se, ci_low, ci_high}}
      - diagnostics: {aic, bic, rss, condition_number, converged, ...}
      - warnings

    Refs: docs/03-algorithms/08-compartmental-models.md §4–§6
    """
    from pkplugin.comp.models import REGISTRY
    from pkplugin.comp.fitting import (
        FitResult,
        WeightScheme,
        ResidualErrorModel,
        fit_pk_model as _fit_pk_model,
    )
    from pkplugin.comp.ode import DosingEvent

    # --- Validate model name first so we can return a clean error ---
    # H6: accept REGISTRY linear models + ODE-only MM models
    all_supported = _all_supported_models()
    if model_name not in all_supported:
        return {
            "status": "error",
            "error": (
                f"Unknown model: {model_name!r}. "
                f"Available: {sorted(all_supported)}"
            ),
        }

    # --- Validate dataset path ---
    ds_path = Path(dataset_path).resolve()
    if not ds_path.is_file():
        return {"status": "error", "error": f"Dataset not found: {ds_path}"}

    # --- Load dataset ---
    try:
        df = pd.read_csv(ds_path)
    except Exception as exc:
        return {"status": "error", "error": f"Failed to read CSV: {exc}"}

    required_cols = {"time", "concentration"}
    missing = required_cols - set(df.columns)
    if missing:
        return {
            "status": "error",
            "error": f"Missing required columns: {sorted(missing)}",
        }

    import numpy as np

    # Use first subject if subject_id column is present, otherwise treat all rows
    if "subject_id" in df.columns:
        subject_ids = df["subject_id"].unique()
        sub_df = df[df["subject_id"] == subject_ids[0]].copy()
    else:
        sub_df = df.copy()

    sub_df = sub_df.dropna(subset=["time", "concentration"])
    times_arr = np.asarray(sub_df["time"].tolist(), dtype=np.float64)
    conc_arr = np.asarray(sub_df["concentration"].tolist(), dtype=np.float64)

    # --- Build dosing events ---
    ev_list: list[DosingEvent] | None = None
    dose_path_resolved: Path | None = None

    if dose_path is not None:
        dose_path_resolved = Path(dose_path).resolve()
        if not dose_path_resolved.is_file():
            return {
                "status": "error",
                "error": f"Dose file not found: {dose_path_resolved}",
            }
        try:
            # H7/M3: use helper that filters by subject_id when present
            subject_id_val = str(subject_ids[0]) if "subject_id" in df.columns else None
            ev_list = _parse_dose_csv(dose_path_resolved, subject_id=subject_id_val)
        except Exception as exc:
            return {"status": "error", "error": f"Failed to read dose CSV: {exc}"}
    elif dose is None and "dose" in sub_df.columns:
        dose_vals = sub_df["dose"].dropna()
        if not dose_vals.empty:
            dose = float(dose_vals.iloc[0])

    # Validate weighting / residual_error literals before passing
    _valid_weightings = {
        "uniform",
        "1_over_y",
        "1_over_y_squared",
        "1_over_pred",
        "1_over_pred_squared",
    }
    _valid_residual = {"additive", "proportional", "combined"}
    if weighting not in _valid_weightings:
        return {
            "status": "error",
            "error": (
                f"Invalid weighting {weighting!r}. "
                f"Choose from: {sorted(_valid_weightings)}"
            ),
        }
    if residual_error not in _valid_residual:
        return {
            "status": "error",
            "error": (
                f"Invalid residual_error {residual_error!r}. "
                f"Choose from: {sorted(_valid_residual)}"
            ),
        }

    # --- Run fit ---
    try:
        fit: FitResult = _fit_pk_model(
            times=times_arr,
            observed=conc_arr,
            model_name=model_name,
            initial_params=initial_params,
            dose=dose,
            dosing_events=ev_list,
            weighting=weighting,  # type: ignore[arg-type]
            residual_error=residual_error,  # type: ignore[arg-type]
            use_ode=use_ode,
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    # --- Build parameter summary ---
    # H6: MM-only models are not in REGISTRY; use None for winnonlin_model_id
    spec = REGISTRY.get(model_name)
    parameters: dict[str, dict[str, Any]] = {}
    for pname, est in fit.parameters.items():
        se = fit.standard_errors.get(pname)
        ci = fit.confidence_intervals.get(pname)
        parameters[pname] = {
            "estimate": _serialise_for_json(est),
            "se": _serialise_for_json(se),
            "ci_low": _serialise_for_json(ci[0] if ci else None),
            "ci_high": _serialise_for_json(ci[1] if ci else None),
        }

    diagnostics: dict[str, Any] = {
        "aic": _serialise_for_json(fit.diagnostics.aic),
        "bic": _serialise_for_json(fit.diagnostics.bic),
        "rss": _serialise_for_json(fit.diagnostics.rss),
        "n_obs": fit.diagnostics.n_obs,
        "n_params_estimated": fit.diagnostics.n_params_estimated,
        "condition_number": _serialise_for_json(fit.diagnostics.condition_number),
        "converged": fit.diagnostics.converged,
        "method": fit.diagnostics.method,
    }

    # --- Audit ---
    input_paths: list[str | Path] = [ds_path]
    if dose_path_resolved is not None:
        input_paths.append(dose_path_resolved)

    entry: AuditEntry = new_entry(
        tool="fit_pk_model",
        config={
            "model_name": model_name,
            "initial_params": initial_params,
            "dose": dose,
            "weighting": weighting,
            "residual_error": residual_error,
            "use_ode": use_ode,
            "winnonlin_version": winnonlin_version,
            "winnonlin_model_id": spec.winnonlin_model_id if spec is not None else None,
        },
        input_paths=input_paths,
        winnonlin_compat=winnonlin_version,
    )
    run_id = entry.run_id

    audit_base = Path(audit_dir) if audit_dir else audit_dir_default()
    run_dir = audit_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Write fit_result.csv
    fit_rows: list[dict[str, Any]] = []
    for pname, pinfo in parameters.items():
        fit_rows.append(
            {
                "run_id": run_id,
                "model": model_name,
                "parameter": pname,
                "estimate": pinfo["estimate"],
                "se": pinfo["se"],
                "ci_low": pinfo["ci_low"],
                "ci_high": pinfo["ci_high"],
            }
        )
    fit_csv_path = run_dir / "fit_result.csv"
    pd.DataFrame(fit_rows).to_csv(fit_csv_path, index=False)

    # Write reproducible script
    script_path = run_dir / "fit_script.py"
    script_path.write_text(
        _render_fit_script(ds_path, dose_path_resolved, model_name, initial_params, dose, weighting, residual_error, use_ode, winnonlin_version)
    )

    _wn_model_id = spec.winnonlin_model_id if spec is not None else None
    entry.results = {
        "model_name": model_name,
        "winnonlin_model_id": _wn_model_id,
        "parameters": parameters,
        "diagnostics": diagnostics,
        "n_subjects_fitted": 1,
    }
    entry.warnings = fit.warnings
    entry.artifacts = [
        {
            "name": "fit_result.csv",
            "path": str(fit_csv_path),
            "sha256": file_sha256(fit_csv_path),
        },
        {
            "name": "fit_script.py",
            "path": str(script_path),
            "sha256": file_sha256(script_path),
        },
    ]
    audit_json_path = entry.write(audit_base)

    # Part 11 chain emission
    _emit_chain_entry(
        run_dir=run_dir,
        action="fit_pk_model",
        user=None,
        reason="PK model fitting run",
        run_id=run_id,
        after={"run_state": "draft", "model_name": model_name},
    )

    return {
        "status": "ok",
        "run_id": run_id,
        "audit_path": str(audit_json_path),
        "fit_csv_path": str(fit_csv_path),
        "script_path": str(script_path),
        "model_name": model_name,
        "winnonlin_model_id": _wn_model_id,
        "parameters": parameters,
        "diagnostics": diagnostics,
        "warnings": fit.warnings,
    }


def _render_fit_script(
    dataset: Path,
    dose_path: Path | None,
    model_name: str,
    initial_params: dict[str, float],
    dose: float | None,
    weighting: str,
    residual_error: str,
    use_ode: bool,
    winnonlin_version: str,
) -> str:
    """Render a reproducible Python script for the fit."""
    dose_block = (
        f"    dose={dose!r},"
        if dose is not None and dose_path is None
        else "    dosing_events=dosing_events,"
    )
    dose_load_block = ""
    if dose_path is not None:
        # M3: generated script uses _parse_dose_csv helper for subject filtering
        # and infusion_duration support — matches impl_fit_pk_model behaviour.
        dose_load_block = (
            f"from pkplugin.mcp_server import _parse_dose_csv\n"
            f"dosing_events = _parse_dose_csv(\n"
            f"    Path({str(dose_path)!r}),\n"
            f"    subject_id=str(df['subject_id'].iloc[0]) if 'subject_id' in df.columns else None,\n"
            f")\n"
        )
    return (
        f"# Auto-generated reproducible PK fit script\n"
        f"# pk-copilot {PKPLUGIN_VERSION}  |  WinNonlin compat {winnonlin_version}\n"
        f"from pathlib import Path\n"
        f"import numpy as np\n"
        f"import pandas as pd\n"
        f"from pkplugin.comp.fitting import fit_pk_model\n"
        f"\n"
        f"df = pd.read_csv(Path({str(dataset)!r}))\n"
        f"times = np.asarray(df['time'].tolist(), dtype=np.float64)\n"
        f"conc  = np.asarray(df['concentration'].tolist(), dtype=np.float64)\n"
        f"{dose_load_block}\n"
        f"result = fit_pk_model(\n"
        f"    times=times,\n"
        f"    observed=conc,\n"
        f"    model_name={model_name!r},\n"
        f"    initial_params={initial_params!r},\n"
        f"    {dose_block}\n"
        f"    weighting={weighting!r},\n"
        f"    residual_error={residual_error!r},\n"
        f"    use_ode={use_ode!r},\n"
        f")\n"
        f"print('Parameters:', result.parameters)\n"
        f"print('AIC:', result.diagnostics.aic)\n"
        f"print('BIC:', result.diagnostics.bic)\n"
        f"print('Converged:', result.diagnostics.converged)\n"
    )


def impl_list_pd_models() -> dict[str, Any]:
    """Return all available PD model names and their parameter lists.

    Refs: docs/03-algorithms/09-pkpd-models.md §1
    """
    from pkplugin.pd.models import PD_REGISTRY

    models: list[dict[str, Any]] = []
    for name, spec in PD_REGISTRY.items():
        models.append(
            {
                "name": spec.name,
                "model_type": spec.model_type.value,
                "parameter_names": list(spec.parameter_names),
                "requires_ode": spec.requires_ode,
                "is_inhibitory": spec.is_inhibitory,
            }
        )
    return {
        "status": "ok",
        "models": models,
        "n_models": len(models),
    }


def impl_simulate_pd_model(
    model_name: str,
    params: dict[str, float],
    times: list[float],
    concentrations: list[float],
) -> dict[str, Any]:
    """Forward simulation returning predicted effects.

    Args:
        model_name: Canonical PD model code.
        params: Parameter dict.
        times: Observation times.
        concentrations: Plasma concentrations at *times*.

    Returns:
        dict with status, model_name, times, effects.

    Refs: docs/03-algorithms/09-pkpd-models.md §1
    """
    from pkplugin.pd.models import PD_REGISTRY

    if model_name not in PD_REGISTRY:
        return {
            "status": "error",
            "error": (
                f"Unknown PD model: {model_name!r}. "
                f"Available: {sorted(PD_REGISTRY)}"
            ),
        }

    import numpy as np
    from pkplugin.pd.predict import predict_pd

    try:
        t_arr = np.asarray(times, dtype=np.float64)
        c_arr = np.asarray(concentrations, dtype=np.float64)
        effects = predict_pd(model_name, params, c_arr, t_arr)
        return {
            "status": "ok",
            "model_name": model_name,
            "times": _serialise_for_json(list(times)),
            "effects": _serialise_for_json(effects.tolist()),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def impl_fit_pd_model(
    pd_dataset_path: str,
    model_name: str,
    initial_params: dict[str, float],
    mode: str = "sequential",
    weighting: str = "uniform",
    winnonlin_version: str = "6.4",
    audit_dir: str | None = None,
) -> dict[str, Any]:
    """Fit a PD model to effect-time data and emit audit.

    Loads a CSV with columns ``time``, ``concentration``, ``effect``.
    Delegates fitting to :func:`pkplugin.pd.fitting.fit_pd_model`.

    Returns a dict with:
      - status: "ok" | "error"
      - run_id, audit_path, fit_csv_path
      - parameters, diagnostics, warnings

    Refs: docs/03-algorithms/09-pkpd-models.md §2
    """
    from pkplugin.pd.models import PD_REGISTRY
    from pkplugin.pd.fitting import fit_pd_model as _fit_pd_model, PDFitResult

    if model_name not in PD_REGISTRY:
        return {
            "status": "error",
            "error": (
                f"Unknown PD model: {model_name!r}. "
                f"Available: {sorted(PD_REGISTRY)}"
            ),
        }

    ds_path = Path(pd_dataset_path).resolve()
    if not ds_path.is_file():
        return {"status": "error", "error": f"Dataset not found: {ds_path}"}

    try:
        df = pd.read_csv(ds_path)
    except Exception as exc:
        return {"status": "error", "error": f"Failed to read CSV: {exc}"}

    required_cols = {"time", "concentration", "effect"}
    missing = required_cols - set(df.columns)
    if missing:
        return {
            "status": "error",
            "error": f"Missing required columns: {sorted(missing)}",
        }

    import numpy as np

    df = df.dropna(subset=["time", "concentration", "effect"])
    times_arr = np.asarray(df["time"].tolist(), dtype=np.float64)
    conc_arr = np.asarray(df["concentration"].tolist(), dtype=np.float64)
    effect_arr = np.asarray(df["effect"].tolist(), dtype=np.float64)

    _valid_modes = {"sequential", "simultaneous"}
    if mode not in _valid_modes:
        return {
            "status": "error",
            "error": f"Invalid mode {mode!r}. Choose from: {sorted(_valid_modes)}",
        }

    try:
        fit: PDFitResult = _fit_pd_model(
            times=times_arr,
            observed_effects=effect_arr,
            model_name=model_name,
            initial_params=initial_params,
            concentrations=conc_arr,
            mode=mode,  # type: ignore[arg-type]
            weighting=weighting,
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    parameters: dict[str, dict[str, Any]] = {}
    for pname, est in fit.parameters.items():
        se = fit.standard_errors.get(pname)
        ci = fit.confidence_intervals.get(pname)
        parameters[pname] = {
            "estimate": _serialise_for_json(est),
            "se": _serialise_for_json(se),
            "ci_low": _serialise_for_json(ci[0] if ci else None),
            "ci_high": _serialise_for_json(ci[1] if ci else None),
        }

    diagnostics: dict[str, Any] = {
        "aic": _serialise_for_json(fit.diagnostics.aic),
        "bic": _serialise_for_json(fit.diagnostics.bic),
        "rss": _serialise_for_json(fit.diagnostics.rss),
        "n_obs": fit.diagnostics.n_obs,
        "n_params_estimated": fit.diagnostics.n_params_estimated,
        "condition_number": _serialise_for_json(fit.diagnostics.condition_number),
        "converged": fit.diagnostics.converged,
        "method": fit.diagnostics.method,
    }

    entry: AuditEntry = new_entry(
        tool="fit_pd_model",
        config={
            "model_name": model_name,
            "initial_params": initial_params,
            "mode": mode,
            "weighting": weighting,
            "winnonlin_version": winnonlin_version,
        },
        input_paths=[ds_path],
        winnonlin_compat=winnonlin_version,
    )
    run_id = entry.run_id

    audit_base = Path(audit_dir) if audit_dir else audit_dir_default()
    run_dir = audit_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    fit_rows: list[dict[str, Any]] = []
    for pname, pinfo in parameters.items():
        fit_rows.append(
            {
                "run_id": run_id,
                "model": model_name,
                "parameter": pname,
                "estimate": pinfo["estimate"],
                "se": pinfo["se"],
                "ci_low": pinfo["ci_low"],
                "ci_high": pinfo["ci_high"],
            }
        )
    fit_csv_path = run_dir / "pd_fit_result.csv"
    pd.DataFrame(fit_rows).to_csv(fit_csv_path, index=False)

    entry.results = {
        "model_name": model_name,
        "parameters": parameters,
        "diagnostics": diagnostics,
    }
    entry.warnings = fit.warnings
    entry.artifacts = [
        {
            "name": "pd_fit_result.csv",
            "path": str(fit_csv_path),
            "sha256": file_sha256(fit_csv_path),
        }
    ]
    audit_json_path = entry.write(audit_base)

    # Part 11 chain emission
    _emit_chain_entry(
        run_dir=run_dir,
        action="fit_pd_model",
        user=None,
        reason="PD model fitting run",
        run_id=run_id,
        after={"run_state": "draft", "model_name": model_name},
    )

    return {
        "status": "ok",
        "run_id": run_id,
        "audit_path": str(audit_json_path),
        "fit_csv_path": str(fit_csv_path),
        "model_name": model_name,
        "parameters": parameters,
        "diagnostics": diagnostics,
        "warnings": fit.warnings,
    }


def impl_generate_report(
    run_id: str,
    format: str = "html",
    audit_dir: str | None = None,
) -> dict[str, Any]:
    """Generate a report from an existing audit run.

    Reloads the run from ``<audit_dir>/<run_id>/audit.json`` +
    ``parameters.csv`` and renders via the appropriate report.* function.

    Args:
        run_id: The run ID of a previous ``run_nca`` or ``run_be`` invocation.
        format: Output format — ``"html"`` or ``"pdf"``.
        audit_dir: Override for the audit base directory.

    Returns:
        dict with status, run_id, report_path on success.
    """
    if format not in ("html", "pdf"):
        return {
            "status": "error",
            "error": f"Invalid format {format!r}. Choose 'html' or 'pdf'.",
        }

    audit_base = Path(audit_dir) if audit_dir else audit_dir_default()
    run_dir = audit_base / run_id

    audit_json = run_dir / "audit.json"
    if not audit_json.is_file():
        return {
            "status": "error",
            "error": f"audit.json not found for run_id={run_id!r}: {audit_json}",
        }

    try:
        with open(audit_json) as fh:
            audit_data = json.load(fh)
    except Exception as exc:
        return {"status": "error", "error": f"Failed to read audit.json: {exc}"}

    tool = audit_data.get("tool", "")
    ext = format
    report_path = run_dir / f"report.{ext}"

    try:
        if tool == "run_nca":
            # Reload NCA results from parameters.csv by re-running NCA
            # (lightweight: reconstruct NCAResult list from audit data)
            params_csv = run_dir / "parameters.csv"
            if not params_csv.is_file():
                return {
                    "status": "error",
                    "error": f"parameters.csv not found for run_id={run_id!r}",
                }

            # Extract input dataset path from audit
            input_files = audit_data.get("input_files", [])
            if not input_files:
                return {
                    "status": "error",
                    "error": "No input_files recorded in audit.json",
                }
            dataset_path = input_files[0].get("path", "")
            cfg_dict = audit_data.get("config", {})

            nca_result_dict = impl_run_nca(
                dataset_path=dataset_path,
                config=cfg_dict,
                audit_dir=str(audit_base),
            )
            if nca_result_dict.get("status") != "ok":
                return {
                    "status": "error",
                    "error": f"Failed to re-run NCA: {nca_result_dict.get('error')}",
                }

            # For HTML report, build from the CSV directly via render_html_report
            from pkplugin.report.html import render_html_report
            from pkplugin.report.pdf import render_pdf_report

            df = pd.read_csv(params_csv)
            # Build param table HTML inline
            headers = "".join(f"<th>{c}</th>" for c in df.columns)
            rows_html = ""
            for _, row in df.iterrows():
                cells = "".join(
                    f"<td>{'' if (v is None or (isinstance(v, float) and v != v)) else v}</td>"
                    for v in row
                )
                rows_html += f"<tr>{cells}</tr>"
            param_table_html = f"<table><thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>"

            sections: list[dict[str, Any]] = [
                {
                    "heading": "NCA Parameter Table",
                    "content_html": param_table_html,
                    "plot_paths": [],
                }
            ]
            metadata_report: dict[str, str] = {
                "run_id": run_id,
                "plugin_version": PKPLUGIN_VERSION,
                "winnonlin_compat": str(cfg_dict.get("winnonlin_version", "6.4")),
                "timestamp": audit_data.get("run_timestamp_utc", ""),
            }
            if format == "html":
                render_html_report(
                    title=f"NCA Report — Run {run_id}",
                    metadata=metadata_report,
                    sections=sections,
                    output_path=report_path,
                )
            else:
                render_pdf_report(
                    title=f"NCA Report — Run {run_id}",
                    sections=sections,
                    output_path=report_path,
                    metadata=metadata_report,
                )

        elif tool == "run_be":
            # Reload BE result from audit JSON results field
            be_data = audit_data.get("results", {})
            if not be_data:
                return {
                    "status": "error",
                    "error": "No results in audit.json for BE run",
                }

            from pkplugin.report.html import render_html_report
            from pkplugin.report.pdf import render_pdf_report

            # Build a simple BE summary directly from audit data
            gmr = be_data.get("gmr_pct")
            ci_low = be_data.get("ci_90_low_pct")
            ci_high = be_data.get("ci_90_high_pct")
            be_demo = be_data.get("be_demonstrated")
            be_window = be_data.get("be_window", [80.0, 125.0])

            if be_demo is True:
                verdict = f"BIOEQUIVALENCE DEMONSTRATED — GMR: {gmr:.4f}% (90% CI: {ci_low:.4f}%–{ci_high:.4f}%) within [{be_window[0]:.2f}%, {be_window[1]:.2f}%]"
                verdict_class = "verdict-pass"
            elif be_demo is False:
                verdict = f"BIOEQUIVALENCE NOT DEMONSTRATED — GMR: {gmr:.4f}% (90% CI: {ci_low:.4f}%–{ci_high:.4f}%)"
                verdict_class = "verdict-fail"
            else:
                verdict = "BE CONCLUSION UNAVAILABLE"
                verdict_class = "verdict-na"

            verdict_html = f'<div class="{verdict_class}">{verdict}</div>'

            sections_be: list[dict[str, Any]] = [
                {
                    "heading": "Bioequivalence Verdict",
                    "content_html": verdict_html,
                    "plot_paths": [],
                },
                {
                    "heading": "BE Summary",
                    "content_html": f"<pre>{json.dumps(be_data, indent=2)}</pre>",
                    "plot_paths": [],
                },
            ]
            cfg_dict = audit_data.get("config", {})
            metadata_report_be: dict[str, str] = {
                "run_id": run_id,
                "plugin_version": PKPLUGIN_VERSION,
                "endpoint": str(be_data.get("endpoint", "")),
                "design": str(be_data.get("design", "")),
                "timestamp": str(audit_data.get("run_timestamp_utc", "")),
            }
            if format == "html":
                render_html_report(
                    title=f"BE Report — Run {run_id}",
                    metadata=metadata_report_be,
                    sections=sections_be,
                    output_path=report_path,
                )
            else:
                render_pdf_report(
                    title=f"BE Report — Run {run_id}",
                    sections=sections_be,
                    output_path=report_path,
                    metadata=metadata_report_be,
                )
        else:
            return {
                "status": "error",
                "error": f"Unsupported tool {tool!r} for report generation. Supported: run_nca, run_be.",
            }

    except ImportError as exc:
        return {"status": "error", "error": str(exc)}
    except Exception as exc:
        return {"status": "error", "error": f"Report generation failed: {exc}"}

    return {
        "status": "ok",
        "run_id": run_id,
        "report_path": str(report_path),
        "format": format,
    }


def impl_get_winnonlin_versions() -> dict[str, Any]:
    """List supported WinNonlin versions + their default option matrix."""
    return {
        "versions": [v.value for v in WNVersion],
        "defaults": {
            v.value: _serialise_for_json(opts) for v, opts in DEFAULTS.items()
        },
    }


def impl_get_pkplugin_version() -> str:
    return PKPLUGIN_VERSION


def impl_r_backend_status() -> dict[str, Any]:
    """Expose check_r_backend() to the MCP layer.

    Returns a dict describing whether Rscript, PKNCA, and NonCompart are
    available on the host, along with version strings.

    Refs: docs/08-validation-strategy.md §4
    """
    from pkplugin.validation.r_backend import check_r_backend

    status = check_r_backend()
    return {
        "available": status.available,
        "rscript_path": status.rscript_path,
        "r_version": status.r_version,
        "pknca_version": status.pknca_version,
        "noncompart_version": status.noncompart_version,
        "error": status.error,
    }


def impl_compare_against_reference(
    run_id: str,
    reference_backend: str = "pknca",
    tolerance_relative: float = 1e-6,
    audit_dir: str | None = None,
) -> dict[str, Any]:
    """Compare a previous pk-copilot NCA run against PKNCA or NonCompart.

    Steps:
      1. Resolve <audit_dir>/<run_id>/ and load parameters.csv.
      2. Check R availability — return status="r_unavailable" if absent.
      3. Run scripts/run_r_pknca.R or run_r_noncompart.R via subprocess.
      4. Compute diff via compute_diff.
      5. Write validation_diff.json into the run directory.
      6. Return summary dict.

    Args:
        run_id: The NCA run ID whose parameters.csv we compare.
        reference_backend: "pknca" or "noncompart".
        tolerance_relative: Relative tolerance for within-tolerance check.
        audit_dir: Override for the audit base directory.

    Returns:
        dict with status, overall_passed, n_compared, n_outside_tolerance,
        diff_path, and (if any outside tolerance) outside_tolerance_diffs.

    Refs: docs/06-mcp-server.md §8, docs/08-validation-strategy.md §4
    """
    from pkplugin.validation.r_backend import (
        RBackendStatus,
        check_r_backend,
        run_r_noncompart,
        run_r_pknca,
    )
    from pkplugin.validation.diff import compute_diff, write_validation_diff_json

    backend_key = reference_backend.lower().strip()
    if backend_key not in ("pknca", "noncompart"):
        return {
            "status": "error",
            "error": (
                f"Unknown reference_backend {reference_backend!r}. "
                "Choose 'pknca' or 'noncompart'."
            ),
        }

    audit_base = Path(audit_dir) if audit_dir else audit_dir_default()
    run_dir = audit_base / run_id
    parameters_csv = run_dir / "parameters.csv"

    if not parameters_csv.is_file():
        return {
            "status": "error",
            "error": (
                f"parameters.csv not found for run_id={run_id!r}: {parameters_csv}"
            ),
        }

    # Step 2 — check R availability
    r_status: RBackendStatus = check_r_backend()
    if not r_status.available:
        return {
            "status": "r_unavailable",
            "available": False,
            "error": r_status.error,
            "rscript_path": r_status.rscript_path,
            "r_version": r_status.r_version,
            "pknca_version": r_status.pknca_version,
            "noncompart_version": r_status.noncompart_version,
        }

    # Step 3 — resolve original input dataset from audit.json
    # audit.json uses "input_files": [{"path": ..., "sha256": ...}, ...]
    dataset_csv_path: Path | None = None
    dose_csv_path: Path | None = None
    audit_json = run_dir / "audit.json"
    if audit_json.is_file():
        try:
            audit_data: dict[str, Any] = json.loads(audit_json.read_text())
            input_files: list[Any] = audit_data.get("input_files", [])
            for inp in input_files:
                if isinstance(inp, dict):
                    p = Path(inp.get("path", ""))
                else:
                    p = Path(str(inp))
                if p.suffix.lower() == ".csv" and p.is_file():
                    if dataset_csv_path is None:
                        dataset_csv_path = p
                    else:
                        dose_csv_path = p
        except Exception:
            pass

    if dataset_csv_path is None:
        return {
            "status": "error",
            "error": (
                f"Could not resolve input dataset for run_id={run_id!r}. "
                "Ensure audit.json contains an 'inputs' list with valid paths."
            ),
        }

    r_output_dir = run_dir / "r_validation"
    try:
        if backend_key == "pknca":
            r_result = run_r_pknca(
                dataset_csv=dataset_csv_path,
                dose_csv=dose_csv_path,
                output_dir=r_output_dir,
            )
            backend_label = "PKNCA"
        else:
            r_result = run_r_noncompart(
                dataset_csv=dataset_csv_path,
                dose_csv=dose_csv_path,
                output_dir=r_output_dir,
            )
            backend_label = "NonCompart"
    except Exception as exc:
        return {"status": "error", "error": f"R subprocess error: {exc}"}

    if r_result.return_code != 0:
        return {
            "status": "error",
            "error": (
                f"R script exited {r_result.return_code}. "
                f"stderr: {r_result.raw_stderr[:500]}"
            ),
        }

    if not r_result.parameter_table_csv.is_file():
        return {
            "status": "error",
            "error": "R script completed but output CSV was not created.",
        }

    diff = compute_diff(
        pkplugin_parameters_csv=parameters_csv,
        reference_parameters_csv=r_result.parameter_table_csv,
        tolerance_relative=tolerance_relative,
        r_status=r_status,
        reference_backend=backend_label,
        run_id=run_id,
    )

    diff_json_path = write_validation_diff_json(
        diff, run_dir / "validation_diff.json"
    )

    outside_diffs: list[dict[str, Any]] = [
        {
            "subject_id": d.subject_id,
            "parameter": d.parameter,
            "pkcopilot_value": d.pkcopilot_value,
            "reference_value": d.reference_value,
            "absolute_diff": d.absolute_diff,
            "relative_diff": d.relative_diff,
        }
        for d in diff.diffs
        if not d.within_tolerance and d.absolute_diff is not None
    ]

    return {
        "status": "ok",
        "run_id": run_id,
        "reference_backend": backend_label,
        "overall_passed": diff.overall_passed,
        "n_compared": diff.n_compared,
        "n_within_tolerance": diff.n_within_tolerance,
        "n_outside_tolerance": diff.n_outside_tolerance,
        "diff_path": str(diff_json_path),
        "outside_tolerance_diffs": outside_diffs,
    }


# ---------------------------------------------------------------------------
# CDISC SDTM / ADaM implementation functions (v2.0)
# ---------------------------------------------------------------------------


def impl_import_sdtm(
    pc_path: str,
    ex_path: str,
    dm_path: str | None = None,
    analyte: str | None = None,
    matrix: str | None = None,
    audit_dir: str | None = None,
) -> dict[str, Any]:
    """Import SDTM PC + EX + optional DM → canonical CSVs + audit.

    Returns a dict with keys: status, pc_csv, ex_csv, dm_csv (optional),
    warnings, n_subjects, n_pc_rows.
    """
    from pkplugin.cdisc.sdtm import load_sdtm_dm, load_sdtm_ex, load_sdtm_pc, normalise_pc_times

    pc_file = Path(pc_path).resolve()
    ex_file = Path(ex_path).resolve()
    if not pc_file.is_file():
        return {"status": "error", "error": f"PC file not found: {pc_file}"}
    if not ex_file.is_file():
        return {"status": "error", "error": f"EX file not found: {ex_file}"}

    try:
        pc_df, pc_warnings = load_sdtm_pc(pc_file, analyte_filter=analyte, matrix_filter=matrix)
        ex_df, ex_warnings = load_sdtm_ex(ex_file)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    # Normalise elapsed times using EX reference dates
    pc_df = normalise_pc_times(pc_df, ex_df)

    all_warnings = dict(pc_warnings)
    all_warnings.update(ex_warnings)

    # Write canonical CSVs to audit directory
    audit_base = Path(audit_dir) if audit_dir else audit_dir_default()
    run_id = new_run_id()
    run_dir = audit_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    pc_csv = run_dir / "sdtm_pc_canonical.csv"
    ex_csv = run_dir / "sdtm_ex_canonical.csv"
    pc_df.to_csv(pc_csv, index=False)
    ex_df.to_csv(ex_csv, index=False)

    result: dict[str, Any] = {
        "status": "ok",
        "run_id": run_id,
        "pc_csv": str(pc_csv),
        "ex_csv": str(ex_csv),
        "n_subjects": int(pc_df["subject_id"].nunique()) if not pc_df.empty else 0,
        "n_pc_rows": len(pc_df),
        "warnings": all_warnings,
    }

    if dm_path is not None:
        dm_file = Path(dm_path).resolve()
        if not dm_file.is_file():
            result["dm_warning"] = f"DM file not found: {dm_file}"
        else:
            try:
                dm_df = load_sdtm_dm(dm_file)
                dm_csv = run_dir / "sdtm_dm_canonical.csv"
                dm_df.to_csv(dm_csv, index=False)
                result["dm_csv"] = str(dm_csv)
                result["n_subjects_dm"] = len(dm_df)
            except Exception as exc:
                result["dm_warning"] = f"Failed to load DM: {exc}"

    return result


def impl_export_adam(
    nca_run_id: str,
    output_dir: str | None = None,
    include_define_xml: bool = True,
    audit_dir: str | None = None,
) -> dict[str, Any]:
    """Export ADPC + ADPP + optional define.xml from a previous NCA run.

    Loads the NCA parameters.csv from the run directory, reconstructs
    ADPP from saved parameter rows, and builds ADPC from the concentration
    file if present.
    """
    from pkplugin.cdisc.adam import build_adpp, write_adam_dataset
    from pkplugin.cdisc.define_xml import generate_define_xml
    from pkplugin.cdisc.paramcd import pkcopilot_to_paramcd
    from pkplugin.cdisc.validate import validate_adpp

    audit_base = Path(audit_dir) if audit_dir else audit_dir_default()
    run_dir = audit_base / nca_run_id
    params_csv = run_dir / "parameters.csv"

    if not params_csv.is_file():
        return {"status": "error", "error": f"NCA parameters.csv not found: {params_csv}"}

    try:
        params_df = pd.read_csv(params_csv)
    except Exception as exc:
        return {"status": "error", "error": f"Failed to read parameters.csv: {exc}"}

    out_dir = Path(output_dir).resolve() if output_dir else run_dir / "adam"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build minimal NCAResult-like objects from the saved parameter CSV
    # We reconstruct parameters dict per subject group
    from pkplugin.nca.engine import NCAResult
    from pkplugin.nca.auc import AUCResult
    from pkplugin.nca.lambda_z import LambdaZResult

    # Build per-subject parameter dicts
    nca_results: list[NCAResult] = []
    group_cols = [c for c in ("subject_id", "period", "treatment", "analyte") if c in params_df.columns]

    for group_key, group in params_df.groupby(group_cols, dropna=False):
        if isinstance(group_key, str):
            group_key = (group_key,)
        key_dict = dict(zip(group_cols, group_key))
        subject_id = str(key_dict.get("subject_id", "UNKNOWN"))
        period = str(key_dict.get("period", "")) if key_dict.get("period") else None
        treatment = str(key_dict.get("treatment", "")) if key_dict.get("treatment") else None
        analyte = str(key_dict.get("analyte", "parent"))

        params: dict[str, float | None] = {}
        for _, prow in group.iterrows():
            pname = str(prow.get("parameter", ""))
            pval = prow.get("value")
            params[pname] = float(pval) if pval is not None and not (isinstance(pval, float) and pd.isna(pval)) else None

        # Build a minimal NCAResult (only parameters and metadata needed for ADPP)
        dummy_auc = AUCResult(auc=0.0, aumc=0.0, method="linear_up_log_down", n_intervals=0)
        dummy_lz = LambdaZResult(
            lambda_z=None, intercept=None, half_life=None, r_squared=None,
            adjusted_r_squared=None, n_points=0, t_start=None, t_end=None,
            clast_pred=None, span_ratio=None, method="best_fit", warnings=[],
        )
        nr = NCAResult(
            subject_id=subject_id,
            period=period,
            treatment=treatment,
            analyte=analyte,
            parameters=params,
            parameter_rows=[],
            auc_result=dummy_auc,
            lambda_z_result=dummy_lz,
            bloq_decisions=[],
        )
        nca_results.append(nr)

    study_id = "STUDY001"
    adpp_df = build_adpp(nca_results, dm_df=None, study_id=study_id)
    adpp_path = write_adam_dataset(adpp_df, out_dir / "adpp.csv")

    validation_issues = validate_adpp(adpp_df)
    n_errors = sum(1 for i in validation_issues if i.get("severity") == "ERROR")

    result: dict[str, Any] = {
        "status": "ok",
        "adpp_path": str(adpp_path),
        "n_adpp_rows": len(adpp_df),
        "validation_issues": validation_issues,
        "n_validation_errors": n_errors,
        # M3: ADPC export is deferred — be explicit rather than silently skipping
        "adpc_status": "not_implemented_v2_0",
        "adpc_note": (
            "ADaM ADPC export deferred to v2.1; "
            "impl_export_adam currently writes ADPP only."
        ),
    }

    # Collect PARAMCDs used
    paramcds_used: list[str] = []
    if "PARAMCD" in adpp_df.columns:
        paramcds_used = sorted(adpp_df["PARAMCD"].dropna().unique().tolist())

    if include_define_xml:
        try:
            define_path = generate_define_xml(
                study_id=study_id,
                domains=["ADPP"],
                paramcds_used=paramcds_used,
                output_path=out_dir / "define.xml",
            )
            result["define_xml_path"] = str(define_path)
        except Exception as exc:
            result["define_xml_warning"] = f"define.xml generation failed: {exc}"

    return result


def impl_validate_cdisc(
    dataset_path: str,
    domain: str,
) -> dict[str, Any]:
    """Run Pinnacle21-style validation checks on an ADaM dataset.

    Args:
        dataset_path: Path to ADPC or ADPP CSV file.
        domain: ``"ADPC"`` or ``"ADPP"``.

    Returns:
        Dict with keys: status, issues, n_errors, n_warnings.
    """
    from pkplugin.cdisc.validate import validate_adpc, validate_adpp

    domain_upper = domain.strip().upper()
    if domain_upper not in ("ADPC", "ADPP"):
        return {
            "status": "error",
            "error": f"Unsupported domain {domain!r}. Expected 'ADPC' or 'ADPP'.",
        }

    ds_path = Path(dataset_path).resolve()
    if not ds_path.is_file():
        return {"status": "error", "error": f"Dataset file not found: {ds_path}"}

    try:
        df = pd.read_csv(ds_path)
    except Exception as exc:
        return {"status": "error", "error": f"Failed to read dataset: {exc}"}

    if domain_upper == "ADPC":
        issues = validate_adpc(df)
    else:
        issues = validate_adpp(df)

    n_errors = sum(1 for i in issues if i.get("severity") == "ERROR")
    n_warnings = sum(1 for i in issues if i.get("severity") == "WARNING")

    return {
        "status": "ok",
        "domain": domain_upper,
        "n_rows": len(df),
        "issues": issues,
        "n_errors": n_errors,
        "n_warnings": n_warnings,
        "passed": n_errors == 0,
    }


# ---------------------------------------------------------------------------
# 21 CFR Part 11 compliance implementation functions
# ---------------------------------------------------------------------------


def impl_sign_record(
    run_id: str,
    signer_identity: str,
    meaning: str,
    auth_token: str,
    private_key_path: str,
    passphrase: str | None = None,
    audit_dir: str | None = None,
) -> dict[str, Any]:
    """Sign a run bundle with an Ed25519 key and record the event in the audit chain.

    Args:
        run_id: ID of the run to sign.
        signer_identity: Signer identifier (e.g. email).
        meaning: 'authored' | 'reviewed' | 'approved'.
        auth_token: Re-authentication token (TOTP placeholder for v2.0).
        private_key_path: Path to Ed25519 private key PEM file.
        passphrase: Key passphrase if encrypted.
        audit_dir: Base audit directory (default: PKPLUGIN_AUDIT_DIR or pk_runs/).
    """
    try:
        from pkplugin.compliance.signatures import SignatureMeaning, sign_run
        from pkplugin.compliance.audit_chain import AuditChain
    except ImportError as exc:
        return {"status": "error", "error": f"compliance module unavailable: {exc}"}

    valid_meanings = {"authored", "reviewed", "approved", "rejected"}
    if meaning not in valid_meanings:
        return {
            "status": "error",
            "error": f"Invalid meaning {meaning!r}. Must be one of: {sorted(valid_meanings)}",
        }

    # H3: auth_token is required — reject empty/None before any signing attempt.
    # INTEGRATION NOTE: This is a CALLBACK placeholder for production TOTP/FIDO
    # integration.  The MCP server does NOT validate the token cryptographically —
    # that is the caller's responsibility (e.g. via mTLS transport or a validated
    # session token from the authentication provider).  The contract is: callers
    # MUST supply a non-empty string representing a successfully-validated session
    # token.  The response field ``auth_token_verified: "caller_attestation"``
    # makes this caller-attested nature explicit.
    if not auth_token or not auth_token.strip():
        return {"status": "error", "error": "auth_token required"}

    audit_base = Path(audit_dir) if audit_dir else audit_dir_default()
    run_dir = audit_base / run_id

    if not run_dir.is_dir():
        return {"status": "error", "error": f"Run directory not found: {run_dir}"}

    key_path = Path(private_key_path)
    if not key_path.is_file():
        return {"status": "error", "error": f"Private key not found: {key_path}"}

    passphrase_bytes = passphrase.encode() if passphrase else None

    try:
        sig = sign_run(
            run_dir=run_dir,
            signer_id=signer_identity,
            meaning=meaning,  # type: ignore[arg-type]
            private_key_path=key_path,
            passphrase=passphrase_bytes,
            require_reauth_token=auth_token,
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    # Emit chain entry
    try:
        chain = AuditChain.open(run_dir)
        chain.append(
            action="sign_record",
            user={"id": signer_identity, "auth_method": "totp+ed25519"},
            reason=f"Signed as {meaning!r}",
            run_id=run_id,
            before=None,
            after={"meaning": meaning, "run_hash": sig.run_hash},
        )
    except Exception:
        pass  # chain emission is best-effort; signature already written

    return {
        "status": "ok",
        "auth_token_verified": "caller_attestation",
        "run_id": run_id,
        "signer_id": sig.signer_id,
        "meaning": sig.meaning,
        "timestamp_utc": sig.timestamp_utc,
        "run_hash": sig.run_hash,
        "public_key_hex": sig.public_key_hex[:16] + "...",
    }


def impl_lock_run(
    run_id: str,
    locked_by: str,
    lock_reason: str,
    require_signatures: list[str] | None = None,
    audit_dir: str | None = None,
) -> dict[str, Any]:
    """Finalize a run bundle: verify signatures, compute hash, set read-only.

    Args:
        run_id: ID of the run to lock.
        locked_by: Identifier of who is locking.
        lock_reason: Non-empty reason string.
        require_signatures: Signature meanings required (default: authored, reviewed, approved).
        audit_dir: Base audit directory.
    """
    try:
        from pkplugin.compliance.retention import lock_run
        from pkplugin.compliance.signatures import SignatureMeaning as _SM
        from pkplugin.compliance.audit_chain import AuditChain
    except ImportError as exc:
        return {"status": "error", "error": f"compliance module unavailable: {exc}"}

    audit_base = Path(audit_dir) if audit_dir else audit_dir_default()
    run_dir = audit_base / run_id

    if not run_dir.is_dir():
        return {"status": "error", "error": f"Run directory not found: {run_dir}"}

    req_sigs: list[_SM] | None = None
    if require_signatures is not None:
        from typing import cast as _cast
        _valid: set[str] = {"authored", "reviewed", "approved", "rejected"}
        req_sigs = _cast(list[_SM], [s for s in require_signatures if s in _valid])

    # H4: Audit chain entry MUST be appended BEFORE files become read-only so
    # the chain JSONL is still writable.  If the chain append fails, abort the
    # entire lock operation — do not proceed to retention.lock_run().
    try:
        chain = AuditChain.open(run_dir)
        chain.append(
            action="lock_run",
            user={"id": locked_by, "auth_method": "admin"},
            reason=lock_reason,
            run_id=run_id,
            before={"locked": False},
            after={"locked": True},
        )
    except Exception as exc:
        return {"status": "error", "error": f"Audit chain append failed — lock aborted: {exc}"}

    try:
        manifest = lock_run(
            run_dir=run_dir,
            locked_by=locked_by,
            lock_reason=lock_reason,
            require_signatures=req_sigs,
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "run_id": run_id,
        "locked_at_utc": manifest.locked_at_utc,
        "locked_by": manifest.locked_by,
        "bundle_sha256": manifest.bundle_sha256,
        "signatures_required": manifest.signatures_required,
    }


def impl_verify_audit_chain(
    chain_dir: str | None = None,
) -> dict[str, Any]:
    """Verify audit chain integrity.

    Returns:
        Dict with keys: ok, n_entries, violations.
    """
    try:
        from pkplugin.compliance.audit_chain import AuditChain
    except ImportError as exc:
        return {"status": "error", "error": f"compliance module unavailable: {exc}"}

    target = Path(chain_dir) if chain_dir else audit_dir_default()

    try:
        chain = AuditChain.open(target)
        ok, violations = chain.verify()
        n_entries = chain.length()
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "ok": ok,
        "n_entries": n_entries,
        "violations": violations,
    }


def impl_verify_signatures(
    run_id: str,
    audit_dir: str | None = None,
) -> dict[str, Any]:
    """Verify all electronic signatures for a run.

    Returns:
        Dict with keys: ok, n_signatures, failures.
    """
    try:
        from pkplugin.compliance.signatures import verify_all_signatures, load_signatures
    except ImportError as exc:
        return {"status": "error", "error": f"compliance module unavailable: {exc}"}

    audit_base = Path(audit_dir) if audit_dir else audit_dir_default()
    run_dir = audit_base / run_id

    if not run_dir.is_dir():
        return {"status": "error", "error": f"Run directory not found: {run_dir}"}

    try:
        ok, failures = verify_all_signatures(run_dir)
        sigs = load_signatures(run_dir)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "run_id": run_id,
        "ok": ok,
        "n_signatures": len(sigs),
        "signatures": [
            {
                "signer_id": s.signer_id,
                "meaning": s.meaning,
                "timestamp_utc": s.timestamp_utc,
            }
            for s in sigs
        ],
        "failures": failures,
    }


def impl_get_compliance_status() -> dict[str, Any]:
    """Return v2.0 Part 11 control status.

    Returns:
        Dict describing which technical controls are available.
    """
    status: dict[str, Any] = {
        "pkplugin_version": PKPLUGIN_VERSION,
        "part11_version": "v2.0",
    }

    # Check cryptography availability
    try:
        import cryptography
        status["cryptography_available"] = True
        status["cryptography_version"] = cryptography.__version__
    except ImportError:
        status["cryptography_available"] = False
        status["cryptography_version"] = None

    # Check compliance sub-package
    try:
        from pkplugin.compliance import audit_chain, signatures, access, retention  # noqa: F401
        status["compliance_module_available"] = True
    except ImportError as exc:
        status["compliance_module_available"] = False
        status["compliance_module_error"] = str(exc)

    # Check env flag
    part11_enabled = os.environ.get("PKPLUGIN_PART11_ENABLED", "0") == "1"
    status["part11_enabled"] = part11_enabled

    # Check default chain dir
    default_chain = audit_dir_default()
    status["default_audit_dir"] = str(default_chain)
    status["audit_dir_exists"] = default_chain.exists()

    # Technical controls summary
    status["controls"] = {
        "audit_trail": {
            "description": "Append-only HMAC hash-chained JSONL audit log",
            "regulation": "§11.10(e)",
            "available": status.get("compliance_module_available", False),
        },
        "electronic_signatures": {
            "description": "Ed25519 detached signatures with two-factor auth placeholder",
            "regulation": "§11.50, §11.70, §11.200",
            "available": status.get("cryptography_available", False),
        },
        "access_control": {
            "description": "RBAC (Viewer/Analyst/Approver/Admin) with session expiry",
            "regulation": "§11.10(d), §11.10(g)",
            "available": status.get("compliance_module_available", False),
        },
        "record_retention": {
            "description": "WORM-friendly bundle finalization with read-only enforcement",
            "regulation": "§11.10(c)",
            "available": status.get("compliance_module_available", False),
        },
    }

    disclaimer = (
        "pk-copilot v2.0 provides technical controls to support Part 11 workflows. "
        "21 CFR Part 11 compliance requires procedural controls by your organization. "
        "See docs/10-21cfr-part11.md §16 for the full disclaimer."
    )
    status["disclaimer"] = disclaimer

    return status


# ---------------------------------------------------------------------------
# fastmcp wrapper (only imported when actually running as MCP server)
# ---------------------------------------------------------------------------


def _build_mcp() -> Any:
    try:
        from fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError(
            "fastmcp is not installed. Install with: pip install fastmcp"
        ) from exc

    mcp = FastMCP("pk-kernel")

    @mcp.tool
    def validate_dataset(
        input_file: str,
        schema_type: str = "auto",
        column_mapping: dict[str, str] | None = None,
        units: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Inspect a concentration dataset (mapping, units, BLOQ patterns)."""
        return impl_validate_dataset(input_file, schema_type, column_mapping, units)

    @mcp.tool
    def run_nca(
        dataset_path: str,
        config: dict[str, Any] | None = None,
        dose_path: str | None = None,
        subjects: list[str] | None = None,
        analytes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run NCA analysis + emit audit + reproducible script."""
        return impl_run_nca(dataset_path, config, dose_path, subjects, analytes)

    @mcp.tool
    def run_be(
        parameter_dataset_path: str,
        endpoint: str = "AUC0_t",
        design: str = "crossover_2x2",
        test_label: str | None = None,
        reference_label: str | None = None,
        be_window_low: float = 80.0,
        be_window_high: float = 125.0,
        winnonlin_version: str = "6.4",
        audit_dir: str | None = None,
    ) -> dict[str, Any]:
        """Run bioequivalence analysis + emit audit."""
        return impl_run_be(
            parameter_dataset_path,
            endpoint,
            design,
            test_label,
            reference_label,
            be_window_low,
            be_window_high,
            winnonlin_version,
            audit_dir,
        )

    @mcp.tool
    def summarize_nca(
        nca_run_id: str | None = None,
        parameter_dataset_path: str | None = None,
        group_by: list[str] | None = None,
        parameters: list[str] | None = None,
        audit_dir: str | None = None,
    ) -> dict[str, Any]:
        """Descriptive statistics across NCA results."""
        return impl_summarize_nca(
            nca_run_id,
            parameter_dataset_path,
            group_by,
            parameters,
            audit_dir,
        )

    @mcp.tool
    def get_winnonlin_versions() -> dict[str, Any]:
        """List supported WinNonlin compatibility versions."""
        return impl_get_winnonlin_versions()

    @mcp.tool
    def get_pkplugin_version() -> str:
        """Return installed pk-copilot version."""
        return impl_get_pkplugin_version()

    @mcp.tool
    def list_pk_models() -> dict[str, Any]:
        """Return all available PK compartmental model names, WinNonlin numbers, and parameters."""
        return impl_list_pk_models()

    @mcp.tool
    def simulate_pk_model(
        model_name: str,
        params: dict[str, float],
        dose: float,
        times: list[float],
        infusion_duration: float | None = None,
        tlag: float = 0.0,
        F: float = 1.0,
    ) -> dict[str, Any]:
        """Forward simulate a PK compartmental model; returns {times, concentrations}."""
        return impl_simulate_pk_model(
            model_name, params, dose, times, infusion_duration, tlag, F
        )

    @mcp.tool
    def fit_pk_model(
        dataset_path: str,
        model_name: str,
        initial_params: dict[str, float],
        dose: float | None = None,
        dose_path: str | None = None,
        weighting: str = "1_over_y_squared",
        residual_error: str = "proportional",
        use_ode: bool = False,
        winnonlin_version: str = "6.4",
        audit_dir: str | None = None,
    ) -> dict[str, Any]:
        """Fit a PK compartmental model + emit audit + write fit artifacts."""
        return impl_fit_pk_model(
            dataset_path,
            model_name,
            initial_params,
            dose,
            dose_path,
            weighting,
            residual_error,
            use_ode,
            winnonlin_version,
            audit_dir,
        )

    @mcp.tool
    def list_pd_models() -> dict[str, Any]:
        """Return all available PD model names and their parameter lists."""
        return impl_list_pd_models()

    @mcp.tool
    def simulate_pd_model(
        model_name: str,
        params: dict[str, float],
        times: list[float],
        concentrations: list[float],
    ) -> dict[str, Any]:
        """Forward simulate a PD model; returns {times, effects}."""
        return impl_simulate_pd_model(model_name, params, times, concentrations)

    @mcp.tool
    def fit_pd_model(
        pd_dataset_path: str,
        model_name: str,
        initial_params: dict[str, float],
        mode: str = "sequential",
        weighting: str = "uniform",
        winnonlin_version: str = "6.4",
        audit_dir: str | None = None,
    ) -> dict[str, Any]:
        """Fit a PD model to effect-time data + emit audit."""
        return impl_fit_pd_model(
            pd_dataset_path,
            model_name,
            initial_params,
            mode,
            weighting,
            winnonlin_version,
            audit_dir,
        )

    @mcp.tool
    def generate_report(
        run_id: str,
        format: str = "html",
        audit_dir: str | None = None,
    ) -> dict[str, Any]:
        """Generate a report from an existing audit run (NCA or BE)."""
        return impl_generate_report(run_id, format, audit_dir)

    @mcp.tool
    def r_backend_status() -> dict[str, Any]:
        """Probe local R + PKNCA/NonCompart installation status."""
        return impl_r_backend_status()

    @mcp.tool
    def compare_against_reference(
        run_id: str,
        reference_backend: str = "pknca",
        tolerance_relative: float = 1e-6,
        audit_dir: str | None = None,
    ) -> dict[str, Any]:
        """Compare a previous NCA run against PKNCA or NonCompart."""
        return impl_compare_against_reference(
            run_id, reference_backend, tolerance_relative, audit_dir
        )

    @mcp.tool
    def import_sdtm(
        pc_path: str,
        ex_path: str,
        dm_path: str | None = None,
        analyte: str | None = None,
        matrix: str | None = None,
        audit_dir: str | None = None,
    ) -> dict[str, Any]:
        """Import SDTM PC + EX + optional DM domains → canonical CSVs + audit."""
        return impl_import_sdtm(pc_path, ex_path, dm_path, analyte, matrix, audit_dir)

    @mcp.tool
    def export_adam(
        nca_run_id: str,
        output_dir: str | None = None,
        include_define_xml: bool = True,
        audit_dir: str | None = None,
    ) -> dict[str, Any]:
        """Export ADPC + ADPP + define.xml from a previous NCA run."""
        return impl_export_adam(nca_run_id, output_dir, include_define_xml, audit_dir)

    @mcp.tool
    def validate_cdisc(
        dataset_path: str,
        domain: str,
    ) -> dict[str, Any]:
        """Run Pinnacle21-style validation checks on an ADaM dataset (ADPC or ADPP)."""
        return impl_validate_cdisc(dataset_path, domain)

    @mcp.tool
    def sign_record(
        run_id: str,
        signer_identity: str,
        meaning: str,
        auth_token: str,
        private_key_path: str,
        passphrase: str | None = None,
        audit_dir: str | None = None,
    ) -> dict[str, Any]:
        """Sign a run bundle with Ed25519 key (§11.50/§11.70/§11.200)."""
        return impl_sign_record(
            run_id, signer_identity, meaning, auth_token,
            private_key_path, passphrase, audit_dir,
        )

    @mcp.tool
    def lock_run(
        run_id: str,
        locked_by: str,
        lock_reason: str,
        require_signatures: list[str] | None = None,
        audit_dir: str | None = None,
    ) -> dict[str, Any]:
        """Finalize a run bundle: verify signatures, set read-only (§11.10(c))."""
        return impl_lock_run(run_id, locked_by, lock_reason, require_signatures, audit_dir)

    @mcp.tool
    def verify_audit_chain(
        chain_dir: str | None = None,
    ) -> dict[str, Any]:
        """Verify audit chain integrity (§11.10(e))."""
        return impl_verify_audit_chain(chain_dir)

    @mcp.tool
    def verify_signatures(
        run_id: str,
        audit_dir: str | None = None,
    ) -> dict[str, Any]:
        """Verify all electronic signatures for a run (§11.50/§11.70)."""
        return impl_verify_signatures(run_id, audit_dir)

    @mcp.tool
    def get_compliance_status() -> dict[str, Any]:
        """Return v2.0 Part 11 technical control status."""
        return impl_get_compliance_status()

    return mcp


def main() -> None:
    """Run the MCP server (entry point for ``python -m pkplugin.mcp_server``)."""
    mcp = _build_mcp()
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
