# 03.07 — Bioequivalence (생물학적동등성)

> Average Bioequivalence (ABE) 분석. FDA / EMA / PMDA 가이드라인 기반.

## 1. 디자인 지원

| 디자인 | 코드 | 설명 |
|---|---|---|
| 2×2 crossover | `crossover_2x2` | 가장 흔함 (RT / TR) |
| Replicate (2x4, 2x3) | `replicate` | high-variability drugs |
| Parallel | `parallel` | 긴 t½ 약물 |
| Higher-order (4-period) | `higher_order` | |

v0.2는 `crossover_2x2` 와 `parallel` 우선.

---

## 2. 핵심 엔드포인트

| 엔드포인트 | 변환 |
|---|---|
| AUC_0-t | log |
| AUC_0-inf | log |
| Cmax | log |

> 모든 BE 통계는 **log-transformed** 데이터에 대해 수행.

---

## 3. 절차 (2×2 crossover)

### 3.1 모델
Mixed-effects model (FDA 권장):
```
ln Y_ijk = μ + S_i(k) + P_j + F_k + ε_ijk
```
- `i` = subject within sequence
- `j` = period (1, 2)
- `k` = sequence/formulation (T or R)
- `S_i(k)` = random subject effect within sequence
- `P_j` = period fixed effect
- `F_k` = formulation fixed effect
- `ε_ijk` = within-subject error

R/SAS 등가:
```
PROC MIXED data=bedata;
  CLASS subject sequence period formulation;
  MODEL ln_y = sequence period formulation;
  RANDOM subject(sequence);
RUN;
```

Python 구현 (statsmodels `MixedLM`):
```python
mod = MixedLM.from_formula(
    "ln_y ~ sequence + period + formulation",
    groups="subject(sequence)",
    data=df,
)
res = mod.fit(reml=True)
```

### 3.2 GMR 및 90% CI
- `GMR = exp( μ_T - μ_R )` — geometric mean ratio
- 90% CI:
```
CI_low  = exp( (μ_T - μ_R) - t_{0.05, df} · SE )
CI_high = exp( (μ_T - μ_R) + t_{0.05, df} · SE )
```
- `df`: Satterthwaite 또는 Kenward-Roger (구현 옵션)

### 3.3 ABE 결정
```
80.00% ≤ CI_low,  CI_high ≤ 125.00%   →  BE 입증
```

### 3.4 TOST (Two One-Sided Tests)
귀무가설:
```
H01: μ_T - μ_R ≤ ln(0.80)
H02: μ_T - μ_R ≥ ln(1.25)
```
- 각각 단측 α=0.05 검정
- 두 H0 모두 기각 시 BE 입증

---

## 4. Cmax — Highly Variable Drugs

EMA / FDA scaled ABE (`SABE`):
- within-subject CV > 30% 약물에 대해 reference-scaled approach
- v0.2는 일반 ABE 만, **v0.3+에서 SABE 옵션 추가**

---

## 5. Parallel 디자인

t-test on log-transformed parameters:
```
ln_y_T ~ N(μ_T, σ_T²)
ln_y_R ~ N(μ_R, σ_R²)
```
- Welch t-test (unequal variance)
- 90% CI: `exp(μ_T - μ_R ± t_{0.05, df_satterthwaite} · SE_diff)`

---

## 6. 출력 스키마

```json
{
  "design": "crossover_2x2",
  "endpoint": "AUC_0_t",
  "transformation": "log",
  "n_subjects": 24,
  "n_completers": 23,
  "model": "MixedLM(formula='ln_y ~ sequence + period + formulation', groups='subject(sequence)')",
  "test_label": "Test_Formulation",
  "reference_label": "Reference_Formulation",
  "ls_means": {
    "test": 7.230,
    "reference": 7.245,
    "difference": -0.015
  },
  "gmr_pct": 98.51,
  "ci_90_low_pct": 92.40,
  "ci_90_high_pct": 105.05,
  "be_window": [80.00, 125.00],
  "be_conclusion": "BE_demonstrated",
  "anova_table": {
    "sequence": {"F": 0.21, "p": 0.65},
    "period":   {"F": 1.34, "p": 0.26},
    "formulation": {"F": 0.45, "p": 0.51}
  },
  "within_subject_cv_pct": 12.4,
  "power_pct": 95.2
}
```

---

## 7. 추가 산출

- **Within-subject CV%**: `100 × sqrt(exp(σ²_w) - 1)`
- **Power**: post-hoc, 80-125% 윈도우 기준
- **Sample size recalculation**: 부족 시 권고

---

## 8. WinNonlin 호환 (Phoenix BE module)

| 출력 | WinNonlin | pk-copilot |
|---|---|---|
| LSMeans | Yes | Yes |
| 90% CI | Yes | Yes |
| Geometric Mean Ratio | Yes | Yes |
| Power | Yes | Yes |
| ANOVA table | Yes | Yes |
| Within-Subject CV | Yes | Yes |
| Sequence effect | Yes | Yes |
| Period effect | Yes | Yes |

📋 TODO: WinNonlin Phoenix BE 모듈 매뉴얼의 df 계산법 (Satterthwaite vs Kenward-Roger 기본값) 검증.

---

## 9. 검증

| 테스트 | 데이터 | 기대 |
|---|---|---|
| `test_fda_be_example` | FDA BE guidance Appendix 데이터 | GMR/CI ±0.01% |
| `test_pknca_crossover` | PKNCA `pk.tss.data.prep` 예제 | 일치 |
| `test_sas_proc_mixed` | SAS 출력 비교 fixture | LSMeans ±1e-6 |
