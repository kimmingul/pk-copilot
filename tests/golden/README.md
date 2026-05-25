# Golden Validation Matrix — tests/golden/

This directory contains the v1.0 cross-version golden validation matrix for
pk-copilot's NCA engine. Each sub-directory holds a pre-computed expected
output JSON and the corresponding input CSV.

## Directory layout

```
tests/golden/
├── README.md                         ← this file
├── winnonlin-5.3/
│   ├── synthetic_5_3.csv             ← shared synthetic IV bolus input
│   └── expected.json                 ← engine output under v5.3 defaults
├── winnonlin-6.4/
│   ├── synthetic_5_3.csv             ← same dataset
│   └── expected.json                 ← engine output under v6.4 defaults
├── winnonlin-8.3/
│   ├── synthetic_5_3.csv             ← same dataset
│   └── expected.json                 ← engine output under v8.3 defaults
├── cross-version/
│   └── expected_diffs.json           ← documented parameter-level differences
└── theophylline/
    └── expected.json                 ← separate oral-absorption golden
```

## Synthetic dataset: synthetic_iv_bolus_no_t0

**PK model**: one-compartment IV bolus, C(t) = C0_true · exp(−k·t)

| Parameter | Value  |
|-----------|--------|
| C0_true   | 100 ng/mL |
| k         | 0.15 1/h  |
| Dose      | 100 mg    |
| True HL   | 4.62 h    |
| True AUCINF | 666.67 ng·h/mL |

**Observations**: t = 0.5, 1, 2, 4, 6, 8, 12, 24 h (no t=0 point)

The absence of a t=0 observation forces the C0 estimation branch in the engine
and makes the dataset sensitive to `c0_method` (observed vs log_back_extrap).
The exponential decline makes it sensitive to `auc_method` (linear vs
linear_up_log_down), since the log-down trapezoid is exact for exponential
profiles while the linear trapezoid overestimates.

## Key version differences observed

| Parameter    | v5.3                  | v6.4/v8.3             | Root cause |
|--------------|-----------------------|-----------------------|------------|
| C0           | 92.77 ng/mL (observed)| 100.00 ng/mL (back-extrap) | `c0_method` |
| AUClast      | 675.32 ng·h/mL        | 648.45 ng·h/mL        | `auc_method` + C0 anchor |
| AUCINF_obs   | 693.54 ng·h/mL        | 666.67 ng·h/mL        | derived from AUClast |
| CL           | 0.1442 L/h            | 0.1500 L/h            | dose/AUCINF |
| Clast_pred   | absent                | 2.7324 ng/mL          | `output_pred_variants` |
| AUCINF_pred  | absent                | 666.67 ng·h/mL        | `output_pred_variants` |
| Lambda_z     | 0.1500 (identical)    | 0.1500 (identical)    | same Best Fit |
| HL_Lambda_z  | 4.621 h (identical)   | 4.621 h (identical)   | derived from Lambda_z |

v6.4 and v8.3 are byte-identical (share the same DEFAULTS in version.py).

## How to regenerate

If you make an intentional algorithm change and the golden tests fail, regenerate
with:

```bash
# Regenerate all versions
python scripts/golden_regen.py all

# Regenerate a single version
python scripts/golden_regen.py 5.3
python scripts/golden_regen.py 6.4
python scripts/golden_regen.py 8.3
```

**Warning**: regeneration overwrites `expected.json`. Only do this after
deliberately changing engine behavior and confirming the new output is correct.
Review the diff carefully before committing.

After regeneration, run the full golden suite to confirm:

```bash
.venv/bin/python -m pytest -q -m golden
```

## Adding a new golden dataset

1. Place the input CSV under `tests/golden/winnonlin-<version>/`.
2. Add an `expected.json` following the schema in the existing files.
3. Add a test in `tests/test_golden_cross_version.py` or
   `tests/test_validation_matrix.py`.
4. Update this README.
