"""
R backend probe and subprocess runners for PKNCA / NonCompart cross-validation.

Detects whether a local Rscript installation is available and, if so, can run
the bundled R scripts to produce parameter tables comparable with pk-copilot.

No R installation is required for the test suite — callers should inspect
RBackendStatus.available before invoking run_r_pknca / run_r_noncompart.

Refs: docs/08-validation-strategy.md §4
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Status probe
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RBackendStatus:
    """Result of probing the local R installation."""

    available: bool
    rscript_path: str | None
    r_version: str | None
    pknca_version: str | None
    noncompart_version: str | None
    error: str | None


def check_r_backend() -> RBackendStatus:
    """Probe the local R installation and key packages.

    Returns an RBackendStatus regardless of whether R is installed.
    When R is absent or a required package is missing, ``available`` is False
    and ``error`` contains a human-readable reason.
    """
    rscript = shutil.which("Rscript")
    if rscript is None:
        return RBackendStatus(
            available=False,
            rscript_path=None,
            r_version=None,
            pknca_version=None,
            noncompart_version=None,
            error="Rscript not found in PATH",
        )

    # Probe R version + package versions in one subprocess call.
    r_code = (
        "cat(paste0('R_VERSION=', R.version$major, '.', R.version$minor, '\n'));"
        "pknca_v <- tryCatch(as.character(packageVersion('PKNCA')), "
        "  error=function(e) 'MISSING');"
        "nc_v <- tryCatch(as.character(packageVersion('NonCompart')), "
        "  error=function(e) 'MISSING');"
        "cat(paste0('PKNCA=', pknca_v, '\n'));"
        "cat(paste0('NONCOMPART=', nc_v, '\n'));"
    )
    try:
        proc = subprocess.run(
            [rscript, "-e", r_code],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return RBackendStatus(
            available=False,
            rscript_path=rscript,
            r_version=None,
            pknca_version=None,
            noncompart_version=None,
            error=f"R probe subprocess failed: {exc}",
        )

    if proc.returncode != 0:
        return RBackendStatus(
            available=False,
            rscript_path=rscript,
            r_version=None,
            pknca_version=None,
            noncompart_version=None,
            error=f"R probe exited {proc.returncode}: {proc.stderr.strip()}",
        )

    # Parse key=value lines from stdout.
    parsed: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            parsed[key.strip()] = val.strip()

    r_version = parsed.get("R_VERSION")
    pknca_version: str | None = parsed.get("PKNCA")
    noncompart_version: str | None = parsed.get("NONCOMPART")

    if pknca_version == "MISSING":
        pknca_version = None
    if noncompart_version == "MISSING":
        noncompart_version = None

    pknca_ok = pknca_version is not None
    nc_ok = noncompart_version is not None

    if not (pknca_ok or nc_ok):
        error: str | None = "Neither PKNCA nor NonCompart is installed"
    elif not pknca_ok:
        error = "PKNCA package not installed"
    elif not nc_ok:
        error = "NonCompart package not installed"
    else:
        error = None

    available = pknca_ok and nc_ok

    return RBackendStatus(
        available=available,
        rscript_path=rscript,
        r_version=r_version,
        pknca_version=pknca_version,
        noncompart_version=noncompart_version,
        error=error,
    )


# ---------------------------------------------------------------------------
# NCA result from R subprocess
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RNCAResult:
    """Output from one R NCA subprocess run."""

    backend: Literal["PKNCA", "NonCompart"]
    parameter_table_csv: Path  # path to a CSV produced by the R script
    raw_stdout: str
    raw_stderr: str
    return_code: int


# ---------------------------------------------------------------------------
# Script path helper
# ---------------------------------------------------------------------------


def _scripts_dir() -> Path:
    """Return the absolute path to the pk-copilot scripts/ directory.

    Resolves relative to this file's location:
      src/pkplugin/validation/r_backend.py → ../../.. → project root → scripts/
    """
    return Path(__file__).resolve().parent.parent.parent.parent / "scripts"


# ---------------------------------------------------------------------------
# PKNCA runner
# ---------------------------------------------------------------------------


def run_r_pknca(
    dataset_csv: Path,
    dose_csv: Path | None,
    output_dir: Path,
    *,
    auc_method: str = "linear up log down",
    timeout_sec: int = 60,
) -> RNCAResult:
    """Invoke scripts/run_r_pknca.R via Rscript subprocess.

    Args:
        dataset_csv: Path to the concentration CSV (must exist).
        dose_csv: Optional path to the dose CSV.
        output_dir: Directory where the R script writes its output CSV.
        auc_method: AUC integration method string passed to PKNCA.
        timeout_sec: Subprocess timeout in seconds.

    Returns:
        RNCAResult with backend="PKNCA".

    Raises:
        ValueError: If dataset_csv does not exist.
    """
    dataset_csv = Path(dataset_csv).resolve()
    if not dataset_csv.is_file():
        raise ValueError(f"Input dataset not found: {dataset_csv}")

    rscript = shutil.which("Rscript")
    if rscript is None:
        raise RuntimeError("Rscript not found in PATH")

    script = _scripts_dir() / "run_r_pknca.R"
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_csv = output_dir / "pknca_parameters.csv"

    cmd: list[str] = [
        rscript,
        str(script),
        "--input",
        str(dataset_csv),
        "--output",
        str(output_csv),
        "--auc-method",
        auc_method,
    ]
    if dose_csv is not None:
        dose_csv = Path(dose_csv).resolve()
        cmd.extend(["--dose", str(dose_csv)])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"run_r_pknca.R timed out after {timeout_sec}s") from exc

    return RNCAResult(
        backend="PKNCA",
        parameter_table_csv=output_csv,
        raw_stdout=proc.stdout,
        raw_stderr=proc.stderr,
        return_code=proc.returncode,
    )


# ---------------------------------------------------------------------------
# NonCompart runner
# ---------------------------------------------------------------------------


def run_r_noncompart(
    dataset_csv: Path,
    dose_csv: Path | None,
    output_dir: Path,
    *,
    timeout_sec: int = 60,
) -> RNCAResult:
    """Invoke scripts/run_r_noncompart.R via Rscript subprocess.

    Args:
        dataset_csv: Path to the concentration CSV (must exist).
        dose_csv: Optional path to the dose CSV.
        output_dir: Directory where the R script writes its output CSV.
        timeout_sec: Subprocess timeout in seconds.

    Returns:
        RNCAResult with backend="NonCompart".

    Raises:
        ValueError: If dataset_csv does not exist.
    """
    dataset_csv = Path(dataset_csv).resolve()
    if not dataset_csv.is_file():
        raise ValueError(f"Input dataset not found: {dataset_csv}")

    rscript = shutil.which("Rscript")
    if rscript is None:
        raise RuntimeError("Rscript not found in PATH")

    script = _scripts_dir() / "run_r_noncompart.R"
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_csv = output_dir / "noncompart_parameters.csv"

    cmd: list[str] = [
        rscript,
        str(script),
        "--input",
        str(dataset_csv),
        "--output",
        str(output_csv),
    ]
    if dose_csv is not None:
        dose_csv = Path(dose_csv).resolve()
        cmd.extend(["--dose", str(dose_csv)])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"run_r_noncompart.R timed out after {timeout_sec}s") from exc

    return RNCAResult(
        backend="NonCompart",
        parameter_table_csv=output_csv,
        raw_stdout=proc.stdout,
        raw_stderr=proc.stderr,
        return_code=proc.returncode,
    )
