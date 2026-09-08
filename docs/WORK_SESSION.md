# Platform build until complete

- Authorization: continue until the requested platform roadmap is complete. User removed the time cutoff on 2026-09-08 at 16:43 UTC.
- Project: `/Users/chris/Projects/Protec`; remote: `AES256Afro/Protec`; branch: `main`.
- Continuation automation: `protec-four-hour-platform-build`, every 10 minutes without a time cutoff. Do not duplicate it.
- Local device: MacBook, already enrolled. Existing foreground control plane listens on 127.0.0.1:8765 and agent uses `.protec/agent.json`.
- Source of milestone scope/dependencies: `docs/ROADMAP.md`.
- Baseline: `9e3019a`, 9 Python tests and 2 JavaScript tests passed, hosted Linux CI passed.

The earlier four-hour schedules are superseded. Continue independent work until milestone acceptance criteria are satisfied. If actual hardware, credentials, or a deployment decision is required, complete independent slices before asking a concrete question.

## Current work

- M0/M1: local inventory, enrollment lifecycle and MacBook onboarding delivered.
- M2: backup/staged restore, transactional migrations, paginated history, readiness and conservative retention delivered. Audit retention is intentionally preserved; production resilience remains M15.
- M6 preparation: read-only Homebrew formula and installed Debian package inventory delivered at d29ccac with hosted CI passing. Last local package report contained 34 formulae. Package mutation awaits M3/M4.
- M3 first slice: local service credentials with viewer/operator/administrator roles, 1-720 hour expiry, revocation, metadata pagination and actor attribution implemented. UI hides actions outside the role; server independently rejects unauthorized routes. Bootstrap token remains intact. SSO/MFA, device-specific scopes, rotation recovery and protected secret stores remain.

## Latest verification

- 34 Python tests plus 2 JavaScript tests passed locally. Tests exercise role escalation denials, device/service identity separation, expiry/revocation, safe metadata and pagination.
- Browser verified viewer restrictions, administrator Access view, test credential issuance and clearing its one-time secret on close. Credential tests used a disposable database, not the live workspace.
- Pre-schema-v2.db backup created. Copy of the live schema-1 database upgraded to schema 2 with device records intact and no issued service credentials. Live control plane restarted on schema 2; bootstrap administrator and device check-ins verified. No live service credentials issued. Verify latest exact-commit CI at the next checkpoint.
- Current foreground control plane and agent use .protec; inspect process ids before restarting. The agent reports packages every five minutes or upon an inventory refresh.

## Next work

1. Live schema-2 verification completed; publish this checkpoint and verify hosted CI.
2. Continue M3: device-specific authorization scopes and recoverable credential rotation. Keep role/target checks centralized; avoid parallel implementations per feature.
3. Continue M4 typed, signed, bounded execution. M5 policy/configuration previews and read-only network/SSH/WireGuard inventory can proceed while external identity/native dependencies remain.

There is no deadline. Continue all meaningful independent milestones. Only pause for completion, user cancellation, or a concrete external dependency after independent work is exhausted. Do not mark the full M3 or platform complete based on this local credential foundation.
