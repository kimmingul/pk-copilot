"""
NLS / weighted-least-squares PK model fitting via lmfit.

Supports closed-form (analytic) and ODE-based prediction, five weighting
schemes, and additive / proportional / combined residual error models.

AIC and BIC follow the WinNonlin convention:
    AIC = N * ln(SS/N) + 2k
    BIC = N * ln(SS/N) + k * ln(N)

Refs: docs/03-algorithms/08-compartmental-models.md §4–§6
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import NDArray

try:
    import lmfit  # type: ignore[import-untyped]
except ImportError as _exc:
    raise ImportError("lmfit is required for compartmental fitting") from _exc

from pkplugin.comp.ode import DosingEvent, simulate_ode

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

WeightScheme = Literal[
    "uniform",
    "1_over_y",
    "1_over_y_squared",
    "1_over_pred",
    "1_over_pred_squared",
]

ResidualErrorModel = Literal["additive", "proportional", "combined"]


@dataclass(frozen=True)
class ParamSpec:
    """Specification for a single model parameter.

    Attributes:
        name: Parameter name (must match the model's parameter dict key).
        initial: Initial guess.
        lower: Lower bound (default 0).
        upper: Upper bound (default +inf).
        vary: Whether to estimate this parameter (False = fix at ``initial``).
    """

    name: str
    initial: float
    lower: float = 0.0
    upper: float = float("inf")
    vary: bool = True


@dataclass(frozen=True)
class FitDiagnostics:
    """Goodness-of-fit summary statistics.

    AIC and BIC follow the WinNonlin (N·ln(SS/N) + k·penalty) convention.
    """

    n_obs: int
    n_params_estimated: int
    rss: float
    aic: float
    bic: float
    condition_number: float | None
    converged: bool
    method: str


@dataclass(frozen=True)
class FitResult:
    """Full result of a PK model fit.

    Attributes:
        model_name: Canonical model code.
        parameters: Point estimates for all estimated parameters.
        standard_errors: Standard errors (None if not available).
        confidence_intervals: 95 % Wald CIs (None if SE not available).
        correlation_matrix: Off-diagonal pairwise correlations; keys are
            ``(param_a, param_b)`` tuples.
        fitted_values: Predicted concentrations at the observation times.
        residuals: Raw residuals ``y_pred - y_obs``.
        weighted_residuals: Residuals scaled by ``sqrt(w_i)``.
        diagnostics: AIC, BIC, RSS, etc.
        weight_scheme: Weighting scheme used.
        residual_error_model: Residual error model.
        warnings: Non-fatal messages (convergence, bound, conditioning).
    """

    model_name: str
    parameters: dict[str, float]
    standard_errors: dict[str, float | None]
    confidence_intervals: dict[str, tuple[float, float] | None]
    correlation_matrix: dict[tuple[str, str], float]
    fitted_values: NDArray[np.float64]
    residuals: NDArray[np.float64]
    weighted_residuals: NDArray[np.float64]
    diagnostics: FitDiagnostics
    weight_scheme: WeightScheme
    residual_error_model: ResidualErrorModel
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ITERATIVE_WEIGHTS: frozenset[WeightScheme] = frozenset(
    ["1_over_pred", "1_over_pred_squared"]
)

_N_ITER_PRED_WEIGHTS = 3  # number of re-fitting passes for pred-based weights


def _compute_weights(
    scheme: WeightScheme,
    y_obs: NDArray[np.float64],
    y_pred: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Compute per-point weights.  Returns w_i ≥ 0."""
    n = len(y_obs)
    w = np.ones(n, dtype=np.float64)

    if scheme == "uniform":
        pass  # w already 1

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


def _build_lmfit_params(
    specs: list[ParamSpec],
) -> "lmfit.Parameters":
    """Convert a list of :class:`ParamSpec` to an lmfit Parameters object."""
    lm_params = lmfit.Parameters()
    for sp in specs:
        lm_params.add(
            sp.name,
            value=sp.initial,
            min=sp.lower,
            max=sp.upper,
            vary=sp.vary,
        )
    return lm_params


def _predict(
    model_name: str,
    pdict: dict[str, float],
    times: NDArray[np.float64],
    dosing_events: list[DosingEvent],
    use_ode: bool,
    rtol: float,
    atol: float,
) -> NDArray[np.float64]:
    """Run prediction, catching solver errors and returning NaN array."""
    try:
        return simulate_ode(
            model_name,
            pdict,
            dosing_events,
            times.tolist(),
            rtol=rtol,
            atol=atol,
        )
    except Exception:
        return np.full(len(times), np.nan, dtype=np.float64)


def _normalise_specs(
    initial_params: dict[str, float] | list[ParamSpec],
) -> list[ParamSpec]:
    if isinstance(initial_params, dict):
        return [ParamSpec(name=k, initial=v) for k, v in initial_params.items()]
    return list(initial_params)


def _aic_bic(
    rss: float,
    n: int,
    k: int,
) -> tuple[float, float]:
    """WinNonlin-convention AIC and BIC.

    AIC = N * ln(SS/N) + 2k
    BIC = N * ln(SS/N) + k * ln(N)
    """
    if n <= 0 or rss <= 0.0:
        return float("nan"), float("nan")
    log_ss_n = np.log(rss / n)
    aic = n * log_ss_n + 2.0 * k
    bic = n * log_ss_n + k * np.log(n)
    return float(aic), float(bic)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fit_pk_model(
    times: NDArray[np.float64],
    observed: NDArray[np.float64],
    model_name: str,
    initial_params: dict[str, float] | list[ParamSpec],
    dose: float | None = None,
    dosing_events: list[DosingEvent] | None = None,
    *,
    weighting: WeightScheme = "1_over_y_squared",
    residual_error: ResidualErrorModel = "proportional",
    use_ode: bool = False,
    method: str = "leastsq",
    rtol: float = 1e-9,
    atol: float = 1e-12,
) -> FitResult:
    """Fit a PK model to concentration-time observations.

    Args:
        times: Observation times (hr).
        observed: Measured concentrations at ``times``.
        model_name: Canonical model code (see :mod:`pkplugin.comp.ode`).
        initial_params: Either a ``dict[name, initial_value]`` or a list of
            :class:`ParamSpec` objects with bounds.
        dose: Single-dose amount (mg).  Ignored when ``dosing_events`` is
            provided.  Constructs a single IV-bolus event at t=0 if set.
        dosing_events: Explicit list of :class:`DosingEvent`.  Takes
            precedence over ``dose``.
        weighting: Weighting scheme for residuals.
        residual_error: Residual error model (currently informational; the
            weighting already encodes the variance structure).
        use_ode: Force ODE prediction even for models with analytic solutions.
            Always True for MM models.
        method: lmfit minimisation method (default ``"leastsq"``).
        rtol: Relative ODE tolerance.
        atol: Absolute ODE tolerance.

    Returns:
        :class:`FitResult` with parameter estimates, diagnostics, and
        residuals.

    Refs: docs/03-algorithms/08-compartmental-models.md §4–§6
    """
    times_arr = np.asarray(times, dtype=np.float64)
    obs_arr = np.asarray(observed, dtype=np.float64)

    if len(times_arr) != len(obs_arr):
        raise ValueError("times and observed must have the same length")

    # Build dosing event list
    if dosing_events is not None:
        ev_list: list[DosingEvent] = list(dosing_events)
    elif dose is not None:
        # Infer route from model name
        if "po" in model_name:
            route: Literal["iv_bolus", "iv_infusion", "oral"] = "oral"
        else:
            route = "iv_bolus"
        ev_list = [DosingEvent(time=0.0, amount=dose, route=route)]
    else:
        raise ValueError(
            "Either dose or dosing_events must be provided."
        )

    specs = _normalise_specs(initial_params)
    fit_warnings: list[str] = []

    # For pred-based weights we run multiple passes
    is_iterative = weighting in _ITERATIVE_WEIGHTS
    n_passes = _N_ITER_PRED_WEIGHTS if is_iterative else 1

    # Initial uniform-weight fit for iterative weight initialisation
    current_weights = np.ones(len(obs_arr), dtype=np.float64)
    lmfit_result: "lmfit.MinimizerResult | None" = None

    for _pass in range(n_passes):
        lm_params = _build_lmfit_params(specs)
        w_snapshot = current_weights.copy()

        def _residual(
            p: "lmfit.Parameters",
            _times: NDArray[np.float64] = times_arr,
            _obs: NDArray[np.float64] = obs_arr,
            _ev: list[DosingEvent] = ev_list,
            _w: NDArray[np.float64] = w_snapshot,
        ) -> NDArray[np.float64]:
            pdict = {k: float(v) for k, v in p.valuesdict().items()}
            y_pred = _predict(
                model_name, pdict, _times, _ev, use_ode, rtol, atol
            )
            raw_res = y_pred - _obs
            return raw_res * np.sqrt(_w)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lmfit_result = lmfit.minimize(
                _residual,
                lm_params,
                method=method,
                nan_policy="propagate",
            )

        if _pass < n_passes - 1:
            # Update pred-based weights for next pass
            best_pdict = {k: float(v) for k, v in lmfit_result.params.valuesdict().items()}
            y_pred_new = _predict(
                model_name, best_pdict, times_arr, ev_list, use_ode, rtol, atol
            )
            current_weights = _compute_weights(weighting, obs_arr, y_pred_new)
        else:
            # Final pass: compute weights for diagnostics
            best_pdict = {k: float(v) for k, v in lmfit_result.params.valuesdict().items()}
            y_pred_final = _predict(
                model_name, best_pdict, times_arr, ev_list, use_ode, rtol, atol
            )
            if not is_iterative:
                current_weights = _compute_weights(weighting, obs_arr, y_pred_final)

    assert lmfit_result is not None

    # -----------------------------------------------------------------------
    # Extract results
    # -----------------------------------------------------------------------
    best_pdict = {k: float(v) for k, v in lmfit_result.params.valuesdict().items()}
    y_pred_final = _predict(
        model_name, best_pdict, times_arr, ev_list, use_ode, rtol, atol
    )
    final_weights = current_weights

    raw_residuals = y_pred_final - obs_arr
    weighted_residuals = raw_residuals * np.sqrt(final_weights)

    # Weighted RSS
    rss = float(np.sum(weighted_residuals ** 2))
    n_obs = len(obs_arr)
    estimated_names = [
        sp.name for sp in specs if sp.vary
    ]
    n_params = len(estimated_names)

    aic, bic = _aic_bic(rss, n_obs, n_params)

    # Standard errors and CIs
    ses: dict[str, float | None] = {}
    cis: dict[str, tuple[float, float] | None] = {}
    corr_matrix: dict[tuple[str, str], float] = {}

    for name in best_pdict:
        p = lmfit_result.params[name]
        se = p.stderr
        if se is not None and np.isfinite(se) and se > 0:
            ses[name] = float(se)
            est = float(p.value)
            cis[name] = (est - 1.96 * float(se), est + 1.96 * float(se))
        else:
            ses[name] = None
            cis[name] = None

    # Correlation matrix
    for i, na in enumerate(estimated_names):
        for j, nb in enumerate(estimated_names):
            if i == j:
                corr_matrix[(na, nb)] = 1.0
            else:
                c = lmfit_result.params[na].correl
                if c and nb in c:
                    corr_matrix[(na, nb)] = float(c[nb])
                else:
                    corr_matrix[(na, nb)] = float("nan")

    # Condition number from covariance matrix
    cond_num: float | None = None
    try:
        cov = lmfit_result.covar
        if cov is not None:
            cond_num = float(np.linalg.cond(cov))
    except Exception:
        cond_num = None

    # -----------------------------------------------------------------------
    # Warnings
    # -----------------------------------------------------------------------
    if not lmfit_result.success:
        fit_warnings.append(
            f"Fit did not converge: {lmfit_result.message}"
        )

    for sp in specs:
        if not sp.vary:
            continue
        est = best_pdict[sp.name]
        at_lower = sp.lower > -np.inf and abs(est - sp.lower) < 1e-6 * (abs(sp.lower) + 1e-10)
        at_upper = sp.upper < np.inf and abs(est - sp.upper) < 1e-6 * (abs(sp.upper) + 1e-10)
        if at_lower or at_upper:
            fit_warnings.append(
                f"Parameter {sp.name!r} is at its bound (estimate={est:.4g})."
            )

    if cond_num is not None and cond_num > 1000.0:
        fit_warnings.append(
            f"Large condition number ({cond_num:.2g}): parameter estimates "
            "may be poorly determined."
        )

    for name, se in ses.items():
        if se is None:
            fit_warnings.append(
                f"Standard error not available for parameter {name!r}."
            )

    # Check for negative parameters that should be positive
    for name, val in best_pdict.items():
        if val < 0:
            fit_warnings.append(
                f"Parameter {name!r} has a negative estimate ({val:.4g})."
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

    return FitResult(
        model_name=model_name,
        parameters=best_pdict,
        standard_errors=ses,
        confidence_intervals=cis,
        correlation_matrix=corr_matrix,
        fitted_values=y_pred_final,
        residuals=raw_residuals,
        weighted_residuals=weighted_residuals,
        diagnostics=diagnostics,
        weight_scheme=weighting,
        residual_error_model=residual_error,
        warnings=fit_warnings,
    )
