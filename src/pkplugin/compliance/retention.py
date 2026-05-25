"""
WORM-friendly run bundle finalization for pk-copilot v2.0.

Implements §11.10(c) (record retention — accurate, complete, retrievable).

A locked run bundle has:
  - All required signatures present and cryptographically valid.
  - A LOCKED.json manifest with bundle hash and lock metadata.
  - All files in the bundle set to read-only (os.chmod 0o444).

Usage::

    manifest = lock_run(
        run_dir=Path("pk_runs/2026-05-25-042"),
        locked_by="approver@example.com",
        lock_reason="Final BE submission",
    )
    ok, issues = verify_lock(run_dir)
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pkplugin.compliance.access import Principal
    from pkplugin.compliance.audit_chain import AuditChain

from pkplugin.compliance.signatures import (
    SignatureMeaning,
    load_signatures,
    verify_all_signatures,
)

_LOCK_FILE = "LOCKED.json"
_SIG_FILE = "signatures.jsonl"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LockManifest:
    """Manifest written to <run_dir>/LOCKED.json on lock_run."""

    run_id: str
    locked_at_utc: str
    locked_by: str
    lock_reason: str
    bundle_sha256: str
    signatures_required: list[SignatureMeaning]
    """Which signature meanings were present at lock time."""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UnlockError(Exception):
    """Raised when unlock_run prerequisites are not met."""


# ---------------------------------------------------------------------------
# Bundle hash
# ---------------------------------------------------------------------------


_BUNDLE_EXCLUSIONS = {
    _LOCK_FILE,
    "signatures.jsonl",   # separate from bundle content (signatures reference bundle hash)
    "audit-chain.jsonl",  # operational audit log
    "chain.key",          # HMAC key
}


def _compute_bundle_sha256(run_dir: Path) -> str:
    """Compute a single SHA-256 hash over all files in the bundle (sorted).

    Excludes metadata/operational files that are not part of the analysis
    bundle content itself.
    """
    h = hashlib.sha256()
    for fpath in sorted(run_dir.rglob("*")):
        if not fpath.is_file():
            continue
        if fpath.name in _BUNDLE_EXCLUSIONS:
            continue
        rel = str(fpath.relative_to(run_dir))
        h.update(rel.encode())
        h.update(b":")
        h.update(fpath.read_bytes())
        h.update(b"\n")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Lock / unlock
# ---------------------------------------------------------------------------


def lock_run(
    run_dir: Path,
    locked_by: str,
    lock_reason: str,
    *,
    require_signatures: list[SignatureMeaning] | None = None,
) -> LockManifest:
    """Finalize a run bundle.

    Steps:
    1. Verify all required signatures are present and valid.
    2. Compute bundle SHA-256 hash.
    3. Write <run_dir>/LOCKED.json.
    4. Set all bundle files to read-only (os.chmod 0o444).

    Args:
        run_dir: Directory containing the run artifacts.
        locked_by: Identifier of the person initiating the lock.
        lock_reason: Non-empty reason string.
        require_signatures: List of signature meanings that must be present.
            Defaults to ["authored", "reviewed", "approved"].

    Returns:
        The :class:`LockManifest`.

    Raises:
        FileNotFoundError: If run_dir does not exist.
        ValueError: If required signatures are missing or invalid.
    """
    if require_signatures is None:
        require_signatures = ["authored", "reviewed", "approved"]

    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    if is_locked(run_dir):
        raise ValueError(f"Run {run_dir.name!r} is already locked")

    # Check signatures
    present_sigs = load_signatures(run_dir)
    present_meanings = {s.meaning for s in present_sigs}

    missing = [m for m in require_signatures if m not in present_meanings]
    if missing:
        raise ValueError(
            f"Cannot lock run {run_dir.name!r}: missing required signatures: {missing}"
        )

    # Verify all signatures cryptographically
    all_valid, failures = verify_all_signatures(run_dir)
    if not all_valid:
        raise ValueError(
            f"Cannot lock run {run_dir.name!r}: signature verification failed: {failures}"
        )

    # Compute bundle hash
    bundle_sha256 = _compute_bundle_sha256(run_dir)

    now = datetime.now(timezone.utc)
    locked_at_utc = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    manifest = LockManifest(
        run_id=run_dir.name,
        locked_at_utc=locked_at_utc,
        locked_by=locked_by,
        lock_reason=lock_reason,
        bundle_sha256=bundle_sha256,
        signatures_required=list(present_meanings & set(require_signatures)),
    )

    # Write LOCKED.json
    lock_file = run_dir / _LOCK_FILE
    lock_dict: dict[str, Any] = {
        "run_id": manifest.run_id,
        "locked_at_utc": manifest.locked_at_utc,
        "locked_by": manifest.locked_by,
        "lock_reason": manifest.lock_reason,
        "bundle_sha256": manifest.bundle_sha256,
        "signatures_required": manifest.signatures_required,
    }
    lock_file.write_text(json.dumps(lock_dict, indent=2), encoding="utf-8")

    # Set all files (including LOCKED.json) to read-only
    for fpath in run_dir.rglob("*"):
        if fpath.is_file():
            os.chmod(fpath, 0o444)

    return manifest


def is_locked(run_dir: Path) -> bool:
    """Return True if <run_dir>/LOCKED.json exists."""
    return (run_dir / _LOCK_FILE).exists()


def verify_lock(run_dir: Path) -> tuple[bool, list[str]]:
    """Verify lock integrity: LOCKED.json present, bundle hash matches current files.

    Returns:
        (ok, list_of_issues)
    """
    issues: list[str] = []
    lock_file = run_dir / _LOCK_FILE

    if not lock_file.exists():
        return False, ["LOCKED.json not found — run is not locked"]

    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"Cannot parse LOCKED.json: {exc}"]

    stored_hash = data.get("bundle_sha256", "")
    current_hash = _compute_bundle_sha256(run_dir)

    if current_hash != stored_hash:
        issues.append(
            f"Bundle SHA-256 mismatch — stored={stored_hash[:16]}..., "
            f"current={current_hash[:16]}... (files may have been modified after locking)"
        )

    return len(issues) == 0, issues


def unlock_run(
    run_dir: Path,
    admin_principal: "Principal",
    unlock_reason: str,
    *,
    chain: "AuditChain",
) -> None:
    """Admin-only emergency unlock.

    Requires admin role, writes a signed unlock event to the audit chain
    (which is itself immutable), then removes LOCKED.json and restores
    file write permissions.

    Args:
        run_dir: Directory of the locked run.
        admin_principal: Must have Role.ADMIN.
        unlock_reason: Non-empty reason (minimum enforced by AuditChain).
        chain: The AuditChain to record the unlock event in.

    Raises:
        UnlockError: If prerequisites are not met.
    """
    from pkplugin.compliance.access import AccessDeniedError, check_permission

    if not run_dir.is_dir():
        raise UnlockError(f"Run directory not found: {run_dir}")

    if not is_locked(run_dir):
        raise UnlockError(f"Run {run_dir.name!r} is not locked")

    if not unlock_reason.strip():
        raise UnlockError("unlock_reason must be non-empty")

    # Check admin permission
    try:
        check_permission(admin_principal, "unlock_with_signed_reason")
    except AccessDeniedError as exc:
        raise UnlockError(str(exc)) from exc

    # Record unlock event in the audit chain BEFORE modifying files
    chain.append(
        action="unlock_run",
        user={"id": admin_principal.user_id, "auth_method": "admin"},
        reason=unlock_reason,
        run_id=run_dir.name,
        before={"locked": True},
        after={"locked": False},
    )

    # Restore write permissions
    for fpath in run_dir.rglob("*"):
        if fpath.is_file():
            os.chmod(fpath, 0o644)

    # Remove lock file
    lock_file = run_dir / _LOCK_FILE
    lock_file.unlink()
