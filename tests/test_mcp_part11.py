"""
Tests for Part 11 MCP impl functions (≥6 tests).

Tests:
 1. impl_sign_record signs a run and returns ok status.
 2. impl_sign_record on missing run returns error.
 3. impl_sign_record with invalid meaning returns error.
 4. impl_lock_run locks a run after signing.
 5. impl_verify_audit_chain returns ok for empty chain.
 6. impl_verify_signatures returns ok for unsigned run.
 7. impl_get_compliance_status returns expected keys.
 8. End-to-end: sign + lock + verify.
"""

from __future__ import annotations

from pathlib import Path

from pkplugin.compliance.signatures import generate_keypair, save_private_key, sign_run
from pkplugin.mcp_server import (
    impl_get_compliance_status,
    impl_lock_run,
    impl_sign_record,
    impl_verify_audit_chain,
    impl_verify_signatures,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(tmp_path: Path, run_id: str = "test-part11-run") -> Path:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "parameters.csv").write_text("subject_id,value\nS01,42.0\n")
    (run_dir / "audit.json").write_text(f'{{"run_id": "{run_id}"}}')
    return run_dir


def _make_key(tmp_path: Path, name: str = "test.key") -> Path:
    kp = generate_keypair()
    key_path = tmp_path / name
    save_private_key(kp, key_path)
    return key_path


def _sign_all_three(run_dir: Path, keys_dir: Path, audit_base: Path) -> None:
    """Sign with all three required meanings via sign_run directly."""
    for meaning in ("authored", "reviewed", "approved"):
        kp = generate_keypair()
        kp_path = keys_dir / f"{meaning}.key"
        save_private_key(kp, kp_path)
        sign_run(
            run_dir=run_dir,
            signer_id=f"{meaning}@example.com",
            meaning=meaning,  # type: ignore[arg-type]
            private_key_path=kp_path,
        )


# ---------------------------------------------------------------------------
# 1. impl_sign_record signs a run
# ---------------------------------------------------------------------------


def test_impl_sign_record_ok(tmp_path: Path) -> None:
    run_id = "mcp-sign-run-001"
    run_dir = _make_run(tmp_path, run_id)
    key_path = _make_key(tmp_path)

    result = impl_sign_record(
        run_id=run_id,
        signer_identity="analyst@example.com",
        meaning="authored",
        auth_token="123456",
        private_key_path=str(key_path),
        audit_dir=str(tmp_path),
    )
    assert result["status"] == "ok"
    assert result["run_id"] == run_id
    assert result["meaning"] == "authored"
    assert "run_hash" in result


# ---------------------------------------------------------------------------
# 2. impl_sign_record on missing run returns error
# ---------------------------------------------------------------------------


def test_impl_sign_record_missing_run(tmp_path: Path) -> None:
    key_path = _make_key(tmp_path)
    result = impl_sign_record(
        run_id="nonexistent-run",
        signer_identity="analyst@example.com",
        meaning="authored",
        auth_token="123456",
        private_key_path=str(key_path),
        audit_dir=str(tmp_path),
    )
    assert result["status"] == "error"
    assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# 3. impl_sign_record with invalid meaning returns error
# ---------------------------------------------------------------------------


def test_impl_sign_record_invalid_meaning(tmp_path: Path) -> None:
    run_id = "mcp-sign-invalid-meaning"
    _make_run(tmp_path, run_id)
    key_path = _make_key(tmp_path)

    result = impl_sign_record(
        run_id=run_id,
        signer_identity="analyst@example.com",
        meaning="invalid_meaning",
        auth_token="123456",
        private_key_path=str(key_path),
        audit_dir=str(tmp_path),
    )
    assert result["status"] == "error"
    assert "meaning" in result["error"].lower()


# ---------------------------------------------------------------------------
# 4. impl_lock_run locks a run after signing
# ---------------------------------------------------------------------------


def test_impl_lock_run_ok(tmp_path: Path) -> None:
    run_id = "mcp-lock-run-001"
    run_dir = _make_run(tmp_path, run_id)
    _sign_all_three(run_dir, tmp_path, tmp_path)

    result = impl_lock_run(
        run_id=run_id,
        locked_by="admin@example.com",
        lock_reason="Final BE submission",
        audit_dir=str(tmp_path),
    )
    assert result["status"] == "ok"
    assert result["run_id"] == run_id
    assert "bundle_sha256" in result
    assert "locked_at_utc" in result


# ---------------------------------------------------------------------------
# 5. impl_verify_audit_chain returns ok for empty chain
# ---------------------------------------------------------------------------


def test_impl_verify_audit_chain_empty(tmp_path: Path) -> None:
    chain_dir = tmp_path / "empty_chain"
    chain_dir.mkdir()

    result = impl_verify_audit_chain(chain_dir=str(chain_dir))
    assert result["status"] == "ok"
    assert result["ok"] is True
    assert result["n_entries"] == 0
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# 6. impl_verify_signatures returns ok for unsigned run
# ---------------------------------------------------------------------------


def test_impl_verify_signatures_no_sigs(tmp_path: Path) -> None:
    run_id = "mcp-verify-no-sigs"
    _make_run(tmp_path, run_id)

    result = impl_verify_signatures(run_id=run_id, audit_dir=str(tmp_path))
    assert result["status"] == "ok"
    assert result["ok"] is True
    assert result["n_signatures"] == 0


# ---------------------------------------------------------------------------
# 7. impl_get_compliance_status returns expected keys
# ---------------------------------------------------------------------------


def test_impl_get_compliance_status_keys() -> None:
    result = impl_get_compliance_status()
    assert "part11_version" in result
    assert result["part11_version"] == "v2.0"
    assert "cryptography_available" in result
    assert result["cryptography_available"] is True
    assert "compliance_module_available" in result
    assert result["compliance_module_available"] is True
    assert "controls" in result
    assert "audit_trail" in result["controls"]
    assert "electronic_signatures" in result["controls"]
    assert "access_control" in result["controls"]
    assert "record_retention" in result["controls"]
    assert "disclaimer" in result


# ---------------------------------------------------------------------------
# 8. End-to-end: sign + lock + verify chain
# ---------------------------------------------------------------------------


def test_e2e_sign_lock_verify(tmp_path: Path) -> None:
    run_id = "e2e-part11-run"
    run_dir = _make_run(tmp_path, run_id)

    # Sign all three
    for meaning in ("authored", "reviewed", "approved"):
        kp = generate_keypair()
        kp_path = tmp_path / f"{meaning}.key"
        save_private_key(kp, kp_path)
        r = impl_sign_record(
            run_id=run_id,
            signer_identity=f"{meaning}@example.com",
            meaning=meaning,
            auth_token="totp_placeholder",
            private_key_path=str(kp_path),
            audit_dir=str(tmp_path),
        )
        assert r["status"] == "ok", f"sign {meaning} failed: {r}"

    # Lock
    lock_result = impl_lock_run(
        run_id=run_id,
        locked_by="admin@example.com",
        lock_reason="Final approval complete",
        audit_dir=str(tmp_path),
    )
    assert lock_result["status"] == "ok"

    # Verify signatures
    vsig_result = impl_verify_signatures(run_id=run_id, audit_dir=str(tmp_path))
    assert vsig_result["status"] == "ok"
    assert vsig_result["n_signatures"] == 3

    # Verify chain in run dir
    vchain_result = impl_verify_audit_chain(chain_dir=str(run_dir))
    assert vchain_result["status"] == "ok"
    assert vchain_result["ok"] is True
