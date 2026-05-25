"""
Golden regression test — FDA BE guidance Appendix-style 2x2 crossover.

Dataset: 24 subjects, balanced 12 TR / 12 RT sequences.
AUC values derived deterministically from a log-normal PK model with:
  - Reference mean = 100 ng·hr/mL (log-scale μ = ln 100)
  - GMR = 1.0 by construction (Test μ = Reference μ)
  - Within-subject CV ≈ 3.3% (tight noise, high precision test)
  - No period effect, no sequence effect

Expected results (pinned):
  - GMR ≈ 99.79% (tolerance ±1%)
  - 90% CI: [98.19%, 101.42%] (tolerance ±2% on each bound)
  - BE demonstrated (CI within 80%–125%)
  - Sequence effect p > 0.1 (non-significant)
  - Period   effect p > 0.1 (non-significant)

Run with: pytest -m golden tests/test_golden_be_fda.py
"""

from __future__ import annotations

import warnings

import pandas as pd
import pytest

warnings.filterwarnings("ignore", category=FutureWarning, module="statsmodels")

from pkplugin.nca.bioequivalence import BEResult, run_bioequivalence

# ---------------------------------------------------------------------------
# Hard-coded golden dataset
# 24 subjects × 2 periods = 48 rows.
# Columns: subject_id, sequence, period, treatment, AUC0_t
# ---------------------------------------------------------------------------

_GOLDEN_ROWS: list[dict[str, object]] = [
    # --- TR sequence (subjects S001–S012): Period 1 = T, Period 2 = R ---
    {"subject_id": "S001", "sequence": "TR", "period": 1, "treatment": "T", "AUC0_t": 113.88283833246221},
    {"subject_id": "S001", "sequence": "TR", "period": 2, "treatment": "R", "AUC0_t": 108.32870676749592},
    {"subject_id": "S002", "sequence": "TR", "period": 1, "treatment": "T", "AUC0_t":  85.21437889662116},
    {"subject_id": "S002", "sequence": "TR", "period": 2, "treatment": "R", "AUC0_t":  89.58341352965283},
    {"subject_id": "S003", "sequence": "TR", "period": 1, "treatment": "T", "AUC0_t": 107.25081812542163},
    {"subject_id": "S003", "sequence": "TR", "period": 2, "treatment": "R", "AUC0_t": 102.02013400267558},
    {"subject_id": "S004", "sequence": "TR", "period": 1, "treatment": "T", "AUC0_t": 117.35108709918109},
    {"subject_id": "S004", "sequence": "TR", "period": 2, "treatment": "R", "AUC0_t": 123.36780599567437},
    {"subject_id": "S005", "sequence": "TR", "period": 1, "treatment": "T", "AUC0_t":  93.23938199059484},
    {"subject_id": "S005", "sequence": "TR", "period": 2, "treatment": "R", "AUC0_t":  95.12294245007146},
    {"subject_id": "S006", "sequence": "TR", "period": 1, "treatment": "T", "AUC0_t": 109.41742837052107},
    {"subject_id": "S006", "sequence": "TR", "period": 2, "treatment": "R", "AUC0_t": 111.62780704588721},
    {"subject_id": "S007", "sequence": "TR", "period": 1, "treatment": "T", "AUC0_t":  83.52702114112726},
    {"subject_id": "S007", "sequence": "TR", "period": 2, "treatment": "R", "AUC0_t":  78.66278610665543},
    {"subject_id": "S008", "sequence": "TR", "period": 1, "treatment": "T", "AUC0_t": 105.12710963760253},
    {"subject_id": "S008", "sequence": "TR", "period": 2, "treatment": "R", "AUC0_t": 110.51709180756487},
    {"subject_id": "S009", "sequence": "TR", "period": 1, "treatment": "T", "AUC0_t": 120.92495976572513},
    {"subject_id": "S009", "sequence": "TR", "period": 2, "treatment": "R", "AUC0_t": 115.02737988572274},
    {"subject_id": "S010", "sequence": "TR", "period": 1, "treatment": "T", "AUC0_t":  91.39311852712287},
    {"subject_id": "S010", "sequence": "TR", "period": 2, "treatment": "R", "AUC0_t":  96.07894391523236},
    {"subject_id": "S011", "sequence": "TR", "period": 1, "treatment": "T", "AUC0_t": 105.12710963760243},
    {"subject_id": "S011", "sequence": "TR", "period": 2, "treatment": "R", "AUC0_t": 104.08107741923887},
    {"subject_id": "S012", "sequence": "TR", "period": 1, "treatment": "T", "AUC0_t":  81.87307530779820},
    {"subject_id": "S012", "sequence": "TR", "period": 2, "treatment": "R", "AUC0_t":  80.25187979624783},
    # --- RT sequence (subjects S013–S024): Period 1 = R, Period 2 = T ---
    {"subject_id": "S013", "sequence": "RT", "period": 1, "treatment": "R", "AUC0_t": 112.74968515793763},
    {"subject_id": "S013", "sequence": "RT", "period": 2, "treatment": "T", "AUC0_t": 118.53048513203659},
    {"subject_id": "S014", "sequence": "RT", "period": 1, "treatment": "R", "AUC0_t":  93.23938199059484},
    {"subject_id": "S014", "sequence": "RT", "period": 2, "treatment": "T", "AUC0_t":  88.69204367171578},
    {"subject_id": "S015", "sequence": "RT", "period": 1, "treatment": "R", "AUC0_t": 106.18365465453597},
    {"subject_id": "S015", "sequence": "RT", "period": 2, "treatment": "T", "AUC0_t": 111.62780704588711},
    {"subject_id": "S016", "sequence": "RT", "period": 1, "treatment": "R", "AUC0_t":  86.07079764250578},
    {"subject_id": "S016", "sequence": "RT", "period": 2, "treatment": "T", "AUC0_t":  81.87307530779820},
    {"subject_id": "S017", "sequence": "RT", "period": 1, "treatment": "R", "AUC0_t": 125.86000099294779},
    {"subject_id": "S017", "sequence": "RT", "period": 2, "treatment": "T", "AUC0_t": 119.72173631218104},
    {"subject_id": "S018", "sequence": "RT", "period": 1, "treatment": "R", "AUC0_t":  95.12294245007146},
    {"subject_id": "S018", "sequence": "RT", "period": 2, "treatment": "T", "AUC0_t": 100.00000000000004},
    {"subject_id": "S019", "sequence": "RT", "period": 1, "treatment": "R", "AUC0_t": 109.41742837052107},
    {"subject_id": "S019", "sequence": "RT", "period": 2, "treatment": "T", "AUC0_t": 104.08107741923887},
    {"subject_id": "S020", "sequence": "RT", "period": 1, "treatment": "R", "AUC0_t": 113.88283833246221},
    {"subject_id": "S020", "sequence": "RT", "period": 2, "treatment": "T", "AUC0_t": 119.72173631218104},
    {"subject_id": "S021", "sequence": "RT", "period": 1, "treatment": "R", "AUC0_t":  89.58341352965283},
    {"subject_id": "S021", "sequence": "RT", "period": 2, "treatment": "T", "AUC0_t":  90.48374180359603},
    {"subject_id": "S022", "sequence": "RT", "period": 1, "treatment": "R", "AUC0_t": 106.18365465453606},
    {"subject_id": "S022", "sequence": "RT", "period": 2, "treatment": "T", "AUC0_t": 107.25081812542173},
    {"subject_id": "S023", "sequence": "RT", "period": 1, "treatment": "R", "AUC0_t":  92.31163463866360},
    {"subject_id": "S023", "sequence": "RT", "period": 2, "treatment": "T", "AUC0_t":  88.69204367171578},
    {"subject_id": "S024", "sequence": "RT", "period": 1, "treatment": "R", "AUC0_t": 112.74968515793763},
    {"subject_id": "S024", "sequence": "RT", "period": 2, "treatment": "T", "AUC0_t": 120.92495976572525},
]

# Pinned expected values (computed deterministically from the dataset above)
_EXPECTED_GMR_PCT: float = 99.7919        # tolerance ±1%
_EXPECTED_CI_LOW_PCT: float = 98.1914     # tolerance ±2%
_EXPECTED_CI_HIGH_PCT: float = 101.4185   # tolerance ±2%


@pytest.fixture(scope="module")
def golden_df() -> pd.DataFrame:
    """Return the golden 48-row DataFrame."""
    return pd.DataFrame(_GOLDEN_ROWS)


@pytest.fixture(scope="module")
def golden_result(golden_df: pd.DataFrame) -> BEResult:
    """Run bioequivalence on the golden dataset once per module."""
    return run_bioequivalence(
        golden_df,
        "AUC0_t",
        design="crossover_2x2",
        test_label="T",
        reference_label="R",
        be_window=(80.0, 125.0),
    )


# ---------------------------------------------------------------------------
# Golden tests
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_golden_be_demonstrated(golden_result: BEResult) -> None:
    """BE must be demonstrated (90% CI within 80%–125% window)."""
    assert golden_result.be_demonstrated is True, (
        f"BE not demonstrated: CI=[{golden_result.ci_90_low_pct:.4f}, "
        f"{golden_result.ci_90_high_pct:.4f}]"
    )


@pytest.mark.golden
def test_golden_n_subjects(golden_result: BEResult) -> None:
    """Must have 24 subjects and 24 completers."""
    assert golden_result.n_subjects == 24
    assert golden_result.n_completers == 24


@pytest.mark.golden
def test_golden_gmr(golden_result: BEResult) -> None:
    """GMR must be within ±1% of the pinned value (99.79%)."""
    assert abs(golden_result.gmr_pct - _EXPECTED_GMR_PCT) <= 1.0, (
        f"GMR={golden_result.gmr_pct:.4f}% deviates > 1% from expected {_EXPECTED_GMR_PCT}%"
    )


@pytest.mark.golden
def test_golden_ci_within_90_110(golden_result: BEResult) -> None:
    """90% CI must sit within (90%, 110%) — very tight for this low-CV dataset."""
    assert golden_result.ci_90_low_pct >= 90.0, (
        f"CI lower bound {golden_result.ci_90_low_pct:.4f}% < 90%"
    )
    assert golden_result.ci_90_high_pct <= 110.0, (
        f"CI upper bound {golden_result.ci_90_high_pct:.4f}% > 110%"
    )


@pytest.mark.golden
def test_golden_ci_bounds_pinned(golden_result: BEResult) -> None:
    """CI bounds must match pinned values within ±2%."""
    assert abs(golden_result.ci_90_low_pct - _EXPECTED_CI_LOW_PCT) <= 2.0, (
        f"CI low={golden_result.ci_90_low_pct:.4f} deviates > 2% from expected {_EXPECTED_CI_LOW_PCT}"
    )
    assert abs(golden_result.ci_90_high_pct - _EXPECTED_CI_HIGH_PCT) <= 2.0, (
        f"CI high={golden_result.ci_90_high_pct:.4f} deviates > 2% from expected {_EXPECTED_CI_HIGH_PCT}"
    )


@pytest.mark.golden
def test_golden_sequence_effect_nonsignificant(golden_result: BEResult) -> None:
    """Sequence effect must be non-significant (p > 0.1) — dataset has no sequence effect."""
    assert "sequence" in golden_result.anova_table, (
        f"ANOVA table missing 'sequence': {golden_result.anova_table}"
    )
    p_seq = golden_result.anova_table["sequence"]["p"]
    assert p_seq > 0.1, (
        f"Unexpected significant sequence effect: p={p_seq:.4f} (expected > 0.1)"
    )


@pytest.mark.golden
def test_golden_period_effect_nonsignificant(golden_result: BEResult) -> None:
    """Period effect must be non-significant (p > 0.1) — dataset has no period effect."""
    assert "period" in golden_result.anova_table, (
        f"ANOVA table missing 'period': {golden_result.anova_table}"
    )
    p_per = golden_result.anova_table["period"]["p"]
    assert p_per > 0.1, (
        f"Unexpected significant period effect: p={p_per:.4f} (expected > 0.1)"
    )


@pytest.mark.golden
def test_golden_transformation_is_log(golden_result: BEResult) -> None:
    """Default transformation must be log (FDA guidance)."""
    assert golden_result.transformation == "log"


@pytest.mark.golden
def test_golden_be_window(golden_result: BEResult) -> None:
    """BE window must match the standard FDA 80%–125%."""
    assert golden_result.be_window == (80.0, 125.0)


@pytest.mark.golden
def test_golden_design_label(golden_result: BEResult) -> None:
    """Design must be recorded as crossover_2x2."""
    assert golden_result.design == "crossover_2x2"
    assert golden_result.endpoint == "AUC0_t"
    assert golden_result.test_label == "T"
    assert golden_result.reference_label == "R"
