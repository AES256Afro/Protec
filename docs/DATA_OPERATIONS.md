# History, health and retention

The main device dashboard displays the latest 100 enrollments. Its fleet counters cover all records, including devices outside that page. Search filters the loaded devices. The History view provides all device, job, enrollment-token and audit records in insertion order, loading 50 at a time. Refresh the collection to see new records; new inserts do not repeat older records while paging.

Administrator API routes:

- `GET /api/history?kind=audit&limit=50`: kinds are `audit`, `jobs`, `enrollments`, and `devices`. Page size is 1 to 100. Pass the returned `next_cursor` as `cursor` for the next page. A null cursor means the end. A cursor is scoped to its collection.
- `GET /api/health`: database readability, schema version, uptime, and full record counts. This is readiness evidence, not a full SQLite integrity scan. Use `python3 -m protec.database check --source .protec/protec.db` for an integrity scan.

History projections do not select device credential hashes. Enrollment-token identifiers are SHA-256 digests of random high-entropy tokens; they are not bearer credentials. Neither listing returns the token secret.

## Conservative retention

No retention job runs automatically. Preview eligible records:

```sh
python3 -m protec.maintenance --database .protec/protec.db --days 90
```

Supported retention windows are 30 to 3650 days. Eligible records are completed/cancelled jobs created before the cutoff with no audit event referencing them since that cutoff, and enrollment tokens that expired before the cutoff. Active/running jobs, device records, and all audit records are preserved. Audit retention/export requires a separate deliberate policy.

To apply a reviewed policy, supply a new backup destination:

```sh
python3 -m protec.maintenance --database .protec/protec.db --days 90 --apply --backup .protec/pre-retention-001.db
```

Apply reserves the database write transaction, takes a validated pre-change snapshot, deletes eligible records, and records the deletion counts in the audit trail. A failed backup aborts the transaction. It can briefly delay device check-ins while taking the snapshot. Restoring a backup is a separate operator action; it never replaces the running database automatically. Preview counts may change before apply because the agent can continue writing between those operations. Apply recomputes eligibility within its transaction.

The CLI runs with the permissions of the local database owner. The browser and HTTP API do not expose a deletion endpoint. This implementation is tested locally and in Linux CI; production load, external backup durability and remote failover remain M15 deployment gates.
