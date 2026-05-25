"""
Tests for the pkplugin CLI (pkplugin.cli.main).

Tests:
  1. pkplugin --version prints "1.0.0".
  2. pkplugin doctor returns exit code 0 and lists numpy/scipy/pandas.
  3. pkplugin sbom produces valid JSON with bomFormat "CycloneDX".
  4. pkplugin nca on a tiny CSV returns exit code 0 and emits results.
  5. pkplugin be on a tiny crossover CSV returns exit code 0.
  6. pkplugin nca on a missing file returns exit code 1.
"""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

from pkplugin.cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """Run main(argv) and return (exit_code, stdout, stderr)."""
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def theophylline_csv() -> Path:
    """Return path to the built-in theophylline fixture."""
    return Path(__file__).parent / "fixtures" / "theophylline.csv"


@pytest.fixture()
def crossover_csv(tmp_path: Path) -> Path:
    """Write a minimal 2x2 crossover parameter CSV and return its path."""
    from tests.test_bioequivalence import make_2x2_crossover_data

    df = make_2x2_crossover_data(
        n_per_sequence=8,
        gmr=0.98,
        within_subject_cv_pct=15.0,
        between_subject_cv_pct=20.0,
        seed=99,
    )
    csv_path = tmp_path / "be_params.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


# ---------------------------------------------------------------------------
# Test 1 — --version
# ---------------------------------------------------------------------------


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """pkplugin --version should print '1.0.0' and raise SystemExit(0)."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "1.0.0" in captured.out


# ---------------------------------------------------------------------------
# Test 2 — doctor
# ---------------------------------------------------------------------------


def test_doctor_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """pkplugin doctor should exit 0 and list numpy/scipy/pandas in output."""
    code, out, _ = _run(["doctor"], capsys)
    assert code == 0
    doc = json.loads(out)
    deps = doc["dependencies"]
    for pkg in ("numpy", "scipy", "pandas"):
        assert pkg in deps, f"Expected {pkg!r} in doctor dependencies"
        assert deps[pkg] != "not installed", f"{pkg} should be installed"


# ---------------------------------------------------------------------------
# Test 3 — sbom
# ---------------------------------------------------------------------------


def test_sbom_valid_cyclonedx_json(capsys: pytest.CaptureFixture[str]) -> None:
    """pkplugin sbom should produce valid JSON with bomFormat 'CycloneDX'."""
    code, out, _ = _run(["sbom"], capsys)
    assert code == 0
    doc = json.loads(out)
    assert doc["bomFormat"] == "CycloneDX"
    assert len(doc["components"]) > 0


# ---------------------------------------------------------------------------
# Test 4 — nca on tiny CSV
# ---------------------------------------------------------------------------


def test_nca_on_fixture_returns_zero(
    theophylline_csv: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """pkplugin nca on theophylline fixture should exit 0 and emit JSON results."""
    code, out, err = _run(
        ["nca", str(theophylline_csv), "--out", str(tmp_path / "audit")],
        capsys,
    )
    assert code == 0, f"Expected exit 0; stderr: {err}"
    doc = json.loads(out)
    assert doc["status"] == "ok"
    assert "run_id" in doc
    assert "parameter_summary" in doc
    assert len(doc["parameter_summary"]) > 0


# ---------------------------------------------------------------------------
# Test 5 — be on crossover CSV
# ---------------------------------------------------------------------------


def test_be_on_crossover_csv_returns_zero(
    crossover_csv: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """pkplugin be on valid crossover CSV should exit 0."""
    code, out, err = _run(
        ["be", str(crossover_csv), "--endpoint", "AUC0_t"],
        capsys,
    )
    assert code == 0, f"Expected exit 0; stderr: {err}"
    doc = json.loads(out)
    assert doc["status"] == "ok"
    assert "be_result" in doc


# ---------------------------------------------------------------------------
# Test 6 — nca on missing file returns 1
# ---------------------------------------------------------------------------


def test_nca_missing_file_returns_one(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """pkplugin nca on a nonexistent file should exit 1."""
    missing = str(tmp_path / "does_not_exist.csv")
    code, out, err = _run(["nca", missing], capsys)
    assert code == 1
