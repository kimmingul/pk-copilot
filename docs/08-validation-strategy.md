# 08. Validation Strategy (검증 전략)

> **연관 문서**: [02-roadmap.md](02-roadmap.md) | [04-winnonlin-version-matrix.md](04-winnonlin-version-matrix.md) | [10-21cfr-part11.md](10-21cfr-part11.md)

---

## 1. 검증 철학 — "검증 가능"과 "검증된"의 구분

pk-copilot은 버전에 따라 서로 다른 수준의 품질 주장을 합니다. 이 구분을 명확히 하는 것이 사용자·개발자 모두에게 중요합니다.

| 구분 | v1.x | v2.0 |
|---|---|---|
| 용어 | **검증 가능 시스템** (Verifiable System) | **검증된 시스템** (Validated System) |
| 의미 | 결과를 독립적으로 재현·비교할 수 있는 기반 제공 | GxP 품질 시스템 절차에 따라 공식 검증 완료 |
| 골든 테스트 | 제공됨 (자동화) | 제공됨 + 서명된 IQ/OQ/PQ 패키지 |
| 21 CFR Part 11 | 미주장 | 준수 |
| 오류 발생 시 책임 | 사용자 판단 | 추적 가능한 감사 추적 |
| 사용 권고 | 탐색적 분석, 내부 검토 | 규제 제출 (IND/NDA 등) |

> **v1.x에서 우리가 주장하지 않는 것**: "21 CFR Part 11 compliant", "validated software", "GxP-ready" — 이 표현은 v2.0 이후에만 사용합니다.

---

## 2. 세 겹의 테스트 구조 (Three Layers of Testing)

### 2.1 단위 테스트 (Unit Tests) — pytest

개별 알고리즘 함수를 독립적으로 검증합니다.

```
tests/
├── unit/
│   ├── test_auc.py            # AUC 적분 (linear / log-down / linear-up log-down)
│   ├── test_lambda_z.py       # Lambda_z 선택 알고리즘
│   ├── test_nca_params.py     # 전체 NCA 파라미터
│   ├── test_be.py             # BE GMR / 90% CI / TOST
│   ├── test_compartmental.py  # 1/2/3-구획 closed-form 및 ODE
│   └── test_bloq.py           # BLOQ 정책 분기
```

각 단위 테스트는:
- 입력/출력을 수식 수준에서 검증
- 경계값(BLOQ, 단일 포인트, 동점 Cmax) 명시 커버
- 실행 시간 < 100ms (CI에서 느린 테스트 격리)

### 2.2 속성 기반 테스트 (Property-Based Tests) — Hypothesis

알고리즘이 수학적 불변성을 만족하는지 무작위 입력으로 검증합니다.

```python
# tests/property/test_auc_properties.py
from hypothesis import given, settings
from hypothesis import strategies as st
import numpy as np

@given(
    doses=st.lists(st.floats(min_value=1.0, max_value=1000.0), min_size=2),
    times=st.lists(st.floats(min_value=0.1, max_value=48.0), min_size=8),
)
def test_auc_monotonic_in_dose_linear_pk(doses, times):
    """선형 PK에서 AUC는 Dose에 비례해야 한다 (linearity of exposure)."""
    ...

@given(times=st.permutations(list(range(1, 12))))
def test_auc_time_sort_invariance(times):
    """입력 행의 순서가 달라도 AUC 결과는 동일해야 한다."""
    ...

@given(n_points=st.integers(min_value=3, max_value=20))
def test_lambda_z_rsq_in_unit_interval(n_points):
    """Lambda_z 회귀의 Adj R²는 항상 [0, 1] 범위여야 한다."""
    ...
```

핵심 속성 목록:

| 속성 | 설명 | 알고리즘 |
|---|---|---|
| Dose-linearity | 선형 PK에서 AUC ∝ Dose | AUC |
| Time-sort invariance | 행 순서 무관 동일 결과 | AUC, NCA 전체 |
| AUC ≥ 0 | 음수 농도 없는 한 항상 양수 | AUC |
| t½ = ln(2)/λz | 항등식 | Lambda_z, t½ |
| Span_ratio ≥ 1 | 정의상 항상 성립 | Lambda_z |
| GMR ∈ (0, ∞) | 로그 변환 후 무한 수렴 없음 | BE |
| CI width → 0 as n → ∞ | 표본 증가 시 CI 수렴 | BE |

### 2.3 골든 / 회귀 테스트 (Golden Tests)

공인된 기준값(WinNonlin 출력, PKNCA 결과)과 bit-exact 또는 허용 오차 이내 일치를 확인합니다.

```
tests/
└── golden/
    ├── pknca/
    │   ├── theophylline/          # PKNCA 내장 Theophylline 데이터셋
    │   └── indomethacin/          # PKNCA 내장 Indomethacin 데이터셋
    ├── fda-be/
    │   └── 2x2-crossover/         # FDA BE guidance Appendix 예제
    ├── winnonlin-5.3/
    │   ├── nca-po-example/        # 5.3 매뉴얼 NCA 예제
    │   └── compartmental/         # 5.3 구획 예제
    ├── winnonlin-6.4/
    │   ├── nca-po-example/
    │   ├── nca-iv-example/
    │   ├── be-crossover/
    │   └── compartmental/
    ├── winnonlin-8.3/
    │   ├── nca-po-example/
    │   ├── nca-iv-example/
    │   └── compartmental/
    ├── synthetic/
    │   ├── 1cmt-iv-closed/        # closed-form vs ODE 동등성
    │   ├── 1cmt-po-closed/
    │   └── 2cmt-iv-closed/
    └── analytical/
        ├── bateman-equation/      # Bateman 해석해
        └── monoexponential/       # 단지수함수
```

각 골든 디렉터리는 다음을 포함합니다:

```
golden/pknca/theophylline/
├── input.csv          # 원본 데이터
├── expected.json      # 기준값 (WinNonlin / PKNCA 출력)
├── config.json        # NCAConfig / winnonlin_version 등 설정
├── tolerance.json     # 파라미터별 허용 오차
└── README.md          # 데이터 출처 및 기준값 생성 방법
```

---

## 3. 골든 데이터셋 매트릭스

| 데이터셋 | 출처 | 분석 범위 | 기준 도구 | 허용 오차 | 위치 |
|---|---|---|---|---|---|
| **Theophylline** (12명) | PKNCA R 패키지 내장 fixture | NCA (PO): AUClast, AUCinf, Cmax, t½, λz, CL/F, Vz/F | PKNCA 0.10+ | 상대오차 ≤ 1e-6 | `tests/golden/pknca/theophylline/` |
| **Indomethacin** | PKNCA R 패키지 내장 fixture | NCA (IV): AUClast, AUCinf, MRT, Vss, CL | PKNCA 0.10+ | 상대오차 ≤ 1e-6 | `tests/golden/pknca/indomethacin/` |
| **FDA BE 2×2** | FDA BE guidance (2001) Appendix | BE: GMR, 90% CI, TOST, Within-Subject CV | SAS PROC MIXED | GMR ±0.01%, CI ±0.01% | `tests/golden/fda-be/2x2-crossover/` |
| **WinNonlin 5.3 NCA** | WinNonlin 5.3 매뉴얼 예제 | NCA (5.3 기본값): AUC linear, C0 observed | WinNonlin 5.3 출력 | 상대오차 ≤ 1e-5 | `tests/golden/winnonlin-5.3/nca-po-example/` |
| **WinNonlin 6.4 NCA** | Phoenix WinNonlin 6.4 User's Guide §7 | NCA (PO+IV): 전체 파라미터 | WinNonlin 6.4 출력 | 상대오차 ≤ 1e-6 | `tests/golden/winnonlin-6.4/nca-po-example/` |
| **WinNonlin 8.3 NCA** | WinNonlin 8.3 User's Guide 예제 | NCA (PO+IV+SS): 전체 파라미터 | WinNonlin 8.3 출력 | 상대오차 ≤ 1e-6 | `tests/golden/winnonlin-8.3/nca-po-example/` |
| **Synthetic 1-cmt IV** | 해석해 (closed-form) | 1-cmt IV bolus: closed-form vs ODE | 수학적 동등성 | 절대오차 ≤ 1e-9 | `tests/golden/synthetic/1cmt-iv-closed/` |
| **Synthetic 1-cmt PO** | 해석해 (Bateman) | 1-cmt PO: Bateman 방정식 | 수학적 동등성 | 절대오차 ≤ 1e-9 | `tests/golden/synthetic/1cmt-po-closed/` |
| **WinNonlin 6.4 Comp** | Phoenix WinNonlin 6.4 User's Guide §10 | Compartmental: WinNonlin Model 1, 7, 11 (1-cmt IV, 2-cmt IV, 2-cmt PO) | WinNonlin 6.4 출력 | 파라미터 상대오차 ≤ 1e-4 (identifiability 한계) | `tests/golden/winnonlin-6.4/compartmental/` |
| **Bateman 해석해** | 이론적 해 | 1-cmt PO 대 Bateman 방정식 | 수학적 참값 | 상대오차 ≤ 1e-9 | `tests/golden/analytical/bateman-equation/` |

---

## 4. 교차 백엔드 검증 (Cross-Backend Validation)

### 4.1 검증 워크플로

```
pk-copilot (Python)
       │
       ├── compare_against_reference() MCP 도구
       │        │
       │        ├── R subprocess: PKNCA::pk.nca()
       │        │      (동일 데이터, 동일 설정)
       │        │
       │        └── R subprocess: NonCompart::nca()
       │
       └── validation_diff.json
```

각 릴리즈에서 `compare_against_reference()` 는 자동으로 실행되며, 결과는 `runs/<run_id>/diff.json`에 저장됩니다.

### 4.2 `compare_against_reference` MCP 도구 서명

```python
@mcp.tool()
async def compare_against_reference(
    dataset_path: str,
    config: NCAConfig,
    reference: Literal["pknca", "noncompart", "both"] = "both",
    tolerance: float = 1e-6,
) -> ValidationDiffResult:
    """
    pk-copilot 결과와 R 기준 백엔드를 비교하여 파라미터별 오차 보고서를 생성합니다.

    Returns:
        ValidationDiffResult: 파라미터별 absolute_error, relative_error, pass/fail
    """
```

### 4.3 `validation_diff.json` 스키마

```json
{
  "run_id": "nca-20260101-abc123",
  "timestamp": "2026-01-01T09:00:00Z",
  "pk_copilot_version": "1.0.0",
  "dataset": "theophylline",
  "reference_backend": "pknca",
  "reference_version": "PKNCA 0.11.0",
  "tolerance": 1e-6,
  "overall_pass": true,
  "parameters": [
    {
      "name": "AUClast",
      "subject": "Subject 1",
      "pk_copilot": 148.923,
      "reference": 148.923,
      "absolute_error": 0.000001,
      "relative_error": 6.7e-9,
      "pass": true
    }
  ],
  "summary": {
    "total_comparisons": 156,
    "passed": 156,
    "failed": 0,
    "max_relative_error": 8.2e-9
  }
}
```

---

## 5. 수치 정밀도 기준 (Numerical Precision Standards)

| 파라미터 / 수량 | 허용 오차 | 근거 |
|---|---|---|
| NCA 파라미터 (AUC, Cmax, t½ 등) | 상대오차 ≤ 1e-6 (6+ significant figures) | PKNCA / WinNonlin 비교 경험 |
| Lambda_z (λz) | 상대오차 ≤ 1e-9 | OLS 회귀 이중정밀도 한계 |
| BE 90% CI (GMR %) | ±0.01% (절대, percentage point) | SAS PROC MIXED 기준 |
| BE GMR | 상대오차 ≤ 1e-5 | log 변환 후 exp 역변환 오차 |
| 구획 파라미터 (V, CL, k 등) | 상대오차 ≤ 1e-3 (3+ significant figures) | 비선형 최적화 + identifiability 한계 |
| ODE solver (closed-form 비교) | 절대오차 ≤ 1e-9 | scipy solve_ivp rtol=1e-9 설정 |
| AIC / BIC | 절대오차 ≤ 0.01 | 정의 일치 확인 후 |
| Span_ratio | 절대오차 ≤ 1e-10 | 단순 산술 |

> **구획 파라미터 주의**: 모델이 poorly identifiable한 경우 (예: 2-cmt, 데이터 포인트 부족) 수치 최적화 결과는 시작값·solver 설정에 민감합니다. 이 경우 3 significant figures를 목표로 하고, condition number > 1000이면 경고를 출력합니다.

---

## 6. 지속적 검증 파이프라인 (Continuous Validation Pipeline)

### 6.1 CI 전략 (GitHub Actions)

```yaml
# .github/workflows/validation.yml
name: Validation Pipeline

on:
  pull_request:
    branches: [main, develop]
  release:
    types: [published]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: pytest tests/unit/ -v --tb=short

  property-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[dev]"
      - run: pytest tests/property/ -v --hypothesis-seed=0

  golden-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: r-lib/actions/setup-r@v2
      - run: |
          pip install -e ".[dev]"
          Rscript -e "install.packages(c('PKNCA', 'NonCompart'))"
      - run: pytest tests/golden/ -v --tb=long
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: golden-test-report
          path: reports/golden-*.json

  r-cross-validation:
    runs-on: ubuntu-latest
    needs: golden-tests
    steps:
      - uses: actions/checkout@v4
      - uses: r-lib/actions/setup-r@v2
      - run: |
          pip install -e ".[dev]"
          Rscript -e "install.packages(c('PKNCA', 'NonCompart'))"
      - run: python scripts/run_cross_validation.py --output reports/cross_validation.json
      - run: python scripts/check_diff_thresholds.py reports/cross_validation.json

  # 릴리즈 시만 실행
  full-validation-matrix:
    if: github.event_name == 'release'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: r-lib/actions/setup-r@v2
      - run: pip install -e ".[dev]"
      - run: python scripts/oq.py --full-matrix --sign --output reports/oq_report.json
      - uses: actions/upload-artifact@v4
        with:
          name: validation-report-${{ github.ref_name }}
          path: reports/
```

### 6.2 PR vs 릴리즈 실행 범위 요약

| 단계 | PR 시 | 릴리즈 시 |
|---|---|---|
| pytest 단위 테스트 | 전체 | 전체 |
| Hypothesis 속성 테스트 | 전체 | 전체 |
| 골든 테스트 (자동 데이터셋) | 전체 | 전체 |
| R PKNCA / NonCompart 교차검증 | 전체 | 전체 |
| 전체 골든 매트릭스 (WinNonlin) | 생략 | 실행 |
| 서명된 검증 보고서 | 생략 | 생성 |

---

## 7. IQ / OQ / PQ 패키지 (v1.x → v2.0)

GxP 환경에서 소프트웨어 검증은 세 단계 자격 확인(Qualification)으로 구성됩니다. pk-copilot은 v1.x부터 이 구조를 준비하고, v2.0에서 공식 문서화합니다.

### 7.1 IQ — Installation Qualification (설치 적격성 확인)

**목적**: pk-copilot이 올바르게 설치되었는지 확인합니다.

**실행자**: 사용자 / IT 관리자 (설치 직후)

**스크립트**: `scripts/iq.py`

```python
# scripts/iq.py 서명
def run_iq(output_path: str = "reports/iq_report.json") -> IQResult:
    """
    Installation Qualification 실행.

    확인 항목:
    - Python 버전 >= 3.11
    - 필수 패키지 버전 (scipy, numpy, statsmodels, lmfit 등)
    - R 설치 여부 및 버전
    - PKNCA, NonCompart R 패키지 설치 여부
    - subprocess 통신 테스트 (Python → R)
    - MCP 서버 기동 테스트
    - 파일시스템 쓰기 권한 (runs/ 디렉터리)

    Returns:
        IQResult: 항목별 pass/fail + 버전 스냅샷
    """
```

**산출물**: `reports/iq_report.json` — 환경 스냅샷, 타임스탬프, 설치자 서명란

### 7.2 OQ — Operational Qualification (운영 적격성 확인)

**목적**: pk-copilot이 의도한 대로 작동하는지 알려진 데이터셋으로 확인합니다.

**실행자**: 검증 담당자 (설치 후, 새 버전 배포 후)

**스크립트**: `scripts/oq.py`

```python
# scripts/oq.py 서명
def run_oq(
    dataset: Literal["theophylline", "indomethacin", "fda_be_2x2"] = "theophylline",
    output_path: str = "reports/oq_report.json",
    sign: bool = False,
) -> OQResult:
    """
    Operational Qualification 실행.

    절차:
    1. 지정된 골든 데이터셋 로드
    2. pk-copilot NCA/BE 분석 실행
    3. 저장된 기준값(expected.json)과 비교
    4. 모든 파라미터가 tolerance 이내인지 확인
    5. (sign=True) 결과에 타임스탬프 + 실행자 서명 첨부

    Returns:
        OQResult: 파라미터별 비교 + 전체 pass/fail
    """
```

**산출물**: `reports/oq_report.json` — 비교 결과, 통과 여부, 서명 (v2에서 Ed25519)

### 7.3 PQ — Performance Qualification (성능 적격성 확인)

**목적**: 사용자의 실제 하드웨어에서 전체 골든 매트릭스를 실행하여 결과를 확인합니다.

**실행자**: 최종 사용자 또는 검증 담당자 (배포 완료 후)

**스크립트**: `scripts/pq.py`

```python
# scripts/pq.py 서명
def run_pq(
    output_path: str = "reports/pq_report.json",
    include_winnonlin_examples: bool = True,
    sign: bool = False,
    signer_name: str = "",
    signer_role: str = "",
) -> PQResult:
    """
    Performance Qualification — 전체 골든 매트릭스 실행.

    포함 데이터셋:
    - Theophylline, Indomethacin (PKNCA)
    - FDA BE 2×2 crossover
    - WinNonlin 5.3 / 6.4 / 8.3 NCA 예제
    - WinNonlin 6.4 구획 모델 예제
    - Synthetic closed-form vs ODE
    - Bateman 해석해

    산출물:
    - reports/pq_report.json
    - reports/pq_summary.html  (서명란 포함)

    Returns:
        PQResult: 데이터셋별 결과 + 전체 통과 여부 + 서명 정보
    """
```

**산출물**: `reports/pq_report.json` + `reports/pq_summary.html` — 전체 매트릭스 결과, 서명자 이름/직책/날짜

### 7.4 IQ / OQ / PQ 요약

| 단계 | 실행 시점 | 실행자 | 주요 확인 | 산출물 |
|---|---|---|---|---|
| **IQ** | 설치 직후 | IT / 관리자 | Python, R, 패키지, MCP 서버 기동 | `iq_report.json` |
| **OQ** | 새 버전 배포 후 | 검증 담당자 | Theophylline NCA ≤ 1e-6 | `oq_report.json` |
| **PQ** | 배포 완료 후 | 최종 사용자 | 전체 골든 매트릭스 | `pq_report.json` + `pq_summary.html` |

---

## 8. GxP 검증 전략 (v2.0)

v2.0에서는 규제 제출 지원을 위해 추가 문서 패키지가 필요합니다.

### 8.1 필수 문서 목록

| 문서 | 약어 | 내용 | 담당 |
|---|---|---|---|
| User Requirements Specification | **URS** | 사용자가 소프트웨어에서 무엇을 필요로 하는가 | 제품팀 + 규제팀 |
| Functional Requirements Specification | **FRS** | 시스템이 어떤 기능을 제공해야 하는가 | 개발팀 |
| Design / Detail Specification | **DDS** | 기능을 어떻게 구현하는가 (알고리즘, 데이터 흐름) | 개발팀 |
| Validation Master Plan | **VMP** | 전체 검증 활동 계획 및 책임 | 품질팀 |
| IQ / OQ / PQ 프로토콜 + 보고서 | — | 각 Qualification 실행 증빙 | 검증 담당자 |
| Traceability Matrix | — | 요구사항 → 구현 → 테스트 → 결과 연결 | 품질팀 |

### 8.2 Traceability Matrix (추적성 매트릭스) 예시

| URS ID | 요구사항 | FRS ID | 구현 파일 | 테스트 ID | 골든 데이터셋 | 결과 |
|---|---|---|---|---|---|---|
| URS-NCA-01 | AUC_0-t를 linear-up/log-down으로 계산 | FRS-NCA-01 | `src/nca/auc.py` | `test_auc_linear_up_log_down` | Theophylline | Pass |
| URS-BE-02 | 2×2 crossover 90% CI를 Satterthwaite df로 계산 | FRS-BE-02 | `src/be/crossover.py` | `test_fda_be_example` | FDA BE 2×2 | Pass |
| URS-COMP-03 | 2-cmt IV bolus closed-form 지원 | FRS-COMP-01 | `src/comp/analytic.py` | `test_1cmt_iv_closed_form_eq_ode` | WinNonlin 6.4 Comp | Pass |

v2.0 전체 Traceability Matrix는 별도 파일 `docs/validation/traceability-matrix.csv`로 관리됩니다.

---

## 9. 회귀 감지 (Regression Detection)

### 9.1 알고리즘 변경 정책

알고리즘 기본값이 변경될 때는 반드시 다음 절차를 따릅니다:

1. **변경 전**: 현재 골든 테스트 전체 통과 확인
2. **변경 분리**: `winnonlin_version` 파라미터로 이전 동작 보존
3. **새 골든 파일**: 변경된 알고리즘의 새 기준값 추가
4. **CHANGELOG 기록**: "Behavior change (version-aware)" 섹션 강제 기재
5. **검증 diff**: 릴리즈 노트에 파라미터별 오차 변동 첨부

```python
# winnonlin_version 플래그로 이전 동작 보존 예시
result = run_nca(
    dataset=df,
    config=NCAConfig(
        winnonlin_version="5.3",   # 5.3 기본값 유지 (AUC linear, C0 observed)
    )
)
```

### 9.2 버전별 골든 디렉터리 분리

```
tests/golden/
├── winnonlin-5.3/    # 5.3 기본값으로 생성된 기준값
├── winnonlin-6.4/    # 6.4 기본값으로 생성된 기준값
└── winnonlin-8.3/    # 8.3 기본값으로 생성된 기준값
```

`winnonlin_version`이 변경되면 해당 버전 디렉터리의 골든 테스트만 영향을 받으며, 다른 버전의 테스트는 보호됩니다. 이로써 기본값 변경이 이전 분석에 영향을 주지 않음을 자동으로 감지합니다.

### 9.3 회귀 감지 시나리오

| 시나리오 | 감지 방법 | 조치 |
|---|---|---|
| AUC 적분 알고리즘 변경 | Theophylline 골든 테스트 실패 | CHANGELOG + 이전 버전 옵션 보존 |
| Lambda_z 선택 로직 변경 | λz / t½ 골든 비교 실패 | 이전 동작을 `lambda_z_method` 옵션으로 유지 |
| scipy 업그레이드로 ODE 결과 미세 변동 | synthetic 1-cmt 골든 테스트 실패 | 허용 오차 조정 또는 solver 고정 |
| statsmodels 업그레이드로 BE df 변동 | FDA BE 골든 테스트 실패 | df 계산 방식 옵션화 |

---

## 10. v1.x에서 명시적으로 주장하지 않는 것

v1.x는 강력한 검증 인프라를 갖추고 있지만, 다음은 **명시적으로 주장하지 않습니다**:

| 미주장 항목 | 이유 |
|---|---|
| "21 CFR Part 11 compliant" | 전자서명, 감사 추적, 접근 통제 등 기술적 통제 미완성 (v2.0 예정) |
| "Validated software" (GxP 의미) | VMP / URS / FRS / DDS / 공식 Traceability Matrix 미작성 |
| "Suitable for regulatory submission" | 사용자 조직의 SOP / 교육 기록 / 계정 관리 등 절차적 통제 미포함 |
| "Audit trail compliant" | append-only hash-chained audit trail 미구현 (v2.0 예정) |
| "popPK validated" | nlmixr2 래퍼 제공 예정이나 자체 popPK 구현 없음 |
| "PBPK / IVIVC capable" | 로드맵 외 범위 |

> v1.x의 올바른 사용법: 내부 검토, 탐색적 분석, WinNonlin 결과 재현 확인. 규제 제출용으로 사용할 경우 사용자 조직이 자체 검증 절차를 추가로 수행해야 합니다.

---

## 연관 문서

- [02-roadmap.md](02-roadmap.md) — v1.0 "Production" vs v2.0 "Regulated" 로드맵
- [04-winnonlin-version-matrix.md](04-winnonlin-version-matrix.md) — 버전별 알고리즘 차이 및 골든 테스트 분기
- [03-algorithms/01-nca-parameters.md](03-algorithms/01-nca-parameters.md) — NCA 파라미터 사전
- [03-algorithms/07-bioequivalence.md](03-algorithms/07-bioequivalence.md) — BE 검증 테스트
- [03-algorithms/08-compartmental-models.md](03-algorithms/08-compartmental-models.md) — 구획 모델 검증 테스트
- [10-21cfr-part11.md](10-21cfr-part11.md) — v2.0 21 CFR Part 11 계획
- [11-development-workflow.md](11-development-workflow.md) — 개발자 테스트 실행 가이드
