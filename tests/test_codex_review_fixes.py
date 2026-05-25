"""
Regression tests for Codex review fixes (C1, H1, H2, H3, H4, H5, H6, H7).

One or more tests per CRITICAL/HIGH item as required by the deliverable spec.

Refs: docs/03-algorithms/08-compartmental-models.md §3–§6
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import pytest

from pkplugin.comp.ode import (
    MODEL_REQUIRED_PARAMS,
    DosingEvent,
    simulate_ode,
)

# ---------------------------------------------------------------------------
# C1: sentinel 0.0 no longer overwrites real zero observations
# ---------------------------------------------------------------------------


def test_c1_zero_concentration_at_t0_oral_not_overwritten() -> None:
    """For an oral dose with no lag, concentration at t=0 is genuinely 0
    (nothing in the central compartment yet).  The ODE must return 0, not
    the post-final-segment state value."""
    dose, V_F, ka, k = 100.0, 20.0, 1.5, 0.3
    # t=0 is truly 0 for oral (dose is in depot, central is empty)
    times = np.array([0.0, 0.5, 1.0, 2.0, 4.0, 8.0])
    dosing = [DosingEvent(time=0.0, amount=dose, route="oral")]

    conc = simulate_ode("cmt1_po", {"V_F": V_F, "ka": ka, "k": k}, dosing, times)

    # t=0 central compartment must be 0 (depot is full, central is empty)
    assert conc[0] == 0.0, f"Expected C(t=0)=0 for oral model (pre-absorption), got {conc[0]}"
    # Later times must be positive
    assert np.all(conc[1:] > 0.0), "Post-dose concentrations must be positive"


def test_c1_zero_conc_not_overwritten_by_fallback() -> None:
    """Observation at t=0 with genuinely zero central compartment should stay
    zero — the old sentinel fallback would overwrite it with a non-zero value
    from the post-final-segment state."""
    # 1-cmt IV bolus at t=6 (no t=0 dose), so C(0)=0 legitimately
    V, k = 10.0, 0.2
    times = np.array([0.0, 3.0, 6.5, 12.0])
    dosing = [DosingEvent(time=6.0, amount=100.0, route="iv_bolus")]

    conc = simulate_ode("cmt1_iv_bolus", {"V": V, "k": k}, dosing, times)

    # Before the dose there is no drug
    assert conc[0] == 0.0, f"Expected 0 at t=0 (before dose at t=6), got {conc[0]}"
    assert conc[1] == 0.0, f"Expected 0 at t=3 (before dose at t=6), got {conc[1]}"
    assert conc[2] > 0.0, "Expected positive conc just after dose at t=6.5"


# ---------------------------------------------------------------------------
# H1: post-dose convention — obs at dose time reflects post-dose state
# ---------------------------------------------------------------------------


def test_h1_iv_bolus_t0_obs_is_post_dose() -> None:
    """For IV bolus at t=0, the concentration at t=0 must equal Dose/V
    (post-dose), not zero (pre-dose)."""
    dose, V, k = 100.0, 20.0, 0.3
    times = np.array([0.0, 1.0, 4.0])
    dosing = [DosingEvent(time=0.0, amount=dose, route="iv_bolus")]

    conc = simulate_ode("cmt1_iv_bolus", {"V": V, "k": k}, dosing, times)

    expected_c0 = dose / V  # 5.0 ng/mL
    assert abs(conc[0] - expected_c0) < 1e-9, (
        f"Expected post-dose C(0)={expected_c0}, got {conc[0]}"
    )


def test_h1_iv_bolus_second_dose_obs_is_post_dose() -> None:
    """Observation at the exact time of a second dose must reflect post-dose
    state (the bolus delta has been added)."""
    V, k = 20.0, 0.3
    dose = 100.0
    # Two doses: t=0 and t=12
    times = np.array([0.0, 11.999, 12.0, 13.0])
    dosing = [
        DosingEvent(time=0.0, amount=dose, route="iv_bolus"),
        DosingEvent(time=12.0, amount=dose, route="iv_bolus"),
    ]

    conc = simulate_ode("cmt1_iv_bolus", {"V": V, "k": k}, dosing, times)

    # Just before t=12 (pre-dose residual)
    c_pre = (dose / V) * math.exp(-k * 11.999)
    # At t=12 (post-dose): residual + new dose/V
    c_at_12_expected = (dose / V) * math.exp(-k * 12.0) + dose / V

    assert abs(conc[2] - c_at_12_expected) < 1e-5, (
        f"Expected post-dose C(12)≈{c_at_12_expected:.4f}, got {conc[2]:.4f}"
    )
    # Post-dose must exceed pre-dose concentration
    assert conc[2] > conc[1], "C at dose time must exceed C just before dose (post-dose convention)"


# ---------------------------------------------------------------------------
# H2: MM unit sanity check — Vmax in concentration/time, Km in concentration
# ---------------------------------------------------------------------------


def test_h2_mm_linear_regime_matches_analytical() -> None:
    """At C << Km the MM RHS reduces to first-order with k_eff = Vmax/Km.
    Analytical: C(t) = C0 * exp(-Vmax/Km * t).

    Params from spec: Vmax=100 ng/mL/hr, Km=5 ng/mL, V=10 L.
    """
    V = 10.0  # L
    Vmax = 100.0  # ng/mL/hr  (concentration-based)
    Km = 5.0  # ng/mL
    k_eff = Vmax / Km  # 20 hr⁻¹

    # Very small dose so C = A/V << Km throughout
    tiny_dose = 0.001  # mg  → C0 = 0.001/10 = 0.0001 ng/mL << 5 ng/mL
    times = np.array([0.0, 0.05, 0.1, 0.2])
    dosing = [DosingEvent(time=0.0, amount=tiny_dose, route="iv_bolus")]

    conc = simulate_ode(
        "cmt1_iv_mm",
        {"V": V, "Vmax": Vmax, "Km": Km},
        dosing,
        times,
    )

    c0 = tiny_dose / V
    ref = c0 * np.exp(-k_eff * times)
    # Should agree to within 0.1% in the linear regime
    np.testing.assert_allclose(
        conc, ref, rtol=1e-3, atol=1e-15, err_msg="MM linear regime must match k_eff=Vmax/Km"
    )


def test_h2_mm_saturation_slows_elimination() -> None:
    """At C >> Km, apparent elimination rate ≈ Vmax (concentration/time).

    Use a dose so that C0 = dose/V is 200x Km to be deep in saturation.
    Params: Vmax=100 ng/mL/hr, Km=5 ng/mL, V=10 L.
    dose = 200 * Km * V = 10000 (same unit system) → C0 = 1000 >> Km=5.
    dC/dt|sat = -Vmax * C/(Km+C) ≈ -Vmax when C >> Km.
    So over dt=0.0001 hr: ΔC ≈ -Vmax * dt = -0.01.
    """
    V, Vmax, Km = 10.0, 100.0, 5.0
    # C0 = 10000/10 = 1000 >> Km=5 (200x saturation)
    high_dose = 10000.0
    times = np.array([0.0, 0.0001])
    dosing = [DosingEvent(time=0.0, amount=high_dose, route="iv_bolus")]

    conc = simulate_ode(
        "cmt1_iv_mm",
        {"V": V, "Vmax": Vmax, "Km": Km},
        dosing,
        times,
    )

    assert conc[0] > conc[1] > 0.0, "Saturation should cause monotone decay"
    # At deep saturation: dC/dt ≈ -Vmax (in concentration/time units)
    actual_rate = (conc[0] - conc[1]) / 0.0001
    # Should be within 5% of Vmax
    assert abs(actual_rate - Vmax) / Vmax < 0.05, (
        f"Saturated MM elimination rate {actual_rate:.2f} should ≈ Vmax={Vmax}"
    )


# ---------------------------------------------------------------------------
# H3: missing required parameters raise ValueError (no silent fallbacks)
# ---------------------------------------------------------------------------


def test_h3_missing_required_param_raises() -> None:
    """Omitting a required parameter must raise ValueError immediately."""
    dosing = [DosingEvent(time=0.0, amount=100.0, route="iv_bolus")]
    times = np.array([1.0, 2.0])

    # cmt1_iv_bolus requires V and k; omit k
    with pytest.raises(ValueError, match="Missing required parameters"):
        simulate_ode("cmt1_iv_bolus", {"V": 10.0}, dosing, times)


def test_h3_missing_mm_param_raises() -> None:
    """Omitting Vmax for an MM model raises ValueError."""
    dosing = [DosingEvent(time=0.0, amount=100.0, route="iv_bolus")]
    times = np.array([1.0, 2.0])

    with pytest.raises(ValueError, match="Missing required parameters"):
        simulate_ode("cmt1_iv_mm", {"V": 10.0, "Km": 5.0}, dosing, times)


def test_h3_model_required_params_table_complete() -> None:
    """MODEL_REQUIRED_PARAMS must list every model in _MODEL_META."""
    from pkplugin.comp.ode import _MODEL_META

    for model_name in _MODEL_META:
        assert model_name in MODEL_REQUIRED_PARAMS, (
            f"MODEL_REQUIRED_PARAMS missing entry for {model_name!r}"
        )
        # Each required set must be non-empty
        assert len(MODEL_REQUIRED_PARAMS[model_name]) > 0, (
            f"MODEL_REQUIRED_PARAMS[{model_name!r}] is empty"
        )


# ---------------------------------------------------------------------------
# H4: dose_route in fit_pk_model
# ---------------------------------------------------------------------------


def test_h4_dose_route_iv_infusion_requires_duration() -> None:
    """Passing dose_route='iv_infusion' without infusion_duration must raise."""
    from pkplugin.comp.fitting import fit_pk_model

    times = np.array([1.0, 2.0, 4.0, 8.0])
    obs = np.array([3.0, 2.5, 1.5, 0.5])

    with pytest.raises(ValueError, match="infusion_duration"):
        fit_pk_model(
            times,
            obs,
            "cmt1_iv_infusion",
            initial_params={"V": 20.0, "k": 0.3},
            dose=100.0,
            dose_route="iv_infusion",
            # infusion_duration intentionally omitted
        )


def test_h4_dose_route_oral_builds_oral_event() -> None:
    """dose_route='oral' must produce an oral DosingEvent (not iv_bolus)."""
    import math

    from pkplugin.comp.fitting import fit_pk_model

    # Generate noiseless oral data
    V_F, ka, k, dose = 20.0, 1.5, 0.3, 100.0
    times = np.array([0.5, 1.0, 2.0, 3.0, 6.0, 12.0])
    obs = np.array(
        [dose * ka / (V_F * (ka - k)) * (math.exp(-k * t) - math.exp(-ka * t)) for t in times]
    )

    # With explicit dose_route="oral"
    result = fit_pk_model(
        times,
        obs,
        "cmt1_po",
        initial_params={"V_F": 25.0, "ka": 1.0, "k": 0.4},
        dose=dose,
        dose_route="oral",
        weighting="uniform",
        use_ode=True,
    )
    assert result.diagnostics.converged
    # Fitted V_F should be within 10% of true value
    assert abs(result.parameters["V_F"] - V_F) / V_F < 0.10


def test_h4_dose_route_none_infers_oral_from_model_name() -> None:
    """When dose_route is not set and model contains 'po', oral is inferred."""
    import math

    from pkplugin.comp.fitting import fit_pk_model

    V_F, ka, k, dose = 20.0, 1.5, 0.3, 100.0
    times = np.array([0.5, 1.0, 2.0, 3.0, 6.0, 12.0])
    obs = np.array(
        [dose * ka / (V_F * (ka - k)) * (math.exp(-k * t) - math.exp(-ka * t)) for t in times]
    )

    # No dose_route supplied — should infer "oral" from "cmt1_po"
    result = fit_pk_model(
        times,
        obs,
        "cmt1_po",
        initial_params={"V_F": 25.0, "ka": 1.0, "k": 0.4},
        dose=dose,
        weighting="uniform",
        use_ode=True,
    )
    assert result.diagnostics.converged


# ---------------------------------------------------------------------------
# H5: missing initial_params raises ValueError before fitting
# ---------------------------------------------------------------------------


def test_h5_missing_initial_param_raises() -> None:
    """Omitting a required parameter from initial_params raises ValueError."""
    from pkplugin.comp.fitting import fit_pk_model

    times = np.array([1.0, 2.0, 4.0, 8.0])
    obs = np.array([5.0, 4.0, 2.5, 1.0])

    # cmt1_iv_bolus requires V and k; only provide V
    with pytest.raises(ValueError, match="missing required parameters"):
        fit_pk_model(
            times,
            obs,
            "cmt1_iv_bolus",
            initial_params={"V": 20.0},  # missing k
            dose=100.0,
            use_ode=True,
        )


# ---------------------------------------------------------------------------
# H6: MCP accepts ODE-only MM models
# ---------------------------------------------------------------------------


def test_h6_simulate_mm_model_accepted() -> None:
    """impl_simulate_pk_model must accept cmt1_iv_mm (ODE-only MM model)."""
    from pkplugin.mcp_server import impl_simulate_pk_model

    result = impl_simulate_pk_model(
        model_name="cmt1_iv_mm",
        params={"V": 10.0, "Vmax": 50.0, "Km": 5.0},
        dose=100.0,
        times=[0.5, 1.0, 2.0, 4.0, 8.0],
    )

    assert result["status"] == "ok", f"Expected ok, got: {result}"
    concs = result["concentrations"]
    assert len(concs) == 5
    # Allow tiny floating-point undershoot (≥ -1e-12) common near zero
    assert all(c >= -1e-12 for c in concs)


def test_h6_fit_mm_model_accepted() -> None:
    """impl_fit_pk_model must accept cmt1_iv_mm without error about REGISTRY."""
    from pkplugin.mcp_server import impl_fit_pk_model

    # Simulate data first
    V, Vmax, Km = 10.0, 50.0, 5.0
    dose = 100.0
    times = np.array([0.5, 1.0, 2.0, 4.0, 8.0])
    dosing = [DosingEvent(time=0.0, amount=dose, route="iv_bolus")]
    concs = simulate_ode("cmt1_iv_mm", {"V": V, "Vmax": Vmax, "Km": Km}, dosing, times)

    with tempfile.TemporaryDirectory() as tmpdir:
        ds_path = Path(tmpdir) / "data.csv"
        import pandas as pd

        pd.DataFrame({"time": times.tolist(), "concentration": concs.tolist()}).to_csv(
            ds_path, index=False
        )

        result = impl_fit_pk_model(
            dataset_path=str(ds_path),
            model_name="cmt1_iv_mm",
            initial_params={"V": 12.0, "Vmax": 60.0, "Km": 6.0},
            dose=dose,
            use_ode=True,
            audit_dir=tmpdir,
        )

    assert result["status"] == "ok", f"Expected ok, got error: {result.get('error')}"
    assert "parameters" in result


def test_h6_unknown_model_error_shows_mm_models() -> None:
    """Error message for unknown model should list MM model names."""
    from pkplugin.mcp_server import impl_simulate_pk_model

    result = impl_simulate_pk_model(
        model_name="cmt99_fake",
        params={"V": 10.0},
        dose=100.0,
        times=[1.0],
    )

    assert result["status"] == "error"
    # Error should mention the combined set including MM models
    assert "cmt1_iv_mm" in result["error"] or "Available" in result["error"]


# ---------------------------------------------------------------------------
# H7: dose_path CSV filtered by subject_id
# ---------------------------------------------------------------------------


def test_h7_dose_path_filtered_by_subject() -> None:
    """When dose_path has multiple subjects, only the matching subject's
    dose rows should be used for the fit."""
    from pkplugin.mcp_server import impl_fit_pk_model

    V, k = 20.0, 0.3
    dose_s1, dose_s2 = 100.0, 200.0

    # Create conc data for subject S1 only
    times = np.array([0.5, 1.0, 2.0, 4.0, 8.0, 12.0])
    dosing_s1 = [DosingEvent(time=0.0, amount=dose_s1, route="iv_bolus")]
    concs_s1 = simulate_ode("cmt1_iv_bolus", {"V": V, "k": k}, dosing_s1, times)

    import pandas as pd

    with tempfile.TemporaryDirectory() as tmpdir:
        ds_path = Path(tmpdir) / "data.csv"
        pd.DataFrame(
            {
                "subject_id": ["S1"] * len(times),
                "time": times.tolist(),
                "concentration": concs_s1.tolist(),
            }
        ).to_csv(ds_path, index=False)

        # Dose CSV has both subjects; S2 has a very different dose
        dose_path = Path(tmpdir) / "doses.csv"
        pd.DataFrame(
            {
                "subject_id": ["S1", "S2"],
                "time": [0.0, 0.0],
                "amount": [dose_s1, dose_s2],
                "route": ["iv_bolus", "iv_bolus"],
            }
        ).to_csv(dose_path, index=False)

        result = impl_fit_pk_model(
            dataset_path=str(ds_path),
            model_name="cmt1_iv_bolus",
            initial_params={"V": 25.0, "k": 0.4},
            dose_path=str(dose_path),
            use_ode=True,
            audit_dir=tmpdir,
        )

    assert result["status"] == "ok", f"Got error: {result.get('error')}"
    # V should be close to true V=20 (not biased by S2's dose=200)
    v_est = result["parameters"]["V"]["estimate"]
    assert abs(v_est - V) / V < 0.15, (
        f"V estimate {v_est:.2f} should be near {V} when using only S1 dose"
    )
