---
name: regulatory-validation
description: Use when user asks whether pk-copilot results can be used for IND/NDA submission or 21 CFR Part 11 compliance. Surfaces the honest answer about v1.x (not Part 11) vs v2.0 (Part 11 controls).
---

# regulatory-validation

규제 제출(IND/NDA) 또는 21 CFR Part 11 준수 여부를 묻는 사용자에게 정확하고
솔직한 답변을 제공합니다. pk-copilot이 *할 수 있는 것*과 *할 수 없는 것*을
명확히 구분하는 것이 이 스킬의 유일한 목적입니다.

---

## v1.x vs v2.0 — 규제 포지션 요약

| 항목 | v1.x | v2.0 |
|---|---|---|
| **21 CFR Part 11 준수 주장** | ❌ 불가 | ❌ 소프트웨어 단독으로 불가 |
| **Part 11 기술적 통제 제공** | ❌ | ✅ Audit Trail, E-Signature, RBAC, WORM |
| **Audit-ready 산출물** | ✅ audit.json + audit.md 생성 | ✅ hash-chained JSONL |
| **재현 가능한 분석** | ✅ nca_script.py / be_script.py | ✅ |
| **IND/NDA 첨부 데이터 생성** | ✅ (조직 검증 후) | ✅ (조직 검증 후) |
| **"FDA 인증 소프트웨어"** | ❌ 해당 없음 | ❌ 해당 없음 |

---

## v1.x — 할 수 있는 것 / 없는 것

### 할 수 있는 것

- WinNonlin과 수치적으로 동등한 NCA 및 BE 결과 산출
- 모든 실행에 대해 `audit.json` + `audit.md` + 재현 스크립트 생성
- 결과를 조직 내부 검토 후 IND/NDA 지원 자료로 활용
- 분석 방법론과 알고리즘 버전을 투명하게 문서화

### 할 수 없는 것

- "21 CFR Part 11 compliant 소프트웨어"를 주장할 수 없습니다.
- 전자서명(Electronic Signature) 기능이 없습니다.
- Append-only hash-chained Audit Trail이 없습니다.
- WORM 스토리지 백엔드가 없습니다.
- 역할 기반 접근 통제(RBAC)가 없습니다.

> **v1.x에서 올바른 표현**: "pk-copilot v1.x는 audit-ready 산출물을 생성하며,
> 재현 가능한 분석을 지원합니다. 21 CFR Part 11 전자 기록 요건을 충족하는
> 기술적 통제는 v2.0에서 제공됩니다."

---

## v2.0 — 기술적 통제 제공 범위

v2.0은 다음 Part 11 기술적 통제를 구현합니다:

- **§11.10(e) Audit Trail**: Append-only, SHA-256 hash-chained JSONL 감사 로그
- **§11.50 / §11.200 Electronic Signatures**: Ed25519 + TOTP 2단계 인증
- **§11.10(d)(g) Access Control**: RBAC (Viewer / Analyst / Approver / Admin)
- **§11.10(c) Record Retention**: WORM 스토리지 백엔드 (AWS S3 Object Lock 등)
- **§11.10(a) System Validation**: IQ/OQ/PQ 패키지 제공

### v2.0에서도 할 수 없는 것

Part 11 준수는 소프트웨어 단독으로 달성 불가능합니다. 사용자 조직이 반드시 갖춰야 할 사항:

- 계정 관리, 교육, 변경 통제, 일탈 처리 SOP 작성 및 승인
- 사용자 교육 기록 유지
- IQ/OQ/PQ 검증 실행 및 검증 보고서 승인
- 감사 로그 주기적 검토
- 물리적 보안 및 네트워크 보안

> **v2.0에서 올바른 표현**: "pk-copilot v2.0은 21 CFR Part 11 §11.10(e)의
> Audit Trail 요건을 충족하는 기술적 통제를 구현합니다."

> **절대 금지**: "pk-copilot은 21 CFR Part 11 compliant 소프트웨어입니다."
> "pk-copilot은 FDA Part 11 인증을 받았습니다."

---

## 공식 면책 고지 (docs/10-21cfr-part11.md §16)

사용자가 규제 제출 적합성을 묻는 경우, 다음 고지를 반드시 제시하십시오:

```
────────────────────────────────────────────────────────────────
21 CFR Part 11 관련 고지

pk-copilot v2.0은 21 CFR Part 11(전자 기록 및 전자서명)의 요건을
지원하기 위한 기술적 통제를 제공합니다. 여기에는 추가 전용(append-only)
해시 체인 감사 추적, 2단계 인증 기반 Ed25519 전자서명, 역할 기반
접근 통제, WORM 스토리지 백엔드가 포함됩니다.

그러나 21 CFR Part 11 준수는 소프트웨어 도구 단독이 아닌
품질 시스템 전체의 속성입니다. pk-copilot 설치만으로는
Part 11 준수가 성립되지 않습니다.

사용자 조직은 다음에 대한 책임을 집니다:
  - 계정 관리, 교육, 변경 통제, 일탈 처리, 기록 보존에 관한 SOP
  - 사용자 교육 기록 유지
  - IQ/OQ/PQ 검증 실행 및 검증 보고서 승인
  - 감사 로그 주기적 검토
  - 물리적 보안 및 네트워크 보안
  - 백업 및 재해 복구 테스트

pk-copilot은 FDA 인증, GxP 인증, 또는 기타 규제 기관 인증을
주장하지 않습니다.

규제 환경에 pk-copilot을 배포하기 전에 반드시 조직의
품질보증(QA) 및 허가 규제(RA) 팀과 협의하십시오.
────────────────────────────────────────────────────────────────
```

---

## 자주 묻는 질문

**Q: v1.x 결과를 IND에 첨부할 수 있습니까?**

v1.x 결과는 WinNonlin과 수치적으로 동등하며 audit-ready 산출물을 포함합니다.
그러나 규제 제출 가능 여부는 조직의 QA 및 RA 팀이 판단해야 합니다.
pk-copilot 자체는 Part 11 전자 기록 요건을 충족하지 않으므로,
v1.x 환경에서는 종이 기록이나 별도의 Part 11 시스템과 병행 사용을 권장합니다.

**Q: v2.0을 설치하면 Part 11 compliant 환경이 됩니까?**

아닙니다. v2.0은 기술적 통제를 제공하지만, Part 11 준수는 SOP + 교육 +
조직 검증의 결합입니다. v2.0 설치 후 반드시 IQ/OQ/PQ를 실행하고
조직 QA 팀의 검증 보고서 승인을 받아야 합니다.

**Q: EMA Annex 11도 적용됩니까?**

v2.0의 기술적 통제는 EMA Annex 11과 21 CFR Part 11을 동시에 고려하여
설계되었습니다. 단, EMA Annex 11 준수 여부도 조직의 전체 시스템 검증에
달려 있습니다. 상세 매핑은 [docs/10-21cfr-part11.md §15](../../docs/10-21cfr-part11.md)를
참조하십시오.

---

*상세 기술 사양: [docs/10-21cfr-part11.md](../../docs/10-21cfr-part11.md)*
