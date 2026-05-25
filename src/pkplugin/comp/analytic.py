"""
Closed-form (analytical) plasma concentration predictions for compartmental PK models.

Supported models
----------------
- cmt1_iv_bolus    (WinNonlin #1)
- cmt1_iv_infusion (WinNonlin #3)
- cmt1_po          (WinNonlin #5)
- cmt2_iv_bolus    (WinNonlin #7)
- cmt2_iv_infusion (WinNonlin #9)
- cmt2_po          (WinNonlin #11)
- cmt3_iv_bolus    (WinNonlin #13)

All functions are pure, deterministic, and free of I/O.

Refs:
- docs/03-algorithms/08-compartmental-models.md §2
- docs/04-winnonlin-version-matrix.md §4
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import scipy.linalg  # type: ignore[import-untyped]
from numpy.typing import NDArray

from pkplugin.comp.models import REGISTRY, PKModelSpec, get_model

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def predict(
    model: PKModelSpec | str,
    params: dict[str, float],
    times: Sequence[float],
    dose: float,
    infusion_duration: float | None = None,
    tlag: float = 0.0,
    F: float = 1.0,
) -> NDArray[np.float64]:
    """Predict plasma concentration at *times* for a single dose.

    Parameters
    ----------
    model:
        A :class:`~pkplugin.comp.models.PKModelSpec` instance **or** a
        canonical model name string (e.g. ``"cmt2_iv_bolus"``).
    params:
        Dictionary mapping parameter names to positive float values.
        Must contain every name listed in ``model.parameter_names``.
        Values must be positive (strictly > 0); *tlag* is the only
        exception — it may be zero or positive.
    times:
        Sequence of post-dose observation times (≥ 0).
    dose:
        Administered dose (same unit as the concentration × volume product,
        e.g. mg when V is in L and C is in mg/L = μg/mL).
    infusion_duration:
        Duration of constant-rate IV infusion (T_inf, same time unit as
        *times*).  Required when ``model.route == IV_INFUSION``; ignored
        otherwise.
    tlag:
        Absorption lag time.  Only honoured for oral models.  Defaults to 0.
    F:
        Bioavailability fraction (0 < F ≤ 1).  Only applied to oral models;
        the model parameter ``V_F`` or ``V1_F`` already embeds F, so this
        argument should normally be left at 1.0 unless the caller supplies
        true V instead of V/F.

    Returns
    -------
    NDArray[np.float64]
        Array of predicted concentrations with the same length as *times*.

    Raises
    ------
    ValueError
        If a required parameter is missing, any parameter value is
        non-positive, or an unsupported model is requested.

    Refs: docs/03-algorithms/08-compartmental-models.md §2
    """
    spec: PKModelSpec = get_model(model) if isinstance(model, str) else model
    if spec.has_michaelis_menten:
        raise ValueError(
            f"Model {spec.name!r} uses Michaelis-Menten elimination and has "
            "no closed-form solution. Use pkplugin.comp.ode.simulate_ode "
            "instead."
        )
    _validate_params(spec, params)

    t_arr = np.asarray(times, dtype=np.float64)

    if spec.name == "cmt1_iv_bolus":
        return _cmt1_iv_bolus(t_arr, params, dose)
    if spec.name == "cmt1_iv_infusion":
        return _cmt1_iv_infusion(t_arr, params, dose, infusion_duration)
    if spec.name == "cmt1_po":
        return _cmt1_po(t_arr, params, dose, tlag, F)
    if spec.name == "cmt2_iv_bolus":
        return _cmt2_iv_bolus(t_arr, params, dose)
    if spec.name == "cmt2_iv_infusion":
        return _cmt2_iv_infusion(t_arr, params, dose, infusion_duration)
    if spec.name == "cmt2_po":
        return _cmt2_po(t_arr, params, dose, tlag, F)
    if spec.name == "cmt3_iv_bolus":
        return _cmt3_iv_bolus(t_arr, params, dose)

    raise ValueError(
        f"No closed-form implementation for model {spec.name!r}. "
        "Available: " + str(sorted(REGISTRY))
    )


def list_models() -> list[str]:
    """Return the list of registered model names.

    Returns
    -------
    list[str]
        All keys in :data:`~pkplugin.comp.models.REGISTRY`.
    """
    return list(REGISTRY)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_params(spec: PKModelSpec, params: dict[str, float]) -> None:
    """Raise :exc:`ValueError` if any required parameter is missing or non-positive."""
    for name in spec.parameter_names:
        if name not in params:
            raise ValueError(
                f"Model {spec.name!r} requires parameter {name!r}, but it is missing from params."
            )
        val = params[name]
        if not (val > 0):
            raise ValueError(
                f"Parameter {name!r} must be > 0 for model {spec.name!r}; got {val!r}."
            )


def _require_infusion_duration(model_name: str, infusion_duration: float | None) -> float:
    if infusion_duration is None or infusion_duration <= 0:
        raise ValueError(
            f"Model {model_name!r} requires a positive infusion_duration (T_inf); "
            f"got {infusion_duration!r}."
        )
    return float(infusion_duration)


# ---------------------------------------------------------------------------
# 1-compartment IV bolus  (WinNonlin #1)
# ---------------------------------------------------------------------------


def _cmt1_iv_bolus(
    t: NDArray[np.float64],
    params: dict[str, float],
    dose: float,
) -> NDArray[np.float64]:
    """C(t) = (D/V) * exp(-k*t).

    Refs: docs/03-algorithms/08-compartmental-models.md §2.1, WinNonlin model #1
    """
    V = params["V"]
    k = params["k"]
    return (dose / V) * np.exp(-k * t)


# ---------------------------------------------------------------------------
# 1-compartment IV infusion  (WinNonlin #3)
# ---------------------------------------------------------------------------


def _cmt1_iv_infusion(
    t: NDArray[np.float64],
    params: dict[str, float],
    dose: float,
    infusion_duration: float | None,
) -> NDArray[np.float64]:
    """Two-phase closed-form for constant-rate IV infusion.

    During infusion [0, T_inf]:
        C(t) = (R0 / (V*k)) * (1 - exp(-k*t)),   R0 = D / T_inf

    Post-infusion (t > T_inf):
        C(t) = C(T_inf) * exp(-k * (t - T_inf))

    Refs: docs/03-algorithms/08-compartmental-models.md §2.2, WinNonlin model #3
    """
    T_inf = _require_infusion_duration("cmt1_iv_infusion", infusion_duration)
    V = params["V"]
    k = params["k"]

    R0 = dose / T_inf
    Css_factor = R0 / (V * k)

    C_Tinf = Css_factor * (1.0 - math.exp(-k * T_inf))

    during = Css_factor * (1.0 - np.exp(-k * t))
    post = C_Tinf * np.exp(-k * (t - T_inf))

    return np.where(t <= T_inf, during, post)


# ---------------------------------------------------------------------------
# 1-compartment oral (Bateman)  (WinNonlin #5)
# ---------------------------------------------------------------------------


def _cmt1_po(
    t: NDArray[np.float64],
    params: dict[str, float],
    dose: float,
    tlag: float,
    F: float,
) -> NDArray[np.float64]:
    """Bateman equation with optional absorption lag.

    τ = t - tlag; when τ < 0 → C = 0.

    Standard case (|ka - k| ≥ 1e-9):
        C(τ) = (F*D*ka) / (V_F*(ka-k)) * [exp(-k*τ) - exp(-ka*τ)]

    l'Hôpital limit (|ka - k| < 1e-9):
        C(τ) = (F*D*ka*τ / V_F) * exp(-k*τ)

    Flip-flop (ka < k) is handled correctly because the denominator (ka-k)
    is negative, and the concentration remains non-negative.

    Refs: docs/03-algorithms/08-compartmental-models.md §2.3, WinNonlin model #5
    """
    V_F = params["V_F"]
    ka = params["ka"]
    k = params["k"]

    tau = t - tlag
    # Where τ < 0 (before absorption starts) concentration is zero.
    valid = tau >= 0.0

    result = np.zeros_like(t)

    if np.any(valid):
        tau_v = tau[valid]
        if abs(ka - k) < 1e-9:
            # l'Hôpital limit: lim_{ka→k} ka/(ka-k) * [exp(-k*τ) - exp(-ka*τ)]
            #   = ka * τ * exp(-k*τ)
            result[valid] = (F * dose * ka * tau_v / V_F) * np.exp(-k * tau_v)
        else:
            result[valid] = ((F * dose * ka) / (V_F * (ka - k))) * (
                np.exp(-k * tau_v) - np.exp(-ka * tau_v)
            )

    return result


# ---------------------------------------------------------------------------
# 2-compartment IV bolus  (WinNonlin #7)
# ---------------------------------------------------------------------------


def _cmt2_macro_constants(
    params: dict[str, float],
    key_v: str,
) -> tuple[float, float, float, float, float]:
    """Derive 2-cmt macro rate constants (α, β) and amplitudes (A, B) from micros.

    Relations (docs/03-algorithms/08-compartmental-models.md §2.4):
        α + β = k10 + k12 + k21
        α * β = k10 * k21
        A + B = D/V1  (at t=0, C = D/V1; the caller passes D separately)
        A*(α-k21) == ... — fully determined by micro params

    Returns (V1_or_V1F, alpha, beta, A_coeff, B_coeff) where A_coeff and
    B_coeff are the *per unit dose* amplitudes (multiply by dose to get A, B).
    """
    V1 = params[key_v]
    k10 = params["k10"]
    k12 = params["k12"]
    k21 = params["k21"]

    disc = (k10 + k12 + k21) ** 2 - 4.0 * k10 * k21
    sqrt_disc = math.sqrt(max(disc, 0.0))

    alpha = (k10 + k12 + k21 + sqrt_disc) / 2.0
    beta = (k10 + k12 + k21 - sqrt_disc) / 2.0

    denom = alpha - beta  # > 0 always (alpha >= beta)

    # Per-dose amplitudes: A = (D/V1)*(alpha - k21)/(alpha - beta)
    A_coeff = (alpha - k21) / (V1 * denom)
    B_coeff = (k21 - beta) / (V1 * denom)

    return V1, alpha, beta, A_coeff, B_coeff


def _cmt2_iv_bolus(
    t: NDArray[np.float64],
    params: dict[str, float],
    dose: float,
) -> NDArray[np.float64]:
    """C(t) = A*exp(-α*t) + B*exp(-β*t).

    Macro constants derived from micro-rate constants via:
        α + β = k10 + k12 + k21
        α * β = k10 * k21

    Refs: docs/03-algorithms/08-compartmental-models.md §2.4, WinNonlin model #7
    """
    _, alpha, beta, A_coeff, B_coeff = _cmt2_macro_constants(params, "V1")
    A = dose * A_coeff
    B = dose * B_coeff
    return A * np.exp(-alpha * t) + B * np.exp(-beta * t)


# ---------------------------------------------------------------------------
# 2-compartment IV infusion  (WinNonlin #9)
# ---------------------------------------------------------------------------


def _cmt2_iv_infusion(
    t: NDArray[np.float64],
    params: dict[str, float],
    dose: float,
    infusion_duration: float | None,
) -> NDArray[np.float64]:
    """2-cmt IV infusion via superposition on the bolus macro form.

    Uses the principle of superposition: a constant-rate infusion of duration
    T_inf is the sum of an infusion that started at t=0 minus one that started
    at t=T_inf.

    During infusion [0, T_inf]:
        C(t) = (R0/α·V1) * (A_coeff/α)*(1-exp(-α*t))
                          + (B_coeff/β)*(1-exp(-β*t))
        with R0 = D/T_inf

    Post-infusion (t > T_inf): superposition gives
        C(t) = C_during(T_inf) * ... but algebraically simpler to use
               the two-phase formula directly.

    Refs: docs/03-algorithms/08-compartmental-models.md §2.5, WinNonlin model #9
    """
    T_inf = _require_infusion_duration("cmt2_iv_infusion", infusion_duration)
    _, alpha, beta, A_coeff, B_coeff = _cmt2_macro_constants(params, "V1")

    R0 = dose / T_inf  # infusion rate

    # C_rising(t) = R0 * [A_coeff/alpha*(1-exp(-alpha*t))
    #                    + B_coeff/beta*(1-exp(-beta*t))]
    def _rising(t_arr: NDArray[np.float64]) -> NDArray[np.float64]:
        return R0 * (
            (A_coeff / alpha) * (1.0 - np.exp(-alpha * t_arr))
            + (B_coeff / beta) * (1.0 - np.exp(-beta * t_arr))
        )

    C_Tinf = float(_rising(np.array([T_inf]))[0])

    during = _rising(t)

    # Post-infusion: superposition — infusion from 0 minus infusion from T_inf
    # = C_rising(t) - C_rising(t - T_inf) evaluated at the shifted times
    t_shift = t - T_inf
    post = R0 * (
        (A_coeff / alpha) * (1.0 - np.exp(-alpha * t))
        - (A_coeff / alpha) * (1.0 - np.exp(-alpha * t_shift))
        + (B_coeff / beta) * (1.0 - np.exp(-beta * t))
        - (B_coeff / beta) * (1.0 - np.exp(-beta * t_shift))
    )

    # Equivalently simplified: post = A*exp(-alpha*(t-T_inf)) + B*exp(-beta*(t-T_inf))
    # where A,B are the concentration amplitudes at T_inf — use that for clarity.
    A_post = C_Tinf  # scalar placeholder; use exact formula below
    _ = A_post  # suppress warning — we use the superposition directly

    return np.where(t <= T_inf, during, post)


# ---------------------------------------------------------------------------
# 2-compartment oral  (WinNonlin #11)
# ---------------------------------------------------------------------------


def _cmt2_po(
    t: NDArray[np.float64],
    params: dict[str, float],
    dose: float,
    tlag: float,
    F: float,
) -> NDArray[np.float64]:
    """3-exponential oral 2-cmt model with optional lag.

    C(τ) = P*exp(-ka*τ) + A*exp(-α*τ) + B*exp(-β*τ)

    where:
        P = (F*D*ka) / (V1_F*(ka-alpha)*(ka-beta))  ... absorption term
        A = (F*D*ka) / (V1_F*(alpha-ka)*(alpha-beta))
        B = (F*D*ka) / (V1_F*(beta-ka)*(beta-alpha))

    τ = t - tlag; when τ < 0 → C = 0.

    Refs: docs/03-algorithms/08-compartmental-models.md §2.5 (2-cmt IV infusion / PO bundle), WinNonlin model #11
    """
    V1_F = params["V1_F"]
    ka = params["ka"]

    # Build a temporary params dict for the 2-cmt macro extraction
    # (V1_F plays the role of V1 in the 2-cmt disposition system)
    sub_params: dict[str, float] = {
        "V1": V1_F,
        "k10": params["k10"],
        "k12": params["k12"],
        "k21": params["k21"],
    }
    _, alpha, beta, _, _ = _cmt2_macro_constants(sub_params, "V1")

    tau = t - tlag
    valid = tau >= 0.0
    result = np.zeros_like(t)

    if not np.any(valid):
        return result

    tau_v = tau[valid]

    common = F * dose * ka / V1_F

    # Handle near-degenerate cases where ka ≈ alpha or ka ≈ beta.
    # For clinical PK parameters these are very unlikely, but we guard
    # with a small epsilon.
    _EPS = 1e-9

    ka_eq_alpha = abs(ka - alpha) < _EPS
    ka_eq_beta = abs(ka - beta) < _EPS

    if ka_eq_alpha and ka_eq_beta:
        # Triple root: ka ≈ alpha ≈ beta — extremely rare; use l'Hôpital twice.
        result[valid] = common * (tau_v**2 / 2.0) * np.exp(-ka * tau_v)
    elif ka_eq_alpha:
        # ka ≈ alpha; l'Hôpital for the ka/alpha pair.
        # C ≈ common/(alpha-beta) * tau * exp(-alpha*tau)
        #   + common/((beta-ka)*(beta-alpha)) * exp(-beta*tau) ... etc.
        # Use numerical approximation: shift ka slightly.
        ka_adj = ka + 2.0 * _EPS
        P = common / ((ka_adj - alpha) * (ka_adj - beta))
        A_amp = common / ((alpha - ka_adj) * (alpha - beta))
        B_amp = common / ((beta - ka_adj) * (beta - alpha))
        result[valid] = (
            P * np.exp(-ka_adj * tau_v)
            + A_amp * np.exp(-alpha * tau_v)
            + B_amp * np.exp(-beta * tau_v)
        )
    elif ka_eq_beta:
        ka_adj = ka + 2.0 * _EPS
        P = common / ((ka_adj - alpha) * (ka_adj - beta))
        A_amp = common / ((alpha - ka_adj) * (alpha - beta))
        B_amp = common / ((beta - ka_adj) * (beta - alpha))
        result[valid] = (
            P * np.exp(-ka_adj * tau_v)
            + A_amp * np.exp(-alpha * tau_v)
            + B_amp * np.exp(-beta * tau_v)
        )
    else:
        P = common / ((ka - alpha) * (ka - beta))
        A_amp = common / ((alpha - ka) * (alpha - beta))
        B_amp = common / ((beta - ka) * (beta - alpha))
        result[valid] = (
            P * np.exp(-ka * tau_v) + A_amp * np.exp(-alpha * tau_v) + B_amp * np.exp(-beta * tau_v)
        )

    return result


# ---------------------------------------------------------------------------
# 3-compartment IV bolus  (WinNonlin #13)
# ---------------------------------------------------------------------------


def _cmt3_iv_bolus(
    t: NDArray[np.float64],
    params: dict[str, float],
    dose: float,
) -> NDArray[np.float64]:
    """C(t) = A*exp(-α*t) + B*exp(-β*t) + G*exp(-γ*t).

    Eigenvalues (α, β, γ) are the negatives of the eigenvalues of the
    3×3 rate-constant matrix K:

        K = [-(k10+k12+k13),  k21,        k31      ]
            [ k12,           -k21,         0        ]
            [ k13,            0,          -k31      ]

    Amplitudes are computed from the eigenvectors via residue decomposition.

    The eigenvalues of K are real and negative for physiologically valid
    parameters, so α, β, γ > 0.

    Refs: docs/03-algorithms/08-compartmental-models.md §2.7, WinNonlin model #13
    """
    V1 = params["V1"]
    k10 = params["k10"]
    k12 = params["k12"]
    k21 = params["k21"]
    k13 = params["k13"]
    k31 = params["k31"]

    K = np.array(
        [
            [-(k10 + k12 + k13), k21, k31],
            [k12, -k21, 0.0],
            [k13, 0.0, -k31],
        ],
        dtype=np.float64,
    )

    # Eigendecomposition: K * v = lambda * v  →  lambda_i are negative reals
    raw_eigvals, eigvecs = scipy.linalg.eig(K)

    # Take real parts (imaginary parts should be numerically zero for valid params)
    eigvals_real: NDArray[np.float64] = np.real(raw_eigvals)
    eigvecs_real: NDArray[np.float64] = np.real(eigvecs)

    # Rate constants are negatives of eigenvalues; sort descending so
    # alpha >= beta >= gamma (fastest to slowest)
    order = np.argsort(-eigvals_real)  # descending eigenvalue → ascending rate
    eigvals_sorted = eigvals_real[order]
    eigvecs_sorted = eigvecs_real[:, order]

    # Macro rate constants (positive)
    rates = -eigvals_sorted  # alpha, beta, gamma  (all > 0 for valid params)

    # Initial condition: at t=0 all dose in compartment 1 → C1(0) = D/V1
    # Concentrations from eigenvector decomposition:
    #   C(t) = sum_i  c_i * v1_i * exp(lambda_i * t)
    # where v1_i is the first element of the i-th eigenvector and c_i are
    # coefficients found by solving  V * c = C(0).
    # C(0) = [D/V1, 0, 0] in state space; we only need compartment 1 output.

    # Solve eigvecs_sorted @ c = [D/V1, 0, 0]
    rhs = np.array([dose / V1, 0.0, 0.0], dtype=np.float64)
    try:
        coeffs = np.linalg.solve(eigvecs_sorted, rhs)
    except np.linalg.LinAlgError:
        # Fallback: use least squares if matrix is singular
        coeffs, _, _, _ = np.linalg.lstsq(eigvecs_sorted, rhs, rcond=None)

    # Amplitudes in the concentration equation are coeffs * (first row of eigvecs)
    # since C1(t) = sum_i coeffs_i * eigvecs_sorted[0, i] * exp(lambda_i * t)
    amplitudes = coeffs * eigvecs_sorted[0, :]

    result = np.zeros_like(t)
    for amp, rate in zip(amplitudes, rates):
        result += float(amp) * np.exp(-float(rate) * t)

    return result
