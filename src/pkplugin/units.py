"""
Pint-based unit system for pk-copilot.

Provides a singleton UnitRegistry with custom aliases (mcg = microgram),
canonical internal unit constants, and conversion helpers for time,
concentration, and dose.

Refs:
- docs/05-data-schemas.md §2 — unit system specification
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

import pint

# ---------------------------------------------------------------------------
# Singleton unit registry with custom definitions
# ---------------------------------------------------------------------------

unit_registry: pint.UnitRegistry = pint.UnitRegistry()  # type: ignore[type-arg]

# Custom aliases not in pint's default registry
unit_registry.define("mcg = microgram = mcg")
unit_registry.define("hr = hour = h")

# ---------------------------------------------------------------------------
# Canonical internal unit constants (docs/05-data-schemas.md §2)
# ---------------------------------------------------------------------------

CANONICAL_TIME: str = "hour"
CANONICAL_CONC_MASS: str = "ng/mL"
CANONICAL_DOSE: str = "mg"
CANONICAL_VOL: str = "L"
CANONICAL_CL: str = "L/hour"

# ---------------------------------------------------------------------------
# Unit parsing helpers
# ---------------------------------------------------------------------------

# Maps common abbreviations / spellings to a pint-parseable form before
# handing off to unit_registry.  This normalises inputs that pint would
# otherwise reject.
_UNIT_ALIASES: dict[str, str] = {
    # time
    "h": "hour",
    "hr": "hour",
    "hrs": "hour",
    "min": "minute",
    "mins": "minute",
    "d": "day",
    "days": "day",
    # concentration mass/volume
    "ng/ml": "nanogram / milliliter",
    "ng/dl": "nanogram / deciliter",
    "ug/l": "microgram / liter",
    "ug/ml": "microgram / milliliter",
    "mcg/l": "microgram / liter",
    "mcg/ml": "microgram / milliliter",
    "mg/l": "milligram / liter",
    "mg/dl": "milligram / deciliter",
    "g/l": "gram / liter",
    # molar (require MW for mass conversion — parse succeeds, conversion raises)
    "nmol/l": "nanomolar",
    "umol/l": "micromolar",
    "mmol/l": "millimolar",
    "mol/l": "molar",
    # dose
    "mg": "milligram",
    "ug": "microgram",
    "mcg": "microgram",
    "g": "gram",
    "mg/kg": "milligram / kilogram",
    "mcg/kg": "microgram / kilogram",
    "ug/kg": "microgram / kilogram",
}


def parse_unit(text: str) -> pint.Unit:
    """Parse a unit string to a ``pint.Unit``.

    Handles common PK abbreviations: ``hr``/``h``/``hour``, ``ng/mL``,
    ``ug/L``, ``mcg/L``, ``nmol/L``, ``mg/kg``, etc.

    Args:
        text: Human-readable unit string.

    Returns:
        Parsed ``pint.Unit``.

    Raises:
        ValueError: If the string cannot be parsed.

    Refs: docs/05-data-schemas.md §2
    """
    normalized = text.strip().lower()
    # Try alias table first, then fall back to pint's own parser
    pint_str = _UNIT_ALIASES.get(normalized, normalized)
    try:
        return unit_registry.Unit(pint_str)
    except pint.UndefinedUnitError as exc:
        raise ValueError(
            f"Unrecognized unit {text!r}. "
            "Supported examples: ng/mL, ug/L, mcg/L, nmol/L, hr, min, day, mg, mg/kg."
        ) from exc


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def to_canonical_time(value: float, unit: str) -> float:
    """Convert a time value to canonical hours.

    Args:
        value: Numeric time value.
        unit:  Unit string (e.g. ``"min"``, ``"h"``, ``"day"``).

    Returns:
        Time in hours (float).

    Refs: docs/05-data-schemas.md §2
    """
    src_unit = parse_unit(unit)
    qty = unit_registry.Quantity(value, src_unit)
    try:
        return float(qty.to(unit_registry.Unit(CANONICAL_TIME)).magnitude)
    except pint.DimensionalityError as exc:
        raise ValueError(
            f"Cannot convert {unit!r} to hours: {exc}"
        ) from exc


def to_canonical_concentration(
    value: float,
    unit: str,
    molecular_weight_g_per_mol: float | None = None,
) -> float:
    """Convert a concentration value to canonical ng/mL.

    Molar units (nmol/L, umol/L, etc.) require *molecular_weight_g_per_mol*
    to perform the molar → mass conversion.

    Args:
        value: Numeric concentration value.
        unit:  Unit string (e.g. ``"ng/mL"``, ``"ug/L"``, ``"nmol/L"``).
        molecular_weight_g_per_mol: Molecular weight in g/mol; required when
            ``unit`` is a molar unit.

    Returns:
        Concentration in ng/mL (float).

    Raises:
        ValueError: For unrecognized units or molar units without MW.

    Refs: docs/05-data-schemas.md §2
    """
    src_unit = parse_unit(unit)
    normalized = unit.strip().lower()

    # Detect molar units and convert to mass/volume via MW
    _molar_roots = ("mol/l", "molar", "nmol", "umol", "mmol")
    is_molar = any(normalized.endswith(m) or normalized.startswith(m) for m in _molar_roots)
    if not is_molar:
        # Check by pint dimensionality: [substance] / [volume]
        try:
            dim = unit_registry.Quantity(1.0, src_unit).dimensionality
            is_molar = "[substance]" in str(dim)
        except Exception:
            pass

    if is_molar:
        if molecular_weight_g_per_mol is None:
            raise ValueError(
                f"Unit {unit!r} is molar; molecular_weight_g_per_mol is required "
                "to convert to ng/mL."
            )
        # Convert mol/L → g/L first, then to ng/mL
        # value [unit] * MW [g/mol] → mass/volume in g/L equivalent
        qty_molar = unit_registry.Quantity(value, src_unit)
        # to mol/L then multiply by MW
        mol_per_l = float(qty_molar.to(unit_registry.Unit("molar")).magnitude)
        g_per_l = mol_per_l * molecular_weight_g_per_mol
        # g/L → ng/mL: 1 g/L = 1e6 ng/mL
        return g_per_l * 1e6

    # Standard mass/volume conversion
    qty = unit_registry.Quantity(value, src_unit)
    target = unit_registry.Unit("nanogram / milliliter")
    try:
        return float(qty.to(target).magnitude)
    except pint.DimensionalityError as exc:
        raise ValueError(
            f"Cannot convert {unit!r} to ng/mL: {exc}"
        ) from exc


def to_canonical_dose(
    value: float,
    unit: str,
    weight_kg: float | None = None,
) -> float:
    """Convert a dose value to canonical mg.

    Handles ``mg/kg`` (and ``ug/kg``, ``mcg/kg``) by multiplying by
    *weight_kg* when supplied.

    Args:
        value:     Numeric dose value.
        unit:      Unit string (e.g. ``"mg"``, ``"mg/kg"``).
        weight_kg: Subject body weight in kg; required for per-kg units.

    Returns:
        Dose in mg (float).

    Raises:
        ValueError: For unrecognized units or per-kg units without weight.

    Refs: docs/05-data-schemas.md §2
    """
    normalized = unit.strip().lower()
    is_per_kg = "/kg" in normalized

    if is_per_kg:
        if weight_kg is None:
            raise ValueError(
                f"Unit {unit!r} is a per-kg dose; weight_kg is required to convert to mg."
            )
        # Strip the /kg part and convert the mass component, then multiply by weight
        mass_unit_str = normalized.replace("/kg", "").strip()
        src_unit = parse_unit(mass_unit_str)
        qty = unit_registry.Quantity(value * weight_kg, src_unit)
    else:
        src_unit = parse_unit(unit)
        qty = unit_registry.Quantity(value, src_unit)

    target = unit_registry.Unit(CANONICAL_DOSE)
    try:
        return float(qty.to(target).magnitude)
    except pint.DimensionalityError as exc:
        raise ValueError(
            f"Cannot convert {unit!r} to mg: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# UnitConfirmation dataclass and confirm_units helper
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitConfirmation:
    """User-confirmed unit choices for a dataset load.

    Refs: docs/05-data-schemas.md §2 — unit confirmation protocol
    """

    concentration_unit: str
    time_unit: str
    dose_unit: str

    def as_dict(self) -> dict[str, str]:
        """Return the confirmation as a plain dict."""
        return {
            "concentration_unit": self.concentration_unit,
            "time_unit": self.time_unit,
            "dose_unit": self.dose_unit,
        }


def confirm_units(
    concentration_unit: str,
    time_unit: str,
    dose_unit: str,
) -> UnitConfirmation:
    """Validate and bundle user-confirmed unit strings.

    This is a pure function — it performs no I/O.  The interactive prompt
    shown at data-load time is built in ``pkplugin.ingest``.  Each string
    is parsed via ``parse_unit`` to fail fast on unrecognised inputs.

    Args:
        concentration_unit: Confirmed concentration unit (e.g. ``"ng/mL"``).
        time_unit:          Confirmed time unit (e.g. ``"hr"``).
        dose_unit:          Confirmed dose unit (e.g. ``"mg"``).

    Returns:
        A frozen :class:`UnitConfirmation` instance.

    Raises:
        ValueError: If any unit string is unrecognised.

    Refs: docs/05-data-schemas.md §2
    """
    parse_unit(concentration_unit)
    parse_unit(time_unit)
    parse_unit(dose_unit)
    return UnitConfirmation(
        concentration_unit=concentration_unit,
        time_unit=time_unit,
        dose_unit=dose_unit,
    )
