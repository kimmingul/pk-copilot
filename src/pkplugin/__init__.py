"""pk-copilot — Phoenix WinNonlin-compatible PK/PD/NCA/Compartmental analysis.

v2.0 Regulated-Capable Edition.  All NCA, BE, compartmental PK, PD, CDISC
SDTM/ADaM, and Part 11-enabling technical controls are available via both
the MCP server (``pkplugin.mcp_server``) and the CLI (``pkplugin`` console
script).

Regulatory note: pk-copilot is NOT a 21 CFR Part 11 compliant system on
its own. v2.0 provides Part 11-ENABLING technical controls (audit chain,
e-signatures, RBAC, WORM lock) for the deterministic CLI/MCP execution
path. Actual compliance depends on the sponsor's predicate-rule
determination, validated deployment, SOPs, training, account governance,
audit review, and record-retention procedures under the customer's QMS.
LLM/chat orchestration is exploratory by default.

See docs/10-21cfr-part11.md (§16 disclaimer, §17 execution modes),
docs/13-compliance-matrix.md, and docs/14-llm-boundary-disclosure.md.
"""

__version__ = "2.0.2"

from pkplugin.version import WNVersion

__all__ = ["WNVersion", "__version__"]
