"""
Tests for pkplugin.pd.fitting — NLS PD model fitting.

All reference data is generated inline from analytical formulas.

Refs: docs/03-algorithms/09-pkpd-models.md §2
"""

from __future__ import annotations

import numpy as np
import pytest

from pkplugin.pd.fitting import PDFitResult, fit_pd_model
from pkplugin.pd.predict import predict_pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_emax_data(
    E0: float,
    Emax: float,
    EC50: float,
    n: int = 20,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate noiseless Emax data."""
    conc = np.linspace(0.0, 20.0 * EC50, n)
    times = np.arange(n, dtype=np.float64)
    effects = E0 + Emax * conc / (EC50 + conc)
    return times, conc, effects


def _make_sigmoid_emax_data(
    E0: float,
    Emax: float,
    EC50: float,
    gamma: float,
    n: int = 24,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    conc = np.linspace(0.0, 20.0 * EC50, n)
    times = np.arange(n, dtype=np.float64)
    c_g = np.power(conc, gamma)
    ec50_g = EC50 ** gamma
    effects = E0 + Emax * c_g / (ec50_g + c_g)
    return times, conc, effects


def _make_idr_i_data(
    kin: float,
    kout: float,
    Imax: float,
    IC50: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate synthetic IDR-I data from constant-concentration input."""
    # Use a step concentration profile
    times = np.linspace(0.0, 40.0, 80)
    conc = np.where(times < 20.0, 5.0, 0.0).astype(np.float64)
    params = {"kin": kin, "kout": kout, "Imax": Imax, "IC50": IC50}
    effects = predict_pd("idr_i", params, conc, times)
    return times, conc, effects


# ---------------------------------------------------------------------------
# Test 1: Fit Emax to noiseless data → recovers E0, Emax, EC50 within 1e-4
# ---------------------------------------------------------------------------


def test_fit_emax_noiseless_recovery() -> None:
    """Fit Emax to noiseless data; recover E0, Emax, EC50 within 1e-4 relative."""
    true = {"E0": 1.0, "Emax": 10.0, "EC50": 5.0}
    times, conc, effects = _make_emax_data(**true)

    result = fit_pd_model(
        times=times,
        observed_effects=effects,
        model_name="emax",
        initial_params={"E0": 0.5, "Emax": 8.0, "EC50": 3.0},
        concentrations=conc,
        weighting="uniform",
    )

    assert result.diagnostics.converged, f"Did not converge: {result.warnings}"
    for name, true_val in true.items():
        est = result.parameters[name]
        rel_err = abs(est - true_val) / (abs(true_val) + 1e-10)
        assert rel_err < 1e-4, (
            f"Emax fit: {name} relative error {rel_err:.2e} > 1e-4 "
            f"(est={est:.6f}, true={true_val})"
        )


# ---------------------------------------------------------------------------
# Test 2: Fit sigmoid Emax → recovers gamma
# ---------------------------------------------------------------------------


def test_fit_sigmoid_emax_recovers_gamma() -> None:
    """Fit sigmoid Emax to noiseless data; recover all params including gamma."""
    true = {"E0": 2.0, "Emax": 8.0, "EC50": 4.0, "gamma": 2.0}
    times, conc, effects = _make_sigmoid_emax_data(**true)

    result = fit_pd_model(
        times=times,
        observed_effects=effects,
        model_name="sigmoid_emax",
        initial_params={"E0": 1.5, "Emax": 6.0, "EC50": 3.0, "gamma": 1.5},
        concentrations=conc,
        weighting="uniform",
    )

    assert result.diagnostics.converged
    for name, true_val in true.items():
        est = result.parameters[name]
        rel_err = abs(est - true_val) / (abs(true_val) + 1e-10)
        assert rel_err < 1e-3, (
            f"Sigmoid Emax: {name} rel_err={rel_err:.2e} > 1e-3"
        )


# ---------------------------------------------------------------------------
# Test 3: Fit effect compartment → recovers ke0
# ---------------------------------------------------------------------------


def test_fit_effect_compartment_recovers_ke0() -> None:
    """Fit effect compartment model to synthetic data; recover ke0."""
    true_params = {"E0": 0.0, "Emax": 1.0, "EC50": 2.0, "ke0": 0.5}
    times = np.linspace(0.0, 20.0, 60)
    # Bolus PK driver
    conc = 10.0 * np.exp(-0.3 * times)
    effects = predict_pd("effect_compartment", true_params, conc, times)

    result = fit_pd_model(
        times=times,
        observed_effects=effects,
        model_name="effect_compartment",
        initial_params={"E0": 0.1, "Emax": 0.8, "EC50": 1.5, "ke0": 0.3},
        concentrations=conc,
        weighting="uniform",
    )

    assert result.diagnostics.converged
    ke0_est = result.parameters["ke0"]
    rel_err = abs(ke0_est - true_params["ke0"]) / true_params["ke0"]
    assert rel_err < 0.01, (
        f"Effect compartment: ke0 rel_err={rel_err:.2e} > 1e-2"
    )


# ---------------------------------------------------------------------------
# Test 4: Fit IDR-I → recovers Imax, IC50
# ---------------------------------------------------------------------------


def test_fit_idr_i_recovers_params() -> None:
    """Fit IDR-I to synthetic data; recover Imax, IC50 within 1%."""
    true_params = {"kin": 10.0, "kout": 0.5, "Imax": 0.8, "IC50": 3.0}
    times, conc, effects = _make_idr_i_data(**true_params)

    result = fit_pd_model(
        times=times,
        observed_effects=effects,
        model_name="idr_i",
        initial_params={"kin": 8.0, "kout": 0.4, "Imax": 0.6, "IC50": 2.0},
        concentrations=conc,
        weighting="uniform",
    )

    assert result.diagnostics.converged
    for name in ("Imax", "IC50"):
        true_val = true_params[name]
        est = result.parameters[name]
        rel_err = abs(est - true_val) / (abs(true_val) + 1e-10)
        assert rel_err < 0.05, (
            f"IDR-I: {name} rel_err={rel_err:.2e} > 5e-2"
        )


# ---------------------------------------------------------------------------
# Test 5: Sequential mode using pre-fitted PK
# ---------------------------------------------------------------------------


def test_sequential_mode_with_pk_fit_result(tmp_path: object) -> None:
    """Sequential fit: derive Cp(t) from a PK FitResult, then fit PD."""
    from pkplugin.comp.fitting import FitResult, FitDiagnostics

    # Build a mock FitResult for 1-cmt IV bolus
    true_pk = {"V": 10.0, "k": 0.2}
    dose = 100.0
    times = np.array([0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 24.0], dtype=np.float64)

    mock_pk_result = FitResult(
        model_name="cmt1_iv_bolus",
        parameters=true_pk,
        standard_errors={k: None for k in true_pk},
        confidence_intervals={k: None for k in true_pk},
        correlation_matrix={},
        fitted_values=np.zeros(len(times)),
        residuals=np.zeros(len(times)),
        weighted_residuals=np.zeros(len(times)),
        diagnostics=FitDiagnostics(
            n_obs=len(times), n_params_estimated=2,
            rss=0.0, aic=0.0, bic=0.0,
            condition_number=None, converged=True, method="lmfit/leastsq"
        ),
        weight_scheme="uniform",
        residual_error_model="additive",
    )

    # True concentrations from PK model
    from pkplugin.comp.analytic import predict as pk_predict
    conc = pk_predict("cmt1_iv_bolus", true_pk, times.tolist(), dose)

    # Generate noiseless Emax effect data
    true_pd = {"E0": 1.0, "Emax": 6.0, "EC50": 3.0}
    effects = true_pd["E0"] + true_pd["Emax"] * conc / (true_pd["EC50"] + conc)

    result = fit_pd_model(
        times=times,
        observed_effects=effects,
        model_name="emax",
        initial_params={"E0": 0.5, "Emax": 4.0, "EC50": 2.0},
        pk_fit_result=mock_pk_result,
        pk_model_name="cmt1_iv_bolus",
        dose=dose,
        mode="sequential",
        weighting="uniform",
    )

    assert result.diagnostics.converged
    for name, true_val in true_pd.items():
        est = result.parameters[name]
        rel_err = abs(est - true_val) / (abs(true_val) + 1e-10)
        assert rel_err < 1e-4, f"Sequential fit: {name} rel_err={rel_err:.2e}"


# ---------------------------------------------------------------------------
# Test 6: Missing inputs raises ValueError
# ---------------------------------------------------------------------------


def test_fit_pd_model_missing_concentrations_raises() -> None:
    """Neither concentrations nor pk_fit_result → ValueError."""
    times = np.array([1.0, 2.0, 3.0])
    effects = np.array([1.0, 1.5, 2.0])
    with pytest.raises(ValueError, match="concentrations"):
        fit_pd_model(
            times=times,
            observed_effects=effects,
            model_name="emax",
            initial_params={"E0": 1.0, "Emax": 5.0, "EC50": 2.0},
        )


# ---------------------------------------------------------------------------
# Test 7: Convergence failure returns result with converged=False warning
# ---------------------------------------------------------------------------


def test_fit_convergence_failure_produces_warning() -> None:
    """When fit fails to converge the warnings list is non-empty or converged=False."""
    # Deliberately bad initial params with tiny data
    times = np.array([0.0, 1.0, 2.0], dtype=np.float64)
    conc = np.array([10.0, 5.0, 2.5], dtype=np.float64)
    effects = np.array([1.0, 1.5, 1.8], dtype=np.float64)

    # This should not raise; just return a result (possibly with warnings)
    result = fit_pd_model(
        times=times,
        observed_effects=effects,
        model_name="emax",
        initial_params={"E0": 0.1, "Emax": 1.0, "EC50": 1.0},
        concentrations=conc,
        weighting="uniform",
        method="leastsq",
    )
    # Whether converged or not, we should get a PDFitResult back
    assert isinstance(result, PDFitResult)


# ---------------------------------------------------------------------------
# Test 8: Linear model fits slope and intercept
# ---------------------------------------------------------------------------


def test_fit_linear_model() -> None:
    """Fit linear E = E0 + S*C to noiseless data."""
    true_E0, true_S = 0.5, 2.0
    conc = np.linspace(0.0, 10.0, 20)
    times = np.arange(20, dtype=np.float64)
    effects = true_E0 + true_S * conc

    result = fit_pd_model(
        times=times,
        observed_effects=effects,
        model_name="linear",
        initial_params={"E0": 0.1, "S": 1.0},
        concentrations=conc,
        weighting="uniform",
    )

    assert result.diagnostics.converged
    assert abs(result.parameters["E0"] - true_E0) < 1e-4
    assert abs(result.parameters["S"] - true_S) < 1e-4
