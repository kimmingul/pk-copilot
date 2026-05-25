# 11. Development Workflow — 개발자 가이드

> pk-copilot 플러그인에 기여하려는 개발자를 위한 환경 셋업, 워크플로우, 레시피 모음.

---

## 1. 개발 환경 셋업

### 1.1 Python 3.12 (uv 권장)

```bash
# uv 설치 (공식 권장)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 저장소 클론 및 의존성 설치
git clone https://github.com/your-org/pk-copilot.git
cd pk-copilot
uv sync --dev          # pyproject.toml + uv.lock 기준 고정 설치

# smoke test
uv run pytest tests/ -x -q
```

pyenv를 선호하면:

```bash
pyenv install 3.12.4
pyenv local 3.12.4
pip install -e ".[dev]"
```

### 1.2 R 4.4+ (검증 백엔드)

```bash
# macOS
brew install r

# R 패키지 복원 (renv.lock 기준)
Rscript -e "install.packages('renv'); renv::restore()"
```

R 백엔드가 없으면 r_backend 마커 테스트만 스킵됩니다. Python 단위 테스트는 정상 동작합니다.

### 1.3 pre-commit 훅 (선택)

```bash
pip install pre-commit
pre-commit install       # .git/hooks/pre-commit 설치
pre-commit run --all-files  # 전체 파일 한 번 실행
```

`.pre-commit-config.yaml`에는 ruff, mypy, 마지막 개행 검사가 포함되어 있습니다.

---

## 2. 저장소 구조 빠른 참조

> 상세 레이아웃은 [01-architecture.md](01-architecture.md) 참조.

| 경로 | 역할 |
|---|---|
| `src/pkplugin/version.py` | `WNVersion` enum + `DEFAULTS` 딕셔너리 (버전 분기 진입점) |
| `src/pkplugin/nca/engine.py` | `calculate_nca()` — NCA 메인 진입점 |
| `src/pkplugin/nca/auc.py` | AUC/AUMC 적분 알고리즘 |
| `src/pkplugin/schemas.py` | Pydantic v2 데이터 모델 (입출력 계약) |
| `src/pkplugin/audit.py` | JSON-of-record 생성 + audit log 방출 |
| `src/pkplugin/mcp_server.py` | MCP `@tool` 등록 진입점 |
| `scripts/run_r_pknca.R` | PKNCA 교차검증 실행기 |
| `scripts/golden_regen.py` | golden fixture 재생성 유틸 |
| `tests/golden/` | 버전별 golden fixture (winnonlin-5.3 / 6.4 / 8.3) |
| `docs/03-algorithms/` | 알고리즘 사양 문서 (단일 진실 공급원) |

---

## 3. 개발 워크플로우

1. **이슈 선택** — 트리아지 우선순위(15절)에 따라 이슈를 선택합니다.
2. **feature branch 생성** — `git checkout -b feat/nca-vss-iv`
3. **테스트 먼저 작성** (TDD):
   - `tests/golden/` 또는 `tests/test_nca_against_pknca.py`에 실패하는 테스트를 추가합니다.
   - `uv run pytest -k "test_new_feature" -x` 로 RED 확인.
4. **구현** — 코드 작성 후 GREEN 확인.
5. **타입·린트 검사**:
   ```bash
   uv run ruff check src/ tests/
   uv run ruff format src/ tests/
   uv run mypy --strict src/pkplugin/
   ```
6. **전체 테스트 통과 확인**:
   ```bash
   uv run pytest
   ```
7. **PR 생성** — 템플릿(14절)에 따라 작성.
8. **리뷰 → 머지** — 최소 1명 승인 + CI 통과 필수.

---

## 4. 새로운 NCA 파라미터 추가 절차

예: `Vss_IV` (IV bolus 전용 Vss) 신규 추가.

1. **알고리즘 사양 문서 추가**
   - `docs/03-algorithms/01-nca-parameters.md` 에 파라미터 정의, 수식, WinNonlin 매뉴얼 인용(섹션·페이지)을 기재합니다.

2. **버전 매트릭스 갱신** (버전 간 차이가 있을 경우)
   - `docs/04-winnonlin-version-matrix.md` 의 해당 표에 행 추가.
   - 출처 매뉴얼 페이지를 `docs/04-winnonlin-version-matrix.trace.csv` 에도 기록합니다.

3. **계산 코드 작성** — `src/pkplugin/nca/engine.py`
   ```python
   from pkplugin.version import WNVersion, DEFAULTS

   def calculate_nca(data: NCAInput, version: WNVersion = WNVersion.V6_4) -> NCAResult:
       cfg = DEFAULTS[version]
       # ... 기존 파라미터 계산 ...
       result.vss_iv = _calc_vss_iv(data, cfg) if data.route == "iv_bolus" else None
       return result

   def _calc_vss_iv(data: NCAInput, cfg: dict) -> float:
       """
       Vss for IV bolus: CL * MRT.

       Refs:
       - Phoenix WinNonlin 6.4 User's Guide §7.4.1 (p. 158)
       - WinNonlin 8.3 §8.4.1 (p. 172)

       Args:
           data: NCA input with aumc, aucinf, cl
           cfg: version-resolved config from DEFAULTS
       """
       return data.cl * data.mrt
   ```
   - 반드시 `winnonlin_version`을 받아 `DEFAULTS`에서 버전별 설정을 참조합니다.
   - 단위 변환은 절대 이 함수에서 수행하지 않습니다 (ingest 레이어 책임).

4. **golden fixture 추가** — `tests/golden/winnonlin-6.4/`
   ```
   tests/golden/winnonlin-6.4/
   ├── vss_iv_input.csv
   └── vss_iv_expected.json
   ```

5. **PKNCA 비교 테스트 추가** — `tests/test_nca_against_pknca.py`
   ```python
   @pytest.mark.golden
   def test_vss_iv_matches_pknca(theophylline_iv):
       result = calculate_nca(theophylline_iv, version=WNVersion.V6_4)
       pknca_ref = load_golden("winnonlin-6.4/vss_iv_expected.json")
       assert abs(result.vss_iv - pknca_ref["vss_iv"]) / pknca_ref["vss_iv"] < 1e-6
   ```

6. **JSON-of-record 스키마 갱신** — `src/pkplugin/schemas.py` 의 `NCAResult` 모델에 필드 추가.

7. **audit log 메시지 추가** — `src/pkplugin/audit.py`
   ```python
   emit_audit_event(
       action="nca.vss_iv.calculated",
       value=result.vss_iv,
       version=version,
       algorithm="cl_times_mrt",
       manual_ref="WinNonlin 6.4 §7.4.1 p.158",
   )
   ```

---

## 5. 새로운 WinNonlin 버전 호환 추가 절차

예: WinNonlin 9.0 지원 추가.

1. **`WNVersion` enum 확장** — `src/pkplugin/version.py`
   ```python
   class WNVersion(str, Enum):
       V5_3 = "5.3"
       V6_4 = "6.4"
       V8_3 = "8.3"
       V9_0 = "9.0"          # 신규
       LATEST = "compat-latest"
   ```

2. **`DEFAULTS` 딕셔너리 매트릭스 추가**
   ```python
   DEFAULTS[WNVersion.V9_0] = {
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
       # 9.0 전용 변경 사항 기재
   }
   ```

3. **golden fixture 디렉터리 추가**
   ```
   tests/golden/winnonlin-9.0/
   ├── theophylline_expected.json
   └── indomethacin_expected.json
   ```
   매뉴얼 예제 또는 WinNonlin 9.0 실제 출력값으로 채웁니다.

4. **버전 매트릭스 문서 갱신** — `docs/04-winnonlin-version-matrix.md` 모든 표에 "9.0" 열 추가 및 차이 기록.

---

## 6. 테스트 실행

| 명령 | 대상 | 속도 |
|---|---|---|
| `uv run pytest` | 전체 단위 테스트 | 빠름 (~30초) |
| `uv run pytest -m golden` | golden 회귀 테스트 | 보통 (~2분) |
| `uv run pytest -m property` | Hypothesis 속성 기반 테스트 | 보통 (~3분) |
| `uv run pytest -m r_backend` | R subprocess 교차검증 | 느림 (~10분) |
| `uv run pytest --validation-report` | 전체 실행 후 `validation_diff.json` 생성 | 가장 느림 |

```bash
# 특정 파라미터 관련 테스트만 빠르게
uv run pytest -k "auc" -x

# 전체 검증 리포트 생성 (릴리즈 전 필수)
uv run pytest --validation-report
cat validation_diff.json | python -m json.tool | head -60
```

---

## 7. 코드 스타일

- **Linter / Formatter**: `ruff` — `pyproject.toml` 의 `[tool.ruff]` 설정 준수.
- **Type checker**: `mypy --strict` (`src/pkplugin/` 전체, `Any` 사용 금지).
- **데이터 모델**: Pydantic v2 strict mode — 모든 필드에 타입 어노테이션 필수.
- **단위 변환 금지**: 알고리즘 함수 내부에서 단위를 변환하지 않습니다. 단위 정규화는 `ingest.py` 레이어에서 처리합니다.
- **`console.log` / `print` 금지**: 프로덕션 코드에 `print()` 사용 금지. 로깅은 `logging` 모듈 또는 audit 레이어를 사용합니다.

```bash
# 린트 + 포맷 + 타입 일괄 검사
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy --strict src/pkplugin/
```

---

## 8. 알고리즘 함수 Docstring 표준

모든 알고리즘 함수는 아래 형식을 **반드시** 따릅니다. WinNonlin 매뉴얼 인용이 없으면 PR을 승인하지 않습니다.

```python
def auc_linear_up_log_down(t, c, version="6.4"):
    """
    AUC by linear-up/log-down trapezoidal rule.

    Refs:
    - Phoenix WinNonlin 6.4 User's Guide §7.2.3 (p. 142)
    - WinNonlin 5.3 §6.1.4 (p. 118)
    - WinNonlin 8.3 §8.3.1 (p. 165)

    Args:
        t: monotonically increasing time array
        c: concentration array (BLOQ pre-resolved)
        version: WinNonlin compat version
    """
```

- `Refs` 블록: 관련 **모든** WinNonlin 버전의 섹션·페이지를 열거합니다.
- `Args`: 각 파라미터에 단위·전제조건을 명시합니다 (e.g. "BLOQ pre-resolved", "monotonically increasing").
- 버전별로 다르게 동작하는 경우 `Notes` 블록에 분기 설명을 추가합니다.

---

## 9. MCP 도구 추가 절차

1. `src/pkplugin/mcp_server.py` 에 `@tool` 데코레이터로 함수를 등록합니다.
   ```python
   from fastmcp import tool

   @tool
   def run_partial_auc(
       dataset: dict,
       t_start: float,
       t_end: float,
       winnonlin_version: str = "6.4",
   ) -> dict:
       """Compute partial AUC between t_start and t_end."""
       # JSON-serializable 입출력 강제
       result = calculate_partial_auc(...)
       emit_audit_event(action="mcp.run_partial_auc", ...)
       return result.model_dump()
   ```
2. 입출력은 JSON-serializable 타입만 사용합니다 (Pydantic 모델 → `.model_dump()` 변환).
3. 모든 도구 호출에 `emit_audit_event()` 를 추가합니다.
4. `docs/06-mcp-server.md` 의 도구 카탈로그 표를 업데이트합니다.
5. `tests/` 에 integration test를 추가합니다:
   ```bash
   uv run pytest tests/test_mcp_integration.py -k "partial_auc" -v
   ```

---

## 10. Audit Log 추가 절차

**언제 방출하는가**: MCP 도구 호출 시작/완료, 알고리즘 선택·분기, BLOQ 처리 결정, Lambda_z 포함/제외 포인트, 사용자 승인 이벤트.

**필수 필드**:

| 필드 | 설명 | 예시 |
|---|---|---|
| `action` | 점 구분 이벤트명 | `"nca.lambda_z.selected"` |
| `run_id` | 분석 실행 UUID | `"2026-05-25-001"` |
| `timestamp` | ISO 8601 UTC | `"2026-05-25T09:00:00Z"` |
| `version` | WinNonlin compat 버전 | `"6.4"` |
| `algorithm` | 사용한 알고리즘 식별자 | `"best_fit_adj_r2"` |
| `value` | 결과값 (선택) | `0.0234` |
| `manual_ref` | 매뉴얼 인용 | `"WinNonlin 6.4 §7.3.1 p.148"` |

```python
from pkplugin.audit import emit_audit_event

emit_audit_event(
    action="nca.auc.calculated",
    run_id=run_id,
    algorithm="linear_up_log_down",
    value={"auc0t": 42.1, "aucinf_obs": 48.5},
    version=version,
    manual_ref="WinNonlin 6.4 §7.2.3 p.142",
)
```

---

## 11. R Backend 검증 호출

```bash
# 단독 실행
Rscript --vanilla scripts/run_r_pknca.R \
  --input tests/fixtures/theophylline.csv \
  --output /tmp/pknca_out.json \
  --subject_col "ID" --time_col "time" --conc_col "conc" \
  --dose 320 --dose_unit "mg" --conc_unit "mg/L" --time_unit "hr"
```

**기대 출력 형식** (`/tmp/pknca_out.json`):
```json
{
  "subject": "1",
  "cmax": 8.33,
  "tmax": 1.0,
  "aucinf_obs": 102.7,
  "lambda_z": 0.0485,
  "half_life": 14.3,
  "pknca_version": "0.10.2",
  "r_version": "4.4.1"
}
```

**오류 처리**: 스크립트가 비정상 종료(exit code != 0)하면 `RBackendError`를 발생시키고, stderr를 audit log에 기록합니다. `renv::restore()` 가 선행되지 않으면 패키지 미설치 오류가 납니다.

---

## 12. 릴리즈 절차

1. **SemVer 엄격 적용**:
   - 알고리즘 기본값 변경 → 마이너 버전 업 (e.g. `0.1.0` → `0.2.0`)
   - Breaking API 변경 → 메이저 버전 업
   - 버그 픽스 → 패치 버전 업

2. **CHANGELOG.md 작성** — 알고리즘 기본값 변경 시 반드시 `"Behavior change (version-aware)"` 섹션 포함:
   ```markdown
   ## [0.2.0] - 2026-06-01
   ### Behavior change (version-aware)
   - WinNonlin 5.3: AUC 기본값이 `linear`에서 `linear_up_log_down`으로 변경됨.
     `winnonlin_version="5.3"` 옵션으로 이전 동작 유지 가능.
   ```

3. **검증 리포트 생성**:
   ```bash
   uv run pytest --validation-report
   # → validation_diff.json 생성
   ```
   `validation_diff.json` 을 GitHub Release artifact로 첨부합니다.

4. **서명된 릴리즈 아티팩트 생성**:
   ```bash
   # sigstore 서명
   python -m build
   cosign sign dist/pk_copilot-0.2.0-py3-none-any.whl

   # SBOM 생성 (CycloneDX)
   cyclonedx-py environment -o sbom.json
   ```

5. **GitHub Release 게시** + Claude Marketplace 동시 게시:
   - Release notes에 `validation_diff.json`, SBOM, sigstore 서명 파일 첨부.
   - `plugin.json` 버전 필드를 릴리즈 버전과 동기화합니다.

---

## 13. CI/CD 파이프라인

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --dev
      - run: uv run ruff check src/ tests/
      - run: uv run ruff format --check src/ tests/
      - run: uv run mypy --strict src/pkplugin/

  test-unit:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --dev
      - run: uv run pytest -m "not golden and not property and not r_backend" -q

  test-golden:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --dev
      - run: uv run pytest -m golden -v

  test-property:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --dev
      - run: uv run pytest -m property -v

  r-cross-validation:
    runs-on: ubuntu-latest
    needs: test-unit
    steps:
      - uses: actions/checkout@v4
      - uses: r-lib/actions/setup-r@v2
        with:
          r-version: "4.4"
      - run: Rscript -e "install.packages('renv'); renv::restore()"
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --dev
      - run: uv run pytest -m r_backend -v

  build-artifacts:
    runs-on: ubuntu-latest
    needs: [test-golden, r-cross-validation]
    if: startsWith(github.ref, 'refs/tags/v')
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --dev
      - run: uv run pytest --validation-report
      - run: python -m build
      - uses: actions/upload-artifact@v4
        with:
          name: release-artifacts
          path: |
            dist/
            validation_diff.json
```

---

## 14. Issue / PR 템플릿

### Bug Report 필수 항목

- **데이터 샘플** (익명화): 재현에 필요한 최소 CSV (subject_id 해시 처리).
- **기대 결과 vs 실제 결과**: WinNonlin 출력 캡처 또는 PKNCA 결과.
- **WinNonlin 버전**: 어느 버전 기준으로 재현했는가 (5.3 / 6.4 / 8.3).
- **pk-copilot 버전 + 호출 코드 스니펫**.

### Algorithm Change PR 필수 항목

- **매뉴얼 페이지 인용**: 어느 매뉴얼 어느 섹션에 근거했는가.
- **영향받는 WinNonlin 버전**: 변경이 어느 버전에 해당하는가.
- **회귀 테스트 추가 여부**: `tests/golden/` 또는 `test_nca_against_pknca.py` 에 테스트가 추가되었는가.
- **CHANGELOG.md 갱신 여부**: 기본값 변경이면 "Behavior change" 섹션 포함.

---

## 15. 이슈 트리아지 우선순위

| 우선순위 | 범주 | 기준 | 대응 목표 |
|---|---|---|---|
| **P0** | 정확성 | NCA/BE 결과 오류, PKNCA 동치성 깨짐 | 24시간 이내 핫픽스 |
| **P1** | 기능 | 새 알고리즘 추가, 새 WinNonlin 버전 지원 | 다음 마이너 릴리즈 |
| **P2** | UX / 문서 | 명령어 UX 개선, 문서 누락 | 다음 패치 또는 마이너 |
| **P3** | Nice-to-have | 성능 최적화, 플롯 개선, 코드 정리 | 백로그 |

P0 이슈는 별도 브랜치 `hotfix/xxx` 에서 작업하고, main 브랜치에 직접 머지 후 즉시 패치 버전을 릴리즈합니다.

---

## 16. 문서 기여 규칙

- **알고리즘 변경 시**: `docs/03-algorithms/` 해당 파일을 **코드와 동일 PR** 에서 업데이트합니다. 문서 없는 알고리즘 PR은 머지하지 않습니다.
- **버전 차이 발견 시**: `docs/04-winnonlin-version-matrix.md` 를 즉시 업데이트하고 `trace.csv` 에 매뉴얼 페이지를 기록합니다.
- **v2 규제 관련 변경 시**: `docs/10-21cfr-part11.md` 의 트레이서빌리티 매트릭스를 갱신합니다.
- **MCP 도구 추가 시**: `docs/06-mcp-server.md` 의 도구 카탈로그를 업데이트합니다.

---

## 17. 외부 기여자 가이드

### 라이선스

이 프로젝트는 **Apache-2.0** 라이선스로 배포됩니다. 기여한 코드는 동일 라이선스로 공개됩니다.

### CLA (Contributor License Agreement)

첫 PR 제출 시 CLA-bot이 자동으로 CLA 서명을 요청합니다. 서명 없이는 PR을 머지하지 않습니다.

### DCO (Developer Certificate of Origin)

모든 커밋에 DCO sign-off가 필요합니다:

```bash
git commit -s -m "feat(nca): add Vss_IV parameter for IV bolus"
# → Signed-off-by: Your Name <your@email.com> 자동 추가
```

### 기여 흐름 요약

1. 이슈를 먼저 열고 (`[Proposal]` 레이블) 구현 방향을 논의합니다.
2. fork → feature branch → PR (템플릿 준수).
3. CI 통과 + 리뷰어 1명 승인 후 머지.
4. 알고리즘 관련 기여는 WinNonlin 매뉴얼 인용이 없으면 승인되지 않습니다.
