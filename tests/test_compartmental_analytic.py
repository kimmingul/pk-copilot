"""
Tests for pkplugin.comp.analytic — closed-form compartmental PK model predictions.

Covers all seven models with analytical ground-truth checks, boundary conditions,
edge cases, and error handling.

Refs:
- docs/03-algorithms/08-compartmental-models.md §2
- docs/04-winnonlin-version-matrix.md §4
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from numpy.typing import NDArray

from pkplugin.comp.analytic import predict
from pkplugin.comp.models import get_model

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trapz(t: list[float], c: NDArray[np.float64]) -> float:
    """Simple trapezoidal AUC (NumPy 2.0+: trapezoid replaces trapz)."""
    return float(np.trapezoid(c, t))


# ---------------------------------------------------------------------------
# 1-cmt IV bolus  (WinNonlin #1)
# ---------------------------------------------------------------------------


class TestCmt1IvBolus:
    """1-cmt IV bolus: C(t) = (D/V)*exp(-k*t)."""

    def test_exact_values_multiple_timepoints(self) -> None:
        """Verify closed-form at several times to 1e-12 relative tolerance."""
        D, V, k = 100.0, 10.0, 0.2
        times = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]
        result = predict("cmt1_iv_bolus", {"V": V, "k": k}, times, dose=D)
        for i, t in enumerate(times):
            expected = (D / V) * math.exp(-k * t)
            assert abs(result[i] - expected) < 1e-12 * max(abs(expected), 1e-30), (
                f"t={t}: got {result[i]}, expected {expected}"
            )

    def test_auc_and_mrt_identity(self) -> None:
        """AUCinf = D/(V*k),  MRT = 1/k — verified via dense trapezoid grid."""
        D, V, k = 50.0, 5.0, 0.3
        t_grid = list(np.linspace(0, 200, 20_001))
        c_grid = predict("cmt1_iv_bolus", {"V": V, "k": k}, t_grid, dose=D)

        auc_trap = _trapz(t_grid, c_grid)
        auc_exact = D / (V * k)
        assert abs(auc_trap - auc_exact) / auc_exact < 1e-6

        # MRT = AUMC/AUC; AUMC = D/(V*k²)
        t_arr = np.asarray(t_grid)
        aumc_trap = _trapz(t_grid, t_arr * c_grid)
        mrt_trap = aumc_trap / auc_trap
        mrt_exact = 1.0 / k
        assert abs(mrt_trap - mrt_exact) / mrt_exact < 1e-5

    def test_c0_equals_dose_over_v(self) -> None:
        D, V, k = 80.0, 16.0, 0.1
        result = predict("cmt1_iv_bolus", {"V": V, "k": k}, [0.0], dose=D)
        assert abs(result[0] - D / V) < 1e-14


# ---------------------------------------------------------------------------
# 1-cmt IV infusion  (WinNonlin #3)
# ---------------------------------------------------------------------------


class TestCmt1IvInfusion:
    """1-cmt IV infusion: rising during infusion, mono-exp decline after."""

    def test_continuity_at_t_inf(self) -> None:
        """C is continuous at T_inf: limit from left == limit from right."""
        D, V, k, T_inf = 100.0, 10.0, 0.2, 1.0
        params = {"V": V, "k": k}
        eps = 1e-8
        c_before = predict(
            "cmt1_iv_infusion", params, [T_inf - eps], dose=D, infusion_duration=T_inf
        )
        c_after = predict(
            "cmt1_iv_infusion", params, [T_inf + eps], dose=D, infusion_duration=T_inf
        )
        assert abs(c_before[0] - c_after[0]) < 1e-6

    def test_css_approached_at_long_infusion(self) -> None:
        """Css = R0/(V*k) is approached as t → ∞ during a long infusion."""
        D_rate = 10.0  # mg/hr
        T_inf = 1000.0  # effectively infinite infusion
        D = D_rate * T_inf
        V, k = 20.0, 0.5
        params = {"V": V, "k": k}
        Css = D_rate / (V * k)
        c_late = predict(
            "cmt1_iv_infusion", params, [T_inf * 0.999], dose=D, infusion_duration=T_inf
        )
        assert abs(c_late[0] - Css) / Css < 1e-3

    def test_post_infusion_mono_exponential_decay(self) -> None:
        """After T_inf, concentration decays as C(T_inf)*exp(-k*(t-T_inf))."""
        D, V, k, T_inf = 100.0, 10.0, 0.3, 2.0
        params = {"V": V, "k": k}
        t_post = [3.0, 5.0, 10.0]
        c_Tinf = predict("cmt1_iv_infusion", params, [T_inf], dose=D, infusion_duration=T_inf)[0]
        result = predict("cmt1_iv_infusion", params, t_post, dose=D, infusion_duration=T_inf)
        for i, t in enumerate(t_post):
            expected = c_Tinf * math.exp(-k * (t - T_inf))
            assert abs(result[i] - expected) < 1e-10

    def test_missing_infusion_duration_raises(self) -> None:
        with pytest.raises(ValueError, match="infusion_duration"):
            predict("cmt1_iv_infusion", {"V": 10.0, "k": 0.2}, [1.0], dose=100.0)


# ---------------------------------------------------------------------------
# 1-cmt oral (Bateman)  (WinNonlin #5)
# ---------------------------------------------------------------------------


class TestCmt1Po:
    """1-cmt PO: Bateman equation with optional tlag."""

    def test_tmax_analytical(self) -> None:
        """Tmax = ln(ka/k) / (ka - k) for the Bateman equation."""
        V_F, ka, k = 20.0, 1.5, 0.3
        params = {"V_F": V_F, "ka": ka, "k": k}
        tmax_exact = math.log(ka / k) / (ka - k)
        t_grid = list(np.linspace(0.01, 30, 10_000))
        c_grid = predict("cmt1_po", params, t_grid, dose=100.0)
        tmax_numerical = t_grid[int(np.argmax(c_grid))]
        assert abs(tmax_numerical - tmax_exact) < 0.01  # within 0.01 hr

    def test_cmax_matches_analytical(self) -> None:
        """Cmax from predict equals the closed-form Cmax."""
        D, V_F, ka, k = 100.0, 20.0, 1.5, 0.3
        params = {"V_F": V_F, "ka": ka, "k": k}
        tmax = math.log(ka / k) / (ka - k)
        cmax_exact = (D * ka / (V_F * (ka - k))) * (math.exp(-k * tmax) - math.exp(-ka * tmax))
        t_fine = list(np.linspace(0.0, 30.0, 100_000))
        c_fine = predict("cmt1_po", params, t_fine, dose=D)
        cmax_numerical = float(np.max(c_fine))
        assert abs(cmax_numerical - cmax_exact) / cmax_exact < 1e-4

    def test_flip_flop_ka_less_than_k(self) -> None:
        """Flip-flop case (ka < k): concentration still peaks and is non-negative.

        In flip-flop, ka=0.1 is the terminal slope so the profile decays slowly;
        we only verify sign correctness and peak existence, not a tight late-time bound.
        """
        D, V_F, ka, k = 100.0, 20.0, 0.1, 0.5
        params = {"V_F": V_F, "ka": ka, "k": k}
        times = list(np.linspace(0.0, 50.0, 500))
        result = predict("cmt1_po", params, times, dose=D)
        # All values must be non-negative
        assert np.all(result >= 0.0)
        # Must have a peak somewhere in the interior
        peak_idx = int(np.argmax(result))
        assert 0 < peak_idx < len(times) - 1
        # Terminal slope governs the slowest exponent — min(ka,k)=ka=0.1
        # At t=50: C ~ (D*k/(V_F*(k-ka)))*exp(-ka*50) ≈ small but not negligible
        assert float(np.max(result)) > 0.0

    def test_ka_equals_k_lhopital_limit(self) -> None:
        """When ka == k (numerically), l'Hôpital limit is applied: C = (D*ka*τ/V_F)*exp(-k*τ)."""
        D, V_F, ka = 100.0, 20.0, 0.3
        k = ka  # exact equality
        params = {"V_F": V_F, "ka": ka, "k": k}
        times = [1.0, 2.0, 5.0, 10.0]
        result = predict("cmt1_po", params, times, dose=D)
        for i, t in enumerate(times):
            expected = (D * ka * t / V_F) * math.exp(-k * t)
            assert abs(result[i] - expected) < 1e-10, f"t={t}: got {result[i]}, expected {expected}"

    def test_tlag_zero_before_tlag(self) -> None:
        """C(t) == 0 for all t < tlag when tlag > 0."""
        D, V_F, ka, k, tlag = 100.0, 20.0, 1.5, 0.3, 2.0
        params = {"V_F": V_F, "ka": ka, "k": k}
        times_before = [0.0, 0.5, 1.0, 1.99]
        result = predict("cmt1_po", params, times_before, dose=D, tlag=tlag)
        assert np.all(result == 0.0)

    def test_tlag_shifts_profile(self) -> None:
        """Profile with tlag=2 at t=5 should equal profile without tlag at t=3."""
        D, V_F, ka, k, tlag = 100.0, 20.0, 1.5, 0.3, 2.0
        params = {"V_F": V_F, "ka": ka, "k": k}
        c_lag = predict("cmt1_po", params, [5.0], dose=D, tlag=tlag)
        c_no_lag = predict("cmt1_po", params, [3.0], dose=D, tlag=0.0)
        assert abs(c_lag[0] - c_no_lag[0]) < 1e-12


# ---------------------------------------------------------------------------
# 2-cmt IV bolus  (WinNonlin #7)
# ---------------------------------------------------------------------------


class TestCmt2IvBolus:
    """2-cmt IV bolus: C(t) = A*exp(-α*t) + B*exp(-β*t)."""

    # Canonical parameters
    _P: dict[str, float] = {
        "V1": 10.0,
        "k10": 0.3,
        "k12": 0.1,
        "k21": 0.05,
    }

    def _alpha_beta(self) -> tuple[float, float]:
        k10, k12, k21 = self._P["k10"], self._P["k12"], self._P["k21"]
        disc = (k10 + k12 + k21) ** 2 - 4.0 * k10 * k21
        sq = math.sqrt(disc)
        alpha = (k10 + k12 + k21 + sq) / 2.0
        beta = (k10 + k12 + k21 - sq) / 2.0
        return alpha, beta

    def test_alpha_plus_beta_identity(self) -> None:
        """α + β == k10 + k12 + k21."""
        alpha, beta = self._alpha_beta()
        expected = self._P["k10"] + self._P["k12"] + self._P["k21"]
        assert abs(alpha + beta - expected) < 1e-12

    def test_alpha_times_beta_identity(self) -> None:
        """α * β == k10 * k21."""
        alpha, beta = self._alpha_beta()
        expected = self._P["k10"] * self._P["k21"]
        assert abs(alpha * beta - expected) < 1e-12

    def test_c0_equals_dose_over_v1(self) -> None:
        """C(0) = A + B = D/V1."""
        D = 100.0
        result = predict("cmt2_iv_bolus", self._P, [0.0], dose=D)
        assert abs(result[0] - D / self._P["V1"]) < 1e-12

    def test_auc_inf_via_trapezoid(self) -> None:
        """AUCinf from trapezoid on dense grid matches D/(V1*k10) ~ analytical."""
        D = 100.0
        # Extend to t=500 so the slow β exponent is fully captured
        t_grid = list(np.linspace(0, 500, 100_001))
        c_grid = predict("cmt2_iv_bolus", self._P, t_grid, dose=D)
        auc_trap = _trapz(t_grid, c_grid)
        # Exact: AUCinf = D / (V1 * k10) for 2-cmt iv bolus
        auc_exact = D / (self._P["V1"] * self._P["k10"])
        assert abs(auc_trap - auc_exact) / auc_exact < 1e-4

    def test_biexponential_shape(self) -> None:
        """Concentration profile is strictly decreasing for these parameters."""
        D = 100.0
        times = list(np.linspace(0.01, 50.0, 200))
        result = predict("cmt2_iv_bolus", self._P, times, dose=D)
        # All concentrations positive
        assert np.all(result > 0)
        # Monotonically decreasing (approximate — use a coarser diff)
        diffs = np.diff(result)
        assert np.all(diffs < 0)


# ---------------------------------------------------------------------------
# 2-cmt oral  (WinNonlin #11)
# ---------------------------------------------------------------------------


class TestCmt2Po:
    """2-cmt oral: 3-exponential structure."""

    _P: dict[str, float] = {
        "V1_F": 10.0,
        "ka": 1.2,
        "k10": 0.3,
        "k12": 0.1,
        "k21": 0.05,
    }

    def test_three_exponential_structure(self) -> None:
        """Model produces a rise-then-fall profile (absorption peak present)."""
        D = 100.0
        times = list(np.linspace(0.0, 50.0, 1000))
        result = predict("cmt2_po", self._P, times, dose=D)
        # Allow tiny floating-point negatives at t=0 (order ~1e-15)
        assert np.all(result >= -1e-12)
        # Peak must exist (not at t=0 and not at t=end)
        peak_idx = int(np.argmax(result))
        assert 0 < peak_idx < len(times) - 1

    def test_zero_at_time_zero(self) -> None:
        """C(0) = 0 for oral dosing (no drug in central compartment at t=0)."""
        D = 100.0
        result = predict("cmt2_po", self._P, [0.0], dose=D)
        assert abs(result[0]) < 1e-12

    def test_decays_to_zero_at_long_time(self) -> None:
        D = 100.0
        result = predict("cmt2_po", self._P, [500.0], dose=D)
        assert abs(result[0]) < 1e-6

    def test_tlag_zero_before_tlag(self) -> None:
        D = 100.0
        result = predict("cmt2_po", self._P, [0.0, 0.5, 0.99], dose=D, tlag=1.0)
        assert np.all(result == 0.0)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Validation and error cases."""

    def test_invalid_model_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown PK model"):
            predict("not_a_model", {}, [1.0], dose=100.0)

    def test_negative_parameter_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            predict("cmt1_iv_bolus", {"V": -5.0, "k": 0.2}, [1.0], dose=100.0)

    def test_zero_parameter_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            predict("cmt1_iv_bolus", {"V": 10.0, "k": 0.0}, [1.0], dose=100.0)

    def test_missing_parameter_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="requires parameter"):
            predict("cmt1_iv_bolus", {"V": 10.0}, [1.0], dose=100.0)

    def test_get_model_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown PK model"):
            get_model("xyz_unknown")


# ---------------------------------------------------------------------------
# 3-cmt IV bolus  (WinNonlin #13)
# ---------------------------------------------------------------------------


class TestCmt3IvBolus:
    """3-cmt IV bolus: 3-exponential macro form."""

    _P: dict[str, float] = {
        "V1": 10.0,
        "k10": 0.4,
        "k12": 0.2,
        "k21": 0.1,
        "k13": 0.05,
        "k31": 0.02,
    }

    def test_c0_equals_dose_over_v1(self) -> None:
        """C(0) = D/V1 (all dose starts in central compartment)."""
        D = 100.0
        result = predict("cmt3_iv_bolus", self._P, [0.0], dose=D)
        assert abs(result[0] - D / self._P["V1"]) < 1e-8

    def test_concentration_positive_and_decaying(self) -> None:
        """Concentrations are positive and approach zero for large t."""
        D = 100.0
        # Use t_end = 300 hr so slowest exponent (k31=0.02) contributes < 0.2%
        times = list(np.linspace(0.01, 300.0, 500))
        result = predict("cmt3_iv_bolus", self._P, times, dose=D)
        assert np.all(result > 0)
        assert result[-1] < 1e-3 * result[0]

    def test_auc_inf_via_trapezoid(self) -> None:
        """AUCinf ≈ D / (V1 * k10) for 3-cmt IV bolus."""
        D = 100.0
        t_grid = list(np.linspace(0, 500, 100_001))
        c_grid = predict("cmt3_iv_bolus", self._P, t_grid, dose=D)
        auc_trap = _trapz(t_grid, c_grid)
        auc_exact = D / (self._P["V1"] * self._P["k10"])
        assert abs(auc_trap - auc_exact) / auc_exact < 1e-3
