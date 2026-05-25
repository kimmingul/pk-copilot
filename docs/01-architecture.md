# 01. Architecture

## 설계 원칙

1. **LLM은 오케스트레이터, MCP가 계산 커널**
   Claude는 데이터 매핑·해석·보고서 작성을 담당하고, 모든 수치 계산은 결정론적 MCP 도구를 통해 수행합니다. LLM이 인-챗에서 Python을 실행하여 계산하는 패턴은 금지합니다.

2. **Python-first, R-validating**
   1차 계산 엔진은 Python (numpy/scipy/lmfit). R (PKNCA, NonCompart) 은 검증 모드에서 subprocess로 호출하여 교차검증.

3. **Version-Aware Algorithms**
   모든 알고리즘은 `winnonlin_version: "5.3" | "6.4" | "8.3" | "compat-latest"` 옵션으로 분기. 기본값은 사용자 선언 또는 6.4.

4. **Audit-First**
   모든 분석 실행은 JSON-of-record + 실행 가능 스크립트(.py / .R) + audit log (.md) 트리플을 산출.

---

## 📁 디렉터리 레이아웃

```
pk-copilot/
├── .claude-plugin/
│   └── plugin.json                       # 플러그인 매니페스트
├── .mcp.json                             # MCP 서버 등록
├── pyproject.toml                        # Python 의존성 (uv)
├── uv.lock                               # 고정 의존성
├── renv.lock                             # R 의존성 (검증 백엔드)
├── README.md
├── LICENSE                               # Apache-2.0
│
├── docs/                                 # ← 이 문서들
│
├── reference/                            # WinNonlin 매뉴얼 PDF (.gitignore)
│
├── commands/                             # 슬래시 명령어
│   ├── nca.md
│   ├── pk-fit.md
│   ├── pd-fit.md
│   ├── be.md
│   ├── prep-data.md
│   ├── diagnose.md
│   └── report.md
│
├── agents/                               # 전문 에이전트
│   ├── nca-analyst.md
│   ├── pk-modeler.md
│   ├── pd-modeler.md
│   ├── report-writer.md
│   └── data-curator.md
│
├── skills/                               # 워크플로우 스킬
│   ├── nca-workflow/SKILL.md
│   ├── model-selection/SKILL.md
│   ├── diagnostics/SKILL.md
│   ├── regulatory-validation/SKILL.md
│   ├── cdisc-mapping/SKILL.md            # v2
│   └── audit-trail/SKILL.md              # v2
│
├── hooks/
│   └── hooks.json                        # PreToolUse: 스키마/단위 검증
│
├── scripts/
│   ├── validate_study_design.py
│   ├── run_r_pknca.R                     # PKNCA 검증 실행
│   ├── run_r_noncompart.R                # NonCompart 검증 실행
│   └── golden_regen.py                   # golden fixture 재생성
│
├── src/pkplugin/
│   ├── __init__.py
│   ├── version.py                        # WinNonlin 호환 버전 enum
│   │
│   ├── schemas.py                        # Pydantic 데이터 모델
│   ├── units.py                          # 단위 시스템 (pint)
│   ├── ingest.py                         # CSV/Excel/XPT/CDISC 로더
│   ├── audit.py                          # JSON-of-record, audit log
│   │
│   ├── nca/
│   │   ├── engine.py                     # calculate_nca() 진입점
│   │   ├── auc.py                        # AUC/AUMC 적분
│   │   ├── lambda_z.py                   # 말단상 회귀
│   │   ├── bloq.py                       # BLOQ 처리 정책
│   │   ├── partial_auc.py
│   │   ├── steady_state.py
│   │   └── bioequivalence.py
│   │
│   ├── comp/                             # v0.3+
│   │   ├── models.py
│   │   ├── analytic.py                   # closed-form 1/2/3-cmt
│   │   ├── ode.py                        # solve_ivp
│   │   ├── fitting.py                    # NLS/MLE/lmfit
│   │   └── diagnostics.py
│   │
│   ├── pd/                               # v0.4+
│   │   ├── models.py
│   │   └── fitting.py
│   │
│   ├── report/
│   │   ├── tables.py                     # WinNonlin-스타일 파라미터 표
│   │   ├── plots.py                      # matplotlib / plotly
│   │   ├── pdf.py                        # reportlab
│   │   └── quarto.py                     # quarto 렌더링
│   │
│   ├── cdisc/                            # v2
│   │   ├── sdtm.py                       # PC/EX/DM 도메인
│   │   └── adam.py                       # ADPC/ADPP
│   │
│   ├── compliance/                       # v2
│   │   ├── part11.py                     # audit trail / e-sign
│   │   ├── access.py                     # RBAC
│   │   └── retention.py
│   │
│   └── mcp_server.py                     # MCP 도구 노출
│
└── tests/
    ├── fixtures/
    ├── golden/
    │   ├── theophylline/
    │   ├── indomethacin/
    │   ├── winnonlin-5.3/
    │   ├── winnonlin-6.4/
    │   └── winnonlin-8.3/
    ├── test_nca_against_pknca.py
    ├── test_nca_version_compat.py        # 버전별 동치성
    ├── test_be.py
    ├── test_compartmental_fit.py
    └── test_properties.py                # hypothesis 기반
```

---

## 🧩 컴포넌트 레이어

```
┌─────────────────────────────────────────────────────────────┐
│                        Claude Code Agent                     │
│                  (대화형 UI, 자연어 의도 해석)                  │
└───────────────────────┬─────────────────────────────────────┘
                        │ 슬래시 명령 / 에이전트 호출
                        ▼
┌─────────────────────────────────────────────────────────────┐
│        Commands / Agents / Skills (마크다운 사양)              │
│  /nca, /pk-fit, /be ...  ← LLM 가이드 + MCP 도구 호출 지침      │
└───────────────────────┬─────────────────────────────────────┘
                        │ MCP tool call
                        ▼
┌─────────────────────────────────────────────────────────────┐
│            MCP Server (pkplugin.mcp_server)                  │
│   validate_dataset / run_nca / run_be / fit_pk_model /       │
│   fit_pd_model / generate_report / compare_against_reference │
└───────────┬─────────────────────────────┬──────────────────┘
            ▼                             ▼
┌───────────────────────┐    ┌────────────────────────────────┐
│  Python Calc Kernel    │    │   R Validation Backend         │
│  (numpy/scipy/lmfit)   │◀──▶│   PKNCA / NonCompart / nlmixr2 │
│  - nca/auc/lambda_z    │    │   (subprocess + renv.lock)     │
│  - comp/analytic/ode   │    │                                │
│  - pd/models           │    │   교차검증 / golden-test         │
└───────────┬───────────┘    └────────────────────────────────┘
            ▼
┌─────────────────────────────────────────────────────────────┐
│           Audit Layer (audit.py)                             │
│  - JSON-of-record (입력 해시, 버전, 알고리즘, 결과)             │
│  - 실행 스크립트(.py/.R)                                       │
│  - audit.md (사람-읽기용 감사 로그)                            │
│  - [v2] e-signature, append-only chain                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔌 MCP 도구 카탈로그 (요약)

> 상세는 [06-mcp-server.md](06-mcp-server.md) 참조

| 도구 | 설명 | 도입 버전 |
|---|---|---|
| `validate_dataset` | 스키마/단위/스터디 디자인 검증 | v0.1 |
| `run_nca` | NCA 파라미터 계산 | v0.1 |
| `run_be` | BE 통계 (TOST, 90% CI, mixed model) | v0.2 |
| `fit_pk_model` | 1/2/3-구획 모델 적합 | v0.3 |
| `fit_pd_model` | PK/PD 연결 모델 적합 | v0.4 |
| `generate_report` | WinNonlin-스타일 PDF/HTML 리포트 | v0.5 |
| `compare_against_reference` | PKNCA/NonCompart 교차검증 | v0.5 |
| `import_sdtm` | CDISC SDTM PC/EX 도메인 임포트 | **v2.0** |
| `export_adam` | ADaM ADPC/ADPP 도메인 익스포트 | **v2.0** |
| `sign_record` | Part 11 전자서명 | **v2.0** |
| `lock_run` | 분석 finalize/lock | **v2.0** |

---

## 📦 의존성 스택

### Python (pyproject.toml)

```toml
[project]
name = "pk-copilot"
requires-python = ">=3.11,<3.14"
dependencies = [
  "numpy>=2.0,<3",
  "scipy>=1.13,<2",
  "pandas>=2.2,<3",
  "lmfit>=1.3,<2",
  "statsmodels>=0.14,<1",
  "pydantic>=2.7,<3",
  "pint>=0.24,<1",                 # 단위 시스템
  "matplotlib>=3.9,<4",
  "plotly>=5.22,<7",
  "reportlab>=4.2,<5",
  "openpyxl>=3.1,<4",
  "pyreadstat>=1.2,<2",            # SAS XPT
  "pyarrow>=17,<25",
  "fastmcp>=2.0,<3",               # MCP 서버
  "rich>=13,<15",                  # 터미널 UI
]

[project.optional-dependencies]
dev = ["pytest>=8", "hypothesis>=6", "ruff", "mypy"]
cdisc = ["pyreadstat", "python-dateutil"]  # v2
compliance = ["cryptography>=42"]           # v2 e-signature
```

### R (renv.lock — 검증 백엔드)

```text
PKNCA          (>= 0.10)
NonCompart     (>= 0.7)
nlmixr2        (>= 2.0)    # v0.3+ popPK 위임용
rxode2         (>= 2.0)
```

> **R 호출 정책**: `Rscript --vanilla` subprocess + `renv` 환경 고정. `rpy2`는 환경 충돌 잦아 미사용.

---

## 🔁 데이터 흐름 예시 (v0.1 NCA)

```
사용자: "이 CSV로 NCA 돌려줘. WinNonlin 6.4 기본값으로."
   ↓
/nca 명령 → nca-analyst 에이전트 호출
   ↓
[1] validate_dataset(file="raw.csv")
    → 컬럼 자동 매핑 제안: subject_id=ID, time=시간(hr), conc=농도(ng)
    → 단위 확인 프롬프트: [Conc: ng/mL, Time: hr, Dose: mg] (Y/n)?
    → 사용자 승인
   ↓
[2] run_nca(
      dataset=normalized,
      config={
        winnonlin_version: "6.4",
        auc_method: "linear_up_log_down",
        lambda_z_method: "best_fit",     # WinNonlin 6.4 기본
        bloq_policy: "default_6_4"
      }
    )
    → Lambda_z 선택 회귀 플롯 자동 표시 + 사용자 승인
    → 파라미터 표 반환
   ↓
[3] generate_report(run_id="2026-05-25-001", format="html")
    → audit.md / nca_script.py / results.csv / report.html 4종 산출
```

---

---

## 🔀 Execution Mode Boundary

### 두 계층 아키텍처

pk-copilot은 LLM 오케스트레이션 계층과 deterministic kernel을 명확히 분리합니다.
이 분리가 "Part 11-enabling" 주장의 핵심 근거입니다.

```
사용자 (자연어 입력)
        │
        ▼
┌────────────────────────────────────────────────────────┐
│  LLM 오케스트레이션 계층  [EXPLORATORY]                  │
│                                                        │
│  - 자연어 의도 해석                                      │
│  - 데이터 컬럼 매핑 제안                                  │
│  - 모델 추천, 파라미터 범위 제안                           │
│  - 보고서 내러티브 초안                                   │
│                                                        │
│  ⚠ 숫자 계산 수행 금지  ⚠ GxP audit chain 미생성         │
│  Audit: LLM transcript log (non-GxP, exploratory)      │
└───────────────────────┬────────────────────────────────┘
                        │
                        │  사용자 승인 (명시적)
                        │  ← controlled mode: 이 승인이 audit chain에 기록됨
                        ▼
┌────────────────────────────────────────────────────────┐
│  Deterministic Kernel  [CONTROLLED CANDIDATE]          │
│                                                        │
│  - numpy / scipy / PKNCA-compatible 계산               │
│  - 동일 입력 해시 → 동일 수치 결과 보장                   │
│  - JSON-of-record + 실행 스크립트 자동 생성               │
│                                                        │
│  Audit: HMAC hash-chained execution record             │
│         (GxP candidate — customer QMS 하에서 사용 가능) │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│  Audit Chain (controlled mode only)                    │
│                                                        │
│  - Append-only JSONL                                   │
│  - HMAC-SHA256 per entry                               │
│  - SHA-256 hash chain (prev_hash → this_hash)          │
│  - Ed25519 e-signature (sign_record)                   │
│  - WORM lock (lock_run → LOCKED.json + 0o444)          │
└────────────────────────────────────────────────────────┘
                        │
                        ▼
                  Signed Bundle
          (규제 제출 후보 — customer QMS 검증 필요)
```

### 각 계층의 Audit Emission 정책

| 계층 | Audit 유형 | GxP 적용 가능 | 비고 |
|---|---|---|---|
| LLM 오케스트레이션 | LLM transcript log | No (non-GxP) | 탐색적 출처 증명용 |
| Deterministic kernel | HMAC hash-chain execution record | Yes (candidate) | customer QMS 하에서 사용 가능 |
| E-signature | Ed25519 signature manifest | Yes (candidate) | §11.50 3필드 강제 |
| WORM lock | LOCKED.json + OS-level 0o444 | Yes (candidate) | lock_run 후 불변 |

### 두 계층 연결 (v2.1 계획)

controlled mode에서 LLM transcript hash를 deterministic record에 reference로 포함하는
기능은 v2.1로 연기되었습니다. v2.0에서는 두 계층이 독립적으로 기록됩니다.

---

## 🔗 다음 단계

- [02-roadmap.md](02-roadmap.md) — 단계별 빌드 계획
- [06-mcp-server.md](06-mcp-server.md) — MCP 도구 상세 사양
- [14-llm-boundary-disclosure.md](14-llm-boundary-disclosure.md) — LLM 경계 공개 (상세)
