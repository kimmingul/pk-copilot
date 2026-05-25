"""
Parameter-level diff between pk-copilot results and an R reference backend.

Compares two long-format parameter CSVs (columns: subject_id, parameter, value)
and computes absolute/relative differences with configurable tolerances.

Refs: docs/08-validation-strategy.md §4–§5
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pkplugin import __version__ as _PKPLUGIN_VERSION
from pkplugin.validation.r_backend import RBackendStatus

# ---------------------------------------------------------------------------
# Per-parameter diff record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParameterDiff:
    """Comparison result for one (subject_id, parameter) pair."""

    subject_id: str
    parameter: str
    pkcopilot_value: float | None
    reference_value: float | None
    absolute_diff: float | None
    relative_diff: float | None
    within_tolerance: bool
    tolerance_used: float


# ---------------------------------------------------------------------------
# Aggregate diff result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationDiff:
    """Full cross-backend validation diff for one run."""

    run_id: str
    reference_backend: str  # "PKNCA" or "NonCompart"
    n_compared: int
    n_within_tolerance: int
    n_outside_tolerance: int
    diffs: list[ParameterDiff]
    overall_passed: bool
    pkplugin_version: str
    r_status: RBackendStatus


# ---------------------------------------------------------------------------
# Tolerance rule
# ---------------------------------------------------------------------------


def _within_tolerance(
    absolute_diff: float,
    reference_value: float | None,
    tolerance_relative: float,
    tolerance_absolute: float,
) -> bool:
    """Return True when abs_diff <= max(tol_abs, tol_rel * |ref|)."""
    if reference_value is None:
        return False
    threshold = max(tolerance_absolute, tolerance_relative * abs(reference_value))
    return absolute_diff <= threshold


# ---------------------------------------------------------------------------
# Core comparison function
# ---------------------------------------------------------------------------


def compute_diff(
    pkplugin_parameters_csv: Path,
    reference_parameters_csv: Path,
    *,
    tolerance_relative: float = 1e-6,
    tolerance_absolute: float = 1e-9,
    parameters_to_compare: list[str] | None = None,
    r_status: RBackendStatus | None = None,
    reference_backend: str = "PKNCA",
    run_id: str | None = None,
) -> ValidationDiff:
    """Compare two long-format parameter CSVs.

    Both CSVs must have columns: ``subject_id``, ``parameter``, ``value``.

    Args:
        pkplugin_parameters_csv: pk-copilot output (long-format).
        reference_parameters_csv: R backend output (long-format).
        tolerance_relative: Relative tolerance (default 1e-6).
        tolerance_absolute: Absolute tolerance floor (default 1e-9).
        parameters_to_compare: If given, only compare these parameter names.
        r_status: RBackendStatus to embed in the result.
        reference_backend: Name of the reference backend ("PKNCA" / "NonCompart").
        run_id: Override run_id; auto-generated if None.

    Returns:
        ValidationDiff with per-parameter comparison results.
    """
    if run_id is None:
        run_id = uuid.uuid4().hex[:12]

    pk_df = pd.read_csv(pkplugin_parameters_csv)
    ref_df = pd.read_csv(reference_parameters_csv)

    # Normalise column names — accept 'value' or 'Value'
    pk_df.columns = [c.lower() for c in pk_df.columns]
    ref_df.columns = [c.lower() for c in ref_df.columns]

    # Build (subject_id, parameter) -> value mappings
    pk_map: dict[tuple[str, str], float | None] = {}
    for _, row in pk_df.iterrows():
        sid = str(row["subject_id"])
        param = str(row["parameter"])
        raw = row.get("value")
        val: float | None = (
            None if (raw is None or (isinstance(raw, float) and math.isnan(raw))) else float(raw)
        )
        pk_map[(sid, param)] = val

    ref_map: dict[tuple[str, str], float | None] = {}
    for _, row in ref_df.iterrows():
        sid = str(row["subject_id"])
        param = str(row["parameter"])
        raw = row.get("value")
        val = None if (raw is None or (isinstance(raw, float) and math.isnan(raw))) else float(raw)
        ref_map[(sid, param)] = val

    # Union of all (subject, parameter) keys
    all_keys = set(pk_map.keys()) | set(ref_map.keys())

    # Filter to requested parameters if specified
    if parameters_to_compare is not None:
        param_set = set(parameters_to_compare)
        all_keys = {k for k in all_keys if k[1] in param_set}

    diffs: list[ParameterDiff] = []
    for sid, param in sorted(all_keys):
        pk_val = pk_map.get((sid, param))
        ref_val = ref_map.get((sid, param))

        if pk_val is None or ref_val is None:
            # One side missing — cannot compute numeric diff
            diffs.append(
                ParameterDiff(
                    subject_id=sid,
                    parameter=param,
                    pkcopilot_value=pk_val,
                    reference_value=ref_val,
                    absolute_diff=None,
                    relative_diff=None,
                    within_tolerance=False,
                    tolerance_used=tolerance_relative,
                )
            )
            continue

        abs_diff = abs(pk_val - ref_val)
        rel_diff: float | None
        if ref_val != 0.0:
            rel_diff = abs_diff / abs(ref_val)
        else:
            rel_diff = None

        within = _within_tolerance(abs_diff, ref_val, tolerance_relative, tolerance_absolute)

        diffs.append(
            ParameterDiff(
                subject_id=sid,
                parameter=param,
                pkcopilot_value=pk_val,
                reference_value=ref_val,
                absolute_diff=abs_diff,
                relative_diff=rel_diff,
                within_tolerance=within,
                tolerance_used=tolerance_relative,
            )
        )

    n_compared = sum(1 for d in diffs if d.absolute_diff is not None)
    n_within = sum(1 for d in diffs if d.within_tolerance)
    n_outside = sum(1 for d in diffs if d.absolute_diff is not None and not d.within_tolerance)

    # Build a default RBackendStatus when none supplied (R not used)
    if r_status is None:
        r_status = RBackendStatus(
            available=False,
            rscript_path=None,
            r_version=None,
            pknca_version=None,
            noncompart_version=None,
            error="R status not provided",
        )

    return ValidationDiff(
        run_id=run_id,
        reference_backend=reference_backend,
        n_compared=n_compared,
        n_within_tolerance=n_within,
        n_outside_tolerance=n_outside,
        diffs=diffs,
        overall_passed=(n_outside == 0 and n_compared > 0),
        pkplugin_version=_PKPLUGIN_VERSION,
        r_status=r_status,
    )


# ---------------------------------------------------------------------------
# JSON persistence
# ---------------------------------------------------------------------------


def _rstatus_to_dict(r_status: RBackendStatus) -> dict[str, Any]:
    return {
        "available": r_status.available,
        "rscript_path": r_status.rscript_path,
        "r_version": r_status.r_version,
        "pknca_version": r_status.pknca_version,
        "noncompart_version": r_status.noncompart_version,
        "error": r_status.error,
    }


def write_validation_diff_json(diff: ValidationDiff, output_path: Path) -> Path:
    """Persist a ValidationDiff as validation_diff.json.

    Args:
        diff: The ValidationDiff to serialise.
        output_path: Target file path.

    Returns:
        The resolved output path.
    """
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    diffs_serialised: list[dict[str, Any]] = []
    for d in diff.diffs:
        diffs_serialised.append(
            {
                "subject_id": d.subject_id,
                "parameter": d.parameter,
                "pkcopilot_value": d.pkcopilot_value,
                "reference_value": d.reference_value,
                "absolute_diff": d.absolute_diff,
                "relative_diff": d.relative_diff,
                "within_tolerance": d.within_tolerance,
                "tolerance_used": d.tolerance_used,
            }
        )

    payload: dict[str, Any] = {
        "run_id": diff.run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "pkplugin_version": diff.pkplugin_version,
        "reference_backend": diff.reference_backend,
        "n_compared": diff.n_compared,
        "n_within_tolerance": diff.n_within_tolerance,
        "n_outside_tolerance": diff.n_outside_tolerance,
        "overall_passed": diff.overall_passed,
        "r_status": _rstatus_to_dict(diff.r_status),
        "diffs": diffs_serialised,
    }

    output_path.write_text(json.dumps(payload, indent=2))
    return output_path
