"""Tests for MCP CDISC tool implementations.

Covers:
- impl_import_sdtm end-to-end with golden fixtures
- impl_export_adam from a saved NCA run
- impl_validate_cdisc on ADPP CSV
- Error handling: missing files, bad domain

Refs: docs/09-cdisc-support.md §2
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from pkplugin.mcp_server import impl_export_adam, impl_import_sdtm, impl_validate_cdisc

GOLDEN = Path(__file__).parent / "golden" / "cdisc"
PC_CSV = GOLDEN / "pc.csv"
EX_CSV = GOLDEN / "ex.csv"
DM_CSV = GOLDEN / "dm.csv"


# ---------------------------------------------------------------------------
# impl_import_sdtm
# ---------------------------------------------------------------------------


class TestImplImportSdtm:
    def test_basic_import_returns_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = impl_import_sdtm(
                pc_path=str(PC_CSV),
                ex_path=str(EX_CSV),
                audit_dir=tmpdir,
            )
        assert result["status"] == "ok"

    def test_import_with_dm(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = impl_import_sdtm(
                pc_path=str(PC_CSV),
                ex_path=str(EX_CSV),
                dm_path=str(DM_CSV),
                audit_dir=tmpdir,
            )
        assert result["status"] == "ok"
        assert "dm_csv" in result

    def test_import_returns_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = impl_import_sdtm(
                pc_path=str(PC_CSV),
                ex_path=str(EX_CSV),
                audit_dir=tmpdir,
            )
        assert "run_id" in result
        assert result["run_id"]

    def test_import_n_subjects_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = impl_import_sdtm(
                pc_path=str(PC_CSV),
                ex_path=str(EX_CSV),
                audit_dir=tmpdir,
            )
        assert result["n_subjects"] == 2

    def test_import_n_pc_rows_16(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = impl_import_sdtm(
                pc_path=str(PC_CSV),
                ex_path=str(EX_CSV),
                audit_dir=tmpdir,
            )
        assert result["n_pc_rows"] == 16

    def test_import_writes_canonical_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = impl_import_sdtm(
                pc_path=str(PC_CSV),
                ex_path=str(EX_CSV),
                audit_dir=tmpdir,
            )
            assert Path(result["pc_csv"]).exists()
            assert Path(result["ex_csv"]).exists()

    def test_import_missing_pc_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = impl_import_sdtm(
                pc_path="/nonexistent/pc.csv",
                ex_path=str(EX_CSV),
                audit_dir=tmpdir,
            )
        assert result["status"] == "error"

    def test_import_missing_ex_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = impl_import_sdtm(
                pc_path=str(PC_CSV),
                ex_path="/nonexistent/ex.csv",
                audit_dir=tmpdir,
            )
        assert result["status"] == "error"

    def test_import_analyte_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = impl_import_sdtm(
                pc_path=str(PC_CSV),
                ex_path=str(EX_CSV),
                analyte="DRUGX",
                audit_dir=tmpdir,
            )
        assert result["status"] == "ok"
        assert result["n_pc_rows"] == 16


# ---------------------------------------------------------------------------
# impl_export_adam
# ---------------------------------------------------------------------------


def _create_nca_run(tmpdir: str) -> str:
    """Create a minimal NCA parameters.csv in the audit dir and return run_id."""
    from pkplugin.cdisc.adam import build_adpp
    from pkplugin.nca.engine import calculate_nca
    from pkplugin.schemas import ConcentrationRecord, DoseRecord, NCAConfig

    times = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0]
    concs = [0.0, 12.4, 18.7, 24.3, 21.1, 14.8, 8.2, 3.1]
    records = [
        ConcentrationRecord(subject_id="STUDY01-001-001", time=t, concentration=c, analyte="DRUGX")
        for t, c in zip(times, concs)
    ]
    dose = DoseRecord(subject_id="STUDY01-001-001", time=0.0, amount=100.0, route="oral")
    results = calculate_nca(records, [dose], NCAConfig())

    run_id = "test-nca-001"
    run_dir = Path(tmpdir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for r in results:
        for prow in r.parameter_rows:
            rows.append({
                "subject_id": prow.subject_id,
                "period": prow.period,
                "treatment": prow.treatment,
                "analyte": prow.analyte,
                "parameter": prow.parameter,
                "value": prow.value,
                "unit": prow.unit,
                "method": prow.method,
                "winnonlin_version": prow.winnonlin_version,
                "flags": ";".join(prow.flags),
                "comment": prow.comment,
            })
    pd.DataFrame(rows).to_csv(run_dir / "parameters.csv", index=False)
    return run_id


class TestImplExportAdam:
    def test_export_returns_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = _create_nca_run(tmpdir)
            result = impl_export_adam(nca_run_id=run_id, audit_dir=tmpdir)
        assert result["status"] == "ok"

    def test_export_writes_adpp_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = _create_nca_run(tmpdir)
            result = impl_export_adam(nca_run_id=run_id, audit_dir=tmpdir)
            assert "adpp_path" in result
            assert Path(result["adpp_path"]).exists()

    def test_export_adpp_has_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = _create_nca_run(tmpdir)
            result = impl_export_adam(nca_run_id=run_id, audit_dir=tmpdir)
            assert result["n_adpp_rows"] > 0

    def test_export_define_xml_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = _create_nca_run(tmpdir)
            result = impl_export_adam(
                nca_run_id=run_id,
                include_define_xml=True,
                audit_dir=tmpdir,
            )
            assert "define_xml_path" in result
            assert Path(result["define_xml_path"]).exists()

    def test_export_missing_run_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = impl_export_adam(nca_run_id="nonexistent-run-id", audit_dir=tmpdir)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# impl_validate_cdisc
# ---------------------------------------------------------------------------


class TestImplValidateCdisc:
    def _write_valid_adpp_csv(self, path: Path) -> None:
        df = pd.DataFrame([{
            "STUDYID": "STUDY01",
            "USUBJID": "STUDY01-001-001",
            "PARAMCD": "CMAX",
            "AVAL": 24.3,
            "AVALU": "ng/mL",
            "PPCAT": "NON-COMPARTMENTAL",
        }])
        df.to_csv(path, index=False)

    def test_validate_adpp_valid_returns_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "adpp.csv"
            self._write_valid_adpp_csv(csv_path)
            result = impl_validate_cdisc(str(csv_path), "ADPP")
        assert result["status"] == "ok"
        assert result["passed"] is True

    def test_validate_adpp_unknown_paramcd_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "adpp.csv"
            df = pd.DataFrame([{
                "STUDYID": "STUDY01",
                "USUBJID": "STUDY01-001-001",
                "PARAMCD": "XXXXXXINVALID",
                "AVAL": 24.3,
                "AVALU": "ng/mL",
                "PPCAT": "NON-COMPARTMENTAL",
            }])
            df.to_csv(csv_path, index=False)
            result = impl_validate_cdisc(str(csv_path), "ADPP")
        assert result["n_errors"] >= 1

    def test_validate_missing_file_returns_error(self) -> None:
        result = impl_validate_cdisc("/nonexistent/adpp.csv", "ADPP")
        assert result["status"] == "error"

    def test_validate_bad_domain_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "adpp.csv"
            pd.DataFrame().to_csv(csv_path, index=False)
            result = impl_validate_cdisc(str(csv_path), "INVALID_DOMAIN")
        assert result["status"] == "error"
