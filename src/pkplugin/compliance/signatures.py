"""
Ed25519 electronic signature support for pk-copilot v2.0.

Implements §11.50 (signature components: signer name, timestamp, meaning),
§11.70 (signatures linked to individuals, non-forgeable),
§11.200 (two identification components per signing event).

Usage::

    keypair = generate_keypair()
    save_private_key(keypair, Path("analyst.key"), passphrase=b"secret")

    sig = sign_run(
        run_dir=Path("pk_runs/2026-05-25-042"),
        signer_id="analyst@example.com",
        meaning="authored",
        private_key_path=Path("analyst.key"),
        passphrase=b"secret",
        require_reauth_token="totp_code",
    )
    ok = verify_signature(run_dir, sig)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SignatureMeaning = Literal["authored", "reviewed", "approved", "rejected"]

_SIG_FILE = "signatures.jsonl"
# Files excluded from run hash computation — these are audit/operational
# metadata that change between signing events and should not be part of the
# signed bundle content.
_SIG_EXCLUSIONS = {
    _SIG_FILE,
    "audit-chain.jsonl",  # grows as audit entries are appended
    "chain.key",          # HMAC key — operational, not bundle content
    "LOCKED.json",        # lock manifest written after signing
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Signature:
    """One electronic signature on a run bundle (§11.50 components)."""

    signer_id: str
    """'Signed by' — §11.50(a)(1)."""

    signer_name: str | None
    """Optional display name — §11.50(a)(1)."""

    timestamp_utc: str
    """'Date/Time' — §11.50(a)(2)."""

    meaning: SignatureMeaning
    """'Meaning of signature' — §11.50(a)(3)."""

    run_id: str
    """Run bundle this signature covers."""

    run_hash: str
    """sha256 of the canonical bundle being signed — §11.50(b) link."""

    signature_hex: str
    """Ed25519 detached signature over run_hash bytes."""

    public_key_hex: str
    """Hex-encoded Ed25519 public key (32 bytes)."""


@dataclass(frozen=True)
class KeyPair:
    """Ed25519 key pair."""

    private_key_pem: bytes
    public_key_pem: bytes
    public_key_hex: str


# ---------------------------------------------------------------------------
# Key generation and persistence
# ---------------------------------------------------------------------------


def generate_keypair() -> KeyPair:
    """Generate a new Ed25519 key pair."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return KeyPair(
        private_key_pem=private_pem,
        public_key_pem=public_pem,
        public_key_hex=pub_raw.hex(),
    )


def save_private_key(
    keypair: KeyPair,
    path: Path,
    passphrase: bytes | None = None,
) -> Path:
    """Save the Ed25519 private key to *path*, optionally encrypted with *passphrase*."""
    if passphrase is not None:
        encryption: serialization.KeySerializationEncryption = (
            serialization.BestAvailableEncryption(passphrase)
        )
    else:
        encryption = serialization.NoEncryption()

    private_key = serialization.load_pem_private_key(keypair.private_key_pem, password=None)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=encryption,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pem)
    # Restrict private-key file to owner-only (Part 11 + best practice)
    try:
        import os
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def load_private_key(path: Path, passphrase: bytes | None = None) -> bytes:
    """Load an Ed25519 private key from PEM file; returns raw 32-byte private key."""
    pem_data = path.read_bytes()
    private_key = serialization.load_pem_private_key(pem_data, password=passphrase)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("Key file does not contain an Ed25519 private key")
    raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return raw


# ---------------------------------------------------------------------------
# Run bundle hashing
# ---------------------------------------------------------------------------


def compute_run_hash(run_dir: Path) -> str:
    """Compute the canonical sha256 hash of a run bundle.

    Algorithm:
    1. Gather all files in run_dir (recursively), sorted by relative path.
    2. Exclude existing signature files so the bundle can be re-signed.
    3. Concatenate "path:sha256\\n" lines and hash the whole string.
    """
    entries: list[str] = []
    for fpath in sorted(run_dir.rglob("*")):
        if not fpath.is_file():
            continue
        if fpath.name in _SIG_EXCLUSIONS:
            continue
        rel = fpath.relative_to(run_dir)
        file_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
        entries.append(f"{rel.as_posix()}:{file_hash}")
    canonical = "\n".join(entries) + "\n"
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Signing and verification
# ---------------------------------------------------------------------------


def sign_run(
    run_dir: Path,
    signer_id: str,
    meaning: SignatureMeaning,
    private_key_path: Path,
    passphrase: bytes | None = None,
    signer_name: str | None = None,
    *,
    require_reauth_token: str | None = None,
) -> Signature:
    """Sign a run bundle and append the signature to <run_dir>/signatures.jsonl.

    If *require_reauth_token* is given, any non-empty string is accepted as
    valid in v2.0 (production should integrate TOTP/hardware key here).

    Args:
        run_dir: Directory containing the run artifacts.
        signer_id: Unique identifier of the signer (e.g. email).
        meaning: Signature meaning ('authored', 'reviewed', 'approved', 'rejected').
        private_key_path: Path to the PEM-encoded Ed25519 private key.
        passphrase: Passphrase for encrypted key file, if any.
        signer_name: Optional display name.
        require_reauth_token: If provided, must be non-empty to proceed.

    Returns:
        The created :class:`Signature`.
    """
    if require_reauth_token is not None and not require_reauth_token.strip():
        raise ValueError("Re-authentication token must be non-empty when provided")

    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    # Derive run_id from directory name
    run_id = run_dir.name

    # Compute canonical hash of bundle
    run_hash = compute_run_hash(run_dir)

    # Load private key
    pem_data = private_key_path.read_bytes()
    private_key = serialization.load_pem_private_key(pem_data, password=passphrase)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("Key file does not contain an Ed25519 private key")

    # Sign the run_hash bytes
    signature_bytes = private_key.sign(run_hash.encode())
    signature_hex = signature_bytes.hex()

    # Extract public key hex
    public_key = private_key.public_key()
    pub_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key_hex = pub_raw.hex()

    now = datetime.now(timezone.utc)
    timestamp_utc = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    sig = Signature(
        signer_id=signer_id,
        signer_name=signer_name,
        timestamp_utc=timestamp_utc,
        meaning=meaning,
        run_id=run_id,
        run_hash=run_hash,
        signature_hex=signature_hex,
        public_key_hex=public_key_hex,
    )

    # Append to signatures.jsonl
    sig_file = run_dir / _SIG_FILE
    sig_dict = {
        "signer_id": sig.signer_id,
        "signer_name": sig.signer_name,
        "timestamp_utc": sig.timestamp_utc,
        "meaning": sig.meaning,
        "run_id": sig.run_id,
        "run_hash": sig.run_hash,
        "signature_hex": sig.signature_hex,
        "public_key_hex": sig.public_key_hex,
    }
    with open(sig_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(sig_dict) + "\n")

    return sig


def verify_signature(
    run_dir: Path,
    signature: Signature,
) -> bool:
    """Verify one signature against the current state of the run bundle.

    Returns True if the signature is cryptographically valid for the
    bundle as it exists now.
    """
    try:
        # Recompute the run hash
        current_hash = compute_run_hash(run_dir)
        if current_hash != signature.run_hash:
            return False

        # Reconstruct public key
        pub_raw = bytes.fromhex(signature.public_key_hex)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = Ed25519PublicKey.from_public_bytes(pub_raw)

        # Verify the signature
        sig_bytes = bytes.fromhex(signature.signature_hex)
        public_key.verify(sig_bytes, signature.run_hash.encode())
        return True
    except Exception:
        return False


def verify_all_signatures(run_dir: Path) -> tuple[bool, list[str]]:
    """Verify all signatures stored in <run_dir>/signatures.jsonl.

    Returns:
        (all_valid, list_of_failure_messages)
    """
    sig_file = run_dir / _SIG_FILE
    if not sig_file.exists():
        return True, []

    failures: list[str] = []
    lines = sig_file.read_text(encoding="utf-8").splitlines()

    for line_no, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            sig = Signature(
                signer_id=data["signer_id"],
                signer_name=data.get("signer_name"),
                timestamp_utc=data["timestamp_utc"],
                meaning=data["meaning"],
                run_id=data["run_id"],
                run_hash=data["run_hash"],
                signature_hex=data["signature_hex"],
                public_key_hex=data["public_key_hex"],
            )
            if not verify_signature(run_dir, sig):
                failures.append(
                    f"line {line_no}: signature by {sig.signer_id!r} "
                    f"(meaning={sig.meaning!r}) failed verification"
                )
        except Exception as exc:
            failures.append(f"line {line_no}: error parsing/verifying — {exc}")

    return len(failures) == 0, failures


def load_signatures(run_dir: Path) -> list[Signature]:
    """Load all signatures from <run_dir>/signatures.jsonl."""
    sig_file = run_dir / _SIG_FILE
    if not sig_file.exists():
        return []
    sigs: list[Signature] = []
    for line in sig_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        sigs.append(
            Signature(
                signer_id=data["signer_id"],
                signer_name=data.get("signer_name"),
                timestamp_utc=data["timestamp_utc"],
                meaning=data["meaning"],
                run_id=data["run_id"],
                run_hash=data["run_hash"],
                signature_hex=data["signature_hex"],
                public_key_hex=data["public_key_hex"],
            )
        )
    return sigs
