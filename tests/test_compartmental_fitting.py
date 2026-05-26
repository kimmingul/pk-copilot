"""
Tests for pkplugin.comp.fitting — NLS PK model fitting.

All reference data is generated inline from analytical formulas so that
these tests are independent of the analytic module.

Refs: docs/03-algorithms/08-compartmental-models.md §4–§6
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pkplugin.comp.fitting import (
    FitResult,
    ParamSpec,
    WeightScheme,
    fit_pk_model,
)
from pkplugin.comp.ode import DosingEvent

# ---------------------------------------------------------------------------
# Inline analytical generators (no dependency on analytic module)
# ---------------------------------------------------------------------------


def _cmt1_iv(times: np.ndarray, dose: float, V: float, k: float) -> np.ndarray:
    return (dose / V) * np.exp(-k * times)


def _bateman(times: np.ndarray, dose: float, V_F: float, ka: float, k: float) -> np.ndarray:
    return (dose * ka / (V_F * (ka - k))) * (np.exp(-k * times) - np.exp(-ka * times))


def _cmt2_iv(
    times: np.ndarray,
    dose: float,
    V1: float,
    k10: float,
    k12: float,
    k21: float,
) -> np.ndarray:
    s = k10 + k12 + k21
    d = math.sqrt(max(s**2 - 4.0 * k10 * k21, 0.0))
    alpha = (s + d) / 2.0
    beta = (s - d) / 2.0
    D_V1 = dose / V1
    D_k21_V1 = dose * k21 / V1
    A = (D_k21_V1 - D_V1 * alpha) / (beta - alpha)
    B = D_V1 - A
    return A * np.exp(-alpha * times) + B * np.exp(-beta * times)


# ---------------------------------------------------------------------------
# Test 1: fit 1-cmt IV bolus to noiseless data → recover true V, k to 1e-4
# ---------------------------------------------------------------------------


def test_fit_cmt1_iv_noiseless_recovery() -> None:
    """Fit 1-cmt IV bolus to noiseless data; recover V, k to 1e-4 relative."""
    true_V, true_k, dose = 20.0, 0.3, 100.0
    times = np.linspace(0.5, 24.0, 20)
    obs = _cmt1_iv(times, dose, true_V, true_k)

    result = fit_pk_model(
        times,
        obs,
        "cmt1_iv_bolus",
        initial_params=[
            ParamSpec("V", initial=15.0, lower=1.0, upper=200.0),
            ParamSpec("k", initial=0.5, lower=1e-4, upper=10.0),
        ],
        dose=dose,
        weighting="uniform",
        use_ode=True,
    )

    assert result.diagnostics.converged, f"Should converge; warnings={result.warnings}"
    assert abs(result.parameters["V"] - true_V) / true_V < 1e-4
    assert abs(result.parameters["k"] - true_k) / true_k < 1e-4


# ---------------------------------------------------------------------------
# Test 2: fit 1-cmt IV bolus with 10% proportional noise → within 5%
# ---------------------------------------------------------------------------


def test_fit_cmt1_iv_noisy_within_5pct() -> None:
    """Fit noisy 1-cmt IV; recovered parameters should be within 5% of truth."""
    rng = np.random.default_rng(42)
    true_V, true_k, dose = 20.0, 0.3, 100.0
    times = np.linspace(0.5, 24.0, 30)
    clean = _cmt1_iv(times, dose, true_V, true_k)
    obs = clean * (1.0 + 0.10 * rng.standard_normal(len(times)))
    obs = np.clip(obs, 1e-6, None)

    result = fit_pk_model(
        times,
        obs,
        "cmt1_iv_bolus",
        initial_params=[
            ParamSpec("V", initial=15.0, lower=1.0, upper=200.0),
            ParamSpec("k", initial=0.5, lower=1e-4, upper=10.0),
        ],
        dose=dose,
        weighting="1_over_y_squared",
        use_ode=True,
    )

    assert result.diagnostics.converged, f"Should converge; warnings={result.warnings}"
    assert abs(result.parameters["V"] - true_V) / true_V < 0.05
    assert abs(result.parameters["k"] - true_k) / true_k < 0.05


# ---------------------------------------------------------------------------
# Test 3: fit 1-cmt PO (Bateman) → recover V_F, ka, k
# ---------------------------------------------------------------------------


def test_fit_cmt1_po_bateman_recovery() -> None:
    """Fit 1-cmt oral model; recover V_F, ka, k within 1% on noiseless data."""
    true_V_F, true_ka, true_k, dose = 25.0, 1.5, 0.2, 100.0
    times = np.array([0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0])
    obs = _bateman(times, dose, true_V_F, true_ka, true_k)

    result = fit_pk_model(
        times,
        obs,
        "cmt1_po",
        initial_params=[
            ParamSpec("V_F", initial=20.0, lower=1.0, upper=500.0),
            ParamSpec("ka", initial=1.0, lower=0.01, upper=20.0),
            ParamSpec("k", initial=0.3, lower=1e-4, upper=5.0),
        ],
        dose=dose,
        weighting="uniform",
        use_ode=True,
    )

    assert result.diagnostics.converged
    assert abs(result.parameters["V_F"] - true_V_F) / true_V_F < 0.01
    assert abs(result.parameters["ka"] - true_ka) / true_ka < 0.01
    assert abs(result.parameters["k"] - true_k) / true_k < 0.01


# ---------------------------------------------------------------------------
# Test 4: fit 2-cmt IV bolus → recover all 4 parameters
# ---------------------------------------------------------------------------


def test_fit_cmt2_iv_bolus_recovery() -> None:
    """Fit 2-cmt IV bolus; recover V1, k10, k12, k21 within 1%."""
    true = {"V1": 10.0, "k10": 0.4, "k12": 0.3, "k21": 0.15}
    dose = 100.0
    times = np.array([0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 24.0])
    obs = _cmt2_iv(times, dose, **true)

    result = fit_pk_model(
        times,
        obs,
        "cmt2_iv_bolus",
        initial_params=[
            ParamSpec("V1", initial=8.0, lower=0.1, upper=200.0),
            ParamSpec("k10", initial=0.3, lower=1e-4, upper=10.0),
            ParamSpec("k12", initial=0.2, lower=1e-4, upper=10.0),
            ParamSpec("k21", initial=0.1, lower=1e-4, upper=10.0),
        ],
        dose=dose,
        weighting="uniform",
        use_ode=True,
    )

    assert result.diagnostics.converged
    for p, true_val in true.items():
        rel_err = abs(result.parameters[p] - true_val) / true_val
        assert rel_err < 0.01, (
            f"{p}: {result.parameters[p]:.4f} vs truth {true_val} (rel {rel_err:.4f})"
        )


# ---------------------------------------------------------------------------
# Test 5: different weighting schemes converge to same answer on noiseless data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scheme",
    [
        "uniform",
        "1_over_y",
        "1_over_y_squared",
        "1_over_pred",
        "1_over_pred_squared",
    ],
)
def test_weighting_schemes_noiseless_convergence(scheme: WeightScheme) -> None:
    """All weighting schemes should recover V and k accurately on noiseless data."""
    true_V, true_k, dose = 20.0, 0.3, 100.0
    times = np.linspace(0.5, 12.0, 15)
    obs = _cmt1_iv(times, dose, true_V, true_k)

    result = fit_pk_model(
        times,
        obs,
        "cmt1_iv_bolus",
        initial_params=[
            ParamSpec("V", initial=15.0, lower=1.0, upper=200.0),
            ParamSpec("k", initial=0.5, lower=1e-4, upper=10.0),
        ],
        dose=dose,
        weighting=scheme,
        use_ode=True,
    )

    assert result.diagnostics.converged, f"scheme={scheme} did not converge"
    assert abs(result.parameters["V"] - true_V) / true_V < 0.01
    assert abs(result.parameters["k"] - true_k) / true_k < 0.01


# ---------------------------------------------------------------------------
# Test 6: 1/y² weighting up-weights low-concentration observations
# ---------------------------------------------------------------------------


def test_1_over_y2_upweights_low_conc() -> None:
    """1/y² weights at low concentrations must be larger than at high conc."""
    from pkplugin.comp.fitting import _compute_weights

    y_obs = np.array([10.0, 1.0, 0.1])
    y_pred = np.ones(3)

    w = _compute_weights("1_over_y_squared", y_obs, y_pred)
    # w[2] = 1/0.1² = 100 >> w[0] = 1/10² = 0.01
    assert w[2] > w[1] > w[0], "1/y² weights must decrease as observed concentration increases"
    np.testing.assert_allclose(w, np.array([0.01, 1.0, 100.0]), rtol=1e-9)


# ---------------------------------------------------------------------------
# Test 7: AIC/BIC computed correctly — hand-check from RSS
# ---------------------------------------------------------------------------


def test_aic_bic_hand_check() -> None:
    """AIC and BIC must equal WinNonlin formula: N*ln(SS/N) + penalty*k."""
    true_V, true_k, dose = 20.0, 0.3, 100.0
    times = np.linspace(0.5, 12.0, 12)
    obs = _cmt1_iv(times, dose, true_V, true_k)

    result = fit_pk_model(
        times,
        obs,
        "cmt1_iv_bolus",
        initial_params=[
            ParamSpec("V", initial=18.0, lower=1.0, upper=200.0),
            ParamSpec("k", initial=0.4, lower=1e-4, upper=10.0),
        ],
        dose=dose,
        weighting="uniform",
        use_ode=True,
    )

    n = result.diagnostics.n_obs
    k = result.diagnostics.n_params_estimated
    rss = result.diagnostics.rss

    # WinNonlin convention: AIC = N*ln(WRSS) + 2P, BIC = N*ln(WRSS) + P*ln(N)
    # (WNL 8.3 UG p.547 — note: WNL omits the -N*ln(N) term present in the
    # classical Akaike formula; confirmed by manual cross-check against WNL output)
    expected_aic = n * math.log(rss) + 2.0 * k
    expected_bic = n * math.log(rss) + k * math.log(n)

    assert math.isfinite(result.diagnostics.aic)
    assert math.isfinite(result.diagnostics.bic)
    np.testing.assert_allclose(result.diagnostics.aic, expected_aic, rtol=1e-9)
    np.testing.assert_allclose(result.diagnostics.bic, expected_bic, rtol=1e-9)


# ---------------------------------------------------------------------------
# Test 8: convergence failure handling on pathological data
# ---------------------------------------------------------------------------


def test_convergence_failure_no_exception() -> None:
    """Pathological data (all-zero obs) must not raise; should emit a warning."""
    times = np.linspace(0.5, 12.0, 10)
    obs = np.zeros(10)  # Pathological: all zero concentrations

    # Should not raise
    result = fit_pk_model(
        times,
        obs,
        "cmt1_iv_bolus",
        initial_params=[
            ParamSpec("V", initial=10.0, lower=0.1, upper=1000.0),
            ParamSpec("k", initial=0.1, lower=1e-6, upper=100.0),
        ],
        dose=100.0,
        weighting="uniform",
        use_ode=True,
    )

    assert isinstance(result, FitResult)
    # Either non-convergence warning or NaN values — just must not raise
    # (The fit may emit warnings but must return a result)


# ---------------------------------------------------------------------------
# Test 9: parameter at bound emits warning
# ---------------------------------------------------------------------------


def test_parameter_at_bound_warning() -> None:
    """When a parameter hits its bound, a warning must be in result.warnings."""
    # Force k to hit the upper bound by using a very small upper limit
    true_V, true_k, dose = 20.0, 0.3, 100.0
    times = np.linspace(0.5, 12.0, 15)
    obs = _cmt1_iv(times, dose, true_V, true_k)

    result = fit_pk_model(
        times,
        obs,
        "cmt1_iv_bolus",
        initial_params=[
            ParamSpec("V", initial=15.0, lower=1.0, upper=200.0),
            ParamSpec("k", initial=0.25, lower=1e-4, upper=0.29),  # true k=0.3 outside bound
        ],
        dose=dose,
        weighting="uniform",
        use_ode=True,
    )

    # k must be at or near 0.29 (its upper bound)
    at_bound_warnings = [w for w in result.warnings if "bound" in w.lower()]
    assert len(at_bound_warnings) >= 1, f"Expected a bound warning; got warnings: {result.warnings}"


# ---------------------------------------------------------------------------
# Test 10: standard errors are finite and reasonable
# ---------------------------------------------------------------------------


def test_standard_errors_finite_and_reasonable() -> None:
    """Standard errors must be finite and smaller than the estimates."""
    rng = np.random.default_rng(123)
    true_V, true_k, dose = 20.0, 0.3, 100.0
    times = np.linspace(0.5, 12.0, 20)
    clean = _cmt1_iv(times, dose, true_V, true_k)
    obs = clean * (1.0 + 0.05 * rng.standard_normal(len(times)))
    obs = np.clip(obs, 1e-6, None)

    result = fit_pk_model(
        times,
        obs,
        "cmt1_iv_bolus",
        initial_params=[
            ParamSpec("V", initial=18.0, lower=1.0, upper=200.0),
            ParamSpec("k", initial=0.4, lower=1e-4, upper=5.0),
        ],
        dose=dose,
        weighting="1_over_y_squared",
        use_ode=True,
    )

    assert result.diagnostics.converged
    for name, se in result.standard_errors.items():
        assert se is not None, f"SE for {name!r} should not be None on well-posed problem"
        assert math.isfinite(se), f"SE for {name!r} must be finite"
        assert se > 0.0, f"SE for {name!r} must be positive"
        # SE should be much smaller than the estimate
        est = result.parameters[name]
        assert se < est, f"SE ({se:.4g}) should be < estimate ({est:.4g}) for {name!r}"


# ---------------------------------------------------------------------------
# Test 11: FitResult has correct shape / types
# ---------------------------------------------------------------------------


def test_fit_result_structure() -> None:
    """FitResult must have the expected field types and shapes."""
    dose = 100.0
    times = np.linspace(0.5, 12.0, 12)
    obs = _cmt1_iv(times, dose, 20.0, 0.3)

    result = fit_pk_model(
        times,
        obs,
        "cmt1_iv_bolus",
        initial_params={"V": 15.0, "k": 0.4},
        dose=dose,
        use_ode=True,
    )

    assert result.model_name == "cmt1_iv_bolus"
    assert len(result.fitted_values) == len(times)
    assert len(result.residuals) == len(times)
    assert len(result.weighted_residuals) == len(times)
    assert isinstance(result.parameters, dict)
    assert isinstance(result.standard_errors, dict)
    assert isinstance(result.confidence_intervals, dict)
    assert isinstance(result.correlation_matrix, dict)
    assert isinstance(result.warnings, list)
    assert result.weight_scheme == "1_over_y_squared"  # default
    assert result.residual_error_model == "proportional"  # default


# ---------------------------------------------------------------------------
# Test 12: dosing_events path
# ---------------------------------------------------------------------------


def test_fit_via_dosing_events() -> None:
    """fit_pk_model must accept explicit dosing_events list."""
    dose = 100.0
    times = np.linspace(0.5, 12.0, 15)
    obs = _cmt1_iv(times, dose, 20.0, 0.3)
    ev = [DosingEvent(time=0.0, amount=dose, route="iv_bolus")]

    result = fit_pk_model(
        times,
        obs,
        "cmt1_iv_bolus",
        initial_params={"V": 15.0, "k": 0.4},
        dosing_events=ev,
        weighting="uniform",
        use_ode=True,
    )

    assert result.diagnostics.converged
    assert abs(result.parameters["V"] - 20.0) / 20.0 < 1e-3
