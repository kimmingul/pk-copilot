# /lock — Finalize a Run Bundle

Lock a pk-copilot run bundle after all required electronic signatures are present. Once locked:

- All files become read-only (OS-level 0o444)
- A `LOCKED.json` manifest is written with bundle SHA-256 hash
- The lock event is recorded in the audit chain (§11.10(e))

Implements §11.10(c) (record retention) and §11.10(f) (operational sequencing).

## Usage

```
/lock <run_id> --reason <text> [--locked-by <user>] [--require-signatures <list>]
```

## Parameters

| Parameter | Required | Description |
|---|---|---|
| `run_id` | Yes | Run ID to finalize |
| `--reason` | Yes | Lock reason (e.g. `"Final BE submission"`) |
| `--locked-by` | No | Identifier of the person locking (default: `cli-user`) |
| `--require-signatures` | No | Comma-separated required meanings (default: `authored,reviewed,approved`) |
| `--out` | No | Audit base directory |

## Prerequisites

All required signatures must be present and cryptographically valid before locking.
By default: `authored`, `reviewed`, and `approved`.

## Example

```bash
pkplugin lock 2026-05-25-042 \
  --reason "Final BE submission — Study ABC-101 SAD cohort" \
  --locked-by admin@example.com
```

## After Locking

| Action | Allowed |
|---|---|
| Modify result files | No (read-only) |
| Add signatures | No |
| Read files | Yes |
| Admin unlock (emergency) | Yes — with mandatory reason and audit event |

## Emergency Unlock

Only Admin role can unlock. The unlock event is permanently recorded in the
immutable audit chain even after the lock is removed.

```bash
pkplugin unlock 2026-05-25-042 \
  --admin-user admin@example.com \
  --reason "Data entry error confirmed by QA — Deviation DEV-2026-042"
```

## Regulatory Reference

- **§11.10(c)**: Record retention — accurate and complete records protected
- **§11.10(f)**: Operational sequencing — only valid state transitions allowed
- **§11.10(k)**: Administrative controls documented in audit chain
