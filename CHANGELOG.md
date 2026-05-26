# Changelog

All notable changes to pk-copilot are documented in this file.

## [2.0.2] - 2026-05-26

### Fixed — Manual cross-verification of every algorithm default

5-agent parallel audit of all four bundled Phoenix WinNonlin manuals
(5.3 / 6.4 / 8.3 / Phoenix 1.4) closed every `📋 TODO: cite manual`
marker and uncovered multiple **incorrect defaults** that we had been
inheriting from informal sources. Numerical correctness fixes:

- **AUC method default**: WinNonlin 5.3 / 6.4 / 8.3 NCA defaults are
  **all `linear` trapezoid** (Method 2 "Linear Trapezoidal Linear
  Interpolation"). Previously we shipped 6.4/8.3 as `linear_up_log_down`
  by default — that is an *available option*, not the default. Existing
  callers can request the old behavior explicitly via
  `NCAConfig(auc_method="linear_up_log_down")`.
- **C0 method for v5.3**: WinNonlin 5.3 uses **log back-extrapolation
  from the first two quantifiable points** (identical algorithm to
  6.4/8.3) — we had wrongly set 5.3 to `"observed"`.
- **v5.3 `_pred` variants**: WNL 5.3 Table B-4 confirms the manual
  emits `Clast_pred`, `AUCINF_pred`, `AUC_%Extrap_pred`,
  `AUMCINF_pred`, `MRTINF_pred`, `VSS_pred`. We had wrongly marked 5.3
  as obs-only. `output_pred_variants` default for 5.3 changed
  `False → True`.
- **Lambda_z Tmax inclusion is version-aware**:
  - WNL 5.3 NCA ("Points prior to Cmax"): the Cmax data point itself
    MAY enter the Best Fit candidate windows → `fit_lambda_z` now uses
    `t >= tmax` for `winnonlin_version="5.3"`.
  - WNL 6.4 / 8.3 ("Points prior to Cmax, **and the point at Cmax for
    non-bolus models**"): Cmax point explicitly excluded → continues
    `t > tmax` (strict).
- **Output column names**: corrected `No_points_lambda_z` →
  `No_points_Lambda_z` (capital L per WNL output); `Vss` →
  `Vss_obs` / `Vss_pred` per WNL 8.3 column convention.
- **PK Model registry numbering** (`comp/models.py`): every
  WinNonlin model id was wrong. Confirmed correct mapping from manuals:
  Model 1 = 1-cmt IV bolus, Model 2 = 1-cmt IV infusion (was: bolus+MM),
  Model 3 = 1-cmt extravascular no lag (was: IV infusion),
  Model 18 = 3-cmt IV bolus (was: 13), and MM variants live in the
  separate MM.LIB (Models 301–304) so `winnonlin_model_id=None` for
  our `cmt*_mm` entries.
- **PD model numbering**: WNL PD models are 101–110, not "101+". Added
  full mapping table. WNL Model 103 changed between 5.3 (Sigmoid Emax)
  and 6.4+ (plain Emax with new IC50 naming).
- **IDR III / IV parameter naming**: `Smax`/`SC50` → `Emax`/`EC50`
  to match WNL convention (Models 53/54).
- **Effect compartment**: `ke0` output label → `Ke0` (capital K per
  WNL 6.4 p.385).
- **Swing formula**: `(Cmax−Cmin)/Cmin` (ratio, NO `× 100`).
  Also: Swing is **WNL 8.3-only** — 5.3 and 6.4 do not define it.
- **MRT for IV infusion v5.3**: confirmed `AUMC/AUC − T_inf/2` (we
  had hedged in the matrix; it does NOT differ from 6.4/8.3).
- **AIC formula**: WNL uses `N·ln(WRSS) + 2·p` (not
  `N·ln(WRSS/N) + 2·k` — same ranking but absolute values differed
  by `−N·ln(N)`). Code aligned to WNL convention.
- **BE Kenward-Roger reference removed**: WNL only ships Satterthwaite
  df — KR mention deleted from docs.

### Implementation gaps closed

- SDTM **VS** (vital signs / body weight) and **LB** (laboratory /
  creatinine) loaders implemented in `cdisc/sdtm.py`. `import_sdtm`
  MCP tool now accepts `vs_path`/`lb_path`.
- `export_adam` MCP tool now actually writes the ADaM ADPC dataset
  alongside ADPP (previously returned `adpc_status="not_implemented_v2_0"`
  while `build_adpc()` was already implemented).
- `generate_report` MCP tool now invokes `report.plots.*` and embeds
  per-subject concentration-time, Lambda_z regression, spaghetti, and
  mean ± SD plots (previously emitted `plot_paths: []`).
- `fit_pk_model` MCP wrapper now forwards `bounds` / `solver` /
  `method` parameters (previously dropped).
- `run_be` MCP wrapper now accepts an `endpoints: list[str]`
  parameter and returns `be_results` list (previously single endpoint
  only, despite the documented multi-endpoint shape).
- All `impl_*` MCP wrappers now forward `user` / `audit_dir` —
  this is what makes Part 11 controlled mode reachable from the
  MCP client.
- `AuditEntry.user` is now populated when callers pass `user=...`
  to `new_entry()` (previously hardcoded `None`).
- New agents: `agents/report-writer.md`, `agents/data-curator.md`
  (referenced by `docs/01-architecture.md` but were missing).
- `report/quarto.py` removed from documented formats (it does not
  exist and would mislead users). `generate_report` now restricts
  `format` to `"html" | "pdf"`.
- `NCAConfig.dose_normalization=True` is now honored — produces
  `Cmax_D`, `AUClast_D`, `AUCINF_D` rows. `weight_normalization="per_kg"`
  emits an explicit `"not_implemented_per_kg"` warning (deferred to
  v2.1). `c0_method="auto"` now correctly resolves to
  `log_back_extrap`.
- Warnings added for silent option mismatches: `bloq_custom` set
  without `bloq_policy="custom"`; `lambda_z_manual` set without
  `lambda_z_method="manual"`; failed partial AUC windows.

### Changed — Documentation

- Every `📋 TODO` marker removed and replaced with explicit manual
  citations (WNL 5.3 p.NNN, WNL 6.4 §X.Y, WNL 8.3 §X.Y).
- `docs/04-winnonlin-version-matrix.md` rewritten with verified
  per-version values.
- `docs/03-algorithms/*` 9 files cleaned of TODO markers, added
  version-aware notes.
- `docs/03-algorithms/README.md` now declares "every algorithm
  manual-verified 2026-05".

### Tests
- **562 passing** (up from 536), mypy --strict clean, ruff clean.
- New regression tests for version-aware Tmax inclusion in
  `tests/test_lambda_z.py`.
- Cross-version golden expected values regenerated by
  `scripts/golden_regen.py` to reflect the new defaults; the
  expected-differences table in `tests/golden/cross-version/` now
  accurately marks Lambda_z-derived parameters as differing 5.3 vs
  6.4/8.3 (because of the Tmax-inclusion behavior change).

### Not changed
- Public API signatures of `NCAConfig`, `calculate_nca`, MCP tool
  names — backward compatible.
- Audit chain crypto, e-signature, RBAC, WORM lock — unchanged.

## [2.0.1] - 2026-05-25

### Changed — Positioning clarity (no behavioural rollback)

After a CCG dual review (Codex + Gemini, see
`.omc/artifacts/ask/codex-i-m-reviewing-a-regulatory-positioning-question-*.md`
and `.omc/artifacts/ask/gemini-i-m-reviewing-the-positioning-of-pk-copilot-*.md`)
v2.0 messaging is reframed from **"21 CFR Part 11 compliant"** overclaim to
**"Part 11-enabling controls for the deterministic execution path; LLM
orchestration is exploratory unless qualified under customer QMS"**.

Rationale: Part 11 (1997) presumes a deterministic system **and** a predicate
rule (IND 21 CFR §312.57/§312.62, NDA §314.50, etc.). pk-copilot v2.0 ships
the technical primitives but is not itself a compliant system. FDA's 2025
draft *"Considerations for the Use of AI to Support Regulatory Decision-Making
for Drug and Biological Products"* additionally requires context-of-use, model
risk, credibility assessment, and lifecycle control whenever AI output enters
regulatory evidence. Both reviewers reached the same conclusion: the only
defensible claim is for the **deterministic CLI/MCP execution path**, not the
LLM orchestration layer.

### Added

- **Execution Mode metadata** — every audit entry, MCP response, CLI run, and
  HTML/PDF report now carries `execution_mode` (`exploratory` | `controlled`)
  and `llm_orchestrated` (bool). Controlled mode requires
  `PKPLUGIN_PART11_ENABLED=1` **and** a non-empty user dict
  (`pkplugin.compliance.classify_execution_mode`).
- `pkplugin.compliance.ExecutionMode` Literal + `classify_execution_mode()`
  classifier.
- `AuditChainEntry.execution_mode` and `.llm_orchestrated` — hash-protected in
  the canonical body, so single-byte tampering with the mode field breaks
  `verify()`.
- HTML/PDF reports render a colored mode badge at the top
  (green `[Controlled]` / amber `[Exploratory — LLM Orchestrated]`).
- New disclosure documents:
  - `docs/12-intended-use.md` — Intended Use Statement (medical-device-style).
  - `docs/13-compliance-matrix.md` — 2-column "we provide" / "your organization
    provides" responsibility split, mapped to Part 11 sub-sections.
  - `docs/14-llm-boundary-disclosure.md` — LLM-in-the-Loop boundary diagram +
    non-determinism risks + reproducibility semantics.
- `docs/10-21cfr-part11.md` §17 — "Execution Modes & LLM-in-the-Loop Boundary"
  with two-mode ASCII data flow.
- `--user-id` CLI argument on `nca`, `be`, `fit`, `pd-fit`, `sign`, `lock`
  commands for controlled-mode identity passing.
- 26 new regression tests (`tests/test_part11_messaging.py`,
  `tests/test_audit_execution_mode.py`) covering README messaging,
  classifier semantics, AuditEntry/AuditChain mode threading, and tamper
  detection on the mode field.

### Fixed

- `docs/10-21cfr-part11.md` §3 — Subpart table corrected (Codex review):
  §11.10 = closed systems, §11.30 = open systems, §11.50 = signature
  manifestations, §11.70 = signature/record linking, §11.200 = non-biometric
  components, §11.300 = password controls.
- `docs/10-21cfr-part11.md` §16 — disclaimer strengthened with explicit
  *"pk-copilot is NOT a 21 CFR Part 11 compliant system"* assertion plus
  predicate-rule responsibility text in Korean and English.
- README, `docs/00`, `docs/01`, `docs/02`, `docs/09` and `docs/10` —
  systematically replaced "21 CFR Part 11 compliant" / "Regulated Edition"
  overclaims with "Part 11-enabling" / "Regulated-Capable Edition".
- `impl_get_compliance_status` MCP response — new fields
  `execution_mode_supported`, `current_mode_hint`, `part11_claim:
  "enabling-controls-only"`, and a rewritten `disclaimer` body.

### Not changed

- Algorithms, numerical results, audit chain crypto, e-signature primitives,
  WORM lock — all v2.0.0 behaviour preserved.
- All 510 v2.0.0 tests still pass (536 total now, +26 new regression tests).
- Mypy --strict clean across 44 source files.
- v2.0.0 tag remains; v2.0.1 is a positioning + metadata patch on top.

## [2.0.0] - 2026-05-25

### Added — CDISC standards
- SDTM PC/EX/DM import (`pkplugin.cdisc.sdtm`).
- ADaM ADPC/ADPP export (`pkplugin.cdisc.adam`).
- PARAMCD controlled-terminology registry (23 PK NCA codes).
- Define-XML 2.1 generation (`pkplugin.cdisc.define_xml`).
- Pinnacle21-style structural validation (`pkplugin.cdisc.validate`).
- MCP tools: `import_sdtm`, `export_adam`, `validate_cdisc`.

### Added — 21 CFR Part 11 technical controls
- Append-only HMAC hash-chained audit log (`pkplugin.compliance.audit_chain`):
  `this_hash` now covers ALL entry fields (user, reason, workstation,
  ntp_source, action, before, after, payload) — single-byte tampering
  in any field is detected by `verify()`.
- Ed25519 detached signatures with bundle-hash linkage
  (`pkplugin.compliance.signatures`). POSIX-canonical path separators
  so run hashes are reproducible across OSes.
- RBAC with session-expiry enforcement (`pkplugin.compliance.access`).
  `check_permission()` now also calls `is_session_valid()`.
- WORM record retention with separation-of-duties (`pkplugin.compliance.retention`).
  `lock_run(require_distinct_signers=True)` rejects identical signers
  across the required authored/reviewed/approved chain.
- MCP tools: `sign_record`, `lock_run`, `verify_audit_chain`,
  `verify_signatures`, `get_compliance_status`.
- CLI subcommands: `keygen` (with `--force`), `sign`, `lock`,
  `verify-chain`, `verify-sigs`, `compliance-status`.
- Private key + HMAC key files restricted to 0o600 by default.
- HMAC key location configurable via `PKPLUGIN_CHAIN_KEY_PATH`
  (with explicit warning when stored alongside the chain).

### Changed
- Version bumped to 2.0.0.
- `__init__.py` no longer carries the "NOT Part 11 compliant" notice
  (replaced with "v2.0 provides Part 11 technical controls").

### Regulatory boundary (v2.0)
v2.0 provides **technical** controls for 21 CFR Part 11. **Procedural**
controls (SOPs, training records, account governance, periodic audit
review) remain the customer organization's responsibility. See
`docs/10-21cfr-part11.md` for the full disclaimer and the verbatim
compliance matrix.

### Fixed (dual review — Opus + Codex)
- audit_chain hash chain: critical hole where `user`/`reason`/`workstation`/
  `ntp_source` could be tampered without detection (Codex CRITICAL).
- compute_run_hash deterministic across OSes (POSIX separators).
- lock_run enforces separation of duties.
- impl_sign_record rejects empty auth_token.
- impl_lock_run writes audit-chain BEFORE WORM lock (no silent failures).
- unlock_run checks session expiry.
- CLI keygen requires `--force` to overwrite existing keys.
- impl_export_adam returns `adpc_status="not_implemented_v2_0"` instead
  of silently writing only ADPP.
- ADPC now includes PARCAT1 (analyte category traceability).

### Tests
506 passing, mypy --strict clean across 44 source files. Includes 14
new regression tests covering every dual-review finding (per-field
tamper detection, POSIX path canonicalization, separation-of-duties,
auth_token rejection, session-expiry enforcement, CLI overwrite
protection).

## [1.0.0] - 2026-05-25

### Added
- CLI entry point (`pkplugin`) with subcommands: nca, be, fit, pd-fit,
  report, compare, doctor, sbom.
- SBOM generation (CycloneDX 1.6 JSON).
- Golden validation matrix across WinNonlin 5.3 / 6.4 / 8.3 default sets.

### Changed
- Version bumped to 1.0.0 (Production).

### Earlier (development)
- v0.5: HTML/PDF reports + R PKNCA/NonCompart cross-validation backend.
- v0.4: PK/PD link models (Emax, Sigmoid Emax, Effect compartment,
  Indirect Response I-IV).
- v0.3: 1/2/3-compartment models (closed-form + ODE) + lmfit NLS.
- v0.2: Multi-subject NCA + Bioequivalence (TOST, 90% CI, mixed model).
- v0.1: Single-subject NCA MVP (Cmax, AUC, Lambda_z, CL, Vz, Vss)
  with WinNonlin-compatible algorithms.

### Regulatory Disclaimer
v1.0 is NOT a 21 CFR Part 11 compliant system. Part 11 technical
controls are planned for v2.0. See docs/10-21cfr-part11.md.
