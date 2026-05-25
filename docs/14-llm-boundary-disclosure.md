# 14. LLM Boundary Disclosure — LLM 역할 및 경계 공개

> **이 문서의 목적**: pk-copilot에서 LLM(대형 언어 모델)이 수행하는 역할과 수행하지 않는
> 역할을 정직하게 공개합니다. LLM의 비결정적 특성, 관련 위험, 그리고 deterministic kernel과의
> 분리 아키텍처를 설명합니다.

---

## 1. LLM이 하는 것 / 하지 않는 것

### LLM이 하는 것 (DOES)

| 역할 | 설명 |
|---|---|
| **자연어 의도 해석** | 사용자의 자연어 입력을 분석 명령으로 변환 |
| **데이터 컬럼 매핑 제안** | CSV/Excel 컬럼 이름을 PK 데이터 스키마에 매핑하는 제안 제공 |
| **모델 추천** | 데이터 특성에 기반한 구획 모델, 오류 모델 추천 |
| **파라미터 범위 제안** | 초기 추정치 제안 (deterministic fitting의 시작점) |
| **보고서 내러티브 초안** | 분석 결과를 서술하는 텍스트 초안 작성 |
| **이상치 탐지 제안** | 데이터에서 잠재적 이상치 또는 문제점 지적 |
| **Lambda_z 선택 협의** | 말단상 회귀 구간 선택에 대한 사용자와의 협의 진행 |

### LLM이 하지 않는 것 (DOES NOT)

| 항목 | 이유 |
|---|---|
| **숫자 계산 수행** | LLM은 AUC 적분, Lambda_z 회귀, t½ 계산을 직접 수행하지 않습니다. 모든 계산은 검증된 deterministic kernel (numpy/scipy/PKNCA-compatible)에 위임됩니다. |
| **통계적 추론** | BE 90% CI, ANOVA, 혼합 모델은 검증된 통계 라이브러리가 계산합니다. LLM은 결과를 해석하는 텍스트만 생성합니다. |
| **AUC/Lambda_z 직접 적분** | 수치 적분은 전적으로 deterministic kernel이 수행합니다. |
| **GxP audit record 생성** | exploratory mode에서는 LLM transcript만 기록되며 GxP audit chain을 생성하지 않습니다. |
| **최종 임상적·규제적 판단** | PK 파라미터의 임상적 의미와 규제적 적용은 자격을 갖춘 사용자의 전문적 판단입니다. |

---

## 2. Two-Layer Architecture (이중 계층 아키텍처)

```
┌───────────────────────────────────────────────────────────────┐
│                    사용자 입력 (자연어)                          │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│  Layer 1: LLM 오케스트레이션 계층  [비결정적, EXPLORATORY]       │
│                                                               │
│  역할:                                                         │
│  - 자연어 → 분석 명령 변환                                      │
│  - 컬럼 매핑 제안                                               │
│  - 모델·파라미터 추천                                           │
│  - 보고서 내러티브 초안                                         │
│                                                               │
│  특성:                                                         │
│  - 비결정적 (동일 입력 → 다른 출력 가능)                          │
│  - Provider drift 위험                                         │
│  - Prompt injection 위험                                       │
│                                                               │
│  출력: LLM transcript log (non-GxP, 탐색적 출처 증명용)         │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           │  ← 사용자 명시적 승인
                           │     (controlled mode에서 audit chain에 기록)
                           ▼
┌───────────────────────────────────────────────────────────────┐
│  Layer 2: Deterministic Kernel  [결정론적, CONTROLLED CANDIDATE]│
│                                                               │
│  역할:                                                         │
│  - NCA 파라미터 계산 (AUC, Cmax, t½, Lambda_z, CL, Vz 등)      │
│  - BE 통계 (GMR, 90% CI, TOST)                                │
│  - 구획 모델 적합 (1/2/3-cmt, ODE)                             │
│  - PK/PD 연결 모델 적합                                         │
│                                                               │
│  특성:                                                         │
│  - 완전 결정론적 (동일 입력 해시 → 동일 수치 결과 보장)            │
│  - numpy/scipy/PKNCA-compatible                               │
│  - JSON-of-record + 실행 스크립트 자동 생성                      │
│                                                               │
│  출력: HMAC hash-chain execution record (GxP candidate)       │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│  Audit Chain (controlled mode only)                           │
│  → E-signature (Ed25519) → WORM lock → Signed bundle         │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. Audit Layers (감사 계층)

pk-copilot v2.0은 두 개의 독립적인 감사 계층을 운영합니다.

| 감사 계층 | 생성 시점 | 내용 | GxP 적용 가능 | 목적 |
|---|---|---|---|---|
| **LLM Transcript Log** | Exploratory mode (항상) | LLM 프롬프트·응답·모델 메타데이터·타임스탬프 | No (non-GxP) | 탐색적 분석 출처 증명, 재현성 참조 |
| **Deterministic Execution Record** | Controlled mode (`PKPLUGIN_PART11_ENABLED=1`) | 입력 파일 해시, 알고리즘 버전, 계산 파라미터, 수치 결과, HMAC | Yes (GxP candidate) | Part 11-controlled workflow 후보 |

### 두 계층의 연결 (v2.0 현재 상태)

v2.0에서는 두 계층이 독립적으로 기록됩니다. LLM transcript hash를 deterministic
record에 reference로 포함하는 기능은 **v2.1 계획**입니다.

v2.0에서 controlled mode 사용 시:
- LLM transcript log: 별도 파일에 기록 (참조용)
- Deterministic execution record: HMAC hash-chain에 기록 (GxP candidate)
- 두 기록의 연결은 사용자가 수동으로 `run_id`를 통해 추적 가능

---

## 4. Non-Determinism Risks (비결정성 위험 — 정직한 공개)

LLM 계층이 포함하는 비결정성 위험을 정직하게 공개합니다:

| 위험 유형 | 설명 | 완화 방법 |
|---|---|---|
| **LLM provider model drift** | 모델 제공업체가 모델을 업데이트하면 동일한 프롬프트에 다른 응답이 생성될 수 있습니다. | LLM 출력을 regulatory record로 직접 사용하지 말 것; deterministic kernel 결과만 사용 |
| **Hidden context / system prompt 변경** | Claude Code의 system prompt 변경이 LLM 응답에 영향을 줄 수 있습니다. | 중요 분석은 항상 deterministic kernel로 재확인 |
| **Sampling / temperature 비결정성** | 동일한 입력이라도 temperature > 0이면 다른 응답이 생성될 수 있습니다. | LLM 응답은 "제안"으로만 취급; 수치는 deterministic kernel로 검증 |
| **Context window truncation** | 긴 데이터나 대화 맥락이 context window를 초과하면 LLM이 이전 정보를 잊을 수 있습니다. | 중요 분석 파라미터는 CLI 명령으로 명시적으로 지정 |
| **Tool call ordering variation** | LLM이 동일한 분석에서 다른 순서로 MCP tool을 호출할 수 있습니다. | Controlled mode에서는 명시적 CLI 명령 사용 |
| **Prompt injection** | 사용자 데이터(CSV 컬럼명, 코멘트 등)에 악의적 지시가 포함될 경우 LLM 동작에 영향을 줄 수 있습니다. | 신뢰할 수 없는 소스의 데이터는 사전 검토 후 사용; controlled mode에서는 LLM 없이 CLI 직접 실행 가능 |

> **중요**: 위 위험들은 LLM 계층에만 적용됩니다. **Deterministic kernel은 이러한
> 비결정성 위험에 영향을 받지 않습니다.** 동일한 입력 해시와 알고리즘 설정은 항상
> 동일한 수치 결과를 생성합니다.

---

## 5. User Responsibility in Controlled Mode (통제 모드에서의 사용자 책임)

### LLM 제안 명령 실행 시 책임

controlled mode에서 LLM이 제안한 명령을 승인하고 실행할 때:

1. **명령 내용 검토 의무**: 승인자는 LLM이 제안한 분석 파라미터(모델 유형, lambda_z 구간,
   BLOQ 정책 등)가 과학적으로 적절한지 검토해야 합니다.

2. **승인 책임**: `pkplugin sign --meaning authored`로 서명하는 것은 해당 분석 명령의
   내용에 동의하는 것을 의미합니다. LLM이 제안했다는 사실이 승인자의 책임을 면제하지 않습니다.

3. **수치 검증 의무**: LLM 출력에 포함된 수치 주장(예: "AUC는 약 120 ng·h/mL")은
   반드시 deterministic kernel 결과로 검증해야 합니다. LLM의 수치 추정은 informational이며
   official result가 아닙니다.

4. **명시적 승인**: controlled mode에서 모든 실행은 사용자 명시적 승인을 거칩니다.
   LLM이 자동으로 controlled execution을 시작할 수 없습니다.

---

## 6. "Reproducibility"의 의미 — LLM이 포함될 때

| 재현성 유형 | 보장 여부 | 설명 |
|---|---|---|
| **LLM 응답 재현성** | ❌ 보장하지 않음 | 동일한 자연어 입력이 동일한 LLM 응답을 보장하지 않습니다. |
| **Deterministic kernel 재현성** | ✅ 보장 | 동일한 입력 파일 해시 + 동일한 알고리즘 설정 → 동일한 수치 결과가 보장됩니다. |
| **규제용 재현성** | ✅ Deterministic 기준 | 규제 기록의 재현성 기준은 "approved deterministic execution"입니다. LLM 응답이 아닙니다. |
| **Audit chain 재현성** | ✅ Hash-chain으로 보장 | 동일한 run_id의 감사 로그는 HMAC hash-chain으로 무결성이 보장됩니다. |

### 실용적 결론

```
규제용 기록의 재현성 = (동일 입력 파일 해시) + (동일 알고리즘 설정)
                      → deterministic kernel이 보장

LLM 자연어 응답은 재현성 기준에 포함되지 않습니다.
```

---

## 7. pk-copilot LLM Path vs Pure ChatGPT 비교

pk-copilot이 LLM을 포함함에도 불구하고 순수 ChatGPT/일반 LLM 사용과 어떻게 다른지:

| 특성 | pk-copilot (LLM + deterministic kernel) | 순수 ChatGPT/LLM |
|---|---|---|
| **수치 계산** | Deterministic kernel이 수행 (환각 없음) | LLM이 직접 계산 (환각 위험) |
| **데이터 보안** | 로컬 실행 (데이터가 외부 LLM API에 전송되지 않음) | 데이터가 LLM 제공업체 서버에 전송됨 |
| **무결성 증명** | HMAC hash-chain audit record | 없음 |
| **재현성 보장** | Deterministic kernel 결과에 대해 보장 | 보장하지 않음 |
| **WinNonlin 호환성** | 검증된 알고리즘 구현 | 알고리즘 정확도 불확실 |
| **E-signature** | Ed25519 + TOTP 2FA | 없음 |
| **LLM 비결정성** | LLM 계층에 동일하게 존재 (단, 계산 결과에 영향 없음) | LLM 계층에 동일하게 존재 |

> **요약**: pk-copilot은 LLM의 비결정성을 제거하는 것이 아닌, **LLM을 결정론적
> 계산 계층과 명확히 분리**하여 계산 결과의 정확성·재현성·무결성을 보장합니다.
> LLM 자체의 비결정성은 두 도구 모두에서 동일하게 존재합니다.

---

## 8. 참조 아키텍처 및 선례

동일한 "LLM orchestration + validated deterministic engine" 분리 방식을 채택한 사례:

- **Certara Phoenix AI**: AI는 오케스트레이션만, 계산은 Phoenix WinNonlin validated engine
- **Pumas-AI**: AI는 자연어 인터페이스, 계산은 Pumas.jl Julia kernel
- **FDA 2025 Draft Guidance "Use of AI to Support Regulatory Decision-Making"**:
  AI가 regulatory decision evidence를 산출할 때 context-of-use, model risk, credibility
  assessment, lifecycle control 추가 요구

pk-copilot v2.0은 이 접근 방식의 오픈소스 구현입니다.

---

## 다음 단계

- [10-21cfr-part11.md §17](10-21cfr-part11.md) — Execution Modes 상세
- [12-intended-use.md](12-intended-use.md) — 의도된 사용 목적 및 사용자 책임
- [13-compliance-matrix.md](13-compliance-matrix.md) — 책임 분리 매트릭스
- [01-architecture.md](01-architecture.md) — Execution Mode Boundary 다이어그램
