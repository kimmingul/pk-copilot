"""
Tests for pkplugin.pd.models and pkplugin.pd.predict.

Covers direct effect, effect compartment, IDR I-IV, registry helpers,
and hysteresis detection.

Refs: docs/03-algorithms/09-pkpd-models.md §1, §3
"""

from __future__ import annotations

import numpy as np
import pytest

from pkplugin.pd.fitting import detect_hysteresis
from pkplugin.pd.models import (
    PD_REGISTRY,
    PDModelType,
    get_pd_model,
    list_pd_models,
)
from pkplugin.pd.predict import predict_pd

# ---------------------------------------------------------------------------
# Registry / model-spec tests
# ---------------------------------------------------------------------------


def test_get_pd_model_known() -> None:
    spec = get_pd_model("emax")
    assert spec.name == "emax"
    assert spec.model_type == PDModelType.EMAX
    assert "E0" in spec.parameter_names
    assert not spec.requires_ode
    assert not spec.is_inhibitory


def test_get_pd_model_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown PD model"):
        get_pd_model("not_a_model")


def test_list_pd_models_returns_all() -> None:
    names = list_pd_models()
    assert set(names) == set(PD_REGISTRY.keys())
    assert "emax" in names
    assert "idr_i" in names


def test_inhibitory_emax_is_inhibitory() -> None:
    spec = get_pd_model("inhibitory_emax")
    assert spec.is_inhibitory
    assert not spec.requires_ode


def test_effect_compartment_requires_ode() -> None:
    spec = get_pd_model("effect_compartment")
    assert spec.requires_ode
    assert not spec.is_inhibitory


def test_idr_models_require_ode() -> None:
    for name in ("idr_i", "idr_ii", "idr_iii", "idr_iv"):
        spec = get_pd_model(name)
        assert spec.requires_ode, f"{name} should require ODE"


# ---------------------------------------------------------------------------
# Direct Emax: known params → predicted E values exact
# ---------------------------------------------------------------------------


def test_emax_known_params() -> None:
    """E = E0 + Emax*C / (EC50 + C) at known C values."""
    params = {"E0": 1.0, "Emax": 10.0, "EC50": 5.0}
    conc = np.array([0.0, 5.0, 10.0, 50.0], dtype=np.float64)
    times = np.arange(len(conc), dtype=np.float64)

    E_pred = predict_pd("emax", params, conc, times)

    expected = params["E0"] + params["Emax"] * conc / (params["EC50"] + conc)
    np.testing.assert_allclose(E_pred, expected, rtol=1e-12)


# ---------------------------------------------------------------------------
# Sigmoid Emax: gamma=1 reduces to plain Emax
# ---------------------------------------------------------------------------


def test_sigmoid_emax_gamma1_equals_emax() -> None:
    params_sig = {"E0": 2.0, "Emax": 8.0, "EC50": 4.0, "gamma": 1.0}
    params_emax = {"E0": 2.0, "Emax": 8.0, "EC50": 4.0}
    conc = np.array([0.0, 1.0, 4.0, 10.0, 100.0], dtype=np.float64)
    times = np.arange(len(conc), dtype=np.float64)

    E_sig = predict_pd("sigmoid_emax", params_sig, conc, times)
    E_emax = predict_pd("emax", params_emax, conc, times)

    np.testing.assert_allclose(E_sig, E_emax, rtol=1e-10)


# ---------------------------------------------------------------------------
# Inhibitory Emax: E < E0 always (when C > 0)
# ---------------------------------------------------------------------------


def test_inhibitory_emax_always_below_e0() -> None:
    params = {"E0": 10.0, "Imax": 0.8, "IC50": 2.0}
    conc = np.array([0.1, 1.0, 5.0, 20.0], dtype=np.float64)
    times = np.arange(len(conc), dtype=np.float64)

    E_pred = predict_pd("inhibitory_emax", params, conc, times)
    assert np.all(E_pred < params["E0"]), "Inhibitory Emax must give E < E0 for C > 0"


def test_inhibitory_emax_at_zero_conc() -> None:
    """At C=0 the inhibitory formula gives exactly E0."""
    params = {"E0": 10.0, "Imax": 1.0, "IC50": 3.0}
    conc = np.array([0.0], dtype=np.float64)
    times = np.array([0.0])
    E_pred = predict_pd("inhibitory_emax", params, conc, times)
    np.testing.assert_allclose(E_pred, [params["E0"]], rtol=1e-12)


# ---------------------------------------------------------------------------
# Effect compartment: lag between C and Ce
# ---------------------------------------------------------------------------


def test_effect_compartment_lag() -> None:
    """Ce should lag Cp; peak effect should occur after peak concentration."""
    # Bolus PK: C(t) = C0 * exp(-k*t)
    C0, k_pk = 10.0, 0.5
    times = np.linspace(0.0, 20.0, 200)
    conc = C0 * np.exp(-k_pk * times)

    # Slow Ke0 → strong lag (WNL convention: Ke0 capital K, WNL 6.4 p.385)
    params = {"E0": 0.0, "Emax": 1.0, "EC50": 2.0, "Ke0": 0.1}
    effects = predict_pd("effect_compartment", params, conc, times)

    # Concentration peaks at t=0; effect should peak later
    peak_conc_idx = int(np.argmax(conc))
    peak_effect_idx = int(np.argmax(effects))
    assert peak_effect_idx > peak_conc_idx, (
        f"Effect peak ({times[peak_effect_idx]:.2f}h) should lag "
        f"concentration peak ({times[peak_conc_idx]:.2f}h)"
    )


# ---------------------------------------------------------------------------
# IDR-I: baseline R(0) = kin/kout, depression at high C
# ---------------------------------------------------------------------------


def test_idr_i_baseline() -> None:
    """At C=0, R should remain at kin/kout (steady state)."""
    kin, kout = 10.0, 0.5
    params = {"kin": kin, "kout": kout, "Imax": 0.9, "IC50": 3.0}
    # Zero concentrations → no drug effect → R stays at baseline
    times = np.linspace(0.0, 20.0, 50)
    conc = np.zeros_like(times)

    R = predict_pd("idr_i", params, conc, times)

    expected_baseline = kin / kout
    # All values should be near the baseline (within 0.1%)
    np.testing.assert_allclose(R, expected_baseline, rtol=1e-3)


def test_idr_i_depression_at_high_conc() -> None:
    """High sustained concentration should depress R below baseline."""
    kin, kout = 10.0, 0.5
    params = {"kin": kin, "kout": kout, "Imax": 0.9, "IC50": 1.0}
    baseline = kin / kout

    times = np.linspace(0.0, 40.0, 100)
    conc = np.full_like(times, 50.0)  # high constant concentration

    R = predict_pd("idr_i", params, conc, times)

    # After sufficient time, R should be well below baseline
    assert R[-1] < baseline * 0.5, (
        f"IDR-I: R at steady state ({R[-1]:.2f}) should be < 50% of baseline ({baseline:.2f})"
    )


# ---------------------------------------------------------------------------
# IDR-II: baseline + inhibition of loss → R rises
# ---------------------------------------------------------------------------


def test_idr_ii_baseline() -> None:
    """At zero concentration IDR-II should stay at kin/kout."""
    kin, kout = 5.0, 0.2
    params = {"kin": kin, "kout": kout, "Imax": 0.8, "IC50": 2.0}
    times = np.linspace(0.0, 30.0, 80)
    conc = np.zeros_like(times)

    R = predict_pd("idr_ii", params, conc, times)
    np.testing.assert_allclose(R, kin / kout, rtol=1e-3)


def test_idr_ii_stimulation_direction() -> None:
    """IDR-II (inhibit loss): sustained C should raise R above baseline."""
    kin, kout = 5.0, 0.2
    params = {"kin": kin, "kout": kout, "Imax": 0.9, "IC50": 1.0}
    baseline = kin / kout

    times = np.linspace(0.0, 60.0, 150)
    conc = np.full_like(times, 20.0)

    R = predict_pd("idr_ii", params, conc, times)
    assert R[-1] > baseline * 1.5, (
        f"IDR-II: R at steady state ({R[-1]:.2f}) should exceed 1.5× baseline ({baseline:.2f})"
    )


# ---------------------------------------------------------------------------
# IDR-III: stimulation of production → R increases
# ---------------------------------------------------------------------------


def test_idr_iii_stimulation_direction() -> None:
    """IDR-III (stimulate production): high C should raise R."""
    kin, kout = 8.0, 0.4
    # WNL Model 53 params: Emax, EC50 (not Smax/SC50). Ref: WNL 6.4 p.238, 8.3 p.223.
    params = {"kin": kin, "kout": kout, "Emax": 3.0, "EC50": 2.0}
    baseline = kin / kout

    times = np.linspace(0.0, 40.0, 120)
    conc = np.full_like(times, 50.0)

    R = predict_pd("idr_iii", params, conc, times)
    assert R[-1] > baseline, (
        f"IDR-III: R at steady state ({R[-1]:.2f}) should exceed baseline ({baseline:.2f})"
    )


# ---------------------------------------------------------------------------
# IDR-IV: stimulation of loss → R decreases
# ---------------------------------------------------------------------------


def test_idr_iv_stimulation_direction() -> None:
    """IDR-IV (stimulate loss): high C should lower R."""
    kin, kout = 8.0, 0.4
    # WNL Model 54 params: Emax, EC50 (not Smax/SC50). Ref: WNL 6.4 p.238, 8.3 p.223.
    params = {"kin": kin, "kout": kout, "Emax": 2.0, "EC50": 1.0}
    baseline = kin / kout

    times = np.linspace(0.0, 40.0, 120)
    conc = np.full_like(times, 50.0)

    R = predict_pd("idr_iv", params, conc, times)
    assert R[-1] < baseline, (
        f"IDR-IV: R at steady state ({R[-1]:.2f}) should be below baseline ({baseline:.2f})"
    )


# ---------------------------------------------------------------------------
# Hysteresis detection
# ---------------------------------------------------------------------------


def test_hysteresis_counter_clockwise() -> None:
    """Synthetic counter-clockwise loop: effect lags concentration.

    Construct an explicit ellipse in C-E space traversed counter-clockwise
    over time: as t increases, the loop goes CCW (effect lags behind C).
    """
    # Explicit counter-clockwise ellipse parameterised by time:
    # C(t) = cos(t) + 1,   E(t) = sin(t) + 1   → CCW unit circle + offset
    t = np.linspace(0, 2 * np.pi * 0.99, 200)  # almost full loop
    conc = np.cos(t) + 2.0  # keeps C > 0
    effect = np.sin(t) + 2.0

    result = detect_hysteresis(conc, effect, t)
    assert result == "counter_clockwise", f"Expected counter_clockwise, got {result!r}"


def test_hysteresis_monotonic_decay() -> None:
    """Monotonically falling C-E: no meaningful loop → 'none'."""
    # C and E both decay together — no loop
    times = np.linspace(0, 10, 50)
    conc = 10.0 * np.exp(-0.3 * times)
    # E is directly proportional to C → no hysteresis
    effect = 2.0 * conc + 1.0

    result = detect_hysteresis(conc, effect, times)
    assert result == "none", f"Expected none, got {result!r}"
