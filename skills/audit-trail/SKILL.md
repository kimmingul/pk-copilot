# audit-trail — 21 CFR Part 11 Audit Trail Skill

Guides users through verifying audit trail integrity, understanding the hash chain structure, and interpreting compliance status.

## When to Use

Invoke this skill when:
- A user asks to verify audit chain integrity
- A user wants to understand if their run is tamper-evident
- A user needs to export audit records for regulatory inspection
- A user asks about Part 11 compliance status

## Core Capabilities

### 1. Hash Chain Verification

Every audit event is linked in an append-only JSONL chain:

```
Entry N-1: {this_hash: "sha256:abc..."}
Entry N:   {prev_hash: "sha256:abc...", ...}  ← tamper detection
```

Verify with:
```bash
pkplugin verify-chain --chain-dir pk_runs/<run_id>
```

### 2. Audit Entry Fields (§11.10(e) — 6-tuple)

| Field | WHO/WHAT/WHEN/WHERE/WHY |
|---|---|
| `user.id` | WHO — authenticated user identity |
| `action` | WHAT — operation performed |
| `timestamp_utc` | WHEN — NTP-synchronized UTC timestamp |
| `run_id` | WHERE — analysis run context |
| `reason` | WHY — reason for the action |
| `before` / `after` | BEFORE→AFTER — state delta |

### 3. HMAC Tamper-Evidence

Each entry includes an HMAC-SHA256 computed with a server-held key.
If any byte in the chain file changes, `verify-chain` reports violations.

## Step-by-Step: Verifying a Run's Audit Trail

```bash
# 1. Check compliance controls are available
pkplugin compliance-status

# 2. Verify signatures for the run
pkplugin verify-sigs <run_id>

# 3. Verify audit chain integrity
pkplugin verify-chain --chain-dir pk_runs/<run_id>
```

## Interpreting verify-chain Output

```json
{
  "status": "ok",
  "ok": true,
  "n_entries": 12,
  "violations": []
}
```

If `ok` is `false`, `violations` lists each issue with line number and event ID.

## Regulatory Reference

| Control | §11 Requirement | Implementation |
|---|---|---|
| Append-only log | §11.10(e) | JSONL opened in mode 'a' |
| Hash chain | §11.10(e) | SHA-256 prev→this linkage |
| HMAC | §11.10(e) | HMAC-SHA256 with server key |
| Timestamp | §11.10(e) | ISO 8601 UTC with microseconds |
| WHO/WHAT/WHEN/WHERE/WHY | §11.10(e) | 6-tuple enforced on every entry |

## Part 11 Disclaimer

pk-copilot v2.0 provides technical controls. Full 21 CFR Part 11 compliance
requires organizational procedural controls (SOPs, training, account management).
See `docs/10-21cfr-part11.md §16` for the complete disclaimer.
