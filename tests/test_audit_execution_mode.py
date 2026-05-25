"""Regression tests for AuditEntry / AuditChain execution_mode threading."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

# ---------- AuditEntry exposes new fields ----------


def test_audit_entry_has_execution_mode_field() -> None:
    from pkplugin.audit import AuditEntry

    fields = {f.name for f in dataclasses.fields(AuditEntry)}
    assert "execution_mode" in fields
    assert "llm_orchestrated" in fields
    assert "llm_transcript_hash" in fields


def test_audit_entry_defaults_are_exploratory_and_not_orchestrated() -> None:
    from pkplugin.audit import new_entry

    e = new_entry(tool="t", config={})
    assert e.execution_mode == "exploratory"
    assert e.llm_orchestrated is False
    assert e.llm_transcript_hash is None


def test_new_entry_accepts_mode_kwargs() -> None:
    from pkplugin.audit import new_entry

    e = new_entry(
        tool="t",
        config={},
        execution_mode="controlled",
        llm_orchestrated=True,
        llm_transcript_hash="sha256:abc",
    )
    assert e.execution_mode == "controlled"
    assert e.llm_orchestrated is True
    assert e.llm_transcript_hash == "sha256:abc"


def test_audit_entry_to_dict_includes_mode() -> None:
    from pkplugin.audit import new_entry

    e = new_entry(tool="t", config={}, execution_mode="controlled")
    d = e.to_dict()
    assert d["execution_mode"] == "controlled"
    assert "llm_orchestrated" in d


# ---------- AuditEntry.write includes mode in JSON + audit.md ----------


def test_audit_entry_write_emits_mode(tmp_path: Path) -> None:
    from pkplugin.audit import new_entry

    e = new_entry(tool="run_nca", config={}, execution_mode="controlled", llm_orchestrated=True)
    json_path = e.write(tmp_path)
    payload = json.loads(json_path.read_text())
    assert payload["execution_mode"] == "controlled"
    assert payload["llm_orchestrated"] is True

    md_path = json_path.parent / "audit.md"
    assert md_path.is_file()
    md_text = md_path.read_text()
    # Mode should appear prominently in markdown companion
    assert "controlled" in md_text.lower()


# ---------- AuditChain entries carry mode in canonical body (hash-protected) ----------


def test_audit_chain_append_records_mode(tmp_path: Path) -> None:
    from pkplugin.compliance.audit_chain import AuditChain

    chain = AuditChain.open(tmp_path)
    entry = chain.append(
        action="run_nca",
        user={"id": "analyst", "auth_method": "cli"},
        reason="test",
        execution_mode="controlled",
        llm_orchestrated=True,
    )
    assert entry.execution_mode == "controlled"
    assert entry.llm_orchestrated is True

    ok, violations = chain.verify()
    assert ok, violations


def test_tampering_with_mode_breaks_chain(tmp_path: Path) -> None:
    """Hash chain must detect a single-byte change to execution_mode."""
    from pkplugin.compliance.audit_chain import AuditChain

    chain = AuditChain.open(tmp_path)
    chain.append(
        action="x",
        user={"id": "u", "auth_method": "none"},
        reason="r",
        execution_mode="exploratory",
    )

    jsonl = tmp_path / "audit-chain.jsonl"
    text = jsonl.read_text()
    tampered = text.replace('"exploratory"', '"controlled"')
    jsonl.write_text(tampered)

    ok, violations = chain.verify()
    assert not ok, "expected tamper detection"
    assert violations


# ---------- impl_run_nca returns execution_mode in result ----------


def test_impl_run_nca_returns_execution_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default (no env) should produce exploratory mode in the response."""
    monkeypatch.delenv("PKPLUGIN_PART11_ENABLED", raising=False)
    # Ensure MCP context default (LLM orchestrated) doesn't break the test
    monkeypatch.setenv("PKPLUGIN_LLM_ORCHESTRATED", "0")
    from pkplugin.mcp_server import impl_run_nca

    csv = tmp_path / "x.csv"
    csv.write_text(
        "subject_id,time_hr,conc_ng_per_ml,dose\n"
        "S1,0,10,100\nS1,1,7.5,100\nS1,2,5.5,100\nS1,4,3.0,100\nS1,8,0.9,100\n"
    )
    result = impl_run_nca(
        dataset_path=str(csv),
        config={"winnonlin_version": "6.4"},
        audit_dir=str(tmp_path / "runs"),
    )
    assert result["status"] == "ok"
    assert result["execution_mode"] == "exploratory"


def test_impl_run_nca_controlled_with_env_and_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PKPLUGIN_PART11_ENABLED", "1")
    monkeypatch.setenv("PKPLUGIN_LLM_ORCHESTRATED", "0")
    from pkplugin.mcp_server import impl_run_nca

    csv = tmp_path / "x.csv"
    csv.write_text(
        "subject_id,time_hr,conc_ng_per_ml,dose\n"
        "S1,0,10,100\nS1,1,7.5,100\nS1,2,5.5,100\nS1,4,3.0,100\nS1,8,0.9,100\n"
    )
    result = impl_run_nca(
        dataset_path=str(csv),
        config={"winnonlin_version": "6.4"},
        user={"id": "analyst@example.com", "auth_method": "cli"},
        audit_dir=str(tmp_path / "runs"),
    )
    assert result["status"] == "ok"
    # user kwarg is threaded through → mode should be controlled
    assert result["execution_mode"] == "controlled"
