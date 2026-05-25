# 12. Intended Use Statement (사용 목적 진술)

> **이 문서의 성격**: pk-copilot v2.0의 의도된 사용 목적, 의도된 사용자, 의도된 워크플로우를
> 명시적으로 정의합니다. 의료기기 Intended Use Statement 관례를 참조하여 작성되었습니다.

---

## 1. 제품 정의

pk-copilot은 **약동학(PK)·약력학(PD) 분석을 돕는 decision support tool**입니다.

자격을 갖춘 약리학자, 통계학자, pharmacometrician이 PK/PD 데이터를 분석하고
규제 제출용 산출물 초안을 작성하는 과정을 지원합니다.

**영문**: *pk-copilot is a decision support tool that assists qualified pharmacologists,
statisticians, and pharmacometricians in conducting pharmacokinetic and pharmacodynamic
analyses.*

---

## 2. Not Intended For (사용 불가 목적)

pk-copilot은 다음 목적으로 사용하도록 설계되지 **않았습니다**:

| 항목 | 이유 |
|---|---|
| **환자 진단·치료 의사결정** | pk-copilot은 의료기기(medical device)가 아닙니다. 임상 진단 또는 치료 결정에 사용하지 마십시오. |
| **LLM 자연어 출력을 final regulatory record로 사용** | LLM 출력은 exploratory이며 비결정적(non-deterministic)입니다. regulatory record는 deterministic kernel 실행 결과만 적합합니다. |
| **자격 없는 사용자에 의한 PK 파라미터 해석** | PK 파라미터의 임상적·규제적 해석은 전문적 교육과 경험이 필요합니다. |
| **조직 QMS·SOP·교육 없이 규제 환경 배포** | Part 11-enabling controls는 조직의 QMS와 결합할 때에만 의미를 가집니다. |
| **LLM 제안 명령을 검토 없이 직접 실행** | controlled mode에서 LLM이 제안한 명령을 그대로 실행할 때, 명령 내용에 대한 책임은 승인자에게 있습니다. |

---

## 3. Intended Users (의도된 사용자)

pk-copilot은 다음 사용자를 위해 설계되었습니다:

- **자격을 갖춘 약리학자 (pharmacologist)**: PK 파라미터의 의미와 한계를 이해하는 전문가
- **임상 통계학자 (clinical statistician)**: BE 분석, 혼합 모델, 통계적 추론을 이해하는 전문가
- **Pharmacometrician**: 구획 모델링, PK/PD 연결 모델을 이해하는 전문가
- **CRO 분석가**: 검증된 PK 분석 방법론을 이해하고 결과를 비판적으로 검토할 수 있는 전문가
- **규제 제출 담당자 (RA)**: PK 데이터 패키지를 IND/NDA에 포함하는 경험이 있는 전문가

**공통 전제**: 모든 의도된 사용자는 **LLM 출력을 비판적으로 검토하고 deterministic
kernel 결과와 독립적으로 검증할 수 있는 능력**을 갖춰야 합니다.

---

## 4. Intended Workflow (의도된 워크플로우)

### 4.1 Exploratory Workflow

```
1. Claude chat으로 데이터 탐색
   - 컬럼 매핑 확인
   - 이상치 탐지
   - 모델 선택 후보 협의

2. LLM이 분석 명령 제안
   - 사용자가 제안 내용 검토

3. Deterministic kernel 실행 (LLM 제안 기반)
   - 결과 확인
   - 필요시 파라미터 조정

4. 보고서 초안 작성 (LLM 지원)
   - 사용자가 초안 검토·수정

5. 최종 해석 및 임상적·규제적 적용 (사용자 책임)
```

### 4.2 Controlled Workflow (Part 11-enabling)

```
1. PKPLUGIN_PART11_ENABLED=1 환경 설정 확인
   - 조직 QMS, SOP, 교육 완료 확인

2. (선택) Exploratory 탐색으로 분석 설계 결정

3. Controlled execution
   - CLI 또는 MCP tool로 deterministic kernel 실행
   - HMAC hash-chain audit record 자동 생성

4. E-signature 워크플로우
   - Analyst: authored 서명
   - Approver: reviewed 서명
   - Final Approver: approved 서명 → WORM lock

5. Signed bundle 아카이브
   - 조직의 기록 보존 SOP에 따라 관리
```

---

## 5. User Responsibility (사용자 책임)

### 개인 사용자 책임

- **분석 결과의 최종 해석**: LLM 출력과 무관하게, PK 파라미터의 임상적·규제적 해석은
  사용자(분석가)의 전문적 판단 책임입니다.
- **LLM 출력의 critical review**: LLM이 제안한 모델, 파라미터 범위, 보고서 내용을
  독립적으로 검토하고 검증하는 것은 사용자 의무입니다.
- **LLM 제안 명령 승인**: controlled mode에서 LLM이 제안한 명령을 승인하고 실행할 때,
  해당 명령의 과학적·규제적 적절성에 대한 책임은 승인자에게 있습니다.
- **데이터 품질**: 입력 데이터의 정확성과 품질은 사용자 책임입니다. pk-copilot은
  데이터 품질 문제를 탐지하는 도구를 제공하지만, 데이터 소유권은 사용자에게 있습니다.

### 조직 책임

- **QMS 운영**: SOP, 교육, 계정 거버넌스, 변경 통제는 조직 책임입니다.
- **Predicate-rule 판단**: 어떤 기록에 Part 11이 적용되는지는 조직의 QA/RA 팀이 결정합니다.
- **Validation 실행**: IQ/OQ/PQ 패키지 실행 및 검증 보고서 승인은 조직 책임입니다.
- **감사 로그 검토**: 주기적 감사 로그 검토 및 이상 사항 처리는 조직 책임입니다.
- **물리적·네트워크 보안**: 서버·워크스테이션 물리 접근 통제 및 네트워크 보안은 조직 책임입니다.
- **장기 아카이브**: 기록의 장기 보존 형식 마이그레이션 및 접근성 유지는 조직 책임입니다.

---

## 6. 규제 환경별 고려사항

| 규제 환경 | pk-copilot 사용 가능 여부 | 추가 요건 |
|---|---|---|
| **탐색적 연구 (비규제)** | 제한 없음 | 없음 |
| **IND 제출 지원** | 가능 (controlled mode) | 조직 QMS + IQ/OQ/PQ 필요 |
| **NDA/BLA 제출 지원** | 가능 (controlled mode) | 조직 QMS + IQ/OQ/PQ + 감사 검토 필요 |
| **GCP 임상시험 지원** | 가능 (controlled mode) | 조직 QMS + CSV 전체 수명주기 관리 필요 |
| **환자 치료 의사결정** | 사용 불가 | — |

---

## 다음 단계

- [13-compliance-matrix.md](13-compliance-matrix.md) — pk-copilot 제공 vs 조직 제공 책임 매트릭스
- [14-llm-boundary-disclosure.md](14-llm-boundary-disclosure.md) — LLM 역할 및 경계 공개
- [10-21cfr-part11.md](10-21cfr-part11.md) — Part 11 기술 통제 상세
