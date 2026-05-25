# 03.08 — Compartmental Models

> 1/2/3-구획 모델 (IV bolus / IV infusion / first-order absorption / Michaelis-Menten).

## 1. 모델 카탈로그 (WinNonlin "PK Model" 번호 매핑)

| WinNonlin Model # | 설명 | pk-copilot 코드 (canonical) |
|---|---|---|
| 1 | 1-cmt IV bolus | `cmt1_iv_bolus` |
| 2 | 1-cmt IV bolus + MM elim | `cmt1_iv_mm` |
| 3 | 1-cmt IV infusion | `cmt1_iv_infusion` |
| 4 | 1-cmt IV infusion + MM | *(not implemented)* |
| 5 | 1-cmt PO + lag | `cmt1_po` |
| 6 | 1-cmt PO + MM | `cmt1_po_mm` |
| 7 | 2-cmt IV bolus | `cmt2_iv_bolus` |
| 8 | 2-cmt IV bolus + MM | `cmt2_iv_mm` |
| 9 | 2-cmt IV infusion | `cmt2_iv_infusion` |
| 10 | 2-cmt IV infusion + MM | *(not implemented)* |
| 11 | 2-cmt PO | `cmt2_po` |
| 12 | 2-cmt PO + MM | *(not implemented)* |
| 13 | 3-cmt IV bolus | `cmt3_iv_bolus` |
| 14 | 3-cmt IV infusion | *(not implemented)* |
| 15 | 3-cmt PO | *(not implemented)* |

**Canonical name convention**: Use the short form (e.g. `cmt1_iv_mm`, not `cmt1_iv_bolus_mm`).
MM models are ODE-only (no closed-form solution); Vmax in concentration/time units, Km in concentration units.

📋 TODO: WinNonlin 버전별 model 번호 매핑 (5.3/6.4/8.3) 정확히 검증

---

## 2. 핵심 수식

### 2.1 1-cmt IV bolus
```
C(t) = (D / V) · exp(-k · t)
```
- 파라미터: `V` (volume), `k` (1차 제거상수)
- 유도: `CL = k · V`, `t½ = ln(2)/k`

### 2.2 1-cmt IV infusion
구간 [0, T_inf]:
```
C(t) = (R_0 / (V·k)) · (1 - exp(-k·t))
R_0 = D / T_inf
```
구간 t > T_inf:
```
C(t) = C(T_inf) · exp(-k · (t - T_inf))
```

### 2.3 1-cmt PO with first-order absorption
```
C(t) = (F·D·ka) / (V·(ka - k)) · [exp(-k·t) - exp(-ka·t)]
```
- 파라미터: `ka`, `k`, `V/F`
- Tlag 옵션: `t → t - Tlag`, t < Tlag 시 C=0
- Flip-flop 케이스 (`ka < k`) 처리: 분모 안전

### 2.4 2-cmt IV bolus
```
C(t) = A · exp(-α·t) + B · exp(-β·t)
```
- Macro: `A`, `B`, `α`, `β`
- Micro 변환: `k10`, `k12`, `k21`, `V1`
```
α + β = k10 + k12 + k21
α · β = k10 · k21
A + B = D / V1
A·β + B·α = D·k21 / V1
```

### 2.5 2-cmt IV infusion / PO
유사한 macro/micro 변환, infusion/absorption 항 포함.

### 2.6 Michaelis-Menten
```
-dC/dt = Vmax · C / (Km + C)
```
- ODE 전용 (analytical 없음)
- 파라미터: `Vmax`, `Km`, `V`

### 2.7 3-cmt
유사한 macro form:
```
C(t) = A·exp(-α·t) + B·exp(-β·t) + G·exp(-γ·t)
```

---

## 3. Solver 선택

| 모델 | 1차 선택 | Fallback |
|---|---|---|
| 1/2/3-cmt 선형 | **Closed-form** | ODE (검증) |
| Michaelis-Menten | ODE (`LSODA`) | — |
| Mixed input (IV+PO) | ODE | 별도 closed-form per route |
| Reversible binding | ODE | — |

ODE 옵션:
```python
from scipy.integrate import solve_ivp
sol = solve_ivp(
    fun=model_rhs,
    t_span=(0, t_end),
    y0=initial_state,
    t_eval=obs_times,
    method="LSODA",    # 또는 BDF, RK45
    rtol=1e-9,
    atol=1e-12,
    dense_output=False,
    events=dosing_events,
)
```

---

## 4. Parameter Estimation

### 4.1 NLS (Non-Linear Least Squares)
```python
from scipy.optimize import least_squares
result = least_squares(
    residual_fn,
    x0=initial_params,
    bounds=(lower, upper),
    method="trf",       # trust-region reflective
    loss="linear",      # 또는 huber for robustness
    jac="3-point",
    xtol=1e-10,
)
```

### 4.2 MLE (Maximum Likelihood) via lmfit
```python
import lmfit
params = lmfit.Parameters()
params.add("V",  value=20, min=0.1, max=1000)
params.add("k",  value=0.1, min=1e-4, max=10)
res = lmfit.minimize(residual, params, args=(times, conc), method="leastsq")
```

### 4.3 Bayesian (v1 이후 optional)
- `pymc` 또는 `numpyro` 위임

### 4.4 Weighting Schemes

| 코드 | 가중치 | 적용 |
|---|---|---|
| `uniform` (=1) | `w_i = 1` | 동일 가중 |
| `1/y` | `w_i = 1 / |C_i|` | 작은 농도 강조 |
| `1/y²` | `w_i = 1 / C_i²` | 더 강조 (WinNonlin 기본) |
| `1/pred` | `w_i = 1 / |Ĉ_i|` | iterative |
| `1/pred²` | `w_i = 1 / Ĉ_i²` | iterative |

### 4.5 Residual Error Model

```python
# additive:        ε ~ N(0, σ_add²)
# proportional:    ε ~ N(0, (σ_prop · C)²)
# combined:        ε ~ N(0, σ_add² + (σ_prop · C)²)
```

---

## 5. 초기 추정치 (NCA → Comp)

NCA 결과를 활용:
```
k_init  ≈ λz (from NCA)
V_init  ≈ Dose / C0_extrap  (IV) 또는  Dose / (AUC * k)
CL_init = k_init * V_init
ka_init = 1.5 · k_init  (PO; ka > k 가정)
```

---

## 6. 진단 (Diagnostics)

| 지표 | 정의 |
|---|---|
| Observed vs Predicted | 산점도, identity line |
| Residuals vs Time | random scatter 기대 |
| Residuals vs Predicted | trend 없어야 |
| Weighted Residuals | NONMEM-style |
| QQ plot | 정규성 검사 |
| AIC | `AIC = 2k - 2·ln(L)` |
| BIC | `BIC = k·ln(n) - 2·ln(L)` |
| Condition number | parameter correlation |
| Profile CI | likelihood profile |

> **AIC 정의 주의**: WinNonlin은 `AIC = N·ln(SS/N) + 2k` 형태를 쓰는 경우가 있음. 정확한 정의 매뉴얼별로 확인 필요. **두 가지 모두 지원하고 옵션으로 명시**.

---

## 7. 출력 스키마

```json
{
  "model": "cmt2_iv_bolus",
  "winnonlin_model_id": 7,
  "winnonlin_version": "6.4",
  "estimation": {
    "method": "NLS",
    "weighting": "1/y2",
    "residual_error": "proportional",
    "solver": "closed_form"
  },
  "parameters": {
    "A":  {"estimate": 12.34, "se": 0.45, "rsd_pct": 3.6, "ci_low": 11.4, "ci_high": 13.2},
    "B":  {"estimate":  4.56, "se": 0.23, "rsd_pct": 5.0, ...},
    "alpha": {...},
    "beta":  {...}
  },
  "secondary_parameters": {
    "k10": 0.12, "k12": 0.08, "k21": 0.05,
    "V1": 8.3, "V2": 14.2, "CL": 1.05
  },
  "goodness_of_fit": {
    "rss": 12.4, "aic": 145.2, "bic": 152.6,
    "n_obs": 80, "n_params": 4,
    "condition_number": 23.4
  },
  "diagnostics_plots": ["obs_vs_pred.png", "resid_vs_time.png", "qq.png"]
}
```

---

## 8. 검증

| 테스트 | 기대 |
|---|---|
| `test_1cmt_iv_closed_form_eq_ode` | closed-form vs ODE ≤ 1e-9 |
| `test_winnonlin_model_7_2cmt` | WinNonlin 6.4 §10 예제 데이터 재현 |
| `test_bateman_po` | 1-cmt PO 해석해와 일치 |
| `test_aic_definition_compat` | WinNonlin/Pumas/NONMEM AIC 정의별 호환 |
