"""Tests for pkplugin.cdisc.adam — ADPC/ADPP builders.

Covers:
- ADPC build from concentration DataFrame
- ADPP build from NCA results
- Schema columns present in output
- PARAMCD mapping applied in ADPP
- Empty input produces empty DataFrame with correct columns
- write_adam_dataset writes CSV; XPT raises NotImplementedError

Refs: docs/09-cdisc-support.md §5
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from pkplugin.cdisc.adam import (
    ADPC_VARIABLES,
    ADPP_VARIABLES,
    build_adpc,
    build_adpp,
    write_adam_dataset,
)
from pkplugin.cdisc.sdtm import load_sdtm_dm
from pkplugin.nca.engine import NCAResult, calculate_nca
from pkplugin.schemas import ConcentrationRecord, DoseRecord, NCAConfig

GOLDEN = Path(__file__).parent / "golden" / "cdisc"
PC_CSV = GOLDEN / "pc.csv"
EX_CSV = GOLDEN / "ex.csv"
DM_CSV = GOLDEN / "dm.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_concentration_df() -> pd.DataFrame:
    """Build a minimal canonical concentration DataFrame."""
    rows = [
        {
            "subject_id": "STUDY01-001-001",
            "time": 0.5,
            "concentration": 12.4,
            "analyte": "DRUGX",
            "matrix": "plasma",
            "bloq": False,
            "raw_concentration": "12.4",
            "pctpt": "30 min",
            "pctptnum": 0.5,
            "pcdtc": "2024-03-01T08:30:00",
            "pcstresu": "ng/mL",
            "studyid": "STUDY01",
        },
        {
            "subject_id": "STUDY01-001-001",
            "time": 1.0,
            "concentration": 18.7,
            "analyte": "DRUGX",
            "matrix": "plasma",
            "bloq": False,
            "raw_concentration": "18.7",
            "pctpt": "1 hr",
            "pctptnum": 1.0,
            "pcdtc": "2024-03-01T09:00:00",
            "pcstresu": "ng/mL",
            "studyid": "STUDY01",
        },
    ]
    return pd.DataFrame(rows)


def _make_nca_results() -> list[NCAResult]:
    """Run NCA on a simple concentration profile and return results."""
    times = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]
    concs = [0.0, 12.4, 18.7, 24.3, 21.1, 14.8, 8.2, 3.1]
    records = [
        ConcentrationRecord(
            subject_id="STUDY01-001-001",
            time=t,
            concentration=c,
            analyte="DRUGX",
        )
        for t, c in zip(times, concs)
    ]
    dose = DoseRecord(
        subject_id="STUDY01-001-001",
        time=0.0,
        amount=100.0,
        route="oral",
    )
    return calculate_nca(records, [dose], NCAConfig())


# ---------------------------------------------------------------------------
# ADPC tests
# ---------------------------------------------------------------------------


class TestBuildAdpc:
    def test_returns_dataframe(self) -> None:
        df = _make_concentration_df()
        adpc = build_adpc(df)
        assert isinstance(adpc, pd.DataFrame)

    def test_adpc_has_all_required_columns(self) -> None:
        df = _make_concentration_df()
        adpc = build_adpc(df)
        for col in ADPC_VARIABLES:
            assert col in adpc.columns, f"Missing column: {col}"

    def test_adpc_row_count_matches_input(self) -> None:
        df = _make_concentration_df()
        adpc = build_adpc(df)
        assert len(adpc) == len(df)

    def test_adpc_studyid_populated(self) -> None:
        df = _make_concentration_df()
        adpc = build_adpc(df, study_id="MYSTUDY")
        assert (adpc["STUDYID"] == "MYSTUDY").all()

    def test_adpc_usubjid_matches_input(self) -> None:
        df = _make_concentration_df()
        adpc = build_adpc(df)
        assert "STUDY01-001-001" in adpc["USUBJID"].values

    def test_adpc_aval_is_numeric(self) -> None:
        df = _make_concentration_df()
        adpc = build_adpc(df)
        non_na = adpc["AVAL"].dropna()
        assert pd.to_numeric(non_na, errors="coerce").notna().all()

    def test_adpc_with_dm_covariates(self) -> None:
        conc_df = _make_concentration_df()
        dm_df = load_sdtm_dm(DM_CSV)
        adpc = build_adpc(conc_df, dm_df=dm_df)
        # First subject has SEX=M
        subj_rows = adpc[adpc["USUBJID"] == "STUDY01-001-001"]
        if not subj_rows.empty:
            assert subj_rows.iloc[0]["SEX"] == "M"

    def test_adpc_empty_input(self) -> None:
        empty_df = pd.DataFrame(
            columns=[
                "subject_id",
                "time",
                "concentration",
                "analyte",
                "matrix",
                "bloq",
                "raw_concentration",
                "pctpt",
                "pctptnum",
                "pcdtc",
                "pcstresu",
            ]
        )
        adpc = build_adpc(empty_df)
        for col in ADPC_VARIABLES:
            assert col in adpc.columns


# ---------------------------------------------------------------------------
# ADPP tests
# ---------------------------------------------------------------------------


class TestBuildAdpp:
    def test_returns_dataframe(self) -> None:
        results = _make_nca_results()
        adpp = build_adpp(results)
        assert isinstance(adpp, pd.DataFrame)

    def test_adpp_has_all_required_columns(self) -> None:
        results = _make_nca_results()
        adpp = build_adpp(results)
        for col in ADPP_VARIABLES:
            assert col in adpp.columns, f"Missing column: {col}"

    def test_adpp_paramcd_present(self) -> None:
        results = _make_nca_results()
        adpp = build_adpp(results)
        assert "PARAMCD" in adpp.columns
        paramcds = adpp["PARAMCD"].dropna().tolist()
        assert len(paramcds) > 0

    def test_adpp_contains_cmax_paramcd(self) -> None:
        results = _make_nca_results()
        adpp = build_adpp(results)
        assert "CMAX" in adpp["PARAMCD"].values

    def test_adpp_contains_auclst_paramcd(self) -> None:
        results = _make_nca_results()
        adpp = build_adpp(results)
        assert "AUCLST" in adpp["PARAMCD"].values

    def test_adpp_aval_numeric(self) -> None:
        results = _make_nca_results()
        adpp = build_adpp(results)
        non_na = adpp["AVAL"].dropna()
        assert pd.to_numeric(non_na, errors="coerce").notna().all()

    def test_adpp_ppcat_noncompartmental(self) -> None:
        results = _make_nca_results()
        adpp = build_adpp(results)
        assert (adpp["PPCAT"] == "NON-COMPARTMENTAL").all()

    def test_adpp_empty_nca_results(self) -> None:
        adpp = build_adpp([])
        for col in ADPP_VARIABLES:
            assert col in adpp.columns

    def test_adpp_studyid_populated(self) -> None:
        results = _make_nca_results()
        adpp = build_adpp(results, study_id="TESTSTUDY")
        assert (adpp["STUDYID"] == "TESTSTUDY").all()


# ---------------------------------------------------------------------------
# write_adam_dataset
# ---------------------------------------------------------------------------


class TestWriteAdamDataset:
    def test_write_csv(self) -> None:
        results = _make_nca_results()
        adpp = build_adpp(results)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "adpp.csv"
            result_path = write_adam_dataset(adpp, out_path, format="csv")
            assert result_path.exists()
            loaded = pd.read_csv(result_path)
            assert len(loaded) == len(adpp)

    def test_write_xpt_raises_not_implemented(self) -> None:
        results = _make_nca_results()
        adpp = build_adpp(results)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "adpp.xpt"
            with pytest.raises(NotImplementedError):
                write_adam_dataset(adpp, out_path, format="xpt")
