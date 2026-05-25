"""
PD model registry and spec types.

Defines :class:`PDModelSpec` and the pre-built :data:`PD_REGISTRY` catalog that
maps canonical model codes to parameter metadata.

Supported model families
------------------------
- Direct effect (linear, log_linear, emax, sigmoid_emax, inhibitory_emax)
- Effect compartment (Hull-Sheiner)
- Indirect response models I-IV (Jusko/Dayneka)

Refs: docs/03-algorithms/09-pkpd-models.md §1
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PDModelType(str, Enum):
    """PD model family identifier."""

    LINEAR = "linear"
    LOG_LINEAR = "log_linear"
    EMAX = "emax"
    SIGMOID_EMAX = "sigmoid_emax"
    INHIBITORY_EMAX = "inhibitory_emax"
    EFFECT_COMPARTMENT = "effect_compartment"
    IDR_I_INHIB_PRODUCTION = "idr_i"
    IDR_II_INHIB_LOSS = "idr_ii"
    IDR_III_STIM_PRODUCTION = "idr_iii"
    IDR_IV_STIM_LOSS = "idr_iv"


@dataclass(frozen=True)
class PDModelSpec:
    """Immutable specification for a single PD model.

    Attributes:
        name:
            Canonical model code, e.g. ``"emax"``.
        model_type:
            :class:`PDModelType` enum value.
        parameter_names:
            Ordered tuple of parameter names expected by
            :func:`~pkplugin.pd.predict.predict_pd`.
        requires_ode:
            ``True`` for effect compartment and IDR models that need ODE
            integration.
        is_inhibitory:
            ``True`` when the driver parameter is Imax/IC50 (inhibition)
            rather than Emax/EC50 (stimulation).

    Refs: docs/03-algorithms/09-pkpd-models.md §1
    """

    name: str
    model_type: PDModelType
    parameter_names: tuple[str, ...]
    requires_ode: bool
    is_inhibitory: bool


# ---------------------------------------------------------------------------
# Pre-built model catalog
# ---------------------------------------------------------------------------

PD_REGISTRY: dict[str, PDModelSpec] = {
    "linear": PDModelSpec(
        "linear",
        PDModelType.LINEAR,
        ("E0", "S"),
        False,
        False,
    ),
    "log_linear": PDModelSpec(
        "log_linear",
        PDModelType.LOG_LINEAR,
        ("E0", "S"),
        False,
        False,
    ),
    "emax": PDModelSpec(
        "emax",
        PDModelType.EMAX,
        ("E0", "Emax", "EC50"),
        False,
        False,
    ),
    "sigmoid_emax": PDModelSpec(
        "sigmoid_emax",
        PDModelType.SIGMOID_EMAX,
        ("E0", "Emax", "EC50", "gamma"),
        False,
        False,
    ),
    "inhibitory_emax": PDModelSpec(
        "inhibitory_emax",
        PDModelType.INHIBITORY_EMAX,
        ("E0", "Imax", "IC50"),
        False,
        True,
    ),
    "effect_compartment": PDModelSpec(
        "effect_compartment",
        PDModelType.EFFECT_COMPARTMENT,
        ("E0", "Emax", "EC50", "ke0"),
        True,
        False,
    ),
    "idr_i": PDModelSpec(
        "idr_i",
        PDModelType.IDR_I_INHIB_PRODUCTION,
        ("kin", "kout", "Imax", "IC50"),
        True,
        True,
    ),
    "idr_ii": PDModelSpec(
        "idr_ii",
        PDModelType.IDR_II_INHIB_LOSS,
        ("kin", "kout", "Imax", "IC50"),
        True,
        True,
    ),
    "idr_iii": PDModelSpec(
        "idr_iii",
        PDModelType.IDR_III_STIM_PRODUCTION,
        ("kin", "kout", "Smax", "SC50"),
        True,
        False,
    ),
    "idr_iv": PDModelSpec(
        "idr_iv",
        PDModelType.IDR_IV_STIM_LOSS,
        ("kin", "kout", "Smax", "SC50"),
        True,
        False,
    ),
}


def get_pd_model(name: str) -> PDModelSpec:
    """Return the :class:`PDModelSpec` for *name*, or raise :exc:`ValueError`.

    Args:
        name: Canonical model code (key in :data:`PD_REGISTRY`).

    Returns:
        The matching :class:`PDModelSpec`.

    Raises:
        ValueError: If *name* is not in :data:`PD_REGISTRY`.

    Refs: docs/03-algorithms/09-pkpd-models.md §1
    """
    if name not in PD_REGISTRY:
        raise ValueError(f"Unknown PD model: {name!r}. Available: {sorted(PD_REGISTRY)}")
    return PD_REGISTRY[name]


def list_pd_models() -> list[str]:
    """Return the list of registered PD model names.

    Returns:
        All keys in :data:`PD_REGISTRY`.
    """
    return list(PD_REGISTRY)
