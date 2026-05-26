"""
JSON-of-record producer for pk-copilot.

Every MCP tool call produces an AuditEntry that is serialised to:
  <audit_dir>/<run_id>/audit.json   — machine-readable JSON-of-record
  <audit_dir>/<run_id>/audit.md     — human-readable companion

Refs:
- docs/05-data-schemas.md §6 — JSON-of-record schema
- docs/01-architecture.md   — Audit-First design principle
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def file_sha256(path: str | Path) -> str:
    """Return the hex-encoded SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def new_run_id(prefix: str = "") -> str:
    """Generate a sortable run ID.

    Format: ``YYYY-MM-DD-HHMMSS-<6-hex>``
    Example: ``2026-05-25-091523-7f3a8b``

    Args:
        prefix: Optional string prepended before the timestamp (with a hyphen
                separator if non-empty).

    Returns:
        Unique run-ID string safe for use as a directory name.
    """
    now = datetime.now(UTC)
    timestamp = now.strftime("%Y-%m-%d-%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    parts = [p for p in (prefix, timestamp, short_uuid) if p]
    return "-".join(parts)


def collect_dependency_versions(
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Collect installed package versions for reproducibility.

    Gathers numpy, scipy, pandas, pydantic, and pkplugin.
    Caller-supplied *extra* entries are merged in (caller wins on collision).

    Args:
        extra: Additional ``{package: version}`` entries to include.

    Returns:
        Dict mapping package name to version string.
        Missing packages are recorded as ``"not-installed"``.
    """
    versions: dict[str, str] = {}

    def _pkg_version(name: str) -> str:
        try:
            import importlib.metadata as meta

            return meta.version(name)
        except Exception:
            return "not-installed"

    for pkg in ("numpy", "scipy", "pandas", "pydantic"):
        versions[pkg] = _pkg_version(pkg)

    # pkplugin self-version
    try:
        import importlib.metadata as meta

        from pkplugin.version import WNVersion  # noqa: F401 — just importing to check

        versions["pkplugin"] = meta.version("pk-copilot")
    except Exception:
        try:
            import importlib.metadata as meta

            versions["pkplugin"] = meta.version("pkplugin")
        except Exception:
            versions["pkplugin"] = "not-installed"

    if extra:
        versions.update(extra)

    return versions


def collect_os_info() -> dict[str, str]:
    """Collect operating-system metadata.

    Returns:
        Dict with keys ``platform``, ``release``, ``python``.
    """
    return {
        "platform": platform.system().lower(),
        "release": platform.release(),
        "python": sys.version.split()[0],
    }


def audit_dir_default() -> Path:
    """Resolve the default audit output directory.

    Uses ``$PKPLUGIN_AUDIT_DIR`` env var when set, otherwise ``$CWD/pk_runs``.

    Returns:
        Resolved :class:`~pathlib.Path`.
    """
    env_val = os.environ.get("PKPLUGIN_AUDIT_DIR", "")
    if env_val.strip():
        return Path(env_val)
    return Path.cwd() / "pk_runs"


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------


@dataclass
class AuditEntry:
    """Complete audit record for one MCP tool invocation.

    Serialises to JSON-of-record (audit.json) and a human-readable
    Markdown companion (audit.md) via :meth:`write`.

    Refs: docs/05-data-schemas.md §6
    """

    run_id: str
    tool: str  # e.g. "run_nca"
    timestamp_utc: str  # ISO 8601 with 'Z' suffix
    pkplugin_version: str
    winnonlin_compat: str  # e.g. "6.4"
    user: str | None  # placeholder; None in v0.1
    input_files: list[dict[str, str]]  # [{"path": ..., "sha256": ...}]
    config: dict[str, Any]
    dependency_versions: dict[str, str]
    os_info: dict[str, str]
    results: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    artifacts: list[dict[str, str]] = field(default_factory=list)
    execution_mode: str = "exploratory"
    llm_orchestrated: bool = False
    llm_transcript_hash: str | None = None
    # TODO(v2): e-signature
    # signature: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict representation suitable for JSON serialisation."""
        return {
            "run_id": self.run_id,
            "run_timestamp_utc": self.timestamp_utc,
            "pkplugin_version": self.pkplugin_version,
            "winnonlin_compat": self.winnonlin_compat,
            "user": self.user,
            "tool": self.tool,
            "input_files": self.input_files,
            "config": self.config,
            "dependency_versions": self.dependency_versions,
            "os": self.os_info,
            "results": self.results,
            "warnings": self.warnings,
            "artifacts": self.artifacts,
            "execution_mode": self.execution_mode,
            "llm_orchestrated": self.llm_orchestrated,
            "llm_transcript_hash": self.llm_transcript_hash,
            # TODO(v2): "signature": self.signature,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def write(self, audit_dir: str | Path) -> Path:
        """Write audit.json and audit.md into ``<audit_dir>/<run_id>/``.

        Both files are written atomically (write-to-temp then rename is
        *not* used here for simplicity, but the directory is always created
        before writing so partial-directory states cannot occur).

        Args:
            audit_dir: Root directory for all audit records.  The run
                       sub-directory ``<audit_dir>/<run_id>/`` is created
                       automatically.

        Returns:
            Absolute :class:`~pathlib.Path` to ``audit.json``.
        """
        run_dir = Path(audit_dir) / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        json_path = run_dir / "audit.json"
        md_path = run_dir / "audit.md"

        # --- JSON-of-record ---
        payload = self.to_dict()
        json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        # --- Markdown companion ---
        md_path.write_text(
            self._render_markdown(),
            encoding="utf-8",
        )

        return json_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _render_markdown(self) -> str:
        """Render the human-readable audit.md companion."""
        lines: list[str] = []

        lines.append(f"# Audit Log — {self.run_id}")
        lines.append("")
        # Execution mode badge — shown prominently at top
        if self.execution_mode == "controlled":
            lines.append(
                "> **[CONTROLLED]** — QMS-validated execution path. "
                "Verify with `pkplugin verify-chain`."
            )
        else:
            lines.append(
                "> **[EXPLORATORY]** — Not for regulatory submission records. "
                "See docs/10-21cfr-part11.md §17."
            )
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        lines.append(f"| **Run ID** | `{self.run_id}` |")
        lines.append(f"| **Tool** | `{self.tool}` |")
        lines.append(f"| **Timestamp (UTC)** | {self.timestamp_utc} |")
        lines.append(f"| **pk-copilot version** | {self.pkplugin_version} |")
        lines.append(f"| **WinNonlin compat** | {self.winnonlin_compat} |")
        lines.append(f"| **User** | {self.user or '(not set)'} |")
        lines.append(f"| **Execution Mode** | {self.execution_mode} |")
        lines.append(f"| **LLM Orchestrated** | {'Yes' if self.llm_orchestrated else 'No'} |")
        if self.llm_transcript_hash:
            lines.append(f"| **LLM Transcript Hash** | `{self.llm_transcript_hash}` |")
        lines.append("")

        # Input files
        lines.append("## Input Files")
        lines.append("")
        if self.input_files:
            lines.append("| Path | SHA-256 (12 chars) |")
            lines.append("|---|---|")
            for f in self.input_files:
                sha_short = f.get("sha256", "")[:12]
                lines.append(f"| `{f.get('path', '')}` | `{sha_short}` |")
        else:
            lines.append("_(no input files recorded)_")
        lines.append("")

        # Config
        lines.append("## Configuration")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(self.config, indent=2, ensure_ascii=False, default=str))
        lines.append("```")
        lines.append("")

        # Warnings
        lines.append("## Warnings")
        lines.append("")
        if self.warnings:
            for w in self.warnings:
                lines.append(f"- {w}")
        else:
            lines.append("_(none)_")
        lines.append("")

        # Artifacts
        lines.append("## Artifacts")
        lines.append("")
        if self.artifacts:
            lines.append("| Name | SHA-256 (12 chars) |")
            lines.append("|---|---|")
            for a in self.artifacts:
                sha_short = a.get("sha256", "")[:12]
                lines.append(f"| `{a.get('name', '')}` | `{sha_short}` |")
        else:
            lines.append("_(none)_")
        lines.append("")

        # Dependencies
        lines.append("## Dependency Versions")
        lines.append("")
        lines.append("| Package | Version |")
        lines.append("|---|---|")
        for pkg, ver in self.dependency_versions.items():
            lines.append(f"| {pkg} | {ver} |")
        lines.append("")

        # OS info
        lines.append("## Environment")
        lines.append("")
        lines.append("| Key | Value |")
        lines.append("|---|---|")
        for k, v in self.os_info.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

        # TODO(v2): e-signature section
        lines.append("---")
        lines.append("")
        lines.append(
            "_Generated by pk-copilot audit module. v2.0 will add e-signature (21 CFR Part 11)._"
        )
        lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def new_entry(
    tool: str,
    config: dict[str, Any],
    input_paths: list[str | Path] | None = None,
    winnonlin_compat: str = "6.4",
    extra_dependency_versions: dict[str, str] | None = None,
    execution_mode: str = "exploratory",
    llm_orchestrated: bool = False,
    llm_transcript_hash: str | None = None,
    user: dict[str, str] | None = None,
) -> AuditEntry:
    """Convenience factory that populates all boilerplate fields.

    Args:
        tool: MCP tool name, e.g. ``"run_nca"``.
        config: Resolved algorithm config dict (NCAConfig.resolved() output).
        input_paths: Files to hash and record.  Non-existent paths are
                     skipped with a warning rather than raising.
        winnonlin_compat: WinNonlin compatibility string.
        extra_dependency_versions: Extra ``{pkg: version}`` to merge.
        execution_mode: ``"exploratory"`` (default) or ``"controlled"``.
        llm_orchestrated: Whether this call was initiated via LLM/chat.
        llm_transcript_hash: Optional hash of the LLM transcript for
                             provenance (v2.1 feature; supply when available).

    Returns:
        Populated :class:`AuditEntry` ready for ``write()``.
    """
    now = datetime.now(UTC)
    timestamp_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    input_files: list[dict[str, str]] = []
    for p in input_paths or []:
        p = Path(p)
        if p.exists():
            input_files.append({"path": str(p), "sha256": file_sha256(p)})
        else:
            input_files.append({"path": str(p), "sha256": "file-not-found"})

    dep_versions = collect_dependency_versions(extra_dependency_versions)

    pkplugin_ver = dep_versions.get("pkplugin", "unknown")

    # Format user as a string representation for the audit record.
    user_str: str | None = None
    if user is not None:
        uid = user.get("id") or user.get("username") or str(user)
        user_str = uid

    return AuditEntry(
        run_id=new_run_id(),
        tool=tool,
        timestamp_utc=timestamp_utc,
        pkplugin_version=pkplugin_ver,
        winnonlin_compat=winnonlin_compat,
        user=user_str,
        input_files=input_files,
        config=config,
        dependency_versions=dep_versions,
        os_info=collect_os_info(),
        execution_mode=execution_mode,
        llm_orchestrated=llm_orchestrated,
        llm_transcript_hash=llm_transcript_hash,
    )
