# cdisc-mapping Skill

## 활성화 조건 (Trigger Patterns)

다음 중 하나에 해당하면 이 스킬을 자동으로 활성화합니다:

- "SDTM PC 데이터를 불러와"
- "SDTM 임포트"
- "cdisc import" / "/cdisc-import"
- "cdisc export" / "/cdisc-export"
- "ADPP 익스포트"
- "Define-XML 생성"
- "CDISC 매핑"
- "SDTM to ADaM"
- "USUBJID 형식"
- "PARAMCD 매핑"
- "Pinnacle21 검증"

## 스킬 설명

CDISC SDTM/ADaM 매핑 워크플로우를 단계별로 안내합니다.
cdisc-mapper 에이전트와 함께 작동하며, 다음 단계를 수행합니다:

1. SDTM PC + EX + DM 파일 불러오기 (`import_sdtm`)
2. 컬럼 매핑 및 USUBJID 형식 검증
3. 시간 정규화 미리보기
4. NCA 분석 실행 (`run_nca`)
5. ADaM ADPP 익스포트 (`export_adam`)
6. Pinnacle21-style 검증 (`validate_cdisc`)

## 에이전트

`cdisc-mapper` 에이전트를 사용합니다 (`agents/cdisc-mapper.md`).

## MCP 도구

- `import_sdtm(pc_path, ex_path, dm_path, analyte, matrix)`
- `export_adam(nca_run_id, output_dir, include_define_xml)`
- `validate_cdisc(dataset_path, domain)`

## 제한 사항 (v2.0)

- SAS XPT 출력은 v2.1에서 지원 예정
- ADPC 완전 익스포트는 v2.1에서 지원 예정
- PopPK ADaM은 v3에서 지원 예정
- CDISC Pilot Study 02 골든 테스트는 v2.1에서 추가 예정

## 참조

- `docs/09-cdisc-support.md`
- `commands/cdisc.md`
- `agents/cdisc-mapper.md`
