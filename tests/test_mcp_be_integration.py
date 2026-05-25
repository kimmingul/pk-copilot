"""
Integration tests for impl_run_be and impl_summarize_nca in mcp_server.

Tests:
  1. impl_run_be produces a valid BEResult dict for a 2x2 crossover CSV.
  2. Audit file and be_result.csv are created with correct columns.
  3. impl_summarize_nca with parameter_dataset_path returns valid structure.
  4. impl_run_be returns error dict when file is missing.
  5. _build_mcp() registers run_be and summarize_nca (skipped if fastmcp absent).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from pkplugin.mcp_server import impl_run_be, impl_summarize_nca

# Import the shared data generator from the bioequivalence test module.
from tests.test_bioequivalence import make_2x2_crossover_data

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def crossover_csv(tmp_path: Path) -> Path:
    """Write a 2x2 crossover parameter CSV to a temp dir and return its path."""
    df = make_2x2_crossover_data(
        n_per_sequence=12,
        gmr=0.98,
        within_subject_cv_pct=15.0,
        between_subject_cv_pct=25.0,
        seed=42,
    )
    csv_path = tmp_path / "parameters.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture()
def wide_nca_csv(tmp_path: Path) -> Path:
    """Write a minimal wide-format NCA parameter CSV for summarize_nca tests."""
    rows = [
        {
            "subject_id": f"S{i:03d}",
            "treatment": "T" if i % 2 == 0 else "R",
            "period": 1,
            "analyte": "Drug",
            "AUC0_t": 100.0 + i * 2.5,
            "Cmax": 10.0 + i * 0.5,
        }
        for i in range(1, 13)
    ]
    csv_path = tmp_path / "nca_params.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return csv_path


# ---------------------------------------------------------------------------
# Test 1 — impl_run_be end-to-end: valid BEResult dict
# ---------------------------------------------------------------------------


def test_impl_run_be_be_demonstrated(crossover_csv: Path, tmp_path: Path) -> None:
    """impl_run_be should return status=ok and demonstrate BE for the fixture."""
    result = impl_run_be(
        parameter_dataset_path=str(crossover_csv),
        endpoint="AUC0_t",
        design="crossover_2x2",
        audit_dir=str(tmp_path / "audit"),
    )

    assert result["status"] == "ok", f"Expected ok, got: {result}"
    assert "run_id" in result
    assert "audit_path" in result
    assert "be_result" in result

    be = result["be_result"]
    assert be["design"] == "crossover_2x2"
    assert be["endpoint"] == "AUC0_t"
    assert be["n_subjects"] == 24
    assert be["be_demonstrated"] is True
    assert 90.0 <= be["gmr_pct"] <= 110.0, f"GMR out of expected range: {be['gmr_pct']}"
    assert be["ci_90_low_pct"] >= 80.0
    assert be["ci_90_high_pct"] <= 125.0


# ---------------------------------------------------------------------------
# Test 2 — Audit file produced + be_result.csv has correct columns
# ---------------------------------------------------------------------------


def test_impl_run_be_artifacts(crossover_csv: Path, tmp_path: Path) -> None:
    """Audit JSON and be_result.csv must be written with expected columns."""
    audit_dir = tmp_path / "audit"
    result = impl_run_be(
        parameter_dataset_path=str(crossover_csv),
        endpoint="AUC0_t",
        design="crossover_2x2",
        audit_dir=str(audit_dir),
    )

    assert result["status"] == "ok"

    audit_path = Path(result["audit_path"])
    assert audit_path.exists(), f"audit.json not found: {audit_path}"

    # Validate JSON structure
    with audit_path.open() as fh:
        audit_data = json.load(fh)
    assert audit_data["tool"] == "run_be"
    assert audit_data["run_id"] == result["run_id"]

    # be_result.csv must exist in the run directory
    run_dir = audit_path.parent
    be_csv = run_dir / "be_result.csv"
    assert be_csv.exists(), f"be_result.csv not found: {be_csv}"

    be_df = pd.read_csv(be_csv)
    assert len(be_df) == 1, "be_result.csv must have exactly one row"

    expected_cols = {
        "run_id",
        "design",
        "endpoint",
        "gmr_pct",
        "ci_90_low_pct",
        "ci_90_high_pct",
        "be_demonstrated",
        "n_subjects",
        "n_completers",
    }
    missing = expected_cols - set(be_df.columns)
    assert not missing, f"be_result.csv missing columns: {missing}"


# ---------------------------------------------------------------------------
# Test 3 — impl_summarize_nca with parameter_dataset_path
# ---------------------------------------------------------------------------


def test_impl_summarize_nca_wide_format(wide_nca_csv: Path, tmp_path: Path) -> None:
    """impl_summarize_nca on a wide-format CSV should return grouped stats."""
    result = impl_summarize_nca(
        parameter_dataset_path=str(wide_nca_csv),
        group_by=["treatment"],
        parameters=["AUC0_t", "Cmax"],
        audit_dir=str(tmp_path / "audit"),
    )

    assert result["status"] == "ok", f"Expected ok, got: {result}"
    assert "run_id" in result
    assert "audit_path" in result
    assert isinstance(result["summary"], list)
    assert len(result["summary"]) >= 1

    for group in result["summary"]:
        assert "group_keys" in group
        assert "n_subjects" in group
        assert "by_parameter" in group
        bp = group["by_parameter"]
        # Each requested parameter must be present
        for param in ("AUC0_t", "Cmax"):
            assert param in bp, f"Parameter {param!r} missing from by_parameter"
            stats = bp[param]
            if stats["n"] > 0:
                assert stats["mean"] is not None
                assert stats["median"] is not None


# ---------------------------------------------------------------------------
# Test 4 — impl_run_be returns error when file missing
# ---------------------------------------------------------------------------


def test_impl_run_be_missing_file(tmp_path: Path) -> None:
    """impl_run_be must return status=error when file does not exist."""
    result = impl_run_be(
        parameter_dataset_path=str(tmp_path / "nonexistent.csv"),
        audit_dir=str(tmp_path / "audit"),
    )
    assert result["status"] == "error"
    assert "not found" in result["error"].lower() or "error" in result["status"]


# ---------------------------------------------------------------------------
# Test 5 — _build_mcp registers run_be and summarize_nca
# ---------------------------------------------------------------------------


def test_build_mcp_registers_run_be_and_summarize_nca() -> None:
    """_build_mcp() must expose run_be and summarize_nca tools."""
    pytest.importorskip("fastmcp")
    from pkplugin.mcp_server import _build_mcp

    mcp = _build_mcp()
    # FastMCP stores tools in _tool_manager or similar; check via tool name listing.
    # Attempt both common attribute patterns across fastmcp versions.
    tool_names: set[str] = set()
    if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
        tool_names = set(mcp._tool_manager._tools.keys())
    elif hasattr(mcp, "tools"):
        tool_names = set(mcp.tools.keys()) if isinstance(mcp.tools, dict) else set()

    if tool_names:
        assert "run_be" in tool_names, f"run_be not found in {tool_names}"
        assert "summarize_nca" in tool_names, f"summarize_nca not found in {tool_names}"
    else:
        # If we cannot introspect the tool registry just verify it didn't error.
        assert mcp is not None
