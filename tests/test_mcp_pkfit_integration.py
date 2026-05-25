"""
Integration tests for impl_fit_pk_model, impl_simulate_pk_model,
and impl_list_pk_models in mcp_server.

Tests:
  1. Fit 1-cmt IV bolus to synthetic CSV → returns sane parameters.
  2. impl_simulate_pk_model produces concentrations matching analytical.
  3. impl_list_pk_models lists at least 7 models.
  4. impl_fit_pk_model with bad model name returns status="error".
  5. Audit file is produced after a successful fit.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pkplugin.mcp_server import (
    impl_fit_pk_model,
    impl_list_pk_models,
    impl_simulate_pk_model,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_1cmt_iv_bolus_csv(
    tmp_path: Path,
    V: float = 10.0,
    k: float = 0.2,
    dose: float = 100.0,
    noise_sd: float = 0.0,
    seed: int = 0,
) -> Path:
    """Write a synthetic 1-cmt IV bolus concentration CSV."""
    rng = np.random.default_rng(seed)
    times = np.array([0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 24.0])
    conc = (dose / V) * np.exp(-k * times)
    if noise_sd > 0.0:
        conc = conc + rng.normal(0.0, noise_sd * conc, size=len(conc))
        conc = np.maximum(conc, 0.0)
    df = pd.DataFrame({"time": times, "concentration": conc})
    csv_path = tmp_path / "1cmt_iv_bolus.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


# ---------------------------------------------------------------------------
# Test 1 — Fit 1-cmt IV bolus to synthetic CSV → sane parameters
# ---------------------------------------------------------------------------


def test_impl_fit_pk_model_1cmt_iv_bolus(tmp_path: Path) -> None:
    """Fit 1-cmt IV bolus to noiseless data; parameters should be close to true."""
    true_V, true_k, dose = 10.0, 0.2, 100.0
    csv_path = _make_1cmt_iv_bolus_csv(tmp_path, V=true_V, k=true_k, dose=dose)

    result = impl_fit_pk_model(
        dataset_path=str(csv_path),
        model_name="cmt1_iv_bolus",
        initial_params={"V": 8.0, "k": 0.15},
        dose=dose,
        weighting="1_over_y_squared",
        residual_error="proportional",
        audit_dir=str(tmp_path / "audit"),
    )

    assert result["status"] == "ok", f"Expected ok, got: {result}"
    assert "run_id" in result
    assert "parameters" in result
    params = result["parameters"]
    assert "V" in params
    assert "k" in params

    V_est = params["V"]["estimate"]
    k_est = params["k"]["estimate"]

    # Noiseless data → should recover parameters within 1%
    assert abs(V_est - true_V) / true_V < 0.01, f"V estimate {V_est} too far from {true_V}"
    assert abs(k_est - true_k) / true_k < 0.01, f"k estimate {k_est} too far from {true_k}"

    diag = result["diagnostics"]
    assert diag["converged"] is True
    assert diag["aic"] is not None


# ---------------------------------------------------------------------------
# Test 2 — impl_simulate_pk_model matches analytical
# ---------------------------------------------------------------------------


def test_impl_simulate_pk_model_matches_analytical() -> None:
    """simulate_pk_model should match direct closed-form prediction."""
    from pkplugin.comp.analytic import predict

    model_name = "cmt1_iv_bolus"
    params = {"V": 10.0, "k": 0.2}
    dose = 100.0
    times = [0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]

    result = impl_simulate_pk_model(
        model_name=model_name,
        params=params,
        dose=dose,
        times=times,
    )

    assert result["status"] == "ok", f"Expected ok, got: {result}"
    assert "concentrations" in result
    assert len(result["concentrations"]) == len(times)

    expected = predict(
        model=model_name,
        params=params,
        times=times,
        dose=dose,
    )

    for t, got, exp in zip(times, result["concentrations"], expected.tolist()):
        assert abs(got - exp) < 1e-9, (
            f"At t={t}: simulate returned {got}, analytic gives {exp}"
        )


# ---------------------------------------------------------------------------
# Test 3 — impl_list_pk_models lists at least 7 models
# ---------------------------------------------------------------------------


def test_impl_list_pk_models_count() -> None:
    """impl_list_pk_models must return at least 7 registered models."""
    result = impl_list_pk_models()

    assert result["status"] == "ok"
    assert "models" in result
    assert result["n_models"] >= 7, (
        f"Expected at least 7 models, got {result['n_models']}"
    )

    # Check each model entry has required fields
    for m in result["models"]:
        assert "name" in m
        assert "winnonlin_model_id" in m
        assert "parameter_names" in m
        assert isinstance(m["parameter_names"], list)
        assert len(m["parameter_names"]) >= 1

    # Spot-check expected models are present
    names = {m["name"] for m in result["models"]}
    for expected in (
        "cmt1_iv_bolus",
        "cmt1_iv_infusion",
        "cmt1_po",
        "cmt2_iv_bolus",
        "cmt2_iv_infusion",
        "cmt2_po",
        "cmt3_iv_bolus",
    ):
        assert expected in names, f"Expected model {expected!r} not in registry"


# ---------------------------------------------------------------------------
# Test 4 — impl_fit_pk_model with bad model name returns status="error"
# ---------------------------------------------------------------------------


def test_impl_fit_pk_model_bad_model_name(tmp_path: Path) -> None:
    """impl_fit_pk_model must return status=error for an unknown model name."""
    csv_path = _make_1cmt_iv_bolus_csv(tmp_path)

    result = impl_fit_pk_model(
        dataset_path=str(csv_path),
        model_name="not_a_real_model",
        initial_params={"V": 10.0, "k": 0.2},
        dose=100.0,
        audit_dir=str(tmp_path / "audit"),
    )

    assert result["status"] == "error", f"Expected error, got: {result}"
    assert "error" in result
    assert "not_a_real_model" in result["error"] or "Unknown" in result["error"]


# ---------------------------------------------------------------------------
# Test 5 — Audit file is produced after a successful fit
# ---------------------------------------------------------------------------


def test_impl_fit_pk_model_audit_produced(tmp_path: Path) -> None:
    """A successful fit must write audit.json to the run directory."""
    csv_path = _make_1cmt_iv_bolus_csv(tmp_path, V=10.0, k=0.2, dose=100.0)
    audit_dir = tmp_path / "audit"

    result = impl_fit_pk_model(
        dataset_path=str(csv_path),
        model_name="cmt1_iv_bolus",
        initial_params={"V": 8.0, "k": 0.15},
        dose=100.0,
        audit_dir=str(audit_dir),
    )

    assert result["status"] == "ok", f"Expected ok, got: {result}"

    audit_path = Path(result["audit_path"])
    assert audit_path.exists(), f"audit.json not found at {audit_path}"

    with audit_path.open() as fh:
        audit_data = json.load(fh)

    assert audit_data["tool"] == "fit_pk_model"
    assert audit_data["run_id"] == result["run_id"]

    fit_csv = Path(result["fit_csv_path"])
    assert fit_csv.exists(), f"fit_result.csv not found at {fit_csv}"

    fit_df = pd.read_csv(fit_csv)
    assert "parameter" in fit_df.columns
    assert "estimate" in fit_df.columns
    param_names = set(fit_df["parameter"].tolist())
    assert "V" in param_names
    assert "k" in param_names
