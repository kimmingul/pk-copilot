"""
Tests for pkplugin.report.html.

Covers:
- render_html_report: file exists, contains expected sections
- Embedded images are base64-encoded
- Disclaimer footer present
- render_nca_report and render_be_report smoke tests

Refs: docs/02-roadmap.md v0.5
"""

from __future__ import annotations

import base64
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_nca_results() -> list:
    from pkplugin.nca.engine import calculate_nca
    from pkplugin.schemas import ConcentrationRecord, DoseRecord, NCAConfig

    times = [0.0, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0]
    concs = [0.0, 4.0, 8.0, 6.0, 4.0, 2.5, 1.5, 0.5]
    records = [
        ConcentrationRecord(subject_id="S1", time=t, concentration=c, analyte="drug")
        for t, c in zip(times, concs)
    ]
    dose = [DoseRecord(subject_id="S1", time=0.0, amount=100.0, route="oral")]
    return list(calculate_nca(records, dose, NCAConfig()))


def _make_be_result():
    import pandas as pd

    from pkplugin.nca.bioequivalence import run_bioequivalence

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
    return run_bioequivalence(df, endpoint="AUClast", design="crossover_2x2")


# ---------------------------------------------------------------------------
# Test 1: render_html_report — file exists, basic structure
# ---------------------------------------------------------------------------


def test_render_html_report_file_exists(tmp_path: Path) -> None:
    from pkplugin.report.html import render_html_report

    out = tmp_path / "report.html"
    result = render_html_report(
        title="Test Report",
        metadata={"run_id": "test-001", "version": "0.5.0"},
        sections=[
            {"heading": "Section A", "content_html": "<p>Hello world</p>", "plot_paths": []},
        ],
        output_path=out,
    )
    assert result == out.resolve()
    assert out.exists()
    assert out.stat().st_size > 500


def test_render_html_report_contains_sections(tmp_path: Path) -> None:
    from pkplugin.report.html import render_html_report

    out = tmp_path / "report2.html"
    render_html_report(
        title="Section Test",
        metadata={},
        sections=[
            {
                "heading": "First Section",
                "content_html": "<p>Section one content</p>",
                "plot_paths": [],
            },
            {
                "heading": "Second Section",
                "content_html": "<p>Section two content</p>",
                "plot_paths": [],
            },
        ],
        output_path=out,
    )
    html = out.read_text(encoding="utf-8")
    assert "First Section" in html
    assert "Section one content" in html
    assert "Second Section" in html
    assert "Section two content" in html


def test_render_html_report_disclaimer_present(tmp_path: Path) -> None:
    from pkplugin.report.html import render_html_report

    out = tmp_path / "disclaimer.html"
    render_html_report(
        title="Disclaimer Test",
        metadata={},
        sections=[],
        output_path=out,
    )
    html = out.read_text(encoding="utf-8")
    assert "docs/10-21cfr-part11.md" in html
    assert "Disclaimer" in html


def test_render_html_report_embedded_image(tmp_path: Path) -> None:
    from pkplugin.report.html import render_html_report
    from pkplugin.report.plots import plot_concentration_time

    # Create a real PNG
    t = np.linspace(0, 12, 10)
    c = np.exp(-0.2 * t) * 5
    img_path = tmp_path / "test_plot.png"
    plot_concentration_time(t, c, img_path)

    out = tmp_path / "with_image.html"
    render_html_report(
        title="Image Test",
        metadata={},
        sections=[
            {
                "heading": "Plot Section",
                "content_html": "",
                "plot_paths": [str(img_path)],
            }
        ],
        output_path=out,
    )
    html = out.read_text(encoding="utf-8")
    # Check for base64 data URI
    assert "data:image/png;base64," in html
    # Verify it's valid base64 by extracting and decoding
    start = html.index("data:image/png;base64,") + len("data:image/png;base64,")
    end = html.index('"', start)
    b64_data = html[start:end]
    decoded = base64.b64decode(b64_data)
    assert decoded[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# Test 2: render_nca_report
# ---------------------------------------------------------------------------


def test_render_nca_report_file_exists(tmp_path: Path) -> None:
    from pkplugin.report.html import render_nca_report

    results = _make_nca_results()
    out = tmp_path / "nca_report.html"
    result = render_nca_report(
        results=results,
        run_id="test-run-001",
        output_path=out,
        include_plots=False,
    )
    assert result.exists()
    html = out.read_text(encoding="utf-8")
    assert "NCA" in html
    assert "test-run-001" in html


# ---------------------------------------------------------------------------
# Test 3: render_be_report
# ---------------------------------------------------------------------------


def test_render_be_report_file_exists(tmp_path: Path) -> None:
    from pkplugin.report.html import render_be_report

    be = _make_be_result()
    out = tmp_path / "be_report.html"
    result = render_be_report(be_result=be, output_path=out)
    assert result.exists()
    html = out.read_text(encoding="utf-8")
    assert "Bioequivalence" in html
    assert "GMR" in html or "gmr" in html.lower() or "90" in html


def test_render_be_report_verdict_present(tmp_path: Path) -> None:
    from pkplugin.report.html import render_be_report

    be = _make_be_result()
    out = tmp_path / "be_verdict.html"
    render_be_report(be_result=be, output_path=out)
    html = out.read_text(encoding="utf-8")
    # Should contain either pass or fail verdict class
    assert "verdict-pass" in html or "verdict-fail" in html or "verdict-na" in html
