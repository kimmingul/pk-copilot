"""
Tests for pkplugin.nca.stats — descriptive statistics module.

Covers:
- Known mean / SD / median values (hand-computed)
- Geometric vs arithmetic mean on log-normal data
- All-zero vector: geo_mean = None, arithmetic mean = 0
- Mixed positives + zero: geo_mean = None (one zero kills it)
- Single value: SD = None (ddof=1 needs n≥2)
- Empty after missing: all stats None
- n_missing counted correctly
- summarize_nca_results: 6 subjects × 2 treatments × 1 period
- Cmax stats match hand-computed values
- Parameter not in any result: appears as N=0 group entry

Refs:
- docs/03-algorithms/01-nca-parameters.md §6, §7
"""

from __future__ import annotations

import math
import warnings

import pytest

from pkplugin.nca.stats import (
    summarize_nca_results,
    summarize_values,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_nca_result(
    subject_id: str,
    treatment: str | None,
    period: str | None,
    analyte: str,
    cmax: float | None,
    auclast: float | None = None,
) -> object:
    """Create a minimal NCAResult-like object for testing summarize_nca_results."""
    from unittest.mock import MagicMock

    result = MagicMock()
    result.subject_id = subject_id
    result.treatment = treatment
    result.period = period
    result.analyte = analyte

    params: dict[str, float | None] = {
        "Cmax": cmax,
        "AUClast": auclast,
    }
    result.parameters = params

    # Build minimal parameter_rows with units
    rows = []
    unit_map = {"Cmax": "ng/mL", "AUClast": "ng·h/mL"}
    for pname, pval in params.items():
        row = MagicMock()
        row.parameter = pname
        row.value = pval
        row.unit = unit_map.get(pname, "")
        rows.append(row)
    result.parameter_rows = rows

    return result


# ---------------------------------------------------------------------------
# 1. Known mean / SD / median — hand-computed
# ---------------------------------------------------------------------------


def test_known_mean_sd_median() -> None:
    """Values [2, 4, 4, 4, 5, 5, 7, 9] have mean=5, SD≈2.138, median=4.5."""
    data = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    result = summarize_values(data, parameter="X", unit="mg")

    assert result.n == 8
    assert result.n_missing == 0
    assert result.mean == pytest.approx(5.0)
    # Sample SD: sqrt(sum((x-5)^2) / 7) = sqrt(32/7) ≈ 2.1381
    assert result.sd == pytest.approx(math.sqrt(32.0 / 7.0), rel=1e-6)
    assert result.median == pytest.approx(4.5)
    assert result.min == pytest.approx(2.0)
    assert result.max == pytest.approx(9.0)
    assert result.q1 == pytest.approx(4.0)  # numpy linear interp: 25th pct of 8 pts
    assert result.q3 == pytest.approx(5.5)  # numpy linear interp: 75th pct of 8 pts


# ---------------------------------------------------------------------------
# 2. CV% computation
# ---------------------------------------------------------------------------


def test_cv_pct() -> None:
    """CV% = 100 * SD / mean."""
    data = [10.0, 20.0, 30.0]
    result = summarize_values(data)
    assert result.mean == pytest.approx(20.0)
    expected_sd = math.sqrt(((10 - 20) ** 2 + (20 - 20) ** 2 + (30 - 20) ** 2) / 2)
    assert result.sd == pytest.approx(expected_sd)
    assert result.cv_pct == pytest.approx(100.0 * expected_sd / 20.0)


# ---------------------------------------------------------------------------
# 3. Geometric vs arithmetic mean on log-normal data
# ---------------------------------------------------------------------------


def test_geometric_vs_arithmetic_lognormal() -> None:
    """For log-normal x = exp(mu + sigma*z), geo_mean ≈ exp(mu), arith_mean > geo_mean."""
    import numpy as np

    rng = np.random.default_rng(42)
    mu, sigma = 2.0, 0.5
    x = rng.lognormal(mean=mu, sigma=sigma, size=1000).tolist()

    result = summarize_values(x)

    assert result.geo_mean is not None
    assert result.mean is not None
    # arithmetic mean > geometric mean for positive non-constant data
    assert result.mean > result.geo_mean
    # geo_mean should be close to exp(mu) for large n
    assert result.geo_mean == pytest.approx(math.exp(mu), rel=0.05)


# ---------------------------------------------------------------------------
# 4. All-zero vector: geo_mean = None, arithmetic mean = 0
# ---------------------------------------------------------------------------


def test_all_zero_geo_mean_none() -> None:
    """All-zero vector: geometric mean is None; arithmetic mean is 0."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = summarize_values([0.0, 0.0, 0.0], parameter="Zeros")
        assert any(
            "geo_mean" in str(warning.message).lower()
            or "non-positive" in str(warning.message).lower()
            for warning in w
        )

    assert result.geo_mean is None
    assert result.geo_cv_pct is None
    assert result.mean == pytest.approx(0.0)
    assert result.n == 3


# ---------------------------------------------------------------------------
# 5. Mixed positives + zero: geo_mean = None
# ---------------------------------------------------------------------------


def test_mixed_positive_and_zero_geo_mean_none() -> None:
    """One zero among positives kills geometric mean."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        result = summarize_values([1.0, 2.0, 0.0, 4.0], parameter="Mix")

    assert result.geo_mean is None
    assert result.geo_cv_pct is None
    assert result.mean == pytest.approx(7.0 / 4.0)
    assert result.n == 4


# ---------------------------------------------------------------------------
# 6. Single value: SD = None (ddof=1 requires n≥2)
# ---------------------------------------------------------------------------


def test_single_value_sd_none() -> None:
    """Single observation: SD and geo_cv_pct are None (ddof=1 requires n≥2)."""
    result = summarize_values([42.0])
    assert result.n == 1
    assert result.sd is None
    assert result.mean == pytest.approx(42.0)
    assert result.median == pytest.approx(42.0)
    assert result.geo_mean == pytest.approx(42.0)
    assert result.geo_cv_pct is None


# ---------------------------------------------------------------------------
# 7. Empty after missing: all stats None
# ---------------------------------------------------------------------------


def test_empty_after_missing_all_none() -> None:
    """All-missing input: n=0 and every stat is None."""
    result = summarize_values([None, None, None], parameter="Empty")
    assert result.n == 0
    assert result.n_missing == 3
    assert result.mean is None
    assert result.sd is None
    assert result.cv_pct is None
    assert result.geo_mean is None
    assert result.geo_cv_pct is None
    assert result.median is None
    assert result.min is None
    assert result.max is None
    assert result.q1 is None
    assert result.q3 is None


# ---------------------------------------------------------------------------
# 8. n_missing counted correctly with mixed values
# ---------------------------------------------------------------------------


def test_n_missing_counting() -> None:
    """n_missing accounts for None and non-finite floats."""
    data: list[float | None] = [1.0, None, 2.0, float("nan"), 3.0, float("inf"), 4.0]
    result = summarize_values(data)
    # None, nan, inf → 3 missing; finite: 1, 2, 3, 4
    assert result.n == 4
    assert result.n_missing == 3
    assert result.mean == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# 9. summarize_nca_results — grouping and subject counts
# ---------------------------------------------------------------------------


def test_summarize_nca_results_grouping_and_counts() -> None:
    """6 subjects, 2 treatments, 1 period → 2 GroupedStats with 3 subjects each."""
    results = []
    cmax_test = [100.0, 120.0, 110.0]
    cmax_ref = [90.0, 95.0, 85.0]

    for i, cmax in enumerate(cmax_test):
        results.append(
            _make_nca_result(
                subject_id=f"S{i + 1:03d}",
                treatment="Test",
                period="1",
                analyte="parent",
                cmax=cmax,
            )
        )
    for i, cmax in enumerate(cmax_ref):
        results.append(
            _make_nca_result(
                subject_id=f"S{i + 1:03d}",
                treatment="Reference",
                period="1",
                analyte="parent",
                cmax=cmax,
            )
        )

    grouped = summarize_nca_results(
        results,
        group_by=("treatment", "period", "analyte"),
        parameters=("Cmax",),
    )

    assert len(grouped) == 2

    by_treatment = {g.group_keys["treatment"]: g for g in grouped}
    assert "Test" in by_treatment
    assert "Reference" in by_treatment
    assert by_treatment["Test"].n_subjects == 3
    assert by_treatment["Reference"].n_subjects == 3


# ---------------------------------------------------------------------------
# 10. Cmax stats match hand-computed values
# ---------------------------------------------------------------------------


def test_cmax_stats_match_hand_computed() -> None:
    """Cmax stats for Test treatment match manual calculations."""
    cmax_test = [100.0, 120.0, 110.0]
    results = [
        _make_nca_result(
            subject_id=f"S{i + 1:03d}",
            treatment="Test",
            period="1",
            analyte="parent",
            cmax=cmax,
        )
        for i, cmax in enumerate(cmax_test)
    ]

    grouped = summarize_nca_results(
        results,
        group_by=("treatment", "period", "analyte"),
        parameters=("Cmax",),
    )
    assert len(grouped) == 1
    summary = grouped[0].by_parameter["Cmax"]

    expected_mean = sum(cmax_test) / 3  # 110.0
    expected_sd = math.sqrt(sum((x - expected_mean) ** 2 for x in cmax_test) / 2)  # ddof=1

    assert summary.n == 3
    assert summary.mean == pytest.approx(expected_mean)
    assert summary.sd == pytest.approx(expected_sd)
    assert summary.median == pytest.approx(110.0)
    assert summary.min == pytest.approx(100.0)
    assert summary.max == pytest.approx(120.0)

    # Geometric mean: exp(mean(ln)) = (100*120*110)^(1/3)
    expected_geo = (100.0 * 120.0 * 110.0) ** (1.0 / 3.0)
    assert summary.geo_mean == pytest.approx(expected_geo, rel=1e-6)

    # Unit carried through
    assert summary.unit == "ng/mL"
    assert summary.parameter == "Cmax"


# ---------------------------------------------------------------------------
# 11. Parameter not in any result → appears as N=0 group entry
# ---------------------------------------------------------------------------


def test_parameter_not_in_results_n_zero() -> None:
    """Parameter absent from all results still appears in by_parameter as N=0."""
    results = [
        _make_nca_result(
            subject_id="S001",
            treatment="Test",
            period="1",
            analyte="parent",
            cmax=100.0,
        )
    ]

    grouped = summarize_nca_results(
        results,
        group_by=("treatment", "period", "analyte"),
        parameters=("Cmax", "AUCINF_obs"),  # AUCINF_obs not in mock result
    )
    assert len(grouped) == 1
    aucinf_summary = grouped[0].by_parameter["AUCINF_obs"]
    assert aucinf_summary.n == 0
    assert aucinf_summary.mean is None


# ---------------------------------------------------------------------------
# 12. None group-key → represented as "<unspecified>"
# ---------------------------------------------------------------------------


def test_none_group_key_becomes_unspecified() -> None:
    """NCAResult with treatment=None → group_keys["treatment"] == "<unspecified>"."""
    results = [
        _make_nca_result(
            subject_id="S001",
            treatment=None,
            period=None,
            analyte="parent",
            cmax=55.0,
        )
    ]

    grouped = summarize_nca_results(
        results,
        group_by=("treatment", "period", "analyte"),
        parameters=("Cmax",),
    )
    assert len(grouped) == 1
    assert grouped[0].group_keys["treatment"] == "<unspecified>"
    assert grouped[0].group_keys["period"] == "<unspecified>"
    assert grouped[0].by_parameter["Cmax"].n == 1
    assert grouped[0].by_parameter["Cmax"].mean == pytest.approx(55.0)


# ---------------------------------------------------------------------------
# 13. DescriptiveSummary contains no numpy types (JSON-serialisable)
# ---------------------------------------------------------------------------


def test_no_numpy_types_in_summary() -> None:
    """All non-None fields in DescriptiveSummary must be plain Python float or int."""
    import numpy as np

    data = [1.5, 2.5, 3.5, 4.5]
    result = summarize_values(data)

    for fname in (
        "mean",
        "sd",
        "cv_pct",
        "geo_mean",
        "geo_cv_pct",
        "median",
        "min",
        "max",
        "q1",
        "q3",
    ):
        val = getattr(result, fname)
        if val is not None:
            assert isinstance(val, float), (
                f"{fname}={val!r} is {type(val).__name__}, expected float"
            )
            assert not isinstance(val, np.floating), (
                f"{fname} is a numpy float, not plain Python float"
            )

    assert isinstance(result.n, int)
    assert isinstance(result.n_missing, int)


# ---------------------------------------------------------------------------
# 14. Geometric CV% formula verification
# ---------------------------------------------------------------------------


def test_geo_cv_pct_formula() -> None:
    """geo_cv_pct = 100 * sqrt(exp(var_ln) - 1) where var_ln is ddof=1 variance of ln(x)."""

    data = [1.0, 2.0, 4.0, 8.0]
    result = summarize_values(data)

    ln_data = [math.log(x) for x in data]
    n = len(ln_data)
    mean_ln = sum(ln_data) / n
    var_ln = sum((x - mean_ln) ** 2 for x in ln_data) / (n - 1)  # ddof=1
    expected_geo_cv = 100.0 * math.sqrt(math.exp(var_ln) - 1.0)

    assert result.geo_cv_pct == pytest.approx(expected_geo_cv, rel=1e-6)
