# pk-copilot

> Phoenix WinNonlin과 수치 호환되는 Pharmacokinetics(PK) / Pharmacodynamics(PD) / NCA / Compartmental Analysis 를 Claude Code에서 자연어로 수행하는 AI 코파일럿 플러그인.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.0.1-brightgreen)]()
[![WinNonlin Compat](https://img.shields.io/badge/WinNonlin-5.3%20%7C%206.4%20%7C%208.3-brightgreen)]()

## 한 줄 정의

**pk-copilot** 은 Claude Code 환경에서 자연어로 약동학·약력학 분석을 수행하면서 **Phoenix WinNonlin과 수치적으로 일치하는** 결정론적 결과를 산출합니다.

## 핵심 가치

- ✅ **WinNonlin 5.3 / 6.4 / 8.3 호환** — `winnonlin_version` 옵션으로 알고리즘 기본값 분기
- ✅ **AI 가속화** — 자연어로 데이터 클리닝·매핑·단위 변환·보고서 초안
- ✅ **결정론적 계산** — LLM은 오케스트레이터, MCP 도구가 계산 (환각 없음)
- ✅ **재현 가능** — JSON-of-record + 실행 스크립트(.py/.R) 자동 생성
- ✅ **검증 가능** — PKNCA/NonCompart 와 6+ significant figures 일치

## 로드맵

| 버전 | 범위 | 상태 |
|---|---|---|
| v0.1 | NCA 단일대상자 (IV/PO) | ✅ 완료 |
| v0.2 | 다대상자 NCA + BE 통계 | ✅ 완료 |
| v0.3 | 1/2/3-구획 모델링 | ✅ 완료 |
| v0.4 | PK/PD 연결 모델 (Emax, IDR) | ✅ 완료 |
| v0.5 | 리포트 + R 교차검증 | ✅ 완료 |
| **v1.0** | Production release (검증 가능, 규제 미주장) | ✅ [Released](https://github.com/kimmingul/pk-copilot/releases/tag/v1.0.0) |
| **v2.0** | **CDISC SDTM/ADaM + Part 11-enabling controls (deterministic path)** | ✅ [Released](https://github.com/kimmingul/pk-copilot/releases/tag/v2.0.0) (현재 — v2.0.1 patch) |

## 빠른 시작

**현재 버전: v2.0.1** (Regulated-Capable Edition — CDISC + Part 11-enabling 기술 통제 포함)

```bash
# Claude Code plugin (예정)
claude plugin install pk-copilot

# 또는 Python 패키지로 직접 설치
git clone https://github.com/kimmingul/pk-copilot.git
cd pk-copilot
uv venv && uv pip install -e ".[dev,mcp,plot,report,cdisc,compliance]"
uv run pkplugin --version  # 2.0.1
uv run pkplugin doctor
```

## 슬래시 명령어

- `/nca` — 비구획 분석 (Non-Compartmental Analysis)
- `/pk-fit` — 구획 모델 적합
- `/pd-fit` — 약력학 모델 적합
- `/be` — 생물학적동등성 분석
- `/prep-data` — 데이터 클리닝 / 단위 변환
- `/diagnose` — 진단 (lambda_z 적합성, hysteresis 등)
- `/report` — WinNonlin-스타일 리포트 생성

## 문서

전체 개발/알고리즘 사양은 [docs/](docs/) 디렉터리 참조.

- [docs/README.md](docs/README.md) — 문서 인덱스
- [docs/02-roadmap.md](docs/02-roadmap.md) — 단계별 로드맵
- [docs/03-algorithms/](docs/03-algorithms/) — 알고리즘 명세
- [docs/04-winnonlin-version-matrix.md](docs/04-winnonlin-version-matrix.md) — 버전 차이
- [docs/10-21cfr-part11.md](docs/10-21cfr-part11.md) — v2.0 Part 11 컴플라이언스 계획

## 규제 / 검증 면책

- **v0.x ~ v1.x** : pk-copilot은 *탐색적 분석 + 데이터 전처리 + 보고서 초안* 도구입니다.
  21 CFR Part 11 또는 GxP 검증 시스템으로 사용하기 위해서는 사용자 조직의 자체 검증/SOP/교육이 필요합니다.
- **v2.0** : **Part 11-enabling 기술 통제** (audit chain, e-signature, RBAC, WORM lock)를
  결정론적 CLI/MCP 실행 경로에 제공합니다. LLM/chat orchestration은 기본 exploratory이며,
  통제 모드 사용 절차는 [docs/10-21cfr-part11.md §17](docs/10-21cfr-part11.md) 참조.
  **pk-copilot은 21 CFR Part 11 compliant 시스템이 아닙니다.** 실제 준수는 sponsor의
  predicate-rule 판단, validated deployment, SOP, 교육, 계정 거버넌스에 달려 있으며,
  이는 사용자 조직의 QMS 책임입니다.

상세 면책은 [docs/10-21cfr-part11.md](docs/10-21cfr-part11.md) §16–17 참조.
완전한 분리 설계는 [docs/14-llm-boundary-disclosure.md](docs/14-llm-boundary-disclosure.md) 참조.

## Execution Modes

pk-copilot은 두 가지 실행 모드를 지원합니다.

| Mode | When | Audit chain emission | Suitable for | Disclaimer |
|---|---|---|---|---|
| **Exploratory** | Claude chat (기본값), env 미설정 | Off (transcript log only) | 탐색적 분석, 가설 검증, 보고서 초안 | LLM 출력을 regulatory record로 직접 사용 불가 |
| **Controlled** | CLI 또는 MCP tool, `PKPLUGIN_PART11_ENABLED=1` + user dict 전달 | On (HMAC hash-chain) | Part 11-controlled workflow (customer QMS 하에서) | 조직의 SOP/validation 필수; [§17](docs/10-21cfr-part11.md) 참조 |

> **참고**: Controlled mode는 "Part 11 compliant"가 아닌 "Part 11-enabling"입니다.
> 실제 Part 11 준수는 sponsor 조직의 QMS 전체 운영에 달려 있습니다.

## 기여

[docs/11-development-workflow.md](docs/11-development-workflow.md) 참조. Apache-2.0, DCO sign-off 필수.

## 라이선스

[Apache License 2.0](LICENSE) © 2026 pk-copilot contributors.

Phoenix, WinNonlin은 Certara USA Inc.의 등록상표입니다. pk-copilot은 Certara와 무관하며, WinNonlin의 알고리즘(공개 약동학 방법론)을 참조하나 어떤 WinNonlin proprietary 파일 포맷이나 UI도 복제하지 않습니다.
