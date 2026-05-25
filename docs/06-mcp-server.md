# 06. MCP Server Tool Catalog

> Claude는 인-챗에서 Python을 실행하지 않습니다. 모든 계산은 결정론적 MCP 도구를 통해 수행합니다.

## 서버 등록 (`.mcp.json`)

```json
{
  "mcpServers": {
    "pk-kernel": {
      "command": "uv",
      "args": ["run", "python", "-m", "pkplugin.mcp_server"],
      "env": {
        "PKPLUGIN_AUDIT_DIR": "${CLAUDE_PROJECT_DIR}/pk_runs",
        "PKPLUGIN_R_BACKEND": "auto"
      }
    }
  }
}
```

---

## 도구 카탈로그

### 1. `validate_dataset` (v0.1)
```python
def validate_dataset(
    input_file: str,
    schema_type: Literal["concentration", "dose", "covariate", "auto"] = "auto",
    column_mapping: dict | None = None,
    units: dict | None = None,
) -> ValidationReport
```
- 컬럼 자동 매핑 + 단위 확인
- BLOQ 패턴 (`<LLOQ`, `BLQ`, `LLOQ`) 자동 검출
- 시간 단조성 / 중복 제거 / 유효 범위 검사
- 반환: `{ status, mapped_columns, units_detected, warnings, lloq_candidates, n_subjects, ... }`

### 2. `run_nca` (v0.1)
```python
def run_nca(
    dataset_path: str,
    config: NCAConfig,
    subjects: list[str] | None = None,   # None = all
    analytes: list[str] | None = None,
) -> NCAResult
```
- 단일 또는 다대상자 NCA
- 모든 NCA 파라미터 + JSON-of-record + 스크립트 생성
- 반환: `{ run_id, parameter_table, audit_path, script_path, ... }`

### 3. `run_be` (v0.2)
```python
def run_be(
    parameter_dataset_path: str,
    design: BEDesign,
    endpoints: list[str] = ["AUC0_t", "AUC0_inf", "Cmax"],
) -> BEResult
```
- crossover / parallel
- mixed model + TOST + 90% CI
- Reference: `Test`, `Reference` 처치 식별

### 4. `fit_pk_model` (v0.3)
```python
def fit_pk_model(
    dataset_path: str,
    model_spec: PKModelSpec,                 # cmt1_iv_bolus 등
    initial_params: dict | None = None,
    bounds: dict | None = None,
    weighting: Literal["uniform", "1_over_y", "1_over_y_squared", "1_over_pred", "1_over_pred_squared"] = "1_over_y_squared",
    residual_error: Literal["additive", "proportional", "combined"] = "proportional",
    solver: Literal["closed_form", "lsoda", "bdf", "rk45"] = "closed_form",
    method: Literal["nls", "mle", "bayesian"] = "nls",
) -> FitResult
```

### 5. `fit_pd_model` (v0.4)
```python
def fit_pd_model(
    pk_fit_id: str | None,                   # sequential mode
    pd_dataset_path: str,
    pd_model_spec: PDModelSpec,              # emax, sigmoid_emax, effect_compartment, idr_1..4, turnover
    mode: Literal["sequential", "simultaneous"] = "sequential",
    initial_params: dict | None = None,
) -> FitResult
```

### 6. `simulate` (v0.3)
```python
def simulate(
    model_spec: PKModelSpec | PDModelSpec,
    params: dict[str, float],
    dosing: DosingSchedule,
    times: list[float],
) -> SimulationResult
```
- 모델 + 파라미터 + 투여 스케줄 → 예측 농도/효과

### 7. `generate_report` (v0.5)
```python
def generate_report(
    run_id: str,
    format: Literal["html", "pdf", "quarto", "docx"] = "html",
    template: str = "winnonlin_compat",
) -> ArtifactPaths
```

### 8. `compare_against_reference` (v0.5)
```python
def compare_against_reference(
    run_id: str,
    reference_backend: Literal["pknca", "noncompart"] = "pknca",
    tolerance: float = 1e-6,
) -> ValidationDiff
```
- R subprocess로 PKNCA/NonCompart 실행
- 파라미터별 absolute / relative error 보고

---

## v2.0 추가 도구

### 9. `import_sdtm` (v2.0)
```python
def import_sdtm(
    pc_path: str,                            # SDTM PC dataset
    ex_path: str,                            # SDTM EX dataset
    dm_path: str | None = None,
    vs_path: str | None = None,
) -> NormalizedDataset
```

### 10. `export_adam` (v2.0)
```python
def export_adam(
    run_id: str,
    domains: list[Literal["ADPC", "ADPP"]] = ["ADPC", "ADPP"],
    output_dir: str = "adam/",
    include_define_xml: bool = True,
) -> list[str]
```

### 11. `sign_record` (v2.0)
```python
def sign_record(
    run_id: str,
    signer_identity: str,
    meaning: Literal["authored", "reviewed", "approved"],
    auth_token: str,                         # TOTP / hardware key
) -> SignedRecord
```

### 12. `lock_run` (v2.0)
```python
def lock_run(run_id: str, lock_reason: str) -> LockResult
```
- 분석 finalize → write-protected
- WORM 스토리지에 sealed copy 작성

---

## 도구 명세 규약

모든 MCP 도구는 다음을 만족:
1. **결정론적**: 동일 입력 → 동일 출력 (난수 시드 명시)
2. **JSON-serializable** 인자/반환
3. **Audit emission**: 모든 호출이 audit log에 기록
4. **Versioned**: 입출력 스키마 변경 시 `tool_version` 증가
5. **Error 명확성**: 입력 오류는 구체적 위치 + 권장 수정

---

## 호출 예시 (Claude → MCP)

사용자: *"이 CSV로 NCA 돌려줘"*
→ Claude:
```
1. validate_dataset(input_file="data.csv")
   → mapping 제안, 사용자 승인
2. run_nca(
     dataset_path="data_normalized.csv",
     config={winnonlin_version: "6.4"}
   )
   → λz 회귀 결과 표시, 사용자 승인 (interactive flag)
3. generate_report(run_id=..., format="html")
   → 파일 경로 반환
```

Claude는 결과를 **요약/해석**하지만, 숫자를 **계산하지 않습니다**.
