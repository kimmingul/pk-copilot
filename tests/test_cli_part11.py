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
            "--out", str(tmp_path),
        ],
        capsys,
    )
    assert code == 0, f"stderr: {err}"
    result = json.loads(out)
    assert result["status"] == "ok"
    assert result["meaning"] == "authored"


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
