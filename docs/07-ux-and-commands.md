# 07. UX & Commands

> 슬래시 명령어, 에이전트, 스킬의 동작 사양과 인터랙티브 UX 설계.
> MCP 도구 스키마는 [06-mcp-server.md](06-mcp-server.md), 알고리즘 세부는 [03-algorithms/](03-algorithms/)를 참조.

---

## 1. UX 철학

### 1.1 대화형 노트북 패러다임

pk-copilot은 Phoenix WinNonlin의 GUI 워크플로우를 **대화형 텍스트 인터페이스**로 옮긴다. 핵심 원칙은 다음과 같다.

- **LLM은 오케스트레이터**: 의도 해석, 결과 설명, 감사 기록. 숫자 계산은 MCP 도구에 위임.
- **단계별 승인**: 데이터 매핑 → 분석 설정 → 결과 → 리포트 각 단계에서 사용자가 계속/수정/중단을 결정.
- **감사 추적 우선**: 모든 실행이 JSON-of-record + 실행 스크립트 + audit log를 생성. 분석을 재현하거나 감사할 수 있어야 한다.

### 1.2 Progressive Disclosure — 초보 vs 전문가

| 모드 | 트리거 | 동작 |
|---|---|---|
| **기본 (Novice)** | 플래그 없음 | 단위 자동 추론 후 확인 프롬프트, 기본 옵션 사용, 결과 요약만 표시 |
| **상세 (Expert)** | `--expert` 또는 `nca_config.yaml` 존재 | 모든 옵션 명시적 확인, 중간 계산 결과 노출, Lambda_z 회귀표 전체 출력 |
| **자동화 (Headless)** | `--no-interactive` | 프롬프트 생략, 기본값 자동 적용, CI/CD 파이프라인용 |

### 1.3 신뢰와 설명 가능성

블랙박스 계산 금지. 모든 파라미터 값에는 계산 근거가 동반된다.

- Lambda_z 회귀 창과 선택 이유 (`adj_R²`, 포인트 수)
- BLOQ 처리 정책과 영향받은 시점 목록
- 어떤 WinNonlin 버전 알고리즘을 사용했는지

---

## 2. 슬래시 명령어

### 2.1 `/nca` — 비구획분석

**목적**: 농도-시간 데이터에서 NCA 파라미터(Cmax, Tmax, AUC, t½, CL 등)를 계산한다.

**사용 시점**: 단일 또는 다대상자 PK 데이터가 준비된 경우. WinNonlin NCA 워크시트의 대화형 대안.

**호출 MCP 도구**: `validate_dataset` → `run_nca` → (선택적) `generate_report`

**흐름**:
1. 파일 경로 또는 현재 디렉터리 CSV/Excel 자동 감지
2. `validate_dataset`로 컬럼 매핑 + 단위 확인 프롬프트
3. `run_nca` 실행 → Lambda_z 승인 프롬프트 (interactive 모드)
4. 결과 요약 출력 + 산출물 경로 안내

**예시 호출**:
```
/nca data/theophylline.csv
/nca data/study001.csv --version 6.4 --expert
/nca data/study001.csv --no-interactive --output runs/
```

**주요 플래그**:

| 플래그 | 기본값 | 설명 |
|---|---|---|
| `--version` | `6.4` | WinNonlin 호환 버전 (`5.3`, `6.4`, `8.3`) |
| `--auc-method` | `linear_up_log_down` | AUC 적분 방법 |
| `--bloq` | `version_default` | BLOQ 정책 ([03-algorithms/04-bloq-handling.md](03-algorithms/04-bloq-handling.md)) |
| `--subjects` | all | 특정 대상자 ID 목록 (쉼표 구분) |
| `--expert` | off | 중간 계산값 노출 |
| `--no-interactive` | off | 모든 프롬프트 자동 승인 |

**기대 출력** (기본 모드):
```text
┌─ NCA 결과 — study001.csv ──────────────────────────────────────┐
│ 대상자: 12명 | 버전: WinNonlin 6.4 | 실행 ID: 2026-05-25-001  │
│                                                                │
│ 파라미터 (geometric mean ± geometric CV%)                       │
│  Cmax        :  42.3 ng/mL   (± 18.4%)                        │
│  Tmax        :   1.5 h       (median)                          │
│  AUC0-t      : 391.2 ng·h/mL (± 21.7%)                        │
│  AUC0-inf    : 418.7 ng·h/mL (± 19.3%)                        │
│  t½          :   8.6 h       (± 12.1%)                        │
│  CL/F        :   2.42 L/h    (± 22.8%)                        │
│  Vz/F        :  29.6 L       (± 28.5%)                        │
│                                                                │
│ 산출물                                                          │
│  runs/2026-05-25-001/audit.md                                  │
│  runs/2026-05-25-001/nca_script.py                             │
│  runs/2026-05-25-001/results.csv                               │
└────────────────────────────────────────────────────────────────┘
```

---

### 2.2 `/pk-fit` — 구획 모델 적합 (v0.3+)

**목적**: 1/2/3-구획 PK 모델을 농도-시간 데이터에 적합시킨다.

**사용 시점**: NCA로 초기 추정치를 얻은 후, 파라미터화된 모델이 필요할 때.

**호출 MCP 도구**: `validate_dataset` → `fit_pk_model` → (선택적) `generate_report`

**예시 호출**:
```
/pk-fit data/study001.csv --model 2cmt-po --weighting 1/y2
/pk-fit data/study001.csv --model 1cmt-iv-infusion --init-from-nca runs/2026-05-25-001
```

**주요 플래그**:

| 플래그 | 기본값 | 설명 |
|---|---|---|
| `--model` | (필수) | 모델 코드 (아래 표) |
| `--weighting` | `1/y2` | 가중치 scheme |
| `--method` | `nls` | 적합 방법 (`nls`, `mle`) |
| `--init-from-nca` | — | NCA 결과에서 초기 추정치 자동 생성 |
| `--solver` | `closed_form` | ODE 솔버 (Michaelis-Menten 시 `lsoda` 자동 전환) |

**지원 모델 코드** (v0.3):

| 코드 | 모델 | WinNonlin 모델 번호 |
|---|---|---|
| `1cmt-iv-bolus` | 1-구획 IV bolus | Model 1 |
| `1cmt-po` | 1-구획 1차 흡수 경구 | Model 7 |
| `1cmt-iv-infusion` | 1-구획 정주 | Model 11 |
| `2cmt-iv-bolus` | 2-구획 IV bolus | Model 2 |
| `2cmt-po` | 2-구획 1차 흡수 경구 | Model 8 |
| `2cmt-iv-infusion` | 2-구획 정주 | Model 12 |

---

### 2.3 `/pd-fit` — PK/PD 연결 모델 적합 (v0.4+)

**목적**: PK 결과(또는 별도 노출 데이터)를 PD 반응 데이터에 연결·적합시킨다.

**사용 시점**: Emax, 효과 구획, 간접 반응 모델 분석 시.

**호출 MCP 도구**: `fit_pd_model` → (선택적) `generate_report`

**예시 호출**:
```
/pd-fit --pk-run 2026-05-25-001 --pd-data pd_response.csv --model emax
/pd-fit --pk-run 2026-05-25-001 --pd-data bis.csv --model effect-cmt --mode simultaneous
```

---

### 2.4 `/be` — 생물학적동등성 분석 (v0.2+)

**목적**: Crossover 또는 parallel BE 스터디에서 GMR + 90% CI + TOST 판정.

**사용 시점**: NCA 파라미터 테이블이 있고 Test vs Reference 비교가 필요할 때.

**호출 MCP 도구**: `run_be`

**예시 호출**:
```
/be nca_results.csv --design 2x2-crossover --ref Reference
/be nca_results.csv --design parallel --endpoints AUC0-t,Cmax
```

**기대 출력**:
```text
┌─ BE 결과 — 2×2 Crossover ──────────────────────────────────────┐
│ 엔드포인트   GMR      90% CI              판정                  │
│ AUC0-t      1.032    [0.983, 1.083]      PASS (80-125%)        │
│ AUC0-inf    1.028    [0.976, 1.082]      PASS                  │
│ Cmax        1.047    [0.991, 1.106]      PASS                  │
│                                                                │
│ 결론: Test와 Reference는 생물학적으로 동등합니다.               │
└────────────────────────────────────────────────────────────────┘
```

---

### 2.5 `/prep-data` — 데이터 전처리

**목적**: 원시 CSV/Excel/XPT를 pk-copilot 표준 스키마로 정규화한다.

**사용 시점**: `/nca` 전, 또는 데이터 품질 문제를 먼저 확인하고 싶을 때. `/nca`는 내부적으로 이 단계를 자동 수행하지만, 별도 실행으로 데이터 문제를 미리 파악할 수 있다.

**호출 MCP 도구**: `validate_dataset`

**예시 호출**:
```
/prep-data raw/messy_study.xlsx
/prep-data data/pc.sas7bdat --cdisc-sdtm  # v2: SDTM PC 도메인
```

---

### 2.6 `/diagnose` — 진단 플롯 및 적합도 평가 (v0.3+)

**목적**: 구획 모델 적합 후 진단 플롯을 생성하고 goodness-of-fit을 평가한다.

**사용 시점**: `/pk-fit` 또는 `/pd-fit` 실행 후, 결과 타당성 검토 시.

**호출 MCP 도구**: 내부적으로 `fit_pk_model` 결과의 `diagnostics` 필드 활용

**생성 플롯**: observed vs predicted, weighted residuals vs time, weighted residuals vs pred, QQ plot

**예시 호출**:
```
/diagnose --run 2026-05-25-002
```

---

### 2.7 `/report` — 리포트 생성 (v0.5+)

**목적**: 기존 분석 실행에서 WinNonlin 스타일 리포트를 생성한다.

**사용 시점**: 분석이 완료된 후 공식 문서화가 필요할 때.

**호출 MCP 도구**: `generate_report`

**예시 호출**:
```
/report --run 2026-05-25-001 --format html
/report --run 2026-05-25-001 --format pdf --template winnonlin_compat
```

---

## 3. 에이전트

에이전트는 슬래시 명령 내부에서 자동으로 호출되거나, `@에이전트명`으로 직접 호출된다.

### 3.1 `nca-analyst`

| 항목 | 내용 |
|---|---|
| **트리거** | `/nca` 호출 시 자동, 또는 "@nca-analyst 이 데이터 분석해줘" |
| **책임** | 데이터 유효성 확인, NCA 실행 조율, 결과 해석 및 요약, Lambda_z 승인 흐름 |
| **허용 도구** | `validate_dataset`, `run_nca`, `generate_report`, `compare_against_reference` |
| **에스컬레이션** | BLOQ > 30% 또는 Lambda_z 추정 불가 → 사용자에게 명시적 정책 결정 요청 |

NCA 분석의 주 실행자. 데이터 준비부터 최종 결과 테이블까지 단일 책임.

---

### 3.2 `pk-modeler`

| 항목 | 내용 |
|---|---|
| **트리거** | `/pk-fit` 호출 시 자동, 또는 "2구획 모델 적합해줘" 의도 감지 |
| **책임** | 모델 선택 권장, 초기 추정치 설정, 적합 실행, 수렴 진단, AIC/BIC 비교 |
| **허용 도구** | `validate_dataset`, `fit_pk_model`, `simulate`, `generate_report` |
| **에스컬레이션** | 수렴 실패 3회 → 초기 추정치 재검토 요청 또는 `model-selection` 스킬 호출 |

NCA 결과를 초기 추정치로 활용하는 것을 우선한다. 모델 미지정 시 `model-selection` 스킬을 통해 구조 선택을 안내한다.

---

### 3.3 `pd-modeler`

| 항목 | 내용 |
|---|---|
| **트리거** | `/pd-fit` 호출 시 자동 |
| **책임** | PK-PD 연결 구조 선택, sequential/simultaneous 모드 결정, hysteresis 진단 |
| **허용 도구** | `fit_pd_model`, `simulate`, `generate_report` |
| **에스컬레이션** | hysteresis 루프 감지 → effect compartment 모델 전환 제안 |

---

### 3.4 `report-writer`

| 항목 | 내용 |
|---|---|
| **트리거** | `/report` 호출 시 자동 |
| **책임** | 분석 결과 내러티브 작성, 파라미터 표 서식화, 결론 문장 생성 |
| **허용 도구** | `generate_report` |
| **에스컬레이션** | 없음. 순수 출력 에이전트 |

규제 제출용 언어 규범(FDA/EMA 가이드라인 용어)을 따른다. 계산하지 않고, 해석만 한다.

---

### 3.5 `data-curator`

| 항목 | 내용 |
|---|---|
| **트리거** | `/prep-data` 호출 시 자동, 또는 "데이터 정리해줘" 의도 감지 |
| **책임** | 컬럼 매핑, 단위 추론, BLOQ 패턴 감지, 이상치 플래깅 |
| **허용 도구** | `validate_dataset`, (v2) `import_sdtm` |
| **에스컬레이션** | 중복 행, 단조 시간 위반 → 자동 수정 전 사용자 확인 요청 |

---

## 4. 스킬

스킬은 에이전트가 내부적으로 호출하는 단계별 워크플로우 가이드다. 직접 `/skill-name`으로 호출할 수도 있다.

### 4.1 `nca-workflow`

**설명**: 단일 NCA 실행의 전체 단계를 구조화한다.

**활성화**: `nca-analyst`가 `/nca` 명령 처리 시 자동 호출.

**주요 단계**:
1. 파일 유형 감지 (CSV / Excel / XPT / SDTM)
2. `validate_dataset` → 컬럼 매핑 확인 프롬프트
3. 단위 확정 프롬프트 (미확정 시 분석 차단)
4. BLOQ 정책 확인 (기본값 또는 명시적 선택)
5. `run_nca` → Lambda_z 승인 인터랙션
6. 결과 요약 렌더링
7. 산출물 경로 목록 출력

---

### 4.2 `model-selection`

**설명**: 데이터 특성 기반으로 최적 구획 모델 구조를 추천한다.

**활성화**: `pk-modeler`가 `--model` 플래그 없이 호출되거나, "어떤 모델을 써야 해?" 질문 감지 시.

**주요 단계**:
1. 투여 경로 파악 (IV bolus / infusion / 경구)
2. NCA에서 double-peak, 이차 흡수 패턴 여부 확인
3. 1-구획부터 시작, AIC/BIC 기준으로 구획 수 증가 권장
4. 각 모델 후보를 표로 비교 (AIC, BIC, 수렴 여부, 파라미터 불확도)

---

### 4.3 `diagnostics`

**설명**: 구획 모델 적합 후 goodness-of-fit 체계적 평가.

**활성화**: `/diagnose` 명령, 또는 `pk-modeler`가 적합 완료 후 자동 호출.

**주요 단계**:
1. Observed vs Individual Predicted, Observed vs Population Predicted 플롯
2. Conditional Weighted Residuals (CWRES) vs time, vs pred
3. QQ-plot for normality
4. 수렴 조건 확인 (gradient, condition number)
5. 이상치 대상자 플래깅 (|CWRES| > 4)

---

### 4.4 `regulatory-validation`

**설명**: 분석 결과가 규제 기관 제출 기준을 충족하는지 자가 점검한다.

**활성화**: `/report` 명령, 또는 사용자가 "제출용으로 검토해줘" 요청 시.

**주요 단계**:
1. Lambda_z Adj R² ≥ 0.85, Span ratio ≥ 1.5 확인
2. AUC0-inf 외삽 비율 ≤ 20% 확인
3. BLOQ 처리 정책이 SOP에 명시된 방법인지 확인
4. 모든 대상자에 일관된 옵션 적용 여부 확인
5. 체크리스트를 audit.md에 추가

---

### 4.5 `cdisc-mapping` (v2.0)

**설명**: SDTM PC/EX 도메인 입력 및 ADaM ADPC/ADPP 도메인 출력 매핑.

**활성화**: `/prep-data --cdisc-sdtm` 또는 v2 환경에서 `.sas7bdat` / Define-XML 감지 시.

**주요 단계**:
1. SDTM `PCTESTCD`, `PCSTRESU`, `VISITNUM` → 내부 스키마 매핑
2. `import_sdtm` 호출
3. 분석 완료 후 `export_adam` → ADPC / ADPP 생성
4. OpenCDISC validator 호환 여부 확인

---

### 4.6 `audit-trail` (v2.0)

**설명**: 21 CFR Part 11 요건에 맞는 감사 추적 생성 및 전자서명 흐름.

**활성화**: v2 환경에서 분석 완료 또는 `sign_record` 요청 시.

**주요 단계**:
1. 분석 완료 → append-only audit chain 기록
2. `sign_record` 호출 → TOTP 인증 → Ed25519 서명
3. `lock_run` 호출 → WORM 스토리지 기록
4. 서명 manifest 출력 (who / what / when / meaning)

---

## 5. 인터랙티브 프롬프트

### 5.1 단위 확인 프롬프트

데이터 로드 직후. 단위가 확정되지 않으면 분석이 차단된다.

```text
┌─ 단위 확인 (필수) ─────────────────────────────────────────────┐
│ 파일: study001.csv                                             │
│                                                               │
│ 자동 감지된 단위:                                               │
│   농도 (conc)   →  ng/mL  ← 헤더 "ng/mL" 에서 추론            │
│   시간 (time)   →  hr     ← 값 범위 0–24 에서 추론             │
│   투여량 (dose) →  mg     ← 미감지. 명시 필요                   │
│                                                               │
│ [Conc: ng/mL | Time: hr | Dose: ?]                           │
│                                                               │
│ 단위를 확인하십시오. 투여량 단위를 입력하세요 (예: mg, μg):      │
└───────────────────────────────────────────────────────────────┘
> mg

단위 확정: Conc=ng/mL, Time=hr, Dose=mg  →  계속합니다.
```

---

### 5.2 BLOQ 처리 정책 확인

BLOQ 값이 감지된 경우, 기본값이 아닌 정책을 사용할 때 확인.

```text
┌─ BLOQ 감지 ───────────────────────────────────────────────────┐
│ 대상자 S003: t=0.5h, t=1.0h → "<1.0 ng/mL" (LLOQ = 1.0)     │
│ 대상자 S007: t=0.5h         → "BLQ"                          │
│                                                               │
│ 현재 BLOQ 정책: WinNonlin 6.4 기본                            │
│   - 용량 전(pre-dose) BLOQ  → 0으로 처리                       │
│   - 첫 번째 Cmax 이후 BLOQ  → 0으로 처리                       │
│   - 마지막 양수값 이후 BLOQ  → 분석 제외                        │
│                                                               │
│ 정책 변경 [Y/n/show-options]?                                  │
└───────────────────────────────────────────────────────────────┘
> n

WinNonlin 6.4 기본 BLOQ 정책 적용.  →  계속합니다.
```

BLOQ 정책 상세는 [03-algorithms/04-bloq-handling.md](03-algorithms/04-bloq-handling.md) 참조.

---

### 5.3 Lambda_z 회귀 창 승인

각 대상자별로 Lambda_z 선택 결과를 표시하고 승인을 받는다. 알고리즘 상세는 [03-algorithms/03-lambda-z-selection.md](03-algorithms/03-lambda-z-selection.md) 참조.

```text
┌─ Lambda_z 선택 — Subject S001 ────────────────────────────────┐
│ Method:       Best Fit (WinNonlin 6.4)                        │
│ Window:       8.0 → 24.0 h  (4 points)                       │
│ Lambda_z:     0.0826 1/h                                      │
│ t½:           8.39 h                                          │
│ Adj R²:       0.9943                                          │
│ Span ratio:   1.91  (OK)                                      │
│                                                               │
│ 선택된 포인트:                                                  │
│   ✔ t= 8.0 h   C= 42.1 ng/mL                                 │
│   ✔ t=12.0 h   C= 30.3 ng/mL                                 │
│   ✔ t=18.0 h   C= 18.7 ng/mL                                 │
│   ✔ t=24.0 h   C= 11.4 ng/mL                                 │
│                                                               │
│ 회귀 플롯 → runs/2026-05-25-001/lambda_z_S001.png             │
│                                                               │
│ 승인? [Y/n/edit]                                               │
└───────────────────────────────────────────────────────────────┘
```

`edit` 선택 시 시간 범위 수동 입력:
```text
시작 시간 (h): 12
종료 시간 (h): 24
→ Manual 선택: t=12.0–24.0, Lambda_z=0.0791, t½=8.77 h, Adj R²=0.9912
승인? [Y/n]
```

다대상자 분석에서 12명 전체를 개별 승인하지 않으려면 `--no-interactive` 또는 아래 명령:
```text
> Y (all remaining)   # 나머지 대상자 전체 자동 승인
```

---

## 6. 출력 구조

### 6.1 터미널 출력 (요약)

분석 완료 시 터미널에 표시되는 내용:

- 대상자 수, 버전, 실행 ID
- 핵심 파라미터 기하평균 ± 기하CV%
- 경고 플래그 목록 (Span ratio, Adj R², 외삽 비율)
- 산출물 경로 목록

### 6.2 디스크 산출물

모든 실행은 `runs/<run_id>/` 디렉터리에 다음을 생성한다.

| 파일 | 내용 | 항상 생성 |
|---|---|---|
| `audit.md` | 사람 읽기용 감사 로그 (입력 해시, 옵션, 단계별 결정) | v0.1+ |
| `audit.json` | JSON-of-record (기계 읽기용) | v0.1+ |
| `nca_script.py` | 분석 재현 가능 Python 스크립트 | v0.1+ |
| `results.csv` | 파라미터 테이블 (대상자 × 파라미터) | v0.1+ |
| `lambda_z_<subj>.png` | 대상자별 Lambda_z 회귀 플롯 | v0.1+ |
| `pk_plot_<subj>.png` | 선형/로그 농도-시간 플롯 | v0.1+ |
| `report.html` | WinNonlin 스타일 HTML 리포트 | v0.5+ |
| `report.pdf` | PDF 리포트 | v0.5+ |
| `validation_diff.json` | PKNCA/NonCompart 교차검증 결과 | v0.5+ |

### 6.3 브라우저 출력 (HTML 리포트)

`generate_report(format="html")` 실행 시 생성. 포함 내용:

- 스터디 메타데이터 헤더
- 대상자별 농도-시간 플롯 + Lambda_z 회귀 플롯
- WinNonlin 스타일 파라미터 테이블 (Subject × Period × Parameter)
- 기술통계 (N, mean, SD, geomean, geoCVpct, median, min, max)
- BLOQ 처리 요약 및 제외 목록
- 감사 추적 요약

---

## 7. 대화형 예시

### 7.1 더러운 CSV → NCA ("Messy Excel Demo")

```
사용자: 이 파일 NCA 돌려줘. 
        /nca data/raw_studyX.xlsx

pk-copilot: 파일을 읽는 중... (xlsx 감지)

  [validate_dataset 호출 중]

  ⚠ 컬럼 매핑 불확실:
    "Subject No."  → subject_id  (확신도 87%)
    "TIME_HR"      → time        (확신도 99%)
    "CONC (ng/ml)" → conc        (확신도 95%)
    "DOSEMG"       → dose        (확신도 72%)

  매핑을 수락하시겠습니까? [Y/n/수정]

사용자: Y

pk-copilot: 단위 확인:
  Conc: ng/mL | Time: hr | Dose: mg

  ⚠ t=0에서 3명 BLOQ 값 감지 (pre-dose zero 처리 예정)
  ⚠ Subject S004: t=2h 중복 행 감지 → 첫 번째 행 유지, 두 번째 제거

  계속합니까? [Y/n]

사용자: Y

  [run_nca 호출 중 — WinNonlin 6.4, linear_up_log_down]

  Lambda_z 선택 완료 (12명):
    S001: Best Fit, 4점, Adj R²=0.9943, t½=8.4h  ✔
    S002: Best Fit, 5점, Adj R²=0.9871, t½=7.9h  ✔
    ...
    S009: Best Fit, 3점, Adj R²=0.8412, t½=11.2h  ⚠ Adj R² < 0.85

  [승인? Y] → 자동 적용

  ┌─ NCA 완료 ──────────────────────────┐
  │ AUC0-t:   391 ng·h/mL (±22%)       │
  │ Cmax:     42.3 ng/mL  (±18%)       │
  │ t½:       8.6 h       (±12%)       │
  │                                    │
  │ ⚠ S009: Adj R² 낮음 (0.84)        │
  │                                    │
  │ 산출물: runs/2026-05-25-001/       │
  └────────────────────────────────────┘
```

---

### 7.2 Crossover BE 분석

```
사용자: 2×2 crossover BE 분석해줘. NCA는 이미 완료됨.
        /be runs/2026-05-25-001/results.csv --design 2x2-crossover --ref Reference

pk-copilot: [run_be 호출 중]
  디자인: 2×2 crossover, N=24 (12 per sequence)
  엔드포인트: AUC0-t, AUC0-inf, Cmax (log 변환)

  ┌─ BE 결과 ──────────────────────────────────────────┐
  │ 엔드포인트  GMR     90% CI          판정           │
  │ AUC0-t     1.032   [0.983, 1.083]  PASS          │
  │ AUC0-inf   1.028   [0.976, 1.082]  PASS          │
  │ Cmax       1.047   [0.991, 1.106]  PASS          │
  │                                                  │
  │ Period effect:  p=0.42 (유의하지 않음)            │
  │ Sequence effect: p=0.71 (유의하지 않음)           │
  │                                                  │
  │ 결론: 80–125% 기준 모두 통과. 생물학적으로 동등함.   │
  └──────────────────────────────────────────────────┘

  산출물: runs/2026-05-25-001/be_results.csv
           runs/2026-05-25-001/be_report.html
```

---

### 7.3 2-구획 PK 적합

```
사용자: 이 데이터 2구획으로 맞춰봐.
        /pk-fit data/study001.csv --model 2cmt-po --init-from-nca runs/2026-05-25-001

pk-copilot: NCA 결과에서 초기 추정치 추출 중...
  CL/F ≈ 2.42 L/h, Vz/F ≈ 29.6 L, Ka 추정 불가 → 1.0 1/h로 초기화

  [fit_pk_model 호출 중 — 2cmt-po, NLS, 1/y²]

  수렴 완료 (23 iterations)

  ┌─ 2-구획 PK 적합 결과 ────────────────────────────┐
  │ 파라미터      추정치   SE       %CV   95% CI      │
  │ CL/F  (L/h)   2.38    0.18    7.6%  [2.03, 2.73]│
  │ V2/F  (L)     18.4    2.1    11.4%  [14.3, 22.5]│
  │ Q/F   (L/h)   1.12    0.31   27.7%  [0.51, 1.73]│
  │ V3/F  (L)     43.2    8.7    20.1%  [26.1, 60.3]│
  │ Ka    (1/h)   1.43    0.22   15.4%  [1.00, 1.86]│
  │                                                  │
  │ AIC: 312.4   BIC: 325.1   OFV: 298.4            │
  │ 수렴: 정상 (gradient < 1e-6)                     │
  │                                                  │
  │ 1-구획 AIC: 334.8 → 2-구획이 더 우수             │
  │                                                  │
  │ 진단 플롯: runs/2026-05-25-002/diagnostics/      │
  └──────────────────────────────────────────────────┘

  /diagnose --run 2026-05-25-002  로 상세 진단 가능합니다.
```

---

## 8. 설정 파일 (전문가 모드)

프로젝트 루트에 `nca_config.yaml`을 두면 플래그 없이 전문가 설정이 적용된다.

```yaml
# nca_config.yaml — pk-copilot 전문가 설정 예시
version: "1.0"

defaults:
  winnonlin_version: "6.4"          # 5.3 | 6.4 | 8.3
  auc_method: linear_up_log_down    # linear_trapezoidal | linear_up_log_down
  lambda_z_method: best_fit         # best_fit | adj_r2 | manual
  bloq_policy: version_default      # version_default | m1 | m2 | m3 | m5 | m6 | m7
  interactive: true                 # false = headless

lambda_z:
  min_points: 3
  span_guard: true
  adj_r2_threshold: 0.85            # 이하 시 경고
  extrapolation_limit: 0.20         # AUC 외삽 비율 20% 초과 시 경고

output:
  audit_dir: "./pk_runs"
  formats: [html, csv]              # 기본 리포트 형식
  include_script: true
  include_validation_diff: false    # true = PKNCA 교차검증 자동 실행

# 대상자별 Lambda_z 수동 오버라이드 (이미 리뷰된 경우)
lambda_z_overrides:
  S009:
    method: manual
    t_start: 12.0
    t_end: 24.0

# v2: CDISC 설정
# cdisc:
#   input_format: sdtm
#   output_format: adam
#   controlled_terminology_version: "2024-09-27"
```

설정 우선순위: 명령줄 플래그 > `nca_config.yaml` > 빌트인 기본값.

---

## 9. 오류 UX

### 9.1 입력 검증 오류

MCP `validate_dataset`이 반환하는 오류는 위치와 수정 방법을 함께 표시한다.

```text
✗ 데이터 검증 실패

  [E001] 단위 미확정
    → 'conc' 컬럼: 단위를 감지하지 못했습니다.
    → 수정: 헤더를 "conc_ng_ml"로 변경하거나 --units conc=ng/mL 플래그 사용.

  [E002] 시간 단조성 위반
    → Subject S003, Row 14: t=8.0h → t=6.0h (감소)
    → 수정: 해당 행을 확인하거나 /prep-data로 전처리.

  [W001] BLOQ 비율 높음
    → Subject S011: 12개 시점 중 5개 BLOQ (41.7%)
    → 권장: BLOQ 처리 정책을 명시적으로 지정하세요.

분석이 차단되었습니다. 위 오류를 수정 후 다시 실행하세요.
```

### 9.2 수렴 실패 (구획 모델)

```text
⚠ 수렴 경고 — fit_pk_model

  모델: 2cmt-po
  상태: 최대 반복 횟수 도달 (500 iterations)
  최종 gradient norm: 0.0847  (기준: < 1e-6)

  가능한 원인:
    1. 초기 추정치가 실제값과 크게 다를 수 있습니다.
       → --init-from-nca 또는 초기값 직접 지정 권장
    2. 파라미터 identifiability 문제일 수 있습니다.
       → 1-구획부터 시도: /pk-fit --model 1cmt-po
    3. 데이터가 terminal phase를 충분히 포함하지 않을 수 있습니다.

  현재 추정치 (수렴 미보장):
    CL/F=2.81 V2/F=24.3 Q/F=3.41 V3/F=112.7 Ka=0.88

  계속합니까? [y/N]
```

### 9.3 Lambda_z 추정 불가

```text
✗ Lambda_z 추정 불가 — Subject S012

  이유: post-Tmax 구간에서 양의 기울기만 감지됨.
        최소 3개 포인트 기준 미충족 (사용 가능: 2개).

  선택지:
    1. manual: 시간 범위 직접 지정
    2. skip:   이 대상자의 t½, CL, Vz 파라미터를 NE(Not Estimable)로 처리
    3. flag:   계속하되 결과에 경고 플래그 표시

  선택 [1/2/3]:
```

---

## 🔗 관련 문서

- [03-algorithms/03-lambda-z-selection.md](03-algorithms/03-lambda-z-selection.md) — Lambda_z 선택 알고리즘 상세
- [03-algorithms/04-bloq-handling.md](03-algorithms/04-bloq-handling.md) — BLOQ 처리 정책
- [06-mcp-server.md](06-mcp-server.md) — MCP 도구 전체 스키마
- [02-roadmap.md](02-roadmap.md) — 버전별 명령 도입 일정
- [04-winnonlin-version-matrix.md](04-winnonlin-version-matrix.md) — 버전별 알고리즘 차이
