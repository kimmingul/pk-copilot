"""
SBOM generation for pk-copilot.

Generates a Software Bill of Materials (CycloneDX 1.6) using only stdlib.
No external dependencies required.
"""

from __future__ import annotations

import importlib.metadata
import json
from datetime import UTC, datetime
from typing import Literal

from pkplugin import __version__ as _PKPLUGIN_VERSION


def _make_purl(name: str, version: str) -> str:
    """Build a minimal pkg:pypi PURL."""
    # Normalise name: PEP 503 canonical form uses hyphens, lowercase.
    canonical = name.lower().replace("_", "-")
    return f"pkg:pypi/{canonical}@{version}"


def _collect_components() -> list[dict[str, str]]:
    """Return a sorted list of CycloneDX component dicts for all installed pkgs."""
    components: list[dict[str, str]] = []
    for dist in importlib.metadata.distributions():
        meta = dist.metadata
        name: str = meta["Name"] or ""
        version: str = meta["Version"] or ""
        if not name:
            continue
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": _make_purl(name, version),
            }
        )
    # Stable sort by normalised name.
    components.sort(key=lambda c: c["name"].lower())
    return components


def generate_sbom(
    format: Literal["cyclonedx-json", "cyclonedx-xml"] = "cyclonedx-json",
) -> str:
    """Generate a Software Bill of Materials for the current installation.

    Uses importlib.metadata to enumerate all installed packages with their
    versions. Returns the SBOM as a string in the requested format.

    Output schema (cyclonedx-json minimal):
      {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
          "timestamp": "<ISO 8601 UTC with Z suffix>",
          "tools": [{"vendor": "pk-copilot", "name": "sbom", "version": "<pkplugin version>"}]
        },
        "components": [
          {"type": "library", "name": "<pkg>", "version": "<v>", "purl": "pkg:pypi/<name>@<v>"}
        ]
      }

    Args:
        format: "cyclonedx-json" (default) or "cyclonedx-xml".

    Returns:
        SBOM document as a string.
    """
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    components = _collect_components()

    if format == "cyclonedx-json":
        doc: dict[object, object] = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {
                "timestamp": timestamp,
                "tools": [
                    {
                        "vendor": "pk-copilot",
                        "name": "sbom",
                        "version": _PKPLUGIN_VERSION,
                    }
                ],
            },
            "components": components,
        }
        return json.dumps(doc, indent=2)

    # cyclonedx-xml — minimal hand-built XML (no lxml required)
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<bom xmlns="http://cyclonedx.org/schema/bom/1.6" version="1">',
        "  <metadata>",
        f"    <timestamp>{timestamp}</timestamp>",
        "    <tools>",
        "      <tool>",
        "        <vendor>pk-copilot</vendor>",
        "        <name>sbom</name>",
        f"        <version>{_PKPLUGIN_VERSION}</version>",
        "      </tool>",
        "    </tools>",
        "  </metadata>",
        "  <components>",
    ]
    for comp in components:
        name_esc = comp["name"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        ver_esc = comp["version"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        purl_esc = comp["purl"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines += [
            '    <component type="library">',
            f"      <name>{name_esc}</name>",
            f"      <version>{ver_esc}</version>",
            f"      <purl>{purl_esc}</purl>",
            "    </component>",
        ]
    lines += [
        "  </components>",
        "</bom>",
    ]
    return "\n".join(lines)
