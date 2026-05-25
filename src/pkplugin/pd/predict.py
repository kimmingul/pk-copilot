"""
PD effect prediction for all supported model families.

For direct models (linear, log_linear, emax, sigmoid_emax, inhibitory_emax)
each observation time is evaluated algebraically at the corresponding
concentration.

For ODE models the driver C(t) is constructed by linear interpolation of the
supplied (times, concentrations) arrays, then integrated with
:func:`scipy.integrate.solve_ivp`.

Refs: docs/03-algorithms/09-pkpd-models.md §1, §3
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import solve_ivp  # type: ignore[import-untyped]
from scipy.interpolate import interp1d  # type: ignore[import-untyped]

from pkplugin.pd.models import PDModelType, get_pd_model


# ---------------------------------------------------------------------------
# Direct-effect formulas
# ---------------------------------------------------------------------------


def _linear(
    params: dict[str, float],
    c: NDArray[np.float64],
) -> NDArray[np.float64]:
    """E = E0 + S * C."""
    return params["E0"] + params["S"] * c


def _log_linear(
    params: dict[str, float],
    c: NDArray[np.float64],
) -> NDArray[np.float64]:
    """E = E0 + S * ln(C).  C > 0 enforced by np.maximum."""
    c_pos = np.maximum(c, 1e-300)
    return params["E0"] + params["S"] * np.log(c_pos)


def _emax(
    params: dict[str, float],
    c: NDArray[np.float64],
) -> NDArray[np.float64]:
    """E = E0 + Emax * C / (EC50 + C)."""
    return params["E0"] + params["Emax"] * c / (params["EC50"] + c)


def _sigmoid_emax(
    params: dict[str, float],
    c: NDArray[np.float64],
) -> NDArray[np.float64]:
    """E = E0 + Emax * C^gamma / (EC50^gamma + C^gamma)."""
    gamma = params["gamma"]
    ec50 = params["EC50"]
    c_g = np.power(np.maximum(c, 0.0), gamma)
    ec50_g: NDArray[np.float64] = np.power(np.float64(ec50), np.float64(gamma))
    return params["E0"] + params["Emax"] * c_g / (ec50_g + c_g)


def _inhibitory_emax(
    params: dict[str, float],
    c: NDArray[np.float64],
) -> NDArray[np.float64]:
    """E = E0 - Imax * C / (IC50 + C)."""
    return params["E0"] - params["Imax"] * c / (params["IC50"] + c)


# ---------------------------------------------------------------------------
# ODE helpers
# ---------------------------------------------------------------------------


def _make_driver(
    times: NDArray[np.float64],
    concentrations: NDArray[np.float64],
) -> interp1d:
    """Build a linear interpolation function for C(t)."""
    return interp1d(
        times,
        concentrations,
        kind="linear",
        bounds_error=False,
        fill_value=(float(concentrations[0]), float(concentrations[-1])),
    )


def _integrate_effect_compartment(
    params: dict[str, float],
    times: NDArray[np.float64],
    concentrations: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Integrate effect compartment + apply Emax at each Ce(t).

    dCe/dt = ke0 * (Cp(t) - Ce)
    E(t) = E0 + Emax * Ce / (EC50 + Ce)
    """
    ke0 = params["ke0"]
    E0 = params["E0"]
    Emax = params["Emax"]
    EC50 = params["EC50"]
    cp_func = _make_driver(times, concentrations)

    def rhs(t: float, y: NDArray[np.float64]) -> list[float]:
        ce = y[0]
        cp = float(cp_func(t))
        return [ke0 * (cp - ce)]

    t_span = (float(times[0]), float(times[-1]))
    t_eval = times

    sol = solve_ivp(
        rhs,
        t_span,
        [0.0],
        method="RK45",
        t_eval=t_eval,
        rtol=1e-9,
        atol=1e-12,
        dense_output=False,
    )

    ce_arr: NDArray[np.float64] = sol.y[0]
    return E0 + Emax * ce_arr / (EC50 + ce_arr)


def _integrate_idr(
    model_type: PDModelType,
    params: dict[str, float],
    times: NDArray[np.float64],
    concentrations: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Integrate indirect response ODE and return R(t).

    Initial condition: R(0) = kin / kout (baseline steady-state).

    IDR-I:   dR/dt = kin * (1 - Imax*C/(IC50+C)) - kout * R
    IDR-II:  dR/dt = kin - kout * (1 - Imax*C/(IC50+C)) * R
    IDR-III: dR/dt = kin * (1 + Smax*C/(SC50+C)) - kout * R
    IDR-IV:  dR/dt = kin - kout * (1 + Smax*C/(SC50+C)) * R
    """
    kin = params["kin"]
    kout = params["kout"]
    R0 = kin / kout

    cp_func = _make_driver(times, concentrations)

    if model_type == PDModelType.IDR_I_INHIB_PRODUCTION:
        Imax = params["Imax"]
        IC50 = params["IC50"]

        def rhs_i(t: float, y: NDArray[np.float64]) -> list[float]:
            r = y[0]
            c = float(cp_func(t))
            inhib = Imax * c / (IC50 + c)
            return [kin * (1.0 - inhib) - kout * r]

        rhs_fn = rhs_i

    elif model_type == PDModelType.IDR_II_INHIB_LOSS:
        Imax = params["Imax"]
        IC50 = params["IC50"]

        def rhs_ii(t: float, y: NDArray[np.float64]) -> list[float]:
            r = y[0]
            c = float(cp_func(t))
            inhib = Imax * c / (IC50 + c)
            return [kin - kout * (1.0 - inhib) * r]

        rhs_fn = rhs_ii

    elif model_type == PDModelType.IDR_III_STIM_PRODUCTION:
        Smax = params["Smax"]
        SC50 = params["SC50"]

        def rhs_iii(t: float, y: NDArray[np.float64]) -> list[float]:
            r = y[0]
            c = float(cp_func(t))
            stim = Smax * c / (SC50 + c)
            return [kin * (1.0 + stim) - kout * r]

        rhs_fn = rhs_iii

    else:  # IDR_IV_STIM_LOSS
        Smax = params["Smax"]
        SC50 = params["SC50"]

        def rhs_iv(t: float, y: NDArray[np.float64]) -> list[float]:
            r = y[0]
            c = float(cp_func(t))
            stim = Smax * c / (SC50 + c)
            return [kin - kout * (1.0 + stim) * r]

        rhs_fn = rhs_iv

    t_span = (float(times[0]), float(times[-1]))
    sol = solve_ivp(
        rhs_fn,
        t_span,
        [R0],
        method="RK45",
        t_eval=times,
        rtol=1e-9,
        atol=1e-12,
        dense_output=False,
    )
    result: NDArray[np.float64] = sol.y[0]
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def predict_pd(
    model_name: str,
    params: dict[str, float],
    concentrations: NDArray[np.float64],
    times: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Predict effect at observation times given concentration-time data.

    For direct models (linear, log_linear, emax, sigmoid_emax,
    inhibitory_emax) the formula is evaluated algebraically at each
    concentration.

    For ``effect_compartment``: integrates ``dCe/dt = ke0*(Cp - Ce)``, then
    applies the Emax function at each ``Ce(t)``.

    For IDR I-IV: integrates ``dR/dt = kin·f(C) - kout·g(C)·R``, returns
    ``R(t)``. Initial condition ``R(0) = kin/kout``.

    Args:
        model_name: Canonical PD model code (see :data:`~pkplugin.pd.models.PD_REGISTRY`).
        params: Parameter dict mapping names to float values.
        concentrations: Plasma concentrations at *times* (same length as *times*).
        times: Observation times. Required for ODE-based models; used as the
            concentration-time driver grid.

    Returns:
        Predicted effects with the same shape as *concentrations* / *times*.

    Raises:
        ValueError: If *model_name* is not registered.

    Refs: docs/03-algorithms/09-pkpd-models.md §1
    """
    spec = get_pd_model(model_name)
    c = np.asarray(concentrations, dtype=np.float64)
    t = np.asarray(times, dtype=np.float64)

    mtype = spec.model_type

    if mtype == PDModelType.LINEAR:
        return _linear(params, c)

    if mtype == PDModelType.LOG_LINEAR:
        return _log_linear(params, c)

    if mtype == PDModelType.EMAX:
        return _emax(params, c)

    if mtype == PDModelType.SIGMOID_EMAX:
        return _sigmoid_emax(params, c)

    if mtype == PDModelType.INHIBITORY_EMAX:
        return _inhibitory_emax(params, c)

    if mtype == PDModelType.EFFECT_COMPARTMENT:
        return _integrate_effect_compartment(params, t, c)

    if mtype in (
        PDModelType.IDR_I_INHIB_PRODUCTION,
        PDModelType.IDR_II_INHIB_LOSS,
        PDModelType.IDR_III_STIM_PRODUCTION,
        PDModelType.IDR_IV_STIM_LOSS,
    ):
        return _integrate_idr(mtype, params, t, c)

    raise ValueError(f"No prediction implementation for model type {mtype!r}")  # pragma: no cover
