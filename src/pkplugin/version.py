"""
WinNonlin compatibility version registry.

This module owns the algorithm default-value matrix for each supported
Phoenix WinNonlin version (5.3 / 6.4 / 8.3). Every algorithm function
must accept a ``winnonlin_version`` argument and consult ``DEFAULTS``
to resolve any option the caller did not explicitly set.

Refs:
- docs/04-winnonlin-version-matrix.md
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class WNVersion(str, Enum):
    """Supported Phoenix WinNonlin compatibility versions."""

    V5_3 = "5.3"
    V6_4 = "6.4"
    V8_3 = "8.3"
    LATEST = "compat-latest"

    @classmethod
    def parse(cls, value: str | "WNVersion") -> "WNVersion":
        if isinstance(value, WNVersion):
            return value
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported winnonlin_version={value!r}. "
                f"Use one of {[v.value for v in cls]}."
            ) from exc


# Default option matrix per WinNonlin version.
# Any value that is None means "not yet validated against the manual" — implementations
# should treat None as 'use 6.4 default' until a TODO in docs/04 is resolved.
DEFAULTS: dict[WNVersion, dict[str, Any]] = {
    WNVersion.V5_3: {
        "auc_method": "linear",  # 📋 TODO confirm 5.3 GUI default
        "lambda_z_method": "best_fit",
        "lambda_z_tolerance": 0.0001,
        "lambda_z_min_points": 3,
        "c0_method": "observed",
        "output_pred_variants": False,
        "bloq_policy": {
            "pre_dose": "zero",
            "up_leading": "zero",
            "embedded": "missing",
            "trailing": "exclude",
        },
        "span_ratio_min": 1.5,
        "comp_weighting_default": "uniform",
    },
    WNVersion.V6_4: {
        "auc_method": "linear_up_log_down",
        "lambda_z_method": "best_fit",
        "lambda_z_tolerance": 0.0001,
        "lambda_z_min_points": 3,
        "c0_method": "log_back_extrap",
        "output_pred_variants": True,
        "bloq_policy": {
            "pre_dose": "zero",
            "up_leading": "zero",
            "embedded": "missing",
            "trailing": "exclude",
        },
        "span_ratio_min": 1.5,
        "comp_weighting_default": "1_over_y_squared",
    },
    WNVersion.V8_3: {
        "auc_method": "linear_up_log_down",
        "lambda_z_method": "best_fit",
        "lambda_z_tolerance": 0.0001,
        "lambda_z_min_points": 3,
        "c0_method": "log_back_extrap",
        "output_pred_variants": True,
        "bloq_policy": {
            "pre_dose": "zero",
            "up_leading": "zero",
            "embedded": "missing",
            "trailing": "exclude",
        },
        "span_ratio_min": 1.5,
        "comp_weighting_default": "1_over_y_squared",
    },
}
# Latest defaults track 8.3.
DEFAULTS[WNVersion.LATEST] = DEFAULTS[WNVersion.V8_3]


def get_default(version: WNVersion | str, key: str) -> Any:
    """Look up a single default value for ``version``."""
    v = WNVersion.parse(version)
    if key not in DEFAULTS[v]:
        raise KeyError(
            f"No default registered for key={key!r} under version={v.value}. "
            "Add an entry to pkplugin.version.DEFAULTS and update docs/04."
        )
    return DEFAULTS[v][key]


def merge_with_defaults(
    version: WNVersion | str, overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return a copy of the version defaults with user-provided overrides applied."""
    v = WNVersion.parse(version)
    merged: dict[str, Any] = {**DEFAULTS[v]}
    if overrides:
        for key, value in overrides.items():
            if value is None:
                continue
            merged[key] = value
    merged["winnonlin_version"] = v.value
    return merged
