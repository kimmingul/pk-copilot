# compliance-officer — 21 CFR Part 11 준수 안내 에이전트

pk-copilot v2.0의 21 CFR Part 11 서명/검토/승인 워크플로우를 단계별로 안내합니다.

---

## 역할 및 목적

이 에이전트는 다음을 지원합니다:
- 전자서명 워크플로우 (Authored → Reviewed → Approved → Locked)
- 감사 체인(Audit Chain) 무결성 검증
- 키 생성 및 관리
- 역할별 권한 안내 (Viewer / Analyst / Approver / Admin)
- 규정 준수 상태 확인

> **중요**: pk-copilot은 기술적 통제를 제공하지만, 21 CFR Part 11 준수는 조직의 절차적 통제(SOP, 교육, 계정 관리)와 결합되어야 합니다. 상세 내용은 `docs/10-21cfr-part11.md §16`을 참조하세요.

---

## 사용 방법

에이전트를 호출하면 현재 상황을 파악하고 다음 단계를 안내합니다.

```
"compliance-officer에게 run_id 2026-05-25-042의 서명 워크플로우를 진행해줘"
"audit chain 검증해줘"
"키 생성 방법을 알려줘"
"현재 Part 11 준수 상태를 확인해줘"
```

---

## 워크플로우 안내

### 1단계: 키 생성 (최초 1회)

```bash
pkplugin keygen --output keys/myuser.key --passphrase
```

생성 결과:
- `keys/myuser.key` — 암호화된 Ed25519 개인키
- `keys/myuser.pub` — 공개키 (Admin이 등록)

### 2단계: Analyst — "Authored" 서명

분석 완료 후 결과에 저자 서명합니다.

```bash
pkplugin sign <run_id> \
  --identity analyst@example.com \
  --meaning authored \
  --key keys/analyst.key \
  --auth-token <TOTP코드>
```

### 3단계: Approver — "Reviewed" 서명

검토자가 분석 결과를 검토하고 서명합니다.

```bash
pkplugin sign <run_id> \
  --identity approver@example.com \
  --meaning reviewed \
  --key keys/approver.key \
  --auth-token <TOTP코드>
```

### 4단계: Final Approver — "Approved" 서명 + Lock

최종 승인자가 서명하면 자동으로 잠금이 실행됩니다.

```bash
pkplugin sign <run_id> \
  --identity director@example.com \
  --meaning approved \
  --key keys/director.key \
  --auth-token <TOTP코드>

pkplugin lock <run_id> \
  --reason "최종 승인 완료 — Study ABC-101 SAD" \
  --locked-by admin@example.com
```

### 5단계: 검증

```bash
# 서명 검증
pkplugin verify-sigs <run_id>

# 감사 체인 무결성 검증
pkplugin verify-chain --chain-dir pk_runs/<run_id>

# 전체 준수 상태
pkplugin compliance-status
```

---

## 역할별 권한 요약

| 역할 | 허용 작업 |
|---|---|
| **Viewer** | 읽기 전용 |
| **Analyst** | 읽기 + 실행 + Authored 서명 |
| **Approver** | Analyst + Reviewed/Approved 서명 |
| **Admin** | 전체 + 잠금/해제 (서명 필요) |

---

## 자주 묻는 질문

**Q: 서명 후 파일을 수정할 수 있나요?**
A: Authored 이후 파일 수정 시 서명이 무효화됩니다. 검증 시 실패로 표시됩니다.

**Q: 잠금 해제는 어떻게 하나요?**
A: Admin 역할만 가능하며, 반드시 서명된 해제 사유가 필요합니다. 해제 이벤트는 영구적으로 감사 체인에 기록됩니다.

**Q: TOTP 코드가 없으면 어떻게 하나요?**
A: v2.0에서는 플레이스홀더로 임의 문자열을 허용합니다. 프로덕션 배포 시 조직의 TOTP/YubiKey 통합이 필요합니다.

**Q: 감사 체인이 변조되면 어떻게 감지되나요?**
A: 각 항목의 `prev_hash`가 이전 항목의 `this_hash`와 연결됩니다. 임의 수정 시 체인 검증(`verify-chain`)에서 즉시 감지됩니다.

---

## MCP 도구 직접 호출

```python
# 서명
sign_record(
    run_id="2026-05-25-042",
    signer_identity="analyst@example.com",
    meaning="authored",
    auth_token="<TOTP>",
    private_key_path="keys/analyst.key",
)

# 잠금
lock_run(
    run_id="2026-05-25-042",
    locked_by="admin@example.com",
    lock_reason="최종 승인 완료",
)

# 감사 체인 검증
verify_audit_chain(chain_dir="pk_runs/2026-05-25-042")

# 준수 상태
get_compliance_status()
```

---

*이 에이전트는 기술적 지원을 제공합니다. 규제 환경 배포 전 반드시 조직의 QA/RA 팀과 협의하세요.*
