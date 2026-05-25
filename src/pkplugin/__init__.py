"""pk-copilot — Phoenix WinNonlin-compatible PK/PD/NCA/Compartmental analysis.

v2.0 Regulated Edition.  All NCA, BE, compartmental PK, PD, CDISC SDTM/ADaM,
and 21 CFR Part 11 technical controls are available via both the MCP server
(``pkplugin.mcp_server``) and the CLI (``pkplugin`` console script).

Regulatory note: v2.0 provides the TECHNICAL controls (audit chain,
e-signatures, RBAC, WORM lock) needed for 21 CFR Part 11 workflows.
Procedural controls (SOPs, training records, account governance, periodic
audit review) remain the customer organization's responsibility.  See
docs/10-21cfr-part11.md §16 for the full disclaimer and compliance matrix.
"""

__version__ = "2.0.0"

from pkplugin.version import WNVersion

__all__ = ["WNVersion", "__version__"]
