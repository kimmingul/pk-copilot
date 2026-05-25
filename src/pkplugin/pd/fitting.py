"""
NLS PD model fitting via lmfit.

Supports sequential and simultaneous PK-PD fitting, five weighting schemes,
and hysteresis detection.

Sequential mode (default):
  1. Accept pre-computed concentrations OR derive them from a previously-fitted
     PK model (``pk_fit_result`` + ``pk_model_name`` + ``dose``).
  2. Fit PD parameters against observed effects.

Simultaneous mode:
  Jointly fit PK and PD parameters in one optimisation (requires
  ``pk_fit_result`` to supply PK model name + initial PK parameters).

Refs: docs/03-algorithms/09-pkpd-models.md §2
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np
from numpy.typing import NDArray

try:
    import lmfit  # type: ignore[import-untyped]
except ImportError as _exc:
    raise ImportError("lmfit is required for PD fitting") from _exc

from pkplugin.comp.fitting import FitDiagnostics
from pkplugin.pd.predict import predict_pd

if TYPE_CHECKING:
    from pkplugin.comp.fitting import FitResult as PKFitResult


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PDFitResult:
    """Full result of a PD model fit.

    Attributes:
        model_name: Canonical PD model code.
        parameters: Point estimates for all estimated parameters.
        standard_errors: Standard errors (None if not available).
        confidence_intervals: 95 % Wald CIs (None if SE not available).
        fitted_effects: Predicted effects at the observation times.
        residuals: Raw residuals ``y_pred - y_obs``.
        diagnostics: AIC, BIC, RSS, etc. (reuses :class:`~pkplugin.comp.fitting.FitDiagnostics`).
        warnings: Non-fatal messages.
    """

    model_name: str
    parameters: dict[str, float]
    standard_errors: dict[str, float | None]
    confidence_intervals: dict[str, tuple[float, float] | None]
    fitted_effects: NDArray[np.float64]
    residuals: NDArray[np.float64]
    diagnostics: FitDiagnostics
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers (mirror comp/fitting.py style)
# ---------------------------------------------------------------------------


def _aic_bic(rss: float, n: int, k: int) -> tuple[float, float]:
    """WinNonlin-convention AIC and BIC."""
    if n <= 0 or rss <= 0.0:
        return float("nan"), float("nan")
    log_ss_n = np.log(rss / n)
    aic = n * log_ss_n + 2.0 * k
    bic = n * log_ss_n + k * np.log(n)
    return float(aic), float(bic)


def _compute_weights(
    scheme: str,
    y_obs: NDArray[np.float64],
    y_pred: NDArray[np.float64],
) -> NDArray[np.float64]:
    n = len(y_obs)
    w = np.ones(n, dtype=np.float64)
    if scheme == "uniform":
        pass
    elif scheme == "1_over_y":
        mask = np.abs(y_obs) > 1e-300
        w[mask] = 1.0 / np.abs(y_obs[mask])
        w[~mask] = 0.0
    elif scheme == "1_over_y_squared":
        mask = np.abs(y_obs) > 1e-300
        w[mask] = 1.0 / y_obs[mask] ** 2
        w[~mask] = 0.0
    elif scheme == "1_over_pred":
        mask = np.abs(y_pred) > 1e-300
        w[mask] = 1.0 / np.abs(y_pred[mask])
        w[~mask] = 0.0
    elif scheme == "1_over_pred_squared":
        mask = np.abs(y_pred) > 1e-300
        w[mask] = 1.0 / y_pred[mask] ** 2
        w[~mask] = 0.0
    return w


def _concentrations_from_pk(
    pk_fit_result: PKFitResult,
    pk_model_name: str,
    dose: float,
    times: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Compute concentrations at *times* from a previously-fitted PK model."""
    from pkplugin.comp.ode import DosingEvent, simulate_ode

    route: Literal["iv_bolus", "iv_infusion", "oral"]
    if "po" in pk_model_name:
        route = "oral"
    else:
        route = "iv_bolus"
    dosing_events = [DosingEvent(time=0.0, amount=dose, route=route)]
    return simulate_ode(
        pk_model_name,
        pk_fit_result.parameters,
        dosing_events,
        times.tolist(),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fit_pd_model(
    times: NDArray[np.float64],
    observed_effects: NDArray[np.float64],
    model_name: str,
    initial_params: dict[str, float],
    concentrations: NDArray[np.float64] | None = None,
    pk_fit_result: PKFitResult | None = None,
    pk_model_name: str | None = None,
    dose: float | None = None,
    mode: Literal["sequential", "simultaneous"] = "sequential",
    weighting: str = "uniform",
    method: str = "leastsq",
) -> PDFitResult:
    """Fit a PD model to observed effect-time data.

    Args:
        times: Observation times.
        observed_effects: Measured effect values at ``times``.
        model_name: Canonical PD model code (see
            :data:`~pkplugin.pd.models.PD_REGISTRY`).
        initial_params: Initial guesses for all PD parameters.
        concentrations: Pre-computed plasma concentrations at ``times``.
            Required when ``pk_fit_result`` is ``None``.
        pk_fit_result: Previously-fitted PK result (see
            :func:`~pkplugin.comp.fitting.fit_pk_model`).  Used to derive
            ``Cp(t)`` when ``concentrations`` is ``None``.
        pk_model_name: Canonical PK model code.  Required when
            ``pk_fit_result`` is provided.
        dose: Dose amount.  Required when ``pk_fit_result`` is provided.
        mode: ``"sequential"`` (default) or ``"simultaneous"``.  In
            simultaneous mode all PK and PD parameters are jointly optimised.
        weighting: Weighting scheme for residuals (``"uniform"`` default).
        method: lmfit minimisation method.

    Returns:
        :class:`PDFitResult` with parameter estimates and diagnostics.

    Raises:
        ValueError: If required inputs are missing.

    Refs: docs/03-algorithms/09-pkpd-models.md §2
    """
    times_arr = np.asarray(times, dtype=np.float64)
    obs_arr = np.asarray(observed_effects, dtype=np.float64)

    if len(times_arr) != len(obs_arr):
        raise ValueError("times and observed_effects must have the same length")

    fit_warnings: list[str] = []

    # --- Resolve concentrations ---
    if concentrations is not None:
        conc_arr = np.asarray(concentrations, dtype=np.float64)
    elif pk_fit_result is not None:
        if pk_model_name is None:
            raise ValueError("pk_model_name is required when pk_fit_result is provided")
        if dose is None:
            raise ValueError("dose is required when pk_fit_result is provided")
        conc_arr = _concentrations_from_pk(pk_fit_result, pk_model_name, dose, times_arr)
    else:
        raise ValueError("Either concentrations or pk_fit_result must be provided.")

    if mode == "simultaneous":
        if pk_fit_result is None:
            raise ValueError("simultaneous mode requires pk_fit_result to supply PK parameters")
        if pk_model_name is None or dose is None:
            raise ValueError("simultaneous mode requires pk_model_name and dose")
        return _fit_simultaneous(
            times_arr,
            obs_arr,
            model_name,
            initial_params,
            pk_fit_result,
            pk_model_name,
            dose,
            weighting,
            method,
            fit_warnings,
        )

    # --- Sequential fit ---
    # Parameters are unconstrained by default — callers may supply negative
    # values (e.g. negative Emax for inhibitory effect compartment models).
    lm_params = lmfit.Parameters()
    for name, val in initial_params.items():
        lm_params.add(name, value=val)

    current_weights = np.ones(len(obs_arr), dtype=np.float64)
    lmfit_result: lmfit.MinimizerResult | None = None

    _ITERATIVE = {"1_over_pred", "1_over_pred_squared"}
    n_passes = 3 if weighting in _ITERATIVE else 1

    for _pass in range(n_passes):
        w_snapshot = current_weights.copy()
        c_snapshot = conc_arr.copy()

        def _residual(
            p: lmfit.Parameters,
            _times: NDArray[np.float64] = times_arr,
            _obs: NDArray[np.float64] = obs_arr,
            _conc: NDArray[np.float64] = c_snapshot,
            _w: NDArray[np.float64] = w_snapshot,
        ) -> NDArray[np.float64]:
            pdict = {k: float(v) for k, v in p.valuesdict().items()}
            try:
                y_pred = predict_pd(model_name, pdict, _conc, _times)
            except Exception:
                return np.full(len(_obs), np.nan, dtype=np.float64)
            return (y_pred - _obs) * np.sqrt(_w)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lmfit_result = lmfit.minimize(
                _residual,
                lm_params,
                method=method,
                nan_policy="propagate",
            )

        if _pass < n_passes - 1:
            best_pdict = {k: float(v) for k, v in lmfit_result.params.valuesdict().items()}
            y_pred_new = predict_pd(model_name, best_pdict, conc_arr, times_arr)
            current_weights = _compute_weights(weighting, obs_arr, y_pred_new)

    assert lmfit_result is not None

    best_pdict = {k: float(v) for k, v in lmfit_result.params.valuesdict().items()}
    y_pred_final = predict_pd(model_name, best_pdict, conc_arr, times_arr)
    final_weights = current_weights

    raw_residuals = y_pred_final - obs_arr
    weighted_residuals = raw_residuals * np.sqrt(final_weights)
    rss = float(np.sum(weighted_residuals**2))
    n_obs = len(obs_arr)
    n_params = len([k for k in initial_params])

    aic, bic = _aic_bic(rss, n_obs, n_params)

    ses: dict[str, float | None] = {}
    cis: dict[str, tuple[float, float] | None] = {}
    for pname in best_pdict:
        p = lmfit_result.params[pname]
        se = p.stderr
        if se is not None and np.isfinite(se) and se > 0:
            ses[pname] = float(se)
            est = float(p.value)
            cis[pname] = (est - 1.96 * float(se), est + 1.96 * float(se))
        else:
            ses[pname] = None
            cis[pname] = None

    cond_num: float | None = None
    try:
        cov = lmfit_result.covar
        if cov is not None:
            cond_num = float(np.linalg.cond(cov))
    except Exception:
        cond_num = None

    if not lmfit_result.success:
        fit_warnings.append(f"Fit did not converge: {lmfit_result.message}")

    for pname, se in ses.items():
        if se is None:
            fit_warnings.append(f"Standard error not available for parameter {pname!r}.")

    if cond_num is not None and cond_num > 1000.0:
        fit_warnings.append(
            f"Large condition number ({cond_num:.2g}): parameter estimates "
            "may be poorly determined."
        )

    diagnostics = FitDiagnostics(
        n_obs=n_obs,
        n_params_estimated=n_params,
        rss=rss,
        aic=aic,
        bic=bic,
        condition_number=cond_num,
        converged=bool(lmfit_result.success),
        method=f"lmfit/{method}",
    )

    return PDFitResult(
        model_name=model_name,
        parameters=best_pdict,
        standard_errors=ses,
        confidence_intervals=cis,
        fitted_effects=y_pred_final,
        residuals=raw_residuals,
        diagnostics=diagnostics,
        warnings=fit_warnings,
    )


def _fit_simultaneous(
    times_arr: NDArray[np.float64],
    obs_arr: NDArray[np.float64],
    pd_model_name: str,
    pd_initial_params: dict[str, float],
    pk_fit_result: PKFitResult,
    pk_model_name: str,
    dose: float,
    weighting: str,
    method: str,
    fit_warnings: list[str],
) -> PDFitResult:
    """Jointly optimise PK + PD parameters."""
    from pkplugin.comp.ode import DosingEvent, simulate_ode

    route: Literal["iv_bolus", "iv_infusion", "oral"]
    if "po" in pk_model_name:
        route = "oral"
    else:
        route = "iv_bolus"

    lm_params = lmfit.Parameters()
    for pname, val in pk_fit_result.parameters.items():
        lm_params.add(f"pk_{pname}", value=val, min=0.0)  # PK params always positive
    for pname, val in pd_initial_params.items():
        lm_params.add(f"pd_{pname}", value=val)  # PD params unconstrained

    dosing_events = [DosingEvent(time=0.0, amount=dose, route=route)]

    def _residual_sim(
        p: lmfit.Parameters,
    ) -> NDArray[np.float64]:
        pdict = {k: float(v) for k, v in p.valuesdict().items()}
        pk_dict = {k[3:]: v for k, v in pdict.items() if k.startswith("pk_")}
        pd_dict = {k[3:]: v for k, v in pdict.items() if k.startswith("pd_")}
        try:
            conc = simulate_ode(pk_model_name, pk_dict, dosing_events, times_arr.tolist())
            y_pred = predict_pd(pd_model_name, pd_dict, conc, times_arr)
        except Exception:
            return np.full(len(obs_arr), np.nan, dtype=np.float64)
        return y_pred - obs_arr

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lmfit_result = lmfit.minimize(
            _residual_sim,
            lm_params,
            method=method,
            nan_policy="propagate",
        )

    all_best: dict[str, float] = {k: float(v) for k, v in lmfit_result.params.valuesdict().items()}
    pd_best = {k[3:]: v for k, v in all_best.items() if k.startswith("pd_")}
    pk_best = {k[3:]: v for k, v in all_best.items() if k.startswith("pk_")}

    conc_final = simulate_ode(pk_model_name, pk_best, dosing_events, times_arr.tolist())
    y_pred_final = predict_pd(pd_model_name, pd_best, conc_final, times_arr)

    raw_residuals = y_pred_final - obs_arr
    rss = float(np.sum(raw_residuals**2))
    n_obs = len(obs_arr)
    n_params = len(pd_best) + len(pk_best)
    aic, bic = _aic_bic(rss, n_obs, n_params)

    ses: dict[str, float | None] = {}
    cis: dict[str, tuple[float, float] | None] = {}
    for pname in pd_best:
        key = f"pd_{pname}"
        p = lmfit_result.params[key]
        se = p.stderr
        if se is not None and np.isfinite(se) and se > 0:
            ses[pname] = float(se)
            est = float(p.value)
            cis[pname] = (est - 1.96 * float(se), est + 1.96 * float(se))
        else:
            ses[pname] = None
            cis[pname] = None

    cond_num: float | None = None
    try:
        cov = lmfit_result.covar
        if cov is not None:
            cond_num = float(np.linalg.cond(cov))
    except Exception:
        cond_num = None

    if not lmfit_result.success:
        fit_warnings.append(f"Simultaneous fit did not converge: {lmfit_result.message}")

    diagnostics = FitDiagnostics(
        n_obs=n_obs,
        n_params_estimated=n_params,
        rss=rss,
        aic=aic,
        bic=bic,
        condition_number=cond_num,
        converged=bool(lmfit_result.success),
        method=f"lmfit/{method}/simultaneous",
    )

    return PDFitResult(
        model_name=pd_model_name,
        parameters=pd_best,
        standard_errors=ses,
        confidence_intervals=cis,
        fitted_effects=y_pred_final,
        residuals=raw_residuals,
        diagnostics=diagnostics,
        warnings=fit_warnings,
    )


# ---------------------------------------------------------------------------
# Hysteresis detection
# ---------------------------------------------------------------------------


def detect_hysteresis(
    concentrations: NDArray[np.float64],
    effects: NDArray[np.float64],
    times: NDArray[np.float64],
) -> Literal["clockwise", "counter_clockwise", "none"]:
    """Determine the rotation direction of the C vs E loop over time.

    Returns ``'counter_clockwise'`` if effect lags concentration (suggesting
    effect compartment model), ``'clockwise'`` for tolerance/sensitization,
    ``'none'`` for monotonic relationships.

    The signed area of the C-E loop is computed using the shoelace formula.
    Positive signed area → counter-clockwise; negative → clockwise.
    A near-zero area relative to the bounding box indicates no meaningful
    hysteresis.

    Refs: docs/03-algorithms/09-pkpd-models.md §3
    """
    c = np.asarray(concentrations, dtype=np.float64)
    e = np.asarray(effects, dtype=np.float64)
    t = np.asarray(times, dtype=np.float64)

    # Sort by time so loop traces the temporal path
    order = np.argsort(t)
    c_s = c[order]
    e_s = e[order]

    n = len(c_s)
    if n < 3:
        return "none"

    # Shoelace formula for signed area of closed polygon
    # Close the loop by appending the first point
    cx = np.append(c_s, c_s[0])
    ey = np.append(e_s, e_s[0])
    signed_area = 0.5 * float(np.sum(cx[:-1] * ey[1:] - cx[1:] * ey[:-1]))

    # Normalise by bounding-box area to get a dimensionless measure
    c_range = float(np.ptp(c_s))
    e_range = float(np.ptp(e_s))
    bbox_area = c_range * e_range

    if bbox_area < 1e-300:
        return "none"

    relative_area = abs(signed_area) / bbox_area

    _THRESHOLD = 0.05  # 5 % of bounding box: below this is "monotonic"
    if relative_area < _THRESHOLD:
        return "none"

    if signed_area > 0.0:
        return "counter_clockwise"
    return "clockwise"
