# /cdisc-import and /cdisc-export Commands

## /cdisc-import

Import CDISC SDTM PC + EX + optional DM domains into pk-copilot canonical format.

### Usage

```
/cdisc-import pc=<path> ex=<path> [dm=<path>] [analyte=<PCTESTCD>] [matrix=<PCSPEC>]
```

### Arguments

| Argument | Required | Description |
|---|---|---|
| `pc` | Yes | Path to SDTM PC domain (CSV or SAS XPT) |
| `ex` | Yes | Path to SDTM EX domain (CSV or SAS XPT) |
| `dm` | No | Path to SDTM DM domain for covariates |
| `analyte` | No | Filter by PCTESTCD value (e.g. `DRUGX`) |
| `matrix` | No | Filter by PCSPEC value (e.g. `PLASMA`) |

### Behaviour

1. Validates required SDTM columns are present (USUBJID, PCSTRESN, PCDTC, EXSTDTC, etc.)
2. Maps EXROUTE to pk-copilot canonical route (iv_bolus, iv_infusion, oral, etc.)
3. Normalises PCDTC → elapsed time (hr) relative to first EXSTDTC per subject
4. Prioritises PCELTM (ISO 8601 duration) over PCDTC arithmetic when present
5. Writes canonical CSVs to audit run directory
6. Returns run_id, file paths, subject count, and any warnings

### Example

```
/cdisc-import pc=data/pc.csv ex=data/ex.csv dm=data/dm.csv analyte=DRUGX matrix=PLASMA
```

---

## /cdisc-export

Export NCA results as ADaM ADPP dataset + optional Define-XML 2.1.

### Usage

```
/cdisc-export run_id=<nca_run_id> [output_dir=<path>] [define_xml=true|false]
```

### Arguments

| Argument | Required | Description |
|---|---|---|
| `run_id` | Yes | NCA run ID from a previous `run_nca` call |
| `output_dir` | No | Output directory (default: `<audit_dir>/<run_id>/adam/`) |
| `define_xml` | No | Include Define-XML 2.1 (default: true) |

### Behaviour

1. Loads NCA parameters.csv from the audit run directory
2. Maps pk-copilot parameter names → CDISC PARAMCD/PARAM via paramcd registry
3. Builds ADPP DataFrame in ADaM BDS structure
4. Validates ADPP with Pinnacle21-style checks
5. Optionally generates Define-XML 2.1 metadata document
6. Returns file paths and validation summary

### Example

```
/cdisc-export run_id=2026-05-25-001 define_xml=true
```

---

## Notes

- SAS XPT output is planned for v2.1 (post-v2.0). Currently CSV only.
- ADPC export from NCA run is planned for v2.1 when PC canonical CSV is present.
- For full Pinnacle21 validation, submit the exported CSV + define.xml to
  Pinnacle21 Community at https://www.pinnacle21.com/tools
- See `docs/09-cdisc-support.md` for the complete CDISC support specification.
