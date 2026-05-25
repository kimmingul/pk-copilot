"""Tests for pkplugin.cdisc.validate — Pinnacle21-style ADaM checks.

Covers:
- Missing required columns flagged as ERROR
- Unknown PARAMCD flagged as ERROR
- Valid frame produces no errors
- USUBJID format warning when not matching <STUDYID>-<SUBJID>
- AVAL string flagged as ERROR
- ADTM non-ISO 8601 flagged as WARNING

Refs: docs/09-cdisc-support.md §9.2
"""

from __future__ import annotations

import pandas as pd
import pytest

from pkplugin.cdisc.validate import validate_adpc, validate_adpp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_adpp_row(
    paramcd: str = "CMAX",
    usubjid: str = "STUDY01-001-001",
    aval: float = 24.3,
) -> dict[str, object]:
    return {
        "STUDYID": "STUDY01",
        "USUBJID": usubjid,
        "PARAMCD": paramcd,
        "AVAL": aval,
        "AVALU": "ng/mL",
        "PPCAT": "NON-COMPARTMENTAL",
    }


def _valid_adpc_row(
    paramcd: str = "DRUG1PC",
    usubjid: str = "STUDY01-001-001",
    aval: float = 18.7,
) -> dict[str, object]:
    return {
        "STUDYID": "STUDY01",
        "USUBJID": usubjid,
        "PARAMCD": paramcd,
        "AVAL": aval,
        "AVALU": "ng/mL",
        "ADTM": "2024-03-01T08:30:00",
    }


# ---------------------------------------------------------------------------
# validate_adpp
# ---------------------------------------------------------------------------


class TestValidateAdpp:
    def test_valid_frame_passes(self) -> None:
        df = pd.DataFrame([_valid_adpp_row()])
        issues = validate_adpp(df)
        errors = [i for i in issues if i["severity"] == "ERROR"]
        assert len(errors) == 0

    def test_missing_required_columns_flagged_error(self) -> None:
        # Remove PARAMCD
        df = pd.DataFrame([{"STUDYID": "STUDY01", "USUBJID": "STUDY01-001", "AVAL": 1.0, "AVALU": "ng/mL"}])
        issues = validate_adpp(df)
        errors = [i for i in issues if i["severity"] == "ERROR"]
        assert any("PPCAT" in i["message"] or "missing" in i["message"].lower() for i in errors)

    def test_unknown_paramcd_flagged_error(self) -> None:
        df = pd.DataFrame([_valid_adpp_row(paramcd="XXXXUNKNOWN")])
        issues = validate_adpp(df)
        errors = [i for i in issues if i["severity"] == "ERROR" and "PARAMCD" in i.get("column", "")]
        assert len(errors) >= 1

    def test_aval_string_flagged_error(self) -> None:
        row = _valid_adpp_row()
        row["AVAL"] = "not_a_number"  # type: ignore[assignment]
        df = pd.DataFrame([row])
        issues = validate_adpp(df)
        errors = [i for i in issues if i["severity"] == "ERROR" and i.get("column") == "AVAL"]
        assert len(errors) >= 1

    def test_bad_usubjid_format_warns(self) -> None:
        df = pd.DataFrame([_valid_adpp_row(usubjid="BADFORMAT")])
        issues = validate_adpp(df)
        warnings = [i for i in issues if i["severity"] == "WARNING" and "USUBJID" in i.get("column", "")]
        assert len(warnings) >= 1

    def test_empty_dataframe_errors_on_required_cols(self) -> None:
        df = pd.DataFrame()
        issues = validate_adpp(df)
        errors = [i for i in issues if i["severity"] == "ERROR"]
        assert len(errors) >= 1


# ---------------------------------------------------------------------------
# validate_adpc
# ---------------------------------------------------------------------------


class TestValidateAdpc:
    def test_valid_frame_passes(self) -> None:
        df = pd.DataFrame([_valid_adpc_row()])
        issues = validate_adpc(df)
        errors = [i for i in issues if i["severity"] == "ERROR"]
        assert len(errors) == 0

    def test_missing_required_columns_flagged_error(self) -> None:
        df = pd.DataFrame([{"STUDYID": "STUDY01"}])
        issues = validate_adpc(df)
        errors = [i for i in issues if i["severity"] == "ERROR"]
        assert len(errors) >= 1

    def test_aval_string_flagged_error(self) -> None:
        row = _valid_adpc_row()
        row["AVAL"] = "non_numeric"  # type: ignore[assignment]
        df = pd.DataFrame([row])
        issues = validate_adpc(df)
        errors = [i for i in issues if i["severity"] == "ERROR" and i.get("column") == "AVAL"]
        assert len(errors) >= 1

    def test_bad_adtm_format_warns(self) -> None:
        row = _valid_adpc_row()
        row["ADTM"] = "not-a-date"
        df = pd.DataFrame([row])
        issues = validate_adpc(df)
        warnings = [i for i in issues if i["severity"] == "WARNING" and "ADTM" in i.get("column", "")]
        assert len(warnings) >= 1

    def test_concentration_paramcd_not_flagged(self) -> None:
        """ADPC PARAMCDs ending in 'PC' should not be flagged as unknown."""
        df = pd.DataFrame([_valid_adpc_row(paramcd="DRUG1PC")])
        issues = validate_adpc(df)
        paramcd_errors = [
            i for i in issues
            if i["severity"] == "ERROR" and i.get("column") == "PARAMCD"
        ]
        assert len(paramcd_errors) == 0
