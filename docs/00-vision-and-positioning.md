# 00. Vision & Positioning

## 한 줄 정의

> **pk-copilot** 은 Claude Code 환경에서 자연어로 약동학·약력학 분석을 수행하면서도 **Phoenix WinNonlin과 수치적으로 일치하는** 결정론적 결과를 산출하는, AI 코파일럿입니다.

---

## 🎯 미션

1. **WinNonlin 호환성**: NCA·구획분석·BE 등 핵심 파라미터를 매뉴얼 명세된 알고리즘으로 정확히 재현
2. **버전 인식 (Version-Aware)**: WinNonlin 5.3 / 6.4 / 8.3 간 알고리즘·기본값 차이를 사용자가 선택 가능
3. **AI 가속화**: 데이터 클리닝, 컬럼 매핑, 단위 변환, 보고서 초안 작성 등 보일러플레이트 작업 자동화
4. **재현성 (Reproducibility)**: 모든 분석은 JSON-of-record + 실행 스크립트로 저장
5. **규제 준비 (v2)**: 21 CFR Part 11 compliance + CDISC SDTM/ADaM 표준 지원

---

## 👥 타겟 사용자

| 사용자 | 페인포인트 | pk-copilot 의 가치 |
|---|---|---|
| **WinNonlin 사용자** | 라이선스 비용 / GUI 반복 작업 | 동일 수치, 자연어 인터페이스, CLI 자동화 |
| **바이오텍 스타트업** | 라이선스 부담 | 오픈 백엔드 + 검증 가능한 결과 |
| **CRO 분석가** | 다수 스터디 반복 처리 | 스크립트 재현 / 배치 처리 |
| **학계 연구자** | R 코딩 진입장벽 | 자연어 → 결정론적 결과 |
| **규제 검토자 (v2)** | 제출물 검증 | 감사 로그 + Part 11 트레이서빌리티 |
| **계량약리학 학생** | 학습 곡선 | 알고리즘 출처를 모두 매뉴얼 페이지로 추적 |

---

## ✅ pk-copilot 이 잘 하는 것

- 더러운 CSV/Excel → 표준화된 컨센트레이션-타임 데이터셋 변환
- 단위 자동 추론 + **강제 확인 프롬프트** (PK 에러의 90%가 단위에서 발생)
- NCA 파라미터 풀세트 계산 (Cmax, AUC, t½, CL, Vss, BE 통계 등)
- Lambda_z 선택을 **투명하게** 사용자와 협의 (블랙박스 금지)
- 모든 결과의 알고리즘·데이터 제외·소프트웨어 버전을 인용
- 재실행 가능한 Python/R 스크립트 자동 생성

## 🚫 pk-copilot 이 하지 않는 것 (의도적 비목표)

| 비목표 | 이유 / 대체 |
|---|---|
| LLM이 직접 수치 계산 | 환각 위험 — 모든 계산은 검증된 백엔드(MCP 커널 / PKNCA / NonCompart)에 위임 |
| Phoenix WinNonlin GUI/파일 포맷 복제 | 트레이드마크 / 호환성 리스크 |
| 자체 popPK SAEM/FOCE 구현 (v1) | nlmixr2 / NONMEM 위임 — 검증 비용 과다 |
| PBPK, IVIVC, adaptive trial sim | 범위 외 |
| **v1**: 21 CFR Part 11 compliant 주장 | **v2에서 정식 지원** |

---

## 🏷️ 포지셔닝 진술

> *"제약 계량약리학자를 위한 AI 코파일럿 — WinNonlin과 동일한 알고리즘으로, 자연어 인터페이스의 속도와 스크립트의 재현성을 결합합니다."*

영문: *"An AI copilot for pharmacometricians — WinNonlin-compatible algorithms with the speed of natural language and the reproducibility of code."*

---

## 🆚 대안과의 비교

| 도구 | 강점 | pk-copilot 차별점 |
|---|---|---|
| **Phoenix WinNonlin** | 업계 표준, GxP 검증 | 가격 / GUI 반복 작업 / AI 자동화 부재 |
| **PKNCA (R)** | 학술적 검증 | R 코딩 필요 / 자연어 UX 부재 |
| **NonCompart (R)** | FDA-cited | R 코딩 필요 |
| **nlmixr2** | 강력한 popPK | pk-copilot는 v1에서 NCA/구획에 집중, popPK는 nlmixr2 위임 |
| **Pumas.jl** | 고성능 | Julia 진입장벽, 폐쇄 라이선스 |

**우리의 자리**: *"PKNCA의 정확성 + WinNonlin의 워크플로우 + Claude Code의 대화형 UX + v2 규제 준수"*

---

## 📈 성공 지표 (KPI)

### v1
- ✅ Theophylline 표준 데이터셋에서 WinNonlin/PKNCA와 **6 significant figures 일치**
- ✅ 평균 사용자가 더러운 CSV → 완성된 NCA 리포트까지 **10분 이내**
- ✅ 모든 알고리즘이 매뉴얼 페이지 인용으로 추적 가능

### v2
- ✅ 21 CFR Part 11 controls (audit trail, e-signature, access control) 통과
- ✅ CDISC SDTM PC/EX 도메인 직접 입력 + ADaM ADPC/ADPP 출력
- ✅ 외부 GxP 컨설팅 감사에서 IQ/OQ/PQ 산출물 인정

---

## 🔗 다음 단계

- [01-architecture.md](01-architecture.md) — 플러그인 아키텍처
- [02-roadmap.md](02-roadmap.md) — 단계별 빌드 계획
