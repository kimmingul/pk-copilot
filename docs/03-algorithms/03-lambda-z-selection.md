# 03.03 — Lambda_z (말단 제거상수) 선택

> WinNonlin의 **Best Fit** 알고리즘을 정확히 재현하는 것이 본 플러그인의 핵심 차별점입니다.

## 1. 정의

말단 양수 농도 데이터에 대해 자연로그 변환 후 OLS 회귀:
```
ln C(t) = intercept - λz · t
```
- `λz > 0` 강제
- 회귀에는 **양수**, **non-BLOQ**, **post-Tmax** 시점만 사용

t½ = ln(2) / λz

---

## 2. 선택 방법 (Method Selection)

| 옵션 코드 | 한국어 | 출처 |
|---|---|---|
| `best_fit` | **Best Fit** (WinNonlin 기본) | WinNonlin 6.4+ |
| `adj_r2` | Adjusted R² 최대화 | 별도 옵션 |
| `manual` | 사용자 직접 시간 범위 지정 | |
| `time_range` | 특정 시간 범위 (`start, end`) | |
| `n_points` | 마지막 N개 점 사용 | |

---

## 3. Best Fit 알고리즘 (WinNonlin 정의)

### 입력
- 시간 / 농도 (post-Tmax, 양수, non-BLOQ)
- 최소 점 개수 `min_points = 3` (기본)

### 절차

```text
candidates = []
# 마지막 점부터 시작해 한 점씩 추가하며 OLS 적합
for n in range(min_points, len(post_tmax_points) + 1):
    subset = last n points (가장 최근 시점부터 역순)
    fit = OLS(ln C ~ t)
    if fit.slope >= 0:
        continue                    # λz > 0 위반
    adj_r2 = 1 - (1 - r2) * (n - 1) / (n - 2)
    candidates.append({
        "n_points": n,
        "lambda_z": -fit.slope,
        "intercept": fit.intercept,
        "r2": fit.r2,
        "adj_r2": adj_r2,
        "t_start": subset.t[0],
        "t_end": subset.t[-1],
    })

# Best Fit 선택 규칙 (WinNonlin):
# 1) adjusted_r2 의 최댓값을 찾고
# 2) 그 최댓값과의 차이가 0.0001 이내인 후보 중 점 개수가 가장 많은 것
best = argmax(adj_r2, with tolerance 1e-4 → prefer largest n_points)
```

### Span Guard (옵션, 권장)
선택된 구간이 너무 짧으면 t½ 신뢰성 의심:
```
span_ratio = (t_end - t_start) / t_half_estimated
if span_ratio < 1.5:
    flag = "span_ratio_low"   # 경고만, 계산은 진행
```

---

## 4. Adjusted R² 변형

위 절차와 동일하나 tolerance 없이 단순 최대 adj_R² 선택:
```
best = argmax(adj_r2)
```

---

## 5. Manual 선택

사용자가 시간 범위 또는 점 인덱스를 직접 지정:
```python
manual = {"t_start": 8.0, "t_end": 24.0}  # 또는
manual = {"indices": [5, 6, 7, 8]}        # 또는
manual = {"n_last": 4}
```

선택된 시점들로 단일 OLS → λz 계산. R² / adj_R² 보고.

---

## 6. 출력 스키마

```python
@dataclass
class LambdaZResult:
    lambda_z: float            # 양의 실수
    intercept: float           # log scale intercept
    half_life: float           # ln(2) / lambda_z
    r_squared: float
    adjusted_r_squared: float
    n_points: int
    t_start: float
    t_end: float
    span_ratio: float | None   # (t_end - t_start) / t_half
    method: Literal["best_fit", "adj_r2", "manual", "time_range", "n_points"]
    excluded_points: list[dict]  # 어느 점이 왜 제외되었는지
    warnings: list[str]          # span_ratio_low, few_points 등
```

---

## 7. 결과 플래그 (WinNonlin 호환)

| 플래그 | 의미 |
|---|---|
| `Span ratio < 1.5` | 권장 미만 |
| `Adj R² < 0.85` | 적합도 낮음 |
| `n_points = 3` | 최소 점 |
| `Clast extrapolated > 20% AUC` | 외삽 비율 과다 |
| `Lambda_z not estimable` | 양수 슬로프 / 포인트 부족 |

---

## 8. 버전 차이

| 버전 | Best Fit | Adj R² tolerance | 기본 method |
|---|---|---|---|
| WinNonlin 5.3 | 알고리즘 동일 | 0.0001 | `best_fit` (WNL 5.3 p.196 confirms Best Fit as default) |
| WinNonlin 6.4 | 동일 | 0.0001 | `best_fit` |
| WinNonlin 8.3 | 동일 | 0.0001 | `best_fit` |
| **pk-copilot 기본** | `best_fit` | 0.0001 | `winnonlin_version` 따름 |

> Adj R² tolerance of 0.0001 confirmed for all three versions (WNL 5.3 p.196; WNL 6.4 UG §7.4; WNL 8.3 UG §8.3). Lambda_z regression uses **post-Tmax** points only — points at or before Tmax are excluded even if their concentrations are declining (WNL 6.4 UG §7.4.1).

---

## 9. UX 권장 (Gemini)

블랙박스 금지. CLI 출력 예:
```
[Lambda_z Selection — Subject S001]
  Method:       Best Fit (WinNonlin 6.4)
  Window:       8.0 → 24.0 h  (4 points)
  Lambda_z:     0.0826 1/h
  t½:           8.39 h
  Adj R²:       0.9943
  Span ratio:   1.91 (OK)

  Selected points:
    ✔ t=8.0   C=42.1
    ✔ t=12.0  C=30.3
    ✔ t=18.0  C=18.7
    ✔ t=24.0  C=11.4

  → Plot saved: runs/.../lambda_z_S001.png
  Approve? [Y/n/edit]
```
