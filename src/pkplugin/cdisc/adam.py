"""CDISC ADaM ADPC / ADPP dataset builders.

Constructs Analysis Data Model datasets from pk-copilot canonical data and
NCA results.

Refs:
- docs/09-cdisc-support.md §5 — ADaM output domains
- CDISC ADaM IG v1.3
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pandas as pd

from pkplugin.cdisc.paramcd import PARAMCD_REGISTRY, pkcopilot_to_paramcd
from pkplugin.nca.engine import NCAResult

# ---------------------------------------------------------------------------
# ADaM variable lists (column order spec)
# ---------------------------------------------------------------------------

ADPC_VARIABLES = [
    "STUDYID", "USUBJID", "SUBJID", "SITEID", "AGE", "AGEU", "SEX", "RACE",
    "ARM", "ARMCD", "ACTARM",
    "PARAMCD", "PARAM", "PARAMN", "AVAL", "AVALC", "AVALU",
    "AVISIT", "AVISITN", "ATPT", "ATPTN",
    "ADTM", "ADY", "ATM", "NRRLT", "ARRLT",
    "ANL01FL", "SAFFL", "ITTFL", "TRTP", "TRTA",
]

ADPP_VARIABLES = [
    "STUDYID", "USUBJID", "SUBJID", "SITEID", "AGE", "AGEU", "SEX", "RACE",
    "ARM", "ARMCD", "ACTARM",
    "PARAMCD", "PARAM", "PARAMN", "PARCAT1", "PARCAT2",
    "AVAL", "AVALU", "AVALCAT1", "ANL01FL", "TRTP", "TRTA",
    "PPCAT", "PPSCAT", "PPSPEC", "PPMETHOD", "PPSTRESU", "DTYPE",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dm_row(dm_df: pd.DataFrame | None, subject_id: str) -> dict[str, Any]:
    """Extract DM covariates for one subject. Returns empty dict if not found."""
    if dm_df is None or dm_df.empty:
        return {}
    match = dm_df[dm_df["subject_id"].astype(str) == subject_id]
    if match.empty:
        # Try USUBJID column if present
        if "USUBJID" in dm_df.columns:
            match = dm_df[dm_df["USUBJID"].astype(str) == subject_id]
    if match.empty:
        return {}
    row = match.iloc[0]
    return {
        "AGE": row.get("age") if "age" in row.index else row.get("AGE"),
        "AGEU": row.get("ageu") if "ageu" in row.index else row.get("AGEU", "YEARS"),
        "SEX": row.get("sex") if "sex" in row.index else row.get("SEX"),
        "RACE": row.get("race") if "race" in row.index else row.get("RACE"),
        "ARM": row.get("arm") if "arm" in row.index else row.get("ARM"),
        "ARMCD": row.get("armcd") if "armcd" in row.index else row.get("ARMCD"),
        "ACTARM": row.get("actarm") if "actarm" in row.index else row.get("ACTARM"),
    }


def _coerce_na(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Ensure all expected columns exist (as NA if absent)."""
    for col in cols:
        if col not in df.columns:
            df[col] = pd.NA
    return df[cols]


# ---------------------------------------------------------------------------
# ADPC builder
# ---------------------------------------------------------------------------


def build_adpc(
    concentration_df: pd.DataFrame,
    dm_df: pd.DataFrame | None = None,
    study_id: str = "STUDY001",
) -> pd.DataFrame:
    """Build ADaM ADPC (Pharmacokinetic Concentration Analysis Dataset).

    Joins concentration data with DM covariates. Empty optional columns are
    kept as NA.

    Args:
        concentration_df: Canonical pk-copilot long-format DataFrame from
            :func:`pkplugin.cdisc.sdtm.load_sdtm_pc` (or ingest).
            Expected columns: ``subject_id``, ``time``, ``concentration``,
            ``analyte``, ``matrix``, ``bloq``, ``raw_concentration``,
            ``pctpt``, ``pctptnum``, ``pcdtc``, ``pcstresu``.
        dm_df: Optional canonical DM DataFrame from
            :func:`pkplugin.cdisc.sdtm.load_sdtm_dm`.
        study_id: STUDYID to populate.

    Returns:
        ADPC DataFrame with columns matching ``ADPC_VARIABLES``.
    """
    rows: list[dict[str, Any]] = []

    for row_num, (_, row) in enumerate(concentration_df.iterrows(), start=1):
        subject_id = str(row.get("subject_id", ""))
        dm = _dm_row(dm_df, subject_id)

        conc_val = row.get("concentration")
        aval: float | None = None
        if conc_val is not None and not (isinstance(conc_val, float) and pd.isna(conc_val)):
            try:
                aval = float(conc_val)
            except (TypeError, ValueError):
                aval = None

        raw_conc = row.get("raw_concentration")
        avalc = str(raw_conc) if raw_conc is not None and str(raw_conc) not in ("", "nan", "None") else None

        analyte = str(row.get("analyte", "UNKNOWN"))
        paramcd = f"{analyte}PC"
        param = f"{analyte} Concentration"

        atpt = row.get("pctpt")
        atptn = row.get("pctptnum")
        adtm = row.get("pcdtc")
        arrlt = row.get("time")
        nrrlt = atptn  # nominal relative time from PCTPTNUM (hr)
        avalu = row.get("pcstresu", "ng/mL")

        out_row: dict[str, Any] = {
            "STUDYID": study_id,
            "USUBJID": subject_id,
            "SUBJID": subject_id.split("-")[-1] if "-" in subject_id else subject_id,
            "SITEID": subject_id.split("-")[-2] if subject_id.count("-") >= 2 else pd.NA,
            "AGE": dm.get("AGE", pd.NA),
            "AGEU": dm.get("AGEU", "YEARS"),
            "SEX": dm.get("SEX", pd.NA),
            "RACE": dm.get("RACE", pd.NA),
            "ARM": dm.get("ARM", pd.NA),
            "ARMCD": dm.get("ARMCD", pd.NA),
            "ACTARM": dm.get("ACTARM", pd.NA),
            "PARAMCD": paramcd,
            "PARAM": param,
            "PARAMN": row_num,
            "AVAL": aval,
            "AVALC": avalc if avalc else (str(aval) if aval is not None else pd.NA),
            "AVALU": avalu,
            "AVISIT": row.get("visit", pd.NA),
            "AVISITN": row.get("visitnum", pd.NA),
            "ATPT": str(atpt) if atpt is not None and str(atpt) not in ("", "nan", "None") else pd.NA,
            "ATPTN": atptn if atptn is not None else pd.NA,
            "ADTM": str(adtm) if adtm is not None and str(adtm) not in ("", "nan", "None") else pd.NA,
            "ADY": pd.NA,
            "ATM": float(arrlt) if arrlt is not None and not (isinstance(arrlt, float) and pd.isna(arrlt)) else pd.NA,
            "NRRLT": float(nrrlt) if nrrlt is not None and not (isinstance(nrrlt, float) and pd.isna(nrrlt)) else pd.NA,
            "ARRLT": float(arrlt) if arrlt is not None and not (isinstance(arrlt, float) and pd.isna(arrlt)) else pd.NA,
            "ANL01FL": "Y",
            "SAFFL": pd.NA,
            "ITTFL": pd.NA,
            "TRTP": dm.get("ARM", pd.NA),
            "TRTA": dm.get("ACTARM", pd.NA),
        }
        rows.append(out_row)

    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=ADPC_VARIABLES)
    return _coerce_na(df, ADPC_VARIABLES)


# ---------------------------------------------------------------------------
# ADPP builder
# ---------------------------------------------------------------------------


def build_adpp(
    nca_results: list[NCAResult],
    dm_df: pd.DataFrame | None = None,
    study_id: str = "STUDY001",
    pp_method: str = "PKCOPILOT_NCA",
) -> pd.DataFrame:
    """Build ADaM ADPP (PK Parameters Analysis Dataset).

    Each NCAResult contributes one row per parameter present in
    PARAMCD_REGISTRY (unmapped parameters are silently skipped).

    Args:
        nca_results: List of NCAResult from ``pkplugin.nca.engine``.
        dm_df: Optional canonical DM DataFrame.
        study_id: STUDYID to populate.
        pp_method: PPMETHOD string (analysis method name).

    Returns:
        ADPP DataFrame with columns matching ``ADPP_VARIABLES``.
    """
    rows: list[dict[str, Any]] = []
    paramn_map: dict[str, int] = {}
    _next_paramn = [1]

    def _get_paramn(paramcd: str) -> int:
        if paramcd not in paramn_map:
            paramn_map[paramcd] = _next_paramn[0]
            _next_paramn[0] += 1
        return paramn_map[paramcd]

    for result in nca_results:
        subject_id = result.subject_id
        dm = _dm_row(dm_df, subject_id)
        analyte = result.analyte

        # PPSCAT from analyte / matrix info (default: PLASMA ANALYTE)
        ppscat = "PLASMA ANALYTE"

        for pkname, value in result.parameters.items():
            paramcd = pkcopilot_to_paramcd(pkname)
            if paramcd is None:
                continue  # skip unmapped parameters

            entry = PARAMCD_REGISTRY[paramcd]
            aval: float | None = None
            if value is not None:
                try:
                    aval = float(value)
                except (TypeError, ValueError):
                    aval = None

            out_row: dict[str, Any] = {
                "STUDYID": study_id,
                "USUBJID": subject_id,
                "SUBJID": subject_id.split("-")[-1] if "-" in subject_id else subject_id,
                "SITEID": subject_id.split("-")[-2] if subject_id.count("-") >= 2 else pd.NA,
                "AGE": dm.get("AGE", pd.NA),
                "AGEU": dm.get("AGEU", "YEARS"),
                "SEX": dm.get("SEX", pd.NA),
                "RACE": dm.get("RACE", pd.NA),
                "ARM": dm.get("ARM", pd.NA),
                "ARMCD": dm.get("ARMCD", pd.NA),
                "ACTARM": dm.get("ACTARM", pd.NA),
                "PARAMCD": entry.paramcd,
                "PARAM": entry.param,
                "PARAMN": _get_paramn(entry.paramcd),
                "PARCAT1": "PK PARAMETER",
                "PARCAT2": analyte.upper(),
                "AVAL": aval,
                "AVALU": entry.unit,
                "AVALCAT1": pd.NA,
                "ANL01FL": "Y",
                "TRTP": dm.get("ARM", pd.NA),
                "TRTA": dm.get("ACTARM", pd.NA),
                "PPCAT": "NON-COMPARTMENTAL",
                "PPSCAT": ppscat,
                "PPSPEC": "PLASMA",
                "PPMETHOD": pp_method,
                "PPSTRESU": entry.unit,
                "DTYPE": pd.NA,
            }
            rows.append(out_row)

    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=ADPP_VARIABLES)
    return _coerce_na(df, ADPP_VARIABLES)


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_adam_dataset(
    df: pd.DataFrame,
    path: str | Path,
    format: Literal["csv", "xpt"] = "csv",
) -> Path:
    """Persist an ADPC or ADPP DataFrame to disk.

    Args:
        df: The ADaM DataFrame to write.
        path: Destination file path.
        format: ``"csv"`` (supported) or ``"xpt"`` (post-v2.0, raises error).

    Returns:
        Resolved Path of the written file.

    Raises:
        NotImplementedError: When ``format="xpt"`` is requested.
    """
    if format == "xpt":
        raise NotImplementedError(
            "SAS XPT output is planned for post-v2.0. "
            "Use format='csv' for now."
            # TODO(v2.1): implement XPT output via pyreadstat.write_xport
        )
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    return dest.resolve()
