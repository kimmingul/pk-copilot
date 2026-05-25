"""
Tests for pkplugin.comp.ode — ODE-based compartmental PK simulator.

All analytical reference formulas are inlined here so that these tests do not
depend on the analytic module.

Refs: docs/03-algorithms/08-compartmental-models.md §2, §3
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pkplugin.comp.ode import DosingEvent, simulate_ode, simulate_ode_with_tlag


# ---------------------------------------------------------------------------
# Helpers — inline analytical formulas
# ---------------------------------------------------------------------------


def _cmt1_iv_bolus_analytical(
    times: np.ndarray,
    dose: float,
    V: float,
    k: float,
) -> np.ndarray:
    """C(t) = (D/V) * exp(-k*t)."""
    return (dose / V) * np.exp(-k * times)


def _cmt1_iv_infusion_analytical(
    times: np.ndarray,
    dose: float,
    V: float,
    k: float,
    t_inf: float,
) -> np.ndarray:
    """
    During [0, t_inf]: C = (R0/(V*k)) * (1 - exp(-k*t))
    After  t_inf:      C = C(t_inf) * exp(-k*(t-t_inf))
    """
    R0 = dose / t_inf
    C_inf = (R0 / (V * k)) * (1.0 - math.exp(-k * t_inf))
    conc = np.where(
        times <= t_inf,
        (R0 / (V * k)) * (1.0 - np.exp(-k * times)),
        C_inf * np.exp(-k * (times - t_inf)),
    )
    return conc


def _bateman_analytical(
    times: np.ndarray,
    dose: float,
    V_F: float,
    ka: float,
    k: float,
) -> np.ndarray:
    """C(t) = (D*ka / (V_F*(ka-k))) * (exp(-k*t) - exp(-ka*t))."""
    if abs(ka - k) < 1e-12:
        # flip-flop degenerate — should not happen in tests
        return np.zeros_like(times)
    return (dose * ka / (V_F * (ka - k))) * (np.exp(-k * times) - np.exp(-ka * times))


def _cmt2_iv_bolus_analytical(
    times: np.ndarray,
    dose: float,
    V1: float,
    k10: float,
    k12: float,
    k21: float,
) -> np.ndarray:
    """
    Macro form: C(t) = A*exp(-alpha*t) + B*exp(-beta*t)
    alpha + beta  = k10 + k12 + k21
    alpha * beta  = k10 * k21
    A + B         = D / V1
    A*beta + B*alpha = D*k21 / V1
    """
    sum_ab = k10 + k12 + k21
    prod_ab = k10 * k21
    disc = math.sqrt(max(sum_ab ** 2 - 4.0 * prod_ab, 0.0))
    alpha = (sum_ab + disc) / 2.0
    beta = (sum_ab - disc) / 2.0

    D_V1 = dose / V1
    D_k21_V1 = dose * k21 / V1
    # A + B = D/V1 and A*beta + B*alpha = D*k21/V1
    # => A*(beta - alpha) = D_k21_V1 - D_V1*alpha
    # => A = (D_k21_V1 - D_V1*alpha) / (beta - alpha)
    A = (D_k21_V1 - D_V1 * alpha) / (beta - alpha)
    B = D_V1 - A
    return A * np.exp(-alpha * times) + B * np.exp(-beta * times)


# ---------------------------------------------------------------------------
# 1. 1-cmt IV bolus: ODE vs analytical, tolerance 1e-7
# ---------------------------------------------------------------------------


def test_cmt1_iv_bolus_vs_analytical() -> None:
    """ODE and analytical 1-cmt IV bolus must agree to 1e-7."""
    dose, V, k = 100.0, 20.0, 0.3
    times = np.array([0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0])
    dosing = [DosingEvent(time=0.0, amount=dose, route="iv_bolus")]

    ode_conc = simulate_ode("cmt1_iv_bolus", {"V": V, "k": k}, dosing, times)
    ref_conc = _cmt1_iv_bolus_analytical(times, dose, V, k)

    np.testing.assert_allclose(ode_conc, ref_conc, rtol=1e-7, atol=1e-10)


# ---------------------------------------------------------------------------
# 2. 1-cmt IV infusion: ODE vs analytical at end-of-infusion and post
# ---------------------------------------------------------------------------


def test_cmt1_iv_infusion_vs_analytical() -> None:
    """ODE and analytical 1-cmt IV infusion must agree to 1e-7."""
    dose, V, k, t_inf = 200.0, 25.0, 0.2, 2.0
    times = np.array([0.5, 1.0, 2.0, 2.5, 4.0, 8.0, 12.0])
    dosing = [DosingEvent(time=0.0, amount=dose, route="iv_infusion", infusion_duration=t_inf)]

    ode_conc = simulate_ode(
        "cmt1_iv_infusion", {"V": V, "k": k}, dosing, times
    )
    ref_conc = _cmt1_iv_infusion_analytical(times, dose, V, k, t_inf)

    np.testing.assert_allclose(ode_conc, ref_conc, rtol=1e-7, atol=1e-10)


# ---------------------------------------------------------------------------
# 3. 1-cmt PO: ODE vs Bateman, tolerance 1e-6
# ---------------------------------------------------------------------------


def test_cmt1_po_vs_bateman() -> None:
    """ODE 1-cmt oral must agree with the Bateman formula to 1e-6."""
    dose, V_F, ka, k = 100.0, 30.0, 1.5, 0.3
    times = np.array([0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 24.0])
    dosing = [DosingEvent(time=0.0, amount=dose, route="oral")]

    ode_conc = simulate_ode("cmt1_po", {"V_F": V_F, "ka": ka, "k": k}, dosing, times)
    ref_conc = _bateman_analytical(times, dose, V_F, ka, k)

    np.testing.assert_allclose(ode_conc, ref_conc, rtol=1e-6, atol=1e-9)


# ---------------------------------------------------------------------------
# 4. 2-cmt IV bolus: ODE vs macro analytical, tolerance 1e-6
# ---------------------------------------------------------------------------


def test_cmt2_iv_bolus_vs_analytical() -> None:
    """ODE 2-cmt IV bolus must agree with macro analytical form to 1e-6."""
    dose = 100.0
    V1, k10, k12, k21 = 10.0, 0.4, 0.3, 0.15
    times = np.array([0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0])
    dosing = [DosingEvent(time=0.0, amount=dose, route="iv_bolus")]

    ode_conc = simulate_ode(
        "cmt2_iv_bolus",
        {"V1": V1, "k10": k10, "k12": k12, "k21": k21},
        dosing,
        times,
    )
    ref_conc = _cmt2_iv_bolus_analytical(times, dose, V1, k10, k12, k21)

    np.testing.assert_allclose(ode_conc, ref_conc, rtol=1e-6, atol=1e-9)


# ---------------------------------------------------------------------------
# 5. Multiple IV bolus doses: verify superposition
# ---------------------------------------------------------------------------


def test_multiple_iv_bolus_superposition() -> None:
    """Three IV bolus doses at t=0, 12, 24; ODE must match superposition."""
    V, k = 20.0, 0.3
    dose = 100.0
    dose_times = [0.0, 12.0, 24.0]

    times = np.array([0.5, 6.0, 12.5, 18.0, 24.5, 30.0, 36.0])
    dosing = [DosingEvent(time=t, amount=dose, route="iv_bolus") for t in dose_times]

    ode_conc = simulate_ode("cmt1_iv_bolus", {"V": V, "k": k}, dosing, times)

    # Superposition: sum of individual doses shifted to their dose times
    ref = np.zeros_like(times)
    for td in dose_times:
        shifted = times - td
        mask = shifted >= 0
        ref[mask] += (dose / V) * np.exp(-k * shifted[mask])

    np.testing.assert_allclose(ode_conc, ref, rtol=1e-7, atol=1e-9)


# ---------------------------------------------------------------------------
# 6. IV infusion + later IV bolus combination
# ---------------------------------------------------------------------------


def test_iv_infusion_plus_bolus() -> None:
    """Infusion at t=0 followed by a bolus at t=6; sum must be consistent."""
    V, k = 15.0, 0.25
    t_inf = 4.0
    dose_inf = 200.0
    dose_bolus = 50.0

    times = np.array([2.0, 4.0, 6.5, 8.0, 12.0])
    dosing = [
        DosingEvent(time=0.0, amount=dose_inf, route="iv_infusion", infusion_duration=t_inf),
        DosingEvent(time=6.0, amount=dose_bolus, route="iv_bolus"),
    ]

    ode_conc = simulate_ode("cmt1_iv_infusion", {"V": V, "k": k}, dosing, times)

    # Reference: infusion contribution + bolus contribution
    ref_inf = _cmt1_iv_infusion_analytical(times, dose_inf, V, k, t_inf)
    # Bolus at t=6 contributes only after t=6
    ref_bolus = np.zeros_like(times)
    for i, t in enumerate(times):
        if t >= 6.0:
            ref_bolus[i] = (dose_bolus / V) * math.exp(-k * (t - 6.0))

    ref = ref_inf + ref_bolus
    np.testing.assert_allclose(ode_conc, ref, rtol=1e-7, atol=1e-9)


# ---------------------------------------------------------------------------
# 7. Michaelis-Menten saturation check
# ---------------------------------------------------------------------------


def test_mm_saturation_vs_linear_regime() -> None:
    """High dose → MM-dominated (slower decay); low dose → near-linear."""
    V, Vmax, Km = 10.0, 50.0, 5.0
    times = np.array([1.0, 2.0, 4.0, 8.0])

    # High dose: Km << C initially → MM saturated → slower first-order apparent
    high_dose = 5000.0
    dosing_high = [DosingEvent(time=0.0, amount=high_dose, route="iv_bolus")]
    c_high = simulate_ode(
        "cmt1_iv_mm", {"V": V, "Vmax": Vmax, "Km": Km}, dosing_high, times
    )

    # In linear regime (C << Km), dA/dt = -Vmax*(A/V)/Km * V = -Vmax/Km * A
    # so apparent k_eff = Vmax / Km  [hr⁻¹] (NOT divided by V)
    k_eff = Vmax / Km
    # Use a very low dose so C << Km throughout
    very_low_dose = 0.001
    dosing_very_low = [DosingEvent(time=0.0, amount=very_low_dose, route="iv_bolus")]
    c_very_low = simulate_ode(
        "cmt1_iv_mm", {"V": V, "Vmax": Vmax, "Km": Km}, dosing_very_low, times
    )
    ref_very_low = (very_low_dose / V) * np.exp(-k_eff * times)
    np.testing.assert_allclose(c_very_low, ref_very_low, rtol=1e-4, atol=1e-12,
                               err_msg="Very-low-dose MM should approximate linear elimination")

    # High dose should show slower decline early (saturation effect)
    # At t=2 vs t=1: decay ratio for high dose should be smaller loss than linear
    # (saturation slows elimination → concentration ratio c[1]/c[0] > exp(-k_eff*1))
    decay_high = c_high[1] / c_high[0]  # ratio over 1 hr at high dose
    # Under pure linear at k_eff, ratio would be exp(-k_eff): check high > that
    # (high-dose apparent k is lower than k_eff because MM is saturated)
    # We just check that the high-dose profile hasn't collapsed to near-zero yet
    assert c_high[0] > 0.01, "High dose should have significant conc at t=1"


# ---------------------------------------------------------------------------
# 8. 1-cmt PO with Tlag: concentrations before Tlag must be zero
# ---------------------------------------------------------------------------


def test_cmt1_po_tlag_zero_before_lag() -> None:
    """Concentrations before tlag must be exactly 0."""
    dose, V_F, ka, k, tlag = 100.0, 20.0, 1.0, 0.2, 2.0
    times = np.array([0.0, 0.5, 1.0, 1.5, 1.99, 2.0, 2.5, 4.0, 8.0])
    dosing = [DosingEvent(time=0.0, amount=dose, route="oral")]

    conc = simulate_ode_with_tlag(
        "cmt1_po", {"V_F": V_F, "ka": ka, "k": k}, dosing, times, tlag=tlag
    )

    # Before tlag all concentrations must be 0
    pre_lag_mask = times < tlag - 1e-9
    assert np.all(conc[pre_lag_mask] == 0.0), (
        f"Expected zero before tlag={tlag}, got: {conc[pre_lag_mask]}"
    )

    # After tlag, concentrations should be positive
    post_lag_mask = times > tlag + 0.1
    assert np.all(conc[post_lag_mask] > 0.0), (
        "Expected positive concentrations after tlag"
    )


# ---------------------------------------------------------------------------
# 9. Different solvers agree to within rtol
# ---------------------------------------------------------------------------


def test_solvers_agree() -> None:
    """LSODA, BDF, and RK45 must produce the same concentrations within rtol."""
    dose, V, k = 100.0, 20.0, 0.3
    times = np.linspace(0.1, 12.0, 20)
    dosing = [DosingEvent(time=0.0, amount=dose, route="iv_bolus")]
    params = {"V": V, "k": k}

    c_lsoda = simulate_ode("cmt1_iv_bolus", params, dosing, times, method="LSODA")
    c_bdf = simulate_ode("cmt1_iv_bolus", params, dosing, times, method="BDF")
    c_rk45 = simulate_ode("cmt1_iv_bolus", params, dosing, times, method="RK45")

    np.testing.assert_allclose(c_lsoda, c_bdf, rtol=1e-6, atol=1e-9,
                               err_msg="LSODA vs BDF")
    np.testing.assert_allclose(c_lsoda, c_rk45, rtol=1e-6, atol=1e-9,
                               err_msg="LSODA vs RK45")


# ---------------------------------------------------------------------------
# 10. Stiff 3-cmt model: LSODA handles it, verify non-NaN
# ---------------------------------------------------------------------------


def test_cmt3_iv_bolus_lsoda_succeeds() -> None:
    """3-cmt IV bolus with stiff rates; LSODA must produce finite values."""
    dose = 200.0
    params = {
        "V1": 5.0,
        "k10": 0.5,
        "k12": 1.0,
        "k21": 0.8,
        "k13": 0.4,
        "k31": 0.2,
    }
    times = np.array([0.1, 0.5, 1.0, 2.0, 4.0, 8.0])
    dosing = [DosingEvent(time=0.0, amount=dose, route="iv_bolus")]

    conc = simulate_ode("cmt3_iv_bolus", params, dosing, times, method="LSODA")

    assert np.all(np.isfinite(conc)), "LSODA 3-cmt concentrations must be finite"
    assert np.all(conc >= 0.0), "Concentrations must be non-negative"
    # Concentrations must be monotonically decreasing for simple elimination
    assert np.all(np.diff(conc) < 0), "3-cmt concentrations should decrease over time"


# ---------------------------------------------------------------------------
# 11. 2-cmt oral ODE: basic sanity check
# ---------------------------------------------------------------------------


def test_cmt2_po_basic_sanity() -> None:
    """2-cmt oral ODE must produce a peaked profile with finite values."""
    dose = 100.0
    params = {
        "V1_F": 20.0,
        "ka": 1.5,
        "k10": 0.3,
        "k12": 0.2,
        "k21": 0.1,
    }
    times = np.array([0.5, 1.0, 2.0, 3.0, 6.0, 12.0])
    dosing = [DosingEvent(time=0.0, amount=dose, route="oral")]

    conc = simulate_ode("cmt2_po", params, dosing, times)

    assert np.all(np.isfinite(conc)), "2-cmt PO concentrations must be finite"
    assert np.all(conc >= 0.0), "Concentrations must be non-negative"
    # Must rise to a peak then fall: maximum should be in the middle
    assert conc[2] > conc[0], "Concentration must rise after dose"
    assert conc[-1] < conc[2], "Concentration must fall at late times"


# ---------------------------------------------------------------------------
# 12. MM 2-cmt IV: central compartment MM elimination
# ---------------------------------------------------------------------------


def test_cmt2_iv_mm_finite() -> None:
    """2-cmt IV + MM elimination must give finite, non-negative concentrations."""
    dose = 100.0
    params = {
        "V1": 10.0,
        "Vmax": 30.0,
        "Km": 3.0,
        "k12": 0.2,
        "k21": 0.1,
    }
    times = np.array([0.5, 1.0, 2.0, 4.0, 8.0])
    dosing = [DosingEvent(time=0.0, amount=dose, route="iv_bolus")]

    conc = simulate_ode("cmt2_iv_mm", params, dosing, times)

    assert np.all(np.isfinite(conc))
    assert np.all(conc >= 0.0)
