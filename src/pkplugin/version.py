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
    def parse(cls, value: str | WNVersion) -> WNVersion:
        if isinstance(value, WNVersion):
            return value
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported winnonlin_version={value!r}. Use one of {[v.value for v in cls]}."
            ) from exc


# Default option matrix per WinNonlin version.
DEFAULTS: dict[WNVersion, dict[str, Any]] = {
    WNVersion.V5_3: {
        # WNL 5.3 default AUC method: Method 2 "Linear trapezoidal rule (Linear interpolation)".
        # Ref: WNL 5.3 User's Guide NCA METHOD command ref (METHOD 2 = default) and NCA
        # Settings tab description. "linear_up_log_down" is available but not the default.
        "auc_method": "linear",
        "lambda_z_method": "best_fit",
        # lambda_z_tolerance: confirmed 0.0001 in WNL 5.3 User's Guide ~line 6443.
        "lambda_z_tolerance": 0.0001,
        "lambda_z_min_points": 3,
        # c0_method: WNL 5.3 IV bolus C0 default is log back-extrapolation from first two
        # data points. Falls back to first observed positive y-value if slope >= 0, y-values
        # are 0, or points are outliers. Algorithm is identical to 6.4/8.3.
        # Ref: WNL 5.3 User's Guide "Insertion of initial time points" (~p.196).
        # "observed"/"log_back_extrap" are plugin-internal labels; WNL has no GUI dropdown.
        "c0_method": "log_back_extrap",
        # WNL 5.3 emits _pred variants: Clast_pred, AUCINF_pred, AUC_%Extrap_pred,
        # AUMCINF_pred, MRTINF_pred, VSS_pred — confirmed in WNL 5.3 Table B-4 (~p.512-514).
        "output_pred_variants": True,
        "bloq_policy": {
            "pre_dose": "zero",
            "up_leading": "zero",
            "embedded": "missing",
            "trailing": "exclude",
        },
        # span_ratio_min: WNL 5.3 does not have a span ratio feature. This 1.5 is a
        # plugin-internal conservative default (industry practice), not a WNL engine
        # value. Set to 0.0 to disable entirely.
        "span_ratio_min": 1.5,
        "comp_weighting_default": "uniform",
    },
    WNVersion.V6_4: {
        # WNL 6.4 default AUC method: "Linear Trapezoidal Linear Interpolation".
        # Ref: WNL 6.4 User's Guide p.22 "This is the default method".
        # "linear_up_log_down" (Linear Up Log Down) is available but not the default.
        "auc_method": "linear",
        "lambda_z_method": "best_fit",
        # lambda_z_tolerance: confirmed 0.0001 in WNL 6.4 User's Guide ~line 1870.
        "lambda_z_tolerance": 0.0001,
        "lambda_z_min_points": 3,
        # c0_method: WNL 6.4 log back-extrapolation from first two data points.
        # "observed"/"log_back_extrap" are plugin-internal labels; WNL has no GUI dropdown.
        "c0_method": "log_back_extrap",
        "output_pred_variants": True,
        "bloq_policy": {
            "pre_dose": "zero",
            "up_leading": "zero",
            "embedded": "missing",
            "trailing": "exclude",
        },
        # span_ratio_min: WNL 6.4 does not have a span ratio feature. This 1.5 is a
        # plugin-internal conservative default (industry practice), not a WNL engine
        # value. Set to 0.0 to disable entirely.
        "span_ratio_min": 1.5,
        "comp_weighting_default": "1_over_y_squared",
    },
    WNVersion.V8_3: {
        # WNL 8.3 default AUC method: "Linear Trapezoidal Linear Interpolation".
        # Ref: WNL 8.3 User's Guide "This is the default method and recommended for Drug
        # Effect Data". "linear_up_log_down" is available but not the default.
        "auc_method": "linear",
        "lambda_z_method": "best_fit",
        # lambda_z_tolerance: confirmed 0.0001 in WNL 8.3 User's Guide ~line 6053.
        "lambda_z_tolerance": 0.0001,
        "lambda_z_min_points": 3,
        # c0_method: WNL 8.3 log back-extrapolation from first two data points.
        # "observed"/"log_back_extrap" are plugin-internal labels; WNL has no GUI dropdown.
        "c0_method": "log_back_extrap",
        "output_pred_variants": True,
        "bloq_policy": {
            "pre_dose": "zero",
            "up_leading": "zero",
            "embedded": "missing",
            "trailing": "exclude",
        },
        # span_ratio_min: WNL 8.3 supports user-defined Span acceptance criterion (Rules
        # tab) but has no built-in default threshold. This 1.5 is a plugin-internal default
        # (industry practice). Users can override via acceptance_criteria config.
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
