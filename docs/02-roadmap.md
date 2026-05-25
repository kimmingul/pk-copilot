# 02. Roadmap (v0.1 → v2.0)

## 개요

| 버전 | 코드네임 | 핵심 가치 | 예상 기간 |
|---|---|---|---|
| **v0.1** | "First NCA" | 단일대상자 NCA, CSV → 표·플롯 | 4-6주 |
| **v0.2** | "Cohort" | 다대상자 NCA + 기술통계 + BE | 4주 |
| **v0.3** | "Compartments" | 1/2-구획 모델 적합 | 6주 |
| **v0.4** | "PK/PD Link" | Emax / Effect compartment / IDR | 4주 |
| **v0.5** | "Report" | PDF/Quarto 리포트, 교차검증 | 3주 |
| **v1.0** | "Production" | MCP 패키징, 골든 검증 매트릭스 완성 | 3주 |
| **v1.x** | "Polish" | 사용자 피드백 반영, 안정화 | 지속 |
| **v2.0** | "Regulated-Capable" | **CDISC SDTM/ADaM + Part 11-enabling controls (deterministic path)** | 12-16주 |

---

## 🛠️ v0.1 — First NCA (단일대상자 MVP)

### 산출물
- `plugin.json`, `.mcp.json`, MCP 서버 초기 구현
- `/nca` 명령 + `nca-analyst` 에이전트 + `nca-workflow` 스킬
- 단위 강제 확인 UX (Gemini 권장)
- 알고리즘 (모두 [03-algorithms/](03-algorithms/) 사양 준수):
  - Cmax, Tmax, Tlast, Clast
  - AUC0-t (linear-up/log-down)
  - AUC0-inf (obs / pred)
  - AUMC, MRT
  - Lambda_z (Best Fit + adj-R², span guard)
  - t½, CL, CL/F, Vz, Vz/F, Vss(IV)
- JSON-of-record + 실행 스크립트(.py)
- Lambda_z 회귀 플롯 + linear/log 농도-시간 플롯
- **Golden test**: Theophylline 데이터셋 PKNCA vs pk-copilot ≤ 6 sig fig

### 인수 기준 (Acceptance Criteria)
- ✅ Theophylline 12명 데이터셋에서 모든 파라미터 PKNCA 0.10+ 결과와 1e-6 상대오차 이내
- ✅ WinNonlin 6.4 기본값(`winnonlin_version="6.4"`) 옵션으로 호출 가능
- ✅ 단위 미확정 입력 시 분석 차단 (PreToolUse hook)
- ✅ 모든 결과 행이 알고리즘·BLOQ·exclusion 설명 동반

### 제외 (Out of Scope)
- 다대상자 통계, BE, 구획분석, popPK, CDISC

---

## 🛠️ v0.2 — Cohort (다대상자 + BE)

### 산출물
- `subject_id × period × treatment × analyte` 그루핑
- 기술 통계: N, mean, SD, geometric mean, geometric CV%, median, min, max
- `/be` 명령 + `bioequivalence.py`
  - log 변환 AUC0-t / AUC0-inf / Cmax
  - GMR + 90% CI
  - TOST (Two One-Sided Tests)
  - Crossover ANOVA / mixed model (sequence, period, treatment, subject(sequence))
  - 기준: 80.00 – 125.00 % (FDA 일반 BE)
- Excel + SAS XPT 입력
- 다대상자 spaghetti plot, mean ± SD 플롯
- **Golden test**: FDA BE guidance 2x2 crossover 예제와 일치

### 인수 기준
- ✅ NonCompart 다대상자 결과와 일치
- ✅ R `PKNCA::pk.calc.geomean` 와 GMR 일치
- ✅ SAS PROC MIXED 결과와 BE 90% CI ±0.01% 이내

---

## 🛠️ v0.3 — Compartments (구획분석)

### 산출물
- `comp/analytic.py` — closed-form
  - 1-cmt IV bolus / IV infusion / first-order absorption
  - 2-cmt IV bolus / IV infusion / first-order absorption
- `comp/ode.py` — `scipy.integrate.solve_ivp` LSODA/BDF
  - Michaelis-Menten elimination
  - 일반 ODE 모델
  - Event dosing (반복 투여, 정주, 경구)
- `comp/fitting.py`:
  - NLS (`scipy.optimize.least_squares`)
  - MLE (`lmfit`)
  - Weighting: `1`, `1/y`, `1/y²`, `1/pred`, `1/pred²`
  - Residual error: additive / proportional / combined
- Diagnostics: observed vs predicted, residual vs time/pred, QQ, AIC/BIC, condition number
- NCA 결과로 초기 추정치 자동 생성
- **Golden test**: closed-form vs ODE 시뮬레이션 동등성 + WinNonlin 6.4 1-cmt PO 예제 일치

### 인수 기준
- ✅ Bateman 방정식과 1-cmt PO closed-form 일치
- ✅ WinNonlin "PK Model 1, 7, 11" 결과 재현
- ✅ AIC/BIC 계산이 WinNonlin 정의와 일치 (k 정의 차이 주의)

---

## 🛠️ v0.4 — PK/PD Link

### 산출물
- Direct effect: linear, log-linear, Emax, sigmoid Emax
- Effect compartment: `dCe/dt = ke0*(Cp - Ce)`
- Indirect Response Models I-IV (Jusko / Dayneka)
- Turnover: `dR/dt = kin·f(Ce) - kout·g(Ce)·R`
- Sequential PK→PD fitting + simultaneous fitting 옵션
- Hysteresis plot
- **Golden test**: WinNonlin 표준 PD 예제 (warfarin, propofol BIS 등) 재현

---

## 🛠️ v0.5 — Report & Cross-Validation

### 산출물
- `report/pdf.py` — reportlab 기반 WinNonlin-스타일 표
- `report/quarto.py` — Quarto 렌더링 (HTML/PDF/Word)
- `report/tables.py` — Subject × Period × Parameter pivot
- `compare_against_reference()` MCP 도구:
  - Python ↔ R PKNCA 자동 비교 → `validation_diff.json`
  - 파라미터별 absolute / relative error
- Run bundle: `runs/<run_id>/{audit.md, script.py, results.csv, report.html, diff.json}`

---

## 🛠️ v1.0 — Production Release

### 산출물
- MCP 서버 안정화 + fastmcp 패키징
- 전체 명령/에이전트/스킬 폴리시
- 골든 검증 매트릭스:
  - Theophylline (PKNCA fixture)
  - Indomethacin (PKNCA fixture)
  - FDA BE guidance 예제
  - WinNonlin 5.3 / 6.4 / 8.3 사용자 매뉴얼 예제 (각 알고리즘별)
- SBOM, signed release artifacts, semver
- 사용자 문서 + 레시피(SAD, MAD, BE crossover, IV infusion)

### v1.0 비목표 (명시적)
- ❌ "21 CFR Part 11 compliant" 주장
- ❌ popPK 자체 구현 (nlmixr2 래퍼만 제공 가능)
- ❌ PBPK / IVIVC

---

## 🏛️ v2.0 — Regulated-Capable Edition (CDISC + Part 11-enabling controls)

> **목표**: v2는 단순한 기능 추가가 아닌 **품질 시스템 준비 + Part 11-enabling 기술 통제**를 갖춘 production-grade tool.
> pk-copilot은 Part 11 compliant 시스템을 주장하지 않습니다. v2.0은 sponsor의 QMS 아래
> controlled deployment 시 deterministic execution record를 Part 11-controlled workflow에
> 사용 가능하도록 enable하는 technical controls를 제공합니다.

### 2.1 Part 11-enabling 기술 통제

상세는 [10-21cfr-part11.md](10-21cfr-part11.md) 참조.

#### 기술적 통제 (Technical Controls)
- **Audit Trail**: append-only, hash-chained, immutable
  - `who / what / when / why / before / after` 6필드 강제
  - 사용자 신원, 타임스탬프(NTP-synced), 변경 사유
- **Electronic Signatures** (`compliance/part11.py`):
  - Public-key 서명 (Ed25519) + 사용자 인증 (TOTP 2FA)
  - 서명 manifest 동결 (immutable run lock)
  - "Signed by", "Date", "Meaning of signature" 3필드
- **Access Control** (RBAC):
  - Roles: Viewer / Analyst / Approver / Admin
  - 모든 작업이 사용자 토큰과 연결
- **Record Retention**:
  - 분석 산출물 영구 보관 옵션
  - WORM(Write-Once-Read-Many) 스토리지 백엔드 (S3 Object Lock 등)
- **System Validation Package**:
  - IQ (Installation Qualification) 스크립트
  - OQ (Operational Qualification) 자동 테스트
  - PQ (Performance Qualification) 골든 데이터셋 매트릭스

#### 절차적 통제 (Procedural — 사용자/조직 책임 명시)
- pk-copilot 단독으로는 Part 11 준수 불가
- 조직의 SOP, 교육 기록, 사용자 계정 관리 등은 사용자 책임
- 가이드 문서 제공: "당신의 조직이 무엇을 해야 하는가" 체크리스트

### 2.2 CDISC 표준 지원

상세는 [09-cdisc-support.md](09-cdisc-support.md) 참조.

#### SDTM 입력 (`cdisc/sdtm.py`)
- **PC** (Pharmacokinetic Concentrations) 도메인 직접 임포트
- **EX** (Exposure) 도메인 직접 임포트
- **DM** (Demographics), **VS** (Vital Signs) 공변량 통합
- **PP** (PK Parameters) 도메인 익스포트 — WinNonlin과 호환되는 PPCAT/PPTESTCD

#### ADaM 출력 (`cdisc/adam.py`)
- **ADPC** (Pharmacokinetic Concentrations Analysis Dataset)
- **ADPP** (Pharmacokinetic Parameters Analysis Dataset)
- Define-XML 메타데이터 자동 생성
- CDISC Controlled Terminology (CT) 적용 (PARAMCD, PARAM 등)

#### 표준 데이터 흐름
```
SDTM PC + EX  →  pk-copilot  →  ADaM ADPC + ADPP  →  IND/NDA 제출 패키지
```

### 2.3 v2.0 추가 산출물
- `cdisc-mapping` 스킬
- `audit-trail` 스킬
- 외부 GxP 감사 통과 증빙 패키지
- WinNonlin → pk-copilot 마이그레이션 가이드

### 인수 기준
- ✅ Part 11-enabling technical controls (audit chain, e-signature, RBAC, WORM lock) 구현 완료
- ✅ 510+ 자동화 테스트 통과 (mypy clean, ruff clean)
- ✅ CDISC Pilot Study 02 데이터셋 end-to-end 처리
- ✅ Define-XML 검증 도구 (PinnacleAI 등) 무오류 통과
- ✅ ADaM 데이터셋이 OpenCDISC validator 통과
- ✅ Exploratory / Controlled 실행 모드 명시적 구분

---

## 📅 마일스톤 요약

| 마일스톤 | 누적 기능 |
|---|---|
| **v0.1** | ✅ NCA 단일대상자 |
| **v0.2** | ✅ + 다대상자 + BE |
| **v0.3** | ✅ + 구획분석 |
| **v0.4** | ✅ + PK/PD 연결 |
| **v0.5** | ✅ + 리포트 + 교차검증 |
| **v1.0** | ✅ Production release (검증 가능, 규제 미주장) |
| **v2.0** | ✅ Regulated-Capable edition (CDISC + Part 11-enabling controls) |

---

## 🚦 출시 정책

- **Semantic Versioning** 엄격 적용
- **Breaking changes**는 메이저(`v2.0` → `v3.0`) 에서만
- **Default algorithms** 변경 시 → `winnonlin_version` 옵션으로 이전 동작 보존
- **Validation diffs**는 모든 릴리즈에 첨부

## 🔗 다음 단계

- [03-algorithms/](03-algorithms/) — 알고리즘 사양
- [04-winnonlin-version-matrix.md](04-winnonlin-version-matrix.md) — 버전 차이
- [10-21cfr-part11.md](10-21cfr-part11.md) — v2 규제 준수 계획
