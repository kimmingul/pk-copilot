# pk-copilot

> Phoenix WinNonlin과 수치 호환되는 Pharmacokinetics(PK) / Pharmacodynamics(PD) / NCA / Compartmental Analysis 를 Claude Code에서 자연어로 수행하는 AI 코파일럿 플러그인.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.0.0--dev-orange)]()
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
| v0.1 | NCA 단일대상자 (IV/PO) | 🚧 in progress |
| v0.2 | 다대상자 NCA + BE 통계 | ⏳ 계획 |
| v0.3 | 1/2/3-구획 모델링 | ⏳ 계획 |
| v0.4 | PK/PD 연결 모델 (Emax, IDR) | ⏳ 계획 |
| v0.5 | 리포트 + R 교차검증 | ⏳ 계획 |
| **v1.0** | Production release (검증 가능, 규제 미주장) | ⏳ 계획 |
| **v2.0** | **21 CFR Part 11 + CDISC SDTM/ADaM** | ⏳ 계획 |

## 빠른 시작

> 아직 개발 중입니다 (v0.0.0-dev).

```bash
# 향후 설치 예정
claude plugin install pk-copilot
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
- **v2.0** : Part 11 기술적 통제(audit trail, e-signature, RBAC, WORM retention)와 CDISC SDTM/ADaM 표준 입출력을 제공합니다.
  단독으로 Part 11 compliance를 주장하지 않으며, 조직의 절차적 통제와 결합 시에만 사용 가능합니다.

상세 면책은 [docs/10-21cfr-part11.md](docs/10-21cfr-part11.md) §16 참조.

## 기여

[docs/11-development-workflow.md](docs/11-development-workflow.md) 참조. Apache-2.0, DCO sign-off 필수.

## 라이선스

[Apache License 2.0](LICENSE) © 2026 pk-copilot contributors.

Phoenix, WinNonlin은 Certara USA Inc.의 등록상표입니다. pk-copilot은 Certara와 무관하며, WinNonlin의 알고리즘(공개 약동학 방법론)을 참조하나 어떤 WinNonlin proprietary 파일 포맷이나 UI도 복제하지 않습니다.
