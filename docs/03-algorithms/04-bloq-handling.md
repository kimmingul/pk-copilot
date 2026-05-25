# 03.04 — BLOQ / Missing 처리 정책

> BLOQ(Below Limit of Quantification) 처리는 NCA 결과에 직접 영향을 줍니다. 정책을 명시적으로 선언하고 모든 변경을 audit log에 기록합니다.

## 1. 정의

| 용어 | 정의 |
|---|---|
| **BLOQ** | LLOQ(Lower Limit of Quantification) 미만 |
| **LLOQ** | 분석법이 정량 가능한 최저 농도 |
| **Missing** | 측정 자체가 없거나 거부된 시점 |
| **ALOQ** | Above Upper LOQ (드물게) |

## 2. 시점별 분류

```
        LLOQ
         ↓
─────[Pre-dose]────[First quantifiable]────...────[Last quantifiable]────[Terminal]──→
         ↑                  ↑                              ↑                  ↑
      pre-dose       up-leading edge                  trailing edge       terminal
      BLOQ           BLOQ (between)                   BLOQ (between)      BLOQ
```

- **Pre-dose BLOQ**: 투여 전 BLOQ
- **Up-leading BLOQ**: 첫 quantifiable 이전의 post-dose BLOQ (PO 흡수 지연)
- **Embedded BLOQ**: quantifiable 사이에 끼인 BLOQ
- **Trailing BLOQ**: 마지막 quantifiable 이후 BLOQ

## 3. 정책 매트릭스

### 3.1 기본 정책 (`bloq_policy="default"`)

| 위치 | 처리 |
|---|---|
| Pre-dose | **0 으로 치환** (IV는 의미 없음, PO는 baseline) |
| Up-leading (PO 흡수 전) | **0 으로 치환** |
| Embedded | **Missing/Exclude** (보간 X, AUC 계산에서 skip) |
| Trailing | **Exclude** (λz, AUC 모두에서) |

### 3.2 "Zero" 정책 (`bloq_policy="zero"`)
- 모든 BLOQ → 0 (단순)
- linear trapezoid에서 안전, log에서 무효 → linear로 폴백

### 3.3 "Missing" 정책 (`bloq_policy="missing"`)
- 모든 BLOQ → 제외
- 인접 시점 정보로만 AUC 계산

### 3.4 "Custom" 정책 (`bloq_policy="custom"`)
사용자가 위치별로 직접 지정:
```yaml
bloq_policy: custom
rules:
  pre_dose: zero
  up_leading: zero
  embedded: missing
  trailing: exclude
  lloq_value: 0.5
  replacement_for_zero: 0
```

---

## 4. 버전별 기본값

| 버전 | Pre-dose | Up-leading | Embedded | Trailing | 비고 |
|---|---|---|---|---|---|
| WinNonlin 5.3 | 0 | 0 | missing | exclude | 📋 TODO: 매뉴얼 확인 |
| WinNonlin 6.4 | 0 | 0 | missing | exclude | 매뉴얼 §7.5 |
| WinNonlin 8.3 | 0 | 0 | missing | exclude | 매뉴얼 §8.4 |

> Phoenix WinNonlin은 LLOQ 미만 처리 옵션이 GUI에서 노출 → 동일 옵션 노출 필요.

---

## 5. 알고리즘에 미치는 영향

| 파라미터 | BLOQ 정책 영향도 | 비고 |
|---|---|---|
| Cmax / Tmax | 낮음 (quantifiable만 사용) | |
| AUC_0-t | **높음** | embedded/trailing 처리에 따라 변동 |
| AUC_0-inf | 높음 | λz 회귀 + extrapolation 모두 |
| λz / t½ | **매우 높음** | trailing BLOQ 제외 여부 |
| Vss / CL | 높음 | AUCINF, MRT 의존 |

---

## 6. 출력 보고

NCA 결과 JSON에 다음 섹션 강제 포함:

```json
"bloq_handling": {
  "policy": "default",
  "lloq": 0.5,
  "lloq_unit": "ng/mL",
  "winnonlin_version": "6.4",
  "modifications": [
    {"subject": "S001", "time": 0.0, "raw": "<0.5", "treated_as": 0,    "rule": "pre_dose"},
    {"subject": "S001", "time": 0.5, "raw": "<0.5", "treated_as": 0,    "rule": "up_leading"},
    {"subject": "S001", "time": 36,  "raw": "<0.5", "treated_as": null, "rule": "trailing_exclude"}
  ]
}
```

---

## 7. UX

데이터 로드 시 BLOQ 발견되면 강제 프롬프트:
```
[BLOQ Detected]
  S001: 3 BLOQ values found
  S002: 5 BLOQ values found
  ...

Recommended policy (WinNonlin 6.4 default):
  - Pre-dose & up-leading BLOQ  → 0
  - Embedded BLOQ               → Missing
  - Trailing BLOQ               → Excluded

Apply this policy? [Y/n/custom]
```

---

## 8. 검증

| 테스트 | 시나리오 |
|---|---|
| `test_pre_dose_bloq_to_zero` | pre-dose BLOQ → 0 치환 후 AUC 일치 |
| `test_embedded_bloq_skip` | 중간 BLOQ → AUC 계산에서 skip |
| `test_trailing_bloq_excluded_from_lambda_z` | trailing BLOQ → λz 회귀에서 제외 |
| `test_pknca_bloq_compat` | PKNCA `conc.blq=0` 옵션과 일치 |
