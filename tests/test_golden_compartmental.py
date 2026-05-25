"""
Golden regression tests for compartmental PK model fitting.

All tests use noiseless synthetic data generated from known parameters
and verify that the fitter recovers them to specified tolerances.

Run with: pytest -m golden tests/test_golden_compartmental.py

Tests:
  1. Fit 1-cmt IV bolus to noiseless data → V error < 1e-6, k error < 1e-6
  2. Fit 1-cmt PO (Bateman) → V_F, ka, k errors < 1e-3
  3. Fit 2-cmt IV bolus to noiseless data → all 4 micros within 1e-4
  4. AIC/BIC comparison: 1-cmt data → 2-cmt should have higher (worse) AIC
"""

from __future__ import annotations

import numpy as np
import pytest

from pkplugin.comp.analytic import predict
from pkplugin.comp.fitting import FitResult, fit_pk_model

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dosing_event(
    dose: float,
    route: str = "iv_bolus",
) -> list[object]:
    from pkplugin.comp.ode import DosingEvent

    return [DosingEvent(time=0.0, amount=dose, route=route)]  # type: ignore[arg-type]


def _times_iv() -> list[float]:
    """Dense time grid appropriate for IV models (0–48 h)."""
    return [0.25, 0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 36.0, 48.0]


def _times_po() -> list[float]:
    """Time grid for oral models (includes early absorption phase)."""
    return [0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 24.0, 36.0, 48.0]


# ---------------------------------------------------------------------------
# Golden 1 — 1-cmt IV bolus: V error < 1e-6, k error < 1e-6
# ---------------------------------------------------------------------------


_TRUE_1CMT_IV = {"V": 12.0, "k": 0.15}
_DOSE_1CMT_IV = 100.0


@pytest.fixture(scope="module")
def fit_1cmt_iv() -> FitResult:
    """Fit 1-cmt IV bolus to noiseless data."""
    times = np.asarray(_times_iv(), dtype=np.float64)
    conc = predict("cmt1_iv_bolus", _TRUE_1CMT_IV, times, _DOSE_1CMT_IV)
    return fit_pk_model(
        times=times,
        observed=conc,
        model_name="cmt1_iv_bolus",
        initial_params={"V": 10.0, "k": 0.1},
        dose=_DOSE_1CMT_IV,
        weighting="1_over_y_squared",
        residual_error="proportional",
    )


@pytest.mark.golden
def test_golden_1cmt_iv_bolus_V(fit_1cmt_iv: FitResult) -> None:
    """1-cmt IV bolus: V estimate must match truth to within 1e-6 relative error."""
    est = fit_1cmt_iv.parameters["V"]
    true = _TRUE_1CMT_IV["V"]
    rel_err = abs(est - true) / true
    assert rel_err < 1e-6, f"V={est:.10f}, true={true}, rel_err={rel_err:.2e}"


@pytest.mark.golden
def test_golden_1cmt_iv_bolus_k(fit_1cmt_iv: FitResult) -> None:
    """1-cmt IV bolus: k estimate must match truth to within 1e-6 relative error."""
    est = fit_1cmt_iv.parameters["k"]
    true = _TRUE_1CMT_IV["k"]
    rel_err = abs(est - true) / true
    assert rel_err < 1e-6, f"k={est:.10f}, true={true}, rel_err={rel_err:.2e}"


@pytest.mark.golden
def test_golden_1cmt_iv_bolus_converged(fit_1cmt_iv: FitResult) -> None:
    """1-cmt IV bolus fit must converge on noiseless data."""
    assert fit_1cmt_iv.diagnostics.converged, f"Fit did not converge: {fit_1cmt_iv.warnings}"


# ---------------------------------------------------------------------------
# Golden 2 — 1-cmt PO (Bateman): V_F, ka, k errors < 1e-3
# ---------------------------------------------------------------------------


_TRUE_1CMT_PO = {"V_F": 20.0, "ka": 0.8, "k": 0.1}
_DOSE_1CMT_PO = 200.0


@pytest.fixture(scope="module")
def fit_1cmt_po() -> FitResult:
    """Fit 1-cmt oral (Bateman) to noiseless data."""
    times = np.asarray(_times_po(), dtype=np.float64)
    conc = predict("cmt1_po", _TRUE_1CMT_PO, times, _DOSE_1CMT_PO)
    from pkplugin.comp.ode import DosingEvent

    dosing = [DosingEvent(time=0.0, amount=_DOSE_1CMT_PO, route="oral")]
    return fit_pk_model(
        times=times,
        observed=conc,
        model_name="cmt1_po",
        initial_params={"V_F": 15.0, "ka": 0.5, "k": 0.08},
        dosing_events=dosing,
        weighting="1_over_y_squared",
        residual_error="proportional",
    )


@pytest.mark.golden
def test_golden_1cmt_po_V_F(fit_1cmt_po: FitResult) -> None:
    """1-cmt PO: V/F estimate must match truth to within 1e-3 relative error."""
    est = fit_1cmt_po.parameters["V_F"]
    true = _TRUE_1CMT_PO["V_F"]
    rel_err = abs(est - true) / true
    assert rel_err < 1e-3, f"V_F={est:.8f}, true={true}, rel_err={rel_err:.2e}"


@pytest.mark.golden
def test_golden_1cmt_po_ka(fit_1cmt_po: FitResult) -> None:
    """1-cmt PO: ka estimate must match truth to within 1e-3 relative error."""
    est = fit_1cmt_po.parameters["ka"]
    true = _TRUE_1CMT_PO["ka"]
    rel_err = abs(est - true) / true
    assert rel_err < 1e-3, f"ka={est:.8f}, true={true}, rel_err={rel_err:.2e}"


@pytest.mark.golden
def test_golden_1cmt_po_k(fit_1cmt_po: FitResult) -> None:
    """1-cmt PO: k estimate must match truth to within 1e-3 relative error."""
    est = fit_1cmt_po.parameters["k"]
    true = _TRUE_1CMT_PO["k"]
    rel_err = abs(est - true) / true
    assert rel_err < 1e-3, f"k={est:.8f}, true={true}, rel_err={rel_err:.2e}"


# ---------------------------------------------------------------------------
# Golden 3 — 2-cmt IV bolus: all 4 micro-rate constants within 1e-4
# ---------------------------------------------------------------------------


_TRUE_2CMT_IV = {"V1": 8.0, "k10": 0.2, "k12": 0.15, "k21": 0.1}
_DOSE_2CMT_IV = 100.0


@pytest.fixture(scope="module")
def fit_2cmt_iv() -> FitResult:
    """Fit 2-cmt IV bolus to noiseless data."""
    times = np.asarray(_times_iv(), dtype=np.float64)
    conc = predict("cmt2_iv_bolus", _TRUE_2CMT_IV, times, _DOSE_2CMT_IV)
    return fit_pk_model(
        times=times,
        observed=conc,
        model_name="cmt2_iv_bolus",
        initial_params={"V1": 6.0, "k10": 0.15, "k12": 0.1, "k21": 0.08},
        dose=_DOSE_2CMT_IV,
        weighting="1_over_y_squared",
        residual_error="proportional",
    )


@pytest.mark.golden
def test_golden_2cmt_iv_bolus_V1(fit_2cmt_iv: FitResult) -> None:
    """2-cmt IV bolus: V1 estimate within 1e-4 relative error."""
    est = fit_2cmt_iv.parameters["V1"]
    true = _TRUE_2CMT_IV["V1"]
    rel_err = abs(est - true) / true
    assert rel_err < 1e-4, f"V1={est:.8f}, true={true}, rel_err={rel_err:.2e}"


@pytest.mark.golden
def test_golden_2cmt_iv_bolus_k10(fit_2cmt_iv: FitResult) -> None:
    """2-cmt IV bolus: k10 estimate within 1e-4 relative error."""
    est = fit_2cmt_iv.parameters["k10"]
    true = _TRUE_2CMT_IV["k10"]
    rel_err = abs(est - true) / true
    assert rel_err < 1e-4, f"k10={est:.8f}, true={true}, rel_err={rel_err:.2e}"


@pytest.mark.golden
def test_golden_2cmt_iv_bolus_k12(fit_2cmt_iv: FitResult) -> None:
    """2-cmt IV bolus: k12 estimate within 1e-4 relative error."""
    est = fit_2cmt_iv.parameters["k12"]
    true = _TRUE_2CMT_IV["k12"]
    rel_err = abs(est - true) / true
    assert rel_err < 1e-4, f"k12={est:.8f}, true={true}, rel_err={rel_err:.2e}"


@pytest.mark.golden
def test_golden_2cmt_iv_bolus_k21(fit_2cmt_iv: FitResult) -> None:
    """2-cmt IV bolus: k21 estimate within 1e-4 relative error."""
    est = fit_2cmt_iv.parameters["k21"]
    true = _TRUE_2CMT_IV["k21"]
    rel_err = abs(est - true) / true
    assert rel_err < 1e-4, f"k21={est:.8f}, true={true}, rel_err={rel_err:.2e}"


# ---------------------------------------------------------------------------
# Golden 4 — AIC comparison: 1-cmt data → 2-cmt should have higher (worse) AIC
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def aic_comparison_fits() -> tuple[FitResult, FitResult]:
    """Fit both 1-cmt and 2-cmt IV bolus to purely 1-cmt synthetic data."""
    true_params = {"V": 12.0, "k": 0.15}
    dose = 100.0
    times = np.asarray(_times_iv(), dtype=np.float64)
    conc = predict("cmt1_iv_bolus", true_params, times, dose)

    fit_1cmt = fit_pk_model(
        times=times,
        observed=conc,
        model_name="cmt1_iv_bolus",
        initial_params={"V": 10.0, "k": 0.1},
        dose=dose,
        weighting="1_over_y_squared",
        residual_error="proportional",
    )

    fit_2cmt = fit_pk_model(
        times=times,
        observed=conc,
        model_name="cmt2_iv_bolus",
        initial_params={"V1": 10.0, "k10": 0.1, "k12": 0.05, "k21": 0.04},
        dose=dose,
        weighting="1_over_y_squared",
        residual_error="proportional",
    )

    return fit_1cmt, fit_2cmt


@pytest.mark.golden
def test_golden_aic_1cmt_better_than_2cmt(
    aic_comparison_fits: tuple[FitResult, FitResult],
) -> None:
    """On purely 1-cmt data, 2-cmt AIC should be higher (overfitting penalty).

    WinNonlin AIC = N*ln(SS/N) + 2k. With noiseless 1-cmt data, the
    2-cmt model has more parameters (k=4 vs k=2) and the extra parameters
    give negligible improvement in RSS, so AIC_{2cmt} > AIC_{1cmt}.
    """
    fit_1cmt, fit_2cmt = aic_comparison_fits
    aic_1 = fit_1cmt.diagnostics.aic
    aic_2 = fit_2cmt.diagnostics.aic
    assert aic_2 > aic_1, (
        f"Expected 2-cmt AIC ({aic_2:.4f}) > 1-cmt AIC ({aic_1:.4f}) "
        "on purely 1-cmt data (overfitting penalty)"
    )


@pytest.mark.golden
def test_golden_bic_1cmt_better_than_2cmt(
    aic_comparison_fits: tuple[FitResult, FitResult],
) -> None:
    """On purely 1-cmt data, 2-cmt BIC should also be higher."""
    fit_1cmt, fit_2cmt = aic_comparison_fits
    bic_1 = fit_1cmt.diagnostics.bic
    bic_2 = fit_2cmt.diagnostics.bic
    assert bic_2 > bic_1, (
        f"Expected 2-cmt BIC ({bic_2:.4f}) > 1-cmt BIC ({bic_1:.4f}) on purely 1-cmt data"
    )
