"""
Tests for src/pkplugin/validation/diff.py

Tests:
  1. Identical CSVs → 0 outside tolerance.
  2. One row 5% off → outside tolerance (relative tol 1e-6).
  3. Relative vs absolute tolerance interaction.
  4. Missing parameter in reference → marked as None reference_value.
  5. Missing parameter in pk-copilot → marked as None pkcopilot_value.
  6. write_validation_diff_json round-trip via json.load.
  7. overall_passed is False when any row is outside tolerance.
  8. Empty comparison (no shared params) → overall_passed False.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from pkplugin.validation.diff import (
    compute_diff,
    write_validation_diff_json,
)
from pkplugin.validation.r_backend import RBackendStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_param_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    """Write a long-format parameter CSV to *path*."""
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _make_rows(
    subjects: list[str],
    parameters: dict[str, float],
) -> list[dict[str, object]]:
    """Build long-format rows for each (subject, parameter) combination."""
    result = []
    for sid in subjects:
        for param, val in parameters.items():
            result.append({"subject_id": sid, "parameter": param, "value": val})
    return result


def _dummy_r_status() -> RBackendStatus:
    return RBackendStatus(
        available=False,
        rscript_path=None,
        r_version=None,
        pknca_version=None,
        noncompart_version=None,
        error="R not used in test",
    )


# ---------------------------------------------------------------------------
# 1. Identical input → 0 outside tolerance
# ---------------------------------------------------------------------------


def test_identical_csvs_zero_outside_tolerance(tmp_path: Path) -> None:
    """Identical pk-copilot and reference CSVs yield n_outside_tolerance=0."""
    params = {"Cmax": 100.0, "AUClast": 500.0, "HL_Lambda_z": 8.0}
    rows = _make_rows(["S01", "S02"], params)

    pk_csv = _write_param_csv(tmp_path / "pk.csv", rows)
    ref_csv = _write_param_csv(tmp_path / "ref.csv", rows)

    diff = compute_diff(pk_csv, ref_csv, r_status=_dummy_r_status())

    assert diff.n_outside_tolerance == 0
    assert diff.n_compared == len(rows)
    assert diff.overall_passed is True
    for d in diff.diffs:
        assert d.absolute_diff is not None
        assert d.absolute_diff == pytest.approx(0.0, abs=1e-15)
        assert d.within_tolerance is True


# ---------------------------------------------------------------------------
# 2. One row 5% off → outside default tolerance (1e-6 relative)
# ---------------------------------------------------------------------------


def test_one_row_5pct_off(tmp_path: Path) -> None:
    """A single parameter 5% off should be marked outside tolerance."""
    pk_rows = [{"subject_id": "S01", "parameter": "Cmax", "value": 100.0}]
    ref_rows = [{"subject_id": "S01", "parameter": "Cmax", "value": 105.0}]  # 5% off

    pk_csv = _write_param_csv(tmp_path / "pk.csv", pk_rows)
    ref_csv = _write_param_csv(tmp_path / "ref.csv", ref_rows)

    diff = compute_diff(
        pk_csv,
        ref_csv,
        tolerance_relative=1e-6,
        r_status=_dummy_r_status(),
    )

    assert diff.n_outside_tolerance == 1
    assert diff.overall_passed is False
    row = diff.diffs[0]
    assert row.pkcopilot_value == pytest.approx(100.0)
    assert row.reference_value == pytest.approx(105.0)
    assert row.absolute_diff == pytest.approx(5.0)
    assert row.relative_diff == pytest.approx(5.0 / 105.0)


# ---------------------------------------------------------------------------
# 3. Relative tolerance vs absolute tolerance interaction
# ---------------------------------------------------------------------------


def test_absolute_tolerance_floor(tmp_path: Path) -> None:
    """
    When abs_diff is tiny but reference_value is also tiny, the absolute
    tolerance floor should allow the comparison to pass even if relative
    tolerance alone would fail.
    """
    # abs_diff = 1e-12, ref = 1e-12 → rel_diff = 1.0 (100 %)
    # But with tolerance_absolute=1e-11, threshold = max(1e-11, 1e-6 * 1e-12) = 1e-11
    # 1e-12 <= 1e-11 → within tolerance
    pk_rows = [{"subject_id": "S01", "parameter": "Lambda_z", "value": 2e-12}]
    ref_rows = [{"subject_id": "S01", "parameter": "Lambda_z", "value": 1e-12}]

    pk_csv = _write_param_csv(tmp_path / "pk.csv", pk_rows)
    ref_csv = _write_param_csv(tmp_path / "ref.csv", ref_rows)

    diff = compute_diff(
        pk_csv,
        ref_csv,
        tolerance_relative=1e-6,
        tolerance_absolute=1e-11,
        r_status=_dummy_r_status(),
    )

    # abs_diff = 1e-12 < 1e-11 → within tolerance
    assert diff.diffs[0].within_tolerance is True
    assert diff.n_outside_tolerance == 0


def test_relative_tolerance_dominates(tmp_path: Path) -> None:
    """When reference is large, rel tolerance dominates; large diff should fail."""
    pk_rows = [{"subject_id": "S01", "parameter": "AUClast", "value": 100.0}]
    ref_rows = [{"subject_id": "S01", "parameter": "AUClast", "value": 110.0}]

    pk_csv = _write_param_csv(tmp_path / "pk.csv", pk_rows)
    ref_csv = _write_param_csv(tmp_path / "ref.csv", ref_rows)

    diff = compute_diff(
        pk_csv,
        ref_csv,
        tolerance_relative=1e-6,
        tolerance_absolute=1e-9,
        r_status=_dummy_r_status(),
    )

    # abs_diff=10, threshold=max(1e-9, 1e-6*110)=1.1e-4 → 10 >> threshold
    assert diff.diffs[0].within_tolerance is False
    assert diff.n_outside_tolerance == 1


# ---------------------------------------------------------------------------
# 4. Missing parameter in reference → reference_value is None
# ---------------------------------------------------------------------------


def test_missing_in_reference(tmp_path: Path) -> None:
    """Parameter present in pk-copilot but absent in reference → ref=None."""
    pk_rows = [
        {"subject_id": "S01", "parameter": "Cmax", "value": 100.0},
        {"subject_id": "S01", "parameter": "AUClast", "value": 500.0},
    ]
    ref_rows = [
        {"subject_id": "S01", "parameter": "Cmax", "value": 100.0},
        # AUClast is absent from reference
    ]

    pk_csv = _write_param_csv(tmp_path / "pk.csv", pk_rows)
    ref_csv = _write_param_csv(tmp_path / "ref.csv", ref_rows)

    diff = compute_diff(pk_csv, ref_csv, r_status=_dummy_r_status())

    auclast_row = next(d for d in diff.diffs if d.parameter == "AUClast")
    assert auclast_row.reference_value is None
    assert auclast_row.pkcopilot_value == pytest.approx(500.0)
    assert auclast_row.within_tolerance is False


# ---------------------------------------------------------------------------
# 5. Missing parameter in pk-copilot → pkcopilot_value is None
# ---------------------------------------------------------------------------


def test_missing_in_pkcopilot(tmp_path: Path) -> None:
    """Parameter absent in pk-copilot but present in reference → pk=None."""
    pk_rows = [
        {"subject_id": "S01", "parameter": "Cmax", "value": 100.0},
    ]
    ref_rows = [
        {"subject_id": "S01", "parameter": "Cmax", "value": 100.0},
        {"subject_id": "S01", "parameter": "HL_Lambda_z", "value": 8.0},
    ]

    pk_csv = _write_param_csv(tmp_path / "pk.csv", pk_rows)
    ref_csv = _write_param_csv(tmp_path / "ref.csv", ref_rows)

    diff = compute_diff(pk_csv, ref_csv, r_status=_dummy_r_status())

    hl_row = next(d for d in diff.diffs if d.parameter == "HL_Lambda_z")
    assert hl_row.pkcopilot_value is None
    assert hl_row.reference_value == pytest.approx(8.0)
    assert hl_row.within_tolerance is False


# ---------------------------------------------------------------------------
# 6. write_validation_diff_json round-trip
# ---------------------------------------------------------------------------


def test_write_validation_diff_json_roundtrip(tmp_path: Path) -> None:
    """write_validation_diff_json writes valid JSON that round-trips correctly."""
    params = {"Cmax": 100.0, "AUClast": 500.0}
    rows = _make_rows(["S01"], params)
    pk_csv = _write_param_csv(tmp_path / "pk.csv", rows)
    ref_csv = _write_param_csv(tmp_path / "ref.csv", rows)

    diff = compute_diff(
        pk_csv,
        ref_csv,
        r_status=_dummy_r_status(),
        reference_backend="PKNCA",
        run_id="test-run-123",
    )

    out_path = tmp_path / "validation_diff.json"
    written = write_validation_diff_json(diff, out_path)

    assert written == out_path.resolve()
    assert out_path.is_file()

    with open(out_path) as fh:
        loaded = json.load(fh)

    assert loaded["run_id"] == "test-run-123"
    assert loaded["reference_backend"] == "PKNCA"
    assert loaded["overall_passed"] is True
    assert loaded["n_outside_tolerance"] == 0
    assert isinstance(loaded["diffs"], list)
    assert len(loaded["diffs"]) == len(rows)
    # r_status embedded
    assert "r_status" in loaded
    assert loaded["r_status"]["available"] is False


# ---------------------------------------------------------------------------
# 7. overall_passed is False when any outside
# ---------------------------------------------------------------------------


def test_overall_passed_false_when_any_outside(tmp_path: Path) -> None:
    """overall_passed is False when at least one parameter is outside tolerance."""
    pk_rows = [
        {"subject_id": "S01", "parameter": "Cmax", "value": 100.0},
        {"subject_id": "S01", "parameter": "AUClast", "value": 600.0},  # 20% off
    ]
    ref_rows = [
        {"subject_id": "S01", "parameter": "Cmax", "value": 100.0},
        {"subject_id": "S01", "parameter": "AUClast", "value": 500.0},
    ]

    pk_csv = _write_param_csv(tmp_path / "pk.csv", pk_rows)
    ref_csv = _write_param_csv(tmp_path / "ref.csv", ref_rows)

    diff = compute_diff(pk_csv, ref_csv, r_status=_dummy_r_status())

    assert diff.overall_passed is False
    assert diff.n_outside_tolerance >= 1
