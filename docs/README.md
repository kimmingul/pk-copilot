# pk-copilot — 개발 문서 인덱스

> **Phoenix WinNonlin 호환** 약동학(PK) / 약력학(PD) / 비구획분석(NCA) / 구획분석(Compartmental) Claude Code 플러그인

이 문서 디렉터리는 `pk-copilot` 플러그인의 모든 설계·알고리즘·검증·규제 사양을 담는 단일 진실 공급원(Single Source of Truth)입니다.

---

## 📚 문서 맵

### 0. 전략 / 개요
| 문서 | 내용 |
|---|---|
| [00-vision-and-positioning.md](00-vision-and-positioning.md) | 프로젝트 비전, 타겟 사용자, 포지셔닝 |
| [01-architecture.md](01-architecture.md) | 플러그인 구조, MCP 커널, 의존성 스택 |
| [02-roadmap.md](02-roadmap.md) | **v0.1 → v2.0 단계별 로드맵** |

### 1. 알고리즘 사양 (Phoenix WinNonlin 호환)
| 문서 | 내용 |
|---|---|
| [03-algorithms/README.md](03-algorithms/README.md) | 알고리즘 명세서 개요 |
| [03-algorithms/01-nca-parameters.md](03-algorithms/01-nca-parameters.md) | NCA 전체 파라미터 사전 |
| [03-algorithms/02-auc-methods.md](03-algorithms/02-auc-methods.md) | AUC/AUMC 적분 방법 |
| [03-algorithms/03-lambda-z-selection.md](03-algorithms/03-lambda-z-selection.md) | 말단상 회귀 / Lambda_z 선택 |
| [03-algorithms/04-bloq-handling.md](03-algorithms/04-bloq-handling.md) | BLOQ / 결측치 처리 정책 |
| [03-algorithms/05-partial-auc.md](03-algorithms/05-partial-auc.md) | Partial AUC 보간 규칙 |
| [03-algorithms/06-steady-state.md](03-algorithms/06-steady-state.md) | 정상상태 파라미터 |
| [03-algorithms/07-bioequivalence.md](03-algorithms/07-bioequivalence.md) | 생물학적동등성 통계 |
| [03-algorithms/08-compartmental-models.md](03-algorithms/08-compartmental-models.md) | 1/2/3-구획 모델 |
| [03-algorithms/09-pkpd-models.md](03-algorithms/09-pkpd-models.md) | PK/PD 연결 모델 |

### 2. 버전 호환성
| 문서 | 내용 |
|---|---|
| [04-winnonlin-version-matrix.md](04-winnonlin-version-matrix.md) | **WinNonlin 5.3 / 6.4 / 8.3 알고리즘·파라미터 차이 매트릭스** |

### 3. 구현 사양
| 문서 | 내용 |
|---|---|
| [05-data-schemas.md](05-data-schemas.md) | Pydantic 데이터 스키마, 단위 시스템 |
| [06-mcp-server.md](06-mcp-server.md) | MCP 도구 카탈로그 |
| [07-ux-and-commands.md](07-ux-and-commands.md) | 슬래시 명령어, 에이전트, 스킬 UX |

### 4. 품질 / 규제 (v1 → v2)
| 문서 | 내용 |
|---|---|
| [08-validation-strategy.md](08-validation-strategy.md) | Golden test, GxP IQ/OQ/PQ |
| [09-cdisc-support.md](09-cdisc-support.md) | **v2: CDISC SDTM / ADaM 지원** |
| [10-21cfr-part11.md](10-21cfr-part11.md) | **v2: Part 11-enabling controls, Execution Modes (§17), 면책 (§16)** |
| [11-development-workflow.md](11-development-workflow.md) | 개발자 가이드, 테스트, 릴리즈 |

### 5. 규제 / 책임 경계 (v2.0.1 포지셔닝 명확화)
| 문서 | 내용 |
|---|---|
| [12-intended-use.md](12-intended-use.md) | **Intended Use Statement** — 의도된 사용 목적, 사용자, 워크플로우, 책임 |
| [13-compliance-matrix.md](13-compliance-matrix.md) | **책임 분리 매트릭스** — pk-copilot 제공 vs 사용자 조직 제공 |
| [14-llm-boundary-disclosure.md](14-llm-boundary-disclosure.md) | **LLM 경계 공개** — LLM 역할, 비결정성 위험, deterministic kernel 분리 |

---

## 🎯 빠른 시작 (개발자용)

1. **비전부터** → [00-vision-and-positioning.md](00-vision-and-positioning.md)
2. **로드맵 확인** → [02-roadmap.md](02-roadmap.md)
3. **본인이 구현할 알고리즘** → [03-algorithms/](03-algorithms/)
4. **WinNonlin 버전 차이 발견 시** → [04-winnonlin-version-matrix.md](04-winnonlin-version-matrix.md)에 즉시 기록

## 📖 참고 자료 (`reference/` 폴더)

| 매뉴얼 | 용도 |
|---|---|
| `Phoenix WinNonlin 6.4 User's Guide.pdf` | 알고리즘 기준 (중간 버전) |
| `WinNonlin User's Guide 5.3.pdf` | 레거시 동작 비교 |
| `WinNonlin User's Guide 8.3.pdf` | 최신 동작 비교 |
| `Phoenix 1.4 Data Tools and Plots Guide.pdf` | 플롯 / 데이터 변환 규칙 |

> **알고리즘 구현 원칙**: 모든 수식·기본값·BLOQ 규칙·Lambda_z 선택 로직은 위 매뉴얼의 해당 페이지를 **반드시 인용**하고, 코드 주석과 docstring에 매뉴얼 페이지를 기재합니다.

---

## 🤝 기여 규칙

- 알고리즘 변경 시 → 03-algorithms 문서 + golden test 동시 업데이트
- 버전 차이 발견 시 → 04-winnonlin-version-matrix.md 갱신 + 기본값 결정 회의록 첨부
- v2 규제 관련 변경 → 10-21cfr-part11.md 의 트레이서빌리티 매트릭스 갱신
