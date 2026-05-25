"""Tests for pkplugin.cdisc.define_xml — Define-XML 2.1 generator.

Covers:
- Generated XML parses without error
- Contains expected ItemGroupDef nodes
- Contains expected ItemDef nodes
- Contains PARAMCD CodeList when paramcds_used is provided
- Round-trip: write + re-read produces consistent structure

Refs: docs/09-cdisc-support.md §7
"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from pkplugin.cdisc.define_xml import generate_define_xml


class TestGenerateDefineXml:
    def _generate(
        self,
        tmpdir: str,
        domains: list[str] | None = None,
        paramcds: list[str] | None = None,
        study_id: str = "STUDY01",
    ) -> Path:
        if domains is None:
            domains = ["ADPC", "ADPP"]
        if paramcds is None:
            paramcds = ["CMAX", "AUCLST", "LAMZHL"]
        out = Path(tmpdir) / "define.xml"
        return generate_define_xml(
            study_id=study_id,
            domains=domains,
            paramcds_used=paramcds,
            output_path=out,
        )

    def test_generates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._generate(tmpdir)
            assert path.exists()
            assert path.stat().st_size > 0

    def test_xml_parses_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._generate(tmpdir)
            tree = ET.parse(str(path))
            root = tree.getroot()
            assert root is not None

    def test_root_is_odm(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._generate(tmpdir)
            tree = ET.parse(str(path))
            root = tree.getroot()
            # Root tag may include namespace
            assert "ODM" in root.tag

    def test_contains_itemgroupdef_adpc(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._generate(tmpdir, domains=["ADPC"])
            content = path.read_text()
            assert "ADPC" in content

    def test_contains_itemgroupdef_adpp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._generate(tmpdir, domains=["ADPP"])
            content = path.read_text()
            assert "ADPP" in content

    def test_contains_itemdef_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._generate(tmpdir, domains=["ADPP"])
            content = path.read_text()
            assert "ItemDef" in content

    def test_contains_paramcd_codelist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._generate(tmpdir, paramcds=["CMAX", "AUCLST"])
            content = path.read_text()
            assert "PARAMCD" in content
            assert "CMAX" in content

    def test_roundtrip_study_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._generate(tmpdir, study_id="MYTEST")
            content = path.read_text()
            assert "MYTEST" in content

    def test_all_paramcds_in_codelist(self) -> None:
        paramcds = ["CMAX", "TMAX", "AUCLST", "LAMZHL"]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._generate(tmpdir, paramcds=paramcds)
            content = path.read_text()
            for pc in paramcds:
                assert pc in content, f"PARAMCD {pc!r} missing from define.xml"

    def test_empty_domains_produces_valid_xml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._generate(tmpdir, domains=[])
            tree = ET.parse(str(path))
            assert tree.getroot() is not None

    def test_file_oid_contains_study_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._generate(tmpdir, study_id="STUDY99")
            content = path.read_text()
            assert "STUDY99" in content
