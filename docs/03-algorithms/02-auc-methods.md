# 03.02 — AUC / AUMC 적분 방법

## 지원하는 방법

| 코드 | 한국어 | 적용 |
|---|---|---|
| `linear` | 선형 사다리꼴 | 모든 구간 직선 보간 |
| `log` | 로그 사다리꼴 | 모든 양수 감소 구간 로그-선형 보간 |
| `linear_up_log_down` | 선형 상승 / 로그 하강 (**기본**) | WinNonlin 권장 |
| `linear_log` (alias) | 동일 | |

---

## 1. Linear Trapezoidal
구간 [t_i, t_{i+1}]:
```
AUC_i = 0.5 · (C_i + C_{i+1}) · (t_{i+1} - t_i)
AUMC_i = 0.5 · (t_i · C_i + t_{i+1} · C_{i+1}) · (t_{i+1} - t_i)
```

**장점**: 단순, 0/음수 농도 안전
**단점**: 감소 구간을 과대평가 (지수 감소 곡선에서)

---

## 2. Log Trapezoidal
양수 감소 구간 (`C_i > C_{i+1} > 0`):
```
AUC_i = (C_i - C_{i+1}) · (t_{i+1} - t_i) / ln(C_i / C_{i+1})
AUMC_i = (t_{i+1} - t_i) · (t_i · C_i - t_{i+1} · C_{i+1}) / ln(C_i / C_{i+1})
       - (t_{i+1} - t_i)² · (C_i - C_{i+1}) / (ln(C_i / C_{i+1}))²
```

**예외**: `C_i = C_{i+1}` 또는 `C_i ≤ 0` 또는 `C_{i+1} ≤ 0` → **linear로 폴백**
- 폴백 발생 시 audit log에 기록

---

## 3. Linear-Up / Log-Down (기본값)
```
if C_{i+1} >= C_i  OR  C_i ≤ 0  OR  C_{i+1} ≤ 0:
    use linear trapezoid
else:  # 감소 구간, 양수
    use log trapezoid
```

- WinNonlin 6.4+ 기본
- **WinNonlin 5.3** 도 동일 알고리즘 지원하나 GUI 기본값이 `linear`인 경우 있음 — 버전 매트릭스 참조

---

## 4. 의사코드 (canonical)

```python
def auc_trapezoid(times, conc, method="linear_up_log_down"):
    """
    times: sorted np.array
    conc:  np.array (None/NaN for BLOQ — must be pre-processed)
    """
    assert np.all(np.diff(times) > 0), "times must be strictly increasing"
    assert len(times) == len(conc) >= 2

    auc = 0.0
    aumc = 0.0
    flags = []  # 폴백 발생 기록

    for i in range(len(times) - 1):
        t1, t2 = times[i], times[i+1]
        c1, c2 = conc[i], conc[i+1]
        dt = t2 - t1

        use_log = (
            method in ("log", "linear_up_log_down")
            and c1 is not None and c2 is not None
            and c1 > 0 and c2 > 0
            and c2 < c1
        )
        # linear_up_log_down: 상승/평탄/0 포함 구간은 linear
        if method == "linear_up_log_down" and (c2 is None or c1 is None or c2 >= c1 or c1 <= 0 or c2 <= 0):
            use_log = False
        if method == "linear":
            use_log = False

        if use_log:
            ln_ratio = math.log(c1 / c2)
            d_auc = (c1 - c2) * dt / ln_ratio
            d_aumc = dt * (t1*c1 - t2*c2) / ln_ratio \
                   - dt**2 * (c1 - c2) / ln_ratio**2
        else:
            d_auc = 0.5 * (c1 + c2) * dt
            d_aumc = 0.5 * (t1*c1 + t2*c2) * dt
            if method == "log":
                flags.append(("log_to_linear_fallback", i))

        auc += d_auc
        aumc += d_aumc

    return AUCResult(auc=auc, aumc=aumc, method=method, fallbacks=flags)
```

---

## 5. AUC_0-inf 외삽

```
AUCINF_obs  = AUC_0-Tlast + Clast      / λz
AUCINF_pred = AUC_0-Tlast + Clast_pred / λz
```

- `Clast`: 마지막 quantifiable observed
- `Clast_pred`: 말단 회귀로부터 `exp(intercept - λz · Tlast)`
- 외삽 비율:
```
%AUC_extrap_obs = (AUCINF_obs - AUC_0-Tlast) / AUCINF_obs × 100
```

---

## 6. AUMC_0-inf 외삽

```
AUMC_inf = AUMC_0-Tlast + Tlast · Clast / λz + Clast / λz²
```

---

## 7. 경계 케이스

| 케이스 | 처리 |
|---|---|
| 첫 시점이 t > 0 (post-dose first observation) | 0 → t1 구간은 단순 linear (dose 시점 가정 C=0 IV bolus는 예외) |
| IV bolus, t=0 데이터 없음 | C0 back-extrapolation → 0→t1 linear |
| 중간 BLOQ → quantifiable로 회복 | 해당 BLOQ 시점 `missing` 처리 (기본) → 좌·우 양수 시점으로 보간 X (skip) |
| Tlast 이후 BLOQ | 외삽에만 영향 (λz 회귀에서는 제외) |
| 모든 농도 BLOQ | 분석 중단, error 반환 |

> BLOQ 정책 세부는 [04-bloq-handling.md](04-bloq-handling.md)

---

## 8. 버전별 기본값

| 버전 | 기본 AUC 방법 | 비고 |
|---|---|---|
| WinNonlin 5.3 | `linear`* | GUI 기본 (옵션 변경 가능) |
| WinNonlin 6.4 | `linear_up_log_down` | |
| WinNonlin 8.3 | `linear_up_log_down` | |
| pk-copilot 기본 | `linear_up_log_down` | `winnonlin_version` 옵션이 우선 |

*📋 TODO: 5.3 매뉴얼에서 GUI 기본값 정확히 확인

---

## 9. 검증 (Golden)

| 테스트 | 입력 | 기대값 |
|---|---|---|
| `test_auc_linear_known` | 직선 0→10@1h | AUC = 5.0 |
| `test_auc_log_exponential` | C(t) = 100·exp(-0.5t), t=0..10 | analytical = 199.66 |
| `test_pknca_theophylline` | PKNCA fixture | PKNCA 결과 ±1e-9 |
| `test_winnonlin_6_4_example_7_2` | 매뉴얼 §7.2 예제 | 매뉴얼 출력값 |
