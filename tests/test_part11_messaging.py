"""Regression tests for v2.0.1 Part 11 messaging precision.

Locks in the positioning shift from 'Part 11 compliant' overclaim to
'Part 11-enabling controls for the deterministic execution path; LLM
orchestration exploratory unless qualified under customer QMS'.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------- README and docs static checks ----------


def test_readme_does_not_overclaim_part11_compliance():
    """README must NOT claim 'Part 11 compliant' as positive statement."""
    text = (REPO_ROOT / "README.md").read_text()
    lower = text.lower()
    # We allow the documented disclaimer phrase "is NOT a 21 CFR Part 11 compliant"
    assert "is not a 21 cfr part 11 compliant" in lower or "compliant 시스템이 아닙니다" in lower, (
        "README must explicitly state 'NOT compliant' somewhere"
    )


def test_readme_uses_enabling_language():
    text = (REPO_ROOT / "README.md").read_text().lower()
    assert "part 11-enabling" in text, "README should describe controls as 'Part 11-enabling'"


def test_readme_has_execution_modes_section():
    text = (REPO_ROOT / "README.md").read_text()
    assert "Execution Modes" in text or "execution mode" in text.lower()
    assert "exploratory" in text.lower()
    assert "controlled" in text.lower()


def test_init_docstring_says_not_compliant():
    init = (REPO_ROOT / "src" / "pkplugin" / "__init__.py").read_text()
    assert "NOT a 21 CFR Part 11 compliant" in init or "is NOT a 21 CFR Part 11 compliant" in init


def test_init_docstring_says_enabling():
    init = (REPO_ROOT / "src" / "pkplugin" / "__init__.py").read_text()
    assert "Part 11-ENABLING" in init or "Part 11-enabling" in init


def test_init_docstring_mentions_new_docs():
    init = (REPO_ROOT / "src" / "pkplugin" / "__init__.py").read_text()
    assert "docs/13" in init or "compliance-matrix" in init
    assert "docs/14" in init or "llm-boundary" in init


# ---------- New docs exist ----------


@pytest.mark.parametrize(
    "path",
    [
        "docs/12-intended-use.md",
        "docs/13-compliance-matrix.md",
        "docs/14-llm-boundary-disclosure.md",
    ],
)
def test_new_docs_exist(path: str) -> None:
    assert (REPO_ROOT / path).is_file(), f"missing {path}"


def test_intended_use_says_not_medical_device():
    text = (REPO_ROOT / "docs" / "12-intended-use.md").read_text().lower()
    # The doc uses "의료기기(medical device)가 아닙니다" or English "not a medical device"
    assert "medical device" in text and ("아닙니다" in text or "not a" in text)


def test_compliance_matrix_has_two_columns():
    text = (REPO_ROOT / "docs" / "13-compliance-matrix.md").read_text()
    # Table splits responsibility: pk-copilot 제공 (provides) vs. 사용자 조직 (organization)
    assert "제공" in text or "provides" in text.lower()
    assert "조직" in text or "organization" in text.lower()


# ---------- API surface for the execution mode classifier ----------


def test_classify_execution_mode_default_exploratory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PKPLUGIN_PART11_ENABLED", raising=False)
    from pkplugin.compliance import classify_execution_mode

    assert classify_execution_mode(user={"id": "a"}) == "exploratory"


def test_classify_execution_mode_controlled_requires_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PKPLUGIN_PART11_ENABLED", "1")
    from pkplugin.compliance import classify_execution_mode

    assert classify_execution_mode(user=None) == "exploratory"
    assert classify_execution_mode(user={"id": ""}) == "exploratory"
    assert classify_execution_mode(user={"id": "analyst@example.com"}) == "controlled"


def test_classify_execution_mode_env_zero_is_exploratory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PKPLUGIN_PART11_ENABLED", "0")
    from pkplugin.compliance import classify_execution_mode

    assert classify_execution_mode(user={"id": "x"}) == "exploratory"


# ---------- impl_get_compliance_status surfaces the new fields ----------


def test_compliance_status_has_execution_mode_supported() -> None:
    from pkplugin.mcp_server import impl_get_compliance_status

    result = impl_get_compliance_status()
    assert "execution_mode_supported" in result
    assert set(result["execution_mode_supported"]) == {"exploratory", "controlled"}


def test_compliance_status_disclaimer_mentions_enabling() -> None:
    from pkplugin.mcp_server import impl_get_compliance_status

    result = impl_get_compliance_status()
    text = (result.get("disclaimer") or "").lower()
    assert "part 11-enabling" in text
    assert "exploratory" in text


def test_compliance_status_part11_claim_is_enabling() -> None:
    from pkplugin.mcp_server import impl_get_compliance_status

    result = impl_get_compliance_status()
    assert result.get("part11_claim") == "enabling-controls-only"
