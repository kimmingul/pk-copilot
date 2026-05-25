# 09. CDISC 표준 지원 (v2.0)

> **대상 버전**: pk-copilot v2.0 "Regulated Edition"
> **준거 표준**: CDISC SDTM Implementation Guide v3.4 / ADaM Implementation Guide v1.3

---

## 1. CDISC 표준 개요

### 1.1 SDTM (Study Data Tabulation Model)

SDTM은 임상시험에서 수집된 **원시 관측 데이터**를 FDA/PMDA 제출 형식으로 표준화하기 위한 모델입니다. 각 관측치는 도메인(Domain) 단위로 구분되며, 도메인은 Subject-Observation-Timing이라는 3-tier 구조를 따릅니다. 약동학 분야에서는 PC(농도), EX(투여), DM(인구통계) 도메인이 핵심입니다. 모든 SDTM 변수명·값은 CDISC Controlled Terminology를 따라야 하며, 규제 기관 제출 시 Define-XML을 함께 제출해야 합니다. 참조: [https://www.cdisc.org/standards/foundational/sdtm](https://www.cdisc.org/standards/foundational/sdtm)

### 1.2 ADaM (Analysis Data Model)

ADaM은 SDTM 원시 데이터를 **분석 목적으로 변환·파생한** 데이터셋 표준입니다. ADPC(농도 분석 데이터셋), ADPP(PK 파라미터 분석 데이터셋)가 PK 연구의 핵심 ADaM 도메인입니다. ADaM 데이터셋은 SDTM으로부터의 파생 경로가 추적 가능해야 하며, 분석 변수(AVAL, AVALC 등)와 시점 변수(ADTM, ATPT 등)를 포함합니다. 참조: [https://www.cdisc.org/standards/foundational/adam](https://www.cdisc.org/standards/foundational/adam)

### 1.3 Define-XML 2.1

Define-XML은 SDTM/ADaM 데이터셋의 **메타데이터를 기술하는 XML 문서**입니다. 변수명, 데이터 타입, 길이, 코드목록(Codelist), 기원(Origin), CDISC CT 버전 등이 포함됩니다. FDA는 Study Data Technical Conformance Guide에 따라 Define-XML 2.1을 요구합니다. pk-copilot v2.0은 ADPC/ADPP 익스포트 시 Define-XML을 자동 생성합니다. 참조: [https://www.cdisc.org/standards/data-exchange/define-xml](https://www.cdisc.org/standards/data-exchange/define-xml)

### 1.4 Controlled Terminology (CT)

CDISC Controlled Terminology는 SDTM/ADaM 코드 목록의 **허용 값 목록**입니다. NCI Thesaurus 기반으로 분기별 업데이트됩니다. pk-copilot v2.0은 특정 CT 버전을 고정(lock)하여 재현성을 보장하며, PARAMCD, PCTESTCD, PCSPEC 등의 값은 CT 목록에서 검증됩니다. CT 다운로드 및 버전 관리는 `cdisc/ct_versions.json`으로 추적합니다. 참조: [https://www.cdisc.org/standards/terminology](https://www.cdisc.org/standards/terminology)

---

## 2. End-to-End 데이터 흐름

```
┌─────────────────────────────────────────────────────────────────────┐
│  스폰서 원시 데이터 (SAS XPT, CSV, Excel)                              │
│  - CRF 농도 측정값, 투여 기록, 인구통계                                  │
└──────────────────┬──────────────────────────────────────────────────┘
                   │  (SOP에 따라 스폰서 SDTM 변환 수행)
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SDTM 도메인 (SAS XPT / CSV)                                         │
│  ├── PC.xpt   — 혈중 약물 농도 관측치                                  │
│  ├── EX.xpt   — 투여 기록 (용량, 경로, 일시)                            │
│  ├── DM.xpt   — 인구통계 (나이, 성별, 인종)                              │
│  ├── VS.xpt   — 활력징후 (체중 공변량)                            [선택] │
│  └── LB.xpt   — 검사 (신장기능 공변량)                            [선택] │
└──────────────────┬──────────────────────────────────────────────────┘
                   │  import_sdtm() MCP 도구
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  pk-copilot v2.0 내부 정규화 레이어                                    │
│  ├── ISO 8601 datetime → elapsed time (hr) 변환                      │
│  ├── SDTM → Pydantic 스키마 매핑                                      │
│  ├── 공변량 JOIN (DM + VS + LB → CovariateRecord)                    │
│  └── CDISC CT 검증 (PCSPEC, PCSTRESU 등)                             │
└──────────────────┬──────────────────────────────────────────────────┘
                   │  run_nca() / run_be() / fit_pk_model()
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  NCA / BE / 구획분석 엔진 (Python Calc Kernel)                         │
│  NCAParameterRow → CMAX, TMAX, AUCLST, AUCIFO, LAMZHL, ...          │
└──────────────────┬──────────────────────────────────────────────────┘
                   │  export_adam() MCP 도구
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ADaM 도메인 출력 (SAS XPT / CSV)                                     │
│  ├── ADPC.xpt  — 농도 분석 데이터셋 (AVAL, ATPT, NRRLT, ARRLT)        │
│  └── ADPP.xpt  — PK 파라미터 분석 데이터셋 (PARAMCD, AVAL, AVALU)      │
└──────────────────┬──────────────────────────────────────────────────┘
                   │  + define.xml (자동 생성)
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  IND / NDA 제출 패키지 (FDA eCTD 5.3.3.4 폴더)                         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. SDTM 입력 도메인

### 3.1 PC — Pharmacokinetic Concentrations

**참조**: CDISC SDTM IG v3.4, Section 6.2.6

#### 필수(Required) 변수

| 변수명 | 타입 | 설명 | pk-copilot 매핑 |
|---|---|---|---|
| `STUDYID` | Char | 스터디 식별자 | `study_id` |
| `DOMAIN` | Char | 도메인 코드 = "PC" | (고정값 검증) |
| `USUBJID` | Char | 유일 대상자 식별자 (`STUDYID-SITEID-SUBJID`) | `subject_id` |
| `PCSEQ` | Num | PC 도메인 내 순번 | (내부 정렬용) |
| `PCTESTCD` | Char | 검사 단축 코드 (CDISC CT) | `analyte` 원형 |
| `PCTEST` | Char | 검사 명칭 (Long label) | `analyte` |
| `PCORRES` | Char | 원본 문자열 결과 (`"<0.5"` 포함) | `raw_concentration` |
| `PCSTRESC` | Char | 표준화 문자 결과 | (BLOQ 판단 사용) |
| `PCSTRESN` | Num | 표준화 수치 결과 | `concentration` |
| `PCSTRESU` | Char | 표준화 단위 (CDISC CT) | `unit` 검증 |
| `PCSTAT` | Char | 상태 코드 (`ND` = not done) | `bloq` 플래그 |
| `PCDTC` | Char | ISO 8601 채혈 일시 | 시간 정규화 원천 |

#### 권장(Expected) 변수

| 변수명 | 타입 | 설명 | pk-copilot 매핑 |
|---|---|---|---|
| `PCSPEC` | Char | 검체 종류 (PLASMA, SERUM, BLOOD, URINE) | `matrix` |
| `PCELTM` | Char | ISO 8601 duration — 투여 후 경과 시간 (`PT1H30M`) | 직접 시간 |
| `PCTPT` | Char | 명목 시점 레이블 (`"30 min"`, `"1 hr"`) | `time_label` |
| `PCTPTNUM` | Num | 명목 시점 번호 | 정렬 보조 |
| `PCTPTREF` | Char | 기준 시점 레퍼런스 (`"FIRST DOSE"`) | 투여 기준 |
| `VISIT` | Char | 방문명 (`"Day 1"`) | `visit` |
| `VISITNUM` | Num | 방문 번호 | 정렬 보조 |
| `EPOCH` | Char | 시험 에포크 (`"TREATMENT"`) | `period` 보조 |

#### 유효성 검증 규칙

```
1. PCSTRESN이 수치인 경우 PCSTRESU 반드시 존재
2. PCDTC가 있으면 EXSTDTC(EX 도메인)와 함께 elapsed time 계산 가능해야 함
3. PCSTRESU는 CDISC CT C85994 코드목록 내 값이어야 함
4. USUBJID 형식: "{STUDYID}-{SITEID}-{SUBJID}" (hyphen 구분)
5. PCSTRESN < LLOQ인 경우 PCSTAT = "ND" 또는 PCORRES에 "<" 포함
6. 동일 USUBJID + PCDTC 조합 중복 불허 (같은 analyte 기준)
```

#### 샘플 SDTM PC 데이터 (CSV)

```csv
STUDYID,DOMAIN,USUBJID,PCSEQ,PCTESTCD,PCTEST,PCORRES,PCSTRESC,PCSTRESN,PCSTRESU,PCSPEC,PCDTC,PCELTM,PCTPT,PCTPTNUM,PCTPTREF,VISIT,VISITNUM
STUDY01,PC,STUDY01-001-001,1,DRUGX,Drug X,<0.5,<0.5,,ng/mL,PLASMA,2024-03-01T08:00:00,,PREDOSE,0,FIRST DOSE,Day 1,1
STUDY01,PC,STUDY01-001-001,2,DRUGX,Drug X,12.4,12.4,12.4,ng/mL,PLASMA,2024-03-01T08:30:00,PT0H30M,30 min,0.5,FIRST DOSE,Day 1,1
STUDY01,PC,STUDY01-001-001,3,DRUGX,Drug X,18.7,18.7,18.7,ng/mL,PLASMA,2024-03-01T09:00:00,PT1H0M,1 hr,1,FIRST DOSE,Day 1,1
STUDY01,PC,STUDY01-001-001,4,DRUGX,Drug X,24.3,24.3,24.3,ng/mL,PLASMA,2024-03-01T10:00:00,PT2H0M,2 hr,2,FIRST DOSE,Day 1,1
STUDY01,PC,STUDY01-001-001,5,DRUGX,Drug X,21.1,21.1,21.1,ng/mL,PLASMA,2024-03-01T12:00:00,PT4H0M,4 hr,4,FIRST DOSE,Day 1,1
STUDY01,PC,STUDY01-001-001,6,DRUGX,Drug X,14.8,14.8,14.8,ng/mL,PLASMA,2024-03-01T16:00:00,PT8H0M,8 hr,8,FIRST DOSE,Day 1,1
STUDY01,PC,STUDY01-001-001,7,DRUGX,Drug X,8.2,8.2,8.2,ng/mL,PLASMA,2024-03-01T20:00:00,PT12H0M,12 hr,12,FIRST DOSE,Day 1,1
STUDY01,PC,STUDY01-001-001,8,DRUGX,Drug X,3.1,3.1,3.1,ng/mL,PLASMA,2024-03-02T08:00:00,PT24H0M,24 hr,24,FIRST DOSE,Day 1,1
```

---

### 3.2 EX — Exposure

**참조**: CDISC SDTM IG v3.4, Section 6.1.4

#### 필수 변수

| 변수명 | 타입 | 설명 | pk-copilot 매핑 |
|---|---|---|---|
| `STUDYID` | Char | 스터디 식별자 | `study_id` |
| `DOMAIN` | Char | "EX" | (고정값 검증) |
| `USUBJID` | Char | 유일 대상자 식별자 | `subject_id` |
| `EXSEQ` | Num | 순번 | (내부 정렬용) |
| `EXTRT` | Char | 치료명/약물명 | `treatment` |
| `EXDOSE` | Num | 투여 용량 (수치) | `dose.amount` |
| `EXDOSU` | Char | 투여 용량 단위 | `dose.unit` |
| `EXROUTE` | Char | 투여 경로 (CDISC CT) | `dose.route` |
| `EXSTDTC` | Char | ISO 8601 투여 시작 일시 | `dose.time` (기준점) |

#### 권장 변수

| 변수명 | 타입 | 설명 | pk-copilot 매핑 |
|---|---|---|---|
| `EXENDTC` | Char | ISO 8601 투여 종료 일시 | 점적 시간 계산 |
| `EXDOSFRQ` | Char | 투여 빈도 (`QD`, `BID`) | `design.dosing_freq` |
| `EXDOSFRM` | Char | 제형 (`TABLET`, `SOLUTION`) | (메타데이터) |
| `EXLOT` | Char | 배치 번호 | (감사 추적) |
| `VISIT` | Char | 방문명 | `period` 보조 |
| `VISITNUM` | Num | 방문 번호 | 정렬 보조 |

#### EXROUTE → dose.route 매핑

| EXROUTE (CDISC CT) | pk-copilot route |
|---|---|
| `INTRAVENOUS BOLUS` | `iv_bolus` |
| `INTRAVENOUS` | `iv_infusion` |
| `ORAL` | `oral` |
| `SUBCUTANEOUS` | `subcut` |
| `INTRAMUSCULAR` | `im` |
| 기타 | `other` |

---

### 3.3 DM — Demographics

**참조**: CDISC SDTM IG v3.4, Section 5.2

#### pk-copilot에서 사용하는 DM 변수

| 변수명 | 타입 | 설명 | pk-copilot 매핑 |
|---|---|---|---|
| `USUBJID` | Char | 유일 대상자 식별자 | 결합 키 |
| `AGE` | Num | 나이 | `covariate.age` |
| `AGEU` | Char | 나이 단위 (`YEARS`) | `covariate.age_unit` |
| `SEX` | Char | 성별 (`M`, `F`) | `covariate.sex` |
| `RACE` | Char | 인종 | (메타데이터) |
| `ETHNIC` | Char | 민족 | (메타데이터) |
| `ARM` | Char | 계획 처치 그룹 | `treatment` |
| `ARMCD` | Char | 처치 그룹 코드 | `treatment_code` |
| `ACTARM` | Char | 실제 처치 그룹 | `actual_treatment` |
| `COUNTRY` | Char | 국가 (ISO 3166) | (메타데이터) |
| `RFSTDTC` | Char | 첫 투여 일시 (참조 기준) | elapsed time 보정 |

---

### 3.4 VS — Vital Signs (공변량 보조)

**참조**: CDISC SDTM IG v3.4, Section 6.3.12

체중(WEIGHT) 공변량 추출에 사용합니다. `VSTESTCD = "WEIGHT"` 레코드만 추출.

| 변수명 | 설명 | pk-copilot 매핑 |
|---|---|---|
| `USUBJID` | 대상자 | 결합 키 |
| `VSTESTCD` | 검사 코드 (`WEIGHT`, `HEIGHT`, `BMI`) | 필터 기준 |
| `VSSTRESN` | 수치 결과 | `covariate.weight` (kg) |
| `VSSTRESU` | 단위 (`kg`) | 단위 검증 |
| `VSDTC` | 측정 일시 | 투여 전 가장 가까운 값 선택 |

---

### 3.5 LB — Laboratory (공변량 보조)

**참조**: CDISC SDTM IG v3.4, Section 6.3.4

신장 기능 공변량(크레아티닌 청소율, eGFR) 추출에 사용합니다.

| 변수명 | 설명 | pk-copilot 매핑 |
|---|---|---|
| `USUBJID` | 대상자 | 결합 키 |
| `LBTESTCD` | 검사 코드 (`CREAT`, `EGFR`) | 필터 기준 |
| `LBSTRESN` | 수치 결과 | `covariate.creatinine` / `covariate.egfr` |
| `LBSTRESU` | 단위 | 단위 검증 |
| `LBDTC` | 측정 일시 | 투여 전 가장 가까운 값 선택 |

---

## 4. 시간 정규화 — ISO 8601 → 경과 시간(hr)

SDTM 날짜시간은 ISO 8601 형식(`2024-03-01T08:30:00`)으로 저장됩니다. NCA 수행을 위해 **투여 기준 경과 시간(hr)** 으로 변환이 필요합니다. 이 과정은 다음 시나리오에서 복잡성이 증가합니다.

### 4.1 정규화 알고리즘

```
1. 각 USUBJID별 EXSTDTC(투여 시작 일시) 조회
2. 복수 투여인 경우: 각 PC 관측 직전 투여 EXSTDTC를 기준으로 계산
3. elapsed_hr = (PCDTC - reference_EXSTDTC).total_seconds() / 3600
4. 음수 시간: predose (time < 0) — NCA에서 별도 처리 (C0 추정)
5. PCELTM 이미 존재 시: ISO 8601 duration 파싱 (P로 시작하는 경우 우선 사용)
6. 시간대(timezone) 처리: UTC+offset 포함 시 UTC 변환 후 계산
```

### 4.2 복잡 케이스 처리

| 케이스 | 처리 방법 |
|---|---|
| Predose 샘플 (`PCDTC < EXSTDTC`) | `time < 0` 보존, C0 추정에 활용 |
| 크로스오버 시험 (2기 이상) | EPOCH 또는 VISIT 기준으로 기(期) 분리 |
| 정맥 점적 (`EXSTDTC ≠ EXENDTC`) | 점적 시작 시각을 기준, `infusion_duration = EXENDTC - EXSTDTC` |
| 시간대 혼재 | 전체 UTC 변환 후 계산 |
| PCDTC 불완전 (`2024-03-01`) | date-only → 해당 일 00:00:00 UTC로 처리, 경고 발생 |
| PCELTM 우선 적용 | `PCELTM` 값이 있으면 PCDTC 기반 계산보다 우선 |

```python
# cdisc/sdtm.py — 시간 정규화 핵심 로직 예시
from datetime import datetime, timezone
import isodate

def normalize_pcdtc_to_elapsed(
    pcdtc: str,
    exstdtc: str,
    pceltm: str | None = None,
) -> float:
    """SDTM ISO 8601 datetime → elapsed time (hr)."""
    if pceltm:
        # ISO 8601 duration 우선: "PT1H30M" -> 1.5 hr
        duration = isodate.parse_duration(pceltm)
        return duration.total_seconds() / 3600.0

    pc_dt = datetime.fromisoformat(pcdtc)
    ex_dt = datetime.fromisoformat(exstdtc)
    # naive datetime 은 UTC 로 가정
    if pc_dt.tzinfo is None:
        pc_dt = pc_dt.replace(tzinfo=timezone.utc)
    if ex_dt.tzinfo is None:
        ex_dt = ex_dt.replace(tzinfo=timezone.utc)
    return (pc_dt - ex_dt).total_seconds() / 3600.0
```

---

## 5. ADaM 출력 도메인

### 5.1 ADPC — PK Concentrations Analysis Dataset

**참조**: CDISC ADaM IG v1.3, ADaM Product-Specific Guidance for Pharmacokinetics

#### 필수 ADaM 표준 변수

| 변수명 | 타입 | 설명 | 원천 |
|---|---|---|---|
| `STUDYID` | Char | 스터디 식별자 | DM.STUDYID |
| `USUBJID` | Char | 유일 대상자 식별자 | DM.USUBJID |
| `SUBJID` | Char | 사이트 내 대상자 번호 | DM.SUBJID |
| `SITEID` | Char | 사이트 번호 | DM.SITEID |
| `AGE` | Num | 나이 | DM.AGE |
| `AGEU` | Char | 나이 단위 | DM.AGEU |
| `SEX` | Char | 성별 | DM.SEX |
| `RACE` | Char | 인종 | DM.RACE |
| `ARM` | Char | 처치군 | DM.ARM |
| `ACTARM` | Char | 실제 처치군 | DM.ACTARM |
| `TRTSDT` | Num | 치료 시작일 (SAS date) | 파생 |
| `RANDDT` | Num | 무작위배정일 | DM.RFSTDTC |

#### PK 전용 분석 변수

| 변수명 | 타입 | 설명 | 원천/계산 |
|---|---|---|---|
| `PARAMCD` | Char | 파라미터 코드 (`DRUGXPC`) | PCTESTCD 기반 |
| `PARAM` | Char | 파라미터 설명 (`Drug X Concentration`) | PCTEST |
| `PARAMN` | Num | 파라미터 번호 | 정렬용 |
| `AVAL` | Num | 분석 값 (수치 농도) | PC.PCSTRESN |
| `AVALC` | Char | 분석 값 (문자) — BLOQ 표현용 | PC.PCSTRESC |
| `AVALU` | Char | 단위 | PC.PCSTRESU |
| `AVISIT` | Char | 분석 방문명 | VISIT 파생 |
| `AVISITN` | Num | 분석 방문 번호 | VISITNUM |
| `ATPT` | Char | 분석 시점 레이블 | PC.PCTPT |
| `ATPTN` | Num | 분석 시점 번호 | PC.PCTPTNUM |
| `ADTM` | Num | 분석 일시 (SAS datetime) | PC.PCDTC 변환 |
| `ADY` | Num | 연구 내 일수 (투여 첫날 = 1) | 파생 |
| `ATM` | Num | 분석 시각 (소수점 hr) | 파생 |
| `NRRLT` | Num | 명목 기준 상대 경과 시간 (hr) | PCTPTNUM |
| `ARRLT` | Num | 실제 기준 상대 경과 시간 (hr) | 4절에서 계산 |
| `ANRLO` | Num | 정상 참조 하한 (LLOQ) | 연구 파라미터 |
| `DTYPE` | Char | 파생 레코드 유형 (`PREDOSE`, `INTERPOLATED`) | 파생 기록 |

---

### 5.2 ADPP — PK Parameters Analysis Dataset

**참조**: CDISC ADaM IG v1.3, BDS (Basic Data Structure) 기반

NCA/구획분석에서 계산된 PK 파라미터를 1행-1파라미터 long format으로 구성합니다.

#### ADPP 변수

| 변수명 | 타입 | 설명 | 원천 |
|---|---|---|---|
| `STUDYID` | Char | 스터디 | DM |
| `USUBJID` | Char | 대상자 | DM |
| `PARAMCD` | Char | 파라미터 코드 (CDISC CT NCA) | NCA 엔진 |
| `PARAM` | Char | 파라미터 설명 | NCA 엔진 |
| `AVAL` | Num | 분석 값 | NCA 결과 |
| `AVALU` | Char | 단위 | 파생 |
| `AVALCAT1` | Char | 분석 값 범주 | (옵션) |
| `PPCAT` | Char | PK 카테고리 (`NON-COMPARTMENTAL`) | 고정 |
| `PPSCAT` | Char | PK 서브카테고리 (`PLASMA ANALYTE`) | PCSPEC 기반 |
| `VISIT` | Char | 방문명 | NCA 입력 |
| `AVISIT` | Char | 분석 방문명 | 파생 |
| `ARM` | Char | 처치군 | DM |

---

## 6. PARAMCD / PARAM 매핑 — NCA 파라미터 Controlled Vocabulary

**참조**: CDISC NCA Controlled Terminology (CDISC CT Package 2024-09-27 기준)

| pk-copilot parameter | PARAMCD | PARAM (CDISC) | 단위 예시 |
|---|---|---|---|
| `Cmax` | `CMAX` | Maximum Observed Analyte Concentration | ng/mL |
| `Tmax` | `TMAX` | Time of Maximum Observed Analyte Concentration | h |
| `Clast` | `CLST` | Last Observed Analyte Concentration above LLOQ | ng/mL |
| `Tlast` | `TLST` | Time of Last Observed Analyte Concentration above LLOQ | h |
| `AUClast` | `AUCLST` | AUC from Time Zero to Time of Last Observed Concentration above LLOQ | h*ng/mL |
| `AUCinf_obs` | `AUCIFO` | AUC from Time Zero Extrapolated to Infinity (Observed) | h*ng/mL |
| `AUCinf_pred` | `AUCIFP` | AUC from Time Zero Extrapolated to Infinity (Predicted) | h*ng/mL |
| `AUMClast` | `AUMCLST` | AUMC from Time Zero to Time of Last Observed Concentration | h2*ng/mL |
| `Lambda_z` | `LAMZ` | Terminal Phase Rate Constant | 1/h |
| `t_half` | `LAMZHL` | Terminal Phase Half-Life | h |
| `CL` | `CL` | Observed Systemic Clearance | mL/h |
| `CL_F` | `CLF` | Apparent Systemic Clearance | mL/h |
| `Vz` | `VZ` | Volume of Distribution Based on Terminal Phase | mL |
| `Vz_F` | `VZF` | Apparent Volume of Distribution Based on Terminal Phase | mL |
| `Vss` | `VSS` | Volume of Distribution at Steady State (IV) | mL |
| `MRT` | `MRT` | Mean Residence Time | h |
| `AUCpct_extrap` | `AUCPEO` | AUC %Extrapolated (Observed) | % |
| `Lambda_z_lower` | `LAMZLL` | Lower Limit of Regression Time Range | h |
| `Lambda_z_upper` | `LAMZUL` | Upper Limit of Regression Time Range | h |
| `Lambda_z_r2` | `CORRXY` | Correlation Coefficient, Terminal Phase | — |
| `Lambda_z_r2_adj` | `R2ADJ` | Adjusted R-Squared, Terminal Phase | — |
| `Lambda_z_n_points` | `LAMZNPT` | Number of Points for Lambda_z | — |
| `Cmax_ss` | `CMAXSS` | Maximum Steady-State Analyte Concentration | ng/mL |
| `Cmin_ss` | `CMINSS` | Minimum Steady-State Analyte Concentration | ng/mL |
| `AUCtau_ss` | `AUCTAU` | AUC over the Dosing Interval at Steady State | h*ng/mL |
| `Cavg_ss` | `CAVGSS` | Average Steady-State Analyte Concentration | ng/mL |

---

## 7. Define-XML 2.1 자동 생성

`export_adam()` 호출 시 `include_define_xml=True` (기본값) 이면 `adam/define.xml`이 자동 생성됩니다.

### 7.1 포함 메타데이터

| 섹션 | 내용 |
|---|---|
| `ODM/@FileOID` | Run ID 기반 고유 OID |
| `Study/GlobalVariables` | 스터디명, 설명, 프로토콜명 |
| `MetaDataVersion` | ADaM IG v1.3, Define-XML v2.1 |
| `ItemGroupDef` (ADPC, ADPP) | 데이터셋명, 라벨, 구조, 클래스 |
| `ItemDef` (각 변수) | 변수명, 데이터 타입, 길이, 라벨, 원천, 계산식 |
| `CodeList` | CT 코드목록 (PARAMCD, PCSPEC 등) |
| `MethodDef` | 파생 변수 계산 방법 기술 |
| `CommentDef` | 비표준 또는 확장 변수 주석 |

### 7.2 검증

생성된 Define-XML은 다음 스키마에 대해 내부 검증합니다:

```
cdisc-define-2.1.0.xsd  (CDISC 공식 XSD)
ODM 1.3.2 기반
```

검증 오류 발생 시 `export_adam()` 은 예외를 반환하며 익스포트를 중단합니다.

---

## 8. Controlled Terminology 적용

### 8.1 CT 버전 고정

```json
// cdisc/ct_versions.json
{
  "sdtm_ct": "2024-09-27",
  "adam_ct": "2024-09-27",
  "nca_ct": "2024-09-27",
  "download_urls": {
    "sdtm": "https://evs.nci.nih.gov/ftp1/CDISC/SDTM/SDTM%20Terminology.xls",
    "adam": "https://evs.nci.nih.gov/ftp1/CDISC/ADaM/ADaM%20Terminology.xls"
  }
}
```

CT 파일은 `cdisc/terminology/` 폴더에 캐시하며, 버전 변경 시 재다운로드 및 재검증이 필요합니다.

### 8.2 검증 대상 변수

| 변수 | CT 코드목록 |
|---|---|
| `PCSPEC` | C78734 (Specimen Type) |
| `PCSTRESU` | C85994 (Unit) |
| `EXROUTE` | C66729 (Route of Administration) |
| `PARAMCD` | PKPCD (PK NCA Parameter Code) |
| `SEX` | C66731 (Sex) |
| `RACE` | C74457 (Race) |

---

## 9. Validation Tools — 외부 검증 도구

### 9.1 Pinnacle21 Community / Enterprise

| 검사 항목 | pk-copilot 자체 점검 | Pinnacle21 검사 |
|---|---|---|
| SDTM IG 준거 | 필수 변수 유무 | 전체 규칙 세트 |
| ADaM IG 준거 | AVAL/PARAMCD 유무 | BDS 구조 완전 검사 |
| Controlled Terminology | CT 값 목록 매핑 | NCI EVS 대조 |
| Define-XML 구조 | XSD 스키마 검증 | 참조 무결성 |

Pinnacle21 Community (무료): [https://www.pinnacle21.com/tools](https://www.pinnacle21.com/tools)

### 9.2 pk-copilot 자체 사전 검증 (export_adam 내부)

```
1. 필수 변수 존재 여부 (USUBJID, PARAMCD, AVAL 등)
2. PARAMCD → CT 매핑 유효성
3. AVAL 수치 범위 합리성 (음수 농도 불허)
4. ARRLT 단조 증가성 (같은 USUBJID, 같은 AVISIT 내)
5. Define-XML XSD 검증
6. ADPP PPCAT/PPSCAT 값 CT 준거 여부
```

---

## 10. 공변량 통합 — DM / VS / LB → CovariateRecord

SDTM PC 데이터만으로는 공변량 보정 NCA 또는 PopPK 분석이 불가능합니다. `import_sdtm()` 은 DM + VS + LB 도메인을 JOIN하여 `CovariateRecord`를 구성합니다.

### 10.1 JOIN 로직

```python
# cdisc/sdtm.py 공변량 통합 개요
def build_covariate_records(
    dm: pd.DataFrame,
    vs: pd.DataFrame | None,
    lb: pd.DataFrame | None,
    reference_date_by_subject: dict[str, datetime],
) -> dict[str, CovariateRecord]:
    """
    reference_date: 투여 전 가장 가까운 측정치 선택 기준
    """
    covariates = {}
    for usubjid, dm_row in dm.set_index("USUBJID").iterrows():
        cov = CovariateRecord(
            subject_id=usubjid,
            age=dm_row.get("AGE"),
            sex=_map_sex(dm_row.get("SEX")),
        )
        if vs is not None:
            weight_row = _closest_before(
                vs[(vs["USUBJID"] == usubjid) & (vs["VSTESTCD"] == "WEIGHT")],
                reference_date_by_subject[usubjid],
            )
            if weight_row is not None:
                cov = cov.model_copy(update={"weight": weight_row["VSSTRESN"]})
        if lb is not None:
            creat_row = _closest_before(
                lb[(lb["USUBJID"] == usubjid) & (lb["LBTESTCD"] == "CREAT")],
                reference_date_by_subject[usubjid],
            )
            if creat_row is not None:
                cov = cov.model_copy(update={"creatinine": creat_row["LBSTRESN"]})
        covariates[usubjid] = cov
    return covariates
```

### 10.2 공변량 JOIN 결과 → ADPC 반영

| CovariateRecord 필드 | ADPC 변수 |
|---|---|
| `age` | `AGE` |
| `sex` | `SEX` |
| `weight` | `WGTBL` (베이스라인 체중) |
| `crcl` | `CRCLBL` (베이스라인 CrCl) |
| `egfr` | `EGFRBL` |

---

## 11. CDISC Pilot Study 02 — 검수 기준 데이터셋

CDISC Pilot Study 02는 CDISC가 공개한 **표준 임상시험 시범 데이터셋**으로, SDTM과 ADaM의 상호 운용성 검증에 사용됩니다.

- **다운로드**: [https://github.com/cdisc-org/sdtm-adam-pilot-project](https://github.com/cdisc-org/sdtm-adam-pilot-project)
- **포함 도메인**: DM, EX, VS, LB, PC, PE (약 100명 대상자)
- **pk-copilot v2.0 인수 기준**:

```
tests/golden/cdisc_pilot_study02/
├── input/
│   ├── pc.xpt
│   ├── ex.xpt
│   ├── dm.xpt
│   ├── vs.xpt
│   └── lb.xpt
├── expected/
│   ├── adpc.xpt
│   └── adpp.xpt
└── test_cdisc_pilot_roundtrip.py
```

인수 테스트는 `import_sdtm()` → NCA → `export_adam()` 전체 파이프라인을 실행하고, 생성된 ADPC/ADPP를 기대 데이터셋과 비교하며, Pinnacle21 Community로 무오류 검증을 확인합니다.

---

## 12. 제한 사항 및 미지원 범위

| 항목 | v2.0 지원 여부 | 비고 |
|---|---|---|
| SDTM PP (PK Parameters) 도메인 **입력** | 미지원 | PP는 ADPP 기원이므로 대부분 불필요 |
| SDTM SUPPPC (Supplemental PC) | 부분 지원 | 표준 qualifier만 처리; 커스텀 SUPPQUAL 제한 |
| 다중 분석물 (multiple analytes) | 지원 | PCTESTCD로 구분 |
| 소변 PK (PCSPEC=URINE) | 지원 | AUC0-inf 제외, renal clearance 별도 |
| 인구약동학 (PopPK) ADaM | 미지원 | v3 예정 (NONMEM/nlmixr2 연동) |
| Receptor Occupancy ADaM | 미지원 | PD 영역, v4 예정 |
| SDTM TS (Trial Summary) 자동 생성 | 미지원 | 수동 작성 필요 |
| MedDRA 코딩 연계 | 미지원 | AE 도메인 외 범위 |
| 가속 안전성 데이터(FAERS) 연계 | 미지원 | 범위 외 |

---

## 13. 구현 코드 골격

### 13.1 `src/pkplugin/cdisc/sdtm.py`

```python
"""CDISC SDTM PC/EX/DM/VS/LB 도메인 임포트.

참조: CDISC SDTM IG v3.4
"""
from __future__ import annotations

import pandas as pd
import pyreadstat
from pathlib import Path

from pkplugin.schemas import ConcentrationRecord, DoseRecord, CovariateRecord


def load_sdtm_domain(path: str | Path) -> pd.DataFrame:
    """SAS XPT 또는 CSV SDTM 도메인 로드."""
    p = Path(path)
    if p.suffix.lower() in (".xpt", ".sas7bdat"):
        df, _ = pyreadstat.read_xport(str(p))
    elif p.suffix.lower() == ".csv":
        df = pd.read_csv(p, dtype=str)
    else:
        raise ValueError(f"Unsupported format: {p.suffix}")
    return df.rename(columns=str.upper)  # 변수명 대문자 강제


def pc_to_concentration_records(
    pc: pd.DataFrame,
    ex: pd.DataFrame,
) -> list[ConcentrationRecord]:
    """SDTM PC + EX → ConcentrationRecord 리스트."""
    # EX에서 USUBJID별 첫 투여 EXSTDTC 추출
    ref_times = (
        ex.sort_values("EXSTDTC")
        .groupby("USUBJID")["EXSTDTC"]
        .first()
        .to_dict()
    )
    records: list[ConcentrationRecord] = []
    for _, row in pc.iterrows():
        usubjid = row["USUBJID"]
        exstdtc = ref_times.get(usubjid)
        if exstdtc is None:
            raise ValueError(f"No EX record found for USUBJID={usubjid}")
        elapsed = normalize_pcdtc_to_elapsed(
            pcdtc=row["PCDTC"],
            exstdtc=exstdtc,
            pceltm=row.get("PCELTM"),
        )
        conc_val = (
            float(row["PCSTRESN"])
            if pd.notna(row.get("PCSTRESN")) and row.get("PCSTRESN") != ""
            else None
        )
        bloq = conc_val is None or str(row.get("PCORRES", "")).startswith("<")
        records.append(
            ConcentrationRecord(
                subject_id=usubjid,
                time=elapsed,
                concentration=conc_val,
                analyte=row.get("PCTESTCD", "UNKNOWN"),
                matrix=_map_pcspec(row.get("PCSPEC", "")),
                bloq=bloq,
                raw_concentration=row.get("PCORRES"),
            )
        )
    return records


def _map_pcspec(pcspec: str) -> str:
    mapping = {
        "PLASMA": "plasma", "SERUM": "serum",
        "BLOOD": "blood", "URINE": "urine",
    }
    return mapping.get(pcspec.upper(), "other")


def _map_sex(sex_code: str) -> str:
    return {"M": "M", "F": "F"}.get(str(sex_code).upper(), "U")
```

### 13.2 `src/pkplugin/cdisc/adam.py`

```python
"""CDISC ADaM ADPC / ADPP 도메인 익스포트.

참조: CDISC ADaM IG v1.3
"""
from __future__ import annotations

import pandas as pd
import pyreadstat
from pathlib import Path
from datetime import datetime

from pkplugin.schemas import NCAParameterRow
from pkplugin.cdisc.paramcd import NCA_PARAMCD_MAP  # 6절 매핑 테이블


def nca_results_to_adpp(
    results: list[NCAParameterRow],
    dm: pd.DataFrame,
    study_id: str,
) -> pd.DataFrame:
    """NCAParameterRow 리스트 → ADPP DataFrame."""
    rows = []
    for r in results:
        paramcd = NCA_PARAMCD_MAP.get(r.parameter)
        if paramcd is None:
            continue  # 미매핑 파라미터 스킵 (경고 기록)
        dm_row = dm[dm["USUBJID"] == r.subject_id]
        rows.append({
            "STUDYID": study_id,
            "USUBJID": r.subject_id,
            "PARAMCD": paramcd.code,
            "PARAM": paramcd.label,
            "AVAL": r.value,
            "AVALU": r.unit,
            "PPCAT": "NON-COMPARTMENTAL",
            "PPSCAT": "PLASMA ANALYTE",
            "ARM": dm_row["ARM"].iloc[0] if len(dm_row) else "",
            "VISIT": r.period or "Day 1",
        })
    return pd.DataFrame(rows)


def export_to_xpt(df: pd.DataFrame, output_path: str | Path) -> None:
    """DataFrame → SAS XPT 파일 저장."""
    pyreadstat.write_xport(df, str(output_path))


def build_define_xml(
    adpc: pd.DataFrame,
    adpp: pd.DataFrame,
    output_path: str | Path,
    study_id: str,
    ct_version: str,
) -> None:
    """ADPC + ADPP 메타데이터 → Define-XML 2.1 생성."""
    # 실제 구현: lxml 기반 XML 빌더 사용
    # XSD 검증: cdisc-define-2.1.0.xsd 대조
    ...
```

---

## 14. `cdisc-mapping` 스킬 (v2.0)

`skills/cdisc-mapping/SKILL.md` 로 배포되는 대화형 스킬로, SDTM 컬럼 매핑과 USUBJID 처리를 사용자와 협력하여 수행합니다.

### 14.1 스킬 트리거

```
사용자: "SDTM PC 데이터를 pk-copilot에 불러와서 NCA 돌려줘"
사용자: "/cdisc-mapping으로 PC 도메인 정의해줘"
```

### 14.2 스킬 수행 단계

```
[Step 1] import_sdtm(pc_path, ex_path, dm_path) 호출
          → 컬럼 목록 반환

[Step 2] 필수 변수 존재 확인
          - USUBJID, PCSTRESN, PCDTC, EXSTDTC 없으면 사용자에게 수동 매핑 요청
          예) "SUBJECT_ID 컬럼을 USUBJID로 매핑하겠습니다. 맞습니까? [Y/n]"

[Step 3] USUBJID 형식 검증
          - "{STUDYID}-{SITEID}-{SUBJID}" 패턴 확인
          - 불일치 시: "USUBJID가 표준 형식이 아닙니다. 대상자 식별에 SUBJECT_ID를 사용하겠습니다."

[Step 4] PCSTRESU (농도 단위) 확인
          - CDISC CT 목록 대조
          - 비표준 단위 발견 시: "PCSTRESU='ug/L'는 CT에 없습니다. 'ng/mL'과 동일 처리하겠습니까?"

[Step 5] 시간 정규화 미리보기
          - USUBJID 샘플 1명의 PCDTC / EXSTDTC 차이 계산 결과 표시
          - 이상한 음수 또는 극단값 경고

[Step 6] import_sdtm() 최종 실행 → NormalizedDataset 반환
          → run_nca() 로 연계
```

### 14.3 USUBJID 모호성 해소 예시

```
[CDISC Mapping] USUBJID 검토 중...
발견: "001-001" 형식 (STUDYID 없음)
→ 스터디 ID "STUDY01" 로 접두사 추가하여 "STUDY01-001-001" 로 변환합니다. [Y/n]
```

---

## 참조 문서

| 문서 | 링크 |
|---|---|
| CDISC SDTM IG v3.4 | https://www.cdisc.org/standards/foundational/sdtm/sdtm-ig |
| CDISC ADaM IG v1.3 | https://www.cdisc.org/standards/foundational/adam/adamig |
| CDISC ADaM for PK | https://www.cdisc.org/standards/foundational/adam |
| CDISC Controlled Terminology | https://www.cdisc.org/standards/terminology/cdisc-controlled-terminology |
| Define-XML 2.1 | https://www.cdisc.org/standards/data-exchange/define-xml |
| Pinnacle21 Community Validator | https://www.pinnacle21.com/tools |
| CDISC Pilot Study 02 | https://github.com/cdisc-org/sdtm-adam-pilot-project |
| FDA Study Data Technical Conformance Guide | https://www.fda.gov/media/136460/download |
