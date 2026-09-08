# Protec

A Linux-first endpoint management project, with Windows and macOS planned next. The goal is a dashboard for enrollment, security posture, logs, configurations, patches, and audited remote access.

**Version 0.1 is a runnable local inventory prototype.** It implements enrollment and device tracking. It does not yet enforce security policies, collect system logs, install patches, deploy configurations, or open remote sessions.

## Run locally on your MacBook or Linux

Requires Python 3.11 or newer. No third-party packages are required.

```sh
cd /Users/chris/Projects/Protec
python3 -m protec.server
```

Open http://127.0.0.1:8765. Paste the token from `.protec/admin-token` into the dashboard's connection form. The token is a local administrator credential: do not commit or share it. The dashboard keeps it in memory only.

On this Mac, copy the administrator token without displaying it:

```sh
pbcopy < /Users/chris/Projects/Protec/.protec/admin-token
```

Paste into the dashboard and select **Connect**. Paste the actual token contents, not the file path or masked dots. Malformed input is rejected with guidance before sending a network request.

Both the control plane and the inventory agent can run on your MacBook. No Linux machine or VM is needed to test enrollment, check-ins, inventory refresh, and revocation.

1. Select **Enroll device** to create a single-use token valid for 15 minutes.
2. In another terminal, from this checkout, run `python3 -m protec.agent --enroll`.
3. Paste the enrollment token into the hidden terminal prompt.
4. The foreground agent checks in every 30 seconds. Keep the terminal running.
5. Select **Refresh inventory** in the device row. The next check-in completes the job.
6. Select **Revoke** to reject further device authentication and cancel pending jobs.

Subsequent runs use `python3 -m protec.agent`. Use `--once` for one check-in, and `--state PATH` for an alternative enrollment state file. Revocation keeps historical inventory and audit events. To re-enroll a revoked device, stop the agent, remove its local state file, and enroll using a new token.

The inventory agent runs as the user who starts it and reports whether that user has administrator privileges. Root is not required for this slice. It does not install a service, elevate privileges, enable SSH, or alter the host. POSIX enrollment supports Linux and local macOS inventory testing. macOS inventory uses its product name and version. The privilege field describes the running process: a normal Terminal session reports standard privileges even if your macOS account belongs to the administrators group. Windows enrollment is intentionally blocked until protected credential storage is implemented.

The control plane binds only to loopback. This is for testing on a single host. Do not expose this prototype as a production service. The agent accepts HTTPS origins for future deployments, but reverse-proxy support and a hardened remote deployment have not been implemented or validated.

## Implemented

- SQLite device inventory and latest check-in time.
- Single-use, 15-minute enrollment tokens, consumed atomically. The Enrollments view lists token metadata and lets an administrator revoke unused tokens; secret values are never returned in that list.
- Unique device credentials; the server stores SHA-256 digests rather than bearer secrets.
- Separate administrator and device authentication.
- Inventory refresh queue with a two-minute lease and idempotent redelivery.
- Job ownership checks, device revocation, and cancellation of pending work.
- Audit events for enrollment-token creation, enrollment, refresh, completion, and revocation.
- Dashboard inventory search, connection counts, action status, and audit history.
- Read-only Homebrew formula and Debian package inventory, with bounded reports and collection status.
- Explicit empty states and capability availability. No seeded or fabricated device records.

Connection status means a check-in was received within 90 seconds. It is not a security compliance verdict. Inventory and privilege data are agent-reported, not attested. The main device, action and audit views show the latest 100 records. The History view loads older device, job, token and audit records in pages; fleet counters cover the full database. Pending action count includes all queued and running jobs.

## Validation

```sh
python3 -m unittest discover -s tests -v
node --check static/app.js
node --test tests/test_login.cjs
```

Tests exercise concurrent token consumption, expiration, hashed credential storage, cross-device authorization, lease expiry, revocation, malformed inventory, browser-origin rejection, and a real HTTP agent-to-server inventory job round trip.

## Security and operating boundaries

Local credentials and the SQLite database are under `.protec/`, ignored by Git. Newly created files use restrictive POSIX permissions. Device credentials are plaintext in the local agent state file, protected by file permissions; an OS credential store remains planned. The browser uses a bearer credential without cookies and the API rejects cross-origin writes. The server has a fixed static-asset allowlist and a restrictive content security policy.

This prototype uses Python's development HTTP server. It has one administrator identity, no MFA, no production rate limiting, no credential rotation, no device attestation, and no tamper-resistant audit export. The SQLite audit table can be modified by the server's local administrator. A lost enrollment response consumes the token and may leave an orphan device record; revoke that record and enroll again. The local `.protec` directory should be owned by the user running the server, and should never be shared across untrusted users.

See [the delivery roadmap](docs/ROADMAP.md) for the next implementation slices and [architecture](docs/ARCHITECTURE.md) for management and privilege boundaries.

Database snapshots and recovery instructions: [Backup and staged restore](docs/BACKUP_RESTORE.md).

History, readiness checks and conservative retention: [Data operations](docs/DATA_OPERATIONS.md).

Package adapter scope and limits: [Package inventory](docs/PACKAGES.md).
