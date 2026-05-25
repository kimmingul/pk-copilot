"""Pinnacle21-style CDISC ADaM structural validation.

Provides basic self-checks on ADPC and ADPP DataFrames, analogous to the
structural checks performed by Pinnacle21 Community validator.

Refs:
- docs/09-cdisc-support.md §9 — Validation tools
- docs/09-cdisc-support.md §9.2 — pk-copilot self-checks
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from pkplugin.cdisc.paramcd import PARAMCD_REGISTRY

# ---------------------------------------------------------------------------
# Issue severity levels
# ---------------------------------------------------------------------------

_SEVERITY_ERROR = "ERROR"
_SEVERITY_WARNING = "WARNING"

# Regex for USUBJID format: <STUDYID>-<SUBJID> (two or more hyphen-separated segments)
_USUBJID_RE = re.compile(r"^[A-Za-z0-9]+-[A-Za-z0-9]")

# ISO 8601 datetime: minimal pattern
_ISO8601_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z)?)?$")

# Required columns for ADPC and ADPP
_ADPC_REQUIRED = {"STUDYID", "USUBJID", "PARAMCD", "AVAL", "AVALU"}
_ADPP_REQUIRED = {"STUDYID", "USUBJID", "PARAMCD", "AVAL", "AVALU", "PPCAT"}


def _issue(
    severity: str,
    rule: str,
    message: str,
    row_index: int | None = None,
    column: str | None = None,
    value: Any = None,
) -> dict[str, Any]:
    """Build an issue dict."""
    out: dict[str, Any] = {
        "severity": severity,
        "rule": rule,
        "message": message,
    }
    if row_index is not None:
        out["row"] = row_index
    if column is not None:
        out["column"] = column
    if value is not None:
        out["value"] = str(value)
    return out


# ---------------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------------


def _check_required_columns(
    df: pd.DataFrame, required: set[str], domain: str
) -> list[dict[str, Any]]:
    """Check that all required columns are present."""
    issues: list[dict[str, Any]] = []
    missing = [c for c in sorted(required) if c not in df.columns]
    if missing:
        issues.append(
            _issue(
                _SEVERITY_ERROR,
                f"{domain}-001",
                f"Required columns missing from {domain}: {missing}",
            )
        )
    return issues


def _check_usubjid_format(df: pd.DataFrame, domain: str) -> list[dict[str, Any]]:
    """Warn when USUBJID does not match <STUDYID>-<SUBJID> pattern."""
    if "USUBJID" not in df.columns:
        return []
    issues: list[dict[str, Any]] = []
    for i, val in df["USUBJID"].items():
        val_str = str(val).strip() if pd.notna(val) else ""
        if val_str and not _USUBJID_RE.match(val_str):
            issues.append(
                _issue(
                    _SEVERITY_WARNING,
                    f"{domain}-002",
                    "USUBJID does not match expected <STUDYID>-<SUBJID> format",
                    row_index=int(str(i)),
                    column="USUBJID",
                    value=val_str,
                )
            )
    return issues


def _check_paramcd_in_ct(df: pd.DataFrame, domain: str) -> list[dict[str, Any]]:
    """Error when PARAMCD values are not in the CDISC CT registry."""
    if "PARAMCD" not in df.columns:
        return []
    issues: list[dict[str, Any]] = []
    for i, val in df["PARAMCD"].items():
        val_str = str(val).strip() if pd.notna(val) else ""
        if not val_str:
            continue
        # ADPC PARAMCDs may be analyte-specific (e.g. "DRUG1PC") — skip those
        # that look like concentration PARAMCDs (ending in "PC")
        if domain == "ADPC" and val_str.endswith("PC"):
            continue
        if val_str not in PARAMCD_REGISTRY:
            issues.append(
                _issue(
                    _SEVERITY_ERROR,
                    f"{domain}-003",
                    f"PARAMCD '{val_str}' not found in CDISC NCA CT registry",
                    row_index=int(str(i)),
                    column="PARAMCD",
                    value=val_str,
                )
            )
    return issues


def _check_aval_numeric(df: pd.DataFrame, domain: str) -> list[dict[str, Any]]:
    """Error when AVAL column contains non-numeric values."""
    if "AVAL" not in df.columns:
        return []
    issues: list[dict[str, Any]] = []
    for i, val in df["AVAL"].items():
        if pd.isna(val):
            continue
        if isinstance(val, str):
            try:
                float(val)
            except ValueError:
                issues.append(
                    _issue(
                        _SEVERITY_ERROR,
                        f"{domain}-004",
                        "AVAL must be numeric, got string value",
                        row_index=int(str(i)),
                        column="AVAL",
                        value=val,
                    )
                )
    return issues


def _check_adtm_iso8601(df: pd.DataFrame, domain: str) -> list[dict[str, Any]]:
    """Warn when ADTM values are not valid ISO 8601 datetime strings."""
    if "ADTM" not in df.columns:
        return []
    issues: list[dict[str, Any]] = []
    for i, val in df["ADTM"].items():
        val_str = str(val).strip() if pd.notna(val) else ""
        if not val_str or val_str in ("nan", "None", ""):
            continue
        if not _ISO8601_DT_RE.match(val_str):
            issues.append(
                _issue(
                    _SEVERITY_WARNING,
                    f"{domain}-005",
                    "ADTM value does not match ISO 8601 datetime format",
                    row_index=int(str(i)),
                    column="ADTM",
                    value=val_str,
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Domain-specific checks
# ---------------------------------------------------------------------------


def validate_adpc(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Run basic structural checks on an ADPC DataFrame.

    Checks performed:
    1. Required columns present (ERROR)
    2. USUBJID format matches <STUDYID>-<SUBJID> (WARNING)
    3. PARAMCD in CT registry — skips analyte-specific PC codes (ERROR)
    4. AVAL is numeric (ERROR)
    5. ADTM is ISO 8601 (WARNING)

    Args:
        df: ADPC DataFrame to validate.

    Returns:
        List of issue dicts, each with keys: ``severity``, ``rule``,
        ``message``, and optionally ``row``, ``column``, ``value``.
        Empty list means no issues found.
    """
    issues: list[dict[str, Any]] = []
    issues.extend(_check_required_columns(df, _ADPC_REQUIRED, "ADPC"))
    issues.extend(_check_usubjid_format(df, "ADPC"))
    issues.extend(_check_paramcd_in_ct(df, "ADPC"))
    issues.extend(_check_aval_numeric(df, "ADPC"))
    issues.extend(_check_adtm_iso8601(df, "ADPC"))
    return issues


def validate_adpp(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Run basic structural checks on an ADPP DataFrame.

    Checks performed:
    1. Required columns present (ERROR)
    2. USUBJID format matches <STUDYID>-<SUBJID> (WARNING)
    3. PARAMCD in CT registry (ERROR)
    4. AVAL is numeric (ERROR)

    Args:
        df: ADPP DataFrame to validate.

    Returns:
        List of issue dicts. Empty list means no issues found.
    """
    issues: list[dict[str, Any]] = []
    issues.extend(_check_required_columns(df, _ADPP_REQUIRED, "ADPP"))
    issues.extend(_check_usubjid_format(df, "ADPP"))
    issues.extend(_check_paramcd_in_ct(df, "ADPP"))
    issues.extend(_check_aval_numeric(df, "ADPP"))
    return issues
