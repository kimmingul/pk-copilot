# 03.01 — NCA Parameters Dictionary

> Phoenix WinNonlin이 산출하는 모든 비구획분석(NCA) 파라미터의 정의·수식·단위·계산 규칙을 명세합니다.

## 명명 규약

- **단위 표시**: `[Conc]`, `[Time]`, `[Conc·Time]`, `[Vol]`, `[Vol/Time]` 등 추상 단위로 표기
- **변수 표시**: `C(t)` = 시간 t에서의 농도, `D` = 투여량, `F` = bioavailability
- **표기 일치**: WinNonlin 매뉴얼의 약어를 그대로 사용 (Cmax, AUClast, AUCINF_obs 등)

---

## 1. 관측 기반 파라미터 (Observed)

### 1.1 Cmax — Maximum Observed Concentration
```
Cmax = max{ C_i : i = 1..n, C_i ≠ BLOQ }
```
- **단위**: [Conc]
- **버전 차이**: 동일 (WNL 5.3 p.194; WNL 6.4 UG §7.3; WNL 8.3 UG §8.2)

### 1.2 Tmax — Time of Maximum Concentration
```
Tmax = t_i where C_i = Cmax
```
- 동일 Cmax가 여러 시점에 발생 시 → **첫 번째 시점**
- **버전 차이**: 동일 (WinNonlin 모든 버전 동일)

### 1.3 Tlag — Lag Time (Oral only)
```
Tlag = max{ t_i : C_i = BLOQ AND ∀ j < i, C_j = BLOQ }
```
- 첫 quantifiable 직전 시점. PO 투여에만 의미
- IV 투여 시 미산출

### 1.4 Tlast — Time of Last Quantifiable Concentration
```
Tlast = max{ t_i : C_i ≠ BLOQ }
```

### 1.5 Clast — Last Observed Quantifiable Concentration
```
Clast = C(Tlast)
```

### 1.6 Clast_pred — Predicted Last Concentration (from λz)
```
Clast_pred = exp(intercept_λz - λz · Tlast)
```
- 말단상 회귀 결과로부터 외삽

### 1.7 C0 — Estimated Concentration at Time Zero (IV bolus only)
- **알고리즘**: All versions (5.3, 6.4, 8.3) use **log back-extrapolation** from the first two quantifiable
  post-dose points. The formula is `C0 = exp(intercept)` where the intercept is from `ln C ~ t` regression
  on points 1–2 (WNL 5.3 p.196; WNL 6.4 UG §7.3; WNL 8.3 UG §8.2).
- **알고리즘 옵션** (`c0_method`): plugin-internal labels — `"log_back_extrap"` (default for all versions) |
  `"observed"` (use first quantifiable concentration; non-WNL) | `"auto"` (alias for `"log_back_extrap"`).
  The `"observed"` label is a plugin convenience option and does not correspond to any WinNonlin version default.

### 1.8 Ctrough / Cmin (Steady-state)
- 정상상태 dosing interval 내 최소 농도

---

## 2. 노출 (Exposure)

### 2.1 AUC_0-t — Area Under Curve, dosing to last observation
```
AUC_0-t = ∫₀^Tlast C(t) dt
```
- 적분 규칙: linear / log / linear-up/log-down — [02-auc-methods.md](02-auc-methods.md) 참조
- **단위**: [Conc·Time]
- **별칭**: `AUClast`, `AUCt`, `AUC0-t`

### 2.2 AUC_0-inf — Extrapolated to Infinity
두 변종 존재:
```
AUCINF_obs  = AUC_0-t + Clast / λz
AUCINF_pred = AUC_0-t + Clast_pred / λz
```
- **버전별 기본값**: All versions (5.3, 6.4, 8.3) output both `AUCINF_obs` and `AUCINF_pred`.
  (WNL 5.3 Table B-4 lists both; WNL 6.4/8.3 UG confirm same.)

### 2.3 AUC_%Extrap
```
AUC_%Extrap = (AUCINF - AUC_0-t) / AUCINF × 100
```
- 일반 BE 기준: **20% 이하** 권장 (그 이상이면 λz 신뢰성 의심)

### 2.4 Partial AUC — AUC(t1, t2)
[05-partial-auc.md](05-partial-auc.md) 참조

### 2.5 AUC_tau — Steady-state Dosing Interval AUC
```
AUC_tau = ∫₀^τ C(t) dt  (steady-state)
```
- [06-steady-state.md](06-steady-state.md)

---

## 3. 모멘트 (Moment-based)

### 3.1 AUMC_0-t
```
AUMC_0-t = ∫₀^Tlast t · C(t) dt
```

### 3.2 AUMC_0-inf
```
AUMC_inf = AUMC_0-t + Tlast · Clast / λz + Clast / λz²
```

### 3.3 MRT — Mean Residence Time (IV bolus)
```
MRT_obs  = AUMC_inf_obs  / AUCINF_obs
MRT_pred = AUMC_inf_pred / AUCINF_pred
```

#### MRT for IV infusion
```
MRT_infusion = AUMC_inf / AUCINF - T_inf / 2
```
- `T_inf` = infusion duration
- **버전 차이**: WinNonlin 5.3 uses `AUMC/AUC` (no T_inf/2 correction per WNL 5.3 p.199); 6.4+ subtracts T_inf/2 (WNL 6.4 UG §7.3.5). See 04-winnonlin-version-matrix §1.

#### MRT for PO
```
MAT (Mean Absorption Time) = MRT_PO - MRT_IV
```
- IV 데이터 없이는 산출 불가

---

## 4. 말단상 / 분포 / 청소율

### 4.1 Lambda_z (λz) — Terminal Elimination Rate Constant
```
ln C(t) = intercept - λz · t   (말단 양수점 OLS)
```
[03-lambda-z-selection.md](03-lambda-z-selection.md) 참조

추가 보고 항목:
- `Lambda_z_intercept`
- `Lambda_z_lower` / `Lambda_z_upper` (선택된 구간 시간)
- `No_points_lambda_z`
- `Rsq` (결정계수)
- `Rsq_adjusted`
- `Span_ratio = (Lambda_z_upper - Lambda_z_lower) / t_half`

### 4.2 t½ — Terminal Half-life
```
t½ = ln(2) / λz
```

### 4.3 CL — Systemic Clearance (IV)
```
CL = Dose / AUCINF
```
- **단위**: [Vol/Time]

### 4.4 CL/F — Apparent Clearance (PO)
```
CL/F = Dose / AUCINF
```

### 4.5 Vz — Volume of Distribution at Terminal Phase
```
Vz = Dose / (λz · AUCINF)         (IV)
Vz/F = Dose / (λz · AUCINF)       (PO)
```

### 4.6 Vss — Volume of Distribution at Steady State (IV only)
```
Vss = CL · MRT
```
- IV bolus 및 IV infusion 둘 다 적용 (MRT 정의 차이 주의)

### 4.7 Vc — Central Compartment Volume (모델 의존, NCA 미산출)

---

## 5. Steady-State 파라미터

[06-steady-state.md](06-steady-state.md) 에서 상세:
- `Cmax_ss`, `Tmax_ss`, `Cmin_ss`, `Ctrough_ss`
- `Cavg_ss = AUC_tau / τ`
- `Fluctuation = (Cmax_ss - Cmin_ss) / Cavg_ss × 100`
- `Swing = (Cmax_ss - Cmin_ss) / Cmin_ss` (ratio, no ×100; WNL 8.3 only)
- `Accumulation Ratio Rac = AUC_tau,ss / AUC_tau,first`

---

## 6. 용량 정규화 (Dose-Normalized)

선택적 산출:
```
Cmax_D    = Cmax    / Dose
AUC_D     = AUC     / Dose
```
- 단위 정의에 주의 (`[Conc]/[Mass]` 등)

---

## 7. 출력 표 스키마

WinNonlin 호환 long-format:

| 컬럼 | 예시 | 설명 |
|---|---|---|
| `subject_id` | `S001` | 대상자 |
| `period` | `1` | crossover period |
| `treatment` | `Test` | 처방 |
| `analyte` | `parent` | 모/대사체 |
| `parameter` | `AUClast` | 파라미터명 |
| `value` | `1234.5` | 수치 |
| `unit` | `ng·h/mL` | 단위 |
| `method` | `linear_up_log_down` | 알고리즘 |
| `winnonlin_version` | `6.4` | 호환 버전 |
| `flag` | `extrap%>20` | 경고/플래그 |
| `comment` | `Subject excluded baseline missing` | 사람-읽기 메모 |

---

## 📋 검증 매트릭스 (golden tests)

| 데이터셋 | 출처 | 적용 알고리즘 | 기준 |
|---|---|---|---|
| Theophylline (12명) | PKNCA fixture | linear + Best Fit λz (WNL 6.4 default) | ≤ 1e-6 상대오차 |
| Indomethacin | PKNCA fixture | 동일 | 동일 |
| WinNonlin 6.4 §7 예제 | 매뉴얼 | linear (WNL 6.4 UG default) | 매뉴얼 결과 |
| WinNonlin 5.3 예제 | 매뉴얼 | linear + log_back_extrap C0 (5.3 기본값) | 매뉴얼 결과 |
| WinNonlin 8.3 예제 | 매뉴얼 | linear (8.3 기본값; 5.3/6.4와 동일) | 매뉴얼 결과 |

> 매뉴얼 예제별 골든 데이터는 `tests/golden/winnonlin-{version}/` 에 위치.
