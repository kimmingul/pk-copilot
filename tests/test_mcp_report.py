"""
Tests for impl_generate_report in pkplugin.mcp_server.

Covers:
- End-to-end: run NCA, then generate HTML report
- End-to-end: run BE, then generate HTML report

Refs: docs/02-roadmap.md v0.5, docs/06-mcp-server.md
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd
import pytest

matplotlib.use("Agg")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def nca_run(tmp_path: Path) -> dict:
    """Run NCA on a minimal CSV and return the result dict."""
    from pkplugin.mcp_server import impl_run_nca

    times = [0.0, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0]
    concs = [0.0, 4.0, 8.0, 6.0, 4.0, 2.5, 1.5, 0.5]
    df = pd.DataFrame(
        {
            "subject_id": "S1",
            "time": times,
            "concentration": concs,
            "analyte": "drug",
            "dose": 100.0,
        }
    )
    csv_path = tmp_path / "conc.csv"
    df.to_csv(csv_path, index=False)

    result = impl_run_nca(
        dataset_path=str(csv_path),
        config={"winnonlin_version": "6.4"},
        audit_dir=str(tmp_path / "audit"),
    )
    assert result["status"] == "ok", f"NCA failed: {result.get('error')}"
    return result


@pytest.fixture()
def be_run(tmp_path: Path) -> dict:
    """Run BE on a minimal CSV and return the result dict."""
    from pkplugin.mcp_server import impl_run_be

    df = pd.DataFrame(
        {
            "subject_id": ["S1", "S2", "S3", "S4", "S5", "S6", "S1", "S2", "S3", "S4", "S5", "S6"],
            "period": ["1"] * 6 + ["2"] * 6,
            "sequence": ["TR", "TR", "TR", "RT", "RT", "RT"] * 2,
            "treatment": ["T", "T", "T", "R", "R", "R", "R", "R", "R", "T", "T", "T"],
            "AUClast": [
                110.0,
                105.0,
                115.0,
                100.0,
                98.0,
                102.0,
                95.0,
                100.0,
                105.0,
                112.0,
                108.0,
                117.0,
            ],
        }
    )
    csv_path = tmp_path / "params.csv"
    df.to_csv(csv_path, index=False)

    result = impl_run_be(
        parameter_dataset_path=str(csv_path),
        endpoint="AUClast",
        design="crossover_2x2",
        audit_dir=str(tmp_path / "audit"),
    )
    assert result["status"] == "ok", f"BE failed: {result.get('error')}"
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_generate_report_nca_html(tmp_path: Path, nca_run: dict) -> None:
    """Generate HTML report from an NCA run and verify file is created."""
    from pkplugin.mcp_server import impl_generate_report

    run_id = nca_run["run_id"]
    audit_dir = str(tmp_path / "audit")

    result = impl_generate_report(
        run_id=run_id,
        format="html",
        audit_dir=audit_dir,
    )

    assert result["status"] == "ok", f"generate_report failed: {result.get('error')}"
    assert result["format"] == "html"
    report_path = Path(result["report_path"])
    assert report_path.exists(), f"Report file not found: {report_path}"
    html = report_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html" in html
    assert run_id in html


def test_generate_report_be_html(tmp_path: Path, be_run: dict) -> None:
    """Generate HTML report from a BE run and verify file is created."""
    from pkplugin.mcp_server import impl_generate_report

    run_id = be_run["run_id"]
    audit_dir = str(tmp_path / "audit")

    result = impl_generate_report(
        run_id=run_id,
        format="html",
        audit_dir=audit_dir,
    )

    assert result["status"] == "ok", f"generate_report failed: {result.get('error')}"
    report_path = Path(result["report_path"])
    assert report_path.exists()
    html = report_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html" in html
    assert "BE" in html or "Bioequivalence" in html or "report" in html.lower()


def test_generate_report_invalid_format(tmp_path: Path, nca_run: dict) -> None:
    """Invalid format returns error status."""
    from pkplugin.mcp_server import impl_generate_report

    result = impl_generate_report(
        run_id=nca_run["run_id"],
        format="word",
        audit_dir=str(tmp_path / "audit"),
    )
    assert result["status"] == "error"
    assert "format" in result["error"].lower() or "word" in result["error"].lower()


def test_generate_report_missing_run_id(tmp_path: Path) -> None:
    """Missing run_id returns error status."""
    from pkplugin.mcp_server import impl_generate_report

    result = impl_generate_report(
        run_id="nonexistent-run-id-xyz",
        format="html",
        audit_dir=str(tmp_path / "audit"),
    )
    assert result["status"] == "error"
