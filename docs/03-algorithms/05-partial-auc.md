# 03.05 — Partial AUC

> 임의의 두 시점 `[t1, t2]` 사이의 AUC. BE/regulatory 분석에서 자주 요구됨 (예: AUC_0-72, AUC_τ).

## 1. 정의

```
AUC(t1, t2) = ∫_{t1}^{t2} C(t) dt
```

- 둘 다 양수 실수
- `t1 < t2`
- 시점이 관측치와 정확히 일치하지 않으면 **보간(interpolation)** 필요

---

## 2. 경계 보간

### 2.1 t1 또는 t2가 관측 시점이 아닌 경우

상수 옵션:
| 옵션 | 동작 |
|---|---|
| `linear` | 두 인접 점 사이를 선형 보간 |
| `log` | 두 인접 점 사이를 log-선형 보간 (양수 감소 시) |
| `auto` | linear-up/log-down 규칙 적용 (기본) |

### 2.2 t2가 Tlast 초과인 경우
```
AUC(t1, t2) = AUC(t1, Tlast) + Clast/λz · [1 - exp(-λz·(t2 - Tlast))]
```
- λz 추정 불가 시 외삽 불가 → error 반환

### 2.3 t1 = 0 IV bolus 인 경우
```
AUC(0, t2) = AUC_0-t2 (정상 적분, C(0) = C0_estimated)
```

---

## 3. 알고리즘 의사코드

```python
def partial_auc(times, conc, t1, t2, method="auto", lambda_z=None, clast=None, tlast=None):
    assert t1 < t2

    # Step 1: 새로운 시간점 t1, t2 를 기존 격자에 삽입
    new_times = sorted(set(times) | {t1, t2})

    # Step 2: 보간으로 C(t1), C(t2) 계산
    c_new = []
    for t in new_times:
        if t in times:
            c_new.append(conc[times.index(t)])
        else:
            c_new.append(interpolate(times, conc, t, method))

    # Step 3: [t1, t2] 구간만 추출
    mask = (np.array(new_times) >= t1) & (np.array(new_times) <= t2)
    sub_t, sub_c = np.array(new_times)[mask], np.array(c_new)[mask]

    # Step 4: 표준 trapezoidal로 AUC 계산
    auc = auc_trapezoid(sub_t, sub_c, method)

    # Step 5: t2 > Tlast 이면 외삽 추가
    if tlast is not None and t2 > tlast and lambda_z is not None:
        auc += clast / lambda_z * (1 - math.exp(-lambda_z * (t2 - tlast)))

    return auc
```

---

## 4. 보간 함수

### Linear interpolation
```
C(t) = C_i + (C_{i+1} - C_i) · (t - t_i) / (t_{i+1} - t_i)
```

### Log-linear interpolation (양수 구간)
```
C(t) = exp( ln C_i + (ln C_{i+1} - ln C_i) · (t - t_i) / (t_{i+1} - t_i) )
```

`auto` 모드: 감소 + 양수 구간이면 log, 아니면 linear (linear-up/log-down 정신과 동일).

---

## 5. 일반적인 partial AUC

| 명칭 | 정의 | 사용처 |
|---|---|---|
| AUC_0-2 | (0, 2 h) | early exposure (BE) |
| AUC_0-12 | (0, 12 h) | |
| AUC_0-24 | (0, 24 h) | once-daily 약물 |
| AUC_0-72 | (0, 72 h) | long half-life 약물 BE |
| AUC_τ | (0, τ) | steady-state |

---

## 6. 출력

```json
"partial_aucs": [
  {
    "name": "AUC_0_24",
    "t_start": 0,
    "t_end": 24,
    "value": 1234.5,
    "unit": "ng·h/mL",
    "interpolation": "linear_up_log_down",
    "extrapolated": false
  },
  {
    "name": "AUC_0_72",
    "t_start": 0,
    "t_end": 72,
    "value": 2345.6,
    "unit": "ng·h/mL",
    "interpolation": "linear_up_log_down",
    "extrapolated": true,
    "tlast": 48,
    "extrap_pct": 8.3
  }
]
```

---

## 7. 버전 차이

| 버전 | 기본 보간 | t1=0 IV C0 처리 |
|---|---|---|
| WinNonlin 5.3 | linear | log back-extrapolation (WNL 5.3 p.196) |
| WinNonlin 6.4 | linear | log back-extrapolation (WNL 6.4 UG §7.3) |
| WinNonlin 8.3 | linear | log back-extrapolation (WNL 8.3 UG §8.2) |

All three versions use `linear` (Linear Trapezoidal Linear Interpolation) as the default partial AUC
interpolation method, consistent with the NCA AUC default. The `linear-up/log-down` option is available
but not the default in any WinNonlin version (WNL 6.4 UG §7.2.3; WNL 8.3 UG §8.2.1).
