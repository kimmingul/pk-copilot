"""
Bioequivalence (BE) statistics module for pk-copilot.

Implements Average Bioequivalence (ABE) for:
  - 2x2 crossover design  (mixed-effects model via statsmodels MixedLM)
  - Parallel design        (Welch t-test on log-transformed parameters)

Endpoint values MUST be log-transformed (FDA/EMA guidance). The
``transformation="untransformed"`` option has been removed — use log only.

Refs:
  - docs/03-algorithms/07-bioequivalence.md
  - docs/04-winnonlin-version-matrix.md §3
  - FDA Guidance for Industry: Statistical Approaches to Establishing
    Bioequivalence (2001)
"""

from __future__ import annotations

import math
import warnings as _warnings
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
import scipy.stats  # type: ignore[import-untyped]
import statsmodels.formula.api as smf  # type: ignore[import-untyped]
from statsmodels.stats.anova import anova_lm  # type: ignore[import-untyped]

BEDesign = Literal["crossover_2x2", "parallel", "replicate_2x4"]
Endpoint = Literal["AUC0_t", "AUC0_inf", "Cmax", "AUClast", "AUCINF_obs"]

# Label sets recognised for auto-detection (all checked case-insensitively).
_LABEL_SETS: list[tuple[str, str]] = [
    ("test", "reference"),
    ("t", "r"),
]


@dataclass(frozen=True)
class BEResult:
    """Immutable container for a single Average Bioequivalence computation.

    All percentage values (GMR, CI bounds, CV) are expressed on the 0–200
    scale (i.e. 100 % = ratio of 1.0).

    Fields
    ------
    anova_table_ols:
        Supplementary OLS-based ANOVA table (Type II).  This is a
        convenience table only; the primary inference is the MixedLM
        t-test on the treatment coefficient.  Do not use this table to
        make the BE decision.
    method:
        Description of the statistical method including df used.
    be_demonstrated:
        True/False if BE is concluded; None if the model fit failed and
        statistics are unreliable.
    """

    design: BEDesign
    endpoint: str
    transformation: Literal["log"]
    n_subjects: int
    n_completers: int
    test_label: str
    reference_label: str
    ls_mean_test: float
    ls_mean_reference: float
    difference_log: float
    gmr_pct: float
    ci_90_low_pct: float
    ci_90_high_pct: float
    be_window: tuple[float, float]
    be_demonstrated: bool | None
    within_subject_cv_pct: float | None
    df: float
    anova_table_ols: dict[str, dict[str, float]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    method: str = ""

    # Keep backward-compatible alias
    @property
    def anova_table(self) -> dict[str, dict[str, float]]:
        return self.anova_table_ols


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_bioequivalence(
    parameters: pd.DataFrame,
    endpoint: str,
    *,
    design: BEDesign = "crossover_2x2",
    test_label: str | None = None,
    reference_label: str | None = None,
    be_window: tuple[float, float] = (80.0, 125.0),
    transformation: Literal["log", "untransformed"] = "log",
    drop_invalid: bool = False,
    winnonlin_version: str = "6.4",
) -> BEResult:
    """Compute Average Bioequivalence statistics.

    Parameters
    ----------
    parameters:
        Subject-level DataFrame with columns:
        ``subject_id``, ``treatment``, ``period``, ``sequence``, ``<endpoint>``.
    endpoint:
        Name of the PK endpoint column to analyse (e.g. ``"AUC0_t"``).
    design:
        Study design code.  Currently ``"crossover_2x2"`` and ``"parallel"``
        are implemented.
    test_label:
        Label used in the ``treatment`` column for the test formulation.
        Auto-detected when *None*.
    reference_label:
        Label used in the ``treatment`` column for the reference formulation.
        Auto-detected when *None*.
    be_window:
        Lower and upper acceptance limits in percent (default 80 %, 125 %).
    transformation:
        Must be ``"log"`` (FDA-recommended). ``"untransformed"`` is not
        supported per FDA guidance; passing it raises ``NotImplementedError``.
    drop_invalid:
        When ``False`` (default), non-positive endpoint values raise
        ``ValueError`` listing offending rows.  When ``True``, those rows
        are silently dropped and the design is re-validated.
    winnonlin_version:
        WinNonlin compatibility version; controls df method choice.

    Returns
    -------
    BEResult

    Raises
    ------
    ValueError
        If required columns are missing, labels cannot be detected, or the
        design is unsupported.
    NotImplementedError
        If ``transformation="untransformed"`` is requested.
    """
    if transformation == "untransformed":
        raise NotImplementedError(
            "transformation='untransformed' is not supported. "
            "Per FDA guidance, ABE requires log-transformation. "
            "Use transformation='log'."
        )

    _validate_columns(parameters, endpoint, design)

    test_label, reference_label = _resolve_labels(
        parameters, test_label, reference_label
    )

    warn: list[str] = []
    df_work = _prepare_data(
        parameters,
        endpoint,
        test_label,
        reference_label,
        warn,
        drop_invalid=drop_invalid,
        design=design,
    )

    n_subjects = int(df_work["subject_id"].nunique())

    if design == "crossover_2x2":
        return _crossover_2x2(
            df_work,
            endpoint=endpoint,
            test_label=test_label,
            reference_label=reference_label,
            be_window=be_window,
            winnonlin_version=winnonlin_version,
            warnings=warn,
            n_subjects_total=n_subjects,
        )
    elif design == "parallel":
        return _parallel(
            df_work,
            endpoint=endpoint,
            test_label=test_label,
            reference_label=reference_label,
            be_window=be_window,
            winnonlin_version=winnonlin_version,
            warnings=warn,
            n_subjects_total=n_subjects,
        )
    else:
        raise ValueError(
            f"Design {design!r} is not implemented in v0.2. "
            "Use 'crossover_2x2' or 'parallel'."
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_columns(
    parameters: pd.DataFrame, endpoint: str, design: BEDesign
) -> None:
    """Raise ValueError if required columns are absent."""
    required = {"subject_id", "treatment", endpoint}
    if design == "crossover_2x2":
        required |= {"period", "sequence"}
    missing = required - set(parameters.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")


def _resolve_labels(
    parameters: pd.DataFrame,
    test_label: str | None,
    reference_label: str | None,
) -> tuple[str, str]:
    """Return (test_label, reference_label), auto-detecting if needed.

    Rules:
    - Both provided → use as-is.
    - One provided → infer the other from the remaining unique value.
    - Neither provided → attempt known-pair match; if no match and labels
      are ambiguous, raise ValueError.
    """
    unique_vals = list(parameters["treatment"].dropna().unique())

    if test_label is not None and reference_label is not None:
        return test_label, reference_label

    # One label provided: infer the other.
    if test_label is not None or reference_label is not None:
        if len(unique_vals) != 2:
            raise ValueError(
                f"Expected exactly 2 unique treatment values to infer the missing "
                f"label, got {len(unique_vals)}: {unique_vals!r}. "
                "Pass both test_label and reference_label explicitly."
            )
        provided = test_label if test_label is not None else reference_label
        others = [str(v) for v in unique_vals if str(v) != str(provided)]
        if len(others) != 1:
            raise ValueError(
                f"Could not uniquely infer the missing label. "
                f"Provided={provided!r}, unique values={unique_vals!r}."
            )
        if test_label is not None:
            return test_label, others[0]
        else:
            return others[0], reference_label  # type: ignore[return-value]

    # Neither provided: attempt known-pair match.
    if len(unique_vals) != 2:
        raise ValueError(
            f"Expected exactly 2 unique treatment values for auto-detection, "
            f"got {len(unique_vals)}: {unique_vals!r}. "
            "Pass test_label and reference_label explicitly."
        )

    lower_vals = [str(v).lower() for v in unique_vals]
    for test_key, ref_key in _LABEL_SETS:
        if test_key in lower_vals and ref_key in lower_vals:
            idx_test = lower_vals.index(test_key)
            idx_ref = lower_vals.index(ref_key)
            return str(unique_vals[idx_test]), str(unique_vals[idx_ref])

    # Two values present but not in a known pair → cannot auto-detect.
    raise ValueError(
        f"Cannot auto-detect Test/Reference. "
        f"Treatment values {unique_vals!r} do not match any known pair. "
        "Pass explicit test_label and reference_label."
    )


def _prepare_data(
    parameters: pd.DataFrame,
    endpoint: str,
    test_label: str,
    reference_label: str,
    warnings_out: list[str],
    *,
    drop_invalid: bool,
    design: BEDesign,
) -> pd.DataFrame:
    """Filter to test/reference rows, log-transform, return copy.

    Non-positive values raise ValueError unless drop_invalid=True.
    After drop, the 2x2 crossover design completers requirement is
    re-validated.
    """
    df = parameters.loc[
        parameters["treatment"].isin([test_label, reference_label])
    ].copy()

    # Drop NaN first.
    n_na = int(df[endpoint].isna().sum())
    if n_na > 0:
        warnings_out.append(
            f"{n_na} row(s) with missing {endpoint!r} dropped."
        )
        df = df.dropna(subset=[endpoint]).copy()

    mask_nonpos = df[endpoint] <= 0
    n_bad = int(mask_nonpos.sum())
    if n_bad > 0:
        if not drop_invalid:
            bad_rows = df.loc[mask_nonpos, ["subject_id", "treatment", endpoint]]
            raise ValueError(
                f"{n_bad} row(s) with non-positive {endpoint!r} found. "
                f"Set drop_invalid=True to drop them automatically.\n"
                f"Offending rows:\n{bad_rows.to_string(index=False)}"
            )
        warnings_out.append(
            f"{n_bad} row(s) with non-positive {endpoint!r} dropped before "
            "log-transformation."
        )
        df = df.loc[~mask_nonpos].copy()

        # Re-validate: 2x2 crossover requires both periods per subject.
        if design == "crossover_2x2":
            counts = df.groupby("subject_id")["treatment"].nunique()
            incomplete = counts[counts < 2].index.tolist()
            if incomplete:
                warnings_out.append(
                    f"After dropping invalid rows, {len(incomplete)} subject(s) "
                    f"have only one treatment period: {incomplete}. "
                    "These subjects are excluded from the completer count."
                )

    df["ln_y"] = np.log(df[endpoint].astype(float))

    # Ensure categorical columns are strings for statsmodels formulas.
    for col in ("subject_id", "treatment", "sequence", "period"):
        if col in df.columns:
            df[col] = df[col].astype(str)

    return df


def _validate_subject_uniqueness(df: pd.DataFrame) -> None:
    """Raise ValueError if subject_id is reused across sequences (H2).

    Each subject must belong to exactly one sequence. If subject IDs are
    reused across sequences (e.g. S001 in TR and S001 in RT), the random
    effect grouping would wrongly merge them.
    """
    seq_per_subject = df.groupby("subject_id")["sequence"].nunique()
    duplicates = seq_per_subject[seq_per_subject > 1].index.tolist()
    if duplicates:
        raise ValueError(
            f"subject_id is reused across sequences for: {duplicates}. "
            "Each subject must appear in exactly one sequence. "
            "Ensure subject IDs are globally unique across sequences."
        )


def _n_completers_crossover(df: pd.DataFrame) -> int:
    """Count subjects with observations in both Test and Reference periods."""
    counts = df.groupby("subject_id")["treatment"].nunique()
    return int((counts >= 2).sum())


def _crossover_2x2(
    df: pd.DataFrame,
    *,
    endpoint: str,
    test_label: str,
    reference_label: str,
    be_window: tuple[float, float],
    winnonlin_version: str,
    warnings: list[str],
    n_subjects_total: int,
) -> BEResult:
    """Fit MixedLM for 2x2 crossover and compute BE statistics."""
    n_completers = _n_completers_crossover(df)

    # H2: Validate subject uniqueness across sequences.
    _validate_subject_uniqueness(df)

    # -----------------------------------------------------------------------
    # Mixed-effects model (C1 fix: explicit reference in formula)
    # Use C(treatment, Treatment(reference=reference_label)) so statsmodels
    # always encodes the coefficient as Test - Reference unambiguously.
    # -----------------------------------------------------------------------
    formula = (
        f"ln_y ~ sequence + period + "
        f"C(treatment, Treatment(reference='{reference_label}'))"
    )

    fit_warnings: list[str] = []
    result = None
    converged = True

    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        try:
            model = smf.mixedlm(formula, data=df, groups=df["subject_id"])
            result = model.fit(reml=True, method="lbfgs")
        except Exception as exc:
            warnings.append(f"MixedLM fitting failed: {exc}")
            converged = False
        for w in caught:
            if issubclass(w.category, UserWarning):
                fit_warnings.append(str(w.message))

    # H3: Check convergence and finite statistics.
    if result is not None:
        # Check result.converged if available, else check scale.
        if hasattr(result, "converged") and not result.converged:
            converged = False
        try:
            scale_val = float(result.scale)
            if not math.isfinite(scale_val) or scale_val <= 0:
                converged = False
        except Exception:
            converged = False

    if not converged or result is None:
        warnings.extend(fit_warnings)
        warnings.append(
            "MixedLM did not converge or produced unreliable estimates. "
            "BE conclusion is unreliable (be_demonstrated=None)."
        )
        # Return a result with be_demonstrated=None to signal unreliability.
        _arr_test_nc: np.ndarray[tuple[int], np.dtype[np.float64]] = (
            df.loc[df["treatment"] == test_label, "ln_y"].to_numpy(dtype=float)
        )
        _arr_ref_nc: np.ndarray[tuple[int], np.dtype[np.float64]] = (
            df.loc[df["treatment"] == reference_label, "ln_y"].to_numpy(dtype=float)
        )
        _diff_nc = float(np.mean(_arr_test_nc) - np.mean(_arr_ref_nc))
        return BEResult(
            design="crossover_2x2",
            endpoint=endpoint,
            transformation="log",
            n_subjects=n_subjects_total,
            n_completers=n_completers,
            test_label=test_label,
            reference_label=reference_label,
            ls_mean_test=float(np.mean(_arr_test_nc)),
            ls_mean_reference=float(np.mean(_arr_ref_nc)),
            difference_log=_diff_nc,
            gmr_pct=100.0 * math.exp(_diff_nc),
            ci_90_low_pct=float("nan"),
            ci_90_high_pct=float("nan"),
            be_window=be_window,
            be_demonstrated=None,
            within_subject_cv_pct=None,
            df=float("nan"),
            anova_table_ols={},
            warnings=warnings,
            method="MixedLM(failed)",
        )

    # Emit any non-fatal fit warnings.
    warnings.extend(fit_warnings)

    # -----------------------------------------------------------------------
    # Extract treatment coefficient (C1 fix: name is now unambiguous)
    # The coefficient name from the formula is:
    #   C(treatment, Treatment(reference='<ref>'))[T.<test>]
    # -----------------------------------------------------------------------
    trt_coef_name: str | None = None
    for name in result.params.index.tolist():
        if "treatment" in name.lower() and f"[T.{test_label}]" in name:
            trt_coef_name = name
            break
    # Fallback: any treatment coefficient.
    if trt_coef_name is None:
        for name in result.params.index.tolist():
            if "treatment" in name.lower() and "[T." in name:
                trt_coef_name = name
                break

    if trt_coef_name is None:
        warnings.append(
            "Treatment coefficient not found in MixedLM params; "
            "fell back to direct group mean contrast."
        )
        diff_log, se_diff, df_val = _manual_contrast(df, test_label, reference_label)
    else:
        # With explicit reference, coefficient is always Test - Reference.
        diff_log = float(result.params[trt_coef_name])
        se_diff = float(result.bse[trt_coef_name])

        # H3: Check SE is finite.
        if not math.isfinite(se_diff) or se_diff <= 0:
            warnings.append(
                f"Treatment SE is not finite ({se_diff}); "
                "BE conclusion may be unreliable."
            )

        # H1: Use df = n_completers - 2 for balanced complete 2x2 crossover.
        df_val = float(n_completers - 2)

    # -----------------------------------------------------------------------
    # 90% CI via TOST
    # -----------------------------------------------------------------------
    t_crit = float(scipy.stats.t.ppf(0.95, df_val))
    ci_low_log = diff_log - t_crit * se_diff
    ci_high_log = diff_log + t_crit * se_diff

    # -----------------------------------------------------------------------
    # LS means: raw group means on log scale (M1 note: documented limitation)
    # For balanced 2x2, these equal the model LSMeans. For imbalanced data,
    # a warning is emitted and raw means are used as approximation.
    # -----------------------------------------------------------------------
    _arr_test: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        df.loc[df["treatment"] == test_label, "ln_y"].to_numpy(dtype=float)
    )
    _arr_ref: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        df.loc[df["treatment"] == reference_label, "ln_y"].to_numpy(dtype=float)
    )
    n_test_per_seq = df[df["treatment"] == test_label].groupby("sequence").size()
    n_ref_per_seq = df[df["treatment"] == reference_label].groupby("sequence").size()
    if n_test_per_seq.std() > 0 or n_ref_per_seq.std() > 0:
        warnings.append(
            "Imbalanced sequence groups detected. "
            "ls_mean_test/ls_mean_reference are raw log-scale group means, "
            "not model LSMeans. Interpret with caution."
        )
    ls_mean_test = float(np.mean(_arr_test))
    ls_mean_ref = float(np.mean(_arr_ref))

    gmr_pct = 100.0 * math.exp(diff_log)
    ci_low_pct = 100.0 * math.exp(ci_low_log)
    ci_high_pct = 100.0 * math.exp(ci_high_log)

    # -----------------------------------------------------------------------
    # Within-subject CV from residual variance
    # -----------------------------------------------------------------------
    within_cv: float | None = None
    try:
        sigma2_resid = float(result.scale)
        if sigma2_resid > 0:
            within_cv = 100.0 * math.sqrt(math.exp(sigma2_resid) - 1.0)
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Supplementary ANOVA table (OLS-based, Type II) — M2: clearly named
    # -----------------------------------------------------------------------
    anova_tbl: dict[str, dict[str, float]] = {}
    try:
        ols_model = smf.ols(
            "ln_y ~ sequence + period + treatment", data=df
        ).fit()
        at = anova_lm(ols_model, typ=2)
        for term in ("sequence", "period", "treatment"):
            if term in at.index:
                anova_tbl[term] = {
                    "F": float(at.loc[term, "F"]),
                    "p": float(at.loc[term, "PR(>F)"]),
                }
    except Exception as exc:
        warnings.append(f"Supplementary OLS ANOVA table computation failed: {exc}")

    be_demo: bool | None = be_window[0] <= ci_low_pct and ci_high_pct <= be_window[1]

    return BEResult(
        design="crossover_2x2",
        endpoint=endpoint,
        transformation="log",
        n_subjects=n_subjects_total,
        n_completers=n_completers,
        test_label=test_label,
        reference_label=reference_label,
        ls_mean_test=ls_mean_test,
        ls_mean_reference=ls_mean_ref,
        difference_log=diff_log,
        gmr_pct=gmr_pct,
        ci_90_low_pct=ci_low_pct,
        ci_90_high_pct=ci_high_pct,
        be_window=be_window,
        be_demonstrated=be_demo,
        within_subject_cv_pct=within_cv,
        df=df_val,
        anova_table_ols=anova_tbl,
        warnings=warnings,
        method=f"MixedLM(reml=True) / df=n_completers-2={df_val:.0f}",
    )


def _parallel(
    df: pd.DataFrame,
    *,
    endpoint: str,
    test_label: str,
    reference_label: str,
    be_window: tuple[float, float],
    winnonlin_version: str,
    warnings: list[str],
    n_subjects_total: int,
) -> BEResult:
    """Welch t-test on log-transformed endpoint for parallel design."""
    y_test: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        df.loc[df["treatment"] == test_label, "ln_y"].to_numpy(dtype=float)
    )
    y_ref: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        df.loc[df["treatment"] == reference_label, "ln_y"].to_numpy(dtype=float)
    )

    n_test = len(y_test)
    n_ref = len(y_ref)
    n_completers = n_test + n_ref  # parallel: each subject contributes once

    if n_test < 2 or n_ref < 2:
        raise ValueError(
            f"Need at least 2 subjects per arm for Welch t-test. "
            f"Got n_test={n_test}, n_ref={n_ref}."
        )

    mean_test = float(np.mean(y_test))
    mean_ref = float(np.mean(y_ref))
    diff_log = mean_test - mean_ref

    var_test = float(np.var(y_test, ddof=1))
    var_ref = float(np.var(y_ref, ddof=1))
    se_diff = math.sqrt(var_test / n_test + var_ref / n_ref)

    # Satterthwaite df for Welch t-test
    num = (var_test / n_test + var_ref / n_ref) ** 2
    denom = (var_test / n_test) ** 2 / (n_test - 1) + (var_ref / n_ref) ** 2 / (n_ref - 1)
    df_resid = num / denom if denom > 0 else float(n_test + n_ref - 2)

    t_crit = float(scipy.stats.t.ppf(0.95, df_resid))
    ci_low_log = diff_log - t_crit * se_diff
    ci_high_log = diff_log + t_crit * se_diff

    gmr_pct = 100.0 * math.exp(diff_log)
    ci_low_pct = 100.0 * math.exp(ci_low_log)
    ci_high_pct = 100.0 * math.exp(ci_high_log)

    be_demo: bool | None = be_window[0] <= ci_low_pct and ci_high_pct <= be_window[1]

    # Within-subject CV is undefined for parallel design.
    within_cv: float | None = None

    # Supplementary ANOVA table — only treatment term meaningful in parallel.
    anova_tbl: dict[str, dict[str, float]] = {}
    try:
        ols_model = smf.ols("ln_y ~ treatment", data=df).fit()
        at = anova_lm(ols_model, typ=2)
        if "treatment" in at.index:
            anova_tbl["treatment"] = {
                "F": float(at.loc["treatment", "F"]),
                "p": float(at.loc["treatment", "PR(>F)"]),
            }
    except Exception as exc:
        warnings.append(f"Supplementary OLS ANOVA table computation failed: {exc}")

    return BEResult(
        design="parallel",
        endpoint=endpoint,
        transformation="log",
        n_subjects=n_subjects_total,
        n_completers=n_completers,
        test_label=test_label,
        reference_label=reference_label,
        ls_mean_test=mean_test,
        ls_mean_reference=mean_ref,
        difference_log=diff_log,
        gmr_pct=gmr_pct,
        ci_90_low_pct=ci_low_pct,
        ci_90_high_pct=ci_high_pct,
        be_window=be_window,
        be_demonstrated=be_demo,
        within_subject_cv_pct=within_cv,
        df=df_resid,
        anova_table_ols=anova_tbl,
        warnings=warnings,
        method=f"Welch_t / Satterthwaite_df={df_resid:.1f}",
    )


def _manual_contrast(
    df: pd.DataFrame,
    test_label: str,
    reference_label: str,
) -> tuple[float, float, float]:
    """Compute treatment difference, SE, and df via raw group statistics.

    Used as fallback when the statsmodels coefficient cannot be located.
    """
    y_test: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        df.loc[df["treatment"] == test_label, "ln_y"].to_numpy(dtype=float)
    )
    y_ref: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        df.loc[df["treatment"] == reference_label, "ln_y"].to_numpy(dtype=float)
    )
    n_t, n_r = len(y_test), len(y_ref)
    diff = float(np.mean(y_test) - np.mean(y_ref))
    var_t = float(np.var(y_test, ddof=1))
    var_r = float(np.var(y_ref, ddof=1))
    se = math.sqrt(var_t / n_t + var_r / n_r)
    num = (var_t / n_t + var_r / n_r) ** 2
    denom = (
        (var_t / n_t) ** 2 / (n_t - 1)
        + (var_r / n_r) ** 2 / (n_r - 1)
    )
    df_val = num / denom if denom > 0 else float(n_t + n_r - 2)
    return diff, se, df_val
