"""
PK compartmental model registry and spec types.

Defines :class:`PKModelSpec` and the pre-built :data:`REGISTRY` catalog that
maps canonical model codes (e.g. ``"cmt2_iv_bolus"``) to WinNonlin model
numbers and parameter metadata.

Refs:
- docs/03-algorithms/08-compartmental-models.md §1
- docs/04-winnonlin-version-matrix.md §4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class CompartmentRoute(str, Enum):
    """Administration route for a compartmental PK model."""

    IV_BOLUS = "iv_bolus"
    IV_INFUSION = "iv_infusion"
    ORAL = "oral"


@dataclass(frozen=True)
class PKModelSpec:
    """Immutable specification for a single compartmental PK model.

    Attributes:
        name:
            Canonical model code, e.g. ``"cmt1_iv_bolus"``.
        winnonlin_model_id:
            WinNonlin "PK Model" number (1–15). ``None`` if no WinNonlin
            equivalent exists.
        n_compartments:
            Number of disposition compartments (1, 2, or 3).
        route:
            Administration route.
        parameter_names:
            Ordered tuple of micro-parameter names. Ordering must match the
            positional array convention used by :mod:`pkplugin.comp.analytic`.
        has_michaelis_menten:
            ``True`` for models with non-linear Michaelis-Menten elimination
            (ODE-only; no closed-form solution).
        has_lag:
            ``True`` when the model includes an absorption lag time (``tlag``).

    Refs: docs/03-algorithms/08-compartmental-models.md §1
    """

    name: str
    winnonlin_model_id: int | None
    n_compartments: Literal[1, 2, 3]
    route: CompartmentRoute
    parameter_names: tuple[str, ...]
    has_michaelis_menten: bool = False
    has_lag: bool = False


# ---------------------------------------------------------------------------
# Pre-built model catalog
# ---------------------------------------------------------------------------

REGISTRY: dict[str, PKModelSpec] = {
    "cmt1_iv_bolus": PKModelSpec(
        name="cmt1_iv_bolus",
        winnonlin_model_id=1,
        n_compartments=1,
        route=CompartmentRoute.IV_BOLUS,
        parameter_names=("V", "k"),
    ),
    "cmt1_iv_infusion": PKModelSpec(
        name="cmt1_iv_infusion",
        winnonlin_model_id=3,
        n_compartments=1,
        route=CompartmentRoute.IV_INFUSION,
        parameter_names=("V", "k"),
    ),
    "cmt1_po": PKModelSpec(
        name="cmt1_po",
        winnonlin_model_id=5,
        n_compartments=1,
        route=CompartmentRoute.ORAL,
        parameter_names=("V_F", "ka", "k"),
        has_lag=False,
    ),
    "cmt2_iv_bolus": PKModelSpec(
        name="cmt2_iv_bolus",
        winnonlin_model_id=7,
        n_compartments=2,
        route=CompartmentRoute.IV_BOLUS,
        parameter_names=("V1", "k10", "k12", "k21"),
    ),
    "cmt2_iv_infusion": PKModelSpec(
        name="cmt2_iv_infusion",
        winnonlin_model_id=9,
        n_compartments=2,
        route=CompartmentRoute.IV_INFUSION,
        parameter_names=("V1", "k10", "k12", "k21"),
    ),
    "cmt2_po": PKModelSpec(
        name="cmt2_po",
        winnonlin_model_id=11,
        n_compartments=2,
        route=CompartmentRoute.ORAL,
        parameter_names=("V1_F", "ka", "k10", "k12", "k21"),
    ),
    "cmt3_iv_bolus": PKModelSpec(
        name="cmt3_iv_bolus",
        winnonlin_model_id=13,
        n_compartments=3,
        route=CompartmentRoute.IV_BOLUS,
        parameter_names=("V1", "k10", "k12", "k21", "k13", "k31"),
    ),
    # ---- Michaelis-Menten variants (ODE-only; closed form does not exist) ----
    # These are discoverable through REGISTRY so list_models()/CDISC tools see
    # them, but ``pkplugin.comp.analytic.predict`` rejects them — they must be
    # evaluated via ``pkplugin.comp.ode.simulate_ode``.
    "cmt1_iv_mm": PKModelSpec(
        name="cmt1_iv_mm",
        winnonlin_model_id=2,
        n_compartments=1,
        route=CompartmentRoute.IV_BOLUS,
        parameter_names=("V", "Vmax", "Km"),
        has_michaelis_menten=True,
    ),
    "cmt1_po_mm": PKModelSpec(
        name="cmt1_po_mm",
        winnonlin_model_id=6,
        n_compartments=1,
        route=CompartmentRoute.ORAL,
        parameter_names=("V_F", "ka", "Vmax", "Km"),
        has_michaelis_menten=True,
    ),
    "cmt2_iv_mm": PKModelSpec(
        name="cmt2_iv_mm",
        winnonlin_model_id=8,
        n_compartments=2,
        route=CompartmentRoute.IV_BOLUS,
        parameter_names=("V1", "Vmax", "Km", "k12", "k21"),
        has_michaelis_menten=True,
    ),
}


def get_model(name: str) -> PKModelSpec:
    """Return the :class:`PKModelSpec` for *name*, or raise :exc:`ValueError`.

    Args:
        name: Canonical model code (key in :data:`REGISTRY`).

    Returns:
        The matching :class:`PKModelSpec`.

    Raises:
        ValueError: If *name* is not in :data:`REGISTRY`.

    Refs: docs/03-algorithms/08-compartmental-models.md §1
    """
    if name not in REGISTRY:
        raise ValueError(
            f"Unknown PK model: {name!r}. Available: {sorted(REGISTRY)}"
        )
    return REGISTRY[name]
