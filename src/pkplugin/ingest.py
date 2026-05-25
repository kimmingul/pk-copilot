"""
CSV/Excel data loader for pk-copilot.

Loads concentration-time data into a canonical long-format DataFrame and
produces an :class:`IngestReport` describing the dataset.  Unit confirmation
and BLOQ policy decisions are NOT applied here — those are upstream concerns
for the MCP layer.  This module only detects and flags.

Supported formats:
- ``.csv`` / ``.tsv``  — standard delimited text
- ``.xlsx``            — Excel (openpyxl backend)

Refs:
- docs/05-data-schemas.md §3  — long format canonical schema
- docs/03-algorithms/04-bloq-handling.md — BLOQ pattern definitions
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from pkplugin.schemas import ConcentrationRecord, DoseRecord

# ---------------------------------------------------------------------------
# Constants — BLOQ recognition
# ---------------------------------------------------------------------------

# Recognised sentinel strings (case-insensitive, whitespace-stripped).
_BLOQ_SENTINEL_RE = re.compile(
    r"^(<\s*lloq|blq|bql|bloq|nq|nd)$",
    re.IGNORECASE,
)

# Numeric-prefixed form: e.g. "<0.5", "< 1.0", "<1"
_BLOQ_NUMERIC_RE = re.compile(
    r"^<\s*(\d+(?:\.\d+)?)$",
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnMapping:
    """Mapping from canonical field names to actual DataFrame column labels.

    The ``subject_id``, ``time``, and ``concentration`` fields are mandatory.
    All others are optional (``None`` means "not present in this dataset").
    """

    subject_id: str
    time: str
    concentration: str
    # optional
    analyte: str | None = None
    period: str | None = None
    treatment: str | None = None
    sequence: str | None = None
    bloq_flag: str | None = None  # separate BLOQ indicator column, if present


@dataclass(frozen=True)
class IngestReport:
    """Summary statistics and metadata produced by :func:`load_dataset`.

    The caller (MCP layer) uses this to render the unit-confirmation and
    BLOQ-policy prompts described in docs/07-ux-and-commands.md §5.
    """

    n_rows: int
    n_subjects: int
    n_bloq: int
    lloq_candidates: list[float]
    inferred_units: dict[str, str]  # {"time": "hr", "concentration": "ng/mL"}
    column_mapping: ColumnMapping
    warnings: list[str]
    raw_bloq_patterns_seen: list[str]  # e.g. ["<0.5", "BLQ", "NQ"]


# ---------------------------------------------------------------------------
# BLOQ detection
# ---------------------------------------------------------------------------


def detect_bloq_pattern(value: Any) -> tuple[bool, float | None, str | None]:
    """Recognise a single concentration value as BLOQ or not.

    Handles:
    - Numeric-prefixed form  ``"<0.5"``, ``"< 1.0"``
    - Sentinel strings       ``"BLQ"``, ``"BQL"``, ``"<LLOQ"``, ``"NQ"``, ``"ND"``
    - Case-insensitive, strips surrounding whitespace.

    Args:
        value: A raw cell value from the concentration column.

    Returns:
        A 3-tuple ``(is_bloq, numeric_lloq_or_none, raw_string_or_none)``
        where:
        - ``is_bloq`` — ``True`` when the value is a BLOQ marker.
        - ``numeric_lloq_or_none`` — the LLOQ extracted from ``"<0.5"``-style
          values, or ``None`` for sentinel-only forms.
        - ``raw_string_or_none`` — the original string (stripped), or ``None``
          when the value was not BLOQ.
    """
    if value is None:
        return False, None, None

    # Already a finite number → not BLOQ
    if isinstance(value, (int, float)):
        return False, None, None

    raw = str(value).strip()
    if not raw:
        return False, None, None

    # Numeric-prefixed form: "<0.5"
    m = _BLOQ_NUMERIC_RE.match(raw)
    if m:
        return True, float(m.group(1)), raw

    # Sentinel form: BLQ, BQL, BLOQ, <LLOQ, NQ, ND
    if _BLOQ_SENTINEL_RE.match(raw):
        return True, None, raw

    return False, None, None


# ---------------------------------------------------------------------------
# Column-name heuristics
# ---------------------------------------------------------------------------

# Candidate lists are ordered by priority (first match wins).
_SUBJECT_CANDIDATES = [
    "usubjid",
    "subjid",
    "subject_id",
    "subjectid",
    "id",
    "대상자",
    "환자",
    "subject",
]
_TIME_CANDIDATES = [
    "time_hr",
    "timeh",
    "time",
    "t",
    "시간(hr)",
    "시간",
    "hours",
    "hr",
]
_CONC_CANDIDATES = [
    "conc_ng_per_ml",
    "concentration",
    "conc",
    "ng_per_ml",
    "value",
    "농도(ng/ml)",
    "농도(ng/ml)",
    "농도",
    "농도(ng/mL)",
]
_ANALYTE_CANDIDATES = ["analyte_id", "analyte"]
_PERIOD_CANDIDATES = ["period", "per", "visit"]
_TREATMENT_CANDIDATES = ["treatment", "trt", "arm", "formulation"]
_SEQUENCE_CANDIDATES = ["sequence", "seq", "group"]
_BLOQ_FLAG_CANDIDATES = ["bloq", "blq", "bql"]


def _match_column(columns_lower: dict[str, str], candidates: list[str]) -> str | None:
    """Return the first column whose lowercased name matches a candidate."""
    for cand in candidates:
        if cand in columns_lower:
            return columns_lower[cand]
    return None


def suggest_column_mapping(columns: list[str]) -> ColumnMapping:
    """Heuristically map actual column names to canonical roles.

    Supports both Korean (한국어) and English column headers.

    Args:
        columns: List of column names as they appear in the DataFrame.

    Returns:
        :class:`ColumnMapping` with all matched roles filled in.

    Raises:
        ValueError: When no concentration-like column can be found.
    """
    # Build a lowercase → original-case lookup for case-insensitive matching.
    lower_map: dict[str, str] = {col.lower().strip(): col for col in columns}

    subject_col = _match_column(lower_map, _SUBJECT_CANDIDATES)
    time_col = _match_column(lower_map, _TIME_CANDIDATES)
    conc_col = _match_column(lower_map, _CONC_CANDIDATES)

    if conc_col is None:
        raise ValueError(
            f"Cannot find a concentration column in: {columns}. "
            "Expected names like 'conc', 'CONCENTRATION', '농도', 'value', etc."
        )

    if subject_col is None:
        # Fall back: use the first non-numeric-looking column
        for col in columns:
            if col.lower().strip() not in (
                (time_col or "").lower(),
                (conc_col or "").lower(),
            ):
                subject_col = col
                break

    if time_col is None:
        raise ValueError(
            f"Cannot find a time column in: {columns}. "
            "Expected names like 'time', 'TIME', '시간', 'hr', etc."
        )

    if subject_col is None:
        raise ValueError(
            f"Cannot find a subject-ID column in: {columns}. "
            "Expected names like 'ID', 'SUBJID', '대상자', etc."
        )

    return ColumnMapping(
        subject_id=subject_col,
        time=time_col,
        concentration=conc_col,
        analyte=_match_column(lower_map, _ANALYTE_CANDIDATES),
        period=_match_column(lower_map, _PERIOD_CANDIDATES),
        treatment=_match_column(lower_map, _TREATMENT_CANDIDATES),
        sequence=_match_column(lower_map, _SEQUENCE_CANDIDATES),
        bloq_flag=_match_column(lower_map, _BLOQ_FLAG_CANDIDATES),
    )


# ---------------------------------------------------------------------------
# Unit inference
# ---------------------------------------------------------------------------

# Map suffix patterns to canonical unit strings.
_TIME_UNIT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bhr\b|\bhour[s]?\b|_hr$|\(hr\)", re.IGNORECASE), "hr"),
    (re.compile(r"\bmin\b|\bminute[s]?\b|_min$|\(min\)", re.IGNORECASE), "min"),
    (re.compile(r"\bday[s]?\b|\bd\b|_day$|\(day\)", re.IGNORECASE), "day"),
]

_CONC_UNIT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ng/mL — slash, underscore, or "per" separator; also parenthesised suffix
    (re.compile(r"ng[/_]?(?:per[_]?)?m[lL]|\(ng[/_]m[lL]\)|ng_per_ml", re.IGNORECASE), "ng/mL"),
    (
        re.compile(
            r"ug[/_]?(?:per[_]?)?[lL]|mcg[/_]?(?:per[_]?)?[lL]|\(ug[/_][lL]\)|ug_per_[lL]",
            re.IGNORECASE,
        ),
        "ug/L",
    ),
    (
        re.compile(r"ug[/_]?(?:per[_]?)?m[lL]|mcg[/_]?(?:per[_]?)?m[lL]|ug_per_ml", re.IGNORECASE),
        "ug/mL",
    ),
    (re.compile(r"nmol[/_]?[lL]", re.IGNORECASE), "nmol/L"),
    (re.compile(r"umol[/_]?[lL]", re.IGNORECASE), "umol/L"),
]

_DOSE_UNIT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bmg\b|_mg$|\(mg\)", re.IGNORECASE), "mg"),
    (re.compile(r"\bug\b|mcg\b|_ug$|\(ug\)", re.IGNORECASE), "ug"),
    (re.compile(r"\bng\b|_ng$|\(ng\)", re.IGNORECASE), "ng"),
]


def _match_unit(
    col_name: str,
    patterns: list[tuple[re.Pattern[str], str]],
) -> str | None:
    for pat, unit in patterns:
        if pat.search(col_name):
            return unit
    return None


def infer_units(columns: list[str], column_mapping: ColumnMapping) -> dict[str, str]:
    """Attempt to infer time/concentration/dose units from column-name suffixes.

    Recognises patterns like ``"time_hr"``, ``"conc_ng_per_ml"``,
    ``"농도(ng/mL)"``, ``"TIMEH"``.

    Args:
        columns: All column names in the DataFrame.
        column_mapping: Already-resolved column mapping.

    Returns:
        Dict with keys ``"time"``, ``"concentration"``, and/or ``"dose"``
        mapped to canonical unit strings.  Keys whose units cannot be inferred
        are omitted — the caller must prompt the user.
    """
    result: dict[str, str] = {}

    time_unit = _match_unit(column_mapping.time, _TIME_UNIT_PATTERNS)
    if time_unit:
        result["time"] = time_unit

    conc_unit = _match_unit(column_mapping.concentration, _CONC_UNIT_PATTERNS)
    if conc_unit:
        result["concentration"] = conc_unit

    # Scan all columns for a dose column and try to infer its unit.
    dose_candidates = [
        c for c in columns if re.search(r"dose|amt|amount|용량|투여", c, re.IGNORECASE)
    ]
    for dc in dose_candidates:
        dose_unit = _match_unit(dc, _DOSE_UNIT_PATTERNS)
        if dose_unit:
            result["dose"] = dose_unit
            break

    return result


# ---------------------------------------------------------------------------
# Core loader
# ---------------------------------------------------------------------------


def load_dataset(
    path: str | Path,
    column_mapping: ColumnMapping | None = None,
    sheet: str | None = None,
) -> tuple[pd.DataFrame, IngestReport]:
    """Load a CSV or Excel file into a canonical long-format DataFrame.

    Canonical output columns:
    ``subject_id``, ``time``, ``concentration``, ``bloq``, ``raw_concentration``,
    ``analyte``, ``period``, ``treatment``, ``sequence``.

    - ``concentration`` is ``float | NaN``; BLOQ rows have ``NaN``.
    - ``raw_concentration`` preserves the original cell string (e.g. ``"<0.5"``).
    - ``bloq`` is ``bool``.
    - Input row order is preserved (no sorting).
    - Negative time values are permitted (pre-dose baseline).

    Args:
        path: Path to ``.csv``, ``.tsv``, or ``.xlsx`` file.
        column_mapping: Explicit mapping; auto-detected when ``None``.
        sheet: Excel sheet name.  Uses the first sheet when ``None``.

    Returns:
        A 2-tuple ``(df, report)`` where ``df`` is the canonical DataFrame and
        ``report`` is an :class:`IngestReport` summarising the dataset.

    Raises:
        ValueError: For unsupported file extensions or missing mandatory columns.
        FileNotFoundError: When ``path`` does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")

    # --- Read raw data ---
    ext = path.suffix.lower()
    if ext in (".csv", ".tsv"):
        sep = "\t" if ext == ".tsv" else ","
        raw_df: pd.DataFrame = pd.read_csv(path, sep=sep, dtype=str)
    elif ext in (".xlsx", ".xls"):
        raw_df = pd.read_excel(
            path,
            sheet_name=sheet or 0,
            dtype=str,
            engine="openpyxl",
        )
    else:
        raise ValueError(f"Unsupported file extension: {ext!r}. Expected .csv, .tsv, or .xlsx.")

    # Strip column whitespace
    raw_df.columns = [str(c).strip() for c in raw_df.columns]

    # --- Resolve column mapping ---
    mapping = column_mapping or suggest_column_mapping(list(raw_df.columns))

    # --- Build canonical DataFrame ---
    warnings: list[str] = []
    bloq_patterns_seen: list[str] = []
    lloq_candidates: list[float] = []
    n_bloq = 0

    out_rows: list[dict[str, Any]] = []

    for idx, row in raw_df.iterrows():
        raw_conc_val = row.get(mapping.concentration, None)
        is_bloq, lloq_val, raw_str = detect_bloq_pattern(raw_conc_val)

        if is_bloq:
            n_bloq += 1
            if raw_str and raw_str not in bloq_patterns_seen:
                bloq_patterns_seen.append(raw_str)
            if lloq_val is not None and lloq_val not in lloq_candidates:
                lloq_candidates.append(lloq_val)
            conc_float: float | None = None
        else:
            # Attempt numeric conversion; non-parseable → NaN (treat as missing)
            try:
                parsed = float(str(raw_conc_val).strip()) if raw_conc_val is not None else None
                conc_float = parsed
            except (ValueError, TypeError):
                conc_float = None
                if raw_conc_val is not None and str(raw_conc_val).strip():
                    warnings.append(
                        f"Row {idx}: could not parse concentration value "
                        f"{raw_conc_val!r} — treated as missing."
                    )

        # Time
        try:
            time_val: float = float(str(row.get(mapping.time, "")).strip())
        except (ValueError, TypeError):
            warnings.append(
                f"Row {idx}: could not parse time value {row.get(mapping.time)!r} — row skipped."
            )
            continue

        out_rows.append(
            {
                "subject_id": str(row.get(mapping.subject_id, "")).strip(),
                "time": time_val,
                "concentration": conc_float,
                "bloq": is_bloq,
                "raw_concentration": str(raw_conc_val).strip()
                if raw_conc_val is not None
                else None,
                "analyte": (
                    str(row[mapping.analyte]).strip()
                    if mapping.analyte and mapping.analyte in row.index
                    else None
                ),
                "period": (
                    str(row[mapping.period]).strip()
                    if mapping.period and mapping.period in row.index
                    else None
                ),
                "treatment": (
                    str(row[mapping.treatment]).strip()
                    if mapping.treatment and mapping.treatment in row.index
                    else None
                ),
                "sequence": (
                    str(row[mapping.sequence]).strip()
                    if mapping.sequence and mapping.sequence in row.index
                    else None
                ),
            }
        )

    # Ensure consistent dtypes
    out_df = pd.DataFrame(out_rows)
    if out_df.empty:
        out_df = pd.DataFrame(
            columns=[
                "subject_id",
                "time",
                "concentration",
                "bloq",
                "raw_concentration",
                "analyte",
                "period",
                "treatment",
                "sequence",
            ]
        )
    else:
        out_df["time"] = pd.to_numeric(out_df["time"], errors="coerce")
        out_df["concentration"] = pd.to_numeric(out_df["concentration"], errors="coerce")
        out_df["bloq"] = out_df["bloq"].astype(bool)

    # --- Per-subject time-monotonicity check ---
    for subj, grp in out_df.groupby("subject_id", sort=False):
        times = grp["time"].dropna().tolist()
        if len(times) > 1:
            for i in range(1, len(times)):
                if times[i] < times[i - 1]:
                    warnings.append(
                        f"Subject {subj!r}: non-monotonic time detected "
                        f"(t[{i - 1}]={times[i - 1]} > t[{i}]={times[i]}). "
                        "Row order preserved; upstream should verify."
                    )
                    break  # one warning per subject is enough

    n_subjects = out_df["subject_id"].nunique()
    inferred_units = infer_units(list(raw_df.columns), mapping)

    # --- Canonical unit conversion (v0.1: simple cases only) ---
    # Canonical algorithm inputs: time=hour, concentration=ng/mL, dose=mg.
    # Convert time if inferred unit != "hr"/"h"/"hour" (e.g., min, day).
    # Convert mass-based concentration if inferred unit != "ng/mL".
    # Molar concentrations (nmol/L, umol/L) require molecular weight and are
    # NOT converted here — a warning is emitted and original values are kept.
    # Dose unit is handled per-DoseRecord, not here.
    from pkplugin.units import (
        to_canonical_concentration,
        to_canonical_time,
    )

    t_unit_raw = inferred_units.get("time")
    c_unit_raw = inferred_units.get("concentration")
    conversions_applied: dict[str, str] = {}

    if t_unit_raw and t_unit_raw not in {"hr", "h", "hour"}:
        try:
            out_df["time"] = out_df["time"].apply(
                lambda v: to_canonical_time(float(v), t_unit_raw) if pd.notna(v) else v
            )
            conversions_applied["time"] = f"{t_unit_raw} -> hour"
        except Exception as exc:  # noqa: BLE001 — surface to user via warnings
            warnings.append(
                f"time unit conversion failed ({t_unit_raw} -> hour): {exc}. "
                "Values kept as-is — verify before analysis."
            )

    if c_unit_raw:
        molar_markers = ("mol/", "nmol", "umol", "mmol", "pmol")
        if any(m in c_unit_raw.lower() for m in molar_markers):
            warnings.append(
                f"concentration unit {c_unit_raw!r} is molar; canonical "
                "conversion to ng/mL requires molecular_weight which is not "
                "yet wired through v0.1 ingestion. Values left as-is."
            )
        elif c_unit_raw != "ng/mL":
            try:
                out_df["concentration"] = out_df["concentration"].apply(
                    lambda v: to_canonical_concentration(float(v), c_unit_raw) if pd.notna(v) else v
                )
                conversions_applied["concentration"] = f"{c_unit_raw} -> ng/mL"
            except Exception as exc:  # noqa: BLE001
                warnings.append(
                    f"concentration unit conversion failed "
                    f"({c_unit_raw} -> ng/mL): {exc}. Values kept as-is."
                )

    if conversions_applied:
        warnings.append(
            "canonical_unit_conversion_applied: "
            + ", ".join(f"{k}({v})" for k, v in conversions_applied.items())
        )

    report = IngestReport(
        n_rows=len(out_df),
        n_subjects=n_subjects,
        n_bloq=n_bloq,
        lloq_candidates=sorted(lloq_candidates),
        inferred_units=inferred_units,
        column_mapping=mapping,
        warnings=warnings,
        raw_bloq_patterns_seen=bloq_patterns_seen,
    )

    return out_df, report


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def to_concentration_records(df: pd.DataFrame) -> list[ConcentrationRecord]:
    """Convert a canonical long DataFrame to a list of :class:`ConcentrationRecord`.

    Columns not present in *df* default to the model's field defaults.

    Args:
        df: Canonical DataFrame as produced by :func:`load_dataset`.

    Returns:
        List of validated :class:`~pkplugin.schemas.ConcentrationRecord` instances.
    """
    records: list[ConcentrationRecord] = []
    for _, row in df.iterrows():
        time_val: float = float(row["time"])
        # ConcentrationRecord validator rejects negative time; pre-dose rows
        # arriving here indicate the data has not been shifted yet — we pass
        # them through and let the validator surface the issue to the caller.
        try:
            rec = ConcentrationRecord(
                subject_id=str(row["subject_id"]),
                time=time_val,
                concentration=(
                    float(row["concentration"]) if pd.notna(row.get("concentration")) else None
                ),
                analyte=str(row["analyte"]) if pd.notna(row.get("analyte")) else "parent",
                period=str(row["period"]) if pd.notna(row.get("period")) else None,
                sequence=str(row["sequence"]) if pd.notna(row.get("sequence")) else None,
                treatment=str(row["treatment"]) if pd.notna(row.get("treatment")) else None,
                bloq=bool(row.get("bloq", False)),
                raw_concentration=(
                    str(row["raw_concentration"])
                    if pd.notna(row.get("raw_concentration"))
                    else None
                ),
            )
            records.append(rec)
        except Exception as exc:
            # Surface row-level validation errors as warnings rather than
            # aborting the entire batch.  Callers inspect IngestReport.warnings.
            raise ValueError(
                f"Validation failed for row (subject={row.get('subject_id')!r}, "
                f"time={row.get('time')!r}): {exc}"
            ) from exc
    return records


def to_dose_records(df: pd.DataFrame) -> list[DoseRecord]:
    """Convert a dose table DataFrame to a list of :class:`DoseRecord`.

    Expected columns: ``subject_id``, ``time``, ``amount``, ``route``.
    Optional: ``infusion_duration``, ``period``, ``treatment``.

    Args:
        df: Dose table DataFrame (separate CSV or sheet).

    Returns:
        List of validated :class:`~pkplugin.schemas.DoseRecord` instances.
    """
    records: list[DoseRecord] = []
    for _, row in df.iterrows():
        rec = DoseRecord(
            subject_id=str(row["subject_id"]),
            time=float(row["time"]),
            amount=float(row["amount"]),
            route=str(row["route"]),
            infusion_duration=(
                float(row["infusion_duration"])
                if "infusion_duration" in row.index and pd.notna(row["infusion_duration"])
                else None
            ),
            period=str(row["period"])
            if "period" in row.index and pd.notna(row["period"])
            else None,
            treatment=(
                str(row["treatment"])
                if "treatment" in row.index and pd.notna(row["treatment"])
                else None
            ),
        )
        records.append(rec)
    return records
