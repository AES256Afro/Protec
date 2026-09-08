# Database backup and staged restore

Create a consistent snapshot while the local control plane is running:

```sh
cd /Users/chris/Projects/Protec
python3 -m protec.database backup --source .protec/protec.db --destination .protec/backup-001.db
```

The destination must be a new file in an existing directory. Protec uses SQLite's backup API, checks database integrity and required tables, then creates the destination atomically with owner-only permissions. It refuses existing paths and symlinks. Committed WAL data is included. Backups contain device inventory, hashed device credentials, token metadata, queued jobs and audit history. Treat them as sensitive operational data.

Stage a restore without replacing the live database:

```sh
mkdir -m 700 .protec/recovery
python3 -m protec.database restore --source .protec/backup-001.db --destination .protec/recovery/protec.db
```

This validates and creates a new database. It does not switch the running server to it. For an intentional local cutover, stop the existing server, securely copy the existing `.protec/admin-token` to `.protec/recovery/admin-token` with owner-only permissions, and start `python3 -m protec.server --data .protec/recovery`. Keep the original data directory for recovery. Never run two control planes against the same device credentials during cutover.

Administrator tokens and agent state files are outside the database; back them up separately using protected storage. This command does not copy them or expose their values. Restoring an older snapshot can restore earlier token/device authorization state, including records revoked since that snapshot. Review and reapply revocations before permitting device traffic. Planned credential rotation/recovery controls will address that lifecycle explicitly.

The current release supports the existing unversioned schema and reserves schema version 1. A versioned migration runner, retention policy and automated backup scheduling remain separate M2 work. Restore testing verifies the database and device authentication in an isolated test, not production cutover or OS service recovery.
