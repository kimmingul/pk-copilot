"""
Tests for pkplugin.compliance.audit_chain (≥10 tests).

Tests:
 1. Append and verify a single entry (genesis).
 2. Append multiple entries and verify the full chain.
 3. Tamper single byte → verify() must fail.
 4. HMAC mismatch (wrong key) → verify() fails.
 5. Missing prev_hash entry → verify() fails.
 6. Chain length counts correctly.
 7. Latest returns most recent entry.
 8. Empty chain → verify() ok, length 0, latest None.
 9. Reason required — empty reason raises ValueError.
10. Key rotation: old entries fail with new key.
11. Genesis hash is correct (prev_hash = '0'*64 for first entry).
12. Canonical JSON round-trip (fields stable).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pkplugin.compliance.audit_chain import (
    AuditChain,
    _GENESIS_HASH,
    derive_hmac_key,
    load_or_create_hmac_key,
    default_hmac_key_path,
)

_USER = {"id": "analyst@example.com", "auth_method": "password"}


# ---------------------------------------------------------------------------
# 1. Append and verify single entry (genesis)
# ---------------------------------------------------------------------------


def test_append_single_genesis(tmp_path: Path) -> None:
    chain = AuditChain.open(tmp_path)
    entry = chain.append(
        action="run_nca",
        user=_USER,
        reason="Initial NCA",
        run_id="test-run-001",
        after={"run_state": "draft"},
    )
    assert entry.prev_hash == _GENESIS_HASH
    assert entry.action == "run_nca"
    assert entry.run_id == "test-run-001"
    ok, violations = chain.verify()
    assert ok, violations
    assert violations == []


# ---------------------------------------------------------------------------
# 2. Multiple entries — chain links correctly
# ---------------------------------------------------------------------------


def test_append_multiple_verify(tmp_path: Path) -> None:
    chain = AuditChain.open(tmp_path)
    e1 = chain.append(action="run_nca", user=_USER, reason="NCA run", run_id="r1")
    e2 = chain.append(action="sign_record", user=_USER, reason="Authored", run_id="r1")
    e3 = chain.append(action="lock_run", user=_USER, reason="Final lock", run_id="r1")

    assert e2.prev_hash == e1.this_hash
    assert e3.prev_hash == e2.this_hash

    ok, violations = chain.verify()
    assert ok, violations
    assert chain.length() == 3


# ---------------------------------------------------------------------------
# 3. Tamper single byte → verify fails
# ---------------------------------------------------------------------------


def test_tamper_single_byte(tmp_path: Path) -> None:
    chain = AuditChain.open(tmp_path)
    chain.append(action="run_nca", user=_USER, reason="NCA run", run_id="r1")
    chain.append(action="sign_record", user=_USER, reason="Authored", run_id="r1")

    chain_file = tmp_path / "audit-chain.jsonl"
    content = chain_file.read_text(encoding="utf-8")
    # Flip a character in the middle of the file
    mid = len(content) // 2
    tampered = content[:mid] + ("X" if content[mid] != "X" else "Y") + content[mid + 1:]
    chain_file.write_text(tampered, encoding="utf-8")

    ok, violations = chain.verify()
    assert not ok
    assert len(violations) > 0


# ---------------------------------------------------------------------------
# 4. HMAC mismatch — wrong key → verify fails
# ---------------------------------------------------------------------------


def test_hmac_mismatch_wrong_key(tmp_path: Path) -> None:
    good_key = b"A" * 32
    bad_key = b"B" * 32

    chain_good = AuditChain.open(tmp_path, hmac_key=good_key)
    chain_good.append(action="run_nca", user=_USER, reason="NCA run", run_id="r1")

    # Open with wrong key
    chain_bad = AuditChain.open(tmp_path, hmac_key=bad_key)
    ok, violations = chain_bad.verify()
    assert not ok
    assert any("HMAC" in v for v in violations)


# ---------------------------------------------------------------------------
# 5. Missing/broken prev_hash → verify fails
# ---------------------------------------------------------------------------


def test_broken_prev_hash(tmp_path: Path) -> None:
    chain = AuditChain.open(tmp_path)
    chain.append(action="run_nca", user=_USER, reason="NCA run", run_id="r1")
    chain.append(action="sign_record", user=_USER, reason="Authored", run_id="r1")

    chain_file = tmp_path / "audit-chain.jsonl"
    lines = chain_file.read_text(encoding="utf-8").splitlines()
    # Corrupt prev_hash of second line
    data = json.loads(lines[1])
    data["prev_hash"] = "deadbeef" * 8
    lines[1] = json.dumps(data)
    chain_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, violations = chain.verify()
    assert not ok
    assert any("prev_hash" in v for v in violations)


# ---------------------------------------------------------------------------
# 6. Chain length
# ---------------------------------------------------------------------------


def test_chain_length(tmp_path: Path) -> None:
    chain = AuditChain.open(tmp_path)
    assert chain.length() == 0
    for i in range(5):
        chain.append(action=f"action_{i}", user=_USER, reason=f"reason {i}", run_id="r1")
    assert chain.length() == 5


# ---------------------------------------------------------------------------
# 7. Latest returns most recent entry
# ---------------------------------------------------------------------------


def test_latest_entry(tmp_path: Path) -> None:
    chain = AuditChain.open(tmp_path)
    chain.append(action="first", user=_USER, reason="first reason", run_id="r1")
    e_last = chain.append(action="last", user=_USER, reason="last reason", run_id="r1")

    latest = chain.latest()
    assert latest is not None
    assert latest.action == "last"
    assert latest.event_id == e_last.event_id


# ---------------------------------------------------------------------------
# 8. Empty chain
# ---------------------------------------------------------------------------


def test_empty_chain(tmp_path: Path) -> None:
    chain = AuditChain.open(tmp_path)
    assert chain.length() == 0
    assert chain.latest() is None
    ok, violations = chain.verify()
    assert ok
    assert violations == []


# ---------------------------------------------------------------------------
# 9. Empty reason raises ValueError
# ---------------------------------------------------------------------------


def test_empty_reason_raises(tmp_path: Path) -> None:
    chain = AuditChain.open(tmp_path)
    with pytest.raises(ValueError, match="reason"):
        chain.append(action="run_nca", user=_USER, reason="   ", run_id="r1")


# ---------------------------------------------------------------------------
# 10. Key rotation: old entries fail with new key
# ---------------------------------------------------------------------------


def test_key_rotation_old_entries_fail(tmp_path: Path) -> None:
    original_key = b"original_key_32bytes_paddingXXXX"
    new_key = b"rotated_key_32bytes_paddingYYYYY"

    chain = AuditChain.open(tmp_path, hmac_key=original_key)
    chain.append(action="run_nca", user=_USER, reason="Before rotation", run_id="r1")

    # Verify passes with original key
    ok, _ = chain.verify()
    assert ok

    # Verify fails with new key (old entries have HMAC from original key)
    chain_new = AuditChain.open(tmp_path, hmac_key=new_key)
    ok2, violations2 = chain_new.verify()
    assert not ok2
    assert len(violations2) > 0


# ---------------------------------------------------------------------------
# 11. Genesis hash check
# ---------------------------------------------------------------------------


def test_genesis_hash_value(tmp_path: Path) -> None:
    chain = AuditChain.open(tmp_path)
    entry = chain.append(action="run_nca", user=_USER, reason="First", run_id="r1")
    assert entry.prev_hash == "0" * 64


# ---------------------------------------------------------------------------
# 12. Canonical JSON round-trip
# ---------------------------------------------------------------------------


def test_canonical_json_roundtrip(tmp_path: Path) -> None:
    chain = AuditChain.open(tmp_path)
    entry = chain.append(
        action="sign_record",
        user=_USER,
        reason="Authored",
        run_id="r1",
        before={"run_state": None},
        after={"run_state": "authored"},
    )
    cj = entry.canonical_json()
    data = json.loads(cj)
    assert data["action"] == "sign_record"
    assert data["reason"] == "Authored"
    assert data["before"] == {"run_state": None}
    assert data["after"] == {"run_state": "authored"}


# ---------------------------------------------------------------------------
# Helper: derive_hmac_key
# ---------------------------------------------------------------------------


def test_derive_hmac_key_deterministic() -> None:
    salt = b"test_salt_1234"
    k1 = derive_hmac_key("mypassphrase", salt)
    k2 = derive_hmac_key("mypassphrase", salt)
    assert k1 == k2
    assert len(k1) == 32


def test_load_or_create_hmac_key(tmp_path: Path) -> None:
    key1 = load_or_create_hmac_key(tmp_path)
    key2 = load_or_create_hmac_key(tmp_path)
    assert key1 == key2  # same key on second call
    assert len(key1) == 32
    assert (tmp_path / "chain.key").exists()


# ---------------------------------------------------------------------------
# C1 regression: tamper detection for individual fields
# ---------------------------------------------------------------------------


def _append_and_tamper(tmp_path: Path, field: str, new_value: object) -> tuple[bool, list[str]]:
    """Helper: append one entry, tamper *field* in the JSONL, return verify()."""
    chain = AuditChain.open(tmp_path)
    chain.append(
        action="x",
        user={"id": "u", "auth_method": "none"},
        reason="original",
        run_id="r1",
    )
    p = tmp_path / "audit-chain.jsonl"
    data = json.loads(p.read_text())
    data[field] = new_value
    p.write_text(json.dumps(data) + "\n", encoding="utf-8")
    return chain.verify()


def test_tamper_detection_reason_field(tmp_path: Path) -> None:
    chain = AuditChain.open(tmp_path)
    chain.append(action="x", user={"id": "u", "auth_method": "none"}, reason="original")
    p = tmp_path / "audit-chain.jsonl"
    text = p.read_text()
    tampered = text.replace('"original"', '"tampered"')
    p.write_text(tampered)
    ok, violations = chain.verify()
    assert not ok
    assert any("hash" in v.lower() or "tamper" in v.lower() for v in violations)


def test_tamper_detection_user_field(tmp_path: Path) -> None:
    ok, violations = _append_and_tamper(
        tmp_path, "user", {"id": "attacker@evil.com", "auth_method": "none"}
    )
    assert not ok
    assert any("hash" in v.lower() or "tamper" in v.lower() for v in violations)


def test_tamper_detection_workstation_field(tmp_path: Path) -> None:
    ok, violations = _append_and_tamper(tmp_path, "workstation", "evil-host/linux")
    assert not ok
    assert any("hash" in v.lower() or "tamper" in v.lower() for v in violations)


def test_tamper_detection_ntp_source_field(tmp_path: Path) -> None:
    ok, violations = _append_and_tamper(tmp_path, "ntp_source", "evil-ntp.example.com")
    assert not ok
    assert any("hash" in v.lower() or "tamper" in v.lower() for v in violations)


def test_tamper_detection_action_field(tmp_path: Path) -> None:
    ok, violations = _append_and_tamper(tmp_path, "action", "evil_action")
    assert not ok
    assert any("hash" in v.lower() or "tamper" in v.lower() for v in violations)


# ---------------------------------------------------------------------------
# C2 regression: HMAC key path from env var + warning on default location
# ---------------------------------------------------------------------------


def test_hmac_key_path_from_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PKPLUGIN_CHAIN_KEY_PATH overrides the default co-located key path."""
    external_key = tmp_path / "external" / "chain.key"
    external_key.parent.mkdir()
    monkeypatch.setenv("PKPLUGIN_CHAIN_KEY_PATH", str(external_key))

    result = default_hmac_key_path(tmp_path / "chain_dir")
    assert result == external_key


def test_hmac_key_warning_on_default_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Creating a key at the default (co-located) location emits UserWarning."""
    monkeypatch.delenv("PKPLUGIN_CHAIN_KEY_PATH", raising=False)
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        load_or_create_hmac_key(tmp_path)
    assert any(
        "PKPLUGIN_CHAIN_KEY_PATH" in str(warning.message) for warning in w
    ), "Expected warning about co-located key file"
