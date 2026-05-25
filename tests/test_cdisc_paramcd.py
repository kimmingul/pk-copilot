"""Tests for pkplugin.cdisc.paramcd — CDISC PARAMCD registry.

Covers:
- Registry has >= 20 entries
- Bi-directional mapping works
- Unknown names return None
- No duplicate pkcopilot_name values
- No duplicate PARAMCD codes
- All entries have non-empty paramcd/param/pkcopilot_name

Refs: docs/09-cdisc-support.md §6
"""

from __future__ import annotations

from pkplugin.cdisc.paramcd import (
    PARAMCD_REGISTRY,
    ParamCodeEntry,
    paramcd_to_pkcopilot,
    pkcopilot_to_paramcd,
)


class TestRegistrySize:
    def test_registry_has_at_least_20_entries(self) -> None:
        assert len(PARAMCD_REGISTRY) >= 20, (
            f"Registry has {len(PARAMCD_REGISTRY)} entries, expected >= 20"
        )

    def test_registry_contains_core_entries(self) -> None:
        required = {"CMAX", "TMAX", "AUCLST", "AUCIFO", "LAMZHL", "CL"}
        missing = required - set(PARAMCD_REGISTRY.keys())
        assert not missing, f"Missing core entries: {missing}"


class TestEntryStructure:
    def test_all_entries_are_frozen_dataclass(self) -> None:
        for paramcd, entry in PARAMCD_REGISTRY.items():
            assert isinstance(entry, ParamCodeEntry), f"{paramcd} is not a ParamCodeEntry"

    def test_all_paramcd_codes_non_empty(self) -> None:
        for paramcd, entry in PARAMCD_REGISTRY.items():
            assert entry.paramcd.strip(), f"Empty paramcd for key {paramcd!r}"

    def test_all_param_labels_non_empty(self) -> None:
        for paramcd, entry in PARAMCD_REGISTRY.items():
            assert entry.param.strip(), f"Empty param for key {paramcd!r}"

    def test_all_pkcopilot_names_non_empty(self) -> None:
        for paramcd, entry in PARAMCD_REGISTRY.items():
            assert entry.pkcopilot_name.strip(), f"Empty pkcopilot_name for key {paramcd!r}"

    def test_registry_key_matches_entry_paramcd(self) -> None:
        for key, entry in PARAMCD_REGISTRY.items():
            assert key == entry.paramcd, (
                f"Registry key {key!r} does not match entry.paramcd {entry.paramcd!r}"
            )


class TestNoDuplicates:
    def test_no_duplicate_pkcopilot_names(self) -> None:
        names = [e.pkcopilot_name for e in PARAMCD_REGISTRY.values()]
        seen: set[str] = set()
        dupes: list[str] = []
        for n in names:
            if n in seen:
                dupes.append(n)
            seen.add(n)
        assert not dupes, f"Duplicate pkcopilot_name values: {dupes}"

    def test_no_duplicate_paramcd_codes(self) -> None:
        codes = list(PARAMCD_REGISTRY.keys())
        assert len(codes) == len(set(codes)), "Duplicate PARAMCD keys found"


class TestBidirectionalMapping:
    def test_pkcopilot_to_paramcd_cmax(self) -> None:
        assert pkcopilot_to_paramcd("Cmax") == "CMAX"

    def test_pkcopilot_to_paramcd_auclast(self) -> None:
        assert pkcopilot_to_paramcd("AUClast") == "AUCLST"

    def test_pkcopilot_to_paramcd_lamzhl(self) -> None:
        assert pkcopilot_to_paramcd("HL_Lambda_z") == "LAMZHL"

    def test_paramcd_to_pkcopilot_auclst(self) -> None:
        assert paramcd_to_pkcopilot("AUCLST") == "AUClast"

    def test_paramcd_to_pkcopilot_cmax(self) -> None:
        assert paramcd_to_pkcopilot("CMAX") == "Cmax"

    def test_paramcd_to_pkcopilot_lamzhl(self) -> None:
        assert paramcd_to_pkcopilot("LAMZHL") == "HL_Lambda_z"

    def test_roundtrip_pkcopilot_name(self) -> None:
        """pkcopilot -> paramcd -> pkcopilot should round-trip."""
        for paramcd, entry in PARAMCD_REGISTRY.items():
            back_paramcd = pkcopilot_to_paramcd(entry.pkcopilot_name)
            assert back_paramcd == paramcd, (
                f"Round-trip failed: {entry.pkcopilot_name!r} -> {back_paramcd!r}, expected {paramcd!r}"
            )

    def test_roundtrip_paramcd(self) -> None:
        """paramcd -> pkcopilot -> paramcd should round-trip."""
        for paramcd in PARAMCD_REGISTRY:
            pkname = paramcd_to_pkcopilot(paramcd)
            assert pkname is not None
            back = pkcopilot_to_paramcd(pkname)
            assert back == paramcd, f"Round-trip failed: {paramcd!r} -> {pkname!r} -> {back!r}"


class TestUnknownReturnsNone:
    def test_pkcopilot_unknown_returns_none(self) -> None:
        assert pkcopilot_to_paramcd("NonExistentParam") is None

    def test_pkcopilot_empty_returns_none(self) -> None:
        assert pkcopilot_to_paramcd("") is None

    def test_paramcd_unknown_returns_none(self) -> None:
        assert paramcd_to_pkcopilot("XXXXXXX") is None

    def test_paramcd_empty_returns_none(self) -> None:
        assert paramcd_to_pkcopilot("") is None

    def test_paramcd_case_insensitive_lookup(self) -> None:
        # paramcd_to_pkcopilot normalises to upper
        assert paramcd_to_pkcopilot("auclst") == "AUClast"
        assert paramcd_to_pkcopilot("cmax") == "Cmax"
