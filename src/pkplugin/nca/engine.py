"""
NCA engine — integration layer for pk-copilot.

Orchestrates BLOQ resolution → AUC/AUMC integration → λz regression →
derived parameter computation → long-format NCAParameterRow table.

All arithmetic is WinNonlin-compatible (tested against v5.3, v6.4, v8.3 defaults).

Refs:
- docs/03-algorithms/01-nca-parameters.md
- docs/03-algorithms/02-auc-methods.md
- docs/03-algorithms/03-lambda-z-selection.md
- docs/03-algorithms/04-bloq-handling.md
- docs/04-winnonlin-version-matrix.md
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import groupby
from operator import attrgetter

import numpy as np
from numpy.typing import NDArray

from pkplugin.nca.auc import AUCResult, auc_inf, auc_trapezoid, partial_auc
from pkplugin.nca.bloq import BLOQDecision, BLOQRule, resolve_bloq
from pkplugin.nca.lambda_z import (
    LambdaZResult,
    estimate_c0_log_back_extrap,
    fit_lambda_z,
)
from pkplugin.schemas import (
    ConcentrationRecord,
    DoseRecord,
    NCAConfig,
    NCAParameterRow,
)

# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NCAResult:
    """Full NCA output for one subject / period / treatment / analyte."""

    subject_id: str
    period: str | None
    treatment: str | None
    analyte: str
    parameters: dict[str, float | None]  # canonical parameter name -> value
    parameter_rows: list[NCAParameterRow]  # long-format table
    auc_result: AUCResult
    lambda_z_result: LambdaZResult
    bloq_decisions: list[BLOQDecision]
    warnings: list[str] = field(default_factory=list)
    flags: dict[str, list[str]] = field(default_factory=dict)  # per-parameter flags


# ---------------------------------------------------------------------------
# Unit map (cosmetic for v0.1)
# ---------------------------------------------------------------------------

_UNITS: dict[str, str] = {
    "Cmax": "ng/mL",
    "C0": "ng/mL",
    "Clast": "ng/mL",
    "Clast_pred": "ng/mL",
    "Tmax": "h",
    "Tlast": "h",
    "HL_Lambda_z": "h",
    "Lambda_z_lower": "h",
    "Lambda_z_upper": "h",
    "Span": "h",
    "Lambda_z": "1/h",
    "Rsq": "",
    "Rsq_adjusted": "",
    "No_points_lambda_z": "",
    "Span_ratio": "",
    "AUClast": "ng·h/mL",
    "AUMClast": "ng·h²/mL",
    "AUCINF_obs": "ng·h/mL",
    "AUCINF_pred": "ng·h/mL",
    "AUMCINF_obs": "ng·h²/mL",
    "AUMCINF_pred": "ng·h²/mL",
    "AUC_%Extrap_obs": "",
    "AUC_%Extrap_pred": "",
    "MRTINF_obs": "h",
    "MRTINF_pred": "h",
    "CL": "L/h",
    "CL_F": "L/h",
    "Vz": "L",
    "Vz_F": "L",
    "Vss": "L",
}


def _unit(name: str) -> str:
    if name.startswith("AUC_") and name not in _UNITS:
        # partial AUC windows like AUC_0_24
        return "ng·h/mL"
    return _UNITS.get(name, "")


# ---------------------------------------------------------------------------
# Helper: build NCAParameterRow
# ---------------------------------------------------------------------------


def _row(
    subject_id: str,
    period: str | None,
    treatment: str | None,
    analyte: str,
    parameter: str,
    value: float | None,
    method: str,
    winnonlin_version: str,
    flags: list[str] | None = None,
    comment: str | None = None,
) -> NCAParameterRow:
    return NCAParameterRow(
        subject_id=subject_id,
        period=period,
        treatment=treatment,
        analyte=analyte,
        parameter=parameter,
        value=value,
        unit=_unit(parameter),
        method=method,
        winnonlin_version=winnonlin_version,
        flags=flags or [],
        comment=comment,
    )


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def calculate_nca_subject(
    concentrations: Sequence[ConcentrationRecord],
    dose: DoseRecord | None,
    config: NCAConfig | None = None,
) -> NCAResult:
    """Compute the full WinNonlin-compatible NCA parameter set for one subject /
    period / treatment / analyte.

    Behavior:
      1.  Sort concentration records by time.
      2.  Resolve BLOQ via pkplugin.nca.bloq.resolve_bloq.
      3.  Determine Cmax, Tmax (first time of max), Tlast, Clast.
      4.  Compute C0 for IV bolus routes.
      5.  AUC and AUMC over [0, Tlast] using config.auc_method or version default.
      6.  Lambda_z via fit_lambda_z (Best Fit default).
      7.  Compute t1/2, Clast_pred.
      8.  AUCINF_obs (and AUCINF_pred when output_pred_variants is True).
      9.  AUMC_inf, MRT.
     10.  CL / Vz / Vss.
     11.  AUC_%Extrap.
     12.  Partial AUCs from config.partial_auc_windows.
     13.  Build NCAParameterRow list.
     14.  Return NCAResult.

    Refs:
      docs/03-algorithms/01-nca-parameters.md
      docs/03-algorithms/02-auc-methods.md
    """
    _cfg = config if config is not None else NCAConfig()
    resolved = _cfg.resolved()

    wn_version: str = resolved["winnonlin_version"]
    auc_method: str = resolved["auc_method"]
    lz_method: str = resolved.get("lambda_z_method", "best_fit")
    lz_min_points: int = int(resolved.get("lambda_z_min_points", 3))
    lz_tolerance: float = float(resolved.get("lambda_z_tolerance", 1e-4))
    span_ratio_min: float = float(resolved.get("span_ratio_min", 1.5))
    c0_method: str = resolved.get("c0_method", "log_back_extrap")
    output_pred: bool = bool(resolved.get("output_pred_variants", True))

    warnings: list[str] = []
    flags_map: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # 1. Sort records by time
    # ------------------------------------------------------------------
    recs = sorted(concentrations, key=attrgetter("time"))
    if not recs:
        raise ValueError("No concentration records provided.")

    subject_id = recs[0].subject_id
    period = recs[0].period
    treatment = recs[0].treatment
    analyte = recs[0].analyte

    # ------------------------------------------------------------------
    # 2. Resolve BLOQ
    # ------------------------------------------------------------------
    dose_time = dose.time if dose is not None else 0.0
    bloq_policy = resolved.get("bloq_policy", {})
    rule: BLOQRule | None = None
    if bloq_policy == "zero":
        rule = BLOQRule(
            pre_dose="zero",
            up_leading="zero",
            embedded="zero",
            trailing="zero",
        )
    elif bloq_policy == "missing":
        rule = BLOQRule(
            pre_dose="missing",
            up_leading="missing",
            embedded="missing",
            trailing="missing",
        )
    elif bloq_policy == "custom":
        custom = _cfg.bloq_custom or {}
        rule = BLOQRule(
            pre_dose=custom.get("pre_dose", "zero"),
            up_leading=custom.get("up_leading", "zero"),
            embedded=custom.get("embedded", "missing"),
            trailing=custom.get("trailing", "exclude"),
        )
    elif isinstance(bloq_policy, dict):
        rule = BLOQRule(
            pre_dose=bloq_policy.get("pre_dose", "zero"),
            up_leading=bloq_policy.get("up_leading", "zero"),
            embedded=bloq_policy.get("embedded", "missing"),
            trailing=bloq_policy.get("trailing", "exclude"),
        )
    # else "default" or unrecognised string: rule stays None → version default

    raw_times = [r.time for r in recs]
    raw_concs: list[float | None] = [r.concentration for r in recs]
    raw_bloq = [r.bloq for r in recs]

    clean_t, clean_c, bloq_decisions = resolve_bloq(
        times=raw_times,
        concentrations=raw_concs,
        bloq_flags=raw_bloq,
        dose_time=dose_time,
        rule=rule,
        winnonlin_version=wn_version,
    )

    # ------------------------------------------------------------------
    # 3. Basic observed parameters
    # ------------------------------------------------------------------
    t_arr: NDArray[np.float64] = clean_t
    c_arr: NDArray[np.float64] = clean_c

    if len(t_arr) == 0:
        raise ValueError("No quantifiable concentration records after BLOQ resolution.")

    cmax_idx = int(np.argmax(c_arr))
    cmax = float(c_arr[cmax_idx])
    tmax = float(t_arr[cmax_idx])
    tlast = float(t_arr[-1])
    clast = float(c_arr[-1])

    # ------------------------------------------------------------------
    # 4. C0 (IV bolus only)
    # ------------------------------------------------------------------
    route = dose.route if dose is not None else "oral"
    c0: float | None = None
    auc_times = list(t_arr)
    auc_concs = list(c_arr)

    if route == "iv_bolus":
        if c0_method == "log_back_extrap" and len(auc_times) >= 2:
            # Only use the first two positive quantifiable points
            pos_mask = [i for i, c in enumerate(auc_concs) if c > 0]
            if len(pos_mask) >= 2:
                t_first2 = [auc_times[pos_mask[0]], auc_times[pos_mask[1]]]
                c_first2 = [auc_concs[pos_mask[0]], auc_concs[pos_mask[1]]]
                # B11: Only back-extrapolate when concentrations are declining.
                # If c(t1) <= c(t2), back-extrap produces nonsense; fall back to observed.
                if c_first2[0] > c_first2[1]:
                    c0 = estimate_c0_log_back_extrap(t_first2, c_first2)
                else:
                    c0 = c_first2[0]
                    warnings.append("c0_back_extrap_skipped_non_decreasing")
            elif len(pos_mask) == 1:
                c0 = auc_concs[pos_mask[0]]
        else:
            # "observed": first quantifiable concentration
            pos_mask2 = [i for i, c in enumerate(auc_concs) if c > 0]
            if pos_mask2:
                c0 = auc_concs[pos_mask2[0]]

        # Prepend (t=0, C=C0) if not already at t=0
        if c0 is not None and (len(auc_times) == 0 or auc_times[0] > 0.0):
            auc_times = [0.0] + auc_times
            auc_concs = [c0] + auc_concs

        # B7: When IV bolus and the first AUC point is t=0 with a near-zero
        # concentration (BLOQ replaced to 0), substitute C0 so AUCINF/Vss
        # are computed from the back-extrapolated value, not the BLOQ zero.
        if c0 is not None and len(auc_times) >= 1 and auc_times[0] == 0.0 and auc_concs[0] < 1e-12:
            auc_concs[0] = c0

    # ------------------------------------------------------------------
    # 5. AUC and AUMC over [0, Tlast]
    # ------------------------------------------------------------------
    auc_result_obj: AUCResult
    if len(auc_times) >= 2:
        auc_result_obj = auc_trapezoid(
            auc_times,
            auc_concs,
            method=auc_method,  # type: ignore[arg-type]
        )
    else:
        # Degenerate: single point — AUC = 0
        auc_result_obj = AUCResult(
            auc=0.0,
            aumc=0.0,
            method=auc_method,  # type: ignore[arg-type]
            n_intervals=0,
        )

    auc_last = auc_result_obj.auc
    aumc_last = auc_result_obj.aumc

    # ------------------------------------------------------------------
    # 6. Lambda_z estimation
    # ------------------------------------------------------------------
    # B9: Build manual spec from config fields.
    # lambda_z_method "time_range" / "n_points" also map to manual spec shapes.
    lz_manual_spec = _cfg.lambda_z_manual
    if lz_method == "time_range" and _cfg.lambda_z_manual is not None:
        # manual spec should contain t_start/t_end; pass as manual method
        lz_manual_spec = _cfg.lambda_z_manual
    elif lz_method == "n_points" and _cfg.lambda_z_manual is not None:
        # manual spec should contain n_last
        lz_manual_spec = _cfg.lambda_z_manual

    # Resolve method name: "time_range" and "n_points" delegate to "manual"
    effective_lz_method = lz_method
    if lz_method in ("time_range", "n_points") and lz_manual_spec is not None:
        effective_lz_method = "manual"

    lz_result: LambdaZResult = fit_lambda_z(
        times=list(t_arr),
        concentrations=list(c_arr),
        tmax=tmax,
        method=effective_lz_method,  # type: ignore[arg-type]
        min_points=lz_min_points,
        tolerance=lz_tolerance,
        span_ratio_min=span_ratio_min,
        manual=lz_manual_spec,
        winnonlin_version=wn_version,
        actual_tlast=tlast,  # B10: pass actual Tlast for correct clast_pred
    )

    lambda_z = lz_result.lambda_z
    _lz_intercept = lz_result.intercept  # noqa: F841 (reserved for v0.5 diagnostics)
    clast_pred = lz_result.clast_pred

    if lambda_z is None:
        warnings.append("lambda_z_not_estimable")

    # Pass through span_ratio_low from lambda_z module
    for w in lz_result.warnings:
        if w not in warnings:
            warnings.append(w)

    # ------------------------------------------------------------------
    # 7. Derived terminal parameters
    # ------------------------------------------------------------------
    half_life: float | None = lz_result.half_life
    span: float | None = (
        (lz_result.t_end - lz_result.t_start)
        if lz_result.t_start is not None and lz_result.t_end is not None
        else None
    )

    # ------------------------------------------------------------------
    # 8. AUCINF
    # ------------------------------------------------------------------
    aucinf_obs: float | None = None
    aucinf_pred: float | None = None
    aumcinf_obs: float | None = None
    aumcinf_pred: float | None = None
    auc_extrap_obs: float | None = None
    auc_extrap_pred: float | None = None

    if lambda_z is not None:
        _aucinf_obs_val, _aumcinf_obs_val = auc_inf(
            auc_last=auc_last,
            aumc_last=aumc_last,
            clast=clast,
            tlast=tlast,
            lambda_z=lambda_z,
            variant="obs",
        )
        aucinf_obs = _aucinf_obs_val
        aumcinf_obs = _aumcinf_obs_val

        if aucinf_obs > 0:
            auc_extrap_obs = 100.0 * (aucinf_obs - auc_last) / aucinf_obs
            if auc_extrap_obs > 20.0:
                warnings.append("auc_extrap_high")
                flags_map.setdefault("AUC_%Extrap_obs", []).append("auc_extrap_high")

        if output_pred and clast_pred is not None:
            _aucinf_pred_val, _aumcinf_pred_val = auc_inf(
                auc_last=auc_last,
                aumc_last=aumc_last,
                clast=clast,
                tlast=tlast,
                lambda_z=lambda_z,
                variant="pred",
                clast_pred=clast_pred,
            )
            aucinf_pred = _aucinf_pred_val
            aumcinf_pred = _aumcinf_pred_val

            if aucinf_pred is not None and aucinf_pred > 0:
                auc_extrap_pred = 100.0 * (aucinf_pred - auc_last) / aucinf_pred

    # ------------------------------------------------------------------
    # 9. MRT
    # ------------------------------------------------------------------
    mrt_obs: float | None = None
    mrt_pred: float | None = None
    t_inf = dose.infusion_duration if dose is not None else None

    if aucinf_obs is not None and aucinf_obs > 0 and aumcinf_obs is not None:
        raw_mrt = aumcinf_obs / aucinf_obs
        if route == "iv_bolus":
            mrt_obs = raw_mrt
        elif route == "iv_infusion" and t_inf is not None:
            mrt_obs = raw_mrt - t_inf / 2.0
        else:
            # B3: oral/subcut/im — WinNonlin reports MRTINF = AUMC_inf / AUC_inf
            # for all routes; only the IV-infusion correction is route-specific.
            # MAT (MRT_oral - MRT_iv) requires paired IV data — deferred to v0.2.
            mrt_obs = raw_mrt

    if output_pred and aucinf_pred is not None and aucinf_pred > 0 and aumcinf_pred is not None:
        raw_mrt_pred = aumcinf_pred / aucinf_pred
        if route == "iv_bolus":
            mrt_pred = raw_mrt_pred
        elif route == "iv_infusion" and t_inf is not None:
            mrt_pred = raw_mrt_pred - t_inf / 2.0
        else:
            # B3: same logic for pred variant
            mrt_pred = raw_mrt_pred

    # ------------------------------------------------------------------
    # 10. CL / Vz / Vss
    # ------------------------------------------------------------------
    cl: float | None = None
    vz: float | None = None
    vss: float | None = None

    if dose is None:
        warnings.append("no_dose_record")
    else:
        dose_amount = dose.amount
        iv_routes = {"iv_bolus", "iv_infusion"}

        aucinf_for_cl = aucinf_obs  # always use obs variant for primary CL
        if aucinf_for_cl is not None and aucinf_for_cl > 0:
            cl = dose_amount / aucinf_for_cl

        if lambda_z is not None and aucinf_for_cl is not None and aucinf_for_cl > 0:
            vz = dose_amount / (lambda_z * aucinf_for_cl)

        if cl is not None and mrt_obs is not None and route in iv_routes:
            vss = cl * mrt_obs

    # Determine whether to use CL or CL/F naming
    iv_routes_set = {"iv_bolus", "iv_infusion"}
    use_iv_names = route in iv_routes_set
    cl_name = "CL" if use_iv_names else "CL_F"
    vz_name = "Vz" if use_iv_names else "Vz_F"

    # ------------------------------------------------------------------
    # 11–12. Partial AUCs
    # ------------------------------------------------------------------
    partial_aucs: dict[str, float | None] = {}
    for window_t1, window_t2 in _cfg.partial_auc_windows:
        param_name = f"AUC_{_fmt_time(window_t1)}_{_fmt_time(window_t2)}"
        if len(auc_times) < 2 or window_t1 >= window_t2:
            val: float | None = None
        else:
            try:
                val = partial_auc(
                    times=auc_times,
                    concentrations=auc_concs,
                    t1=window_t1,
                    t2=window_t2,
                    method=auc_method,  # type: ignore[arg-type]
                    lambda_z=lambda_z,
                    clast=clast,
                    tlast=tlast,
                )
            except (ValueError, Exception):
                val = None
        partial_aucs[param_name] = val

    # ------------------------------------------------------------------
    # 13. Build parameters dict
    # ------------------------------------------------------------------
    params: dict[str, float | None] = {
        "Cmax": cmax,
        "Tmax": tmax,
        "Tlast": tlast,
        "Clast": clast,
        "AUClast": auc_last,
        "AUMClast": aumc_last,
        "Lambda_z": lambda_z,
        "Lambda_z_lower": lz_result.t_start,
        "Lambda_z_upper": lz_result.t_end,
        "No_points_lambda_z": float(lz_result.n_points) if lz_result.n_points else None,
        "Rsq": lz_result.r_squared,
        "Rsq_adjusted": lz_result.adjusted_r_squared,
        "Span": span,
        "Span_ratio": lz_result.span_ratio,
        "HL_Lambda_z": half_life,
        "AUCINF_obs": aucinf_obs,
        "AUMCINF_obs": aumcinf_obs,
        "AUC_%Extrap_obs": auc_extrap_obs,
        "MRTINF_obs": mrt_obs,
        cl_name: cl,
        vz_name: vz,
    }

    if c0 is not None:
        params["C0"] = c0

    if output_pred:
        params["Clast_pred"] = clast_pred  # B15: gate on output_pred_variants
        params["AUCINF_pred"] = aucinf_pred
        params["AUMCINF_pred"] = aumcinf_pred
        params["AUC_%Extrap_pred"] = auc_extrap_pred
        params["MRTINF_pred"] = mrt_pred

    if use_iv_names and vss is not None:
        params["Vss"] = vss

    # Add partial AUCs
    params.update(partial_aucs)

    # ------------------------------------------------------------------
    # 14. Build NCAParameterRow list
    # ------------------------------------------------------------------
    rows: list[NCAParameterRow] = []
    for pname, pval in params.items():
        pval_float: float | None = None
        if pval is not None:
            pval_float = float(pval)
        pflags = flags_map.get(pname, [])
        # Pass through lambda_z warnings on relevant rows
        if pname in ("Lambda_z", "HL_Lambda_z", "AUCINF_obs", "AUCINF_pred"):
            if "lambda_z_not_estimable" in warnings:
                pflags = list(pflags) + ["lambda_z_not_estimable"]
        rows.append(
            _row(
                subject_id=subject_id,
                period=period,
                treatment=treatment,
                analyte=analyte,
                parameter=pname,
                value=pval_float,
                method=auc_method,
                winnonlin_version=wn_version,
                flags=pflags,
            )
        )

    return NCAResult(
        subject_id=subject_id,
        period=period,
        treatment=treatment,
        analyte=analyte,
        parameters=params,
        parameter_rows=rows,
        auc_result=auc_result_obj,
        lambda_z_result=lz_result,
        bloq_decisions=bloq_decisions,
        warnings=warnings,
        flags=flags_map,
    )


# ---------------------------------------------------------------------------
# Multi-subject convenience wrapper
# ---------------------------------------------------------------------------


def calculate_nca(
    concentrations: Sequence[ConcentrationRecord],
    doses: Sequence[DoseRecord] | None = None,
    config: NCAConfig | None = None,
    group_by: tuple[str, ...] = ("subject_id", "period", "treatment", "analyte"),
) -> list[NCAResult]:
    """Multi-subject convenience wrapper.

    Groups concentration records by the group_by tuple, joins with the
    corresponding dose row (matching subject_id + period + treatment when
    present), and calls calculate_nca_subject for each group.
    """
    dose_list: list[DoseRecord] = list(doses) if doses is not None else []

    # Index doses by (subject_id, period, treatment)
    dose_index: dict[tuple[str | None, str | None, str | None], DoseRecord] = {}
    for d in dose_list:
        key = (d.subject_id, d.period, d.treatment)
        dose_index[key] = d  # last wins on collision (v0.1 single-dose assumption)

    # Group concentration records
    def _group_key(r: ConcentrationRecord) -> tuple[str | None, ...]:
        return tuple(getattr(r, field, None) for field in group_by)

    sorted_recs = sorted(concentrations, key=_group_key)

    results: list[NCAResult] = []
    for _key, group_iter in groupby(sorted_recs, key=_group_key):
        group: list[ConcentrationRecord] = list(group_iter)
        rep = group[0]

        # Warn if multiple dose records exist for the same subject (v0.1 limitation)
        matching_doses = [
            d
            for d in dose_list
            if d.subject_id == rep.subject_id
            and (d.period is None or d.period == rep.period)
            and (d.treatment is None or d.treatment == rep.treatment)
        ]

        dose: DoseRecord | None = None
        if matching_doses:
            dose = matching_doses[0]

        result = calculate_nca_subject(group, dose=dose, config=config)

        # Append "single_dose_assumed" warning when more than one dose matched
        if len(matching_doses) > 1:
            new_warnings = list(result.warnings) + ["single_dose_assumed"]
            results.append(
                NCAResult(
                    subject_id=result.subject_id,
                    period=result.period,
                    treatment=result.treatment,
                    analyte=result.analyte,
                    parameters=result.parameters,
                    parameter_rows=result.parameter_rows,
                    auc_result=result.auc_result,
                    lambda_z_result=result.lambda_z_result,
                    bloq_decisions=result.bloq_decisions,
                    warnings=new_warnings,
                    flags=result.flags,
                )
            )
        else:
            results.append(result)

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fmt_time(t: float) -> str:
    """Format a time value for use in a parameter name (e.g. 0.5 -> '0_5')."""
    if t == int(t):
        return str(int(t))
    return str(t).replace(".", "_")
