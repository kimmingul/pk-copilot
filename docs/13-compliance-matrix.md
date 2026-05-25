# 13. Compliance Matrix — 책임 분리

> **이 문서의 목적**: pk-copilot v2.0이 제공하는 것과 사용자 조직이 제공해야 하는 것을
> 명확히 구분합니다. 이 구분은 "Part 11-enabling"과 "Part 11 compliant"의 차이를
> 구체적으로 보여줍니다.

---

## 핵심 원칙

> pk-copilot은 **Part 11-enabling technical controls**를 제공합니다.
> **실제 Part 11 준수(compliance)**는 이 표의 두 컬럼을 모두 충족할 때 성립하며,
> 그 판단과 실행은 **사용자 조직의 QMS 책임**입니다.

---

## 책임 분리 매트릭스

| 항목 | pk-copilot v2.0 제공 | 사용자 조직 제공 | Reference |
|---|---|---|---|
| **감사 추적 (Audit Trail)** | ✅ Append-only HMAC-SHA256 hash-chain JSONL | 주기적 감사 로그 검토 및 이상 보고 (SOP-QA-002) | §11.10(e) |
| **전자서명 기본 요소 (E-signature primitives)** | ✅ Ed25519 키페어 + TOTP 2FA; 서명 매니페스트 3필드 (§11.50) | 개인키 보안 관리 SOP; 키 분실·침해 대응 절차 | §11.50, §11.70, §11.200 |
| **RBAC 프레임워크** | ✅ Role enum (Viewer/Analyst/Approver/Admin) + 권한 매트릭스 | 역할 할당 승인 문서화; 최소 권한 원칙 적용 | §11.10(d), §11.10(g) |
| **WORM lock** | ✅ LOCKED.json + OS-level 0o444; WORM 스토리지 백엔드 인터페이스 | WORM 스토리지 구성 및 테스트 (AWS S3 Object Lock 등) | §11.10(c) |
| **IQ/OQ/PQ 스크립트** | ✅ 자동화 검증 스크립트 + golden dataset 매트릭스 | 검증 실행, 결과 검토, 검증 보고서 서명 및 보관 | §11.10(a) |
| **Validation Master Plan 템플릿** | ✅ VMP 템플릿 제공 | 조직 환경에 맞게 수정·승인; CSV 수명주기 전체 관리 | §11.10(a) |
| **시스템 검증 패키지** | ✅ IQ/OQ/PQ 산출물, 알고리즘 트레이서빌리티 | 검증 완료 기준 결정; 재검증 트리거 정의 | §11.10(a) |
| **운영 시퀀싱 (State machine)** | ✅ Draft→Authored→Reviewed→Approved 상태 머신 | 워크플로우 일탈 시 일탈 처리 절차 (SOP-QA-003) | §11.10(f) |
| **워크스테이션 로깅** | ✅ hostname, IP, platform, python_env_hash 자동 수집 | 인가된 장치 목록 관리; 비인가 장치 접근 차단 | §11.10(h) |
| **SOP 템플릿** | ✅ SOP-IT-001~003, SOP-QA-001~004 참조 템플릿 | **조직 맞춤화 후 공식 승인 필수** — 미수정 템플릿 사용 금지 | §11.10(i) |
| **Predicate-rule 판단** | ❌ 제공하지 않음 | **조직 QA/RA 팀이 결정** — 어떤 기록에 Part 11이 적용되는지 | §11.1 |
| **SOP (실제 운영)** | ❌ 제공하지 않음 (템플릿만 제공) | 계정 관리, 교육, 변경 통제, 일탈 처리, 기록 보존 SOP 작성·승인·시행 | §11.10(i), §11.10(j) |
| **교육 기록** | ❌ 제공하지 않음 | 모든 시스템 사용자 교육 실시 및 기록 보존 (SOP-TR-001) | §11.10(i) |
| **계정 거버넌스** | ❌ 제공하지 않음 | 계정 생성 승인, 주기적 접근 권한 검토, 퇴직자 즉시 비활성화 | §11.10(j), §11.100(c) |
| **감사 로그 주기 검토** | ❌ 제공하지 않음 | 분기별 이상 탐지 및 일탈 처리 (SOP-QA-002) | §11.10(e) |
| **물리적 보안** | ❌ 제공하지 않음 | 서버실·워크스테이션 물리 접근 통제; 출입 기록 | §11.10(d) |
| **네트워크 보안** | ❌ 제공하지 않음 | TLS 종단, 방화벽, VPN 정책 수립 및 문서화 | §11.30 (open systems) |
| **백업 / 재해 복구** | ❌ 제공하지 않음 | 백업 주기 정의, 복원 테스트, RTO/RPO 문서화 (SOP-IT-003) | §11.10(c) |
| **LLM 제공업체 모델 적격성 평가** | ❌ 제공하지 않음 | LLM 출력이 controlled record에 진입하는 경우 모델 drift 관리; v2.1까지 권장하지 않음 | FDA 2025 AI guidance |
| **장기 보존 형식 마이그레이션** | ❌ 제공하지 않음 | 20-30년 후 파일 형식(JSON/JSONL) 가독성 보장; 아카이브 정책 | §11.10(c) |
| **규제 제출물 패키지 조립** | ❌ 제공하지 않음 | IND/NDA 제출 패키지 조립 및 제출은 조직 RA 책임 | 21 CFR §314.50 등 |

---

## 요약: "Enabling" vs "Compliant"

```
pk-copilot v2.0 제공:
  ✅ Technical controls (audit chain, e-sig, RBAC, WORM, IQ/OQ/PQ)
  ✅ Deterministic execution (동일 입력 → 동일 결과 보장)
  ✅ Exploratory / Controlled 모드 분리

사용자 조직 제공:
  ✅ Predicate-rule 판단
  ✅ QMS 운영 (SOP, 교육, 계정 거버넌스)
  ✅ Validation 실행 및 승인
  ✅ 물리적·네트워크 보안
  ✅ 감사 로그 검토 및 일탈 처리
  ✅ 장기 아카이브 관리

두 컬럼 모두 충족 = Part 11 준수 (compliance)
                   ↑
              이 판단은 조직 QA/RA 팀의 몫입니다
```

---

## 다음 단계

- [10-21cfr-part11.md](10-21cfr-part11.md) — §17 Execution Modes 상세
- [12-intended-use.md](12-intended-use.md) — 의도된 사용 목적 및 사용자 책임
- [14-llm-boundary-disclosure.md](14-llm-boundary-disclosure.md) — LLM 역할 및 비결정성 위험
