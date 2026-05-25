#!/usr/bin/env python
# type: ignore
"""
Regenerate golden expected.json files by running the current engine.

Usage:
    python scripts/golden_regen.py [version]    # e.g. 5.3, 6.4, 8.3, all

This OVERWRITES the existing expected.json — use only when you have made an
intentional algorithm change and are accepting the new behavior as the new
golden.  Review the diff carefully before committing.

The script re-reads the input CSV named in the existing expected.json (field
"input_csv"), runs the engine with the version's defaults, and writes the
resulting parameter values back into expected.json.  The "must_not_contain" /
"must_contain" / "description" / "fixture" / "config" fields are preserved
as-is; only the "expected" block is overwritten.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — allow running from repo root or scripts/
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from pkplugin.nca.engine import calculate_nca_subject  # noqa: E402
from pkplugin.schemas import ConcentrationRecord, DoseRecord, NCAConfig  # noqa: E402

GOLDEN_ROOT = _REPO_ROOT / "tests" / "golden"
SUPPORTED_VERSIONS = ["5.3", "6.4", "8.3"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_csv_records(csv_path):
    concs = []
    dose_amount = None
    route = "iv_bolus"
    subject_id = "S001"

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

    assert dose_amount is not None, f"No dose column in {csv_path}"
    dose_rec = DoseRecord(
        subject_id=subject_id,
        time=0.0,
        amount=dose_amount,
        route=route,
    )
    return concs, dose_rec


def _regen_version(version):
    golden_dir = GOLDEN_ROOT / f"winnonlin-{version}"
    golden_file = golden_dir / "expected.json"

    if not golden_file.exists():
        print(f"  [SKIP] {golden_file} does not exist — nothing to regenerate.")
        return

    existing = json.loads(golden_file.read_text())
    csv_name = existing["input_csv"]
    csv_path = golden_dir / csv_name

    if not csv_path.exists():
        print(f"  [ERROR] Input CSV not found: {csv_path}")
        sys.exit(1)

    print(f"  Loading {csv_path} ...")
    concs, dose = _load_csv_records(csv_path)

    print(f"  Running engine with winnonlin_version={version!r} ...")
    cfg = NCAConfig(winnonlin_version=version)
    result = calculate_nca_subject(concs, dose, cfg)

    # Rebuild expected block — preserve exact float values from engine
    new_expected = {}
    for subject_id_key in existing.get("expected", {}):
        if subject_id_key == result.subject_id:
            params_out = {}
            for param, val in result.parameters.items():
                params_out[param] = val  # float or None
            new_expected[result.subject_id] = params_out
        else:
            # Multi-subject golden: keep old values for subjects not in this run
            new_expected[subject_id_key] = existing["expected"][subject_id_key]

    existing["expected"] = new_expected

    golden_file.write_text(json.dumps(existing, indent=2) + "\n")
    print(f"  [OK] Wrote {golden_file}")

    # Print summary of changed parameters
    old_expected = existing.get("expected", {}).get(result.subject_id, {})
    for param, new_val in new_expected.get(result.subject_id, {}).items():
        old_val = old_expected.get(param, "<missing>")
        if old_val != new_val:
            print(f"       {param}: {old_val!r} → {new_val!r}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    args = sys.argv[1:]
    if not args or args[0] == "all":
        versions = SUPPORTED_VERSIONS
    else:
        requested = args[0].strip()
        if requested not in SUPPORTED_VERSIONS:
            print(
                f"Unknown version {requested!r}. "
                f"Supported: {SUPPORTED_VERSIONS} or 'all'."
            )
            sys.exit(1)
        versions = [requested]

    print(f"Regenerating golden files for versions: {versions}")
    for version in versions:
        print(f"\n--- v{version} ---")
        _regen_version(version)

    print("\nDone. Review the diff before committing:")
    print("  git diff tests/golden/")


if __name__ == "__main__":
    main()
