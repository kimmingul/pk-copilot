"""
Integration tests for impl_compare_against_reference and impl_r_backend_status
in mcp_server.py.

Tests:
  1. When R is unavailable: returns status="r_unavailable".
  2. When mocked R returns matching values: overall_passed=True.
  3. When mocked R returns different values: overall_passed=False with diffs.
  4. impl_r_backend_status returns a dict with the expected keys.
  5. Unknown reference_backend returns status="error".
"""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pkplugin.mcp_server import (
    impl_compare_against_reference,
    impl_r_backend_status,
)
from pkplugin.validation.r_backend import RBackendStatus, RNCAResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_params_csv(path: Path, rows: list[dict[str, object]]) -> None:
    """Write a long-format parameter CSV (subject_id, parameter, value)."""
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_audit_json(run_dir: Path, dataset_path: Path) -> None:
    """Write a minimal audit.json pointing to *dataset_path*."""
    payload = {
        "run_id": run_dir.name,
        "tool": "run_nca",
        "input_files": [{"path": str(dataset_path), "sha256": "abc123"}],
        "config": {},
    }
    (run_dir / "audit.json").write_text(json.dumps(payload))


def _make_run_dir(
    tmp_path: Path,
    pk_rows: list[dict[str, object]],
    dataset_rows: list[dict[str, object]] | None = None,
) -> tuple[Path, Path, Path]:
    """
    Create a fake run directory with:
      - parameters.csv (pk-copilot output, long-format)
      - input_dataset.csv (original concentration data, for audit.json)
      - audit.json

    Returns (audit_base, run_id_dir, dataset_csv_path).
    """
    audit_base = tmp_path / "pk_runs"
    audit_base.mkdir()
    run_id = "test-run-001"
    run_dir = audit_base / run_id
    run_dir.mkdir()

    # Write parameters.csv
    _write_params_csv(run_dir / "parameters.csv", pk_rows)

    # Write a placeholder dataset CSV (concentration data)
    dataset_csv = tmp_path / "dataset.csv"
    if dataset_rows is None:
        dataset_rows = [
            {"subject_id": "S01", "time": 0.0, "concentration": 0.0},
            {"subject_id": "S01", "time": 1.0, "concentration": 5.0},
        ]
    pd.DataFrame(dataset_rows).to_csv(dataset_csv, index=False)

    _write_audit_json(run_dir, dataset_csv)

    return audit_base, run_dir, dataset_csv


def _make_r_unavailable_status() -> RBackendStatus:
    return RBackendStatus(
        available=False,
        rscript_path=None,
        r_version=None,
        pknca_version=None,
        noncompart_version=None,
        error="Rscript not found in PATH",
    )


def _make_r_available_status() -> RBackendStatus:
    return RBackendStatus(
        available=True,
        rscript_path="/usr/bin/Rscript",
        r_version="4.3.1",
        pknca_version="0.11.0",
        noncompart_version="0.6.0",
        error=None,
    )


# ---------------------------------------------------------------------------
# 1. R unavailable → status="r_unavailable"
# ---------------------------------------------------------------------------


def test_compare_r_unavailable(tmp_path: Path) -> None:
    """When R is not available, impl_compare_against_reference returns r_unavailable."""
    pk_rows = [{"subject_id": "S01", "parameter": "Cmax", "value": 100.0}]
    audit_base, run_dir, _ = _make_run_dir(tmp_path, pk_rows)

    with patch(
        "pkplugin.validation.r_backend.check_r_backend",
        return_value=_make_r_unavailable_status(),
    ):
        result = impl_compare_against_reference(
            run_id="test-run-001",
            audit_dir=str(audit_base),
        )

    assert result["status"] == "r_unavailable"
    assert result["available"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# 2. Mocked R returns matching values → overall_passed=True
# ---------------------------------------------------------------------------


def test_compare_matching_values(tmp_path: Path) -> None:
    """When R produces the same values, overall_passed=True."""
    pk_rows = [
        {"subject_id": "S01", "parameter": "Cmax", "value": 100.0},
        {"subject_id": "S01", "parameter": "AUClast", "value": 500.0},
    ]
    audit_base, run_dir, _ = _make_run_dir(tmp_path, pk_rows)

    # R output CSV with identical values
    r_out_dir = run_dir / "r_validation"
    r_out_dir.mkdir(parents=True)
    r_out_csv = r_out_dir / "pknca_parameters.csv"
    _write_params_csv(
        r_out_csv,
        [
            {"subject_id": "S01", "parameter": "Cmax", "value": 100.0},
            {"subject_id": "S01", "parameter": "AUClast", "value": 500.0},
        ],
    )

    mock_r_result = RNCAResult(
        backend="PKNCA",
        parameter_table_csv=r_out_csv,
        raw_stdout="PKNCA: wrote 2 rows\n",
        raw_stderr="",
        return_code=0,
    )

    with (
        patch(
            "pkplugin.validation.r_backend.check_r_backend",
            return_value=_make_r_available_status(),
        ),
        patch(
            "pkplugin.validation.r_backend.run_r_pknca",
            return_value=mock_r_result,
        ),
    ):
        result = impl_compare_against_reference(
            run_id="test-run-001",
            reference_backend="pknca",
            audit_dir=str(audit_base),
        )

    assert result["status"] == "ok"
    assert result["overall_passed"] is True
    assert result["n_outside_tolerance"] == 0
    assert result["n_compared"] == 2


# ---------------------------------------------------------------------------
# 3. Mocked R returns different values → overall_passed=False with diffs
# ---------------------------------------------------------------------------


def test_compare_different_values(tmp_path: Path) -> None:
    """When R produces different values, overall_passed=False and diffs are reported."""
    pk_rows = [
        {"subject_id": "S01", "parameter": "Cmax", "value": 100.0},
        {"subject_id": "S01", "parameter": "AUClast", "value": 500.0},
    ]
    audit_base, run_dir, _ = _make_run_dir(tmp_path, pk_rows)

    r_out_dir = run_dir / "r_validation"
    r_out_dir.mkdir(parents=True)
    r_out_csv = r_out_dir / "pknca_parameters.csv"
    _write_params_csv(
        r_out_csv,
        [
            # Cmax matches; AUClast is 10% off
            {"subject_id": "S01", "parameter": "Cmax", "value": 100.0},
            {"subject_id": "S01", "parameter": "AUClast", "value": 550.0},
        ],
    )

    mock_r_result = RNCAResult(
        backend="PKNCA",
        parameter_table_csv=r_out_csv,
        raw_stdout="",
        raw_stderr="",
        return_code=0,
    )

    with (
        patch(
            "pkplugin.validation.r_backend.check_r_backend",
            return_value=_make_r_available_status(),
        ),
        patch(
            "pkplugin.validation.r_backend.run_r_pknca",
            return_value=mock_r_result,
        ),
    ):
        result = impl_compare_against_reference(
            run_id="test-run-001",
            reference_backend="pknca",
            tolerance_relative=1e-6,
            audit_dir=str(audit_base),
        )

    assert result["status"] == "ok"
    assert result["overall_passed"] is False
    assert result["n_outside_tolerance"] >= 1
    assert len(result["outside_tolerance_diffs"]) >= 1

    # Verify the diff entry for AUClast
    auclast_diff = next(
        (d for d in result["outside_tolerance_diffs"] if d["parameter"] == "AUClast"),
        None,
    )
    assert auclast_diff is not None
    assert auclast_diff["pkcopilot_value"] == pytest.approx(500.0)
    assert auclast_diff["reference_value"] == pytest.approx(550.0)

    # validation_diff.json was written
    diff_path = Path(result["diff_path"])
    assert diff_path.is_file()
    loaded = json.loads(diff_path.read_text())
    assert loaded["overall_passed"] is False


# ---------------------------------------------------------------------------
# 4. impl_r_backend_status returns dict with expected keys
# ---------------------------------------------------------------------------


def test_r_backend_status_keys() -> None:
    """impl_r_backend_status returns a dict with all required keys."""
    result = impl_r_backend_status()
    required_keys = {
        "available",
        "rscript_path",
        "r_version",
        "pknca_version",
        "noncompart_version",
        "error",
    }
    assert required_keys <= set(result.keys())
    assert isinstance(result["available"], bool)


# ---------------------------------------------------------------------------
# 5. Unknown reference_backend returns error
# ---------------------------------------------------------------------------


def test_compare_unknown_backend(tmp_path: Path) -> None:
    """Passing an unknown reference_backend returns status='error'."""
    pk_rows = [{"subject_id": "S01", "parameter": "Cmax", "value": 100.0}]
    audit_base, _, _ = _make_run_dir(tmp_path, pk_rows)

    result = impl_compare_against_reference(
        run_id="test-run-001",
        reference_backend="winnonlin",
        audit_dir=str(audit_base),
    )

    assert result["status"] == "error"
    assert "winnonlin" in result["error"]
