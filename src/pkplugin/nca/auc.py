"""
AUC / AUMC trapezoidal integration for NCA.

Implements three integration methods:
  - ``linear``              : linear trapezoid for every interval
  - ``log``                 : log-linear trapezoid for positive-decreasing
                              intervals; falls back to linear otherwise
  - ``linear_up_log_down``  : linear on ascending/flat/zero intervals,
                              log-linear on strictly positive-decreasing
                              intervals (WinNonlin 6.4+ default)

Also provides:
  - ``auc_inf``     : tail extrapolation to infinity (AUC_0-inf, AUMC_0-inf)
  - ``partial_auc`` : AUC over an arbitrary sub-interval [t1, t2] with
                      boundary interpolation and optional tail extrapolation

Refs:
  - docs/03-algorithms/02-auc-methods.md
  - docs/03-algorithms/05-partial-auc.md
  - WinNonlin 6.4 User's Guide §7.2.3
  - WinNonlin 5.3 §6.1.4
  - WinNonlin 8.3 §8.3.1
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Sequence

import numpy as np

AUCMethod = Literal["linear", "log", "linear_up_log_down"]


@dataclass(frozen=True)
class AUCResult:
    """Result of a trapezoidal AUC/AUMC calculation.

    Attributes:
        auc:
            Area Under the Curve (concentration × time).
        aumc:
            Area Under the first Moment Curve (time × concentration × time).
        method:
            Integration method used.
        n_intervals:
            Number of trapezoidal intervals evaluated (= len(times) - 1).
        log_to_linear_fallbacks:
            Zero-based interval indices where the log trapezoid rule was
            requested but fell back to linear because ``c1 == c2`` or either
            side was non-positive.  Empty when ``method="linear"``.
    """

    auc: float
    aumc: float
    method: AUCMethod
    n_intervals: int
    log_to_linear_fallbacks: list[int] = field(default_factory=list)


def _linear_interval(
    t1: float, t2: float, c1: float, c2: float
) -> tuple[float, float]:
    """Linear trapezoid AUC and exact AUMC under linear C interpolation.

    AUC uses the standard trapezoid rule.

    AUMC is computed as the exact integral of ``t · C(t)`` where ``C(t)`` is
    linearly interpolated between ``(t1, c1)`` and ``(t2, c2)``:
        ∫_{t1}^{t2} t · C(t) dt
            = dt/6 · (2·t1·c1 + t1·c2 + t2·c1 + 2·t2·c2)
    This is **not** the same as the trapezoid rule applied to ``t·C(t)``
    (which would underestimate for monotone curves).

    Refs: docs/03-algorithms/02-auc-methods.md §1
    """
    dt = t2 - t1
    d_auc = 0.5 * (c1 + c2) * dt
    d_aumc = (dt / 6.0) * (
        2.0 * t1 * c1 + t1 * c2 + t2 * c1 + 2.0 * t2 * c2
    )
    return d_auc, d_aumc


def _log_interval(
    t1: float, t2: float, c1: float, c2: float
) -> tuple[float, float]:
    """Log-linear trapezoid AUC and AUMC for a single interval.

    Caller must ensure ``c1 > 0``, ``c2 > 0``, and ``c1 != c2``.

    Refs: docs/03-algorithms/02-auc-methods.md §2
    """
    dt = t2 - t1
    ln_ratio = math.log(c1 / c2)  # > 0 because c1 > c2 > 0
    d_auc = (c1 - c2) * dt / ln_ratio
    # AUMC for log-linear C interpolation. Sign on the second term is +,
    # not - (derived from ∫ t · C1·exp(-λ(t-t1)) dt and confirmed against
    # closed-form 1-cmt IV bolus AUMC_inf = D/(V·k²)).
    d_aumc = (
        dt * (t1 * c1 - t2 * c2) / ln_ratio
        + dt * dt * (c1 - c2) / (ln_ratio * ln_ratio)
    )
    return d_auc, d_aumc


def auc_trapezoid(
    times: Sequence[float],
    concentrations: Sequence[float],
    method: AUCMethod = "linear_up_log_down",
) -> AUCResult:
    """Compute AUC and AUMC by the trapezoidal rule.

    Parameters
    ----------
    times:
        Strictly increasing observation times.  Must have at least 2 elements.
    concentrations:
        Corresponding concentrations.  All values must be finite floats;
        BLOQ rows must be pre-processed (see ``pkplugin.nca.bloq``).
    method:
        Integration method.  One of ``"linear"``, ``"log"``, or
        ``"linear_up_log_down"`` (default, WinNonlin 6.4+ standard).

    Returns
    -------
    AUCResult
        Holds ``auc``, ``aumc``, ``method``, ``n_intervals``, and
        ``log_to_linear_fallbacks``.

    Raises
    ------
    ValueError
        If ``times`` is not strictly increasing, the lengths differ, or
        fewer than 2 points are provided.

    Refs: docs/03-algorithms/02-auc-methods.md §1–§4
    """
    t_arr = np.asarray(times, dtype=np.float64)
    c_arr = np.asarray(concentrations, dtype=np.float64)

    n = len(t_arr)
    if len(c_arr) != n:
        raise ValueError(
            f"times and concentrations must have the same length; "
            f"got {n} and {len(c_arr)}."
        )
    if n < 2:
        raise ValueError(
            f"At least 2 data points are required; got {n}."
        )
    if not np.all(np.diff(t_arr) > 0):
        raise ValueError("times must be strictly increasing.")

    total_auc = 0.0
    total_aumc = 0.0
    fallbacks: list[int] = []

    for i in range(n - 1):
        t1, t2 = float(t_arr[i]), float(t_arr[i + 1])
        c1, c2 = float(c_arr[i]), float(c_arr[i + 1])

        use_log: bool
        if method == "linear":
            use_log = False
        elif method == "log":
            # Log method: use log when c1 > c2 > 0 and c1 != c2.
            # Falls back to linear for equal, ascending, or non-positive values.
            use_log = c1 > 0 and c2 > 0 and c2 < c1
            if not use_log and method == "log":
                # Record fallback only when log was requested but cannot apply.
                fallbacks.append(i)
        else:
            # linear_up_log_down: log only on strictly positive-decreasing intervals.
            use_log = c1 > 0 and c2 > 0 and c2 < c1

        if use_log:
            if c1 == c2:
                # Identical values — log(1) == 0 would cause division by zero;
                # fall back to linear and record.
                d_auc, d_aumc = _linear_interval(t1, t2, c1, c2)
                fallbacks.append(i)
            else:
                d_auc, d_aumc = _log_interval(t1, t2, c1, c2)
        else:
            d_auc, d_aumc = _linear_interval(t1, t2, c1, c2)

        total_auc += d_auc
        total_aumc += d_aumc

    return AUCResult(
        auc=total_auc,
        aumc=total_aumc,
        method=method,
        n_intervals=n - 1,
        log_to_linear_fallbacks=fallbacks,
    )


def auc_inf(
    auc_last: float,
    aumc_last: float,
    clast: float,
    tlast: float,
    lambda_z: float,
    *,
    variant: Literal["obs", "pred"],
    clast_pred: float | None = None,
) -> tuple[float, float]:
    """Extrapolate AUC and AUMC to infinity using the terminal slope λz.

    Parameters
    ----------
    auc_last:
        AUC from time zero to Tlast (``AUC_0-Tlast``).
    aumc_last:
        AUMC from time zero to Tlast (``AUMC_0-Tlast``).
    clast:
        Last observed quantifiable concentration (``Clast``).
    tlast:
        Time of last quantifiable concentration (``Tlast``).
    lambda_z:
        Terminal elimination rate constant (λz > 0).
    variant:
        ``"obs"``  — use ``clast`` for the tail.
        ``"pred"`` — use ``clast_pred`` for the tail (requires
                     ``clast_pred`` to be provided).
    clast_pred:
        Predicted last concentration from the terminal regression
        ``exp(intercept - λz * Tlast)``.  Required when
        ``variant="pred"``, ignored otherwise.

    Returns
    -------
    (auc_inf_value, aumc_inf_value) : tuple[float, float]

    Raises
    ------
    ValueError
        If ``variant="pred"`` and ``clast_pred`` is ``None``.

    Refs: docs/03-algorithms/02-auc-methods.md §5, §6
    """
    if variant == "pred":
        if clast_pred is None:
            raise ValueError(
                "clast_pred must be provided when variant='pred'."
            )
        c_tail = clast_pred
    else:
        c_tail = clast

    # AUC_0-inf = AUC_0-Tlast + Clast / λz
    auc_inf_value = auc_last + c_tail / lambda_z

    # AUMC_0-inf = AUMC_0-Tlast + Tlast * Clast / λz + Clast / λz²
    aumc_inf_value = aumc_last + tlast * c_tail / lambda_z + c_tail / (lambda_z ** 2)

    return auc_inf_value, aumc_inf_value


def _interpolate_concentration(
    t_query: float,
    t_lo: float,
    t_hi: float,
    c_lo: float,
    c_hi: float,
    method: AUCMethod,
) -> float:
    """Interpolate concentration at ``t_query`` between two bracketing points.

    Uses log-linear interpolation when the interval is strictly decreasing and
    both concentrations are positive AND ``method`` is ``"log"`` or
    ``"linear_up_log_down"``; otherwise falls back to linear interpolation.

    Parameters
    ----------
    t_query:
        Time at which to interpolate.  Must satisfy ``t_lo <= t_query <= t_hi``.
    t_lo, t_hi:
        Bracketing times (``t_lo < t_hi``).
    c_lo, c_hi:
        Concentrations at the bracketing times.
    method:
        AUC integration method that governs the interpolation rule.

    Returns
    -------
    float
        Interpolated concentration.
    """
    frac = (t_query - t_lo) / (t_hi - t_lo)

    use_log = (
        method in ("log", "linear_up_log_down")
        and c_lo > 0
        and c_hi > 0
        and c_hi < c_lo
    )

    if use_log:
        ln_c = math.log(c_lo) + (math.log(c_hi) - math.log(c_lo)) * frac
        return math.exp(ln_c)
    return c_lo + (c_hi - c_lo) * frac


def partial_auc(
    times: Sequence[float],
    concentrations: Sequence[float],
    t1: float,
    t2: float,
    method: AUCMethod = "linear_up_log_down",
    lambda_z: float | None = None,
    clast: float | None = None,
    tlast: float | None = None,
) -> float:
    """Compute AUC over the sub-interval [t1, t2].

    Boundary points ``t1`` and ``t2`` are inserted into the observation grid
    via interpolation (linear or log-linear per ``method``) when they do not
    coincide with an existing observation time.

    If ``t2`` exceeds the last observation time (``tlast``) and ``lambda_z``
    is provided, the tail beyond ``tlast`` is extrapolated using:

        AUC_tail = Clast / λz · [1 − exp(−λz · (t2 − tlast))]

    Parameters
    ----------
    times:
        Strictly increasing observation times.
    concentrations:
        Corresponding concentrations.
    t1:
        Start of the partial AUC interval.
    t2:
        End of the partial AUC interval.  Must satisfy ``t1 < t2``.
    method:
        Integration method for both the trapezoidal sum and boundary
        interpolation.
    lambda_z:
        Terminal elimination rate constant.  Required for tail extrapolation
        when ``t2 > tlast``.
    clast:
        Last quantifiable concentration.  Required for tail extrapolation
        when ``t2 > tlast``.
    tlast:
        Time of last quantifiable concentration.  If ``None``, taken as the
        last element of ``times``.

    Returns
    -------
    float
        Partial AUC value.

    Raises
    ------
    ValueError
        If ``t1 >= t2``, or if ``times`` is not strictly increasing or has
        fewer than 2 elements.

    Refs: docs/03-algorithms/05-partial-auc.md §2–§4
    """
    if t1 >= t2:
        raise ValueError(f"t1 must be strictly less than t2; got t1={t1}, t2={t2}.")

    t_arr = np.asarray(times, dtype=np.float64)
    c_arr = np.asarray(concentrations, dtype=np.float64)

    n = len(t_arr)
    if len(c_arr) != n:
        raise ValueError(
            f"times and concentrations must have the same length; "
            f"got {n} and {len(c_arr)}."
        )
    if n < 2:
        raise ValueError(f"At least 2 data points are required; got {n}.")
    if not np.all(np.diff(t_arr) > 0):
        raise ValueError("times must be strictly increasing.")

    t_obs_last = float(t_arr[-1])
    effective_tlast = tlast if tlast is not None else t_obs_last

    # B13: If the entire window [t1, t2] lies beyond Tlast and lambda_z is
    # provided, return the analytical tail integral directly.
    if t1 >= effective_tlast and lambda_z is not None and clast is not None:
        return clast / lambda_z * (
            math.exp(-lambda_z * (t1 - effective_tlast))
            - math.exp(-lambda_z * (t2 - effective_tlast))
        )

    # Step 1: Build the augmented grid containing all original points plus
    # t1 and t2 (within the observed range), with deduplication so that
    # boundary points coinciding exactly with observation times are not doubled.
    _EPS = 1e-12  # tolerance for "on existing grid"
    t_inner_end = min(t2, t_obs_last)

    def _on_grid(t_query: float) -> bool:
        return bool(np.any(np.abs(t_arr - t_query) < _EPS))

    def _interp(t_query: float) -> float:
        idx = int(np.searchsorted(t_arr, t_query, side="right")) - 1
        idx = max(0, min(idx, n - 2))
        return _interpolate_concentration(
            t_query,
            float(t_arr[idx]),
            float(t_arr[idx + 1]),
            float(c_arr[idx]),
            float(c_arr[idx + 1]),
            method,
        )

    # Build the merged time set: union of observation grid + {t1, t2},
    # clipped to [t1, t_inner_end], then deduplicate and sort.
    candidate_times: list[float] = []
    for t_i in t_arr:
        t_f = float(t_i)
        if t1 - _EPS <= t_f <= t_inner_end + _EPS:
            candidate_times.append(t_f)

    # Add boundary points only if they are not already on the grid.
    if not _on_grid(t1) and t1 <= t_obs_last:
        candidate_times.append(t1)
    if not _on_grid(t_inner_end) and t_inner_end <= t_obs_last:
        candidate_times.append(t_inner_end)

    # Sort and deduplicate (merge points within _EPS of each other).
    candidate_times.sort()
    deduped_times: list[float] = []
    for t_f in candidate_times:
        if not deduped_times or abs(t_f - deduped_times[-1]) > _EPS:
            deduped_times.append(t_f)

    # Build concentration array: use original value if on grid, else interpolate.
    sub_t_list: list[float] = []
    sub_c_list: list[float] = []
    for t_f in deduped_times:
        if _on_grid(t_f):
            grid_idx = int(np.argmin(np.abs(t_arr - t_f)))
            sub_t_list.append(t_f)
            sub_c_list.append(float(c_arr[grid_idx]))
        else:
            sub_t_list.append(t_f)
            sub_c_list.append(_interp(t_f))

    sub_t = np.array(sub_t_list, dtype=np.float64)
    sub_c = np.array(sub_c_list, dtype=np.float64)

    # Need at least 2 points to integrate.
    result_auc = 0.0
    if len(sub_t) >= 2:
        result = auc_trapezoid(sub_t.tolist(), sub_c.tolist(), method=method)
        result_auc = result.auc

    # Step 3: Tail extrapolation when t2 > effective_tlast and lambda_z given.
    if t2 > effective_tlast and lambda_z is not None and clast is not None:
        tail_start = max(effective_tlast, t1)
        tail_end = t2
        if tail_end > tail_start:
            result_auc += clast / lambda_z * (
                1.0 - math.exp(-lambda_z * (tail_end - tail_start))
            )

    return result_auc
