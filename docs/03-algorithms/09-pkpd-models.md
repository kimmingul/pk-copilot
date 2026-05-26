# 03.09 — PK/PD Link Models

> 약동학(PK)과 약력학(PD) 연결 모델.

## 1. 모델 카탈로그

### 1.1 Direct Effect (즉시 효과)

| 모델 | 수식 |
|---|---|
| Linear | `E = E0 + S · C` |
| Log-linear | `E = E0 + S · ln(C)` |
| Emax | `E = E0 + (Emax · C) / (EC50 + C)` |
| Sigmoid Emax (Hill) | `E = E0 + (Emax · C^γ) / (EC50^γ + C^γ)` |
| Inhibitory Emax | `E = E0 - (Imax · C) / (IC50 + C)` |

### 1.2 Effect Compartment (Hull-Sheiner)
```
dCe/dt = Ke0 · (Cp - Ce)
E(t) = f(Ce(t))                # 위 direct 모델 중 하나
```
- 효과 부위 농도 `Ce` 가 plasma `Cp` 와 시간차
- 파라미터명: `Ke0` (capital K, capital zero; WNL 6.4 p.385 convention)

### 1.3 Indirect Response Models (Jusko/Dayneka I-IV)

기본 turnover:
```
dR/dt = kin - kout · R
R_ss = kin / kout
```

| 모델 | 메커니즘 | 수식 |
|---|---|---|
| IRM-I | Inhibition of production | `dR/dt = kin · (1 - Imax·C/(IC50+C)) - kout · R` |
| IRM-II | Inhibition of loss | `dR/dt = kin - kout · (1 - Imax·C/(IC50+C)) · R` |
| IRM-III | Stimulation of production | `dR/dt = kin · (1 + Emax·C/(EC50+C)) - kout · R` |
| IRM-IV | Stimulation of loss | `dR/dt = kin - kout · (1 + Emax·C/(EC50+C)) · R` |

### 1.4 Turnover with Effect Compartment
조합:
```
dCe/dt = ke0 · (Cp - Ce)
dR/dt  = kin · f(Ce) - kout · g(Ce) · R
```

### 1.5 Tolerance / Sensitization (v1 이후)
- Precursor pool
- Receptor downregulation

---

## 2. 적합 (Fitting) 전략

### Sequential PK-PD
1. PK 모델 적합 → `Cp(t)` 추정
2. 추정된 `Cp(t)` 를 입력으로 PD 모델 적합
- 빠르고 안정적, PK 모델 신뢰 시 권장

### Simultaneous PK-PD
모든 파라미터를 한 번에 적합
- 더 통계적으로 옳음
- 초기값 민감, 수렴 어려움

코드:
```python
def fit_pkpd(observations, pk_model, pd_model, mode="sequential"):
    if mode == "sequential":
        pk_fit = fit_pk_model(observations.pk, pk_model)
        ce_or_cp = simulate(pk_model, pk_fit.params, t=observations.pd.time)
        pd_fit = fit_pd_model(observations.pd, pd_model, driver=ce_or_cp)
        return CombinedFit(pk=pk_fit, pd=pd_fit)
    elif mode == "simultaneous":
        return joint_minimize(...)
```

---

## 3. Hysteresis Plot

E vs C 그릴 때 시간 진행 방향 화살표:
- **Clockwise**: tolerance (positive hysteresis)
- **Counter-clockwise**: delay → effect compartment 필요 (negative hysteresis)

`/diagnose` 명령에서 자동 생성.

---

## 4. 파라미터 의미

| 파라미터 | 단위 | 해석 |
|---|---|---|
| `E0` | [Effect] | baseline 효과 |
| `Emax` | [Effect] | 최대 효과 |
| `EC50` | [Conc] | 50% 효과 농도 |
| `γ` (Hill) | — | sigmoid 기울기 (1=단순 Emax) |
| `Ke0` | 1/[Time] | 효과실 평형 상수 (WNL 6.4 p.385 naming) |
| `kin` | [R]/[Time] | 0차 생성 속도 |
| `kout` | 1/[Time] | 1차 소실 속도 |

---

## 5. 출력 스키마

```json
{
  "model": "indirect_response_I",
  "estimation_mode": "sequential",
  "pk_driver": "cmt2_iv_bolus",
  "parameters": {
    "kin":  {"estimate": 10.5, "se": 1.2},
    "kout": {"estimate":  0.4, "se": 0.05},
    "Imax": {"estimate":  0.85, "se": 0.04},
    "IC50": {"estimate":  3.2, "se": 0.6}
  },
  "secondary": {
    "R_baseline": 26.25,
    "max_inhibition_pct": 85.0
  },
  "hysteresis": "counter_clockwise",
  "goodness_of_fit": {...}
}
```

---

## 6. WinNonlin PD 모델 번호 매핑

WinNonlin PD 모델 번호 (WNL 6.4 UG §11; WNL 8.3 UG §12):

| WNL Model # | 모델 | pk-copilot 코드 |
|---|---|---|
| 101 | Linear E = E0 + S·C | `linear` |
| 102 | Log-linear E = E0 + S·ln(C) | `log_linear` |
| 103 | Emax (WNL 5.3: Sigmoid Emax) | `emax` |
| 104 | Sigmoid Emax (Hill) | `sigmoid_emax` |
| 105 | Inhibitory Emax | `inhibitory_emax` |
| 106 | Effect Compartment (Ke0) | `effect_compartment` |
| 107 | IDR-I (Inhibit production) | `idr_i` |
| 108 | IDR-II (Inhibit loss) | `idr_ii` |
| 109 | IDR-III (Stimulate production) | `idr_iii` |
| 110 | IDR-IV (Stimulate loss) | `idr_iv` |

**IDR III/IV parameter naming**: WNL uses `Emax`/`EC50` for stimulation models (same as inhibition models use
`Imax`/`IC50`). The older notation `Smax`/`SC50` is not used by WinNonlin (WNL 6.4 UG §11.3).

**Version note**: WNL 5.3 Model 103 is Sigmoid Emax; WNL 6.4+ Model 103 is plain Emax and Model 104 is
Sigmoid Emax. Adjust model number when comparing 5.3 vs 6.4+ output (WNL 6.4 UG §11.1).

---

## 7. 검증

| 테스트 | 데이터 | 모델 |
|---|---|---|
| `test_emax_warfarin` | warfarin INR 표준 데이터 | Sigmoid Emax |
| `test_effect_compartment_propofol` | propofol BIS | Hull-Sheiner |
| `test_idr_corticosteroid` | corticosteroid 표준 | IRM-I |
