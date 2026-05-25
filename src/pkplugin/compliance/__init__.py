"""Part 11 compliance technical controls for pk-copilot v2.0.

This package provides Part 11-enabling controls for the deterministic
execution path. Actual 21 CFR Part 11 compliance depends on the sponsor's
predicate-rule determination, validated deployment, SOPs, training, account
governance, audit review, and record-retention procedures under the
customer's QMS.

See docs/10-21cfr-part11.md and docs/14-llm-boundary-disclosure.md.
"""

from __future__ import annotations

import os
from typing import Literal

ExecutionMode = Literal["exploratory", "controlled"]


def classify_execution_mode(
    user: dict[str, str] | None = None,
    *,
    part11_enabled_env: str = "PKPLUGIN_PART11_ENABLED",
) -> ExecutionMode:
    """Classify the current MCP/CLI call as exploratory or controlled.

    Controlled mode requires BOTH:
    - PKPLUGIN_PART11_ENABLED=1 in the environment (organization opt-in)
    - A non-None ``user`` dict identifying the caller

    Any other configuration falls back to exploratory mode.

    Refs:
        docs/10-21cfr-part11.md §17
        docs/14-llm-boundary-disclosure.md
    """
    if os.environ.get(part11_enabled_env) != "1":
        return "exploratory"
    if not user or not user.get("id"):
        return "exploratory"
    return "controlled"


__all__ = ["ExecutionMode", "classify_execution_mode"]
