"""pk-copilot — Phoenix WinNonlin-compatible PK/PD/NCA/Compartmental analysis.

v1.0 Production Release.  All NCA, BE, compartmental PK, and PD workflows are
available via both the MCP server (``pkplugin.mcp_server``) and the CLI
(``pkplugin`` console script).

Regulatory note: v1.0 is NOT a 21 CFR Part 11 compliant system.  Part 11
technical controls are planned for v2.0.  See docs/10-21cfr-part11.md.
"""

__version__ = "2.0.0"

from pkplugin.version import WNVersion

__all__ = ["WNVersion", "__version__"]
