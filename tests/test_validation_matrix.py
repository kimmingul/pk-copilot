"""
Higher-level validation suite: walks tests/golden/winnonlin-*/expected.json,
loads the input CSV, runs the engine, and diffs against expected values with
parameter-level failure detail.

Refs:
- docs/04-winnonlin-version-matrix.md
- docs/08-validation-strategy.md §2.3
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from pkplugin.nca.engine import calculate_nca_subject
from pkplugin.schemas import ConcentrationRecord, DoseRecord, NCAConfig

GOLDEN_ROOT = Path(__file__).parent / "golden"


def _load_csv_records(
    csv_path: Path,
) -> tuple[list[ConcentrationRecord], DoseRecord]:
    """Parse a golden CSV into ConcentrationRecord list + one DoseRecord."""
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

    assert dose_amount is not None, f"No dose column found in {csv_path}"
    dose_rec = DoseRecord(
        subject_id=subject_id,
        time=0.0,
        amount=dose_amount,
        route=route,  # type: ignore[arg-type]
    )
    return concs, dose_rec


def _collect_failures(
    actual: dict[str, float | None],
    expected_params: dict[str, float | None],
    tol: float,
) -> list[str]:
    """Return a list of human-readable failure messages, empty if all match."""
    failures: list[str] = []
    for param, exp_val in expected_params.items():
        actual_val = actual.get(param)
        if exp_val is None:
            if actual_val is not None:
                failures.append(f"  {param}: expected absent (None), got {actual_val!r}")
            continue
        if actual_val is None:
            failures.append(f"  {param}: expected {exp_val!r}, engine returned None")
            continue
        if not isinstance(actual_val, float) or not isinstance(exp_val, float):
            failures.append(
                f"  {param}: type mismatch actual={type(actual_val)} expected={type(exp_val)}"
            )
            continue
        if exp_val == 0.0:
            if abs(actual_val) >= 1e-12:
                failures.append(f"  {param}: expected 0.0, got {actual_val!r}")
        else:
            rel_err = abs((actual_val - exp_val) / exp_val)
            if rel_err > tol:
                failures.append(
                    f"  {param}: actual={actual_val!r} expected={exp_val!r} "
                    f"rel_err={rel_err:.3e} > tol={tol:.3e}"
                )
    return failures


@pytest.mark.golden
@pytest.mark.parametrize("version", ["5.3", "6.4", "8.3"])
def test_full_golden_matrix(version: str) -> None:
    """Run engine against the version-specific golden expectations.

    Walks tests/golden/winnonlin-<version>/expected.json, loads the input CSV,
    runs the NCA engine, and reports any parameter-level deviations.
    """
    golden_dir = GOLDEN_ROOT / f"winnonlin-{version}"
    golden_file = golden_dir / "expected.json"
    assert golden_file.exists(), (
        f"Golden file not found: {golden_file}. Run scripts/golden_regen.py {version} to create it."
    )

    golden: dict[str, object] = json.loads(golden_file.read_text())  # type: ignore[assignment]
    assert golden["version"] == version, (
        f"Golden file version mismatch: expected {version!r}, got {golden['version']!r}"
    )

    csv_name: str = str(golden["input_csv"])
    csv_path = golden_dir / csv_name
    assert csv_path.exists(), (
        f"Input CSV not found: {csv_path}. Golden file references {csv_name!r} but it is missing."
    )

    tol: float = float(golden["tolerance_relative"])  # type: ignore[arg-type]
    expected_by_subject: dict[str, dict[str, float | None]] = golden["expected"]  # type: ignore[assignment]

    concs, dose = _load_csv_records(csv_path)
    cfg = NCAConfig(winnonlin_version=version)  # type: ignore[arg-type]
    result = calculate_nca_subject(concs, dose, cfg)

    all_failures: list[str] = []

    subject = result.subject_id
    if subject not in expected_by_subject:
        pytest.fail(
            f"Subject {subject!r} in engine output not found in golden "
            f"(golden subjects: {list(expected_by_subject.keys())})"
        )

    failures = _collect_failures(result.parameters, expected_by_subject[subject], tol)
    if failures:
        all_failures.append(f"Subject {subject!r}:")
        all_failures.extend(failures)

    if all_failures:
        pytest.fail(f"Golden matrix failures for v{version}:\n" + "\n".join(all_failures))
