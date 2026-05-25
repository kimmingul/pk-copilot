"""
Golden cross-version regression tests for pk-copilot NCA engine.

Validates that WinNonlin 5.3 / 6.4 / 8.3 compatibility flags produce:
  - byte-matched results against pre-computed golden expected values
  - the differences documented in the version matrix (docs/04-winnonlin-version-matrix.md)
  - deterministic / reproducible output within each version

Fixture:   tests/golden/winnonlin-*/synthetic_5_3.csv
Golden:    tests/golden/winnonlin-*/expected.json
Diffs ref: tests/golden/cross-version/expected_diffs.json

Refs:
- docs/04-winnonlin-version-matrix.md
- docs/08-validation-strategy.md §2.3
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from pkplugin.nca.engine import calculate_nca_subject
from pkplugin.schemas import ConcentrationRecord, DoseRecord, NCAConfig

# ---------------------------------------------------------------------------
# Directory constants
# ---------------------------------------------------------------------------

GOLDEN_ROOT = Path(__file__).parent / "golden"
GOLDEN_53 = GOLDEN_ROOT / "winnonlin-5.3"
GOLDEN_64 = GOLDEN_ROOT / "winnonlin-6.4"
GOLDEN_83 = GOLDEN_ROOT / "winnonlin-8.3"
GOLDEN_CROSS = GOLDEN_ROOT / "cross-version"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_golden(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())  # type: ignore[return-value]


def _load_csv_records(
    csv_path: Path,
) -> tuple[list[ConcentrationRecord], DoseRecord]:
    """Parse the synthetic CSV into ConcentrationRecord list + one DoseRecord."""
    import csv

    concs: list[ConcentrationRecord] = []
    dose_amount: float | None = None
    route: str = "iv_bolus"
    subject_id: str = "S001"

    with csv_path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            subject_id = row["subject_id"]
            concs.append(
                ConcentrationRecord(
                    subject_id=subject_id,
                    time=float(row["time"]),
                    concentration=float(row["concentration"]),
                    bloq=row["bloq"].strip().lower() == "true",
                )
            )
            if dose_amount is None:
                dose_amount = float(row["dose"])
                route = row["route"].strip()

    assert dose_amount is not None, "No dose found in CSV"
    dose_rec = DoseRecord(
        subject_id=subject_id,
        time=0.0,
        amount=dose_amount,
        route=route,  # type: ignore[arg-type]
    )
    return concs, dose_rec


def _run_engine(
    csv_path: Path, version: str
) -> dict[str, float | None]:
    """Run the NCA engine for one subject and return the parameters dict."""
    concs, dose = _load_csv_records(csv_path)
    cfg = NCAConfig(winnonlin_version=version)  # type: ignore[arg-type]
    result = calculate_nca_subject(concs, dose, cfg)
    return result.parameters


def _assert_matches_golden(
    actual: dict[str, float | None],
    golden: dict[str, object],
    subject: str = "S001",
) -> None:
    """Assert actual parameters match golden expected values within tolerance."""
    expected_params: dict[str, float | None] = golden["expected"][subject]  # type: ignore[index,assignment]
    tol: float = float(golden["tolerance_relative"])  # type: ignore[arg-type]

    for param, exp_val in expected_params.items():
        actual_val = actual.get(param)
        if exp_val is None:
            assert actual_val is None, (
                f"{param}: expected None (not emitted by this version), got {actual_val!r}"
            )
            continue
        assert actual_val is not None, (
            f"{param}: expected {exp_val!r}, engine returned None"
        )
        assert isinstance(actual_val, float)
        assert isinstance(exp_val, float)
        if exp_val == 0.0:
            assert abs(actual_val) < 1e-12, (
                f"{param}: expected 0.0, got {actual_val!r}"
            )
        else:
            rel_err = abs((actual_val - exp_val) / exp_val)
            assert rel_err <= tol, (
                f"{param}: actual={actual_val!r} expected={exp_val!r} "
                f"rel_err={rel_err:.3e} > tol={tol:.3e}"
            )


# ---------------------------------------------------------------------------
# Core golden match tests
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_v5_3_matches_expected() -> None:
    """v5.3 engine output matches the v5.3 golden within tolerance 1e-9."""
    golden = _load_golden(GOLDEN_53 / "expected.json")
    actual = _run_engine(GOLDEN_53 / "synthetic_5_3.csv", "5.3")
    _assert_matches_golden(actual, golden)


@pytest.mark.golden
def test_v6_4_matches_expected() -> None:
    """v6.4 engine output matches the v6.4 golden within tolerance 1e-9."""
    golden = _load_golden(GOLDEN_64 / "expected.json")
    actual = _run_engine(GOLDEN_64 / "synthetic_5_3.csv", "6.4")
    _assert_matches_golden(actual, golden)


@pytest.mark.golden
def test_v8_3_matches_expected() -> None:
    """v8.3 engine output matches the v8.3 golden within tolerance 1e-9."""
    golden = _load_golden(GOLDEN_83 / "expected.json")
    actual = _run_engine(GOLDEN_83 / "synthetic_5_3.csv", "8.3")
    _assert_matches_golden(actual, golden)


# ---------------------------------------------------------------------------
# Pred-variant emission tests
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_v5_3_does_not_emit_pred_variants() -> None:
    """v5.3 must NOT include Clast_pred / AUCINF_pred (output_pred_variants=False per docs/04)."""
    golden = _load_golden(GOLDEN_53 / "expected.json")
    actual = _run_engine(GOLDEN_53 / "synthetic_5_3.csv", "5.3")

    must_not: list[str] = golden["must_not_contain"]  # type: ignore[assignment]
    for param in must_not:
        assert param not in actual, (
            f"v5.3 must NOT emit {param!r}, but it appeared in engine output"
        )


@pytest.mark.golden
def test_v6_4_emits_pred_variants() -> None:
    """v6.4 must include Clast_pred / AUCINF_pred (output_pred_variants=True per docs/04)."""
    golden = _load_golden(GOLDEN_64 / "expected.json")
    actual = _run_engine(GOLDEN_64 / "synthetic_5_3.csv", "6.4")

    must_have: list[str] = golden["must_contain"]  # type: ignore[assignment]
    for param in must_have:
        assert param in actual, (
            f"v6.4 must emit {param!r}, but it was absent from engine output"
        )
        assert actual[param] is not None, (
            f"v6.4 emitted {param!r} but value is None"
        )


@pytest.mark.golden
def test_v8_3_emits_pred_variants() -> None:
    """v8.3 must include Clast_pred / AUCINF_pred (output_pred_variants=True per docs/04)."""
    golden = _load_golden(GOLDEN_83 / "expected.json")
    actual = _run_engine(GOLDEN_83 / "synthetic_5_3.csv", "8.3")

    must_have: list[str] = golden["must_contain"]  # type: ignore[assignment]
    for param in must_have:
        assert param in actual, (
            f"v8.3 must emit {param!r}, but it was absent from engine output"
        )


# ---------------------------------------------------------------------------
# Cross-version difference / consistency tests
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_cross_version_differences_present() -> None:
    """Where the version matrix says results SHOULD differ, they DO."""
    csv_path = GOLDEN_53 / "synthetic_5_3.csv"
    params_53 = _run_engine(csv_path, "5.3")
    params_64 = _run_engine(csv_path, "6.4")
    params_83 = _run_engine(csv_path, "8.3")

    diffs_doc = _load_golden(GOLDEN_CROSS / "expected_diffs.json")
    differences: list[dict[str, object]] = diffs_doc["differences"]  # type: ignore[assignment]

    for entry in differences:
        if not entry["expected_to_differ"]:
            continue
        param = str(entry["parameter"])
        v53 = params_53.get(param)
        v64 = params_64.get(param)
        # At minimum: v5.3 vs v6.4 must differ in value or presence
        assert v53 != v64, (
            f"Parameter {param!r} was expected to differ between v5.3 and v6.4 "
            f"(reason: {entry['reason']!r}), but both returned {v53!r}"
        )


@pytest.mark.golden
def test_cross_version_consistencies_held() -> None:
    """Where the version matrix says results should NOT differ, they do not."""
    csv_path = GOLDEN_53 / "synthetic_5_3.csv"
    params_53 = _run_engine(csv_path, "5.3")
    params_64 = _run_engine(csv_path, "6.4")
    params_83 = _run_engine(csv_path, "8.3")

    diffs_doc = _load_golden(GOLDEN_CROSS / "expected_diffs.json")
    differences: list[dict[str, object]] = diffs_doc["differences"]  # type: ignore[assignment]

    for entry in differences:
        if entry["expected_to_differ"]:
            continue
        param = str(entry["parameter"])
        v53 = params_53.get(param)
        v64 = params_64.get(param)
        v83 = params_83.get(param)

        # None values are equal-to-None
        if v53 is None and v64 is None and v83 is None:
            continue

        assert v53 is not None and v64 is not None and v83 is not None, (
            f"Parameter {param!r} is None in some version: "
            f"v5.3={v53!r}, v6.4={v64!r}, v8.3={v83!r}"
        )
        assert isinstance(v53, float) and isinstance(v64, float) and isinstance(v83, float)

        denom = max(abs(v53), 1e-15)
        assert abs((v53 - v64) / denom) < 1e-9, (
            f"{param!r}: v5.3={v53!r} vs v6.4={v64!r} expected identical "
            f"(reason: {entry['reason']!r})"
        )
        assert abs((v64 - v83) / denom) < 1e-9, (
            f"{param!r}: v6.4={v64!r} vs v8.3={v83!r} expected identical"
        )


@pytest.mark.golden
def test_v6_4_v8_3_byte_identical() -> None:
    """6.4 and 8.3 share all algorithm defaults — results are numerically identical."""
    csv_path = GOLDEN_53 / "synthetic_5_3.csv"
    params_64 = _run_engine(csv_path, "6.4")
    params_83 = _run_engine(csv_path, "8.3")

    assert set(params_64.keys()) == set(params_83.keys()), (
        f"Parameter sets differ: only in 6.4={set(params_64)-set(params_83)}, "
        f"only in 8.3={set(params_83)-set(params_64)}"
    )

    for param in params_64:
        v64 = params_64[param]
        v83 = params_83[param]
        if v64 is None and v83 is None:
            continue
        assert v64 is not None and v83 is not None, (
            f"{param!r}: one version returned None (v6.4={v64!r}, v8.3={v83!r})"
        )
        assert isinstance(v64, float) and isinstance(v83, float)
        # Truly byte-identical (same IEEE 754 bits)
        assert v64 == v83, (
            f"{param!r}: v6.4={v64!r} != v8.3={v83!r} — expected byte-identical"
        )


@pytest.mark.golden
def test_reproducibility_within_version() -> None:
    """Running the same input twice under the same version produces identical results."""
    csv_path = GOLDEN_53 / "synthetic_5_3.csv"

    for version in ("5.3", "6.4", "8.3"):
        run1 = _run_engine(csv_path, version)
        run2 = _run_engine(csv_path, version)

        assert set(run1.keys()) == set(run2.keys()), (
            f"v{version}: parameter key sets differ between runs"
        )
        for param in run1:
            v1, v2 = run1[param], run2[param]
            if v1 is None and v2 is None:
                continue
            assert v1 == v2, (
                f"v{version} {param!r}: run1={v1!r} != run2={v2!r} — not reproducible"
            )
