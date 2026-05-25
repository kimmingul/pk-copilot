# 03.06 — Steady-State Parameters

> 반복 투여(multiple dosing)에서 정상상태 도달 후 한 dosing interval 내 파라미터.

## 1. 전제 조건

- 정상상태(steady-state)에 도달 (보통 `≥ 5 × t½` 이후)
- Dosing interval τ가 정의됨
- 분석 구간이 정확히 한 τ 또는 정수배 (τ × n)

> 정상상태 도달 여부 검증은 `/diagnose` 명령으로 제공 (Ctrough 안정성 검사).

---

## 2. 파라미터 사전

### 2.1 Cmax_ss
```
Cmax_ss = max{ C(t) : t ∈ [t_dose, t_dose + τ] }
```

### 2.2 Tmax_ss
```
Tmax_ss = t where C(t) = Cmax_ss   (within dosing interval)
```

### 2.3 Cmin_ss / Ctrough_ss
```
Cmin_ss = min{ C(t) : t ∈ [t_dose, t_dose + τ] }
Ctrough_ss = C(t_dose + τ)        # 다음 투여 직전
```

### 2.4 Cavg_ss
```
Cavg_ss = AUC_τ / τ
```

### 2.5 AUC_τ
```
AUC_τ = ∫_{t_dose}^{t_dose + τ} C(t) dt
```
- 표준 trapezoidal (linear-up/log-down) 적용
- partial AUC 알고리즘 [05-partial-auc.md](05-partial-auc.md) 와 동일

### 2.6 Fluctuation
```
Fluctuation = (Cmax_ss - Cmin_ss) / Cavg_ss × 100   [%]
```

### 2.7 Swing
```
Swing = (Cmax_ss - Cmin_ss) / Cmin_ss × 100         [%]
```

### 2.8 Accumulation Ratio
첫 투여 후 vs 정상상태 AUC 비율:
```
Rac = AUC_τ,ss / AUC_τ,first
```
- 또는 Cmax 기준:
```
Rac_Cmax = Cmax_ss / Cmax_first
```

이론적 (1-cmt) accumulation:
```
Rac_theoretical = 1 / (1 - exp(-λz · τ))
```

---

## 3. Single → Steady-State 비교

| 파라미터 | Single Dose | Steady-State | 비고 |
|---|---|---|---|
| Cmax | Cmax | Cmax_ss | 보통 더 큼 |
| Tmax | Tmax | Tmax_ss | 변화 작음 |
| AUC_0-τ | AUC(0,τ) | AUC_τ,ss | Rac 만큼 증가 |
| CL/F | Dose/AUCINF | Dose/AUC_τ,ss | 동일 (정상상태 가정) |

---

## 4. 알고리즘 의사코드

```python
def steady_state_params(times, conc, dose, tau, t_dose=0.0, method="linear_up_log_down"):
    """
    times, conc:  dosing interval 내 데이터
    tau:          dosing interval (h)
    t_dose:       해당 dose 의 투여 시각 (보통 0)
    """
    # 1) AUC_tau
    auc_tau = partial_auc(times, conc, t_dose, t_dose + tau, method)

    # 2) Cmax_ss, Tmax_ss
    mask = (times >= t_dose) & (times <= t_dose + tau)
    sub_t, sub_c = times[mask], conc[mask]
    idx_max = np.argmax(sub_c)
    cmax_ss = sub_c[idx_max]
    tmax_ss = sub_t[idx_max]

    # 3) Cmin_ss, Ctrough_ss
    cmin_ss = sub_c.min()
    # Ctrough = C(t_dose + tau)
    ctrough_ss = interpolate(times, conc, t_dose + tau, method)

    # 4) Derived
    cavg_ss = auc_tau / tau
    fluctuation = (cmax_ss - cmin_ss) / cavg_ss * 100
    swing = (cmax_ss - cmin_ss) / cmin_ss * 100

    return SteadyStateResult(
        cmax_ss=cmax_ss, tmax_ss=tmax_ss,
        cmin_ss=cmin_ss, ctrough_ss=ctrough_ss,
        cavg_ss=cavg_ss, auc_tau=auc_tau,
        fluctuation_pct=fluctuation, swing_pct=swing,
        tau=tau,
    )
```

---

## 5. 출력 표

| Parameter | Value | Unit | Note |
|---|---|---|---|
| Cmax_ss | 12.4 | ng/mL | |
| Tmax_ss | 2.0 | h | |
| Cmin_ss | 3.1 | ng/mL | |
| Cavg_ss | 6.7 | ng/mL | AUC_tau / tau |
| AUC_tau | 80.4 | ng·h/mL | linear-up/log-down |
| Fluctuation | 138.8 | % | |
| Swing | 300.0 | % | |
| Rac (AUC) | 1.85 | — | vs first dose |

---

## 6. 버전 차이

📋 TODO: 매뉴얼별 Fluctuation/Swing 정의 차이 검증
- WinNonlin 5.3: Fluctuation 정의가 (Cmax-Cmin)/Cavg 인지 확인
- WinNonlin 6.4/8.3: 동일 정의 추정
