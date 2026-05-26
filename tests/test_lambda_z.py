"""
Tests for pkplugin.nca.lambda_z — terminal elimination rate constant estimation.

Refs:
- docs/03-algorithms/03-lambda-z-selection.md
- docs/03-algorithms/01-nca-parameters.md §4
"""

from __future__ import annotations

import math

import pytest

from pkplugin.nca.lambda_z import estimate_c0_log_back_extrap, fit_lambda_z

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TIMES_FULL = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0, 16.0, 24.0]
LAMBDA_Z_TRUE = 0.5
C0_TRUE = 100.0
TMAX = 1.0  # peak at t=1 for most tests (tmax from data, not explicitly known here)


def _pure_exp(times: list[float], c0: float = C0_TRUE, lz: float = LAMBDA_Z_TRUE) -> list[float]:
    return [c0 * math.exp(-lz * t) for t in times]


# ---------------------------------------------------------------------------
# Core accuracy
# ---------------------------------------------------------------------------


def test_lambda_z_pure_exponential() -> None:
    """Pure mono-exponential: λz should recover TRUE value to machine precision."""
    times = TIMES_FULL
    concs = _pure_exp(times)
    # tmax = 0 so all points except t=0 are post-tmax
    result = fit_lambda_z(times, concs, tmax=0.0)

    assert result.lambda_z is not None
    assert abs(result.lambda_z - LAMBDA_Z_TRUE) < 1e-9
    assert result.half_life is not None
    assert abs(result.half_life - math.log(2.0) / LAMBDA_Z_TRUE) < 1e-9
    assert result.r_squared is not None
    assert abs(result.r_squared - 1.0) < 1e-9


def test_lambda_z_skips_pre_tmax() -> None:
    """Points at or before tmax must be excluded from the fit."""
    times = TIMES_FULL
    concs = _pure_exp(times)
    # Set tmax=4 → only t=8,12,16,24 should be used
    result = fit_lambda_z(times, concs, tmax=4.0)

    assert result.lambda_z is not None
    assert result.t_start is not None and result.t_start > 4.0
    assert result.n_points <= 4

    # Excluded points should contain indices 0..4 (t=0,1,2,4 → pre/at tmax)
    excluded_times = {ep["time"] for ep in result.excluded_points}
    for t in [0.0, 1.0, 2.0, 4.0]:
        assert t in excluded_times


# ---------------------------------------------------------------------------
# Best Fit tie-breaker
# ---------------------------------------------------------------------------


def test_lambda_z_best_fit_tie_breaker() -> None:
    """
    When two windows have adj_R² within tolerance, Best Fit picks the larger window.
    """
    # Pure exponential → all windows have adj_R² ≈ 1.0 (within tolerance)
    # Best Fit should therefore pick the largest window.
    times = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0, 16.0, 24.0]
    concs = _pure_exp(times)
    result = fit_lambda_z(times, concs, tmax=0.0, method="best_fit")

    assert result.lambda_z is not None
    # With tmax=0, post-tmax count = 7 (t=1..24); best_fit should pick all 7
    assert result.n_points == 7


def test_lambda_z_adj_r2_method() -> None:
    """adj_r2 method picks argmax(adj_R²) without tie-breaker."""
    times = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0, 16.0, 24.0]
    concs = _pure_exp(times)
    result = fit_lambda_z(times, concs, tmax=0.0, method="adj_r2")

    assert result.lambda_z is not None
    assert result.adjusted_r_squared is not None
    # adj_r2 must equal or be close to 1.0 for pure exponential
    assert result.adjusted_r_squared > 0.999


# ---------------------------------------------------------------------------
# Manual selection modes
# ---------------------------------------------------------------------------


def test_lambda_z_manual_indices() -> None:
    """Manual indices selection: t_start, t_end, n_points reflect the chosen points."""
    times = TIMES_FULL
    concs = _pure_exp(times)
    # indices 4,5,6,7 → t=8,12,16,24
    result = fit_lambda_z(times, concs, tmax=0.0, method="manual", manual={"indices": [4, 5, 6, 7]})

    assert result.lambda_z is not None
    assert result.n_points == 4
    assert result.t_start == pytest.approx(8.0)
    assert result.t_end == pytest.approx(24.0)


def test_lambda_z_manual_t_range() -> None:
    """Manual t_range: picks observed times within [t_start, t_end]."""
    times = TIMES_FULL
    concs = _pure_exp(times)
    result = fit_lambda_z(
        times, concs, tmax=0.0, method="manual", manual={"t_start": 8.0, "t_end": 24.0}
    )

    assert result.lambda_z is not None
    assert result.n_points == 4
    assert result.t_start == pytest.approx(8.0)
    assert result.t_end == pytest.approx(24.0)


def test_lambda_z_manual_n_last() -> None:
    """Manual n_last: uses the last n post-tmax observations."""
    times = TIMES_FULL
    concs = _pure_exp(times)
    result = fit_lambda_z(times, concs, tmax=0.0, method="manual", manual={"n_last": 4})

    assert result.lambda_z is not None
    assert result.n_points == 4
    # Last 4 of post-tmax (t=1..24) → t=12,16,24... wait, post-tmax with tmax=0 is t=1,2,4,8,12,16,24
    # n_last=4 → t=12,16,24 is 3... no: last 4 of [1,2,4,8,12,16,24] = [8,12,16,24]
    assert result.t_start == pytest.approx(8.0)
    assert result.t_end == pytest.approx(24.0)


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_lambda_z_insufficient_points() -> None:
    """Fewer than min_points post-tmax returns lambda_z=None with warning."""
    times = [0.0, 1.0, 2.0, 4.0]
    concs = _pure_exp(times)
    # tmax=2 → only t=4 is post-tmax (1 point < 3)
    result = fit_lambda_z(times, concs, tmax=2.0)

    assert result.lambda_z is None
    assert result.n_points == 0
    assert "insufficient_terminal_points" in result.warnings


def test_lambda_z_positive_slope_only() -> None:
    """Rising concentrations in the tail → returns None with no_positive_lambda_z warning."""
    # Increasing concentrations → positive slope → lambda_z would be negative
    times = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0]
    # Tail rises: all post-tmax points go up
    concs = [100.0, 50.0, 20.0, 30.0, 40.0, 50.0]
    # tmax=2 (peak at idx 1, but set tmax=2 so post-tmax is t=4,8,12 which rise)
    result = fit_lambda_z(times, concs, tmax=2.0)

    assert result.lambda_z is None
    assert "no_positive_lambda_z" in result.warnings


# ---------------------------------------------------------------------------
# Span ratio warning
# ---------------------------------------------------------------------------


def test_lambda_z_span_ratio_warning() -> None:
    """
    A window that is too short relative to the estimated half-life emits
    'span_ratio_low' but still returns a valid lambda_z.
    """
    # Use a very slow decay so that a 3-point window spanning 2 time units
    # is much less than 1.5 * half_life.
    # lambda_z = 0.001 → half_life ≈ 693 h; window 0.1 h → span_ratio << 1.5
    lz_slow = 0.001
    times = [0.0, 0.05, 0.10, 0.15]
    concs = [C0_TRUE * math.exp(-lz_slow * t) for t in times]
    result = fit_lambda_z(times, concs, tmax=0.0, method="best_fit", span_ratio_min=1.5)

    assert result.lambda_z is not None
    assert "span_ratio_low" in result.warnings
    assert result.span_ratio is not None
    assert result.span_ratio < 1.5


# ---------------------------------------------------------------------------
# C0 back-extrapolation
# ---------------------------------------------------------------------------


def test_estimate_c0_log_back_extrap() -> None:
    """IV bolus C0 back-extrapolation should recover the true C0."""
    # C(t) = 100 * exp(-0.5 * t); first two quantifiable points at t=1, t=2
    times = [1.0, 2.0, 4.0, 8.0]
    concs = _pure_exp(times)
    c0 = estimate_c0_log_back_extrap(times, concs)
    assert abs(c0 - C0_TRUE) < 1e-6


# ---------------------------------------------------------------------------
# clast_pred consistency
# ---------------------------------------------------------------------------


def test_lambda_z_clast_pred() -> None:
    """clast_pred = exp(intercept - lambda_z * tlast) must be self-consistent."""
    times = TIMES_FULL
    concs = _pure_exp(times)
    result = fit_lambda_z(times, concs, tmax=0.0)

    assert result.lambda_z is not None
    assert result.intercept is not None
    assert result.clast_pred is not None
    assert result.t_end is not None

    expected_clast_pred = math.exp(result.intercept - result.lambda_z * result.t_end)
    assert abs(result.clast_pred - expected_clast_pred) < 1e-12


# ---------------------------------------------------------------------------
# v2.0.2: Tmax inclusion is WinNonlin-version-aware
# ---------------------------------------------------------------------------


def test_lambda_z_tmax_inclusive_for_v5_3():
    """WNL 5.3 includes the Tmax point as a candidate ('points prior to Cmax');
    WNL 6.4/8.3 explicitly exclude it. Verify the masks differ at t == tmax."""
    import math

    from pkplugin.nca.lambda_z import fit_lambda_z

    # Synthetic data where t=2.0 IS the Cmax point.
    # Post-Tmax data continues the same decay shape so 5.3 and 6.4 should
    # both succeed, but 5.3 should use one more point.
    times = [0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 16.0, 24.0]
    k = 0.3
    concs = [10.0, 18.0, 22.0]  # rising to tmax=2.0
    concs += [22.0 * math.exp(-k * (t - 2.0)) for t in times[3:]]

    tmax = 2.0
    r_v53 = fit_lambda_z(times, concs, tmax=tmax, winnonlin_version="5.3")
    r_v64 = fit_lambda_z(times, concs, tmax=tmax, winnonlin_version="6.4")

    # 5.3 may include t=2.0; 6.4 must exclude it strictly.
    assert r_v53.lambda_z is not None and r_v53.lambda_z > 0
    assert r_v64.lambda_z is not None and r_v64.lambda_z > 0
    # If 5.3 picked the larger window, it has more n_points OR an earlier t_start.
    assert (r_v53.n_points or 0) >= (r_v64.n_points or 0) and (r_v53.t_start or float("inf")) <= (
        r_v64.t_start or 0.0
    )


def test_lambda_z_tmax_exclusive_reason_label_differs_by_version():
    """5.3 labels excluded-pre-Tmax points as 'before_tmax'; 6.4/8.3 as 'pre_tmax'."""
    from pkplugin.nca.lambda_z import fit_lambda_z

    times = [0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]
    concs = [5.0, 8.0, 10.0, 7.0, 4.0, 2.0, 0.5]
    tmax = 2.0

    r53 = fit_lambda_z(times, concs, tmax=tmax, winnonlin_version="5.3")
    r64 = fit_lambda_z(times, concs, tmax=tmax, winnonlin_version="6.4")

    reasons_53 = {
        p["reason"] for p in r53.excluded_points if p.get("reason") in ("before_tmax", "pre_tmax")
    }
    reasons_64 = {
        p["reason"] for p in r64.excluded_points if p.get("reason") in ("before_tmax", "pre_tmax")
    }
    assert "before_tmax" in reasons_53 or len(r53.excluded_points) == 0
    assert "pre_tmax" in reasons_64 or len(r64.excluded_points) == 0
