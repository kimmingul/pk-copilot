"""
Tests for pkplugin.report.tables.

Covers:
- build_nca_parameter_table: basic construction, metadata, warnings
- pivot_subject_x_parameter: wide format, parameter selection
- build_descriptive_table: group stats round-trip
- build_be_summary_table: BE summary, verdict fields

Refs: docs/02-roadmap.md v0.5
"""

from __future__ import annotations

import pandas as pd
import pytest

from pkplugin.nca.stats import DescriptiveSummary, GroupedStats
from pkplugin.report.tables import (
    ParameterTable,
    build_be_summary_table,
    build_descriptive_table,
    build_nca_parameter_table,
    pivot_subject_x_parameter,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_nca_results() -> list:
    """Build minimal NCAResult-like objects via the real engine."""
    from pkplugin.nca.engine import calculate_nca
    from pkplugin.schemas import ConcentrationRecord, DoseRecord, NCAConfig

    times = [0.0, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0]
    concs = [0.0, 4.0, 8.0, 6.0, 4.0, 2.5, 1.5, 0.5]

    records = [
        ConcentrationRecord(subject_id="S1", time=t, concentration=c, analyte="drug")
        for t, c in zip(times, concs)
    ]
    dose = [DoseRecord(subject_id="S1", time=0.0, amount=100.0, route="oral")]
    cfg = NCAConfig()
    return list(calculate_nca(records, dose, cfg))


def _make_be_result():
    """Build a real BEResult via run_bioequivalence."""
    import pandas as pd

    from pkplugin.nca.bioequivalence import run_bioequivalence

    df = pd.DataFrame(
        {
            "subject_id": ["S1", "S2", "S3", "S4", "S5", "S6", "S1", "S2", "S3", "S4", "S5", "S6"],
            "period": ["1", "1", "1", "1", "1", "1", "2", "2", "2", "2", "2", "2"],
            "sequence": ["TR", "TR", "TR", "RT", "RT", "RT", "TR", "TR", "TR", "RT", "RT", "RT"],
            "treatment": ["T", "T", "T", "R", "R", "R", "R", "R", "R", "T", "T", "T"],
            "AUClast": [
                110.0,
                105.0,
                115.0,
                100.0,
                98.0,
                102.0,
                95.0,
                100.0,
                105.0,
                112.0,
                108.0,
                117.0,
            ],
        }
    )
    return run_bioequivalence(df, endpoint="AUClast", design="crossover_2x2")


# ---------------------------------------------------------------------------
# Test 1: build_nca_parameter_table basics
# ---------------------------------------------------------------------------


def test_build_nca_parameter_table_nonempty() -> None:
    results = _make_nca_results()
    table = build_nca_parameter_table(results)
    assert isinstance(table, ParameterTable)
    assert len(table.rows) > 0
    assert not table.df.empty
    assert "parameter" in table.df.columns
    assert "value" in table.df.columns
    assert table.title == "NCA Parameters"


def test_build_nca_parameter_table_subject_present() -> None:
    results = _make_nca_results()
    table = build_nca_parameter_table(results)
    subjects = table.df["subject_id"].unique().tolist()
    assert "S1" in subjects


def test_build_nca_parameter_table_metadata() -> None:
    results = _make_nca_results()
    table = build_nca_parameter_table(results, title="Custom Title")
    assert table.title == "Custom Title"
    assert isinstance(table.metadata, dict)


def test_build_nca_parameter_table_include_warnings_false() -> None:
    results = _make_nca_results()
    table = build_nca_parameter_table(results, include_warnings=False)
    assert "warnings" not in table.df.columns


def test_build_nca_parameter_table_include_warnings_true() -> None:
    results = _make_nca_results()
    table = build_nca_parameter_table(results, include_warnings=True)
    assert "warnings" in table.df.columns


def test_build_nca_parameter_table_empty_input() -> None:
    table = build_nca_parameter_table([])
    assert table.df.empty
    assert table.rows == []


# ---------------------------------------------------------------------------
# Test 2: pivot_subject_x_parameter
# ---------------------------------------------------------------------------


def test_pivot_subject_x_parameter_basic() -> None:
    results = _make_nca_results()
    table = build_nca_parameter_table(results)
    wide = pivot_subject_x_parameter(table)
    assert isinstance(wide, pd.DataFrame)
    assert not wide.empty
    assert "subject_id" in wide.columns
    # Some known parameters should be columns
    all_params = set(table.df["parameter"].unique())
    for col in wide.columns:
        if col not in ("subject_id", "period", "treatment", "analyte"):
            assert col in all_params


def test_pivot_subject_x_parameter_filter() -> None:
    results = _make_nca_results()
    table = build_nca_parameter_table(results)
    wide = pivot_subject_x_parameter(table, parameters=["Cmax", "AUClast"])
    param_cols = [
        c for c in wide.columns if c not in ("subject_id", "period", "treatment", "analyte")
    ]
    assert set(param_cols).issubset({"Cmax", "AUClast"})


def test_pivot_empty_table() -> None:
    table = build_nca_parameter_table([])
    wide = pivot_subject_x_parameter(table)
    assert isinstance(wide, pd.DataFrame)


# ---------------------------------------------------------------------------
# Test 3: build_descriptive_table
# ---------------------------------------------------------------------------


def _make_grouped_stats() -> list[GroupedStats]:
    summary = DescriptiveSummary(
        parameter="Cmax",
        unit="ng/mL",
        n=6,
        n_missing=0,
        mean=8.5,
        sd=1.2,
        cv_pct=14.1,
        geo_mean=8.4,
        geo_cv_pct=15.0,
        median=8.4,
        min=7.0,
        max=10.0,
        q1=8.0,
        q3=9.0,
    )
    return [
        GroupedStats(
            group_keys={"treatment": "Test", "period": "1"},
            n_subjects=6,
            by_parameter={"Cmax": summary},
        )
    ]


def test_build_descriptive_table_structure() -> None:
    groups = _make_grouped_stats()
    table = build_descriptive_table(groups)
    assert isinstance(table, ParameterTable)
    assert not table.df.empty
    assert "parameter" in table.df.columns
    assert "mean" in table.df.columns
    assert "geo_mean" in table.df.columns


def test_build_descriptive_table_values() -> None:
    groups = _make_grouped_stats()
    table = build_descriptive_table(groups)
    row = table.df[table.df["parameter"] == "Cmax"].iloc[0]
    assert row["n"] == 6
    assert abs(float(row["mean"]) - 8.5) < 1e-6


def test_build_descriptive_table_group_keys() -> None:
    groups = _make_grouped_stats()
    table = build_descriptive_table(groups)
    assert "treatment" in table.df.columns
    assert "period" in table.df.columns


def test_build_descriptive_table_empty() -> None:
    table = build_descriptive_table([])
    assert isinstance(table, ParameterTable)
    assert table.df.empty


# ---------------------------------------------------------------------------
# Test 4: build_be_summary_table
# ---------------------------------------------------------------------------


def test_build_be_summary_table_columns() -> None:
    be = _make_be_result()
    table = build_be_summary_table(be)
    assert isinstance(table, ParameterTable)
    assert not table.df.empty
    assert "gmr_pct" in table.df.columns
    assert "ci_90_low_pct" in table.df.columns
    assert "ci_90_high_pct" in table.df.columns
    assert "be_demonstrated" in table.df.columns


def test_build_be_summary_table_metadata() -> None:
    be = _make_be_result()
    table = build_be_summary_table(be, title="BE Summary Test")
    assert table.title == "BE Summary Test"
    assert "endpoint" in table.metadata


def test_build_be_summary_table_one_row() -> None:
    be = _make_be_result()
    table = build_be_summary_table(be)
    assert len(table.rows) == 1
    assert len(table.df) == 1


def test_build_be_summary_table_be_window() -> None:
    be = _make_be_result()
    table = build_be_summary_table(be)
    row = table.df.iloc[0]
    assert float(row["be_window_low"]) == pytest.approx(80.0)
    assert float(row["be_window_high"]) == pytest.approx(125.0)
