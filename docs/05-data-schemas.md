# 05. Data Schemas & Units

> 모든 데이터 입력은 Pydantic v2 스키마로 검증되며, 단위는 `pint` 라이브러리로 명시 관리합니다.

## 1. 핵심 데이터 모델

### 1.1 ConcentrationRecord
```python
from pydantic import BaseModel, Field
from typing import Literal

class ConcentrationRecord(BaseModel):
    subject_id: str
    time: float = Field(..., description="post-dose time in canonical unit (hr)")
    concentration: float | None = Field(..., description="None == missing")
    analyte: str = "parent"
    matrix: Literal["plasma", "serum", "blood", "urine", "other"] = "plasma"
    period: str | None = None
    sequence: str | None = None
    treatment: str | None = None
    bloq: bool = False
    bloq_rule_applied: str | None = None     # "pre_dose", "embedded_missing", etc
    raw_concentration: str | None = None     # "<0.5"와 같은 원본 문자열 보존
```

### 1.2 DoseRecord
```python
class DoseRecord(BaseModel):
    subject_id: str
    time: float                              # canonical hr
    amount: float                            # canonical mg
    route: Literal["iv_bolus", "iv_infusion", "oral", "subcut", "im", "other"]
    infusion_duration: float | None = None   # hr
    period: str | None = None
    treatment: str | None = None
```

### 1.3 CovariateRecord
```python
class CovariateRecord(BaseModel):
    subject_id: str
    age: float | None = None                  # years
    sex: Literal["M", "F", "U"] = "U"
    weight: float | None = None               # kg
    height: float | None = None               # cm
    crcl: float | None = None                 # mL/min (Cockcroft-Gault 또는 보고치)
    egfr: float | None = None                 # mL/min/1.73m²
    bsa: float | None = None                  # m²
    custom: dict[str, float | str] = {}
```

### 1.4 StudyDesign
```python
class StudyDesign(BaseModel):
    study_id: str
    design: Literal[
        "single_dose", "multiple_dose",
        "crossover_2x2", "parallel",
        "replicate_2x4", "higher_order"
    ]
    tau: float | None = None                  # dosing interval (hr) for MD
    formulations: list[str] = []              # ["Test", "Reference"]
    sequences: list[str] = []                 # ["TR", "RT"]
    washout_hr: float | None = None
```

### 1.5 NCAConfig
```python
class NCAConfig(BaseModel):
    winnonlin_version: Literal["5.3", "6.4", "8.3", "compat-latest"] = "6.4"
    auc_method: Literal["linear", "log", "linear_up_log_down"] | None = None
    lambda_z_method: Literal["best_fit", "adj_r2", "manual", "time_range", "n_points"] | None = None
    lambda_z_tolerance: float | None = None
    lambda_z_min_points: int = 3
    lambda_z_manual: dict | None = None
    c0_method: Literal["observed", "log_back_extrap", "auto"] | None = None
    bloq_policy: Literal["default", "zero", "missing", "custom"] = "default"
    bloq_custom: dict | None = None
    partial_auc_windows: list[tuple[float, float]] = []
    output_pred_variants: bool | None = None
    span_ratio_min: float = 1.5
    weight_normalization: Literal["none", "per_kg"] = "none"
    dose_normalization: bool = False
```

---

## 2. 단위 시스템 (pint)

### 정규화된 내부 단위
| 양 | 정규 단위 | 표시 |
|---|---|---|
| 농도 | mass/volume (`ng/mL`) | `ng·mL⁻¹` |
| 시간 | `hr` | `h` |
| 용량 | `mg` | `mg` |
| 부피 | `L` | `L` |
| 청소율 | `L/hr` | `L·h⁻¹` |

### 자동 인식 패턴
- `ng/mL`, `ug/L`, `mcg/L` → 동일
- `nmol/L`, `umol/L` → molar (분자량 입력 필수 → mass로 변환)
- `min`, `day` → `hr` 변환
- `mg/kg` → 사용자 가중치로 정규화 (또는 dose normalization)

### 단위 강제 확인
**모든 데이터 로드 시점**에서:
```
[Unit Confirmation Required]
  Concentration column: 농도 (ng/mL)  →  ng/mL    [Y/edit]
  Time column:          시간 (hr)     →  hr       [Y/edit]
  Dose column:          용량 (mg)     →  mg       [Y/edit]

Proceed with analysis? [Y/n]
```
- 거부 시 분석 차단 (PreToolUse hook)
- Audit log에 단위 결정 기록

---

## 3. Long Format (canonical)

모든 분석은 long format에서 동작:

```csv
subject_id,time_hr,conc_ng_per_ml,bloq,analyte,period,treatment,raw_conc
S001,0,0,true,parent,1,Test,<0.5
S001,0.5,12.4,false,parent,1,Test,12.4
S001,1.0,18.7,false,parent,1,Test,18.7
...
```

Wide → Long 변환 helper:
```python
def wide_to_long(df, time_cols=["t0", "t0_5", "t1", ...]) -> pd.DataFrame:
    ...
```

---

## 4. CDISC 매핑 (v2)

[09-cdisc-support.md](09-cdisc-support.md) 상세. 요약:

| pk-copilot 필드 | CDISC SDTM PC |
|---|---|
| `subject_id` | `USUBJID` |
| `time` | `PCDTC` (datetime) 또는 `PCELTM` (elapsed time) |
| `concentration` | `PCSTRESN` |
| `analyte` | `PCTEST` |
| `matrix` | `PCSPEC` |
| `bloq` | `PCSTRESN < LLOQ` (LB 도메인의 LBORRES 참조) |

| pk-copilot 필드 | CDISC SDTM EX |
|---|---|
| `dose.amount` | `EXDOSE` |
| `dose.time` | `EXSTDTC` |
| `dose.route` | `EXROUTE` |

---

## 5. 출력 파라미터 표 (long)

```python
class NCAParameterRow(BaseModel):
    subject_id: str
    period: str | None = None
    treatment: str | None = None
    analyte: str = "parent"
    parameter: str                            # "Cmax", "AUClast", ...
    value: float | None
    unit: str
    method: str                               # "linear_up_log_down" etc
    winnonlin_version: str
    flags: list[str] = []
    comment: str | None = None
```

CSV/Excel/Parquet 출력 시 동일 스키마.

---

## 6. JSON-of-Record 스키마

```json
{
  "run_id": "2026-05-25-001",
  "run_timestamp_utc": "2026-05-25T03:58:08Z",
  "pkplugin_version": "0.1.0",
  "winnonlin_compat": "6.4",
  "user": "kimmingul@gmail.com",       // v2: signed
  "input_files": [
    {"path": "raw.csv", "sha256": "..."}
  ],
  "normalized_dataset_hash": "sha256:...",
  "config": {NCAConfig.dict()},
  "dependency_versions": {
    "python": "3.12.4",
    "numpy": "2.1.0",
    "scipy": "1.14.1",
    "pkplugin": "0.1.0",
    "PKNCA": "0.10.2 (validation backend)"
  },
  "os": {"platform": "darwin", "release": "25.5.0"},
  "results": {NCAResult.dict()},
  "warnings": [],
  "artifacts": [
    {"name": "report.html", "sha256": "..."},
    {"name": "nca_script.py", "sha256": "..."}
  ]
}
```
