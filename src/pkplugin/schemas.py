"""
Pydantic v2 data models for pk-copilot.

All schema classes are defined per docs/05-data-schemas.md §1, §2, and §5.
Frozen models are used for immutable record types (ConcentrationRecord,
DoseRecord, CovariateRecord, NCAParameterRow, LambdaZResult, AUCResult).
Mutable config models (StudyDesign, NCAConfig) are not frozen.

Refs:
- docs/05-data-schemas.md §1 — core data models
- docs/05-data-schemas.md §2 — unit system
- docs/05-data-schemas.md §5 — output parameter table
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pkplugin.version import WNVersion, merge_with_defaults

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# §1.1  ConcentrationRecord
# ---------------------------------------------------------------------------


class ConcentrationRecord(BaseModel):
    """One row of measured concentration data.

    Refs: docs/05-data-schemas.md §1.1
    """

    model_config = ConfigDict(frozen=True)

    subject_id: str
    time: float = Field(..., description="Post-dose time in canonical unit (hr)")
    concentration: float | None = Field(
        ..., description="Measured concentration (ng/mL); None == missing"
    )
    analyte: str = "parent"
    matrix: Literal["plasma", "serum", "blood", "urine", "other"] = "plasma"
    period: str | None = None
    sequence: str | None = None
    treatment: str | None = None
    bloq: bool = False
    bloq_rule_applied: str | None = None  # "pre_dose", "embedded_missing", etc.
    raw_concentration: str | None = None  # Original string e.g. "<0.5"

    @field_validator("time")
    @classmethod
    def _time_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"time must be >= 0, got {v}")
        return v


# ---------------------------------------------------------------------------
# §1.2  DoseRecord
# ---------------------------------------------------------------------------


class DoseRecord(BaseModel):
    """One dosing event.

    Refs: docs/05-data-schemas.md §1.2
    """

    model_config = ConfigDict(frozen=True)

    subject_id: str
    time: float = Field(..., description="Dose time in canonical unit (hr)")
    amount: float = Field(..., description="Dose amount in canonical unit (mg)")
    route: Literal["iv_bolus", "iv_infusion", "oral", "subcut", "im", "other"]
    infusion_duration: float | None = None  # hr
    period: str | None = None
    treatment: str | None = None

    @field_validator("time")
    @classmethod
    def _time_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"time must be >= 0, got {v}")
        return v

    @field_validator("amount")
    @classmethod
    def _amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"dose amount must be > 0, got {v}")
        return v


# ---------------------------------------------------------------------------
# §1.3  CovariateRecord
# ---------------------------------------------------------------------------


class CovariateRecord(BaseModel):
    """Subject-level covariate data.

    Refs: docs/05-data-schemas.md §1.3
    """

    model_config = ConfigDict(frozen=True)

    subject_id: str
    age: float | None = None          # years
    sex: Literal["M", "F", "U"] = "U"
    weight: float | None = None       # kg
    height: float | None = None       # cm
    crcl: float | None = None         # mL/min (Cockcroft-Gault or reported)
    egfr: float | None = None         # mL/min/1.73m²
    bsa: float | None = None          # m²
    custom: dict[str, float | str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# §1.4  StudyDesign
# ---------------------------------------------------------------------------


class StudyDesign(BaseModel):
    """Study-level design metadata.

    Refs: docs/05-data-schemas.md §1.4
    """

    study_id: str
    design: Literal[
        "single_dose",
        "multiple_dose",
        "crossover_2x2",
        "parallel",
        "replicate_2x4",
        "higher_order",
    ]
    tau: float | None = None          # dosing interval (hr) for multiple-dose
    formulations: list[str] = Field(default_factory=list)  # ["Test", "Reference"]
    sequences: list[str] = Field(default_factory=list)      # ["TR", "RT"]
    washout_hr: float | None = None

    @field_validator("tau")
    @classmethod
    def _tau_positive(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError(f"tau (dosing interval) must be > 0, got {v}")
        return v

    @field_validator("formulations", "sequences", mode="before")
    @classmethod
    def _non_empty_strings(cls, v: list[str]) -> list[str]:
        for item in v:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"All formulations/sequences must be non-empty strings, got {item!r}"
                )
        return v


# ---------------------------------------------------------------------------
# §1.5  NCAConfig
# ---------------------------------------------------------------------------


class NCAConfig(BaseModel):
    """Configuration for an NCA run.

    Refs: docs/05-data-schemas.md §1.5
    """

    winnonlin_version: Literal["5.3", "6.4", "8.3", "compat-latest"] = "6.4"
    auc_method: Literal["linear", "log", "linear_up_log_down"] | None = None
    lambda_z_method: (
        Literal["best_fit", "adj_r2", "manual", "time_range", "n_points"] | None
    ) = None
    lambda_z_tolerance: float | None = None
    lambda_z_min_points: int = 3
    lambda_z_manual: dict[str, Any] | None = None
    c0_method: Literal["observed", "log_back_extrap", "auto"] | None = None
    bloq_policy: Literal["default", "zero", "missing", "custom"] = "default"
    bloq_custom: dict[str, Any] | None = None
    partial_auc_windows: list[tuple[float, float]] = Field(default_factory=list)
    output_pred_variants: bool | None = None
    span_ratio_min: float = 1.5
    weight_normalization: Literal["none", "per_kg"] = "none"
    dose_normalization: bool = False

    def resolved(self, version: str | WNVersion | None = None) -> dict[str, Any]:
        """Return a fully-populated options dict by merging version defaults with overrides.

        Calls ``pkplugin.version.merge_with_defaults``, so callers get a complete
        dict with every algorithm option set.  User fields that are not None
        override the version defaults.

        Args:
            version: Override the winnonlin_version for this resolution.
                     Defaults to ``self.winnonlin_version``.

        Returns:
            dict with all algorithm options resolved.
        """
        resolved_version = version if version is not None else self.winnonlin_version
        overrides: dict[str, Any] = {}
        for field_name in type(self).model_fields:
            val = getattr(self, field_name)
            if val is not None:
                overrides[field_name] = val
        return merge_with_defaults(resolved_version, overrides)


# ---------------------------------------------------------------------------
# §5  NCAParameterRow — output table row
# ---------------------------------------------------------------------------


class NCAParameterRow(BaseModel):
    """One row of the NCA output parameter table.

    Refs: docs/05-data-schemas.md §5
    """

    model_config = ConfigDict(frozen=True)

    subject_id: str
    period: str | None = None
    treatment: str | None = None
    analyte: str = "parent"
    parameter: str                   # "Cmax", "AUClast", "AUCinf", ...
    value: float | None
    unit: str
    method: str                      # e.g. "linear_up_log_down"
    winnonlin_version: str
    flags: list[str] = Field(default_factory=list)
    comment: str | None = None


# ---------------------------------------------------------------------------
# Result types imported by nca modules
# ---------------------------------------------------------------------------


class LambdaZResult(BaseModel):
    """Result of terminal elimination rate constant regression.

    Imported by pkplugin.nca.lambda_z.
    """

    model_config = ConfigDict(frozen=True)

    lambda_z: float                    # hr⁻¹
    half_life: float                   # hr  (ln2 / lambda_z)
    r_squared: float
    adj_r_squared: float
    n_points: int
    time_first: float                  # first time point used in regression (hr)
    time_last: float                   # last time point used in regression (hr)
    span_ratio: float                  # (time_last - time_first) / half_life
    intercept: float                   # back-extrapolated C0 from regression line
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _span_ratio_consistent(self) -> "LambdaZResult":
        if self.lambda_z <= 0:
            raise ValueError(f"lambda_z must be > 0, got {self.lambda_z}")
        return self


class AUCResult(BaseModel):
    """Result of AUC/AUMC integration.

    Imported by pkplugin.nca.auc.
    """

    model_config = ConfigDict(frozen=True)

    auc_last: float                    # AUC from t=0 to last quantifiable (ng·hr/mL)
    auc_inf: float | None = None       # AUC extrapolated to infinity
    auc_extrap_pct: float | None = None  # % extrapolated beyond last point
    aumc_last: float | None = None     # AUMC to last quantifiable
    aumc_inf: float | None = None      # AUMC extrapolated to infinity
    method: str                        # "linear", "log", "linear_up_log_down"
    flags: list[str] = Field(default_factory=list)
