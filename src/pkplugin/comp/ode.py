"""
ODE-based compartmental PK simulator.

Supports repeated dosing (IV bolus, IV infusion, oral), Michaelis-Menten
elimination, and absorption lag.  Integration is performed piecewise between
dosing events using :func:`scipy.integrate.solve_ivp`.

Supported model codes
---------------------
Linear models (from REGISTRY):
  cmt1_iv_bolus / cmt1_iv_infusion / cmt1_po
  cmt2_iv_bolus / cmt2_iv_infusion / cmt2_po
  cmt3_iv_bolus

Michaelis-Menten variants (not in REGISTRY, ODE-only):
  cmt1_iv_mm  — 1-cmt IV + MM elimination
  cmt2_iv_mm  — 2-cmt IV + MM elimination from central
  cmt1_po_mm  — 1-cmt oral + MM elimination

Refs: docs/03-algorithms/08-compartmental-models.md §3
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Sequence, Union

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import solve_ivp  # type: ignore[import-untyped]

# Accept either a plain Python sequence or a numpy array for time inputs
_TimeInput = Union[Sequence[float], NDArray[np.float64]]


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DosingEvent:
    """A single dosing event.

    Attributes:
        time: Dose time (hr).
        amount: Dose amount (mg).
        route: Administration route.
        infusion_duration: Duration (hr) for IV infusion; ignored for other routes.
    """

    time: float
    amount: float
    route: Literal["iv_bolus", "iv_infusion", "oral"]
    infusion_duration: float | None = None


# ---------------------------------------------------------------------------
# RHS builders — return f(t, y) callables
# ---------------------------------------------------------------------------

# Type alias for RHS function
_RHS = Callable[[float, NDArray[np.float64]], NDArray[np.float64]]


def _make_rhs_cmt1_iv(
    params: dict[str, float],
    infusion_windows: list[tuple[float, float, float]],
) -> _RHS:
    """1-cmt IV (bolus + infusion).

    State: [A_c]  (central amount, mg)
    C = A_c / V
    dA_c/dt = R_in(t) - k * A_c
    """
    V = params["V"]
    k = params["k"]

    def rhs(t: float, y: NDArray[np.float64]) -> NDArray[np.float64]:
        a_c = y[0]
        r_in = 0.0
        for t0, t1, rate in infusion_windows:
            if t0 <= t < t1:
                r_in += rate
        return np.array([r_in - k * a_c])

    return rhs


def _make_rhs_cmt1_po(
    params: dict[str, float],
    infusion_windows: list[tuple[float, float, float]],
) -> _RHS:
    """1-cmt oral.

    State: [A_depot, A_c]
    dA_depot/dt = -ka * A_depot
    dA_c/dt    =  ka * A_depot - k * A_c
    """
    V_F = params.get("V_F", params.get("V", 1.0))
    ka = params["ka"]
    k = params["k"]
    _ = V_F  # used only for concentration conversion, not needed in RHS

    def rhs(t: float, y: NDArray[np.float64]) -> NDArray[np.float64]:
        a_dep, a_c = y[0], y[1]
        return np.array([
            -ka * a_dep,
            ka * a_dep - k * a_c,
        ])

    return rhs


def _make_rhs_cmt2_iv(
    params: dict[str, float],
    infusion_windows: list[tuple[float, float, float]],
) -> _RHS:
    """2-cmt IV (bolus + infusion).

    State: [A1, A2]  (central, peripheral amounts)
    dA1/dt = R_in - k10*A1 - k12*A1 + k21*A2
    dA2/dt =                 k12*A1 - k21*A2
    """
    k10 = params["k10"]
    k12 = params["k12"]
    k21 = params["k21"]

    def rhs(t: float, y: NDArray[np.float64]) -> NDArray[np.float64]:
        a1, a2 = y[0], y[1]
        r_in = 0.0
        for t0, t1, rate in infusion_windows:
            if t0 <= t < t1:
                r_in += rate
        da1 = r_in - k10 * a1 - k12 * a1 + k21 * a2
        da2 = k12 * a1 - k21 * a2
        return np.array([da1, da2])

    return rhs


def _make_rhs_cmt2_po(
    params: dict[str, float],
    infusion_windows: list[tuple[float, float, float]],
) -> _RHS:
    """2-cmt oral.

    State: [A_depot, A1, A2]
    """
    ka = params["ka"]
    k10 = params["k10"]
    k12 = params["k12"]
    k21 = params["k21"]

    def rhs(t: float, y: NDArray[np.float64]) -> NDArray[np.float64]:
        a_dep, a1, a2 = y[0], y[1], y[2]
        return np.array([
            -ka * a_dep,
            ka * a_dep - k10 * a1 - k12 * a1 + k21 * a2,
            k12 * a1 - k21 * a2,
        ])

    return rhs


def _make_rhs_cmt3_iv(
    params: dict[str, float],
    infusion_windows: list[tuple[float, float, float]],
) -> _RHS:
    """3-cmt IV bolus.

    State: [A1, A2, A3]
    dA1/dt = R_in - k10*A1 - k12*A1 + k21*A2 - k13*A1 + k31*A3
    dA2/dt =                 k12*A1 - k21*A2
    dA3/dt =                                   k13*A1 - k31*A3
    """
    k10 = params["k10"]
    k12 = params["k12"]
    k21 = params["k21"]
    k13 = params["k13"]
    k31 = params["k31"]

    def rhs(t: float, y: NDArray[np.float64]) -> NDArray[np.float64]:
        a1, a2, a3 = y[0], y[1], y[2]
        r_in = 0.0
        for t0, t1, rate in infusion_windows:
            if t0 <= t < t1:
                r_in += rate
        da1 = r_in - (k10 + k12 + k13) * a1 + k21 * a2 + k31 * a3
        da2 = k12 * a1 - k21 * a2
        da3 = k13 * a1 - k31 * a3
        return np.array([da1, da2, da3])

    return rhs


def _make_rhs_cmt1_iv_mm(
    params: dict[str, float],
    infusion_windows: list[tuple[float, float, float]],
) -> _RHS:
    """1-cmt IV + Michaelis-Menten elimination.

    State: [A_c]
    dA_c/dt = R_in - Vmax*(A_c/V) / (Km + A_c/V)

    Note: Vmax is in mg/hr (amount units), Km in mg/L (conc units).
    """
    V = params["V"]
    vmax = params["Vmax"]
    km = params["Km"]

    def rhs(t: float, y: NDArray[np.float64]) -> NDArray[np.float64]:
        a_c = y[0]
        c = a_c / V
        r_in = 0.0
        for t0, t1, rate in infusion_windows:
            if t0 <= t < t1:
                r_in += rate
        elim = vmax * c / (km + c) * V  # convert back to amount/hr
        return np.array([r_in - elim])

    return rhs


def _make_rhs_cmt2_iv_mm(
    params: dict[str, float],
    infusion_windows: list[tuple[float, float, float]],
) -> _RHS:
    """2-cmt IV + MM elimination from central.

    State: [A1, A2]
    """
    V1 = params["V1"]
    vmax = params["Vmax"]
    km = params["Km"]
    k12 = params["k12"]
    k21 = params["k21"]

    def rhs(t: float, y: NDArray[np.float64]) -> NDArray[np.float64]:
        a1, a2 = y[0], y[1]
        c1 = a1 / V1
        r_in = 0.0
        for t0, t1, rate in infusion_windows:
            if t0 <= t < t1:
                r_in += rate
        elim = vmax * c1 / (km + c1) * V1
        da1 = r_in - elim - k12 * a1 + k21 * a2
        da2 = k12 * a1 - k21 * a2
        return np.array([da1, da2])

    return rhs


def _make_rhs_cmt1_po_mm(
    params: dict[str, float],
    infusion_windows: list[tuple[float, float, float]],
) -> _RHS:
    """1-cmt oral + MM elimination.

    State: [A_depot, A_c]
    """
    V_F = params.get("V_F", params.get("V", 1.0))
    ka = params["ka"]
    vmax = params["Vmax"]
    km = params["Km"]

    def rhs(t: float, y: NDArray[np.float64]) -> NDArray[np.float64]:
        a_dep, a_c = y[0], y[1]
        c = a_c / V_F
        elim = vmax * c / (km + c) * V_F
        return np.array([
            -ka * a_dep,
            ka * a_dep - elim,
        ])

    return rhs


# ---------------------------------------------------------------------------
# Model metadata
# ---------------------------------------------------------------------------

# (n_states, central_idx, depot_idx_or_None, volume_param, rhs_factory)
_MODEL_META: dict[
    str,
    tuple[
        int,   # n_states
        int,   # index of central compartment in state vector
        int | None,  # index of depot (oral) compartment, or None
        str,   # name of volume parameter (V, V1, V_F, V1_F)
        Callable[
            [dict[str, float], list[tuple[float, float, float]]],
            _RHS,
        ],
    ],
] = {
    "cmt1_iv_bolus":     (1, 0, None, "V",    _make_rhs_cmt1_iv),
    "cmt1_iv_infusion":  (1, 0, None, "V",    _make_rhs_cmt1_iv),
    "cmt1_po":           (2, 1, 0,    "V_F",  _make_rhs_cmt1_po),
    "cmt2_iv_bolus":     (2, 0, None, "V1",   _make_rhs_cmt2_iv),
    "cmt2_iv_infusion":  (2, 0, None, "V1",   _make_rhs_cmt2_iv),
    "cmt2_po":           (3, 1, 0,    "V1_F", _make_rhs_cmt2_po),
    "cmt3_iv_bolus":     (3, 0, None, "V1",   _make_rhs_cmt3_iv),
    "cmt1_iv_mm":        (1, 0, None, "V",    _make_rhs_cmt1_iv_mm),
    "cmt2_iv_mm":        (2, 0, None, "V1",   _make_rhs_cmt2_iv_mm),
    "cmt1_po_mm":        (2, 1, 0,    "V_F",  _make_rhs_cmt1_po_mm),
}


# ---------------------------------------------------------------------------
# Core simulator
# ---------------------------------------------------------------------------


def simulate_ode(
    model_name: str,
    params: dict[str, float],
    dosing: Sequence[DosingEvent],
    times: _TimeInput,
    *,
    method: Literal["LSODA", "BDF", "RK45"] = "LSODA",
    rtol: float = 1e-9,
    atol: float = 1e-12,
) -> NDArray[np.float64]:
    """Numerical ODE simulation for compartmental PK models.

    Integrates piecewise between dosing events, injecting bolus amounts at
    event boundaries and applying constant infusion rates during windows.

    Args:
        model_name: One of the supported model codes (see module docstring).
        params: Parameter dictionary.  Keys must include all parameters
            required by the selected model.
        dosing: Sequence of :class:`DosingEvent` objects, need not be sorted.
        times: Observation times at which to return concentrations.
        method: ODE solver method passed to :func:`scipy.integrate.solve_ivp`.
        rtol: Relative tolerance.
        atol: Absolute tolerance.

    Returns:
        Plasma concentration array, shape ``(len(times),)``, in the same
        units as Dose/Volume (mg / L = µg/mL if Dose in mg and V in L).

    Refs: docs/03-algorithms/08-compartmental-models.md §3
    """
    if model_name not in _MODEL_META:
        raise ValueError(
            f"Unknown ODE model: {model_name!r}. "
            f"Supported: {sorted(_MODEL_META)}"
        )

    n_states, central_idx, depot_idx, vol_param, rhs_factory = _MODEL_META[model_name]

    # Volume used for concentration conversion
    vol = params.get(vol_param, params.get("V", 1.0))

    obs_times = np.asarray(times, dtype=np.float64)

    # Sort events by time
    sorted_events = sorted(dosing, key=lambda e: e.time)

    # Build list of infusion windows: (t_start, t_end, rate_mg_per_hr)
    infusion_windows: list[tuple[float, float, float]] = []
    for ev in sorted_events:
        if ev.route == "iv_infusion":
            dur = ev.infusion_duration
            if dur is None or dur <= 0.0:
                raise ValueError(
                    f"iv_infusion event at t={ev.time} requires infusion_duration > 0"
                )
            rate = ev.amount / dur
            infusion_windows.append((ev.time, ev.time + dur, rate))

    # Collect unique event times as segment boundaries
    event_times_set = {0.0}
    for ev in sorted_events:
        event_times_set.add(ev.time)
        if ev.route == "iv_infusion" and ev.infusion_duration is not None:
            event_times_set.add(ev.time + ev.infusion_duration)

    t_max = float(np.max(obs_times)) if len(obs_times) > 0 else 0.0
    breakpoints = sorted(t for t in event_times_set if t <= t_max + 1e-12)
    if t_max > breakpoints[-1] + 1e-12:
        breakpoints.append(t_max)

    # Initial state
    state = np.zeros(n_states, dtype=np.float64)

    # Accumulate concentration at observation times
    conc_out = np.zeros(len(obs_times), dtype=np.float64)

    # Map from observation time → indices (multiple obs can share a time)
    obs_idx: dict[float, list[int]] = {}
    for i, t in enumerate(obs_times):
        obs_idx.setdefault(float(t), []).append(i)

    def _apply_event_at(t_event: float, current_state: NDArray[np.float64]) -> NDArray[np.float64]:
        new_state = current_state.copy()
        for ev in sorted_events:
            if abs(ev.time - t_event) < 1e-12:
                if ev.route == "iv_bolus":
                    new_state[central_idx] += ev.amount
                elif ev.route == "oral":
                    if depot_idx is None:
                        raise ValueError(
                            f"Model {model_name!r} has no depot compartment "
                            "but received an oral dose."
                        )
                    # Apply Tlag by scheduling as a separate bolus to depot
                    new_state[depot_idx] += ev.amount
                # iv_infusion: handled via infusion_windows in RHS, no bolus injection
        return new_state

    def _record_obs(t: float, y: NDArray[np.float64]) -> None:
        if t in obs_idx:
            conc = y[central_idx] / vol
            for i in obs_idx[t]:
                conc_out[i] = conc

    # Handle t=0 dose applications before any integration
    state = _apply_event_at(0.0, state)
    _record_obs(0.0, state)

    # Segment integration
    for seg_idx in range(len(breakpoints) - 1):
        t_start = breakpoints[seg_idx]
        t_end = breakpoints[seg_idx + 1]

        if t_end <= t_start + 1e-14:
            continue

        # Apply any dosing events at the START of this segment (t > 0 events)
        # (t=0 already handled above)
        if seg_idx > 0 or t_start > 0.0:
            state = _apply_event_at(t_start, state)

        # Observation times within this segment
        seg_obs = sorted(
            t for t in obs_idx if t_start < t <= t_end + 1e-14
        )
        # We always evaluate at t_end; add segment obs
        t_eval_set = set(seg_obs)
        t_eval_set.add(t_end)
        t_eval = np.array(sorted(t_eval_set), dtype=np.float64)
        # Clip to segment bounds
        t_eval = t_eval[(t_eval >= t_start - 1e-14) & (t_eval <= t_end + 1e-14)]
        t_eval = np.clip(t_eval, t_start, t_end)

        rhs = rhs_factory(params, infusion_windows)

        sol = solve_ivp(
            fun=rhs,
            t_span=(t_start, t_end),
            y0=state.copy(),
            method=method,
            t_eval=t_eval,
            rtol=rtol,
            atol=atol,
            dense_output=False,
        )

        if not sol.success:
            raise RuntimeError(
                f"ODE solver failed in segment [{t_start}, {t_end}]: {sol.message}"
            )

        # Record observations from this segment
        for j, tj in enumerate(sol.t):
            tj_f = float(tj)
            if tj_f in obs_idx:
                conc = sol.y[central_idx, j] / vol
                for i in obs_idx[tj_f]:
                    conc_out[i] = conc

        # State at end of segment
        state = sol.y[:, -1].copy()

    # Handle obs exactly at t=0 if not already set (post dose)
    for i, t in enumerate(obs_times):
        if abs(t) < 1e-14 and conc_out[i] == 0.0:
            conc_out[i] = state[central_idx] / vol

    return conc_out


# ---------------------------------------------------------------------------
# Tlag wrapper
# ---------------------------------------------------------------------------


def simulate_ode_with_tlag(
    model_name: str,
    params: dict[str, float],
    dosing: Sequence[DosingEvent],
    times: _TimeInput,
    *,
    tlag: float = 0.0,
    method: Literal["LSODA", "BDF", "RK45"] = "LSODA",
    rtol: float = 1e-9,
    atol: float = 1e-12,
) -> NDArray[np.float64]:
    """Simulate with absorption lag time.

    Oral doses are shifted by ``tlag``; observations before the first shifted
    dose time return 0.

    Args:
        tlag: Absorption lag time (hr).  Applied to all oral events.
        All other args: same as :func:`simulate_ode`.
    """
    obs_times = np.asarray(times, dtype=np.float64)
    if tlag <= 0.0:
        return simulate_ode(
            model_name, params, dosing, times,
            method=method, rtol=rtol, atol=atol,
        )

    # Shift oral doses
    shifted: list[DosingEvent] = []
    for ev in dosing:
        if ev.route == "oral":
            shifted.append(
                DosingEvent(
                    time=ev.time + tlag,
                    amount=ev.amount,
                    route=ev.route,
                    infusion_duration=ev.infusion_duration,
                )
            )
        else:
            shifted.append(ev)

    conc = simulate_ode(
        model_name, params, shifted, times,
        method=method, rtol=rtol, atol=atol,
    )

    # Zero out observations before the first shifted oral dose
    min_shifted_oral = min(
        (ev.time for ev in shifted if ev.route == "oral"),
        default=0.0,
    )
    conc[obs_times < min_shifted_oral - 1e-12] = 0.0
    return conc
