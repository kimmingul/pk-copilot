"""
Tests for pkplugin.compliance.retention (≥6 tests).

Tests:
 1. lock_run with all required signatures succeeds.
 2. lock_run with missing signatures fails.
 3. Locked files are read-only (0o444).
 4. admin unlock_run writes chain event.
 5. verify_lock detects file modification after lock.
 6. is_locked returns True after lock, False before.
 7. Double-lock raises ValueError.
 8. unlock_run by non-admin raises UnlockError.
"""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pkplugin.compliance.access import Principal, Role
from pkplugin.compliance.audit_chain import AuditChain
from pkplugin.compliance.retention import (
    LockManifest,
    UnlockError,
    is_locked,
    lock_run,
    unlock_run,
    verify_lock,
)
from pkplugin.compliance.signatures import generate_keypair, save_private_key, sign_run

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _future_expiry() -> str:
    return (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_run_dir(tmp_path: Path, name: str = "test-run-lock") -> Path:
    run_dir = tmp_path / name
    run_dir.mkdir()
    (run_dir / "parameters.csv").write_text("subject_id,value\nS01,42.0\n")
    (run_dir / "audit.json").write_text('{"run_id": "test-run-lock"}')
    return run_dir


def _sign_all(run_dir: Path, key_dir: Path) -> None:
    """Sign with authored/reviewed/approved meanings."""
    for i, meaning in enumerate(("authored", "reviewed", "approved")):
        kp = generate_keypair()
        kp_path = key_dir / f"key_{meaning}.key"
        save_private_key(kp, kp_path)
        sign_run(
            run_dir=run_dir,
            signer_id=f"{meaning}@example.com",
            meaning=meaning,  # type: ignore[arg-type]
            private_key_path=kp_path,
        )


# ---------------------------------------------------------------------------
# 1. lock_run with all required signatures succeeds
# ---------------------------------------------------------------------------


def test_lock_run_success(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _sign_all(run_dir, tmp_path)

    manifest = lock_run(run_dir, locked_by="admin@example.com", lock_reason="Final submission")

    assert isinstance(manifest, LockManifest)
    assert manifest.run_id == run_dir.name
    assert manifest.locked_by == "admin@example.com"
    assert len(manifest.bundle_sha256) == 64
    assert is_locked(run_dir)


# ---------------------------------------------------------------------------
# 2. lock_run with missing signatures fails
# ---------------------------------------------------------------------------


def test_lock_run_missing_signatures(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    # Only sign 'authored', missing 'reviewed' and 'approved'
    kp = generate_keypair()
    kp_path = tmp_path / "authored.key"
    save_private_key(kp, kp_path)
    sign_run(
        run_dir=run_dir,
        signer_id="analyst@example.com",
        meaning="authored",
        private_key_path=kp_path,
    )

    with pytest.raises(ValueError, match="missing required signatures"):
        lock_run(run_dir, locked_by="admin@example.com", lock_reason="Too early")


# ---------------------------------------------------------------------------
# 3. Locked files are read-only
# ---------------------------------------------------------------------------


def test_locked_files_are_readonly(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _sign_all(run_dir, tmp_path)
    lock_run(run_dir, locked_by="admin@example.com", lock_reason="Final")

    for fpath in run_dir.rglob("*"):
        if fpath.is_file():
            mode = stat.S_IMODE(os.stat(fpath).st_mode)
            # Should be read-only: 0o444
            assert mode & stat.S_IWRITE == 0, f"{fpath} should be read-only"


# ---------------------------------------------------------------------------
# 4. Admin unlock writes chain event
# ---------------------------------------------------------------------------


def test_admin_unlock_writes_chain_event(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _sign_all(run_dir, tmp_path)
    lock_run(run_dir, locked_by="admin@example.com", lock_reason="Initial lock")

    admin = Principal(
        user_id="admin@example.com",
        role=Role.ADMIN,
        session_token="sess_admin",
        session_expires_utc=_future_expiry(),
    )
    # Chain needs writable key file — use separate chain dir
    chain_dir = tmp_path / "chain"
    chain_dir.mkdir()
    chain = AuditChain.open(chain_dir)

    unlock_run(
        run_dir=run_dir,
        admin_principal=admin,
        unlock_reason="Data entry error — deviation DEV-2026-001",
        chain=chain,
    )

    assert not is_locked(run_dir)
    # Chain should have the unlock event
    assert chain.length() == 1
    latest = chain.latest()
    assert latest is not None
    assert latest.action == "unlock_run"


# ---------------------------------------------------------------------------
# 5. verify_lock detects file modification after lock
# ---------------------------------------------------------------------------


def test_verify_lock_detects_modification(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _sign_all(run_dir, tmp_path)
    lock_run(run_dir, locked_by="admin@example.com", lock_reason="Final")

    # Make files writable again to simulate tampering
    for fpath in run_dir.rglob("*"):
        if fpath.is_file():
            os.chmod(fpath, 0o644)

    # Tamper a file
    (run_dir / "parameters.csv").write_text("TAMPERED CONTENT\n")

    ok, issues = verify_lock(run_dir)
    assert not ok
    assert len(issues) > 0


# ---------------------------------------------------------------------------
# 6. is_locked returns correct value
# ---------------------------------------------------------------------------


def test_is_locked_states(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    assert not is_locked(run_dir)

    _sign_all(run_dir, tmp_path)
    lock_run(run_dir, locked_by="admin@example.com", lock_reason="Final")
    assert is_locked(run_dir)


# ---------------------------------------------------------------------------
# 7. Double-lock raises ValueError
# ---------------------------------------------------------------------------


def test_double_lock_raises(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _sign_all(run_dir, tmp_path)
    lock_run(run_dir, locked_by="admin@example.com", lock_reason="First lock")

    # Make files writable for the second attempt
    for fpath in run_dir.rglob("*"):
        if fpath.is_file():
            os.chmod(fpath, 0o644)

    with pytest.raises(ValueError, match="already locked"):
        lock_run(run_dir, locked_by="admin@example.com", lock_reason="Second lock")


# ---------------------------------------------------------------------------
# 8. unlock_run by non-admin raises UnlockError
# ---------------------------------------------------------------------------


def test_unlock_by_non_admin_raises(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    _sign_all(run_dir, tmp_path)
    lock_run(run_dir, locked_by="admin@example.com", lock_reason="Final")

    analyst = Principal(
        user_id="analyst@example.com",
        role=Role.ANALYST,
        session_token="sess_analyst",
        session_expires_utc=_future_expiry(),
    )
    chain_dir = tmp_path / "chain"
    chain_dir.mkdir()
    chain = AuditChain.open(chain_dir)

    with pytest.raises(UnlockError):
        unlock_run(
            run_dir=run_dir,
            admin_principal=analyst,
            unlock_reason="Unauthorized attempt",
            chain=chain,
        )


# ---------------------------------------------------------------------------
# H2. Separation of duties — same signer for all meanings raises LockError
# ---------------------------------------------------------------------------

from pkplugin.compliance.retention import LockError  # noqa: E402


def test_lock_run_same_signer_all_meanings_raises(tmp_path: Path) -> None:
    """lock_run with require_distinct_signers=True raises if one signer covers all meanings."""
    run_dir = _make_run_dir(tmp_path)

    # Single signer signs all three meanings
    kp = generate_keypair()
    kp_path = tmp_path / "single.key"
    save_private_key(kp, kp_path)
    for meaning in ("authored", "reviewed", "approved"):
        sign_run(
            run_dir=run_dir,
            signer_id="omnisigner@example.com",
            meaning=meaning,  # type: ignore[arg-type]
            private_key_path=kp_path,
        )

    with pytest.raises(LockError, match="[Ss]eparation"):
        lock_run(
            run_dir,
            locked_by="admin@example.com",
            lock_reason="Should fail",
            require_distinct_signers=True,
        )


def test_lock_run_same_signer_distinct_false_succeeds(tmp_path: Path) -> None:
    """lock_run with require_distinct_signers=False allows single signer for all."""
    run_dir = _make_run_dir(tmp_path)

    kp = generate_keypair()
    kp_path = tmp_path / "single.key"
    save_private_key(kp, kp_path)
    for meaning in ("authored", "reviewed", "approved"):
        sign_run(
            run_dir=run_dir,
            signer_id="omnisigner@example.com",
            meaning=meaning,  # type: ignore[arg-type]
            private_key_path=kp_path,
        )

    manifest = lock_run(
        run_dir,
        locked_by="admin@example.com",
        lock_reason="Override allowed",
        require_distinct_signers=False,
    )
    assert manifest is not None


# ---------------------------------------------------------------------------
# M1. unlock_run checks session expiry
# ---------------------------------------------------------------------------


def test_unlock_expired_session_raises(tmp_path: Path) -> None:
    """unlock_run raises UnlockError when admin session is expired."""
    run_dir = _make_run_dir(tmp_path)
    _sign_all(run_dir, tmp_path)
    lock_run(run_dir, locked_by="admin@example.com", lock_reason="Final")

    # Admin with EXPIRED session
    from datetime import timedelta

    expired_expiry = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    admin = Principal(
        user_id="admin@example.com",
        role=Role.ADMIN,
        session_token="sess_expired",
        session_expires_utc=expired_expiry,
    )
    chain_dir = tmp_path / "chain"
    chain_dir.mkdir()
    chain = AuditChain.open(chain_dir)

    with pytest.raises(UnlockError, match="[Ss]ession|[Ee]xpir"):
        unlock_run(
            run_dir=run_dir,
            admin_principal=admin,
            unlock_reason="Emergency unlock",
            chain=chain,
        )
