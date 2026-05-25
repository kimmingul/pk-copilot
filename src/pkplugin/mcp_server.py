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
import os
from pathlib import Path
from typing import Any

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

    return mcp


def main() -> None:
    """Run the MCP server (entry point for ``python -m pkplugin.mcp_server``)."""
    mcp = _build_mcp()
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
