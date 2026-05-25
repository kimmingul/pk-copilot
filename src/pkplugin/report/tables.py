"""
Report tables module for pk-copilot v0.5.

Produces WinNonlin-style parameter tables from NCA results, descriptive
statistics groups, and BE results.

Refs: docs/02-roadmap.md v0.5
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

import pandas as pd

if TYPE_CHECKING:
    from pkplugin.nca.engine import NCAResult
    from pkplugin.nca.stats import GroupedStats
    from pkplugin.nca.bioequivalence import BEResult


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParameterTable:
    """WinNonlin-style long-format parameter table."""

    rows: list[dict[str, object]]
    df: pd.DataFrame
    title: str
    metadata: dict[str, str]  # winnonlin_version, auc_method, run_id, ...


# ---------------------------------------------------------------------------
# NCA parameter table
# ---------------------------------------------------------------------------


def build_nca_parameter_table(
    results: Sequence["NCAResult"],
    title: str = "NCA Parameters",
    include_warnings: bool = True,
) -> ParameterTable:
    """Long-format parameter table from NCAResults.

    Returns a ParameterTable whose ``df`` has columns:
      subject_id, period, treatment, analyte, parameter, value, unit,
      method, winnonlin_version, flags, comment, [warnings]
    """
    rows: list[dict[str, object]] = []
    metadata: dict[str, str] = {}

    for result in results:
        for prow in result.parameter_rows:
            row: dict[str, object] = {
                "subject_id": prow.subject_id,
                "period": prow.period,
                "treatment": prow.treatment,
                "analyte": prow.analyte,
                "parameter": prow.parameter,
                "value": prow.value,
                "unit": prow.unit,
                "method": prow.method,
                "winnonlin_version": prow.winnonlin_version,
                "flags": ";".join(prow.flags),
                "comment": prow.comment,
            }
            if include_warnings:
                row["warnings"] = ";".join(result.warnings)
            rows.append(row)
            # Capture metadata from first populated row
            if not metadata and prow.winnonlin_version:
                metadata["winnonlin_version"] = prow.winnonlin_version

    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=[
            "subject_id", "period", "treatment", "analyte",
            "parameter", "value", "unit", "method",
            "winnonlin_version", "flags", "comment",
        ]
    )
    return ParameterTable(rows=rows, df=df, title=title, metadata=metadata)


# ---------------------------------------------------------------------------
# Pivot: subjects × parameters
# ---------------------------------------------------------------------------


def pivot_subject_x_parameter(
    table: ParameterTable,
    parameters: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Wide-format pivot: subjects on rows, parameters on columns.

    Index columns retained: subject_id, period, treatment, analyte.
    Each requested parameter becomes its own column with numeric values.
    Missing subject/parameter combinations become NaN.
    """
    df = table.df.copy()
    if df.empty:
        return df

    id_cols = [c for c in ("subject_id", "period", "treatment", "analyte") if c in df.columns]
    if "parameter" not in df.columns or "value" not in df.columns:
        return df

    if parameters is not None:
        df = df[df["parameter"].isin(parameters)]

    wide = df.pivot_table(
        index=id_cols,
        columns="parameter",
        values="value",
        aggfunc="first",
        dropna=False,
    ).reset_index()
    wide.columns.name = None
    return wide


# ---------------------------------------------------------------------------
# Descriptive statistics table
# ---------------------------------------------------------------------------


def build_descriptive_table(
    stats_groups: Sequence["GroupedStats"],
    title: str = "Descriptive Statistics",
) -> ParameterTable:
    """Long-format descriptive statistics table.

    Each row contains one (group, parameter, statistic) combination with
    columns: group_keys (flattened as separate columns), parameter, unit,
    n, n_missing, mean, sd, cv_pct, geo_mean, geo_cv_pct,
    median, min, max, q1, q3.
    """
    rows: list[dict[str, object]] = []

    for group in stats_groups:
        group_base: dict[str, object] = dict(group.group_keys)
        group_base["n_subjects"] = group.n_subjects

        for param_name, summary in group.by_parameter.items():
            row: dict[str, object] = {
                **group_base,
                "parameter": param_name,
                "unit": summary.unit,
                "n": summary.n,
                "n_missing": summary.n_missing,
                "mean": summary.mean,
                "sd": summary.sd,
                "cv_pct": summary.cv_pct,
                "geo_mean": summary.geo_mean,
                "geo_cv_pct": summary.geo_cv_pct,
                "median": summary.median,
                "min": summary.min,
                "max": summary.max,
                "q1": summary.q1,
                "q3": summary.q3,
            }
            rows.append(row)

    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    return ParameterTable(rows=rows, df=df, title=title, metadata={})


# ---------------------------------------------------------------------------
# BE summary table
# ---------------------------------------------------------------------------


def build_be_summary_table(
    be_result: "BEResult",
    title: str = "Bioequivalence Summary",
) -> ParameterTable:
    """One-row summary table with key BE outputs (GMR, 90% CI, verdict).

    Columns: design, endpoint, transformation, n_subjects, n_completers,
    test_label, reference_label, gmr_pct, ci_90_low_pct, ci_90_high_pct,
    be_window_low, be_window_high, be_demonstrated, within_subject_cv_pct,
    df, method.
    """
    row: dict[str, object] = {
        "design": be_result.design,
        "endpoint": be_result.endpoint,
        "transformation": be_result.transformation,
        "n_subjects": be_result.n_subjects,
        "n_completers": be_result.n_completers,
        "test_label": be_result.test_label,
        "reference_label": be_result.reference_label,
        "gmr_pct": be_result.gmr_pct,
        "ci_90_low_pct": be_result.ci_90_low_pct,
        "ci_90_high_pct": be_result.ci_90_high_pct,
        "be_window_low": be_result.be_window[0],
        "be_window_high": be_result.be_window[1],
        "be_demonstrated": be_result.be_demonstrated,
        "within_subject_cv_pct": be_result.within_subject_cv_pct,
        "df": be_result.df,
        "method": be_result.method,
    }
    rows = [row]
    df = pd.DataFrame(rows)
    metadata: dict[str, str] = {
        "endpoint": str(be_result.endpoint),
        "design": str(be_result.design),
    }
    return ParameterTable(rows=rows, df=df, title=title, metadata=metadata)
