"""
Tests for Part 11 CLI subcommands (≥4 tests).

Tests:
 1. pkplugin keygen generates key files.
 2. pkplugin sign signs a run.
 3. pkplugin verify-chain on empty dir returns ok.
 4. pkplugin compliance-status returns Part 11 info.
 5. pkplugin verify-sigs on unsigned run returns ok.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pkplugin.cli import main
from pkplugin.compliance.signatures import generate_keypair, save_private_key, sign_run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _make_run(tmp_path: Path, run_id: str = "cli-test-run") -> Path:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "parameters.csv").write_text("subject_id,value\nS01,42.0\n")
    (run_dir / "audit.json").write_text(f'{{"run_id": "{run_id}"}}')
    return run_dir


# ---------------------------------------------------------------------------
# 1. pkplugin keygen generates key files
# ---------------------------------------------------------------------------


def test_cmd_keygen(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    key_path = str(tmp_path / "test.key")
    code, out, err = _run(["keygen", "--output", key_path], capsys)
    assert code == 0, f"stderr: {err}"
    result = json.loads(out)
    assert result["status"] == "ok"
    assert Path(result["private_key_path"]).exists()
    assert Path(result["public_key_path"]).exists()
    assert len(result["public_key_hex"]) == 64


# ---------------------------------------------------------------------------
# 2. pkplugin sign signs a run
# ---------------------------------------------------------------------------


def test_cmd_sign(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_id = "cli-sign-run"
    _make_run(tmp_path, run_id)

    # Generate a key first
    kp = generate_keypair()
    key_path = tmp_path / "analyst.key"
    save_private_key(kp, key_path)

    code, out, err = _run(
        [
            "sign", run_id,
            "--identity", "analyst@example.com",
            "--meaning", "authored",
            "--key", str(key_path),
            "--auth-token", "test-session-token",
            "--out", str(tmp_path),
        ],
        capsys,
    )
    assert code == 0, f"stderr: {err}"
    result = json.loads(out)
    assert result["status"] == "ok"
    assert result["meaning"] == "authored"
    assert result["auth_token_verified"] == "caller_attestation"


# ---------------------------------------------------------------------------
# 3. pkplugin verify-chain on empty dir returns ok
# ---------------------------------------------------------------------------


def test_cmd_verify_chain_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    chain_dir = tmp_path / "empty_chain"
    chain_dir.mkdir()
    code, out, err = _run(["verify-chain", "--chain-dir", str(chain_dir)], capsys)
    assert code == 0, f"stderr: {err}"
    result = json.loads(out)
    assert result["status"] == "ok"
    assert result["ok"] is True
    assert result["n_entries"] == 0


# ---------------------------------------------------------------------------
# 4. pkplugin compliance-status
# ---------------------------------------------------------------------------


def test_cmd_compliance_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(["compliance-status"], capsys)
    assert code == 0, f"stderr: {err}"
    result = json.loads(out)
    assert "part11_version" in result
    assert result["part11_version"] == "v2.0"
    assert result["cryptography_available"] is True
    assert "controls" in result


# ---------------------------------------------------------------------------
# 5. pkplugin verify-sigs on unsigned run returns ok
# ---------------------------------------------------------------------------


def test_cmd_verify_sigs_unsigned(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_id = "cli-verify-no-sigs"
    _make_run(tmp_path, run_id)

    code, out, err = _run(
        ["verify-sigs", run_id, "--out", str(tmp_path)],
        capsys,
    )
    assert code == 0, f"stderr: {err}"
    result = json.loads(out)
    assert result["status"] == "ok"
    assert result["n_signatures"] == 0


# ---------------------------------------------------------------------------
# M2. keygen refuses to overwrite without --force
# ---------------------------------------------------------------------------


def test_cmd_keygen_refuses_overwrite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """keygen returns error if key file already exists and --force is not given."""
    key_path = str(tmp_path / "existing.key")
    # First call — succeeds
    code, out, err = _run(["keygen", "--output", key_path], capsys)
    assert code == 0, f"First keygen failed: {err}"

    # Second call without --force — must fail
    code2, out2, err2 = _run(["keygen", "--output", key_path], capsys)
    assert code2 != 0, "Expected non-zero exit when key file already exists"
    result2 = json.loads(err2)
    assert result2["status"] == "error"
    assert "already exists" in result2["error"]


def test_cmd_keygen_force_overwrites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """keygen with --force overwrites an existing key file."""
    key_path = str(tmp_path / "existing.key")
    code, _, _ = _run(["keygen", "--output", key_path], capsys)
    assert code == 0

    first_key = Path(key_path).read_bytes()

    code2, out2, _ = _run(["keygen", "--output", key_path, "--force"], capsys)
    assert code2 == 0, "keygen --force should succeed"
    result2 = json.loads(out2)
    assert result2["status"] == "ok"

    # Key bytes should differ (new random key generated)
    second_key = Path(key_path).read_bytes()
    assert first_key != second_key


# ---------------------------------------------------------------------------
# H3. impl_sign_record rejects empty auth_token
# ---------------------------------------------------------------------------


def test_cmd_sign_empty_auth_token_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """sign with no --auth-token (empty string) returns error."""
    run_id = "h3-no-auth-run"
    _make_run(tmp_path, run_id)
    kp = generate_keypair()
    key_path = tmp_path / "analyst.key"
    save_private_key(kp, key_path)

    # Explicitly pass empty auth-token
    code, out, err = _run(
        [
            "sign", run_id,
            "--identity", "analyst@example.com",
            "--meaning", "authored",
            "--key", str(key_path),
            "--auth-token", "",
            "--out", str(tmp_path),
        ],
        capsys,
    )
    assert code != 0
    # Error may appear in stdout or stderr depending on impl
    combined = out + err
    assert "auth_token" in combined.lower() or "error" in combined.lower()
