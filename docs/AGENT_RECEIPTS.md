# Unreleased: local inventory attempt journal

Source after the 0.5.0 tag adds a local journal to the command-line inventory agent. It records protocol-1 job attempts and server acknowledgements across restarts. This is not in the published 0.5.0 image or agent release.

The default location is `.protec/agent.json.receipts/journal.db`, beside the selected agent state file. A custom `--state` path gets its own adjacent `<state filename>.receipts` directory. The directory must be owned by the agent user with mode 0700, and the database must be a regular, single-link file owned by that user with mode 0600. Symlink targets and unsafe permissions are rejected. The journal binds to one exact control-plane origin and device ID, preventing accidental reuse after switching enrollment or server.

The journal stores job/attempt IDs, states, inventory digests and validated server receipt metadata. It never stores device credentials, lease tokens, inventory contents or completion request bodies. The existing agent credential remains in its separate state file; native Keychain/Windows secret stores are still future work. Local receipts currently require POSIX file protection, tested on macOS and Linux CI.

## Workflow and recovery

Before processing a newly delivered protocol-1 attempt, the agent commits a `started` record. After sending inventory, it stores the digest as `completion_pending` before submitting the completion. A matching acknowledgement becomes `acknowledged`. Legacy protocol-0 jobs remain compatible and do not receive fabricated local receipts.

The journal prevents processing the same recorded attempt twice. A locally acknowledged job is not automatically processed again while its evidence is retained. For this read-only job only, a new delivery attempt may repeat inventory collection after an uncertain prior attempt. This does not establish an execution policy for package mutations or other side effects.

A new server advertises `receipt_lookup: 1` in heartbeat responses. The agent then reconciles up to ten unresolved journal entries per cycle using device-authenticated `GET /api/job-receipt?job=JOB_ID`. The endpoint returns only that device's job status, attempt and safe receipt metadata; another device's or missing job returns unknown. Revoked devices and management credentials cannot use this agent endpoint.

If the server accepted completion but its response was lost, reconciliation can acknowledge the local record without resending a lease token or another completion. If the server has moved to a later attempt, the old entry becomes `superseded`. Cancellation and failure become `server_cancelled` and `server_failed`. Missing or inconclusive history stays `unknown`; the journal never turns uncertain work into an invented success. Receipts with an incorrect target, attempt, digest or schema are rejected rather than saved.

With an older server that does not advertise receipt lookup, normal protocol-1 acknowledgements can still be journalled, but a lost response remains unresolved until a compatible server is available. Journal errors withhold job acknowledgement; the agent logs the receipt failure. A journal that cannot be opened at startup stops the agent with a clear error.

## Inspection and capacity

Inspect local metadata without contacting the server:

```sh
python3 -m protec.agent --state .protec/agent.json --receipt-status
```

The command shows state counts and the latest 50 entries. It creates the empty private journal on first use if necessary. Keep journal directories beside protected agent state, outside shared writable locations. Receipt directories are excluded from this repository's Git tracking.

Capacity is capped at 10,000 records. At that boundary, terminal entries older than 30 days can be pruned. Unresolved entries and recent terminal evidence are preserved. If the journal remains full, new attempts are refused with an error; stop the agent and inspect/archive the journal before choosing how to proceed. Removing evidence also removes its replay protection, so it must not become an automatic recovery action for future side-effecting jobs.

SQLite uses DELETE journal mode with `synchronous=EXTRA`, plus `fullfsync` on macOS. EXTRA includes directory synchronization when committing DELETE-mode transactions, following [SQLite's durability guidance](https://www.sqlite.org/pragma.html#pragma_synchronous); the macOS flag uses the platform's stronger sync method where supported, as documented for [fullfsync](https://www.sqlite.org/pragma.html#pragma_fullfsync). These settings do not replace hardware and filesystem verification.

Tests cover journal reopening, abrupt process exit after a committed pending record, lost-response reconciliation through the HTTP control plane, scope/identity isolation, secret-free output, unsafe paths, bounded retention and conflicting receipts. Real power-loss testing and native service reboot/update validation remain separate acceptance gates. This journal is not a cryptographic signature or a guarantee of exactly-once privileged execution.
