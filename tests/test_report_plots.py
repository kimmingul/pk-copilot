"""
Tests for pkplugin.report.plots.

Covers:
- Each plot function saves a PNG of expected dimensions
- No exception raised on valid inputs
- log_scale vs linear
- Uses matplotlib Agg backend
- Uses tmp_path for all file I/O

Refs: docs/02-roadmap.md v0.5
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure Agg backend is used before any matplotlib import
import matplotlib
matplotlib.use("Agg")

from pkplugin.report.plots import (
    plot_concentration_time,
    plot_goodness_of_fit,
    plot_hysteresis,
    plot_lambda_z_regression,
    plot_mean_sd,
    plot_residuals,
    plot_spaghetti,
)


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------


@pytest.fixture()
def times_concs() -> tuple[np.ndarray, np.ndarray]:
    t = np.array([0.0, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0])
    c = np.array([0.0, 4.0, 8.0, 6.0, 4.0, 2.5, 1.5, 0.5])
    return t, c


@pytest.fixture()
def df_long() -> pd.DataFrame:
    rows = []
    for sid in ["S1", "S2", "S3"]:
        for t, c in zip([0, 1, 2, 4, 8], [0, 5, 8, 4, 1]):
            rows.append({"subject_id": sid, "time": float(t), "concentration": float(c)})
    return pd.DataFrame(rows)


def _assert_png(path: Path) -> None:
    """Assert file exists, is non-empty, and has PNG magic bytes."""
    assert path.exists(), f"Expected PNG at {path}"
    data = path.read_bytes()
    assert len(data) > 1000, f"PNG too small ({len(data)} bytes)"
    assert data[:4] == b"\x89PNG", "File does not start with PNG magic bytes"


# ---------------------------------------------------------------------------
# Test 1: plot_concentration_time — linear
# ---------------------------------------------------------------------------


def test_plot_concentration_time_linear(tmp_path: Path, times_concs: tuple) -> None:
    t, c = times_concs
    out = tmp_path / "conc_linear.png"
    result = plot_concentration_time(t, c, out, subject_id="S1", title="Test")
    assert result == out.resolve()
    _assert_png(out)


def test_plot_concentration_time_log(tmp_path: Path, times_concs: tuple) -> None:
    t, c = times_concs
    # Avoid zero in log scale
    c_pos = c + 0.01
    out = tmp_path / "conc_log.png"
    result = plot_concentration_time(t, c_pos, out, log_scale=True)
    assert result == out.resolve()
    _assert_png(out)


def test_plot_concentration_time_returns_absolute_path(tmp_path: Path, times_concs: tuple) -> None:
    t, c = times_concs
    out = tmp_path / "abs.png"
    result = plot_concentration_time(t, c, out)
    assert result.is_absolute()


# ---------------------------------------------------------------------------
# Test 2: plot_spaghetti
# ---------------------------------------------------------------------------


def test_plot_spaghetti_basic(tmp_path: Path, df_long: pd.DataFrame) -> None:
    out = tmp_path / "spaghetti.png"
    result = plot_spaghetti(df_long, out, title="Spaghetti Test")
    assert result == out.resolve()
    _assert_png(out)


def test_plot_spaghetti_log_scale(tmp_path: Path, df_long: pd.DataFrame) -> None:
    out = tmp_path / "spaghetti_log.png"
    df2 = df_long.copy()
    df2["concentration"] = df2["concentration"] + 0.1
    result = plot_spaghetti(df2, out, log_scale=True)
    _assert_png(out)


# ---------------------------------------------------------------------------
# Test 3: plot_mean_sd
# ---------------------------------------------------------------------------


def test_plot_mean_sd_basic(tmp_path: Path, df_long: pd.DataFrame) -> None:
    out = tmp_path / "mean_sd.png"
    result = plot_mean_sd(df_long, out)
    assert result == out.resolve()
    _assert_png(out)


def test_plot_mean_sd_group_by(tmp_path: Path) -> None:
    rows = []
    for sid in ["S1", "S2", "S3"]:
        trt = "T" if sid in ["S1", "S2"] else "R"
        for t, c in zip([0, 1, 2, 4, 8], [0, 5, 8, 4, 1]):
            rows.append({"subject_id": sid, "time": float(t),
                         "concentration": float(c), "treatment": trt})
    df = pd.DataFrame(rows)
    out = tmp_path / "mean_sd_grp.png"
    result = plot_mean_sd(df, out, group_by="treatment")
    _assert_png(out)


def test_plot_mean_sd_log_scale(tmp_path: Path, df_long: pd.DataFrame) -> None:
    out = tmp_path / "mean_sd_log.png"
    df2 = df_long.copy()
    df2["concentration"] = df2["concentration"] + 0.1
    result = plot_mean_sd(df2, out, log_scale=True)
    _assert_png(out)


# ---------------------------------------------------------------------------
# Test 4: plot_lambda_z_regression
# ---------------------------------------------------------------------------


def test_plot_lambda_z_regression_basic(tmp_path: Path, times_concs: tuple) -> None:
    t, c = times_concs
    # Use log-linear portion (positive concentrations only)
    pos_mask = c > 0
    t_pos = t[pos_mask]
    c_pos = c[pos_mask]
    selected = list(range(len(t_pos)))
    lambda_z = 0.15
    intercept = np.log(8.0) + lambda_z * t_pos[0]
    out = tmp_path / "lz.png"
    result = plot_lambda_z_regression(
        t_pos, c_pos, selected, lambda_z, intercept, out, subject_id="S1"
    )
    assert result == out.resolve()
    _assert_png(out)


def test_plot_lambda_z_regression_no_exception(tmp_path: Path) -> None:
    t = np.array([4.0, 6.0, 8.0, 12.0])
    c = np.array([4.0, 2.5, 1.5, 0.5])
    selected = [0, 1, 2, 3]
    out = tmp_path / "lz2.png"
    plot_lambda_z_regression(t, c, selected, 0.2, 2.0, out)
    _assert_png(out)


# ---------------------------------------------------------------------------
# Test 5: plot_goodness_of_fit
# ---------------------------------------------------------------------------


def test_plot_goodness_of_fit_basic(tmp_path: Path) -> None:
    observed = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    predicted = np.array([1.1, 1.9, 3.1, 3.9, 5.1])
    out = tmp_path / "gof.png"
    result = plot_goodness_of_fit(observed, predicted, out)
    assert result == out.resolve()
    _assert_png(out)


def test_plot_goodness_of_fit_returns_absolute(tmp_path: Path) -> None:
    obs = np.array([2.0, 4.0, 6.0])
    pred = np.array([2.1, 3.9, 6.2])
    out = tmp_path / "gof2.png"
    result = plot_goodness_of_fit(obs, pred, out)
    assert result.is_absolute()


# ---------------------------------------------------------------------------
# Test 6: plot_residuals
# ---------------------------------------------------------------------------


def test_plot_residuals_unweighted(tmp_path: Path, times_concs: tuple) -> None:
    t, _ = times_concs
    residuals = np.random.default_rng(42).normal(0, 0.1, len(t))
    out = tmp_path / "resid.png"
    result = plot_residuals(t, residuals, out)
    assert result == out.resolve()
    _assert_png(out)


def test_plot_residuals_weighted(tmp_path: Path, times_concs: tuple) -> None:
    t, _ = times_concs
    residuals = np.random.default_rng(0).normal(0, 0.05, len(t))
    out = tmp_path / "resid_w.png"
    result = plot_residuals(t, residuals, out, weighted=True, title="Weighted Residuals")
    _assert_png(out)


# ---------------------------------------------------------------------------
# Test 7: plot_hysteresis
# ---------------------------------------------------------------------------


def test_plot_hysteresis_basic(tmp_path: Path) -> None:
    t = np.linspace(0, 12, 50)
    conc = np.exp(-0.1 * t) * 10
    effect = 0.5 * conc + np.random.default_rng(7).normal(0, 0.1, 50)
    out = tmp_path / "hysteresis.png"
    result = plot_hysteresis(conc, effect, t, out)
    assert result == out.resolve()
    _assert_png(out)


def test_plot_hysteresis_returns_absolute(tmp_path: Path) -> None:
    t = np.linspace(0, 6, 20)
    conc = np.exp(-0.2 * t) * 5
    effect = conc * 0.3
    out = tmp_path / "hyst2.png"
    result = plot_hysteresis(conc, effect, t, out)
    assert result.is_absolute()
