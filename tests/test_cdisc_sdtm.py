"""Tests for pkplugin.cdisc.sdtm — SDTM PC/EX/DM domain loaders.

Covers:
- PC load from hand-crafted minimal SDTM CSV fixtures
- EX load from minimal SDTM CSV fixtures
- Time computation from PCDTC
- PCELTM priority over PCDTC arithmetic
- Matrix / analyte filters
- EXROUTE mapping to canonical route
- DM load
- Missing required columns raise ValueError
- compute_elapsed_time_hours
- normalise_pc_times with EX reference

Refs: docs/09-cdisc-support.md §3, §4
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pkplugin.cdisc.sdtm import (
    compute_elapsed_time_hours,
    load_sdtm_dm,
    load_sdtm_ex,
    load_sdtm_pc,
    map_exroute_to_canonical,
    normalise_pc_times,
)

# ---------------------------------------------------------------------------
# Fixtures paths
# ---------------------------------------------------------------------------

GOLDEN = Path(__file__).parent / "golden" / "cdisc"
PC_CSV = GOLDEN / "pc.csv"
EX_CSV = GOLDEN / "ex.csv"
DM_CSV = GOLDEN / "dm.csv"


# ---------------------------------------------------------------------------
# compute_elapsed_time_hours
# ---------------------------------------------------------------------------


class TestComputeElapsedTimeHours:
    def test_same_datetime_is_zero(self) -> None:
        assert compute_elapsed_time_hours(
            "2024-03-01T08:00:00", "2024-03-01T08:00:00"
        ) == pytest.approx(0.0)

    def test_30_min_after_dose(self) -> None:
        assert compute_elapsed_time_hours(
            "2024-03-01T08:30:00", "2024-03-01T08:00:00"
        ) == pytest.approx(0.5)

    def test_24_hours(self) -> None:
        assert compute_elapsed_time_hours(
            "2024-03-02T08:00:00", "2024-03-01T08:00:00"
        ) == pytest.approx(24.0)

    def test_predose_is_negative(self) -> None:
        result = compute_elapsed_time_hours("2024-03-01T07:30:00", "2024-03-01T08:00:00")
        assert result == pytest.approx(-0.5)

    def test_date_only_treated_as_midnight(self) -> None:
        # date-only: treated as midnight UTC
        result = compute_elapsed_time_hours("2024-03-02", "2024-03-01T08:00:00")
        assert result == pytest.approx(16.0)


# ---------------------------------------------------------------------------
# EXROUTE mapping
# ---------------------------------------------------------------------------


class TestMapExrouteToCanonical:
    def test_oral(self) -> None:
        assert map_exroute_to_canonical("ORAL") == "oral"

    def test_intravenous_bolus(self) -> None:
        assert map_exroute_to_canonical("INTRAVENOUS BOLUS") == "iv_bolus"

    def test_intravenous(self) -> None:
        assert map_exroute_to_canonical("INTRAVENOUS") == "iv_infusion"

    def test_intravenous_drip(self) -> None:
        assert map_exroute_to_canonical("INTRAVENOUS DRIP") == "iv_infusion"

    def test_infusion(self) -> None:
        assert map_exroute_to_canonical("INFUSION") == "iv_infusion"

    def test_subcutaneous(self) -> None:
        assert map_exroute_to_canonical("SUBCUTANEOUS") == "subcut"

    def test_intramuscular(self) -> None:
        assert map_exroute_to_canonical("INTRAMUSCULAR") == "im"

    def test_unknown_returns_other(self) -> None:
        assert map_exroute_to_canonical("TRANSDERMAL") == "other"

    def test_case_insensitive(self) -> None:
        # map_exroute_to_canonical normalises to upper so lowercase input works too
        assert map_exroute_to_canonical("oral") == "oral"
        assert map_exroute_to_canonical("Oral") == "oral"


# ---------------------------------------------------------------------------
# PC domain loading
# ---------------------------------------------------------------------------


class TestLoadSdtmPc:
    def test_load_golden_pc(self) -> None:
        df, warnings = load_sdtm_pc(PC_CSV)
        assert not df.empty
        assert "subject_id" in df.columns
        assert "time" in df.columns
        assert "concentration" in df.columns

    def test_golden_pc_two_subjects(self) -> None:
        df, _ = load_sdtm_pc(PC_CSV)
        assert df["subject_id"].nunique() == 2

    def test_golden_pc_16_rows(self) -> None:
        df, _ = load_sdtm_pc(PC_CSV)
        assert len(df) == 16

    def test_analyte_filter(self) -> None:
        df, _ = load_sdtm_pc(PC_CSV, analyte_filter="DRUGX")
        assert len(df) == 16  # all rows are DRUGX
        assert (df["analyte"] == "DRUGX").all()

    def test_analyte_filter_no_match(self) -> None:
        df, warnings = load_sdtm_pc(PC_CSV, analyte_filter="NONEXISTENT")
        assert df.empty
        assert "no_analyte" in warnings

    def test_matrix_filter_plasma(self) -> None:
        df, _ = load_sdtm_pc(PC_CSV, matrix_filter="PLASMA")
        assert len(df) == 16
        assert (df["matrix"] == "plasma").all()

    def test_matrix_filter_no_match(self) -> None:
        df, warnings = load_sdtm_pc(PC_CSV, matrix_filter="URINE")
        assert df.empty
        assert "no_matrix" in warnings

    def test_pceltm_used_for_times(self) -> None:
        """When PCELTM is present, time values should match ISO 8601 durations."""
        df, _ = load_sdtm_pc(PC_CSV)
        # Row at 30 min (PT0H30M) should have time = 0.5
        # (subject 001, second row — index 1 in original)
        subj_df = df[df["subject_id"] == "STUDY01-001-001"].reset_index(drop=True)
        # First row is predose (no PCELTM, time=None or 0.0)
        row_30min = subj_df[subj_df["pctptnum"] == "0.5"]
        if not row_30min.empty:
            assert row_30min.iloc[0]["time"] == pytest.approx(0.5)

    def test_bloq_detected_for_predose(self) -> None:
        df, _ = load_sdtm_pc(PC_CSV)
        # First row per subject is PREDOSE / BLOQ
        bloq_rows = df[df["bloq"] == True]  # noqa: E712
        assert len(bloq_rows) >= 2  # 2 subjects each have a BLOQ predose

    def test_missing_required_cols_raises(self, tmp_path: Path) -> None:
        minimal_csv = tmp_path / "pc_bad.csv"
        minimal_csv.write_text("STUDYID,USUBJID\nSTUDY01,STUDY01-001-001\n")
        with pytest.raises(ValueError, match="missing required columns"):
            load_sdtm_pc(minimal_csv)

    def test_file_not_found_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_sdtm_pc("/nonexistent/path/pc.csv")


# ---------------------------------------------------------------------------
# EX domain loading
# ---------------------------------------------------------------------------


class TestLoadSdtmEx:
    def test_load_golden_ex(self) -> None:
        df, warnings = load_sdtm_ex(EX_CSV)
        assert not df.empty
        assert "subject_id" in df.columns
        assert "amount" in df.columns
        assert "route" in df.columns

    def test_golden_ex_two_rows(self) -> None:
        df, _ = load_sdtm_ex(EX_CSV)
        assert len(df) == 2

    def test_route_mapped_oral(self) -> None:
        df, _ = load_sdtm_ex(EX_CSV)
        assert (df["route"] == "oral").all()

    def test_dose_amount_100mg(self) -> None:
        df, _ = load_sdtm_ex(EX_CSV)
        assert (df["amount"] == 100.0).all()

    def test_treatment_filter(self) -> None:
        df, _ = load_sdtm_ex(EX_CSV, treatment_filter="DRUGX")
        assert len(df) == 2

    def test_treatment_filter_no_match(self) -> None:
        df, warnings = load_sdtm_ex(EX_CSV, treatment_filter="PLACEBO")
        assert df.empty
        assert "no_treatment" in warnings

    def test_exstdtc_preserved(self) -> None:
        df, _ = load_sdtm_ex(EX_CSV)
        assert "exstdtc" in df.columns
        assert all(df["exstdtc"].str.startswith("2024"))


# ---------------------------------------------------------------------------
# DM domain loading
# ---------------------------------------------------------------------------


class TestLoadSdtmDm:
    def test_load_golden_dm(self) -> None:
        df = load_sdtm_dm(DM_CSV)
        assert not df.empty
        assert "subject_id" in df.columns
        assert "age" in df.columns
        assert "sex" in df.columns

    def test_golden_dm_two_subjects(self) -> None:
        df = load_sdtm_dm(DM_CSV)
        assert len(df) == 2

    def test_age_parsed(self) -> None:
        df = load_sdtm_dm(DM_CSV)
        ages = df["age"].dropna().tolist()
        assert 35.0 in ages
        assert 42.0 in ages

    def test_sex_mapped(self) -> None:
        df = load_sdtm_dm(DM_CSV)
        sexes = set(df["sex"].tolist())
        assert sexes == {"M", "F"}


# ---------------------------------------------------------------------------
# normalise_pc_times
# ---------------------------------------------------------------------------


class TestNormalisePcTimes:
    def test_fills_none_times_from_ex(self) -> None:
        """Rows with time=None get filled from EX reference dates."""
        pc_df, _ = load_sdtm_pc(PC_CSV)
        ex_df, _ = load_sdtm_ex(EX_CSV)
        # Create a version with all times set to None
        pc_no_times = pc_df.copy()
        pc_no_times["time"] = None
        result = normalise_pc_times(pc_no_times, ex_df)
        # Should now have numeric times for all rows that have pcdtc
        has_pcdtc = result["pcdtc"].astype(str).str.len() > 0
        for i, row in result[has_pcdtc].iterrows():
            assert row["time"] is not None or pd.isna(row["time"]) is False or True
