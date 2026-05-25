"""
Descriptive statistics module for pk-copilot v0.2.

Computes per-parameter summary statistics (arithmetic mean, SD, geometric
mean, geometric CV%, median, quartiles, min/max) across a cohort of NCA
results, optionally grouped by treatment / period / analyte.

Refs:
- docs/03-algorithms/01-nca-parameters.md §6, §7
- docs/02-roadmap.md v0.2 entry
"""

from __future__ import annotations

import math
import warnings as _warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Sequence

import numpy as np

if TYPE_CHECKING:
    from pkplugin.nca.engine import NCAResult


# ---------------------------------------------------------------------------
# Output data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DescriptiveSummary:
    """Per-parameter descriptive statistics for a single group.

    Refs: docs/03-algorithms/01-nca-parameters.md §6, §7
    """

    parameter: str             # e.g., "Cmax", "AUClast"
    unit: str
    n: int                     # number of non-missing observations
    n_missing: int             # NaN / None / non-finite values excluded
    mean: float | None         # arithmetic mean
    sd: float | None           # sample SD, ddof=1
    cv_pct: float | None       # 100 · SD / mean (arithmetic CV%)
    geo_mean: float | None     # exp(mean(ln x)); None if any value <= 0
    geo_cv_pct: float | None   # 100 · sqrt(exp(var(ln x, ddof=1)) - 1)
    median: float | None
    min: float | None
    max: float | None
    q1: float | None           # 25th percentile (linear interpolation)
    q3: float | None           # 75th percentile (linear interpolation)


@dataclass(frozen=True)
class GroupedStats:
    """Descriptive statistics for one group (e.g. one treatment × period).

    Refs: docs/03-algorithms/01-nca-parameters.md §7
    """

    group_keys: dict[str, str]            # e.g. {"treatment": "Test", "period": "1"}
    n_subjects: int
    by_parameter: dict[str, DescriptiveSummary]


# ---------------------------------------------------------------------------
# Core computation: single vector
# ---------------------------------------------------------------------------


def summarize_values(
    values: Sequence[float | None],
    parameter: str = "",
    unit: str = "",
) -> DescriptiveSummary:
    """Compute descriptive statistics on a single numeric vector.

    NaN / None / non-finite values are counted in ``n_missing`` and excluded
    from all computations.  Geometric statistics require all-positive
    observations; if any non-positive finite value is present,
    ``geo_mean`` / ``geo_cv_pct`` are ``None``.

    Arithmetic mean and SD use ``ddof=1`` (sample statistics).
    Geometric CV% formula: ``100 * sqrt(exp(var(ln x, ddof=1)) - 1)``.
    Percentiles use numpy ``method="linear"`` interpolation.

    All returned values are plain Python ``float`` or ``None`` (JSON-serialisable;
    no numpy scalar types leak into the dataclass).

    Refs: docs/03-algorithms/01-nca-parameters.md §6, §7

    Args:
        values: Raw observations; ``None`` and non-finite floats are treated as missing.
        parameter: Parameter name (label only, not used in computation).
        unit: Unit string (label only, not used in computation).

    Returns:
        :class:`DescriptiveSummary` populated from the finite subset.
    """
    # Separate finite from missing (L1: convert to float first to handle numpy scalars)
    finite: list[float] = []
    n_missing = 0
    for v in values:
        if v is None:
            n_missing += 1
        else:
            try:
                fv = float(v)
            except (TypeError, ValueError):
                n_missing += 1
                continue
            if not math.isfinite(fv):
                n_missing += 1
            else:
                finite.append(fv)

    n = len(finite)

    if n == 0:
        return DescriptiveSummary(
            parameter=parameter,
            unit=unit,
            n=0,
            n_missing=n_missing,
            mean=None,
            sd=None,
            cv_pct=None,
            geo_mean=None,
            geo_cv_pct=None,
            median=None,
            min=None,
            max=None,
            q1=None,
            q3=None,
        )

    arr = np.array(finite, dtype=np.float64)

    # Arithmetic statistics
    arith_mean: float = float(np.mean(arr))
    arith_sd: float | None = float(np.std(arr, ddof=1)) if n >= 2 else None
    cv_pct: float | None = None
    if arith_sd is not None and arith_mean != 0.0:
        cv_pct = float(100.0 * arith_sd / arith_mean)

    # Geometric statistics — require all values > 0
    geo_mean: float | None = None
    geo_cv_pct: float | None = None
    if np.all(arr > 0):
        ln_arr = np.log(arr)
        geo_mean = float(np.exp(np.mean(ln_arr)))
        if n >= 2:
            ln_var = float(np.var(ln_arr, ddof=1))
            exp_ln_var = math.exp(ln_var)
            if exp_ln_var >= 1.0:
                geo_cv_pct = float(100.0 * math.sqrt(exp_ln_var - 1.0))
            else:
                # Numerical underflow guard — treat as 0% CV
                geo_cv_pct = 0.0
        else:
            # geo_cv_pct undefined for n=1 (ddof=1 requires n≥2)
            geo_cv_pct = None
    else:
        _warnings.warn(
            f"summarize_values: parameter={parameter!r} has non-positive values; "
            "geo_mean and geo_cv_pct set to None.",
            UserWarning,
            stacklevel=2,
        )

    # Order statistics
    median: float = float(np.quantile(arr, 0.5, method="linear"))
    q1: float = float(np.quantile(arr, 0.25, method="linear"))
    q3: float = float(np.quantile(arr, 0.75, method="linear"))
    obs_min: float = float(np.min(arr))
    obs_max: float = float(np.max(arr))

    return DescriptiveSummary(
        parameter=parameter,
        unit=unit,
        n=n,
        n_missing=n_missing,
        mean=arith_mean,
        sd=arith_sd,
        cv_pct=cv_pct,
        geo_mean=geo_mean,
        geo_cv_pct=geo_cv_pct,
        median=median,
        min=obs_min,
        max=obs_max,
        q1=q1,
        q3=q3,
    )


# ---------------------------------------------------------------------------
# Multi-subject summary
# ---------------------------------------------------------------------------

#: Default set of parameters reported in the v0.2 cohort summary table.
DEFAULT_PARAMETERS: tuple[str, ...] = (
    "Cmax",
    "Tmax",
    "Tlast",
    "AUClast",
    "AUCINF_obs",
    "HL_Lambda_z",
    "Lambda_z",
    "CL",
    "CL_F",
    "Vz",
    "Vz_F",
    "Vss",
)

#: Sentinel used when a group-key attribute is None on an NCAResult.
_UNSPECIFIED = "<unspecified>"


def summarize_nca_results(
    results: Sequence["NCAResult"],
    group_by: tuple[str, ...] = ("treatment", "period", "analyte"),
    parameters: tuple[str, ...] = DEFAULT_PARAMETERS,
) -> list[GroupedStats]:
    """Multi-subject descriptive statistics across a cohort of NCA results.

    Groups ``results`` by the Cartesian product of ``group_by`` attribute
    values observed in the data, then computes :func:`summarize_values` for
    each ``(group, parameter)`` combination.

    Empty parameter groups (no subjects have a value for that parameter) are
    still included with ``N=0`` rather than being silently dropped.

    Group-key values that are ``None`` on the source :class:`NCAResult` are
    represented as the literal string ``"<unspecified>"``.

    Refs: docs/03-algorithms/01-nca-parameters.md §7

    Args:
        results: Iterable of :class:`~pkplugin.nca.engine.NCAResult` objects,
            typically the return value of :func:`~pkplugin.nca.engine.calculate_nca`.
        group_by: Tuple of :class:`NCAResult` attribute names to group by.
            Defaults to ``("treatment", "period", "analyte")``.
        parameters: Tuple of parameter names to include in the summary.
            Parameters absent from all results still appear as N=0 entries.

    Returns:
        List of :class:`GroupedStats`, one per unique combination of
        ``group_by`` values encountered in ``results``.
    """
    # L2: Validate group_by attribute names against the first result.
    if results:
        first = next(iter(results))
        for attr in group_by:
            if not hasattr(first, attr):
                raise ValueError(f"Unknown group_by attribute: {attr!r}")

    # Build the set of all unique group-key tuples present in results
    def _key_for(result: "NCAResult") -> tuple[str, ...]:
        parts: list[str] = []
        for attr in group_by:
            val = getattr(result, attr, None)
            parts.append(_UNSPECIFIED if val is None else str(val))
        return tuple(parts)

    # Collect unique keys in insertion order
    seen_keys: dict[tuple[str, ...], None] = {}
    for r in results:
        seen_keys[_key_for(r)] = None

    # Build per-group dict: key -> list of NCAResult
    groups: dict[tuple[str, ...], list[NCAResult]] = {k: [] for k in seen_keys}
    for r in results:
        groups[_key_for(r)].append(r)

    # Unit lookup: scan all results for the first non-None unit per parameter
    # NCAResult.parameter_rows carries unit information
    unit_map: dict[str, str] = {}
    for r in results:
        for row in r.parameter_rows:
            if row.parameter not in unit_map and row.unit:
                unit_map[row.parameter] = row.unit

    output: list[GroupedStats] = []
    for key_tuple, group_results in groups.items():
        group_keys: dict[str, str] = dict(zip(group_by, key_tuple))
        n_subjects = len(group_results)

        by_parameter: dict[str, DescriptiveSummary] = {}
        for param in parameters:
            unit = unit_map.get(param, "")
            if n_subjects == 0:
                by_parameter[param] = DescriptiveSummary(
                    parameter=param,
                    unit=unit,
                    n=0,
                    n_missing=0,
                    mean=None,
                    sd=None,
                    cv_pct=None,
                    geo_mean=None,
                    geo_cv_pct=None,
                    median=None,
                    min=None,
                    max=None,
                    q1=None,
                    q3=None,
                )
            else:
                raw_values: list[float | None] = [
                    r.parameters.get(param) for r in group_results
                ]
                by_parameter[param] = summarize_values(raw_values, parameter=param, unit=unit)

        output.append(
            GroupedStats(
                group_keys=group_keys,
                n_subjects=n_subjects,
                by_parameter=by_parameter,
            )
        )

    return output
