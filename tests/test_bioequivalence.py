"""
Tests for pkplugin.nca.bioequivalence.

Covers:
  1. FDA BE guidance-style synthetic 2x2 crossover (GMR ≈ 0.98, CI within 90–110%)
  2. Parallel design with N=20 per arm; Welch t and CI
  3. Auto-detection of treatment labels (multiple conventions)
  4. Log-transform skips non-positive rows, emits warning
  5. BE not demonstrated when CI extends beyond 125%
  6. Sequence effect detected (p < 0.05)
  7. Period effect detected
  8. Higher within-subject CV → wider CI
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

warnings.filterwarnings("ignore", category=FutureWarning, module="statsmodels")

from pkplugin.nca.bioequivalence import BEResult, run_bioequivalence

# ---------------------------------------------------------------------------
# Synthetic data generator
# ---------------------------------------------------------------------------


def make_2x2_crossover_data(
    n_per_sequence: int = 12,
    gmr: float = 1.0,
    within_subject_cv_pct: float = 20.0,
    between_subject_cv_pct: float = 30.0,
    period_effect: float = 0.0,
    seq_effect: float = 0.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate a synthetic 2x2 crossover dataset.

    Returns long-format DataFrame with columns:
      subject_id, sequence ("TR"/"RT"), period (1/2), treatment ("T"/"R"), AUC0_t.

    Parameters
    ----------
    n_per_sequence:
        Number of subjects per sequence arm (total N = 2 * n_per_sequence).
    gmr:
        True geometric mean ratio (Test / Reference).
    within_subject_cv_pct:
        Within-subject CV% on the natural-log scale.
    between_subject_cv_pct:
        Between-subject CV% on the natural-log scale.
    period_effect:
        Additive log-scale period 2 effect (0 = no period effect).
    seq_effect:
        Additive log-scale RT-sequence effect (0 = no sequence effect).
    seed:
        Random seed for reproducibility.
    """
    rng = np.random.default_rng(seed)

    sigma_w = np.log1p(within_subject_cv_pct / 100.0)
    sigma_b = np.log1p(between_subject_cv_pct / 100.0)
    mu_ref = np.log(100.0)  # log-scale reference mean (100 ng·hr/mL)
    mu_test = mu_ref + np.log(gmr)

    rows = []
    for seq_idx, (seq_label, order) in enumerate([("TR", ["T", "R"]), ("RT", ["R", "T"])]):
        for i in range(n_per_sequence):
            subj_id = f"S{seq_idx * n_per_sequence + i + 1:03d}"
            # between-subject random effect
            b_i = rng.normal(0.0, sigma_b)
            for period_num, trt in enumerate(order, start=1):
                mu = mu_test if trt == "T" else mu_ref
                # period and sequence fixed effects
                p_eff = period_effect if period_num == 2 else 0.0
                s_eff = seq_effect if seq_label == "RT" else 0.0
                # within-subject residual
                eps = rng.normal(0.0, sigma_w)
                ln_y = mu + b_i + p_eff + s_eff + eps
                rows.append(
                    {
                        "subject_id": subj_id,
                        "sequence": seq_label,
                        "period": period_num,
                        "treatment": trt,
                        "AUC0_t": np.exp(ln_y),
                    }
                )

    return pd.DataFrame(rows)


def make_parallel_data(
    n_per_arm: int = 20,
    gmr: float = 1.0,
    cv_pct: float = 25.0,
    seed: int = 7,
) -> pd.DataFrame:
    """Generate a synthetic parallel-design dataset (one observation per subject)."""
    rng = np.random.default_rng(seed)
    sigma = np.log1p(cv_pct / 100.0)
    mu_ref = np.log(100.0)
    mu_test = mu_ref + np.log(gmr)

    rows = []
    for i in range(n_per_arm):
        rows.append(
            {
                "subject_id": f"T{i + 1:03d}",
                "treatment": "T",
                "period": 1,
                "sequence": "T",
                "AUC0_t": np.exp(rng.normal(mu_test, sigma)),
            }
        )
    for i in range(n_per_arm):
        rows.append(
            {
                "subject_id": f"R{i + 1:03d}",
                "treatment": "R",
                "period": 1,
                "sequence": "R",
                "AUC0_t": np.exp(rng.normal(mu_ref, sigma)),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Test 1 — FDA guidance-style crossover: GMR ≈ 0.98, CI within 90–110%
# ---------------------------------------------------------------------------


def test_crossover_2x2_be_demonstrated() -> None:
    """24-subject 2x2 crossover with GMR ≈ 0.98 should demonstrate BE."""
    df = make_2x2_crossover_data(
        n_per_sequence=12,
        gmr=0.98,
        within_subject_cv_pct=15.0,
        between_subject_cv_pct=25.0,
        seed=42,
    )
    result = run_bioequivalence(df, "AUC0_t", design="crossover_2x2")

    assert isinstance(result, BEResult)
    assert result.design == "crossover_2x2"
    assert result.n_subjects == 24
    assert result.n_completers == 24
    assert result.be_demonstrated is True
    # GMR should be close to 98% (within ±5%)
    assert 93.0 <= result.gmr_pct <= 103.0, f"GMR={result.gmr_pct:.2f}"
    # CI must sit within 90–110% (tight CV, moderate GMR)
    assert result.ci_90_low_pct >= 90.0, f"CI_low={result.ci_90_low_pct:.2f}"
    assert result.ci_90_high_pct <= 110.0, f"CI_high={result.ci_90_high_pct:.2f}"
    assert result.be_window == (80.0, 125.0)
    assert result.transformation == "log"
    assert result.within_subject_cv_pct is not None
    assert result.within_subject_cv_pct > 0.0


# ---------------------------------------------------------------------------
# Test 2 — Parallel design with N=20 per arm
# ---------------------------------------------------------------------------


def test_parallel_design_welch() -> None:
    """Parallel design: Welch t-test; result must have finite CI and correct method."""
    df = make_parallel_data(n_per_arm=20, gmr=1.02, cv_pct=20.0, seed=7)
    result = run_bioequivalence(df, "AUC0_t", design="parallel")

    assert result.design == "parallel"
    assert result.n_subjects == 40
    assert result.n_completers == 40
    assert math.isfinite(result.ci_90_low_pct)
    assert math.isfinite(result.ci_90_high_pct)
    assert result.ci_90_low_pct < result.gmr_pct < result.ci_90_high_pct
    assert result.within_subject_cv_pct is None  # undefined for parallel
    # Satterthwaite df should be close to (n-2) = 38 for equal arms
    assert 30.0 <= result.df <= 45.0
    assert result.be_demonstrated is True


# ---------------------------------------------------------------------------
# Test 3 — Auto-detection of labels (several conventions)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "test_val,ref_val",
    [
        ("Test", "Reference"),
        ("test", "reference"),
        ("T", "R"),
        ("t", "r"),
    ],
)
def test_label_autodetection(test_val: str, ref_val: str) -> None:
    """Auto-detection must work for several treatment label conventions."""
    df = make_2x2_crossover_data(n_per_sequence=8, seed=1)
    # Rename treatments to the parametrised convention
    df["treatment"] = df["treatment"].map({"T": test_val, "R": ref_val})

    result = run_bioequivalence(df, "AUC0_t", design="crossover_2x2")
    assert result.test_label == test_val
    assert result.reference_label == ref_val


# ---------------------------------------------------------------------------
# Test 4 — Non-positive rows skipped + warning emitted
# ---------------------------------------------------------------------------


def test_nonpositive_rows_dropped_with_warning() -> None:
    """Non-positive endpoint values dropped with drop_invalid=True; warning recorded."""
    df = make_2x2_crossover_data(n_per_sequence=12, seed=5)
    # Inject a few non-positive values
    df_mod = df.copy()
    df_mod.loc[df_mod.index[:3], "AUC0_t"] = -1.0

    result = run_bioequivalence(df_mod, "AUC0_t", design="crossover_2x2", drop_invalid=True)

    assert any("non-positive" in w.lower() for w in result.warnings), (
        f"Expected 'non-positive' warning, got: {result.warnings}"
    )
    # n_completers should be reduced
    assert result.n_subjects <= 24


def test_nonpositive_rows_raise_by_default() -> None:
    """Non-positive endpoint values raise ValueError by default (drop_invalid=False)."""
    df = make_2x2_crossover_data(n_per_sequence=12, seed=5)
    df_mod = df.copy()
    df_mod.loc[df_mod.index[:3], "AUC0_t"] = -1.0

    with pytest.raises(ValueError, match="non-positive"):
        run_bioequivalence(df_mod, "AUC0_t", design="crossover_2x2")


# ---------------------------------------------------------------------------
# Test 5 — BE NOT demonstrated when CI extends beyond 125%
# ---------------------------------------------------------------------------


def test_be_not_demonstrated_wide_ci() -> None:
    """Large GMR (1.35) or high CV should push CI outside the BE window."""
    df = make_2x2_crossover_data(
        n_per_sequence=6,  # small N → wide CI
        gmr=1.35,
        within_subject_cv_pct=40.0,
        seed=99,
    )
    result = run_bioequivalence(df, "AUC0_t", design="crossover_2x2")

    assert result.be_demonstrated is False, (
        f"Expected BE not demonstrated, but CI=[{result.ci_90_low_pct:.1f}, "
        f"{result.ci_90_high_pct:.1f}], GMR={result.gmr_pct:.1f}"
    )


# ---------------------------------------------------------------------------
# Test 6 — Sequence effect detected (p < 0.05)
# ---------------------------------------------------------------------------


def test_sequence_effect_detected() -> None:
    """A large sequence effect should be reflected in the ANOVA table."""
    df = make_2x2_crossover_data(
        n_per_sequence=20,
        gmr=1.0,
        within_subject_cv_pct=15.0,
        seq_effect=0.8,  # large log-scale sequence effect
        seed=10,
    )
    result = run_bioequivalence(df, "AUC0_t", design="crossover_2x2")

    assert "sequence" in result.anova_table, f"ANOVA table missing 'sequence': {result.anova_table}"
    p_seq = result.anova_table["sequence"]["p"]
    assert p_seq < 0.05, f"Expected sequence p < 0.05, got p={p_seq:.4f}"


# ---------------------------------------------------------------------------
# Test 7 — Period effect detected
# ---------------------------------------------------------------------------


def test_period_effect_detected() -> None:
    """A large period effect should be reflected in the ANOVA table."""
    df = make_2x2_crossover_data(
        n_per_sequence=20,
        gmr=1.0,
        within_subject_cv_pct=15.0,
        period_effect=0.8,  # large log-scale period effect
        seed=11,
    )
    result = run_bioequivalence(df, "AUC0_t", design="crossover_2x2")

    assert "period" in result.anova_table, f"ANOVA table missing 'period': {result.anova_table}"
    p_per = result.anova_table["period"]["p"]
    assert p_per < 0.05, f"Expected period p < 0.05, got p={p_per:.4f}"


# ---------------------------------------------------------------------------
# Test 8 — Higher within-subject CV → wider CI
# ---------------------------------------------------------------------------


def test_higher_cv_wider_ci() -> None:
    """Increasing within-subject CV must produce a wider 90% CI."""
    base_kwargs = dict(n_per_sequence=16, gmr=1.0, seed=20)

    df_low = make_2x2_crossover_data(within_subject_cv_pct=10.0, **base_kwargs)
    df_high = make_2x2_crossover_data(within_subject_cv_pct=35.0, **base_kwargs)

    res_low = run_bioequivalence(df_low, "AUC0_t", design="crossover_2x2")
    res_high = run_bioequivalence(df_high, "AUC0_t", design="crossover_2x2")

    ci_width_low = res_low.ci_90_high_pct - res_low.ci_90_low_pct
    ci_width_high = res_high.ci_90_high_pct - res_high.ci_90_low_pct

    assert ci_width_high > ci_width_low, (
        f"Expected wider CI for high CV. "
        f"low CV width={ci_width_low:.2f}, high CV width={ci_width_high:.2f}"
    )
    assert res_high.within_subject_cv_pct is not None
    assert res_low.within_subject_cv_pct is not None
    assert res_high.within_subject_cv_pct > res_low.within_subject_cv_pct


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------


def test_explicit_labels_override_autodetection() -> None:
    """Explicit test_label / reference_label must override auto-detection."""
    df = make_2x2_crossover_data(n_per_sequence=10, seed=3)
    result = run_bioequivalence(
        df,
        "AUC0_t",
        design="crossover_2x2",
        test_label="T",
        reference_label="R",
    )
    assert result.test_label == "T"
    assert result.reference_label == "R"


def test_be_window_custom() -> None:
    """Custom BE window (90, 111) should be stored and used for decision."""
    df = make_2x2_crossover_data(n_per_sequence=12, gmr=1.0, seed=42)
    result = run_bioequivalence(df, "AUC0_t", design="crossover_2x2", be_window=(90.0, 111.0))
    assert result.be_window == (90.0, 111.0)
    # With GMR=1 and tight window the decision should match CI containment
    expected = result.ci_90_low_pct >= 90.0 and result.ci_90_high_pct <= 111.0
    assert result.be_demonstrated == expected


def test_missing_columns_raises() -> None:
    """Missing required columns must raise ValueError."""
    df = pd.DataFrame({"subject_id": ["A"], "treatment": ["T"], "AUC0_t": [100.0]})
    with pytest.raises(ValueError, match="Missing required columns"):
        run_bioequivalence(df, "AUC0_t", design="crossover_2x2")


def test_unsupported_design_raises() -> None:
    """Unsupported design string must raise ValueError."""
    df = make_2x2_crossover_data(n_per_sequence=6, seed=1)
    with pytest.raises(ValueError, match="not implemented"):
        run_bioequivalence(df, "AUC0_t", design="replicate_2x4")  # type: ignore[arg-type]


def test_untransformed_raises_not_implemented() -> None:
    """transformation='untransformed' must raise NotImplementedError (M5 / FDA guidance)."""
    df = make_2x2_crossover_data(n_per_sequence=8, seed=1)
    with pytest.raises(NotImplementedError, match="untransformed"):
        run_bioequivalence(df, "AUC0_t", design="crossover_2x2", transformation="untransformed")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# C1 regression: GMR direction must be Test/Reference, not Reference/Test
# ---------------------------------------------------------------------------


def test_gmr_direction_t_greater_than_r() -> None:
    """C1 regression: T mean = 2x R mean → GMR must be 200%, not 50%.

    This test encodes the original bug: when reference_label='R' contained
    the letter 'R' which matched the 'treatment' substring in Patsy coefficient
    names, the sign was flipped and T=2, R=1 gave GMR=50% instead of 200%.
    """
    rng = np.random.default_rng(1234)
    # Construct a 2x2 crossover where T is exactly 2× R on log scale.
    # Use very low within-subject CV so the GMR is tightly estimated.
    sigma_w = 0.01
    sigma_b = 0.05
    n = 14  # 14 per sequence = 28 total

    rows = []
    for seq_idx, (seq_label, order) in enumerate([("TR", ["T", "R"]), ("RT", ["R", "T"])]):
        for i in range(n):
            subj_id = f"S{seq_idx * n + i + 1:03d}"
            b_i = rng.normal(0.0, sigma_b)
            for period_num, trt in enumerate(order, start=1):
                # T mean = ln(2), R mean = 0 → GMR = e^ln(2) = 2.0 = 200%
                mu = math.log(2.0) if trt == "T" else 0.0
                eps = rng.normal(0.0, sigma_w)
                ln_y = mu + b_i + eps
                rows.append(
                    {
                        "subject_id": subj_id,
                        "sequence": seq_label,
                        "period": period_num,
                        "treatment": trt,
                        "AUC0_t": math.exp(ln_y),
                    }
                )

    df = pd.DataFrame(rows)
    result = run_bioequivalence(
        df,
        "AUC0_t",
        design="crossover_2x2",
        test_label="T",
        reference_label="R",
    )

    # GMR must be ~200%, not ~50%.
    assert result.gmr_pct == pytest.approx(200.0, abs=5.0), (
        f"GMR={result.gmr_pct:.2f}% — expected ~200%, not ~50% (sign-flip bug C1)"
    )
    assert result.gmr_pct > 150.0, (
        f"GMR={result.gmr_pct:.2f}% is too low — C1 sign-flip bug may be present"
    )


# ---------------------------------------------------------------------------
# H2 regression: subject_id reused across sequences must raise ValueError
# ---------------------------------------------------------------------------


def test_subject_id_reused_across_sequences_raises() -> None:
    """H2 regression: subject_id shared between TR and RT sequences raises ValueError."""
    df = make_2x2_crossover_data(n_per_sequence=6, seed=1)
    # Corrupt: rename all RT-sequence subjects to the same IDs as TR subjects.
    df_bad = df.copy()
    tr_ids = df_bad.loc[df_bad["sequence"] == "TR", "subject_id"].unique()
    rt_mask = df_bad["sequence"] == "RT"
    # Reassign RT subjects to reuse TR subject IDs
    rt_subjects = df_bad.loc[rt_mask, "subject_id"].unique()
    id_map = {rt_id: tr_ids[i % len(tr_ids)] for i, rt_id in enumerate(rt_subjects)}
    df_bad.loc[rt_mask, "subject_id"] = df_bad.loc[rt_mask, "subject_id"].map(id_map)

    with pytest.raises(ValueError, match="reused across sequences"):
        run_bioequivalence(
            df_bad,
            "AUC0_t",
            design="crossover_2x2",
            test_label="T",
            reference_label="R",
        )


# ---------------------------------------------------------------------------
# M3: ambiguous label auto-detection raises ValueError
# ---------------------------------------------------------------------------


def test_ambiguous_labels_raise_value_error() -> None:
    """M3: unknown label pair (not T/R or test/reference) with no explicit labels raises."""
    df = make_2x2_crossover_data(n_per_sequence=6, seed=1)
    df["treatment"] = df["treatment"].map({"T": "Drug_A", "R": "Drug_B"})

    with pytest.raises(ValueError, match="Cannot auto-detect"):
        run_bioequivalence(df, "AUC0_t", design="crossover_2x2")


def test_one_label_provided_infers_other() -> None:
    """M3: providing only test_label infers reference_label from remaining unique value."""
    df = make_2x2_crossover_data(n_per_sequence=8, seed=2)
    result = run_bioequivalence(
        df,
        "AUC0_t",
        design="crossover_2x2",
        test_label="T",
    )
    assert result.test_label == "T"
    assert result.reference_label == "R"


import math
