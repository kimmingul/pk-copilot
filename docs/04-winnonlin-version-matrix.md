# 04. WinNonlin Version Matrix (5.3 / 6.4 / 8.3)

> 동일한 PK/PD 파라미터라도 WinNonlin 버전마다 알고리즘 기본값, 출력 컬럼, 보고 규칙이 다를 수 있습니다. 이 문서는 그 차이를 한 곳에 집계하고, pk-copilot이 `winnonlin_version` 옵션으로 어떻게 분기하는지 명세합니다.

## 사용법

```python
result = run_nca(
    dataset=df,
    config=NCAConfig(
        winnonlin_version="6.4",   # "5.3" | "6.4" | "8.3" | "compat-latest"
        # ... 개별 옵션은 명시 지정 시 version 기본값을 오버라이드
    )
)
```

기본 결정 트리:
```
if user_specified == "5.3"  → use 5.3 defaults
if user_specified == "6.4"  → use 6.4 defaults (pk-copilot 권장 기본)
if user_specified == "8.3"  → use 8.3 defaults
if user_specified == "compat-latest" → pk-copilot 자체 기본 (8.3 ≈ 동일)
```

---

## 1. NCA 핵심 알고리즘 비교

| 항목 | WinNonlin 5.3 | WinNonlin 6.4 | WinNonlin 8.3 | pk-copilot 기본 |
|---|---|---|---|---|
| AUC 적분 기본 | linear (GUI 기본) 📋 | linear-up/log-down | linear-up/log-down | linear-up/log-down |
| Lambda_z 기본 | Best Fit 📋 | Best Fit | Best Fit | Best Fit |
| Best Fit tolerance (Adj R²) | 0.0001 📋 | 0.0001 | 0.0001 | 0.0001 |
| C0 (IV bolus) 추정 | observed first | log back-extrapolation (2점) | log back-extrap | log back-extrap |
| AUCINF_pred 출력 | 미지원 📋 | 지원 | 지원 | 지원 |
| Span ratio 경고 임계 | 없음 📋 | < 2 (권장) | < 2 (권장) | < 1.5 (안전) + 옵션 |
| Partial AUC 기본 보간 | linear | linear-up/log-down | linear-up/log-down | linear-up/log-down |
| BLOQ pre-dose 처리 | 0 | 0 | 0 | 0 |
| BLOQ embedded 처리 | missing | missing | missing | missing |
| BLOQ trailing 처리 | exclude | exclude | exclude | exclude |
| MRT (IV infusion) 정의 | `AUMC/AUC` 📋 | `AUMC/AUC - T_inf/2` | `AUMC/AUC - T_inf/2` | `AUMC/AUC - T_inf/2` |
| Vss 정의 | `CL · MRT` | `CL · MRT` | `CL · MRT` | `CL · MRT` |
| AUC %Extrap 경고 임계 | 20% | 20% | 20% | 20% |
| Geometric mean 정의 | exp(mean(ln)) | exp(mean(ln)) | exp(mean(ln)) | exp(mean(ln)) |
| Geometric CV% | `sqrt(exp(σ²_ln) - 1) · 100` | 동일 | 동일 | 동일 |

📋 = TODO: 매뉴얼 페이지 직접 확인 필요

---

## 2. 출력 파라미터 컬럼 차이

| 파라미터 | 5.3 | 6.4 | 8.3 | 비고 |
|---|---|---|---|---|
| `Cmax` | ✓ | ✓ | ✓ | |
| `Tmax` | ✓ | ✓ | ✓ | |
| `Tlast` | ✓ | ✓ | ✓ | |
| `Clast` | ✓ | ✓ | ✓ | |
| `Clast_pred` | ✗ 📋 | ✓ | ✓ | |
| `C0` | observed | log back-extrap | log back-extrap | |
| `AUCINF_obs` | ✓ | ✓ | ✓ | |
| `AUCINF_pred` | ✗ 📋 | ✓ | ✓ | |
| `AUC_%Extrap_obs` | ✓ | ✓ | ✓ | |
| `AUC_%Extrap_pred` | ✗ 📋 | ✓ | ✓ | |
| `Lambda_z_lower` | ✓ | ✓ | ✓ | |
| `Lambda_z_upper` | ✓ | ✓ | ✓ | |
| `No_points_lambda_z` | ✓ | ✓ | ✓ | |
| `Rsq_adjusted` | ✓ | ✓ | ✓ | |
| `Span` | ✓ | ✓ | ✓ | |
| `Span_ratio` | 📋 | ✓ | ✓ | |
| `AUMC_obs` / `AUMC_pred` | obs only | both | both | |
| `MRTINF_obs` / `MRTINF_pred` | obs only | both | both | |
| `Vss` | ✓ | ✓ | ✓ | |
| `Vss_obs` / `Vss_pred` | obs only | both | both | |

📋 = 매뉴얼 직접 확인 필요

---

## 3. BE 모듈 차이

| 항목 | 5.3 | 6.4 | 8.3 | 비고 |
|---|---|---|---|---|
| df 계산 (mixed model) | Satterthwaite 📋 | Satterthwaite | Satterthwaite / Kenward-Roger 선택 | |
| Sequence test 보고 | F-test | F-test | F-test | |
| Within-subject CV 정의 | `sqrt(exp(σ²_w) - 1)` | 동일 | 동일 | |
| Power 계산 기본 | post-hoc | post-hoc | post-hoc | |
| Higher-order 디자인 | 제한적 | 지원 확대 | 풀 지원 | |

---

## 4. 구획 모델 차이

| 항목 | 5.3 | 6.4 | 8.3 | 비고 |
|---|---|---|---|---|
| Weighting 기본 | `1` 📋 | `1/y²` | `1/y²` | |
| AIC 정의 | `N·ln(SS/N) + 2k` | `N·ln(SS/N) + 2k` | `N·ln(SS/N) + 2k` (대안: `2k - 2lnL`) | |
| BIC 정의 | `N·ln(SS/N) + k·ln(N)` | 동일 | 동일 | |
| ODE solver 노출 | 제한적 | 지원 | LSODA 기본 | |
| Initial estimate auto-fill | 부분 | 자동 | 자동 + recommend | |

---

## 5. UI / Export 차이 (참고용)

| 항목 | 5.3 | 6.4 | 8.3 |
|---|---|---|---|
| Worksheet 형식 | `.wnl5` | `.phxproj` | `.phxproj` |
| Plot export | EMF/JPG | PNG/SVG | PNG/SVG/PDF |
| CDISC export | 없음 | SDTM PP 시작 | SDTM PP 풀 지원 |

> pk-copilot은 어떤 WinNonlin 파일 포맷도 직접 읽지/쓰지 않습니다. **CSV/Excel/CDISC만 지원**.

---

## 6. 구현 패턴

```python
# src/pkplugin/version.py
from enum import Enum

class WNVersion(str, Enum):
    V5_3 = "5.3"
    V6_4 = "6.4"
    V8_3 = "8.3"
    LATEST = "compat-latest"

DEFAULTS: dict[WNVersion, dict] = {
    WNVersion.V5_3: {
        "auc_method": "linear",
        "lambda_z_method": "best_fit",
        "lambda_z_tolerance": 0.0001,
        "c0_method": "observed",
        "output_pred_variants": False,
        "bloq_policy": {
            "pre_dose": "zero", "up_leading": "zero",
            "embedded": "missing", "trailing": "exclude",
        },
        "comp_weighting_default": "uniform",
    },
    WNVersion.V6_4: {
        "auc_method": "linear_up_log_down",
        "lambda_z_method": "best_fit",
        "lambda_z_tolerance": 0.0001,
        "c0_method": "log_back_extrap",
        "output_pred_variants": True,
        "bloq_policy": {
            "pre_dose": "zero", "up_leading": "zero",
            "embedded": "missing", "trailing": "exclude",
        },
        "comp_weighting_default": "1_over_y_squared",
    },
    WNVersion.V8_3: {
        "auc_method": "linear_up_log_down",
        "lambda_z_method": "best_fit",
        "lambda_z_tolerance": 0.0001,
        "c0_method": "log_back_extrap",
        "output_pred_variants": True,
        "bloq_policy": { ... 6.4 와 동일 ... },
        "comp_weighting_default": "1_over_y_squared",
    },
}

def resolve_config(user_config: NCAConfig) -> NCAConfig:
    base = DEFAULTS[user_config.winnonlin_version]
    return NCAConfig.merge(base, user_config)
```

---

## 7. 보고 출력에 버전 표시

모든 NCA / BE / Comp 결과 표 헤더에 다음을 강제 포함:
```
NCA Analysis — pk-copilot v0.1.0
WinNonlin compatibility: 6.4
AUC method: linear-up/log-down
Lambda_z method: Best Fit
Backend: Python (PKNCA cross-validated)
```

---

## 8. 매뉴얼 인용 트레이서빌리티

각 알고리즘 차이 항목별로 매뉴얼 페이지를 기록한 trace 파일:

`docs/04-winnonlin-version-matrix.trace.csv` (자동 생성 예정):
```csv
field,version,manual,section,page,notes
auc_method,5.3,WinNonlin User's Guide 5.3.pdf,§6.1.4,118,linear default GUI
auc_method,6.4,Phoenix WinNonlin 6.4 User's Guide.pdf,§7.2.3,142,linear-up/log-down
...
```

> 📋 TODO 항목들은 v0.1 개발 초기에 일괄 매뉴얼 검증 후 채워야 함. 이 작업은 별도 issue로 트래킹.

---

## 9. 변경 관리

- 매뉴얼 검증 후 default 변경 시 → CHANGELOG.md "Behavior change (version-aware)" 섹션 강제
- 골든 테스트가 버전별 디렉터리로 분리되어 있으므로 회귀 자동 감지
- v2 규제 모드에서는 `winnonlin_version` 명시 강제 (디폴트 적용 차단)
