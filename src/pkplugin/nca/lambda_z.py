"""
Terminal elimination rate constant (λz) estimation for NCA.

Implements WinNonlin-compatible Best Fit, Adj R², and Manual selection
algorithms for the terminal log-linear phase.

Refs:
- docs/03-algorithms/03-lambda-z-selection.md
- docs/03-algorithms/01-nca-parameters.md §4
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import NDArray

LambdaZMethod = Literal["best_fit", "adj_r2", "manual", "time_range", "n_points"]

_F64 = NDArray[np.float64]
_ExcludedPoint = dict[str, object]


@dataclass(frozen=True)
class LambdaZResult:
    lambda_z: float | None  # 1/time (positive). None if not estimable.
    intercept: float | None  # log-scale (ln of C(0) of regression)
    half_life: float | None  # ln(2) / lambda_z
    r_squared: float | None
    adjusted_r_squared: float | None
    n_points: int
    t_start: float | None
    t_end: float | None
    span_ratio: float | None
    method: LambdaZMethod
    clast_pred: float | None  # exp(intercept - lambda_z * tlast)
    excluded_points: list[_ExcludedPoint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _ols_log_linear(
    t: _F64,
    ln_c: _F64,
) -> tuple[float, float, float]:
    """
    Fit ln C = intercept - lambda_z * t via OLS.

    Returns (lambda_z, intercept, r_squared).
    lambda_z = -slope (positive if declining).
    """
    coeffs = np.polyfit(t, ln_c, 1)
    slope: float = float(coeffs[0])
    intercept: float = float(coeffs[1])

    # R²
    ln_c_mean = float(np.mean(ln_c))
    ss_tot = float(np.sum((ln_c - ln_c_mean) ** 2))
    ln_c_pred = slope * t + intercept
    ss_res = float(np.sum((ln_c - ln_c_pred) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else 1.0

    return -slope, intercept, r_squared


def _adj_r2(r_squared: float, n: int) -> float:
    """Adjusted R² = 1 - (1 - R²) * (n - 1) / (n - 2)."""
    return 1.0 - (1.0 - r_squared) * (n - 1) / (n - 2)


def _make_failure(
    method: LambdaZMethod,
    warning: str,
    excluded_points: list[_ExcludedPoint],
) -> LambdaZResult:
    return LambdaZResult(
        lambda_z=None,
        intercept=None,
        half_life=None,
        r_squared=None,
        adjusted_r_squared=None,
        n_points=0,
        t_start=None,
        t_end=None,
        span_ratio=None,
        method=method,
        clast_pred=None,
        excluded_points=excluded_points,
        warnings=[warning],
    )


def _build_result(
    *,
    lambda_z: float,
    intercept: float,
    r_squared: float,
    n: int,
    t_arr: _F64,
    method: LambdaZMethod,
    span_ratio_min: float,
    excluded_points: list[_ExcludedPoint],
    actual_tlast: float | None = None,
) -> LambdaZResult:
    half_life = math.log(2.0) / lambda_z
    adj_r2_val = _adj_r2(r_squared, n)
    # B10: use actual_tlast (last quantifiable in the full profile) for clast_pred,
    # not the end of the regression window, which may exclude trailing points.
    tlast = actual_tlast if actual_tlast is not None else float(t_arr[-1])
    clast_pred = math.exp(intercept - lambda_z * tlast)
    t_start = float(t_arr[0])
    t_end = float(t_arr[-1])
    span_ratio: float | None = (t_end - t_start) / half_life if half_life > 0.0 else None
    warnings: list[str] = []
    if span_ratio is not None and span_ratio < span_ratio_min:
        warnings.append("span_ratio_low")
    return LambdaZResult(
        lambda_z=lambda_z,
        intercept=intercept,
        half_life=half_life,
        r_squared=r_squared,
        adjusted_r_squared=adj_r2_val,
        n_points=n,
        t_start=t_start,
        t_end=t_end,
        span_ratio=span_ratio,
        method=method,
        clast_pred=clast_pred,
        excluded_points=excluded_points,
        warnings=warnings,
    )


def _fit_subset(
    t_sub: _F64,
    c_sub: _F64,
) -> tuple[float, float, float] | None:
    """
    Fit a subset; return (lambda_z, intercept, r_squared) or None if slope >= 0.
    """
    ln_c = np.log(c_sub)
    lambda_z, intercept, r_squared = _ols_log_linear(t_sub, ln_c)
    if lambda_z <= 0.0:
        return None
    return lambda_z, intercept, r_squared


ManualSpec = dict[str, "int | float | list[int]"]


def fit_lambda_z(
    times: Sequence[float],
    concentrations: Sequence[float],
    tmax: float,
    *,
    method: LambdaZMethod = "best_fit",
    min_points: int = 3,
    tolerance: float = 1e-4,
    span_ratio_min: float = 1.5,
    manual: ManualSpec | None = None,
    winnonlin_version: str = "6.4",
    actual_tlast: float | None = None,
) -> LambdaZResult:
    """
    Fit the terminal log-linear elimination rate constant.

    Inputs are already BLOQ-resolved (no None values, positive concentrations).
    Excludes points at or before tmax. Requires >= min_points post-tmax points.

    Best Fit algorithm:
      1. Enumerate consecutive subsets ending at the last observation, of size
         min_points to all_post_tmax_points.
      2. Fit OLS ln(C) = a - lambda_z * t for each subset.
      3. Skip subsets with positive slope (lambda_z must be > 0).
      4. Compute adjusted R² = 1 - (1 - R²) * (n - 1) / (n - 2).
      5. Pick the subset whose adj_R² is within `tolerance` of the max adj_R²
         AND has the LARGEST n_points (WinNonlin tie-breaker).

    Adj R² method: pick argmax(adj_R²) without tie-breaker.

    Manual method (one of):
      - {"indices": [i,j,k,...]}
      - {"t_start": float, "t_end": float}
      - {"n_last": int}

    Span guard:
      span_ratio = (t_end - t_start) / half_life.
      If span_ratio < span_ratio_min: append a warning, do not change the result.

    Refs: docs/03-algorithms/03-lambda-z-selection.md
    """
    t_all: _F64 = np.array(times, dtype=np.float64)
    c_all: _F64 = np.array(concentrations, dtype=np.float64)

    # Collect excluded points (at or before tmax, or non-positive/non-finite post-tmax)
    excluded_points: list[_ExcludedPoint] = []

    # Tmax inclusion is version-aware per WinNonlin manual differences:
    #   - WNL 5.3 NCA manual ("Points prior to Cmax"): the Cmax data point itself
    #     MAY participate in the Lambda_z candidate windows.
    #   - WNL 6.4 / 8.3 ("Points prior to Cmax, and the point at Cmax for
    #     non-bolus models"): the Cmax data point is explicitly EXCLUDED.
    # 5.3 → t >= tmax (inclusive)
    # 6.4 / 8.3 / compat-latest → t > tmax (strict, default)
    if str(winnonlin_version) == "5.3":
        post_mask: NDArray[np.bool_] = t_all >= tmax
        _tmax_exclusion_reason = "before_tmax"  # 5.3 keeps the Cmax point
    else:
        post_mask = t_all > tmax
        _tmax_exclusion_reason = "pre_tmax"
    # B8: also exclude non-positive or non-finite concentrations post-tmax
    positive_finite_mask: NDArray[np.bool_] = np.isfinite(c_all) & (c_all > 0)
    for i in range(len(t_all)):
        if not post_mask[i]:
            excluded_points.append(
                {"index": i, "time": float(t_all[i]), "reason": _tmax_exclusion_reason}
            )
        elif not positive_finite_mask[i]:
            excluded_points.append(
                {
                    "index": i,
                    "time": float(t_all[i]),
                    "reason": "non_positive_or_nonfinite_concentration",
                }
            )

    eligible_post_mask: NDArray[np.bool_] = post_mask & positive_finite_mask
    t_post: _F64 = t_all[eligible_post_mask]
    c_post: _F64 = c_all[eligible_post_mask]

    if method == "manual":
        return _fit_manual(
            t_all=t_all,
            c_all=c_all,
            t_post=t_post,
            c_post=c_post,
            manual=manual,
            method=method,
            span_ratio_min=span_ratio_min,
            excluded_points=excluded_points,
            actual_tlast=actual_tlast,
        )

    # For best_fit / adj_r2 / time_range / n_points we need post-tmax points
    n_post = len(t_post)
    if n_post < min_points:
        return _make_failure(method, "insufficient_terminal_points", excluded_points)

    return _fit_auto(
        t_post=t_post,
        c_post=c_post,
        method=method,
        min_points=min_points,
        tolerance=tolerance,
        span_ratio_min=span_ratio_min,
        excluded_points=excluded_points,
        actual_tlast=actual_tlast,
    )


@dataclass
class _Candidate:
    n: int
    lambda_z: float
    intercept: float
    r_squared: float
    adj_r2: float
    t_arr: _F64
    c_arr: _F64


def _fit_auto(
    *,
    t_post: _F64,
    c_post: _F64,
    method: LambdaZMethod,
    min_points: int,
    tolerance: float,
    span_ratio_min: float,
    excluded_points: list[_ExcludedPoint],
    actual_tlast: float | None = None,
) -> LambdaZResult:
    """Best Fit or Adj R² automatic window selection over post-tmax points."""
    n_post = len(t_post)
    candidates: list[_Candidate] = []

    for n in range(min_points, n_post + 1):
        # Subset: last n points (most-recent)
        t_sub: _F64 = t_post[n_post - n :]
        c_sub: _F64 = c_post[n_post - n :]
        fit = _fit_subset(t_sub, c_sub)
        if fit is None:
            continue
        lz, intercept, r2 = fit
        adj = _adj_r2(r2, n)
        candidates.append(
            _Candidate(
                n=n,
                lambda_z=lz,
                intercept=intercept,
                r_squared=r2,
                adj_r2=adj,
                t_arr=t_sub,
                c_arr=c_sub,
            )
        )

    if not candidates:
        return _make_failure(method, "no_positive_lambda_z", excluded_points)

    max_adj = max(c.adj_r2 for c in candidates)

    if method == "best_fit":
        # Among candidates within tolerance of max_adj, pick largest n
        within_tol = [c for c in candidates if max_adj - c.adj_r2 <= tolerance]
        best = max(within_tol, key=lambda c: c.n)
    else:
        # adj_r2 / time_range / n_points: pick argmax(adj_R²)
        best = max(candidates, key=lambda c: c.adj_r2)

    return _build_result(
        lambda_z=best.lambda_z,
        intercept=best.intercept,
        r_squared=best.r_squared,
        n=best.n,
        t_arr=best.t_arr,
        method=method,
        span_ratio_min=span_ratio_min,
        excluded_points=excluded_points,
        actual_tlast=actual_tlast,
    )


def _fit_manual(
    *,
    t_all: _F64,
    c_all: _F64,
    t_post: _F64,
    c_post: _F64,
    manual: ManualSpec | None,
    method: LambdaZMethod,
    span_ratio_min: float,
    excluded_points: list[_ExcludedPoint],
    actual_tlast: float | None = None,
) -> LambdaZResult:
    """Resolve manual selection and fit."""
    if manual is None:
        return _make_failure(method, "manual_spec_missing", excluded_points)

    t_sub: _F64
    c_sub: _F64

    if "indices" in manual:
        raw_indices = manual["indices"]
        if not isinstance(raw_indices, list):
            return _make_failure(method, "manual_spec_invalid", excluded_points)
        indices: list[int] = [int(i) for i in raw_indices]
        for idx in indices:
            if idx < 0 or idx >= len(t_all):
                return _make_failure(method, "manual_index_out_of_range", excluded_points)
        t_sub = t_all[indices]
        c_sub = c_all[indices]

    elif "t_start" in manual and "t_end" in manual:
        t_start_scalar = manual["t_start"]
        t_end_scalar = manual["t_end"]
        if isinstance(t_start_scalar, list) or isinstance(t_end_scalar, list):
            return _make_failure(method, "manual_spec_invalid", excluded_points)
        t_start_val = float(t_start_scalar)
        t_end_val = float(t_end_scalar)
        mask: NDArray[np.bool_] = (t_all >= t_start_val) & (t_all <= t_end_val)
        t_sub = t_all[mask]
        c_sub = c_all[mask]

    elif "n_last" in manual:
        n_last_val = manual["n_last"]
        if isinstance(n_last_val, list):
            return _make_failure(method, "manual_spec_invalid", excluded_points)
        n_last = int(n_last_val)
        t_sub = t_post[-n_last:]
        c_sub = c_post[-n_last:]

    else:
        return _make_failure(method, "manual_spec_invalid", excluded_points)

    n = len(t_sub)
    if n < 2:
        return _make_failure(method, "insufficient_terminal_points", excluded_points)

    fit = _fit_subset(t_sub, c_sub)
    if fit is None:
        return _make_failure(method, "no_positive_lambda_z", excluded_points)

    lz, intercept, r2 = fit

    # adj_r² requires n >= 3 (n-2 denominator); use NaN sentinel for n==2
    adj_r2_val: float = _adj_r2(r2, n) if n >= 3 else float("nan")

    half_life = math.log(2.0) / lz
    # B10: use actual_tlast (last quantifiable in the full profile) for clast_pred,
    # not the end of the regression subset, which may exclude trailing points.
    tlast = actual_tlast if actual_tlast is not None else float(t_sub[-1])
    clast_pred = math.exp(intercept - lz * tlast)
    t_start_out = float(t_sub[0])
    t_end_out = float(t_sub[-1])
    span_ratio: float | None = (t_end_out - t_start_out) / half_life if half_life > 0.0 else None
    warnings: list[str] = []
    if span_ratio is not None and span_ratio < span_ratio_min:
        warnings.append("span_ratio_low")

    return LambdaZResult(
        lambda_z=lz,
        intercept=intercept,
        half_life=half_life,
        r_squared=r2,
        adjusted_r_squared=adj_r2_val,
        n_points=n,
        t_start=t_start_out,
        t_end=t_end_out,
        span_ratio=span_ratio,
        method=method,
        clast_pred=clast_pred,
        excluded_points=excluded_points,
        warnings=warnings,
    )


def estimate_c0_log_back_extrap(
    times: Sequence[float],
    concentrations: Sequence[float],
) -> float:
    """
    IV bolus C0 by log back-extrapolation from the first two quantifiable points.

    Fits ln C = a - b * t through the first two points and evaluates at t=0:
      C0 = exp(a)

    Refs: docs/03-algorithms/01-nca-parameters.md §1.7
    """
    t_arr: _F64 = np.array(list(times)[:2], dtype=np.float64)
    c_arr: _F64 = np.array(list(concentrations)[:2], dtype=np.float64)
    ln_c: _F64 = np.log(c_arr)
    slope = float((ln_c[1] - ln_c[0]) / (t_arr[1] - t_arr[0]))
    intercept = float(ln_c[0]) - slope * float(t_arr[0])
    return math.exp(intercept)
