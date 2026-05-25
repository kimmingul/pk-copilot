"""
Report plots module for pk-copilot v0.5.

All plots use matplotlib Agg backend (no display), figsize=(8,6), dpi=120.
Saves PNG files and returns absolute Path objects.

Refs: docs/02-roadmap.md v0.5
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_path(output_path: str | Path) -> Path:
    return Path(output_path).resolve()


def _apply_log_scale(ax: matplotlib.axes.Axes, log_scale: bool) -> None:
    if log_scale:
        ax.set_yscale("log")


# ---------------------------------------------------------------------------
# Single-subject concentration-time
# ---------------------------------------------------------------------------


def plot_concentration_time(
    times: NDArray[np.float64],
    concentrations: NDArray[np.float64],
    output_path: str | Path,
    *,
    log_scale: bool = False,
    title: str = "",
    subject_id: str = "",
) -> Path:
    """Single-subject concentration-time plot. Returns the saved path."""
    out = _resolve_path(output_path)

    fig, ax = plt.subplots(figsize=(8, 6), dpi=120)
    ax.plot(times, concentrations, marker="o", linewidth=1.5, markersize=5)
    _apply_log_scale(ax, log_scale)
    ax.set_xlabel("Time (h)")
    ax.set_ylabel("Concentration (ng/mL)")
    display_title = title or (
        f"Subject {subject_id}" if subject_id else "Concentration-Time Profile"
    )
    ax.set_title(display_title)
    ax.grid(True, alpha=0.3)
    if subject_id:
        ax.text(
            0.98,
            0.98,
            f"Subject: {subject_id}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=8,
            color="gray",
        )
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Multi-subject spaghetti plot
# ---------------------------------------------------------------------------


def plot_spaghetti(
    df_long: pd.DataFrame,
    output_path: str | Path,
    *,
    log_scale: bool = False,
    title: str = "Concentration-Time Profile",
) -> Path:
    """Multi-subject spaghetti plot, color by subject."""
    out = _resolve_path(output_path)

    fig, ax = plt.subplots(figsize=(8, 6), dpi=120)

    if not df_long.empty and "subject_id" in df_long.columns:
        subjects = df_long["subject_id"].unique()
        cmap = plt.get_cmap("tab20")
        for i, sid in enumerate(subjects):
            sub = df_long[df_long["subject_id"] == sid].sort_values("time")
            color = cmap(i % 20)
            ax.plot(
                sub["time"],
                sub["concentration"],
                marker="o",
                linewidth=1.0,
                markersize=3,
                color=color,
                alpha=0.7,
                label=str(sid),
            )
        if len(subjects) <= 12:
            ax.legend(title="Subject", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=7)

    _apply_log_scale(ax, log_scale)
    ax.set_xlabel("Time (h)")
    ax.set_ylabel("Concentration (ng/mL)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Mean ± SD plot
# ---------------------------------------------------------------------------


def plot_mean_sd(
    df_long: pd.DataFrame,
    output_path: str | Path,
    *,
    log_scale: bool = False,
    title: str = "Mean ± SD",
    group_by: str | None = None,
) -> Path:
    """Mean ± SD over time, optionally grouped by treatment."""
    out = _resolve_path(output_path)

    fig, ax = plt.subplots(figsize=(8, 6), dpi=120)

    if not df_long.empty and "time" in df_long.columns and "concentration" in df_long.columns:
        group_col = group_by if (group_by is not None and group_by in df_long.columns) else None
        groups = df_long[group_col].unique() if group_col else [None]
        cmap = plt.get_cmap("tab10")

        for i, grp in enumerate(groups):
            if group_col is not None and grp is not None:
                sub = df_long[df_long[group_col] == grp]
                label = str(grp)
            else:
                sub = df_long
                label = "All"

            color = cmap(i % 10)
            agg = sub.groupby("time")["concentration"].agg(["mean", "std"]).reset_index()
            agg.columns = ["time", "mean", "sd"]
            agg["sd"] = agg["sd"].fillna(0.0)

            ax.plot(
                agg["time"],
                agg["mean"],
                marker="o",
                linewidth=1.5,
                markersize=5,
                color=color,
                label=label,
            )
            ax.fill_between(
                agg["time"],
                agg["mean"] - agg["sd"],
                agg["mean"] + agg["sd"],
                alpha=0.2,
                color=color,
            )

        if group_col is not None:
            ax.legend(title=group_col, fontsize=8)

    _apply_log_scale(ax, log_scale)
    ax.set_xlabel("Time (h)")
    ax.set_ylabel("Concentration (ng/mL)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Lambda_z regression plot
# ---------------------------------------------------------------------------


def plot_lambda_z_regression(
    times: NDArray[np.float64],
    concentrations: NDArray[np.float64],
    selected_indices: list[int],
    lambda_z: float,
    intercept: float,
    output_path: str | Path,
    *,
    subject_id: str = "",
) -> Path:
    """Log-scale plot with terminal regression line highlighted."""
    out = _resolve_path(output_path)

    fig, ax = plt.subplots(figsize=(8, 6), dpi=120)

    # Filter out non-positive concentrations for log scale
    valid = concentrations > 0
    if np.any(valid):
        ax.plot(
            times[valid],
            concentrations[valid],
            "o",
            color="steelblue",
            markersize=5,
            label="All data",
        )

    # Highlight selected points
    if selected_indices:
        sel_idx = np.array(selected_indices)
        valid_sel = sel_idx[concentrations[sel_idx] > 0]
        if len(valid_sel) > 0:
            ax.plot(
                times[valid_sel],
                concentrations[valid_sel],
                "o",
                color="darkorange",
                markersize=7,
                zorder=5,
                label="Selected (λz)",
            )

            # Draw regression line over the selected range
            t_min = times[valid_sel].min()
            t_max = times[valid_sel].max()
            t_line = np.linspace(t_min, t_max, 100)
            # Log-linear regression: ln(C) = intercept - lambda_z * t
            c_line = np.exp(intercept - lambda_z * t_line)
            ax.plot(t_line, c_line, "--", color="red", linewidth=1.5, label=f"λz = {lambda_z:.4f}")

    ax.set_yscale("log")
    ax.set_xlabel("Time (h)")
    ax.set_ylabel("Concentration (ng/mL)")
    title = f"λz Regression{' — Subject ' + subject_id if subject_id else ''}"
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, which="both")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Goodness of fit
# ---------------------------------------------------------------------------


def plot_goodness_of_fit(
    observed: NDArray[np.float64],
    predicted: NDArray[np.float64],
    output_path: str | Path,
    *,
    title: str = "Observed vs Predicted",
) -> Path:
    """GoF scatter with identity line."""
    out = _resolve_path(output_path)

    fig, ax = plt.subplots(figsize=(8, 6), dpi=120)
    ax.scatter(predicted, observed, alpha=0.7, s=30, color="steelblue")

    # Identity line
    all_vals = np.concatenate([observed[np.isfinite(observed)], predicted[np.isfinite(predicted)]])
    if len(all_vals) > 0:
        vmin, vmax = all_vals.min(), all_vals.max()
        margin = (vmax - vmin) * 0.05
        line_range = np.array([vmin - margin, vmax + margin])
        ax.plot(line_range, line_range, "r--", linewidth=1.5, label="Identity")

    ax.set_xlabel("Predicted")
    ax.set_ylabel("Observed")
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Residuals vs time
# ---------------------------------------------------------------------------


def plot_residuals(
    times: NDArray[np.float64],
    residuals: NDArray[np.float64],
    output_path: str | Path,
    *,
    weighted: bool = False,
    title: str = "Residuals",
) -> Path:
    """Residuals vs time."""
    out = _resolve_path(output_path)

    fig, ax = plt.subplots(figsize=(8, 6), dpi=120)
    ax.scatter(times, residuals, alpha=0.7, s=30, color="steelblue")
    ax.axhline(0, color="red", linewidth=1.5, linestyle="--")
    ax.set_xlabel("Time (h)")
    ylabel = "Weighted Residuals" if weighted else "Residuals"
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# PK/PD Hysteresis
# ---------------------------------------------------------------------------


def plot_hysteresis(
    concentrations: NDArray[np.float64],
    effects: NDArray[np.float64],
    times: NDArray[np.float64],
    output_path: str | Path,
    *,
    title: str = "PK/PD Hysteresis",
) -> Path:
    """Concentration vs effect loop with time-direction arrows."""
    out = _resolve_path(output_path)

    fig, ax = plt.subplots(figsize=(8, 6), dpi=120)

    # Plot the loop
    ax.plot(concentrations, effects, color="steelblue", linewidth=1.5, alpha=0.8)
    ax.scatter(concentrations, effects, c=times, cmap="viridis", s=20, zorder=5)

    # Add arrows at ~25% and ~75% of the time series to show direction
    n = len(times)
    if n >= 4:
        for idx in (n // 4, 3 * n // 4):
            if idx + 1 < n:
                dx = concentrations[idx + 1] - concentrations[idx]
                dy = effects[idx + 1] - effects[idx]
                if abs(dx) + abs(dy) > 1e-10:
                    ax.annotate(
                        "",
                        xy=(concentrations[idx + 1], effects[idx + 1]),
                        xytext=(concentrations[idx], effects[idx]),
                        arrowprops=dict(arrowstyle="->", color="darkorange", lw=1.5),
                    )

    # Mark start and end
    ax.scatter(concentrations[0], effects[0], color="green", s=60, zorder=10, label="Start")
    ax.scatter(concentrations[-1], effects[-1], color="red", s=60, zorder=10, label="End")

    import matplotlib.colors as _mcolors

    sm = plt.cm.ScalarMappable(
        cmap="viridis", norm=_mcolors.Normalize(vmin=times.min(), vmax=times.max())
    )
    sm.set_array([])
    fig.colorbar(sm, ax=ax, label="Time (h)")

    ax.set_xlabel("Concentration (ng/mL)")
    ax.set_ylabel("Effect")
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out
