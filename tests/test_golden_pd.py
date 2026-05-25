"""
Golden regression tests for PK/PD link model fitting.

All tests use noiseless synthetic data generated from known parameters.

Run with: pytest -m golden tests/test_golden_pd.py

Tests:
  1. Emax on warfarin-style INR data (synthetic)
  2. Effect compartment on propofol-BIS-style data
  3. IDR-I on corticosteroid-style data
"""

from __future__ import annotations

import numpy as np
import pytest

from pkplugin.pd.fitting import PDFitResult, fit_pd_model
from pkplugin.pd.predict import predict_pd


# ---------------------------------------------------------------------------
# Golden 1 — Emax on warfarin-style INR data
# ---------------------------------------------------------------------------


# Warfarin-style: Emax PD on INR baseline ~1.1; max INR ~4; EC50 ~1.5 mg/L
_WARFARIN_PD_TRUE = {"E0": 1.1, "Emax": 3.0, "EC50": 1.5}
_WARFARIN_CONC = np.array(
    [0.0, 0.2, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0],
    dtype=np.float64,
)
_WARFARIN_TIMES = np.arange(len(_WARFARIN_CONC), dtype=np.float64)


@pytest.fixture(scope="module")
def fit_warfarin_emax() -> PDFitResult:
    params = _WARFARIN_PD_TRUE
    effects = params["E0"] + params["Emax"] * _WARFARIN_CONC / (
        params["EC50"] + _WARFARIN_CONC
    )
    return fit_pd_model(
        times=_WARFARIN_TIMES,
        observed_effects=effects,
        model_name="emax",
        initial_params={"E0": 0.8, "Emax": 2.0, "EC50": 1.0},
        concentrations=_WARFARIN_CONC,
        weighting="uniform",
    )


@pytest.mark.golden
def test_warfarin_emax_converged(fit_warfarin_emax: PDFitResult) -> None:
    assert fit_warfarin_emax.diagnostics.converged


@pytest.mark.golden
def test_warfarin_emax_E0(fit_warfarin_emax: PDFitResult) -> None:
    est = fit_warfarin_emax.parameters["E0"]
    assert abs(est - _WARFARIN_PD_TRUE["E0"]) < 1e-4, f"E0={est}"


@pytest.mark.golden
def test_warfarin_emax_Emax(fit_warfarin_emax: PDFitResult) -> None:
    est = fit_warfarin_emax.parameters["Emax"]
    assert abs(est - _WARFARIN_PD_TRUE["Emax"]) < 1e-4, f"Emax={est}"


@pytest.mark.golden
def test_warfarin_emax_EC50(fit_warfarin_emax: PDFitResult) -> None:
    est = fit_warfarin_emax.parameters["EC50"]
    assert abs(est - _WARFARIN_PD_TRUE["EC50"]) < 1e-4, f"EC50={est}"


# ---------------------------------------------------------------------------
# Golden 2 — Effect compartment on propofol-BIS-style data
# ---------------------------------------------------------------------------


# Propofol-BIS-style: ke0~0.26/min; EC50~3 mcg/mL; BIS baseline ~95
_PROPOFOL_PD_TRUE = {"E0": 95.0, "Emax": -90.0, "EC50": 3.0, "ke0": 0.26}
_PROPOFOL_TIMES = np.linspace(0.0, 30.0, 80)
# Bolus PK: C0=10, k=0.3 (simplified)
_PROPOFOL_CONC = 10.0 * np.exp(-0.3 * _PROPOFOL_TIMES)


@pytest.fixture(scope="module")
def fit_propofol_effect_compartment() -> PDFitResult:
    effects = predict_pd(
        "effect_compartment", _PROPOFOL_PD_TRUE, _PROPOFOL_CONC, _PROPOFOL_TIMES
    )
    return fit_pd_model(
        times=_PROPOFOL_TIMES,
        observed_effects=effects,
        model_name="effect_compartment",
        initial_params={"E0": 90.0, "Emax": -80.0, "EC50": 2.0, "ke0": 0.15},
        concentrations=_PROPOFOL_CONC,
        weighting="uniform",
    )


@pytest.mark.golden
def test_propofol_effect_compartment_converged(
    fit_propofol_effect_compartment: PDFitResult,
) -> None:
    assert fit_propofol_effect_compartment.diagnostics.converged


@pytest.mark.golden
def test_propofol_effect_compartment_ke0(
    fit_propofol_effect_compartment: PDFitResult,
) -> None:
    est = fit_propofol_effect_compartment.parameters["ke0"]
    rel_err = abs(est - _PROPOFOL_PD_TRUE["ke0"]) / _PROPOFOL_PD_TRUE["ke0"]
    assert rel_err < 0.01, f"ke0 rel_err={rel_err:.3e}"


@pytest.mark.golden
def test_propofol_effect_compartment_EC50(
    fit_propofol_effect_compartment: PDFitResult,
) -> None:
    est = fit_propofol_effect_compartment.parameters["EC50"]
    rel_err = abs(est - _PROPOFOL_PD_TRUE["EC50"]) / _PROPOFOL_PD_TRUE["EC50"]
    assert rel_err < 0.01, f"EC50 rel_err={rel_err:.3e}"


# ---------------------------------------------------------------------------
# Golden 3 — IDR-I on corticosteroid-style data
# ---------------------------------------------------------------------------


# Corticosteroid cortisol suppression style: IDR-I
# kin~100 ng/mL/h, kout~0.2/h (baseline~500 ng/mL), Imax~0.9, IC50~0.05 mcg/mL
_CORTISOL_PD_TRUE = {"kin": 100.0, "kout": 0.2, "Imax": 0.9, "IC50": 0.1}
_CORTISOL_TIMES = np.linspace(0.0, 50.0, 100)
# Simplified PK: step concentration
_CORTISOL_CONC = np.where(_CORTISOL_TIMES < 24.0, 0.5, 0.0).astype(np.float64)


@pytest.fixture(scope="module")
def fit_cortisol_idr_i() -> PDFitResult:
    effects = predict_pd(
        "idr_i", _CORTISOL_PD_TRUE, _CORTISOL_CONC, _CORTISOL_TIMES
    )
    return fit_pd_model(
        times=_CORTISOL_TIMES,
        observed_effects=effects,
        model_name="idr_i",
        initial_params={"kin": 80.0, "kout": 0.15, "Imax": 0.7, "IC50": 0.05},
        concentrations=_CORTISOL_CONC,
        weighting="uniform",
    )


@pytest.mark.golden
def test_cortisol_idr_i_converged(fit_cortisol_idr_i: PDFitResult) -> None:
    assert fit_cortisol_idr_i.diagnostics.converged


@pytest.mark.golden
def test_cortisol_idr_i_Imax(fit_cortisol_idr_i: PDFitResult) -> None:
    est = fit_cortisol_idr_i.parameters["Imax"]
    rel_err = abs(est - _CORTISOL_PD_TRUE["Imax"]) / _CORTISOL_PD_TRUE["Imax"]
    assert rel_err < 0.05, f"Imax rel_err={rel_err:.3e}"


@pytest.mark.golden
def test_cortisol_idr_i_IC50(fit_cortisol_idr_i: PDFitResult) -> None:
    est = fit_cortisol_idr_i.parameters["IC50"]
    rel_err = abs(est - _CORTISOL_PD_TRUE["IC50"]) / _CORTISOL_PD_TRUE["IC50"]
    assert rel_err < 0.05, f"IC50 rel_err={rel_err:.3e}"
