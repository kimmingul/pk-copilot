"""
Integration tests for impl_fit_pd_model, impl_simulate_pd_model,
and impl_list_pd_models in mcp_server.

Tests:
  1. End-to-end fit_pd_model via MCP.
  2. simulate_pd_model returns correct effects.
  3. list_pd_models returns all 10 models.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from pkplugin.mcp_server import (
    impl_fit_pd_model,
    impl_list_pd_models,
    impl_simulate_pd_model,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_emax_csv(
    tmp_path: Path,
    E0: float = 1.0,
    Emax: float = 10.0,
    EC50: float = 5.0,
) -> Path:
    conc = np.linspace(0.0, 50.0, 20)
    times = np.arange(len(conc), dtype=np.float64)
    effects = E0 + Emax * conc / (EC50 + conc)
    df = pd.DataFrame({"time": times, "concentration": conc, "effect": effects})
    csv_path = tmp_path / "emax_pd.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


# ---------------------------------------------------------------------------
# Test 1 — End-to-end fit_pd_model via MCP
# ---------------------------------------------------------------------------


def test_impl_fit_pd_model_emax(tmp_path: Path) -> None:
    """Fit Emax model via MCP; parameters should be close to true values."""
    true_E0, true_Emax, true_EC50 = 1.0, 10.0, 5.0
    csv_path = _make_emax_csv(tmp_path, E0=true_E0, Emax=true_Emax, EC50=true_EC50)

    result = impl_fit_pd_model(
        pd_dataset_path=str(csv_path),
        model_name="emax",
        initial_params={"E0": 0.5, "Emax": 8.0, "EC50": 3.0},
        mode="sequential",
        weighting="uniform",
        audit_dir=str(tmp_path / "audit"),
    )

    assert result["status"] == "ok", f"Expected ok, got: {result}"
    assert "run_id" in result
    assert "parameters" in result
    params = result["parameters"]
    assert "E0" in params
    assert "Emax" in params
    assert "EC50" in params

    assert result["diagnostics"]["converged"] is True

    for name, true_val in [("E0", true_E0), ("Emax", true_Emax), ("EC50", true_EC50)]:
        est = params[name]["estimate"]
        rel_err = abs(est - true_val) / (abs(true_val) + 1e-10)
        assert rel_err < 0.01, f"MCP fit: {name} rel_err={rel_err:.3e}"


def test_impl_fit_pd_model_bad_model_returns_error(tmp_path: Path) -> None:
    """Unknown model name returns status='error'."""
    csv_path = _make_emax_csv(tmp_path)
    result = impl_fit_pd_model(
        pd_dataset_path=str(csv_path),
        model_name="not_a_model",
        initial_params={"E0": 1.0},
        audit_dir=str(tmp_path / "audit"),
    )
    assert result["status"] == "error"
    assert "not_a_model" in result["error"]


def test_impl_fit_pd_model_missing_column_returns_error(tmp_path: Path) -> None:
    """CSV missing 'effect' column returns status='error'."""
    df = pd.DataFrame({"time": [1, 2], "concentration": [5.0, 3.0]})
    csv_path = tmp_path / "bad.csv"
    df.to_csv(csv_path, index=False)

    result = impl_fit_pd_model(
        pd_dataset_path=str(csv_path),
        model_name="emax",
        initial_params={"E0": 1.0, "Emax": 5.0, "EC50": 2.0},
        audit_dir=str(tmp_path / "audit"),
    )
    assert result["status"] == "error"
    assert "effect" in result["error"]


# ---------------------------------------------------------------------------
# Test 2 — simulate_pd_model
# ---------------------------------------------------------------------------


def test_impl_simulate_pd_model_emax() -> None:
    """Simulate Emax model; returned effects match formula."""
    params = {"E0": 1.0, "Emax": 10.0, "EC50": 5.0}
    conc = [0.0, 5.0, 10.0, 50.0]
    times = [0.0, 1.0, 2.0, 3.0]

    result = impl_simulate_pd_model("emax", params, times, conc)

    assert result["status"] == "ok"
    assert "effects" in result
    effects = result["effects"]
    assert len(effects) == 4

    # Check known values
    # At C=5: E = 1 + 10*5/(5+5) = 6
    assert abs(effects[1] - 6.0) < 1e-8
    # At C=0: E = 1
    assert abs(effects[0] - 1.0) < 1e-8


def test_impl_simulate_pd_model_bad_model() -> None:
    """Unknown model returns error."""
    result = impl_simulate_pd_model("bad_model", {}, [1.0], [1.0])
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Test 3 — list_pd_models
# ---------------------------------------------------------------------------


def test_impl_list_pd_models_returns_all() -> None:
    """list_pd_models returns all 10 PD models."""
    result = impl_list_pd_models()

    assert result["status"] == "ok"
    assert result["n_models"] == 10
    names = {m["name"] for m in result["models"]}
    expected = {
        "linear",
        "log_linear",
        "emax",
        "sigmoid_emax",
        "inhibitory_emax",
        "effect_compartment",
        "idr_i",
        "idr_ii",
        "idr_iii",
        "idr_iv",
    }
    assert names == expected


def test_impl_list_pd_models_has_parameter_names() -> None:
    """Each model entry includes parameter_names list."""
    result = impl_list_pd_models()
    for model in result["models"]:
        assert "parameter_names" in model
        assert len(model["parameter_names"]) > 0
        assert "requires_ode" in model
        assert "is_inhibitory" in model
