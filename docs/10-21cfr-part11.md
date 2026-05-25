# 10. 21 CFR Part 11 준수 계획 (v2.0)

> **이 문서의 성격**: 이 문서는 규제 의향 문서(Regulatory Intent Document)입니다. v2.0이 제공할 기술적 통제(Technical Controls)와 사용자 조직이 반드시 갖춰야 할 절차적 통제(Procedural Controls)를 명확히 구분합니다. **pk-copilot 단독으로 21 CFR Part 11 준수를 보장할 수 없습니다.**

---

## 목차

1. [21 CFR Part 11 개요](#1-21-cfr-part-11-개요)
2. [Scope Boundary — 책임 경계 (매우 중요)](#2-scope-boundary--책임-경계-매우-중요)
3. [기술적 통제 — v2.0 제공 범위](#3-기술적-통제--v20-제공-범위)
   - 3.1 Audit Trail (§11.10(e))
   - 3.2 Electronic Signatures (§11.50, §11.70, §11.200)
   - 3.3 Access Control / Authority Checks (§11.10(d), §11.10(g))
   - 3.4 Record Retention (§11.10(c))
   - 3.5 System Validation (§11.10(a))
   - 3.6 Operational System Checks (§11.10(f))
   - 3.7 Device Checks (§11.10(h))
4. [절차적 통제 — 사용자 조직 책임](#4-절차적-통제--사용자-조직-책임)
5. [Compliance Matrix](#5-compliance-matrix)
6. [Electronic Signature Workflow](#6-electronic-signature-workflow)
7. [Audit Log 포맷 사양](#7-audit-log-포맷-사양)
8. [Hash Chain 검증 알고리즘](#8-hash-chain-검증-알고리즘)
9. [Signature Lock Workflow](#9-signature-lock-workflow)
10. [암호학적 키 관리](#10-암호학적-키-관리)
11. [백업 / 복원 절차](#11-백업--복원-절차)
12. [시간 동기화 (NTP) 요구사항](#12-시간-동기화-ntp-요구사항)
13. [v2.0에서 다루지 않는 항목](#13-v20에서-다루지-않는-항목)
14. [Compliance Audit Readiness Package](#14-compliance-audit-readiness-package)
15. [EMA Annex 11 / GCP 교차 참조](#15-ema-annex-11--gcp-교차-참조)
16. [공식 면책 고지 (Disclaimer)](#16-공식-면책-고지-disclaimer)

---

## 1. 21 CFR Part 11 개요

### 규정 원문 위치

- **Title 21, Code of Federal Regulations, Part 11**: *Electronic Records; Electronic Signatures* (FDA, 최종 규칙 1997년 발효)
- URL: `https://www.ecfr.gov/current/title-21/chapter-I/subchapter-A/part-11`

### Subpart 구조

| Subpart | 제목 | 주요 조항 |
|---|---|---|
| **Subpart A** | General Provisions | §11.1 범위, §11.2 구현, §11.3 정의 |
| **Subpart B** | Electronic Records | §11.10 Open systems 통제, §11.30 Closed systems, §11.50 서명 구성요소 |
| **Subpart C** | Electronic Signatures | §11.100 일반, §11.200 서명 컴포넌트, §11.300 신원 확인 |

### 핵심 정의 (§11.3)

- **Electronic Record**: 전자적 매체에 저장되거나 컴퓨터 시스템에 의해 생성·수정·유지·보관·검색·전송되는 텍스트, 그래픽, 데이터, 오디오, 기록
- **Electronic Signature**: 개인에게 귀속되며 해당 개인에 의해 실행·채택된 전자적 형태의 기호 모음
- **Audit Trail**: 시스템 활동에 대한 연대기적(chronological) 기록

### EMA Annex 11 동등성

EMA GMP Annex 11 "Computerised Systems" (2011)는 EU에서 21 CFR Part 11에 대응하는 규정입니다. 주요 대응 관계:

| 21 CFR Part 11 | EMA Annex 11 |
|---|---|
| §11.10(e) — Audit Trail | §9 — Audit Trails |
| §11.10(d) — Access Control | §12 — Security |
| §11.50 — E-Signature components | §14 — Electronic Signature |
| §11.10(a) — System Validation | §4 — Validation |
| §11.10(c) — Record Retention | §17 — Archiving |

pk-copilot v2.0의 기술적 통제 설계는 두 규정을 동시에 고려하여 설계되었으나, **EMA Annex 11 준수 여부는 사용자 조직의 전체 시스템 검증에 의존합니다.**

---

## 2. Scope Boundary — 책임 경계 (매우 중요)

### 핵심 원칙

> **21 CFR Part 11 준수(Compliance)는 시스템 + 절차 + 조직의 결합입니다. 소프트웨어 도구 단독으로는 달성 불가능합니다.**

FDA 21 CFR Part 11은 전자 기록 시스템을 *운영하는 조직* 전체에 적용됩니다. pk-copilot은 기술적 통제를 제공하는 도구이지, 조직의 품질 시스템을 대체하지 않습니다.

### 책임 경계 다이어그램

```
┌─────────────────────────────────────────────────────────────────┐
│                     Part 11 준수 = A + B                        │
├──────────────────────────┬──────────────────────────────────────┤
│  A. 기술적 통제            │  B. 절차적 통제                       │
│  (pk-copilot v2.0 제공)   │  (사용자 조직 책임)                    │
│                          │                                      │
│  - Audit Trail           │  - SOP 작성 및 승인                   │
│  - Electronic Signatures │  - 사용자 교육 및 교육 기록 유지          │
│  - RBAC Access Control   │  - 계정 생성·비활성화 절차              │
│  - Record Retention      │  - 주기적 감사 로그 검토                │
│  - Hash Chain Integrity  │  - 변경 통제(Change Control) 절차       │
│  - System Validation Pkg │  - 일탈 처리(Deviation Handling)        │
│  - Operational Checks    │  - 백업/재해복구 계획 수립              │
│  - Device Logging        │  - 물리적 보안                         │
│                          │  - 인사 관리 및 신원 조회              │
└──────────────────────────┴──────────────────────────────────────┘
```

### v1 vs v2 메시징 차이

| 버전 | 규제 포지션 | 허용되는 주장 |
|---|---|---|
| **v1.0** | 규제 미주장 | "audit-ready 산출물 생성", "재현 가능한 분석" |
| **v2.0** | 기술적 통제 제공 | "Part 11 §11.10(e) Audit Trail 기술 통제 구현", "Part 11 호환 전자서명 기능 제공" |
| **절대 금지** | — | "pk-copilot는 21 CFR Part 11 compliant 소프트웨어입니다" (조직 검증 없이) |

### 올바른 표현 예시

```
올바름: "pk-copilot v2.0은 21 CFR Part 11 §11.10(e)의 Audit Trail 요건을
         충족하는 기술적 통제를 구현합니다."

올바름: "pk-copilot v2.0 enables Part 11-compliant workflows when deployed
         within a validated quality system."

잘못됨: "pk-copilot is 21 CFR Part 11 compliant."

잘못됨: "pk-copilot은 FDA Part 11 인증을 받았습니다."
```

---

## 3. 기술적 통제 — v2.0 제공 범위

### 3.1 Audit Trail (§11.10(e))

**규정 요건**: 운영자가 생성·수정·삭제한 기록의 컴퓨터 생성 날짜/시간 감사 추적을 보안 방식으로 기록. 기록의 권한 없는 수정 또는 삭제를 방지.

#### 구현: Append-Only, Hash-Chained Log

`src/pkplugin/compliance/part11.py` 구현 사양:

- **저장 형식**: JSONL (JSON Lines) — 한 줄 = 한 이벤트
- **추가 전용(Append-Only)**: 파일 열기 모드 `'a'` 고정, 기존 항목 수정 불가
- **Hash Chain**: 각 레코드의 `prev_hash` 필드가 직전 레코드의 `this_hash`를 포함
- **HMAC**: 각 레코드에 서버 측 HMAC-SHA256 서명 포함 (서버 키는 HSM 또는 환경변수 보호)

#### 6 필드 강제

모든 감사 이벤트는 다음 6개 필드를 반드시 포함합니다:

| 필드 | 설명 | §11.10(e) 대응 |
|---|---|---|
| `user.id` | **WHO** — 인증된 사용자 신원 | 작성자 식별 |
| `action` | **WHAT** — 수행된 작업 | 이벤트 내용 |
| `timestamp_utc` | **WHEN** — NTP 동기화 UTC 타임스탬프 | 날짜/시간 도장 |
| `run_id` | **WHERE** — 분석 실행 컨텍스트 | 레코드 위치 |
| `reason` | **WHY** — 작업 수행 사유 | 변경 사유 |
| `before` / `after` | **BEFORE→AFTER** — 상태 델타 | 수정 전/후 |

#### 변조 감지

Hash Chain 무결성: 임의의 과거 레코드를 수정하면 해당 레코드부터 최신 레코드까지 모든 `prev_hash` 값이 불일치하여 감지됩니다.

```
Record N-1: {this_hash: "sha256:abc..."}
Record N:   {prev_hash: "sha256:abc...", ...}   ← 이 링크가 끊기면 변조 감지
```

검증 명령: `pkplugin audit verify --run-id <run_id>`

---

### 3.2 Electronic Signatures (§11.50, §11.70, §11.200)

**규정 요건 (§11.50)**: 전자서명은 (a) 서명자 성명, (b) 서명 날짜/시간, (c) 서명의 의미를 포함해야 함.

**규정 요건 (§11.70)**: 전자서명은 고유하게 식별 가능한 개인에게 연결되어야 하며 위조 불가해야 함.

**규정 요건 (§11.200(a))**: 생물지표 기반이 아닌 전자서명은 (1) 최소 두 개의 식별 컴포넌트 사용 또는 (2) 한 세션 외 서명 시 두 컴포넌트 사용.

#### 구현 사양

**서명 알고리즘**: Ed25519 (Elliptic Curve 기반, NIST 권장)

**2단계 인증**: 서명 이벤트마다 다음 두 요소 모두 요구:
1. 사용자 비밀키 (Ed25519 private key, 암호화된 키링에 저장)
2. TOTP 코드 (RFC 6238) 또는 Hardware Key (YubiKey FIDO2)

**서명 대상 (Canonical Run Hash)**: 분석 결과의 SHA-256 해시를 서명 대상으로 합니다.

```python
# canonical_hash 계산 (part11.py)
canonical = json.dumps(run_record, sort_keys=True, separators=(',', ':'))
canonical_hash = hashlib.sha256(canonical.encode()).hexdigest()
```

**서명 매니페스트 3필드 (§11.50 요건)**:

```json
{
  "signed_by": "Kim Mingul <kimmingul@example.com>",
  "timestamp_utc": "2026-05-25T10:30:00Z",
  "meaning": "approved"
}
```

**허용 `meaning` 값**: `"authored"` | `"reviewed"` | `"approved"`

---

### 3.3 Access Control / Authority Checks (§11.10(d), §11.10(g))

**규정 요건 (§11.10(d))**: 시스템에 접근을 제한하고 시스템을 사용할 권한이 있는 개인만 접근하도록 절차 마련.

**규정 요건 (§11.10(g))**: 입력 또는 작업을 수행할 권한이 있는 개인만 시스템 입력을 할 수 있도록 권한 검사.

#### RBAC 역할 정의

`src/pkplugin/compliance/access.py` 구현:

| 역할 | 설명 | 허용 작업 |
|---|---|---|
| **Viewer** | 읽기 전용 | 결과 조회, 감사 로그 열람, 리포트 다운로드 |
| **Analyst** | 분석 수행 | Viewer + 데이터 로드, NCA/PK/PD 실행, Draft 서명(authored) |
| **Approver** | 검토·승인 | Analyst + Reviewed 서명, Approved 서명 |
| **Admin** | 시스템 관리 | 전체 + 계정 관리, 잠금 해제(서명 필요), 역할 할당 |

#### 역할별 서명 권한

| 서명 의미 | 최소 필요 역할 |
|---|---|
| `authored` | Analyst |
| `reviewed` | Approver |
| `approved` | Approver |
| Lock 해제 (Admin Unlock) | Admin + 서명된 해제 사유 필수 |

#### 세션 및 계정 정책

- **세션 타임아웃**: 비활성 30분 후 자동 로그아웃 (기본값, 조직 설정으로 단축 가능, 연장 불가)
- **계정 잠금**: 연속 5회 인증 실패 시 자동 잠금 — Admin 수동 해제 필요
- **동시 세션**: 동일 사용자 동시 세션 1개로 제한 (기본값)
- **비밀번호 정책**: 최소 12자, 대소문자+숫자+특수문자 조합 — **조직 SOP에서 정의**

---

### 3.4 Record Retention (§11.10(c))

**규정 요건**: 전자 기록은 인간이 읽을 수 있는 형태 및 전자 형태로 규제 요건이 요구하는 기간 동안 보호·검색 가능하게 유지.

#### WORM 스토리지 백엔드

`src/pkplugin/compliance/retention.py` 구현:

| 백엔드 | 설정 키 | WORM 메커니즘 | 비고 |
|---|---|---|---|
| **AWS S3 Object Lock** | `backend: s3_object_lock` | Governance / Compliance mode | 권장 — FDA 검사 경험 다수 |
| **Azure Blob Immutability** | `backend: azure_immutable` | Time-based retention policy | Azure GovCloud 사용 시 |
| **로컬 append-only 파일** | `backend: local_append_only` | OS-level append-only flag | 개발/소규모 환경 |
| **사용자 정의** | `backend: custom` | 사용자 구현 RetentionBackend | 플러그인 인터페이스 제공 |

#### 보존 기간 설정

```python
# pyproject.toml 또는 환경 변수
PKPLUGIN_RETENTION_YEARS=10      # 임상시험 기록 — IND/NDA 표준
PKPLUGIN_RETENTION_BACKEND=s3_object_lock
PKPLUGIN_RETENTION_MODE=compliance   # 또는 governance
```

**주의**: 실제 보존 기간은 **규제 제출물 유형 및 해당 지역 법규**에 따라 다릅니다. 21 CFR §312.62는 IND 관련 기록에 대해 연구 완료 후 2년 보존을 요구하지만, 조직 정책은 더 긴 기간을 적용하는 경우가 일반적입니다.

#### 레거시 Run Bundle 재봉인 (Migration Path)

v1.x에서 생성된 기존 분석 번들은 `pkplugin audit reseal` 명령으로 v2.0 WORM 스토리지로 마이그레이션 가능합니다. 재봉인 이벤트 자체가 감사 로그에 기록됩니다.

---

### 3.5 System Validation (§11.10(a))

**규정 요건**: 시스템이 정확성·신뢰성·일관적 의도 성능을 위해 적합하게 검증되었고 데이터 레코드를 식별할 수 있는 기능이 있음을 보장.

#### 검증 패키지 (Validation Package)

상세는 [08-validation-strategy.md](08-validation-strategy.md) 참조.

| 문서 | 내용 | 인수 기준 |
|---|---|---|
| **IQ (Installation Qualification)** | 설치 스크립트, 환경 검증 | 의존성 버전 고정(uv.lock) + 체크섬 검증 통과 |
| **OQ (Operational Qualification)** | 기능 동작 검증 | 자동화 테스트 100% pass, 알려진 입력→출력 일치 |
| **PQ (Performance Qualification)** | 운영 성능 검증 | Golden dataset 매트릭스 6 significant figures 일치 |

#### Validation Master Plan (VMP)

v2.0 출시 시 제공:
- 시스템 설명 및 검증 범위
- 위험 평가 (Risk Assessment)
- 테스트 전략 및 트레이서빌리티 매트릭스
- 검증 완료 기준
- 유지보수 및 재검증 기준 (Change Control 연동)

---

### 3.6 Operational System Checks (§11.10(f))

**규정 요건**: 작업 시퀀싱 장치 — 유효한 작업 단계만 허용하도록 시스템이 시퀀싱 강제.

#### 구현: 상태 머신 기반 시퀀싱

분석 Run은 다음 상태 머신을 따릅니다. **역방향 전환은 불가능합니다.**

```
Draft → Authored → Reviewed → Approved (Locked)
```

| 전환 | 필요 조건 | 위반 시 |
|---|---|---|
| Draft → Authored | Analyst 역할 + `sign_record(meaning="authored")` | 서명 거부 |
| Authored → Reviewed | Approver 역할 + 재인증 + `sign_record(meaning="reviewed")` | 서명 거부 |
| Reviewed → Approved | Approver 역할 + 재인증 + `sign_record(meaning="approved")` | 서명 거부 |
| Approved → Locked | `lock_run()` 자동 호출 | — |

**서명 전 결과 수정 불가**: Authored 상태 이후 분석 결과 파일 수정 시도는 서명 무효화 경고와 함께 차단됩니다.

---

### 3.7 Device Checks (§11.10(h))

**규정 요건**: 입력 또는 작업의 원점으로서 장치 점검을 사용하는 경우, 해당 장치(예: 터미널)의 유효한 원점 확인 보장.

#### 구현: 워크스테이션 로깅

모든 감사 이벤트의 `workstation` 필드에 다음을 기록합니다:

```json
{
  "workstation": {
    "hostname": "analyst-ws-042",
    "ip": "192.168.1.105",
    "platform": "darwin",
    "python_env_hash": "sha256:..."
  }
}
```

- 호스트명 및 IP 주소 자동 수집 (사용자 오버라이드 불가)
- 실행 환경 해시 (설치된 패키지 버전 집합의 SHA-256)

---

## 4. 절차적 통제 — 사용자 조직 책임

아래 항목은 **pk-copilot이 제공하지 않으며**, 사용자 조직이 자체적으로 갖춰야 합니다. 도구가 이를 대신할 수 없습니다.

### 필수 SOP 목록

| SOP 번호 | 제목 | 핵심 내용 |
|---|---|---|
| SOP-IT-001 | 컴퓨터 시스템 계정 관리 | 계정 생성, 권한 부여, 비활성화 절차, 퇴직자 처리 |
| SOP-IT-002 | 비밀번호 및 인증 관리 | 비밀번호 복잡도, 변경 주기, MFA 설정 |
| SOP-QA-001 | 변경 통제 (Change Control) | 소프트웨어 업데이트 승인 절차, 재검증 기준 |
| SOP-QA-002 | 감사 로그 주기 검토 | 검토 주기(최소 분기), 이상 발견 시 일탈 처리 |
| SOP-QA-003 | 일탈 및 CAPA 처리 | 시스템 일탈 탐지, 원인 분석, 교정 조치 |
| SOP-TR-001 | 시스템 사용자 교육 | 교육 내용, 인증 시험, 교육 기록 보존 |
| SOP-IT-003 | 백업 및 재해 복구 | 백업 주기, 복원 테스트, RTO/RPO 정의 |
| SOP-QA-004 | 기록 보존 및 폐기 | 보존 기간별 기록 분류, 승인된 폐기 절차 |

### 조직 책임 체크리스트

조직이 Part 11 환경을 운영하기 전에 반드시 확인해야 할 사항:

```
[ ] 시스템 책임자(System Owner) 지정 및 문서화
[ ] SOP-IT-001 ~ SOP-QA-004 작성, 검토, 승인 완료
[ ] 모든 시스템 사용자 SOP-TR-001 교육 완료 및 기록 보존
[ ] RBAC 역할 할당 승인 문서 (사용자별 승인된 역할)
[ ] pk-copilot v2.0 IQ/OQ/PQ 검증 실행 및 검증 보고서 서명 완료
[ ] WORM 스토리지 백엔드 구성 및 테스트 완료
[ ] 백업/복원 절차 테스트 및 결과 문서화
[ ] 감사 로그 주기 검토 일정 수립 (SOP-QA-002)
[ ] 변경 통제 절차 적용 대상에 pk-copilot 포함 확인
[ ] 네트워크 보안 정책 (TLS, 방화벽) 수립 및 문서화
[ ] 물리적 보안 구역 접근 통제 문서화
[ ] 비상시 시스템 접근 절차 (Break-glass) 문서화
```

---

## 5. Compliance Matrix

21 CFR Part 11의 각 하위 요건과 pk-copilot v2.0 구현 및 조직 책임을 매핑합니다.

| 조항 | 요건 (요약) | pk-copilot v2.0 구현 | 조직 책임 | 검증 방법 |
|---|---|---|---|---|
| **§11.10(a)** | 시스템 검증 (정확성·신뢰성) | IQ/OQ/PQ 패키지 제공; Golden dataset 자동 검증 | 검증 실행 및 보고서 서명; 재검증 트리거 정의 | OQ 자동 테스트 전체 pass; PQ golden diff ≤ 1e-6 |
| **§11.10(b)** | 인간-읽기 가능 기록 생성·유지 | HTML/PDF 리포트, audit.md 생성 | 출력물 장기 보관 확인 | 리포트 렌더링 통합 테스트 |
| **§11.10(c)** | 정확하고 완전한 기록 복사 가능 | Run bundle ZIP 내보내기, WORM 백엔드 | 주기적 복원 테스트; 저장 미디어 관리 | `pkplugin audit export`; 복원 테스트 체크리스트 |
| **§11.10(d)** | 시스템 접근 제한 | RBAC (Viewer/Analyst/Approver/Admin); 세션 타임아웃; 계정 잠금 | SOP-IT-001 계정 관리; 역할 최소 권한 원칙 적용 | 권한 경계 침범 시도 자동 테스트 |
| **§11.10(e)** | 컴퓨터 생성 날짜/시간 감사 추적 | Append-only JSONL; SHA-256 Hash Chain; 6필드 강제; HMAC; NTP 동기화 | 감사 로그 주기 검토 (SOP-QA-002); 이상 보고 | `pkplugin audit verify`; chain 무결성 자동 테스트 |
| **§11.10(f)** | 작업 시퀀싱 강제 | 상태 머신 (Draft→Authored→Reviewed→Approved); 역방향 전환 차단 | 워크플로우 일탈 시 일탈 처리 | 시퀀싱 위반 시도 단위 테스트 |
| **§11.10(g)** | 권한자만 입력 허용 | 역할 기반 MCP 도구 접근 제어; 서명 시 재인증 | 역할 할당 승인; 최소 권한 원칙 | 역할 권한 매트릭스 자동 테스트 |
| **§11.10(h)** | 장치 점검 | 워크스테이션 식별 정보 자동 수집 (hostname, IP, env hash) | 인가된 장치 목록 관리 | 감사 로그 workstation 필드 검사 |
| **§11.10(i)** | 교육받은 개인이 시스템 사용 | 역할 교육 완료 확인 체크리스트 템플릿 제공 | SOP-TR-001 교육 실시 및 기록 보존 | 교육 기록 검토 — 조직 감사 |
| **§11.10(j)** | 계정 관리 문서화 | 역할 변경 이력 감사 로그 기록 | SOP-IT-001 계정 수명주기 관리 | 감사 로그에서 역할 변경 이벤트 확인 |
| **§11.10(k)** | 적절한 통제 수행 (명확한 책임) | Admin 역할 잠금 해제 시 서명 강제 | 관리 책임자 지정 및 문서화 | Admin 작업 감사 로그 검토 |
| **§11.50(a)** | 서명 컴포넌트: 이름, 날짜/시간, 의미 | 서명 매니페스트 3필드 (signed_by, timestamp_utc, meaning) 강제 | 서명자가 자신의 신원임을 SOP로 확인 | 서명 매니페스트 스키마 자동 검증 |
| **§11.50(b)** | 서명이 기록과 연결 | Ed25519 서명 대상 = canonical run hash; 분리 서명 파일이 run bundle에 포함 | 서명-기록 연결 검토 절차 | 서명 검증 자동 테스트 (`pkplugin verify-sig`) |
| **§11.70** | 서명의 위조 불가성 | Ed25519 공개키 암호학; 서명 분리 파일 + run bundle hash 연결 | 개인키 보안 관리 절차 (SOP-IT-002) | 서명 변조 감지 단위 테스트 |
| **§11.100(a)** | 서명은 고유하게 개인 귀속 | 사용자당 고유 Ed25519 키페어; 키 공유 기술적 차단 | 키페어 1인 1키 정책 SOP | 사용자 키 고유성 검증 |
| **§11.200(a)** | 2요소 인증 (서명 이벤트마다) | TOTP (RFC 6238) + 개인키; YubiKey FIDO2 지원 | MFA 장치 배포 및 분실 처리 절차 | 서명 이벤트 2FA 우회 시도 테스트 |
| **§11.300** | 서명 코드 통제 (분실·도용 방지) | 개인키 암호화 저장; 잘못된 TOTP 5회 계정 잠금 | 분실 신고 절차; 즉시 키 폐기 SOP | 잠금 정책 자동 테스트 |

---

## 6. Electronic Signature Workflow

### 단계별 워크플로우

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1. Analyst — 분석 수행 및 Draft 생성                   │
│                                                             │
│  $ pkplugin run-nca --dataset data.csv --config config.json │
│  → run_id: 2026-05-25-042                                   │
│  → 상태: Draft                                              │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2. Analyst — "Authored" 서명                          │
│                                                             │
│  $ pkplugin sign --run-id 2026-05-25-042 \                  │
│      --meaning authored \                                   │
│      --user analyst@example.com                             │
│                                                             │
│  [Authenticate] Enter TOTP code: ______                     │
│  [Confirm] Sign run 2026-05-25-042 as "authored"? [y/N]: y  │
│                                                             │
│  → Signed by: Kim Analyst <analyst@example.com>             │
│  → Timestamp: 2026-05-25T10:15:00Z                          │
│  → Meaning: authored                                        │
│  → Signature: ed25519:3f8a2b...                             │
│  → 상태: Authored (awaiting review)                         │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3. Approver — "Reviewed" 서명 (재인증 필수)            │
│                                                             │
│  $ pkplugin sign --run-id 2026-05-25-042 \                  │
│      --meaning reviewed \                                   │
│      --user approver@example.com                            │
│                                                             │
│  [Re-authenticate required for signing event]               │
│  [Authenticate] Enter TOTP code: ______                     │
│  [Confirm] Sign run 2026-05-25-042 as "reviewed"? [y/N]: y  │
│                                                             │
│  → Signed by: Lee Approver <approver@example.com>           │
│  → Timestamp: 2026-05-25T14:30:00Z                          │
│  → Meaning: reviewed                                        │
│  → 상태: Reviewed (awaiting approval)                       │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4. Final Approver — "Approved" 서명 + Lock (재인증)    │
│                                                             │
│  $ pkplugin sign --run-id 2026-05-25-042 \                  │
│      --meaning approved \                                   │
│      --user final-approver@example.com                      │
│                                                             │
│  [Re-authenticate required for signing event]               │
│  [Authenticate] Enter TOTP code: ______                     │
│  [Confirm] Sign run 2026-05-25-042 as "approved"? [y/N]: y  │
│                                                             │
│  → Signed by: Park Director <final-approver@example.com>    │
│  → Timestamp: 2026-05-25T16:00:00Z                          │
│  → Meaning: approved                                        │
│  → Initiating lock_run...                                   │
│  → WORM seal: s3://pk-records/runs/2026-05-25-042.bundle    │
│  → 상태: Approved + Locked (immutable)                      │
└─────────────────────────────────────────────────────────────┘
```

### MCP 도구 호출 순서

```python
# Step 2: Analyst 서명
sign_record(
    run_id="2026-05-25-042",
    signer_identity="analyst@example.com",
    meaning="authored",
    auth_token="<TOTP-code>"
)

# Step 3: Approver 검토 서명
sign_record(
    run_id="2026-05-25-042",
    signer_identity="approver@example.com",
    meaning="reviewed",
    auth_token="<TOTP-code>"
)

# Step 4: 최종 승인 서명 — lock_run은 approved 서명 후 자동 호출
sign_record(
    run_id="2026-05-25-042",
    signer_identity="final-approver@example.com",
    meaning="approved",
    auth_token="<TOTP-code>"
)
# → lock_run(run_id="2026-05-25-042", lock_reason="Approved signature completed") 자동 실행
```

---

## 7. Audit Log 포맷 사양

### 단일 감사 이벤트 JSON Schema

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "prev_hash": "sha256:a3f2c1d4e5b6789012345678901234567890abcdef1234567890abcdef123456",
  "this_hash": "sha256:b4e3d2c1f0a9876543210987654321098765fedcba0987654321fedcba098765",
  "timestamp_utc": "2026-05-25T10:15:00.123456Z",
  "ntp_source": "pool.ntp.org (offset: +0.012s)",
  "user": {
    "id": "analyst@example.com",
    "display_name": "Kim Analyst",
    "role": "analyst",
    "auth_method": "totp+ed25519",
    "session_id": "sess_7f3a2b1c"
  },
  "action": "run_nca",
  "run_id": "2026-05-25-042",
  "reason": "Initial NCA analysis for Study ABC-101 SAD cohort",
  "before": {
    "run_state": null,
    "result_hash": null
  },
  "after": {
    "run_state": "draft",
    "result_hash": "sha256:c5d4e3f2a1b0987654321098765432109876543210fedcba9876543210fedcba"
  },
  "workstation": {
    "hostname": "analyst-ws-042",
    "ip": "192.168.1.105",
    "platform": "darwin",
    "os_version": "25.5.0",
    "python_env_hash": "sha256:d6e5f4a3b2c1098765432109876543210987654321fedcba098765fedcba0987"
  },
  "pkplugin_version": "2.0.0",
  "hmac": "hmac-sha256:e7f6a5b4c3d2e1f0987654321098765432109876543210fedcba0987654321fe"
}
```

### 필드 설명

| 필드 | 타입 | 설명 | 필수 |
|---|---|---|---|
| `event_id` | UUID v4 | 이벤트 고유 식별자 | 필수 |
| `prev_hash` | `sha256:...` | 직전 레코드의 `this_hash` (첫 레코드는 `"sha256:GENESIS"`) | 필수 |
| `this_hash` | `sha256:...` | 이 레코드 전체(hmac 필드 제외)의 SHA-256 | 필수 |
| `timestamp_utc` | ISO 8601 + microseconds + Z | NTP 동기화 UTC 시각 | 필수 |
| `ntp_source` | string | 사용된 NTP 서버 및 시간 오차 | 필수 |
| `user.id` | string | 인증된 사용자 이메일/ID | 필수 |
| `user.auth_method` | string | 인증 방법 (totp+ed25519 등) | 필수 |
| `action` | string enum | 수행된 작업 식별자 | 필수 |
| `run_id` | string | 분석 실행 ID | 필수 |
| `reason` | string | 작업 수행 사유 (빈 문자열 허용 안 됨) | 필수 |
| `before` | object | 이벤트 전 상태 스냅샷 | 필수 |
| `after` | object | 이벤트 후 상태 스냅샷 | 필수 |
| `workstation` | object | 워크스테이션 식별 정보 | 필수 |
| `hmac` | `hmac-sha256:...` | 서버 HMAC 키로 이 레코드 서명 | 필수 |

### 허용 `action` 값

```
validate_dataset | run_nca | run_be | fit_pk_model | fit_pd_model |
sign_record | lock_run | unlock_run | role_change | account_create |
account_deactivate | audit_export | key_rotate | system_config_change
```

---

## 8. Hash Chain 검증 알고리즘

### 알고리즘 설명

```python
def verify_audit_chain(audit_log_path: str) -> ChainVerificationResult:
    """
    감사 로그 JSONL 파일의 hash chain 무결성을 검증합니다.
    
    Returns:
        ChainVerificationResult:
            .intact: bool — chain 전체 무결성
            .broken_at: int | None — 최초 무결성 위반 레코드 인덱스
            .tampered_event_ids: list[str] — 위변조 의심 event_id 목록
            .total_records: int — 검증한 총 레코드 수
    """
    records = []
    with open(audit_log_path, 'r') as f:
        for line in f:
            records.append(json.loads(line))
    
    prev_hash = "sha256:GENESIS"
    
    for idx, record in enumerate(records):
        # 1. prev_hash 연결 검증
        if record["prev_hash"] != prev_hash:
            return ChainVerificationResult(
                intact=False,
                broken_at=idx,
                tampered_event_ids=[record["event_id"]]
            )
        
        # 2. this_hash 재계산 검증
        record_for_hashing = {k: v for k, v in record.items() 
                               if k not in ("this_hash", "hmac")}
        canonical = json.dumps(record_for_hashing, sort_keys=True, separators=(',', ':'))
        computed_hash = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
        
        if computed_hash != record["this_hash"]:
            return ChainVerificationResult(intact=False, broken_at=idx, ...)
        
        # 3. HMAC 검증 (서버 키 필요)
        if not verify_hmac(record, server_hmac_key):
            return ChainVerificationResult(intact=False, broken_at=idx, ...)
        
        prev_hash = record["this_hash"]
    
    return ChainVerificationResult(intact=True, total_records=len(records))
```

### CLI 검증 명령

```bash
# 단일 run 감사 로그 검증
pkplugin audit verify --run-id 2026-05-25-042

# 전체 감사 로그 검증
pkplugin audit verify --all

# 특정 날짜 범위 검증
pkplugin audit verify --from 2026-01-01 --to 2026-05-25

# 규제 제출용 검증 보고서 생성
pkplugin audit verify --all --report-format pdf --output audit-integrity-report.pdf
```

### 예상 출력

```
[AUDIT CHAIN VERIFICATION]
Log file: pk_runs/2026-05-25-042/audit.jsonl
Records:  847 entries
Period:   2026-05-25T08:00:00Z → 2026-05-25T16:05:00Z

Chain integrity:   INTACT
HMAC verification: PASSED (all 847 records)
NTP drift check:   PASSED (max drift: 0.023s < threshold 1.0s)

RESULT: VERIFICATION PASSED
```

---

## 9. Signature Lock Workflow

### `lock_run` MCP 도구

```python
def lock_run(run_id: str, lock_reason: str) -> LockResult
```

`approved` 서명 완료 후 자동으로 호출됩니다. 수동 호출도 가능하나, Approved 상태가 아니면 실패합니다.

### Lock 후 변경되는 사항

| 항목 | Lock 전 | Lock 후 |
|---|---|---|
| 결과 파일 수정 | Approved 이전 가능 | **불가능** (OS-level read-only + WORM) |
| 서명 추가 | 가능 (상태에 따라) | **불가능** |
| 감사 로그 추가 | 가능 | **불가능** (별도 Admin 잠금 해제 로그로 기록) |
| Run bundle 삭제 | 역할에 따라 | **불가능** (WORM 보존 기간 내) |

### Lock 해제 (Admin Unlock)

Lock 해제는 **매우 예외적인 상황**에만 허용되며, 절차가 엄격합니다:

```bash
pkplugin unlock --run-id 2026-05-25-042 \
    --admin-user admin@example.com \
    --reason "Data entry error in subject S003 confirmed by QA — Deviation DEV-2026-042"
```

1. Admin 역할 필수
2. `--reason` 필드 최소 50자 이상 (빈 사유 불가)
3. Admin이 서명 (TOTP + Ed25519) 필수
4. 잠금 해제 이벤트 자체가 감사 로그에 서명과 함께 기록
5. 잠금 해제 후 재분석 → 전체 서명 워크플로우 재시작 필수

---

## 10. 암호학적 키 관리

### 사용자 키페어

- **알고리즘**: Ed25519 (256-bit, NIST SP 800-186 권장)
- **키 생성**: 계정 생성 시 서버에서 생성 또는 사용자 로컬 생성 후 공개키만 등록
- **개인키 보호**:
  - 키링 암호화: AES-256-GCM, 키 유도: PBKDF2-HMAC-SHA256 (iterations ≥ 600,000)
  - YubiKey PIV 또는 FIDO2 기반 하드웨어 보안 키 지원
- **키 공유 금지**: 개인키 공유는 Part 11 §11.100(c) 위반 — 기술적으로 차단 불가하므로 SOP 및 교육으로 보완

### 공개키 배포 및 폐기

```bash
# 공개키 등록 (Admin 수행)
pkplugin key register --user analyst@example.com --pubkey analyst.pub

# 키 폐기 (분실, 퇴직, 침해 발생 시 — 즉시 실행)
pkplugin key revoke --user analyst@example.com \
    --reason "Employee departure" \
    --effective "2026-05-25T00:00:00Z"
```

폐기된 키로 생성된 서명은 폐기 시점 이후 검증 실패로 표시됩니다. 폐기 이전 서명의 유효성은 유지됩니다.

### 키 교체 정책

| 이벤트 | 교체 시기 | 절차 |
|---|---|---|
| 정기 교체 | 2년마다 | Admin 승인 + 신구 키 중복 유효 기간 30일 |
| 퇴직/역할 변경 | 즉시 | `pkplugin key revoke` + 계정 비활성화 |
| 침해 의심 | 즉시 | 긴급 폐기 → 일탈 보고(SOP-QA-003) |
| 암호 알고리즘 취약점 발견 | 공지 후 60일 내 | 전체 키 재생성 + 기존 서명 재서명 불필요 (타임스탬프 기준 유효) |

### HMAC 서버 키

감사 로그의 HMAC 서버 키는 별도로 관리합니다:

- **보관**: AWS KMS, Azure Key Vault, HashiCorp Vault 또는 HSM
- **접근**: MCP 서버 프로세스만 접근 (환경변수 주입, 파일시스템 노출 금지)
- **교체**: 연간 1회 + 침해 의심 시 즉시

---

## 11. 백업 / 복원 절차

### 백업 대상

| 대상 | 위치 | 백업 주기 |
|---|---|---|
| Run bundles (WORM) | PKPLUGIN_AUDIT_DIR | WORM 특성상 별도 백업 불필요 (단, 이중화 구성 권장) |
| 감사 로그 JSONL | pk_runs/*/audit.jsonl | 실시간 복제 (S3 Cross-Region Replication 등) |
| 공개키 레지스트리 | `compliance/keys/` | 일별 |
| 시스템 설정 | `.mcp.json`, `pyproject.toml` | 변경 시마다 (Git 관리) |

### 복원 절차

```bash
# 1. Run bundle 복원
pkplugin restore --run-id 2026-05-25-042 --from s3://pk-backup/runs/

# 2. 복원 후 chain 무결성 재검증 (필수)
pkplugin audit verify --run-id 2026-05-25-042

# 3. 검증 결과를 복원 SOP 문서에 첨부
# → 복원 이벤트 자체가 감사 로그에 기록됨
```

### 복원 후 필수 확인

1. `pkplugin audit verify` — chain 무결성 PASSED 확인
2. 서명 파일 존재 및 서명 유효성 확인 (`pkplugin verify-sig --run-id ...`)
3. 복원된 결과와 원본 결과의 SHA-256 일치 확인
4. 복원 이벤트를 SOP-IT-003에 따라 문서화

---

## 12. 시간 동기화 (NTP) 요구사항

### 요건

Part 11은 정확한 날짜/시간 기록을 요구합니다(§11.10(e)). pk-copilot은 시스템 클럭에 의존하므로 NTP 동기화가 필수입니다.

### 설정

```bash
# 환경 변수 설정
PKPLUGIN_NTP_SERVER=pool.ntp.org     # 기본값
PKPLUGIN_NTP_MAX_DRIFT_SECONDS=1.0   # 허용 최대 시간 오차 (기본: 1초)
```

### 드리프트 초과 시 동작

| 상황 | 동작 |
|---|---|
| NTP 오차 < 1.0초 | 정상 운영 |
| NTP 오차 1.0 ~ 5.0초 | 경고 메시지 감사 로그 기록, 분석 계속 |
| NTP 오차 > 5.0초 | **분석 차단** — `pkplugin ntp fix` 실행 요구 |
| NTP 서버 응답 없음 | **분석 차단** — 네트워크 연결 또는 내부 NTP 서버 설정 필요 |

### 오프라인 환경 (에어갭)

인터넷이 차단된 GxP 환경에서는 내부 NTP 서버를 설정해야 합니다:

```bash
PKPLUGIN_NTP_SERVER=ntp.internal.example.com
```

내부 NTP 서버가 없는 환경에서 분석을 강제 실행하려면 Admin이 `--allow-no-ntp` 플래그를 명시적으로 승인해야 하며, 이 사실이 감사 로그에 기록됩니다.

---

## 13. v2.0에서 다루지 않는 항목

다음 항목은 v2.0 범위에 포함되지 않으며, **사용자 조직의 책임**입니다:

| 항목 | 이유 / 대안 |
|---|---|
| **물리적 보안** | 서버실, 워크스테이션 물리 접근 통제는 소프트웨어 범위 외 |
| **인사 관리 (배경 조회, 서약서)** | 조직 HR 및 QA 정책 — SOP-TR-001로 보완 |
| **네트워크 보안 (TLS 종단)** | TLS는 고객의 MCP 게이트웨이에서 처리; pk-copilot은 MCP 메시지 내용만 처리 |
| **장기 보존 형식 마이그레이션** | 20-30년 후 파일 형식(JSON, JSONL) 가독성 보장은 조직 IT 아카이빙 정책 |
| **규제 제출물 패키지 조립** | IND/NDA 제출은 조직의 규제 부서 책임 |
| **컴퓨터 시스템 검증 (CSV) 전체 수명주기** | pk-copilot은 IQ/OQ/PQ 패키지를 제공하지만, 전체 CSV 수명주기 관리는 조직 |
| **21 CFR Part 820 (QMS)** | 의료기기 품질 시스템 — pk-copilot 범위 외 |
| **GCP/GLP/GMP 전체 준수** | pk-copilot은 특정 기술 통제를 제공할 뿐, GxP 전체 준수 시스템 아님 |

---

## 14. Compliance Audit Readiness Package

규제 기관 실사(Regulatory Inspection)를 위해 v2.0은 다음 패키지를 제공합니다:

### 제공 문서

| 항목 | 설명 | 비고 |
|---|---|---|
| **System Description** | pk-copilot 시스템 설명서 | 자동 생성 |
| **Validation Package** | IQ/OQ/PQ 실행 보고서 + 검증 매트릭스 | `pkplugin validate --report` |
| **Audit Log Export** | 지정 기간 감사 로그 전체 + chain 검증 보고서 | `pkplugin audit export` |
| **Compliance Matrix** | 이 문서 (10-21cfr-part11.md) | 사람이 읽는 용도 |
| **Signature Manifest Export** | 지정 run의 서명 이력 + 검증 상태 | `pkplugin verify-sig --all` |
| **Sample SOP Templates** | SOP-IT-001~003, SOP-QA-001~004 템플릿 | **템플릿 전용 — 조직 맞춤화 필수** |

### 감사 로그 내보내기

```bash
# 전체 감사 로그 내보내기 (암호화된 ZIP)
pkplugin audit export \
    --from 2026-01-01 \
    --to 2026-05-25 \
    --output audit-export-2026-Q2.zip \
    --verify-chain \
    --encrypt-with inspector-pubkey.pem

# 특정 run만 내보내기
pkplugin audit export --run-id 2026-05-25-042 --output run-042-audit.zip
```

### SOP 템플릿 경고

```
⚠ 주의: pk-copilot이 제공하는 SOP 템플릿은 참조 목적 전용입니다.
  조직의 실제 운영 절차, 책임자, 규제 환경에 맞게 반드시 수정·승인을
  받아야 합니다. 수정되지 않은 템플릿을 규제 제출에 사용하지 마십시오.
```

---

## 15. EMA Annex 11 / GCP 교차 참조

### EMA Annex 11 (2011) 주요 매핑

| EMA Annex 11 조항 | 조항 제목 | pk-copilot 대응 | 구현 |
|---|---|---|---|
| §4 Validation | 검증 | IQ/OQ/PQ 패키지 | [08-validation-strategy.md](08-validation-strategy.md) |
| §7.1 Data | 데이터 무결성 | JSON-of-record + hash | `audit.py` |
| §9 Audit Trails | 감사 추적 | Append-only hash-chained JSONL | `compliance/part11.py` |
| §12.1 Security | 접근 통제 | RBAC | `compliance/access.py` |
| §12.3 Passwords | 비밀번호 | 계정 잠금 정책 | 조직 SOP 보완 필요 |
| §14 Electronic Signature | 전자서명 | Ed25519 + TOTP | `compliance/part11.py` |
| §17 Archiving | 아카이빙 | WORM 스토리지 백엔드 | `compliance/retention.py` |

### ICH E6(R2) GCP 관련성

임상시험 환경에서 pk-copilot 사용 시:

- **ICH E6(R2) §5.5.3**: 컴퓨터화 시스템 검증 요건 — IQ/OQ/PQ로 대응
- **ICH E6(R2) §5.5.4**: 소스 데이터 무결성 — JSON-of-record + 입력 파일 SHA-256으로 대응
- **ICH E6(R2) §8.3.17**: 감사 추적 기록 보존 — WORM 스토리지로 대응

---

## 16. 공식 면책 고지 (Disclaimer)

### README 및 제품 페이지 필수 문구

아래 고지는 제품 README, 제품 페이지, 문서 홈페이지에 **그대로** 포함되어야 합니다:

```
────────────────────────────────────────────────────────────────
21 CFR Part 11 NOTICE

pk-copilot v2.0 provides technical controls designed to support
workflows subject to 21 CFR Part 11 (Electronic Records; Electronic
Signatures). These controls include an append-only, hash-chained
audit trail; Ed25519 electronic signatures with two-factor
authentication; role-based access control; and WORM-capable
storage backends.

However, 21 CFR Part 11 compliance is a property of an entire
quality system — not a single software tool. Deploying pk-copilot
alone does NOT constitute Part 11 compliance.

Your organization remains responsible for:
  - Written SOPs for account management, training, change control,
    deviation handling, and record retention
  - User training records
  - Installation, operational, and performance qualification (IQ/OQ/PQ)
    execution and approval
  - Periodic audit log review
  - Physical security and network security
  - Backup and disaster recovery testing

pk-copilot makes no claim of FDA certification, GxP certification,
or ISO 13485 certification. The tool has not been reviewed or
endorsed by FDA.

Contact your organization's Quality Assurance and Regulatory Affairs
teams before deploying pk-copilot in a regulated environment.
────────────────────────────────────────────────────────────────
```

### 한국어 버전 (국내 규제 환경용)

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

## 변경 이력

| 버전 | 날짜 | 변경 내용 | 작성자 |
|---|---|---|---|
| 0.1 | 2026-05-25 | 초안 작성 — v2.0 Part 11 계획 전체 구조 | pk-copilot team |

---

*이 문서는 v2.0 Compliance Matrix의 공식 트레이서빌리티 기준입니다. 기술적 통제 구현 변경 시 이 문서의 Compliance Matrix (§5)를 동시에 갱신해야 합니다. ([README.md 기여 규칙](README.md) 참조)*
