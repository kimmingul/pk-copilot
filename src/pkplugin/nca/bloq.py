"""
BLOQ (Below Limit of Quantification) handling for NCA.

Classifies each observation into one of four positional categories and
applies the WinNonlin-compatible replacement rule to produce a clean
array suitable for downstream AUC / λz computation.

Positional categories (per docs/03-algorithms/04-bloq-handling.md §2):
  - pre_dose    : time < dose_time
  - up_leading  : dose_time <= time < first quantifiable
  - embedded    : between the first and last quantifiable points
  - trailing    : after the last quantifiable point

Default policy matrix (WinNonlin 6.4, §7.5):
  pre_dose   → zero
  up_leading → zero
  embedded   → missing  (dropped from arrays but decision recorded)
  trailing   → exclude  (dropped from arrays and decision recorded)

Refs:
  - docs/03-algorithms/04-bloq-handling.md §3, §4
  - docs/04-winnonlin-version-matrix.md
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from pkplugin.version import get_default

BLOQPolicyName = Literal["default", "zero", "missing", "custom"]
PositionRule = Literal["zero", "missing", "exclude"]


@dataclass(frozen=True)
class BLOQRule:
    """Per-position replacement rules for BLOQ observations.

    Attributes:
        pre_dose:    Rule for BLOQ observations before the dose time.
        up_leading:  Rule for post-dose BLOQ observations before the first
                     quantifiable concentration (absorption lag / leading edge).
        embedded:    Rule for BLOQ observations between two quantifiable points.
        trailing:    Rule for BLOQ observations after the last quantifiable point.
    """

    pre_dose: PositionRule = "zero"
    up_leading: PositionRule = "zero"
    embedded: PositionRule = "missing"
    trailing: PositionRule = "exclude"


@dataclass(frozen=True)
class BLOQDecision:
    """Audit record for a single observation's BLOQ disposition.

    One ``BLOQDecision`` is produced for every input row regardless of
    whether it was BLOQ or not — non-BLOQ rows carry ``rule="quantifiable"``
    and ``treated_as=raw_value``.

    Attributes:
        index:       Original row index in the input sequences.
        time:        Observation time.
        raw_value:   Original concentration value; ``None`` when the raw
                     measurement was already absent.
        rule:        Which positional rule was applied
                     (``"pre_dose"``, ``"up_leading"``, ``"embedded"``,
                     ``"trailing"``, or ``"quantifiable"``).
        treated_as:  Effective concentration used in calculations.
                     ``None`` means the row is treated as missing (skipped).
                     A numeric value (e.g. 0.0) means use that value instead.
        excluded:    ``True`` if the row is dropped from the output arrays
                     entirely (either ``exclude`` or ``missing`` rule).
    """

    index: int
    time: float
    raw_value: float | None
    rule: str
    treated_as: float | None
    excluded: bool


def _rule_to_decision(
    rule_name: str,
    position: PositionRule,
    index: int,
    time: float,
    raw_value: float | None,
) -> BLOQDecision:
    """Translate a positional rule into a ``BLOQDecision``."""
    if position == "zero":
        return BLOQDecision(
            index=index,
            time=time,
            raw_value=raw_value,
            rule=rule_name,
            treated_as=0.0,
            excluded=False,
        )
    if position == "missing":
        return BLOQDecision(
            index=index,
            time=time,
            raw_value=raw_value,
            rule=rule_name,
            treated_as=None,
            excluded=True,
        )
    # position == "exclude"
    return BLOQDecision(
        index=index,
        time=time,
        raw_value=raw_value,
        rule=rule_name,
        treated_as=None,
        excluded=True,
    )


def _build_rule_from_defaults(winnonlin_version: str) -> BLOQRule:
    """Construct a ``BLOQRule`` from the version-specific DEFAULTS matrix."""
    policy: dict[str, str] = get_default(winnonlin_version, "bloq_policy")
    return BLOQRule(
        pre_dose=policy["pre_dose"],  # type: ignore[arg-type]
        up_leading=policy["up_leading"],  # type: ignore[arg-type]
        embedded=policy["embedded"],  # type: ignore[arg-type]
        trailing=policy["trailing"],  # type: ignore[arg-type]
    )


def resolve_bloq(
    times: Sequence[float],
    concentrations: Sequence[float | None],
    bloq_flags: Sequence[bool],
    dose_time: float = 0.0,
    rule: BLOQRule | None = None,
    winnonlin_version: str = "6.4",
) -> tuple[np.ndarray, np.ndarray, list[BLOQDecision]]:
    """Apply the WinNonlin-compatible BLOQ policy to a single subject's data.

    The input arrays are assumed to be sorted by time within a subject;
    this function does **not** sort them.

    Parameters
    ----------
    times:
        Observation times (seconds, hours, or any consistent unit).
    concentrations:
        Measured concentrations; ``None`` indicates an already-missing value.
        BLOQ rows may carry ``None`` or a numeric stub — the ``bloq_flags``
        array is the authoritative signal.
    bloq_flags:
        Boolean mask; ``True`` means the corresponding concentration is BLOQ.
    dose_time:
        Time of dose administration.  Pre-dose is defined as
        ``time < dose_time``.  Default 0.0.
    rule:
        Explicit ``BLOQRule`` to apply.  When ``None`` (default), the rule is
        derived from ``pkplugin.version.get_default("bloq_policy", ...)``
        for the given ``winnonlin_version``.
    winnonlin_version:
        WinNonlin compatibility version string (e.g. ``"6.4"``).
        Only consulted when ``rule`` is ``None``.

    Returns
    -------
    clean_times : np.ndarray
        Times array with excluded/missing rows removed.
    clean_concentrations : np.ndarray
        Concentrations array (dtype float64) with BLOQ rows replaced
        according to the policy, and excluded/missing rows removed.
    decisions : list[BLOQDecision]
        One entry per input row, in original order.  Includes both retained
        and excluded observations so callers can produce a complete audit log.

    Raises
    ------
    ValueError
        If the three input sequences have different lengths.

    Refs: docs/03-algorithms/04-bloq-handling.md §3, §4
    """
    t_list = list(times)
    c_list = list(concentrations)
    f_list = list(bloq_flags)

    n = len(t_list)
    if len(c_list) != n or len(f_list) != n:
        raise ValueError(
            f"times, concentrations, and bloq_flags must have the same length; "
            f"got {n}, {len(c_list)}, {len(f_list)}."
        )

    effective_rule: BLOQRule = (
        rule if rule is not None else _build_rule_from_defaults(winnonlin_version)
    )

    # Identify the first and last quantifiable indices.
    # A row is quantifiable when it is not BLOQ and not None.
    quantifiable_indices: list[int] = [
        i for i in range(n) if not f_list[i] and c_list[i] is not None
    ]

    first_q: int | None = quantifiable_indices[0] if quantifiable_indices else None
    last_q: int | None = quantifiable_indices[-1] if quantifiable_indices else None

    decisions: list[BLOQDecision] = []

    for i in range(n):
        t = t_list[i]
        raw = c_list[i]
        is_bloq = f_list[i]

        if not is_bloq:
            # Non-BLOQ row: keep as-is regardless of missing raw value.
            decisions.append(
                BLOQDecision(
                    index=i,
                    time=t,
                    raw_value=raw,
                    rule="quantifiable",
                    treated_as=raw,
                    excluded=(raw is None),
                )
            )
            continue

        # Determine positional category.
        if t < dose_time:
            position_name = "pre_dose"
            position_rule: PositionRule = effective_rule.pre_dose
        elif first_q is None or i < first_q:
            # Post-dose but before first quantifiable (up-leading edge).
            position_name = "up_leading"
            position_rule = effective_rule.up_leading
        elif last_q is not None and i > last_q:
            # After the last quantifiable point (trailing).
            position_name = "trailing"
            position_rule = effective_rule.trailing
        else:
            # Between first and last quantifiable (embedded).
            position_name = "embedded"
            position_rule = effective_rule.embedded

        decisions.append(
            _rule_to_decision(
                rule_name=position_name,
                position=position_rule,
                index=i,
                time=t,
                raw_value=raw,
            )
        )

    # Build clean arrays by dropping excluded rows.
    clean_times_list: list[float] = []
    clean_conc_list: list[float] = []

    for dec in decisions:
        if not dec.excluded and dec.treated_as is not None:
            clean_times_list.append(dec.time)
            clean_conc_list.append(dec.treated_as)

    clean_times = np.array(clean_times_list, dtype=np.float64)
    clean_concentrations = np.array(clean_conc_list, dtype=np.float64)

    return clean_times, clean_concentrations, decisions
