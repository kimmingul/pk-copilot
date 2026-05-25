"""
Golden regression tests for the NCA engine against a synthetic Bateman-equation
dataset (3 subjects, 1-compartment oral first-order absorption).

Fixture: tests/fixtures/theophylline.csv
Golden:  tests/golden/theophylline/expected.json

Refs:
- docs/03-algorithms/01-nca-parameters.md
- docs/08-validation-strategy.md §2.3
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from pkplugin.ingest import load_dataset
from pkplugin.nca.engine import calculate_nca
from pkplugin.schemas import ConcentrationRecord, DoseRecord, NCAConfig

FIXTURE_DIR = Path(__file__).parent / "fixtures"
GOLDEN_DIR = Path(__file__).parent / "golden" / "theophylline"


def _load_records(
    df: pd.DataFrame,
    raw_csv_path: Path,
) -> tuple[list[ConcentrationRecord], list[DoseRecord]]:
    """Build ConcentrationRecord and DoseRecord lists from the canonical DataFrame.

    The ``dose`` column is read from the raw CSV because load_dataset only
    returns concentration-side canonical columns.
    """
    conc_records: list[ConcentrationRecord] = [
        ConcentrationRecord(
            subject_id=str(row["subject_id"]),
            time=float(row["time"]),
            concentration=float(row["concentration"]) if pd.notna(row["concentration"]) else None,
            bloq=False,
        )
        for _, row in df.iterrows()
    ]

    # Read dose from the raw CSV (load_dataset drops non-canonical columns)
    raw = pd.read_csv(raw_csv_path)
    dose_records: list[DoseRecord] = []
    for sid, sub in raw.groupby("subject_id"):
        dose = float(sub["dose"].iloc[0])
        dose_records.append(DoseRecord(subject_id=str(sid), time=0.0, amount=dose, route="oral"))

    return conc_records, dose_records


@pytest.mark.golden
def test_theophylline_per_subject_parameters() -> None:
    """Each subject's NCA parameters match the engine-generated golden values within tolerance."""
    df, _ = load_dataset(FIXTURE_DIR / "theophylline.csv")
    expected = json.loads((GOLDEN_DIR / "expected.json").read_text())
    config = NCAConfig(winnonlin_version=expected["winnonlin_version"])

    conc_records, dose_records = _load_records(df, FIXTURE_DIR / "theophylline.csv")

    results = calculate_nca(conc_records, dose_records, config)
    assert len(results) == len(expected["expected"]), (
        f"Expected {len(expected['expected'])} subjects, got {len(results)}"
    )

    tol = expected["tolerance"]

    for r in results:
        assert r.subject_id in expected["expected"], (
            f"Subject {r.subject_id!r} not found in golden expected"
        )
        exp = expected["expected"][r.subject_id]

        for param, exp_val in exp.items():
            actual = r.parameters.get(param)
            assert actual is not None, (
                f"{r.subject_id}: parameter {param!r} is None in engine output"
            )
            assert exp_val != 0, (
                f"{r.subject_id} {param}: golden expected value is zero — use absolute tolerance"
            )
            rel_key = f"{param.lower()}_relative"
            rel_tol = tol.get(rel_key, tol["default_relative"])
            rel_err = abs((actual - exp_val) / exp_val)
            assert rel_err < rel_tol, (
                f"{r.subject_id} {param}: actual={actual!r} expected={exp_val!r} "
                f"rel_err={rel_err:.3e} > tol={rel_tol:.3e}"
            )


@pytest.mark.golden
def test_theophylline_version_consistency() -> None:
    """v6.4 and v8.3 produce identical results for this dataset (same algorithm defaults)."""
    df, _ = load_dataset(FIXTURE_DIR / "theophylline.csv")
    conc_records, dose_records = _load_records(df, FIXTURE_DIR / "theophylline.csv")

    r64 = calculate_nca(conc_records, dose_records, NCAConfig(winnonlin_version="6.4"))
    r83 = calculate_nca(conc_records, dose_records, NCAConfig(winnonlin_version="8.3"))

    assert len(r64) == len(r83), f"Subject count differs: v6.4={len(r64)}, v8.3={len(r83)}"

    for a, b in zip(r64, r83):
        assert a.subject_id == b.subject_id, (
            f"Subject order mismatch: {a.subject_id} vs {b.subject_id}"
        )
        for k in a.parameters:
            va = a.parameters[k]
            vb = b.parameters.get(k)
            if va is None and vb is None:
                continue
            assert va is not None and vb is not None, (
                f"{a.subject_id} {k!r}: one version returned None (v6.4={va}, v8.3={vb})"
            )
            denom = max(abs(va), 1e-12)
            rel_diff = abs((va - vb) / denom)
            assert rel_diff < 1e-12, (
                f"{a.subject_id} {k!r}: v6.4={va!r} v8.3={vb!r} rel_diff={rel_diff:.3e}"
            )
