"""CDISC SDTM PC/EX/DM domain importers.

Loads SDTM domains from CSV (or SAS XPT via pyreadstat when available) and
returns canonical pk-copilot DataFrames ready for NCA analysis.

Refs:
- docs/09-cdisc-support.md §3 — SDTM domain specifications
- docs/09-cdisc-support.md §4 — ISO 8601 time normalisation
- CDISC SDTM IG v3.4
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_PC_COLS = [
    "STUDYID",
    "USUBJID",
    "PCSEQ",
    "PCTESTCD",
    "PCSTRESN",
    "PCSTRESU",
    "PCSPEC",
    "PCDTC",
]
REQUIRED_EX_COLS = [
    "STUDYID",
    "USUBJID",
    "EXSEQ",
    "EXTRT",
    "EXDOSE",
    "EXDOSU",
    "EXROUTE",
    "EXSTDTC",
]

# ---------------------------------------------------------------------------
# Route mapping
# ---------------------------------------------------------------------------

_ROUTE_MAP: dict[str, str] = {
    "INTRAVENOUS BOLUS": "iv_bolus",
    "INTRAVENOUS": "iv_infusion",
    "INTRAVENOUS DRIP": "iv_infusion",
    "INFUSION": "iv_infusion",
    "ORAL": "oral",
    "SUBCUTANEOUS": "subcut",
    "INTRAMUSCULAR": "im",
}


def map_exroute_to_canonical(exroute: str) -> str:
    """Map SDTM EXROUTE controlled term to pk-copilot canonical route.

    Args:
        exroute: CDISC EXROUTE value, e.g. ``"ORAL"``, ``"INTRAVENOUS BOLUS"``.

    Returns:
        Canonical route string: ``"iv_bolus"``, ``"iv_infusion"``, ``"oral"``,
        ``"subcut"``, ``"im"``, or ``"other"`` for unrecognised values.
    """
    normalised = exroute.strip().upper()
    return _ROUTE_MAP.get(normalised, "other")


# ---------------------------------------------------------------------------
# ISO 8601 time helpers
# ---------------------------------------------------------------------------

_ISO8601_DURATION_RE = re.compile(
    r"^P(?:(\d+(?:\.\d+)?)Y)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)W)?"
    r"(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?"
    r"(?:(\d+(?:\.\d+)?)S)?)?$"
)


def _parse_iso8601_duration_hours(duration: str) -> float | None:
    """Parse an ISO 8601 duration string to hours.

    Supports e.g. ``"PT1H30M"``, ``"PT2H0M"``, ``"P0DT0H30M0S"``.
    Returns ``None`` when the string cannot be parsed.
    """
    m = _ISO8601_DURATION_RE.match(duration.strip())
    if not m:
        return None
    years = float(m.group(1) or 0)
    months = float(m.group(2) or 0)
    weeks = float(m.group(3) or 0)
    days = float(m.group(4) or 0)
    hours = float(m.group(5) or 0)
    minutes = float(m.group(6) or 0)
    seconds = float(m.group(7) or 0)
    # Approximate: 1 year = 8766 h, 1 month = 730.5 h
    total = (
        years * 8766.0
        + months * 730.5
        + weeks * 168.0
        + days * 24.0
        + hours
        + minutes / 60.0
        + seconds / 3600.0
    )
    return total


def _parse_datetime(dtc: str) -> datetime:
    """Parse an ISO 8601 datetime string to an aware or naive datetime.

    Handles:
    - Full datetime: ``"2024-03-01T08:30:00"``
    - Date only: ``"2024-03-01"`` → treated as midnight UTC, warning issued
    - Timezone offset: ``"2024-03-01T08:30:00+09:00"``
    """
    dtc = dtc.strip()
    if len(dtc) == 10:
        # date-only: assume midnight UTC
        return datetime(
            int(dtc[0:4]), int(dtc[5:7]), int(dtc[8:10]),
            tzinfo=timezone.utc,
        )
    try:
        dt = datetime.fromisoformat(dtc)
    except ValueError:
        raise ValueError(f"Cannot parse datetime: {dtc!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_elapsed_time_hours(
    pc_dtc: str,
    dose_dtc: str,
) -> float:
    """Compute elapsed time from dose to PC sample in canonical hours.

    Args:
        pc_dtc: ISO 8601 datetime of sample collection.
        dose_dtc: ISO 8601 datetime of dose administration (reference).

    Returns:
        Elapsed time in hours (may be negative for pre-dose samples).
    """
    pc_dt = _parse_datetime(pc_dtc)
    ex_dt = _parse_datetime(dose_dtc)
    delta: timedelta = pc_dt - ex_dt
    return delta.total_seconds() / 3600.0


def _compute_elapsed_with_pceltm(
    pc_dtc: str,
    dose_dtc: str,
    pceltm: Any,
) -> tuple[float, bool]:
    """Compute elapsed time, preferring PCELTM over PCDTC arithmetic.

    Returns:
        (elapsed_hours, used_pceltm)
    """
    pceltm_str = str(pceltm).strip() if pceltm is not None and str(pceltm).strip() not in ("", "nan") else ""
    if pceltm_str.startswith("P"):
        hours = _parse_iso8601_duration_hours(pceltm_str)
        if hours is not None:
            return hours, True
    return compute_elapsed_time_hours(pc_dtc, dose_dtc), False


# ---------------------------------------------------------------------------
# Generic domain loader
# ---------------------------------------------------------------------------


def _load_domain(path: str | Path) -> pd.DataFrame:
    """Load a SDTM domain from CSV or SAS XPT.

    Raises:
        ValueError: For unsupported file formats.
        FileNotFoundError: When path does not exist.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"SDTM file not found: {p}")
    ext = p.suffix.lower()
    if ext == ".csv":
        df: pd.DataFrame = pd.read_csv(p, dtype=str)
    elif ext in (".xpt", ".sas7bdat"):
        try:
            import pyreadstat
            raw_df, _ = pyreadstat.read_xport(str(p))
            df = raw_df.astype(str)
        except ImportError:
            raise ImportError(
                "pyreadstat is required to read SAS XPT files. "
                "Install with: pip install pyreadstat"
            )
    else:
        raise ValueError(f"Unsupported SDTM format: {ext!r}. Expected .csv or .xpt")
    df.columns = pd.Index([str(c).strip().upper() for c in df.columns])
    return df


# ---------------------------------------------------------------------------
# PC loader
# ---------------------------------------------------------------------------


def load_sdtm_pc(
    path: str | Path,
    *,
    analyte_filter: str | None = None,
    matrix_filter: str | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Load SDTM PC domain and return a canonical long-format concentration DataFrame.

    The canonical DataFrame has columns:
    ``subject_id``, ``time``, ``concentration``, ``analyte``, ``matrix``,
    ``bloq``, ``raw_concentration``, ``studyid``, ``pctpt``, ``pctptnum``,
    ``pcdtc``, ``pcstresu``.

    Time is computed from PCDTC relative to the earliest EX dose date when
    PCELTM is absent.  PCELTM (ISO 8601 duration) takes priority.

    Note: This loader does not join EX; call :func:`load_sdtm_ex` separately
    and pass dose times to the time-normalisation step when PCELTM is absent.
    When PCELTM is present in the PC domain, times are computed without EX.

    Args:
        path: Path to PC domain CSV or XPT file.
        analyte_filter: Keep only rows where PCTESTCD == this value.
        matrix_filter: Keep only rows where PCSPEC == this value.

    Returns:
        Tuple of (canonical_df, warnings_dict).
        warnings_dict keys are warning codes, values are descriptions.
    """
    df = _load_domain(path)
    warnings: dict[str, str] = {}

    # Validate required columns
    missing = [c for c in REQUIRED_PC_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"PC domain missing required columns: {missing}")

    # Apply filters
    if analyte_filter is not None:
        df = df[df["PCTESTCD"].str.strip().str.upper() == analyte_filter.strip().upper()]
        if df.empty:
            warnings["no_analyte"] = f"No rows matching PCTESTCD={analyte_filter!r}"

    if matrix_filter is not None:
        df = df[df["PCSPEC"].str.strip().str.upper() == matrix_filter.strip().upper()]
        if df.empty:
            warnings["no_matrix"] = f"No rows matching PCSPEC={matrix_filter!r}"

    if df.empty:
        empty: pd.DataFrame = pd.DataFrame(
            columns=[
                "subject_id", "time", "concentration", "analyte", "matrix",
                "bloq", "raw_concentration", "studyid", "pctpt", "pctptnum",
                "pcdtc", "pcstresu",
            ]
        )
        return empty, warnings

    rows: list[dict[str, Any]] = []
    date_only_warned = False

    for _, row in df.iterrows():
        subject_id = str(row["USUBJID"]).strip()
        pcdtc = str(row.get("PCDTC", "")).strip()
        pceltm_raw = row.get("PCELTM")

        # Determine time
        time_val: float | None = None
        pceltm_str = str(pceltm_raw).strip() if pceltm_raw is not None and str(pceltm_raw).strip() not in ("", "nan") else ""

        if pceltm_str.startswith("P"):
            parsed_hours = _parse_iso8601_duration_hours(pceltm_str)
            if parsed_hours is not None:
                time_val = parsed_hours
            else:
                warnings["pceltm_parse_failed"] = (
                    f"Could not parse PCELTM={pceltm_str!r}; falling back to PCDTC arithmetic"
                )
        # If time not yet resolved and PCDTC is available, mark for later EX join
        # For now store the PCDTC string; caller must pass ex_df for normalisation
        # OR use compute_elapsed_time_hours after loading both domains.
        # We store raw PCDTC so callers can compute elapsed time.
        if time_val is None and pcdtc:
            if len(pcdtc) == 10:
                if not date_only_warned:
                    warnings["pcdtc_date_only"] = (
                        "Some PCDTC values are date-only (no time component); "
                        "treated as midnight UTC. Elapsed times may be imprecise."
                    )
                    date_only_warned = True
            # Store None; caller normalises using compute_elapsed_time_hours or
            # call normalise_pc_times(pc_df, ex_df) below.
            time_val = None

        # Concentration
        pcstresn = row.get("PCSTRESN", "")
        try:
            conc_val: float | None = float(str(pcstresn).strip()) if str(pcstresn).strip() not in ("", "nan", "NaN") else None
        except (ValueError, TypeError):
            conc_val = None

        pcorres = str(row.get("PCORRES", "")).strip()
        pcstresc = str(row.get("PCSTRESC", "")).strip()
        is_bloq = (
            conc_val is None
            or pcorres.startswith("<")
            or pcstresc.startswith("<")
            or str(row.get("PCSTAT", "")).strip().upper() == "ND"
        )

        # Matrix mapping
        pcspec = str(row.get("PCSPEC", "")).strip().upper()
        matrix_map = {
            "PLASMA": "plasma",
            "SERUM": "serum",
            "BLOOD": "blood",
            "URINE": "urine",
        }
        matrix = matrix_map.get(pcspec, "other")

        rows.append({
            "subject_id": subject_id,
            "time": time_val,       # None when PCELTM absent; normalise via EX
            "concentration": conc_val,
            "analyte": str(row.get("PCTESTCD", "UNKNOWN")).strip(),
            "matrix": matrix,
            "bloq": is_bloq,
            "raw_concentration": pcorres if pcorres else None,
            "studyid": str(row.get("STUDYID", "")).strip(),
            "pctpt": str(row.get("PCTPT", "")).strip() if "PCTPT" in df.columns else None,
            "pctptnum": (
                float(str(row.get("PCTPTNUM", "")).strip())
                if "PCTPTNUM" in df.columns
                and str(row.get("PCTPTNUM", "")).strip() not in ("", "nan")
                else None
            ),
            "pcdtc": pcdtc,
            "pcstresu": str(row.get("PCSTRESU", "")).strip(),
        })

    out_df = pd.DataFrame(rows)
    return out_df, warnings


def normalise_pc_times(
    pc_df: pd.DataFrame,
    ex_df: pd.DataFrame,
) -> pd.DataFrame:
    """Fill in ``time`` column for PC rows where PCELTM was absent.

    Joins PC with EX on USUBJID (matched to ``subject_id``), uses the earliest
    EXSTDTC per subject as the dose reference, and calls
    :func:`compute_elapsed_time_hours`.

    Args:
        pc_df: Output of :func:`load_sdtm_pc` (may have ``time=None`` rows).
        ex_df: Output of :func:`load_sdtm_ex` canonical DataFrame.

    Returns:
        Copy of pc_df with ``time`` filled in.
    """
    # Build per-subject first-dose reference from ex_df
    ref: dict[str, str] = {}
    for _, row in ex_df.iterrows():
        sid = str(row["subject_id"])
        exstdtc = str(row.get("exstdtc", "")).strip()
        if exstdtc and sid not in ref:
            ref[sid] = exstdtc

    result = pc_df.copy()
    for i, row in result.iterrows():
        if row["time"] is not None and not (isinstance(row["time"], float) and pd.isna(row["time"])):
            continue
        sid = str(row["subject_id"])
        pcdtc = str(row.get("pcdtc", "")).strip()
        dose_dtc = ref.get(sid)
        if dose_dtc and pcdtc:
            try:
                result.at[i, "time"] = compute_elapsed_time_hours(pcdtc, dose_dtc)
            except ValueError:
                pass
    return result


# ---------------------------------------------------------------------------
# EX loader
# ---------------------------------------------------------------------------


def load_sdtm_ex(
    path: str | Path,
    *,
    treatment_filter: str | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Load SDTM EX domain and return a canonical dose DataFrame.

    Canonical columns:
    ``subject_id``, ``time`` (0.0 for first dose; relative to EXSTDTC of
    first record per subject), ``amount``, ``route``, ``infusion_duration``,
    ``treatment``, ``studyid``, ``exstdtc``, ``exdosu``.

    Args:
        path: Path to EX domain CSV or XPT file.
        treatment_filter: Keep only rows where EXTRT == this value.

    Returns:
        Tuple of (canonical_df, warnings_dict).
    """
    df = _load_domain(path)
    warnings: dict[str, str] = {}

    missing = [c for c in REQUIRED_EX_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"EX domain missing required columns: {missing}")

    if treatment_filter is not None:
        df = df[df["EXTRT"].str.strip().str.upper() == treatment_filter.strip().upper()]
        if df.empty:
            warnings["no_treatment"] = f"No rows matching EXTRT={treatment_filter!r}"

    rows: list[dict[str, Any]] = []
    unrecognised_routes: list[str] = []

    for _, row in df.iterrows():
        subject_id = str(row["USUBJID"]).strip()
        exstdtc = str(row.get("EXSTDTC", "")).strip()

        try:
            dose_amount = float(str(row.get("EXDOSE", "")).strip())
        except (ValueError, TypeError):
            dose_amount = 0.0
            warnings["dose_parse"] = "Some EXDOSE values could not be parsed; defaulting to 0."

        exroute = str(row.get("EXROUTE", "")).strip()
        canonical_route = map_exroute_to_canonical(exroute)
        if canonical_route == "other" and exroute:
            unrecognised_routes.append(exroute)

        # Infusion duration from EXSTDTC / EXENDTC
        infusion_duration: float | None = None
        exendtc = str(row.get("EXENDTC", "")).strip() if "EXENDTC" in df.columns else ""
        if exendtc and exendtc not in ("", "nan", "NaN") and exstdtc:
            try:
                delta = compute_elapsed_time_hours(exendtc, exstdtc)
                if delta > 0:
                    infusion_duration = delta
            except ValueError:
                pass

        rows.append({
            "subject_id": subject_id,
            "time": 0.0,            # First dose assumed at t=0 for NCA
            "amount": dose_amount,
            "route": canonical_route,
            "infusion_duration": infusion_duration,
            "treatment": str(row.get("EXTRT", "")).strip(),
            "studyid": str(row.get("STUDYID", "")).strip(),
            "exstdtc": exstdtc,
            "exdosu": str(row.get("EXDOSU", "")).strip(),
        })

    if unrecognised_routes:
        unique_routes = sorted(set(unrecognised_routes))
        warnings["unrecognised_routes"] = (
            f"EXROUTE values not in CDISC CT mapped to 'other': {unique_routes}"
        )

    out_df = pd.DataFrame(rows)
    return out_df, warnings


# ---------------------------------------------------------------------------
# DM loader
# ---------------------------------------------------------------------------


def load_sdtm_dm(path: str | Path) -> pd.DataFrame:
    """Load SDTM DM domain and return canonical covariate DataFrame.

    Canonical columns:
    ``subject_id``, ``age``, ``ageu``, ``sex``, ``race``, ``arm``,
    ``armcd``, ``actarm``, ``country``, ``rfstdtc``, ``studyid``.

    Args:
        path: Path to DM domain CSV or XPT file.

    Returns:
        Canonical covariate DataFrame (one row per subject).
    """
    df = _load_domain(path)

    def _get(row: Any, col: str) -> str | None:
        val = row.get(col, "")
        s = str(val).strip() if val is not None else ""
        return s if s not in ("", "nan", "NaN") else None

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        age_str = _get(row, "AGE")
        try:
            age = float(age_str) if age_str else None
        except (ValueError, TypeError):
            age = None

        sex_raw = (_get(row, "SEX") or "").upper()
        sex = sex_raw if sex_raw in ("M", "F") else "U"

        rows.append({
            "subject_id": str(row.get("USUBJID", "")).strip(),
            "age": age,
            "ageu": _get(row, "AGEU") or "YEARS",
            "sex": sex,
            "race": _get(row, "RACE"),
            "arm": _get(row, "ARM"),
            "armcd": _get(row, "ARMCD"),
            "actarm": _get(row, "ACTARM"),
            "country": _get(row, "COUNTRY"),
            "rfstdtc": _get(row, "RFSTDTC"),
            "studyid": _get(row, "STUDYID"),
        })

    return pd.DataFrame(rows)
