"""
Tests for src/pkplugin/validation/r_backend.py

All tests run without R installed — subprocess calls are mocked where needed.

Tests:
  1. check_r_backend() returns a populated RBackendStatus (R absent on CI).
  2. When shutil.which("Rscript") returns None, status.available is False.
  3. Mock subprocess success → status.available is True.
  4. run_r_pknca raises ValueError on missing input file.
  5. run_r_noncompart raises ValueError on missing input file.
  6. RBackendStatus is frozen (immutable).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pkplugin.validation.r_backend import (
    RBackendStatus,
    check_r_backend,
    run_r_noncompart,
    run_r_pknca,
)

# ---------------------------------------------------------------------------
# 1. check_r_backend() always returns a populated status
# ---------------------------------------------------------------------------


def test_check_r_backend_returns_status() -> None:
    """check_r_backend() always returns a valid RBackendStatus regardless of R."""
    status = check_r_backend()
    assert isinstance(status, RBackendStatus)
    # Fields are populated (not unset)
    assert isinstance(status.available, bool)
    assert status.error is None or isinstance(status.error, str)


# ---------------------------------------------------------------------------
# 2. Rscript absent → available=False
# ---------------------------------------------------------------------------


def test_check_r_backend_no_rscript() -> None:
    """When Rscript is not in PATH, status.available must be False."""
    with patch("pkplugin.validation.r_backend.shutil.which", return_value=None):
        status = check_r_backend()

    assert status.available is False
    assert status.rscript_path is None
    assert status.r_version is None
    assert status.error is not None
    assert "Rscript" in status.error


# ---------------------------------------------------------------------------
# 3. Mocked subprocess success → available=True
# ---------------------------------------------------------------------------


def test_check_r_backend_mocked_success() -> None:
    """When subprocess returns R + both packages, status.available is True."""
    mock_stdout = "R_VERSION=4.3.1\nPKNCA=0.11.0\nNONCOMPART=0.6.0\n"
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = mock_stdout
    mock_proc.stderr = ""

    with (
        patch("pkplugin.validation.r_backend.shutil.which", return_value="/usr/bin/Rscript"),
        patch("pkplugin.validation.r_backend.subprocess.run", return_value=mock_proc),
    ):
        status = check_r_backend()

    assert status.available is True
    assert status.rscript_path == "/usr/bin/Rscript"
    assert status.r_version == "4.3.1"
    assert status.pknca_version == "0.11.0"
    assert status.noncompart_version == "0.6.0"
    assert status.error is None


# ---------------------------------------------------------------------------
# 3b. One package missing → available=False, correct error
# ---------------------------------------------------------------------------


def test_check_r_backend_pknca_missing() -> None:
    """When PKNCA is MISSING, status.available is False."""
    mock_stdout = "R_VERSION=4.3.1\nPKNCA=MISSING\nNONCOMPART=0.6.0\n"
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = mock_stdout
    mock_proc.stderr = ""

    with (
        patch("pkplugin.validation.r_backend.shutil.which", return_value="/usr/bin/Rscript"),
        patch("pkplugin.validation.r_backend.subprocess.run", return_value=mock_proc),
    ):
        status = check_r_backend()

    assert status.available is False
    assert status.pknca_version is None
    assert status.noncompart_version == "0.6.0"


# ---------------------------------------------------------------------------
# 4. run_r_pknca raises ValueError on missing input file
# ---------------------------------------------------------------------------


def test_run_r_pknca_missing_input(tmp_path: Path) -> None:
    """run_r_pknca raises ValueError when dataset_csv does not exist."""
    with pytest.raises(ValueError, match="Input dataset not found"):
        run_r_pknca(
            dataset_csv=tmp_path / "nonexistent.csv",
            dose_csv=None,
            output_dir=tmp_path / "out",
        )


# ---------------------------------------------------------------------------
# 5. run_r_noncompart raises ValueError on missing input file
# ---------------------------------------------------------------------------


def test_run_r_noncompart_missing_input(tmp_path: Path) -> None:
    """run_r_noncompart raises ValueError when dataset_csv does not exist."""
    with pytest.raises(ValueError, match="Input dataset not found"):
        run_r_noncompart(
            dataset_csv=tmp_path / "nonexistent.csv",
            dose_csv=None,
            output_dir=tmp_path / "out",
        )


# ---------------------------------------------------------------------------
# 6. RBackendStatus is frozen
# ---------------------------------------------------------------------------


def test_r_backend_status_frozen() -> None:
    """RBackendStatus is a frozen dataclass — attribute assignment raises."""
    status = RBackendStatus(
        available=False,
        rscript_path=None,
        r_version=None,
        pknca_version=None,
        noncompart_version=None,
        error="test",
    )
    with pytest.raises((AttributeError, TypeError)):
        status.available = True  # type: ignore[misc]
