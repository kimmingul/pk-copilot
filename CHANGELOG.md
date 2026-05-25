# Changelog

All notable changes to pk-copilot are documented in this file.

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
