"""
Append-only, hash-chained audit log with HMAC tamper-evidence.

Implements §11.10(e) (audit trail) and §11.10(a/f) (operational checks).

Chain format: JSONL at <chain_dir>/audit-chain.jsonl
HMAC key: <chain_dir>/chain.key (32 random bytes, created on first open)

Usage::

    chain = AuditChain.open("/path/to/run_dir")
    entry = chain.append(
        action="run_nca",
        user={"id": "analyst@example.com", "auth_method": "password"},
        reason="Initial NCA for Study ABC-101",
        run_id="2026-05-25-042",
        after={"run_state": "draft"},
    )
    ok, violations = chain.verify()
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import platform
import socket
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# HMAC key helpers
# ---------------------------------------------------------------------------


def derive_hmac_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte key from *passphrase* via PBKDF2-HMAC-SHA256 (200 000 iter)."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode(),
        salt,
        200_000,
        dklen=32,
    )


def default_hmac_key_path(chain_dir: str | Path) -> Path:
    """Return the canonical path for the HMAC key file.

    Checks the ``PKPLUGIN_CHAIN_KEY_PATH`` environment variable first.
    If unset, falls back to ``<chain_dir>/chain.key`` (co-located with the
    chain file).

    .. warning::
        Storing the key alongside the chain file weakens tamper-evidence —
        an attacker who can modify the chain can also re-HMAC it with the
        co-located key.  For production 21 CFR Part 11 deployments, set
        ``PKPLUGIN_CHAIN_KEY_PATH`` to an externally-managed (e.g. KMS-backed)
        key location.
    """
    env_path = os.environ.get("PKPLUGIN_CHAIN_KEY_PATH")
    if env_path:
        return Path(env_path)
    return Path(chain_dir) / "chain.key"


def load_or_create_hmac_key(chain_dir: str | Path) -> bytes:
    """Read the HMAC key or create a fresh one with os.urandom(32).

    Key path resolution: ``PKPLUGIN_CHAIN_KEY_PATH`` env var takes priority;
    falls back to ``<chain_dir>/chain.key``.  When the fallback (co-located)
    path is used for the first time, a :class:`UserWarning` is emitted advising
    production deployments to use an external KMS-backed location.

    Refuses to overwrite an existing key file.
    """
    import warnings as _w

    env_path = os.environ.get("PKPLUGIN_CHAIN_KEY_PATH")
    key_path = Path(env_path) if env_path else Path(chain_dir) / "chain.key"
    using_default_location = not env_path

    if key_path.exists():
        # Warn if permissions are too open (Opus review MAJOR-1 follow-up)
        try:
            mode = key_path.stat().st_mode & 0o777
            if mode & 0o077:
                _w.warn(
                    f"HMAC chain key at {key_path} has permissions {oct(mode)}; "
                    f"recommend 0o600. Run `chmod 600 {key_path}` to restrict.",
                    UserWarning,
                    stacklevel=2,
                )
        except OSError:
            pass
        return key_path.read_bytes()

    # Create a new 32-byte random key
    if using_default_location:
        _w.warn(
            "WARNING: HMAC chain key stored alongside chain file. "
            "For production Part 11 use, set PKPLUGIN_CHAIN_KEY_PATH to an "
            "external KMS-backed location.",
            UserWarning,
            stacklevel=2,
        )
    key = os.urandom(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    # Restrict permissions to owner-only (Part 11 tamper-evidence requirement)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        # Non-POSIX filesystems (Windows) — best effort
        pass
    return key


# ---------------------------------------------------------------------------
# Canonical helpers
# ---------------------------------------------------------------------------


def _canonical_payload_json(
    action: str,
    run_id: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> str:
    """Return canonical JSON string of the payload tuple."""
    obj: dict[str, Any] = {
        "action": action,
        "run_id": run_id,
        "before": before,
        "after": after,
    }
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _compute_payload_sha256(
    action: str,
    run_id: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> str:
    raw = _canonical_payload_json(action, run_id, before, after)
    return hashlib.sha256(raw.encode()).hexdigest()


def _canonical_body(entry_dict: dict[str, Any]) -> str:
    """Return canonical JSON of an entry dict with ``this_hash`` and ``hmac`` stripped.

    Used as the pre-image for ``this_hash`` computation so that ALL fields
    (including ``user``, ``reason``, ``workstation``, ``ntp_source``, etc.) are
    covered by the hash.  ``this_hash`` and ``hmac`` are excluded because they
    are computed FROM this body and cannot appear in their own input.
    """
    body = {k: v for k, v in entry_dict.items() if k not in ("this_hash", "hmac")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)


def _compute_this_hash_from_body(body_json: str) -> str:
    return hashlib.sha256(body_json.encode()).hexdigest()


def _compute_hmac(this_hash: str, key: bytes) -> str:
    return _hmac.new(key, this_hash.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# AuditChainEntry dataclass
# ---------------------------------------------------------------------------

_GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditChainEntry:
    """One entry in the append-only hash chain.

    Fields enforce the 6-tuple WHO/WHAT/WHEN/WHERE/WHY/BEFORE→AFTER spec
    as required by §11.10(e), §11.10(a/f).
    """

    event_id: str
    """uuid4 — unique event identifier."""

    prev_hash: str
    """sha256 of previous entry (or '0'*64 for genesis)."""

    timestamp_utc: str
    """ISO 8601 with 'Z' suffix."""

    ntp_source: str
    """NTP server name or 'system_clock'."""

    user: dict[str, str]
    """WHO — {'id': '...', 'auth_method': 'totp' | 'password' | 'key' | 'anonymous'}."""

    workstation: str
    """WHERE — hostname + platform."""

    action: str
    """WHAT — e.g. 'run_nca', 'sign_record', 'lock_run'."""

    run_id: str | None
    """Related run, or None for non-run events."""

    reason: str
    """WHY — required, non-empty for state changes."""

    before: dict[str, Any] | None
    """State delta — state before event."""

    after: dict[str, Any] | None
    """State delta — state after event."""

    payload_sha256: str
    """sha256 of canonical JSON of (action, run_id, before, after)."""

    this_hash: str
    """sha256 of the canonical JSON of all fields except this_hash and hmac."""

    hmac: str
    """hex hmac-sha256 of this_hash using the chain key."""

    def canonical_json(self) -> str:
        """Return canonical JSON string of this entry (for storage)."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), default=str)


# ---------------------------------------------------------------------------
# AuditChain
# ---------------------------------------------------------------------------


class AuditChain:
    """Append-only chain stored as JSONL at <chain_dir>/audit-chain.jsonl."""

    _CHAIN_FILE = "audit-chain.jsonl"

    def __init__(self, chain_dir: str | Path, hmac_key: bytes | None = None) -> None:
        self._dir = Path(chain_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._chain_file = self._dir / self._CHAIN_FILE
        if hmac_key is not None:
            self._key = hmac_key
        else:
            self._key = load_or_create_hmac_key(self._dir)

    @classmethod
    def open(cls, chain_dir: str | Path, hmac_key: bytes | None = None) -> "AuditChain":
        """Open (or create) an AuditChain at *chain_dir*."""
        return cls(chain_dir, hmac_key)

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------

    def append(
        self,
        action: str,
        user: dict[str, str],
        reason: str,
        run_id: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        ntp_source: str = "system_clock",
    ) -> AuditChainEntry:
        """Append one entry to the chain and return it."""
        if not reason.strip():
            raise ValueError("reason must be non-empty")

        # Determine prev_hash
        prev = self.latest()
        prev_hash = prev.this_hash if prev is not None else _GENESIS_HASH

        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        timestamp_utc = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        workstation = socket.gethostname() + "/" + platform.system().lower()

        payload_sha256 = _compute_payload_sha256(action, run_id, before, after)

        # Build the entry dict without this_hash/hmac so _canonical_body can
        # produce the exact pre-image used for this_hash computation.
        entry_body: dict[str, Any] = {
            "event_id": event_id,
            "prev_hash": prev_hash,
            "timestamp_utc": timestamp_utc,
            "ntp_source": ntp_source,
            "user": user,
            "workstation": workstation,
            "action": action,
            "run_id": run_id,
            "reason": reason,
            "before": before,
            "after": after,
            "payload_sha256": payload_sha256,
        }
        body_json = _canonical_body(entry_body)
        this_hash = _compute_this_hash_from_body(body_json)
        hmac_hex = _compute_hmac(this_hash, self._key)

        entry = AuditChainEntry(
            event_id=event_id,
            prev_hash=prev_hash,
            timestamp_utc=timestamp_utc,
            ntp_source=ntp_source,
            user=user,
            workstation=workstation,
            action=action,
            run_id=run_id,
            reason=reason,
            before=before,
            after=after,
            payload_sha256=payload_sha256,
            this_hash=this_hash,
            hmac=hmac_hex,
        )

        # Append to JSONL file
        with open(self._chain_file, "a", encoding="utf-8") as fh:
            fh.write(entry.canonical_json() + "\n")

        return entry

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

    def verify(self) -> tuple[bool, list[str]]:
        """Walk the chain; each entry's prev_hash must match previous entry's this_hash.

        HMAC is verified with the current key.

        Returns:
            (ok, list_of_violations_with_line_numbers)
        """
        violations: list[str] = []

        if not self._chain_file.exists():
            return True, []

        lines = self._chain_file.read_text(encoding="utf-8").splitlines()
        prev_hash = _GENESIS_HASH

        for line_no, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                violations.append(f"line {line_no}: JSON parse error: {exc}")
                continue

            entry_id = data.get("event_id", f"<line {line_no}>")

            # 1. Check prev_hash linkage
            if data.get("prev_hash") != prev_hash:
                violations.append(
                    f"line {line_no} (event_id={entry_id}): "
                    f"prev_hash mismatch — expected {prev_hash[:16]}..., "
                    f"got {str(data.get('prev_hash', ''))[:16]}..."
                )

            # 2. Verify this_hash — re-compute from the canonical body using the
            #    EXPECTED prev_hash (not the stored one) so tampering of any field,
            #    including prev_hash itself, is detected.
            body_for_verify = {k: v for k, v in data.items() if k not in ("this_hash", "hmac")}
            body_for_verify["prev_hash"] = prev_hash  # use expected, not stored
            body_json = _canonical_body(body_for_verify)
            expected_this = _compute_this_hash_from_body(body_json)
            if data.get("this_hash") != expected_this:
                violations.append(
                    f"line {line_no} (event_id={entry_id}): "
                    f"this_hash mismatch — entry tampered"
                )

            # 3. Verify payload_sha256
            expected_payload = _compute_payload_sha256(
                data.get("action", ""),
                data.get("run_id"),
                data.get("before"),
                data.get("after"),
            )
            if data.get("payload_sha256") != expected_payload:
                violations.append(
                    f"line {line_no} (event_id={entry_id}): "
                    f"payload_sha256 mismatch — payload tampered"
                )

            # 4. Verify HMAC
            expected_hmac = _compute_hmac(data.get("this_hash", ""), self._key)
            if data.get("hmac") != expected_hmac:
                violations.append(
                    f"line {line_no} (event_id={entry_id}): "
                    f"HMAC verification failed"
                )

            # Advance prev_hash for next iteration (use stored this_hash so the
            # chain walk continues; violations are already recorded above).
            prev_hash = data.get("this_hash", "")

        return len(violations) == 0, violations

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def length(self) -> int:
        """Return the number of entries in the chain."""
        if not self._chain_file.exists():
            return 0
        count = 0
        with open(self._chain_file, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    count += 1
        return count

    def latest(self) -> AuditChainEntry | None:
        """Return the most recent entry, or None if chain is empty."""
        if not self._chain_file.exists():
            return None
        last_line: str | None = None
        with open(self._chain_file, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last_line = line.strip()
        if last_line is None:
            return None
        data = json.loads(last_line)
        return _entry_from_dict(data)


def _entry_from_dict(data: dict[str, Any]) -> AuditChainEntry:
    """Reconstruct an AuditChainEntry from a dict (e.g. from JSONL)."""
    return AuditChainEntry(
        event_id=data["event_id"],
        prev_hash=data["prev_hash"],
        timestamp_utc=data["timestamp_utc"],
        ntp_source=data.get("ntp_source", "system_clock"),
        user=data.get("user", {}),
        workstation=data.get("workstation", ""),
        action=data["action"],
        run_id=data.get("run_id"),
        reason=data.get("reason", ""),
        before=data.get("before"),
        after=data.get("after"),
        payload_sha256=data["payload_sha256"],
        this_hash=data["this_hash"],
        hmac=data["hmac"],
    )
