# /sign — Sign a Run Bundle

Sign a pk-copilot analysis run with an Ed25519 electronic signature, satisfying 21 CFR Part 11 §11.50 requirements (signer identity, timestamp, and meaning of signature).

## Usage

```
/sign <run_id> --identity <user> --meaning <authored|reviewed|approved> --key <path>
```

## Parameters

| Parameter | Required | Description |
|---|---|---|
| `run_id` | Yes | The run ID to sign (e.g. `2026-05-25-042`) |
| `--identity` | Yes | Signer identifier (email or user ID) |
| `--meaning` | Yes | `authored`, `reviewed`, or `approved` |
| `--key` | Yes | Path to Ed25519 private key PEM file |
| `--passphrase` | No | Key passphrase if key is encrypted |
| `--auth-token` | No | TOTP re-authentication token (v2.0 placeholder) |
| `--out` | No | Audit base directory (default: `$PKPLUGIN_AUDIT_DIR` or `pk_runs/`) |

## Signature Workflow (§11.10(f) State Machine)

```
Draft → Authored → Reviewed → Approved (→ Locked)
```

| Step | Role Required | Meaning |
|---|---|---|
| 1 | Analyst | `authored` |
| 2 | Approver | `reviewed` |
| 3 | Approver | `approved` |

## Examples

```bash
# Step 1 — Analyst authors the run
pkplugin sign 2026-05-25-042 \
  --identity analyst@example.com \
  --meaning authored \
  --key keys/analyst.key

# Step 2 — Approver reviews
pkplugin sign 2026-05-25-042 \
  --identity approver@example.com \
  --meaning reviewed \
  --key keys/approver.key

# Step 3 — Final approval
pkplugin sign 2026-05-25-042 \
  --identity director@example.com \
  --meaning approved \
  --key keys/director.key
```

## Regulatory Reference

- **§11.50(a)**: Signature components — signer name, date/time, meaning
- **§11.50(b)**: Signature linked to the specific record via canonical run hash
- **§11.70**: Ed25519 cryptographic binding (non-forgeable)
- **§11.200(a)**: Two-factor authentication placeholder (TOTP + private key)

## Related Commands

- `/keygen` — Generate an Ed25519 keypair
- `/lock` — Finalize a run after all signatures are complete
- `/verify` — Verify signatures and audit chain integrity
