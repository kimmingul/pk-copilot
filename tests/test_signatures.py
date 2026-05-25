"""
Tests for pkplugin.compliance.signatures (≥8 tests).

Tests:
 1. Keypair generation produces valid Ed25519 keys.
 2. Sign + verify succeeds.
 3. Tampered file → verify fails.
 4. Signature meanings are preserved.
 5. Multiple signatures per run.
 6. verify_all_signatures all-pass.
 7. verify_all_signatures partial-fail.
 8. compute_run_hash excludes signatures.jsonl.
 9. save_private_key + load_private_key round-trip (no passphrase).
10. save_private_key + load_private_key round-trip (with passphrase).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pkplugin.compliance.signatures import (
    KeyPair,
    Signature,
    compute_run_hash,
    generate_keypair,
    load_signatures,
    save_private_key,
    sign_run,
    verify_all_signatures,
    verify_signature,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_dir(tmp_path: Path, name: str = "test-run-001") -> Path:
    run_dir = tmp_path / name
    run_dir.mkdir()
    (run_dir / "parameters.csv").write_text("subject_id,value\nS01,42.0\n")
    (run_dir / "audit.json").write_text('{"run_id": "test-run-001"}')
    return run_dir


def _write_key(tmp_path: Path, keypair: KeyPair, name: str = "test.key") -> Path:
    key_path = tmp_path / name
    save_private_key(keypair, key_path)
    return key_path


# ---------------------------------------------------------------------------
# 1. Keypair generation
# ---------------------------------------------------------------------------


def test_generate_keypair() -> None:
    kp = generate_keypair()
    assert len(kp.public_key_hex) == 64  # 32 bytes = 64 hex chars
    assert b"BEGIN PRIVATE KEY" in kp.private_key_pem
    assert b"BEGIN PUBLIC KEY" in kp.public_key_pem


# ---------------------------------------------------------------------------
# 2. Sign + verify succeeds
# ---------------------------------------------------------------------------


def test_sign_and_verify(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    kp = generate_keypair()
    key_path = _write_key(tmp_path, kp)

    sig = sign_run(
        run_dir=run_dir,
        signer_id="analyst@example.com",
        meaning="authored",
        private_key_path=key_path,
        signer_name="Analyst Kim",
    )

    assert sig.signer_id == "analyst@example.com"
    assert sig.meaning == "authored"
    assert sig.signer_name == "Analyst Kim"
    assert len(sig.run_hash) == 64  # sha256 hex

    assert verify_signature(run_dir, sig)


# ---------------------------------------------------------------------------
# 3. Tampered file → verify fails
# ---------------------------------------------------------------------------


def test_tampered_file_verify_fails(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    kp = generate_keypair()
    key_path = _write_key(tmp_path, kp)

    sig = sign_run(
        run_dir=run_dir,
        signer_id="analyst@example.com",
        meaning="authored",
        private_key_path=key_path,
    )

    # Tamper a file after signing
    (run_dir / "parameters.csv").write_text("subject_id,value\nS01,999.0\n")

    assert not verify_signature(run_dir, sig)


# ---------------------------------------------------------------------------
# 4. Signature meanings preserved
# ---------------------------------------------------------------------------


def test_signature_meanings(tmp_path: Path) -> None:
    for meaning in ("authored", "reviewed", "approved", "rejected"):
        run_dir = _make_run_dir(tmp_path, name=f"run-{meaning}")
        kp = generate_keypair()
        key_path = tmp_path / f"{meaning}.key"
        save_private_key(kp, key_path)

        sig = sign_run(
            run_dir=run_dir,
            signer_id=f"{meaning}@example.com",
            meaning=meaning,  # type: ignore[arg-type]
            private_key_path=key_path,
        )
        assert sig.meaning == meaning


# ---------------------------------------------------------------------------
# 5. Multiple signatures per run
# ---------------------------------------------------------------------------


def test_multiple_signatures_per_run(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    kp1 = generate_keypair()
    kp2 = generate_keypair()
    k1 = tmp_path / "key1.key"
    k2 = tmp_path / "key2.key"
    save_private_key(kp1, k1)
    save_private_key(kp2, k2)

    sign_run(run_dir=run_dir, signer_id="analyst@example.com", meaning="authored", private_key_path=k1)
    sign_run(run_dir=run_dir, signer_id="approver@example.com", meaning="reviewed", private_key_path=k2)

    sigs = load_signatures(run_dir)
    assert len(sigs) == 2
    meanings = {s.meaning for s in sigs}
    assert "authored" in meanings
    assert "reviewed" in meanings


# ---------------------------------------------------------------------------
# 6. verify_all_signatures all-pass
# ---------------------------------------------------------------------------


def test_verify_all_signatures_pass(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    kp = generate_keypair()
    key_path = _write_key(tmp_path, kp)

    sign_run(run_dir=run_dir, signer_id="analyst@example.com", meaning="authored", private_key_path=key_path)

    ok, failures = verify_all_signatures(run_dir)
    assert ok
    assert failures == []


# ---------------------------------------------------------------------------
# 7. verify_all_signatures partial-fail when sig file is corrupted
# ---------------------------------------------------------------------------


def test_verify_all_signatures_fail(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    kp = generate_keypair()
    key_path = _write_key(tmp_path, kp)

    sign_run(run_dir=run_dir, signer_id="analyst@example.com", meaning="authored", private_key_path=key_path)

    # Corrupt the signature hex in signatures.jsonl
    import json
    sig_file = run_dir / "signatures.jsonl"
    lines = sig_file.read_text().splitlines()
    data = json.loads(lines[0])
    data["signature_hex"] = "deadbeef" * 16
    sig_file.write_text(json.dumps(data) + "\n")

    ok, failures = verify_all_signatures(run_dir)
    assert not ok
    assert len(failures) > 0


# ---------------------------------------------------------------------------
# 8. compute_run_hash excludes signatures.jsonl
# ---------------------------------------------------------------------------


def test_compute_run_hash_excludes_signatures(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    hash_before_sig = compute_run_hash(run_dir)

    # Add signatures.jsonl — hash should remain the same
    (run_dir / "signatures.jsonl").write_text('{"test": "data"}\n')
    hash_after_sig = compute_run_hash(run_dir)

    assert hash_before_sig == hash_after_sig


# ---------------------------------------------------------------------------
# 9. save_private_key + load_private_key no passphrase
# ---------------------------------------------------------------------------


def test_save_load_key_no_passphrase(tmp_path: Path) -> None:
    from pkplugin.compliance.signatures import load_private_key

    kp = generate_keypair()
    key_path = tmp_path / "test_nopass.key"
    save_private_key(kp, key_path)

    raw = load_private_key(key_path)
    assert len(raw) == 32  # Ed25519 raw private key is 32 bytes


# ---------------------------------------------------------------------------
# 10. save_private_key + load_private_key with passphrase
# ---------------------------------------------------------------------------


def test_save_load_key_with_passphrase(tmp_path: Path) -> None:
    from pkplugin.compliance.signatures import load_private_key

    kp = generate_keypair()
    key_path = tmp_path / "test_pass.key"
    passphrase = b"my_secure_passphrase"
    save_private_key(kp, key_path, passphrase=passphrase)

    # Should fail without passphrase
    with pytest.raises(Exception):
        load_private_key(key_path, passphrase=None)

    # Should succeed with correct passphrase
    raw = load_private_key(key_path, passphrase=passphrase)
    assert len(raw) == 32


# ---------------------------------------------------------------------------
# 11. require_reauth_token: empty string raises when provided
# ---------------------------------------------------------------------------


def test_reauth_token_empty_raises(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    kp = generate_keypair()
    key_path = _write_key(tmp_path, kp)

    with pytest.raises(ValueError, match="Re-authentication"):
        sign_run(
            run_dir=run_dir,
            signer_id="analyst@example.com",
            meaning="authored",
            private_key_path=key_path,
            require_reauth_token="",  # empty — should raise
        )


# ---------------------------------------------------------------------------
# 12. No signatures file → verify_all returns ok=True
# ---------------------------------------------------------------------------


def test_no_signatures_file(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    ok, failures = verify_all_signatures(run_dir)
    assert ok
    assert failures == []
