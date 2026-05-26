"""CDISC PK NCA Controlled Terminology — PARAMCD / PARAM registry.

Maps between pk-copilot internal parameter names (from nca/engine.py) and
CDISC PARAMCD / PARAM controlled vocabulary.

Refs:
- docs/09-cdisc-support.md §6 — PARAMCD/PARAM mapping table
- CDISC NCA Controlled Terminology (2024-09-27)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParamCodeEntry:
    """One entry in the CDISC PK NCA PARAMCD registry."""

    paramcd: str  # e.g. "AUCLST"
    param: str  # e.g. "AUC From Time of First Dose to Time of Last Measurable Concentration"
    unit: str  # standard ADaM unit, e.g. "ng.h/mL"
    pkcopilot_name: str  # internal canonical name from nca/engine.py, e.g. "AUClast"


# Full registry — required minimum per deliverable spec.
PARAMCD_REGISTRY: dict[str, ParamCodeEntry] = {
    "CMAX": ParamCodeEntry(
        "CMAX",
        "Maximum Observed Concentration",
        "ng/mL",
        "Cmax",
    ),
    "TMAX": ParamCodeEntry(
        "TMAX",
        "Time of Maximum Observed Concentration",
        "h",
        "Tmax",
    ),
    "TLST": ParamCodeEntry(
        "TLST",
        "Time of Last Measurable Concentration",
        "h",
        "Tlast",
    ),
    "CLST": ParamCodeEntry(
        "CLST",
        "Last Measurable Concentration",
        "ng/mL",
        "Clast",
    ),
    "CLSTP": ParamCodeEntry(
        "CLSTP",
        "Predicted Last Concentration",
        "ng/mL",
        "Clast_pred",
    ),
    "AUCLST": ParamCodeEntry(
        "AUCLST",
        "AUC From Time of First Dose to Time of Last Measurable Concentration",
        "ng.h/mL",
        "AUClast",
    ),
    "AUCIFO": ParamCodeEntry(
        "AUCIFO",
        "AUC Infinity Observed",
        "ng.h/mL",
        "AUCINF_obs",
    ),
    "AUCIFP": ParamCodeEntry(
        "AUCIFP",
        "AUC Infinity Predicted",
        "ng.h/mL",
        "AUCINF_pred",
    ),
    "AUMCLST": ParamCodeEntry(
        "AUMCLST",
        "AUMC From Time of First Dose to Time of Last Measurable Concentration",
        "ng.h2/mL",
        "AUMClast",
    ),
    "AUMCIFO": ParamCodeEntry(
        "AUMCIFO",
        "AUMC Infinity Observed",
        "ng.h2/mL",
        "AUMCINF_obs",
    ),
    "LAMZ": ParamCodeEntry(
        "LAMZ",
        "Lambda z",
        "1/h",
        "Lambda_z",
    ),
    "LAMZHL": ParamCodeEntry(
        "LAMZHL",
        "Half-Life Lambda z",
        "h",
        "HL_Lambda_z",
    ),
    "LAMZLL": ParamCodeEntry(
        "LAMZLL",
        "Lambda z Lower Limit",
        "h",
        "Lambda_z_lower",
    ),
    "LAMZUL": ParamCodeEntry(
        "LAMZUL",
        "Lambda z Upper Limit",
        "h",
        "Lambda_z_upper",
    ),
    "LAMZNPT": ParamCodeEntry(
        "LAMZNPT",
        "Number of Points for Lambda z",
        "",
        "No_points_Lambda_z",
    ),
    "R2": ParamCodeEntry(
        "R2",
        "R Squared",
        "",
        "Rsq",
    ),
    "R2ADJ": ParamCodeEntry(
        "R2ADJ",
        "R Squared Adjusted",
        "",
        "Rsq_adjusted",
    ),
    "MRTIFO": ParamCodeEntry(
        "MRTIFO",
        "Mean Residence Time Infinity Observed",
        "h",
        "MRTINF_obs",
    ),
    "CL": ParamCodeEntry(
        "CL",
        "Total Clearance",
        "L/h",
        "CL",
    ),
    "CLF": ParamCodeEntry(
        "CLF",
        "Apparent Clearance",
        "L/h",
        "CL_F",
    ),
    "VZ": ParamCodeEntry(
        "VZ",
        "Volume of Distribution During Terminal Phase",
        "L",
        "Vz",
    ),
    "VZF": ParamCodeEntry(
        "VZF",
        "Apparent Volume of Distribution During Terminal Phase",
        "L",
        "Vz_F",
    ),
    "VSS": ParamCodeEntry(
        "VSS",
        "Volume of Distribution at Steady State (observed)",
        "L",
        "Vss_obs",
    ),
}

# Reverse lookup: pkcopilot_name -> paramcd
_PKCOPILOT_TO_PARAMCD: dict[str, str] = {
    entry.pkcopilot_name: entry.paramcd for entry in PARAMCD_REGISTRY.values()
}


def pkcopilot_to_paramcd(name: str) -> str | None:
    """Return the CDISC PARAMCD for a pk-copilot internal parameter name.

    Args:
        name: pk-copilot canonical parameter name, e.g. ``"AUClast"``.

    Returns:
        PARAMCD string (e.g. ``"AUCLST"``) or ``None`` if not in registry.
    """
    return _PKCOPILOT_TO_PARAMCD.get(name)


def paramcd_to_pkcopilot(paramcd: str) -> str | None:
    """Return the pk-copilot name for a CDISC PARAMCD.

    Args:
        paramcd: CDISC PARAMCD code, e.g. ``"AUCLST"``.

    Returns:
        pk-copilot canonical name (e.g. ``"AUClast"``) or ``None`` if not in registry.
    """
    entry = PARAMCD_REGISTRY.get(paramcd.upper())
    return entry.pkcopilot_name if entry is not None else None
