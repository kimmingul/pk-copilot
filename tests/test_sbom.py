"""
Tests for pkplugin.sbom.generate_sbom.

Tests:
  1. SBOM contains pkplugin, numpy, scipy, and pandas components.
  2. JSON output is valid + parsable.
  3. All components have name, version, and purl fields.
  4. Timestamp is ISO 8601 UTC with Z suffix.
"""

from __future__ import annotations

import json
import re

from pkplugin.sbom import generate_sbom

# ---------------------------------------------------------------------------
# Test 1 — key packages present
# ---------------------------------------------------------------------------


def test_sbom_contains_key_packages() -> None:
    """SBOM must include pkplugin, numpy, scipy, and pandas components."""
    raw = generate_sbom(format="cyclonedx-json")
    doc = json.loads(raw)
    names = {c["name"].lower() for c in doc["components"]}
    for required in ("pk-copilot", "numpy", "scipy", "pandas"):
        assert required in names, (
            f"Expected {required!r} in SBOM components; found: {sorted(names)}"
        )


# ---------------------------------------------------------------------------
# Test 2 — JSON validity
# ---------------------------------------------------------------------------


def test_sbom_json_valid_and_parsable() -> None:
    """generate_sbom(cyclonedx-json) must return valid JSON with expected top-level keys."""
    raw = generate_sbom(format="cyclonedx-json")
    doc = json.loads(raw)
    assert doc["bomFormat"] == "CycloneDX"
    assert doc["specVersion"] == "1.6"
    assert doc["version"] == 1
    assert "metadata" in doc
    assert "components" in doc
    assert len(doc["components"]) > 0


# ---------------------------------------------------------------------------
# Test 3 — all components have required fields
# ---------------------------------------------------------------------------


def test_sbom_components_have_required_fields() -> None:
    """Every component must have non-empty name, version, and purl."""
    raw = generate_sbom(format="cyclonedx-json")
    doc = json.loads(raw)
    for comp in doc["components"]:
        assert "name" in comp and comp["name"], f"Missing name in: {comp}"
        assert "version" in comp and comp["version"], f"Missing version in: {comp}"
        assert "purl" in comp and comp["purl"].startswith("pkg:pypi/"), f"Bad purl in: {comp}"


# ---------------------------------------------------------------------------
# Test 4 — timestamp is ISO 8601 UTC with Z suffix
# ---------------------------------------------------------------------------


def test_sbom_timestamp_iso8601_utc() -> None:
    """Metadata timestamp must match YYYY-MM-DDTHH:MM:SSZ format."""
    raw = generate_sbom(format="cyclonedx-json")
    doc = json.loads(raw)
    ts = doc["metadata"]["timestamp"]
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    assert re.match(pattern, ts), f"Timestamp {ts!r} does not match ISO 8601 UTC (Z suffix)"
