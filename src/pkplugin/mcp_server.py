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
