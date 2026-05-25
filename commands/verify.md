# /verify — Verify Audit Chain and Signatures

Verify the integrity of a run's audit chain and/or electronic signatures.

## Subcommands

### verify-chain

Verify that the audit chain JSONL file has not been tampered with.

```bash
pkplugin verify-chain [--chain-dir <dir>]
```

Checks each entry:
1. `prev_hash` matches the previous entry's `this_hash`
2. `this_hash` matches the recomputed hash of the entry fields
3. HMAC signature verifies with the chain key

### verify-sigs

Verify all electronic signatures for a specific run.

```bash
pkplugin verify-sigs <run_id> [--out <audit_dir>]
```

For each signature in `signatures.jsonl`:
1. Recomputes the canonical run bundle hash
2. Verifies the Ed25519 signature against the stored public key
3. Confirms the run hash matches (no files changed after signing)

## Examples

```bash
# Verify audit chain integrity
pkplugin verify-chain --chain-dir pk_runs/2026-05-25-042

# Verify signatures for a specific run
pkplugin verify-sigs 2026-05-25-042

# Check overall compliance status
pkplugin compliance-status
```

## Expected Output

```json
{
  "status": "ok",
  "ok": true,
  "n_entries": 12,
  "violations": []
}
```

## Regulatory Reference

- **§11.10(e)**: Computer-generated audit trail with tamper detection
- **§11.50(b)**: Electronic signatures linked to specific records
- **§11.70**: Signature non-forgeability — Ed25519 cryptographic verification
