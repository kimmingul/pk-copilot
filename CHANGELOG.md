# Changelog

All notable changes to pk-copilot are documented in this file.

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
