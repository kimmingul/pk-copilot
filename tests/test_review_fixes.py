"""
Tests covering review-fix regressions (B1–B15).

Required coverage per deliverable spec:
  B1  - partial_auc boundary-on-grid deduplication
  B2  - generated script is valid Python (compile check)
  B3  - oral/subcut MRT is populated
  B6  - "zero" and "missing" bloq_policy strings
  B7  - IV bolus t=0 BLOQ replaced with C0
  B8  - non-positive post-Tmax concentration excluded from λz
  B9  - lambda_z_manual time_range / n_last wiring
  B11 - non-decreasing C0 back-extrap fallback
  B13 - partial AUC window entirely beyond Tlast

Refs:
  docs/03-algorithms/01-nca-parameters.md
  docs/03-algorithms/02-auc-methods.md
  docs/03-algorithms/04-bloq-handling.md
  docs/03-algorithms/05-partial-auc.md
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest

from pkplugin.nca.auc import partial_auc
from pkplugin.nca.engine import NCAResult, calculate_nca_subject
from pkplugin.nca.lambda_z import fit_lambda_z
from pkplugin.schemas import ConcentrationRecord, DoseRecord, NCAConfig


# ---------------------------------------------------------------------------
# Helpers (mirrors test_nca_engine.py style)
# ---------------------------------------------------------------------------


def _make_conc(
    subject_id: str,
    times: list[float],
    concs: list[float | None],
    bloq: list[bool] | None = None,
    analyte: str = "parent",
) -> list[ConcentrationRecord]:
    if bloq is None:
        bloq = [False] * len(times)
    return [
        ConcentrationRecord(
            subject_id=subject_id,
            time=t,
            concentration=c,
            analyte=analyte,
            bloq=b,
        )
        for t, c, b in zip(times, concs, bloq)
    ]


def _make_dose(
    subject_id: str,
    amount: float,
    route: str,
    time: float = 0.0,
    infusion_duration: float | None = None,
) -> DoseRecord:
    return DoseRecord(
        subject_id=subject_id,
        time=time,
        amount=amount,
        route=route,  # type: ignore[arg-type]
        infusion_duration=infusion_duration,
    )


def _param(result: NCAResult, name: str) -> float | None:
    return result.parameters.get(name)


# ---------------------------------------------------------------------------
# B1: partial_auc boundary exactly on existing grid time
# ---------------------------------------------------------------------------


def test_partial_auc_boundary_on_grid_no_duplicate() -> None:
    """When t1 and t2 coincide with existing observation times, partial_auc
    must not produce duplicate time points (which would cause ValueError)."""
    times = [0.0, 2.0, 4.0, 6.0, 8.0, 12.0]
    concs = [10.0, 8.0, 6.0, 4.0, 2.0, 1.0]

    # t1=2.0 and t2=8.0 both exist in the grid — must not raise
    result = partial_auc(times, concs, t1=2.0, t2=8.0, method="linear_up_log_down")
    assert result > 0

    # t1=0.0 and t2=12.0 — full range using exact grid endpoints
    full = partial_auc(times, concs, t1=0.0, t2=12.0, method="linear_up_log_down")
    assert full > 0

    # t1 and t2 both on interior grid points
    inner = partial_auc(times, concs, t1=4.0, t2=6.0, method="linear")
    # Linear: (6+4)/2 * 2 = 10
    assert abs(inner - 10.0) < 1e-9


def test_partial_auc_boundary_on_grid_value_correct() -> None:
    """Verify numerical correctness when boundaries coincide with grid."""
    times = [0.0, 1.0, 2.0, 3.0, 4.0]
    concs = [10.0, 8.0, 6.0, 4.0, 2.0]

    # AUC [1, 3] via linear: (8+6)/2*1 + (6+4)/2*1 = 7 + 5 = 12
    result = partial_auc(times, concs, t1=1.0, t2=3.0, method="linear")
    assert abs(result - 12.0) < 1e-9


# ---------------------------------------------------------------------------
# B2: generated NCA script is valid Python
# ---------------------------------------------------------------------------


def test_nca_script_is_valid_python() -> None:
    """The auto-generated re-run script must compile without SyntaxError."""
    from pkplugin.mcp_server import _render_nca_script

    cfg = NCAConfig(
        winnonlin_version="6.4",
        bloq_policy="default",
        output_pred_variants=True,
        partial_auc_windows=[(0.0, 12.0)],
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        ds_path = Path(tmpdir) / "data.csv"
        ds_path.write_text("subject_id,time,concentration\nS1,0,10\n")
        script = _render_nca_script(ds_path, None, cfg, subjects=["S1"], analytes=None)
        # Must compile without error
        compile(script, "<nca_script>", "exec")


def test_nca_script_contains_subjects_filter() -> None:
    """When subjects filter is passed, the script must include a filter line."""
    from pkplugin.mcp_server import _render_nca_script

    cfg = NCAConfig()
    with tempfile.TemporaryDirectory() as tmpdir:
        ds_path = Path(tmpdir) / "data.csv"
        ds_path.write_text("subject_id,time,concentration\nS1,0,10\n")
        script = _render_nca_script(ds_path, None, cfg, subjects=["S1", "S2"])
        assert "subject_id" in script
        # Ensure the repr is valid Python (no json null/true/false)
        assert "null" not in script
        assert "true" not in script
        assert "false" not in script
        compile(script, "<nca_script>", "exec")


# ---------------------------------------------------------------------------
# B3: oral route MRT is populated
# ---------------------------------------------------------------------------


def test_oral_mrt_is_populated() -> None:
    """For oral route, MRTINF_obs must be set (= AUMCINF/AUCINF).

    Previously the MRT block silently dropped oral routes.
    """
    ka = 1.5
    ke = 0.2
    D = 100.0
    F = 1.0
    V = 20.0
    coeff = D * F * ka / (V * (ka - ke))

    times = [0.0, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 24.0]
    concs = [max(coeff * (math.exp(-ke * t) - math.exp(-ka * t)), 0.0) for t in times]

    recs = _make_conc("OralMRT", times, concs)
    dose = _make_dose("OralMRT", amount=D, route="oral")
    cfg = NCAConfig(winnonlin_version="6.4")

    result = calculate_nca_subject(recs, dose, cfg)

    mrt = _param(result, "MRTINF_obs")
    assert mrt is not None, "MRTINF_obs must be set for oral route"
    assert mrt > 0, f"MRTINF_obs should be positive, got {mrt}"


def test_subcut_mrt_is_populated() -> None:
    """For subcut route, MRTINF_obs must be set."""
    times = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]
    concs = [0.0, 5.0, 8.0, 7.0, 4.0, 2.0, 0.5]

    recs = _make_conc("SubcutMRT", times, concs)
    dose = _make_dose("SubcutMRT", amount=100.0, route="subcut")
    cfg = NCAConfig(winnonlin_version="6.4")

    result = calculate_nca_subject(recs, dose, cfg)

    mrt = _param(result, "MRTINF_obs")
    assert mrt is not None, "MRTINF_obs must be set for subcut route"


# ---------------------------------------------------------------------------
# B6: "zero" and "missing" bloq_policy strings
# ---------------------------------------------------------------------------


def test_bloq_policy_zero_string() -> None:
    """bloq_policy='zero' must replace ALL BLOQ positions with 0 (not exclude)."""
    # trailing BLOQ at t=12 should be treated as 0, not excluded
    times = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0]
    concs: list[float | None] = [None, 10.0, 8.0, 5.0, 2.0, None]
    bloq_flags = [True, False, False, False, False, True]

    recs = _make_conc("ZeroPolicy", times, concs, bloq=bloq_flags)
    dose = _make_dose("ZeroPolicy", amount=100.0, route="oral")
    cfg = NCAConfig(winnonlin_version="6.4", bloq_policy="zero")

    result = calculate_nca_subject(recs, dose, cfg)

    # With trailing BLOQ treated as 0: Tlast should be 12.0 and Clast = 8 or 0
    tlast = _param(result, "Tlast")
    # Under "zero" policy the trailing BLOQ at t=12 stays in with value 0,
    # but since it's zero it may or may not affect Tlast depending on implementation.
    # The key requirement is no exception and bloq decisions show "zero" treatment.
    trailing_dec = next(
        (d for d in result.bloq_decisions if d.time == 12.0 and d.rule == "trailing"),
        None,
    )
    assert trailing_dec is not None
    assert not trailing_dec.excluded, "zero policy must not exclude trailing BLOQ"
    assert trailing_dec.treated_as == 0.0


def test_bloq_policy_missing_string_embedded() -> None:
    """bloq_policy='missing' must drop ALL BLOQ positions (treat as missing)."""
    # Embedded BLOQ at t=4 should be excluded under "missing" policy
    times = [0.0, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0]
    concs: list[float | None] = [None, 10.0, 8.0, None, 5.0, 2.0, None]
    bloq_flags = [True, False, False, True, False, False, True]

    recs = _make_conc("MissingPolicy", times, concs, bloq=bloq_flags)
    dose = _make_dose("MissingPolicy", amount=100.0, route="oral")
    cfg = NCAConfig(winnonlin_version="6.4", bloq_policy="missing")

    result = calculate_nca_subject(recs, dose, cfg)

    # pre-dose BLOQ at t=0 must be excluded
    pre_dec = next(d for d in result.bloq_decisions if d.time == 0.0 and d.rule == "up_leading")
    assert pre_dec.excluded, "missing policy must exclude up_leading BLOQ"

    # embedded BLOQ at t=4 must be excluded
    emb_dec = next(
        (d for d in result.bloq_decisions if d.time == 4.0 and d.rule == "embedded"),
        None,
    )
    assert emb_dec is not None
    assert emb_dec.excluded, "missing policy must exclude embedded BLOQ"

    # trailing BLOQ at t=12 must be excluded
    trail_dec = next(
        (d for d in result.bloq_decisions if d.time == 12.0 and d.rule == "trailing"),
        None,
    )
    assert trail_dec is not None
    assert trail_dec.excluded, "missing policy must exclude trailing BLOQ"


# ---------------------------------------------------------------------------
# B7: IV bolus t=0 BLOQ should use C0 not 0
# ---------------------------------------------------------------------------


def test_iv_bolus_t0_bloq_uses_c0() -> None:
    """When IV bolus has a BLOQ at t=0, AUC integration must use back-extrapolated
    C0, not the BLOQ-replaced 0.  AUCINF should be similar to the no-BLOQ case."""
    V = 10.0
    k = 0.3
    D = 100.0

    times_no_bloq = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]
    concs_no_bloq = [(D / V) * math.exp(-k * t) for t in times_no_bloq]

    # With t=0 as BLOQ (value None, bloq=True)
    times_bloq = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]
    concs_bloq: list[float | None] = [None] + [(D / V) * math.exp(-k * t) for t in times_bloq[1:]]
    bloq_flags = [True] + [False] * (len(times_bloq) - 1)

    recs_no_bloq = _make_conc("IVBolus_NoBloq", times_no_bloq, concs_no_bloq)
    recs_bloq = _make_conc("IVBolus_Bloq", times_bloq, concs_bloq, bloq=bloq_flags)

    dose_no_bloq = _make_dose("IVBolus_NoBloq", amount=D, route="iv_bolus")
    dose_bloq = _make_dose("IVBolus_Bloq", amount=D, route="iv_bolus")

    cfg = NCAConfig(winnonlin_version="6.4", c0_method="log_back_extrap", auc_method="linear")

    result_no_bloq = calculate_nca_subject(recs_no_bloq, dose_no_bloq, cfg)
    result_bloq = calculate_nca_subject(recs_bloq, dose_bloq, cfg)

    aucinf_no_bloq = _param(result_no_bloq, "AUCINF_obs")
    aucinf_bloq = _param(result_bloq, "AUCINF_obs")

    assert aucinf_no_bloq is not None
    assert aucinf_bloq is not None
    # With B7 fix, AUCINF should be very similar (within 5%) because C0 replaces the BLOQ zero
    rel_err = abs(aucinf_bloq - aucinf_no_bloq) / aucinf_no_bloq
    assert rel_err < 0.05, (
        f"AUCINF with t=0 BLOQ ({aucinf_bloq:.4f}) should be close to "
        f"no-BLOQ case ({aucinf_no_bloq:.4f}), got {rel_err:.2%} relative error"
    )


# ---------------------------------------------------------------------------
# B8: non-positive post-Tmax concentration excluded from λz
# ---------------------------------------------------------------------------


def test_lambda_z_excludes_nonpositive_post_tmax() -> None:
    """Post-Tmax concentrations that are 0 or negative must not be used in λz fit."""
    # Times: Tmax at t=1; post-tmax has a zero at t=6
    times = [0.0, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0]
    concs = [0.0, 10.0, 8.0, 5.0, 0.0, 2.0, 1.0]  # zero at t=6

    result = fit_lambda_z(
        times=times,
        concentrations=concs,
        tmax=1.0,
        method="best_fit",
        min_points=3,
    )

    # The zero at t=6 must be in excluded_points
    excluded_times = [ep["time"] for ep in result.excluded_points]
    assert 6.0 in excluded_times, f"t=6 (c=0) should be excluded; got excluded_times={excluded_times}"

    # λz should still be estimable from the remaining positive points
    assert result.lambda_z is not None, "lambda_z should be estimable from remaining positive points"


def test_lambda_z_excludes_negative_post_tmax() -> None:
    """Negative concentrations post-Tmax are excluded."""
    # Need enough post-tmax positive points for min_points=3 after excluding t=6
    times = [0.0, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 24.0]
    concs = [0.0, 10.0, 8.0, 5.0, -1.0, 3.0, 1.5, 0.5]  # negative at t=6

    result = fit_lambda_z(
        times=times,
        concentrations=concs,
        tmax=1.0,
        method="best_fit",
        min_points=3,
    )

    excluded_times = [ep["time"] for ep in result.excluded_points]
    assert 6.0 in excluded_times


# ---------------------------------------------------------------------------
# B9: lambda_z_manual wiring through engine
# ---------------------------------------------------------------------------


def test_engine_lambda_z_manual_time_range() -> None:
    """lambda_z_method='time_range' with lambda_z_manual={t_start, t_end} must
    select only the specified window for λz regression."""
    V = 10.0
    k = 0.3
    D = 100.0

    times = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]
    concs = [(D / V) * math.exp(-k * t) for t in times]

    recs = _make_conc("ManualRange", times, concs)
    dose = _make_dose("ManualRange", amount=D, route="iv_bolus")

    cfg = NCAConfig(
        winnonlin_version="6.4",
        c0_method="observed",
        lambda_z_method="time_range",
        lambda_z_manual={"t_start": 8.0, "t_end": 24.0},
    )

    result = calculate_nca_subject(recs, dose, cfg)

    lz = _param(result, "Lambda_z")
    assert lz is not None
    # With only t=8,12,24 the fit should recover k=0.3 closely
    assert abs(lz - k) / k < 0.01, f"Expected λz≈{k}, got {lz}"

    # Regression window should match the requested range
    assert result.lambda_z_result.t_start is not None
    assert result.lambda_z_result.t_end is not None
    assert abs(result.lambda_z_result.t_start - 8.0) < 0.01
    assert abs(result.lambda_z_result.t_end - 24.0) < 0.01


def test_engine_lambda_z_manual_n_last() -> None:
    """lambda_z_method='n_points' with lambda_z_manual={n_last: 3} selects
    the last 3 post-tmax points for regression."""
    V = 10.0
    k = 0.3
    D = 100.0

    times = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]
    concs = [(D / V) * math.exp(-k * t) for t in times]

    recs = _make_conc("ManualNLast", times, concs)
    dose = _make_dose("ManualNLast", amount=D, route="iv_bolus")

    cfg = NCAConfig(
        winnonlin_version="6.4",
        c0_method="observed",
        lambda_z_method="n_points",
        lambda_z_manual={"n_last": 3},
    )

    result = calculate_nca_subject(recs, dose, cfg)

    lz = _param(result, "Lambda_z")
    assert lz is not None
    # 3 points from exponential are exact; expect very close to k
    assert abs(lz - k) / k < 0.01, f"Expected λz≈{k}, got {lz}"
    assert result.lambda_z_result.n_points == 3


# ---------------------------------------------------------------------------
# B11: non-decreasing C0 back-extrap fallback
# ---------------------------------------------------------------------------


def test_c0_back_extrap_skipped_when_non_decreasing() -> None:
    """When first two concentrations are non-decreasing, C0 back-extrap must be
    skipped and warning 'c0_back_extrap_skipped_non_decreasing' must be emitted."""
    # Ascending first two points (C increasing: 2 → 5) — back-extrap would give nonsense
    times = [0.5, 1.0, 2.0, 4.0, 8.0, 12.0]
    concs = [2.0, 5.0, 4.0, 3.0, 1.5, 0.5]

    recs = _make_conc("NonDecC0", times, concs)
    dose = _make_dose("NonDecC0", amount=100.0, route="iv_bolus")
    cfg = NCAConfig(winnonlin_version="6.4", c0_method="log_back_extrap")

    result = calculate_nca_subject(recs, dose, cfg)

    assert "c0_back_extrap_skipped_non_decreasing" in result.warnings, (
        f"Expected warning not found; got: {result.warnings}"
    )
    # C0 should equal the first quantifiable concentration (fallback to observed)
    c0 = _param(result, "C0")
    assert c0 is not None
    assert abs(c0 - 2.0) < 1e-9, f"Expected C0=2.0 (first quantifiable), got {c0}"


# ---------------------------------------------------------------------------
# B13: partial AUC window entirely beyond Tlast
# ---------------------------------------------------------------------------


def test_partial_auc_beyond_tlast_analytical() -> None:
    """When the entire window [t1, t2] is beyond Tlast, partial_auc must return
    the analytical tail: clast/λz * (exp(-λz*(t1-Tlast)) - exp(-λz*(t2-Tlast)))."""
    times = [0.0, 1.0, 2.0, 4.0, 8.0]
    clast_val = 2.0
    lambda_z_val = 0.3
    concs = [10.0, 8.0, 6.0, 4.0, clast_val]

    t1 = 10.0  # beyond Tlast=8
    t2 = 24.0
    tlast = 8.0

    result = partial_auc(
        times,
        concs,
        t1=t1,
        t2=t2,
        method="linear_up_log_down",
        lambda_z=lambda_z_val,
        clast=clast_val,
        tlast=tlast,
    )

    expected = clast_val / lambda_z_val * (
        math.exp(-lambda_z_val * (t1 - tlast))
        - math.exp(-lambda_z_val * (t2 - tlast))
    )
    assert abs(result - expected) < 1e-9, f"Expected {expected}, got {result}"


def test_partial_auc_beyond_tlast_via_engine() -> None:
    """Engine partial AUC window beyond Tlast is computed correctly."""
    V = 10.0
    k = 0.3
    D = 100.0

    times = [0.0, 1.0, 2.0, 4.0, 8.0, 12.0]
    concs = [(D / V) * math.exp(-k * t) for t in times]

    recs = _make_conc("BeyondTlast", times, concs)
    dose = _make_dose("BeyondTlast", amount=D, route="iv_bolus")
    cfg = NCAConfig(
        winnonlin_version="6.4",
        c0_method="observed",
        partial_auc_windows=[(14.0, 24.0)],  # entirely beyond Tlast=12
    )

    result = calculate_nca_subject(recs, dose, cfg)

    auc_14_24 = result.parameters.get("AUC_14_24")
    assert auc_14_24 is not None, "Partial AUC beyond Tlast must be computed when λz available"
    assert auc_14_24 > 0


# ---------------------------------------------------------------------------
# B14: canonical unit conversion in load_dataset
# ---------------------------------------------------------------------------


def test_b14_load_dataset_converts_time_min_to_hour(tmp_path):
    """time_min column values should be divided by 60 (canonical hour)."""
    import pandas as pd  # noqa: F401
    from pkplugin.ingest import ColumnMapping, load_dataset

    p = tmp_path / "min.csv"
    p.write_text(
        "subject_id,time_min,conc_ng_per_ml\n"
        "S001,0,10\nS001,30,8.61\nS001,60,7.41\nS001,120,5.49\n"
    )
    df, rpt = load_dataset(
        p,
        column_mapping=ColumnMapping(
            subject_id="subject_id",
            time="time_min",
            concentration="conc_ng_per_ml",
        ),
    )
    assert df["time"].tolist() == [0.0, 0.5, 1.0, 2.0]
    assert any("canonical_unit_conversion_applied" in w for w in rpt.warnings)


def test_b14_load_dataset_skips_molar_concentration(tmp_path):
    """nmol/L concentration should NOT be converted (requires MW); warning emitted."""
    from pkplugin.ingest import ColumnMapping, load_dataset

    p = tmp_path / "molar.csv"
    p.write_text(
        "subject_id,time_hr,conc_nmol_L\nS001,0,100\nS001,1,80\n"
    )
    df, rpt = load_dataset(
        p,
        column_mapping=ColumnMapping(
            subject_id="subject_id",
            time="time_hr",
            concentration="conc_nmol_L",
        ),
    )
    # Values left as-is — caller must supply MW.
    assert df["concentration"].tolist() == [100.0, 80.0]
    assert any("molar" in w for w in rpt.warnings)


# ---------------------------------------------------------------------------
# Cleanup commit regression tests (literature review follow-ups)
# ---------------------------------------------------------------------------


def test_aucmethod_linear_log_alias_works():
    """`linear_log` alias must produce identical results to `linear_up_log_down`."""
    from pkplugin.nca.auc import auc_trapezoid

    times = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 16.0, 24.0]
    concs = [10.0, 7.788, 6.065, 3.679, 1.353, 0.183, 0.0247, 0.00335, 6.144e-5]
    r1 = auc_trapezoid(times, concs, method="linear_up_log_down")
    r2 = auc_trapezoid(times, concs, method="linear_log")  # type: ignore[arg-type]
    assert r1.auc == r2.auc
    assert r1.aumc == r2.aumc


def test_analytic_predict_rejects_mm_models():
    """analytic.predict refuses MM models with a clear ODE-routing hint."""
    import pytest
    from pkplugin.comp.analytic import predict

    with pytest.raises(ValueError, match="Michaelis-Menten"):
        predict(
            model="cmt1_iv_mm",
            params={"V": 10.0, "Vmax": 50.0, "Km": 5.0},
            times=[0.5, 1.0, 2.0],
            dose=100.0,
        )


def test_registry_includes_mm_models():
    """MM models are discoverable via REGISTRY with has_michaelis_menten=True."""
    from pkplugin.comp.models import REGISTRY

    for name in ("cmt1_iv_mm", "cmt1_po_mm", "cmt2_iv_mm"):
        assert name in REGISTRY
        assert REGISTRY[name].has_michaelis_menten is True


def test_mcp_simulate_pk_model_routes_mm_to_ode():
    """impl_simulate_pk_model handles MM models via the ODE backend."""
    from pkplugin.mcp_server import impl_simulate_pk_model

    result = impl_simulate_pk_model(
        model_name="cmt1_iv_mm",
        params={"V": 10.0, "Vmax": 50.0, "Km": 5.0},
        dose=100.0,
        times=[0.5, 1.0, 2.0, 4.0, 8.0],
    )
    assert result["status"] == "ok"
    assert len(result["concentrations"]) == 5
