# Protec 0.6.0: reliable inventory operations

This release consolidates the tested inventory execution foundations since 0.5. It remains an inventory pilot: package mutation, policy enforcement, SSH sessions, VPN changes and native OS service installation are still planned. Actual publication and live deployment evidence is recorded in WORK_SESSION.md.

## Included

- Cancel queued or running inventory refreshes with stored-device scope checks, lease invalidation and one audit event. An in-flight read may still finish locally.
- Durable private agent receipts and a narrow device-authenticated lookup for reconciling lost completion responses across process restarts.
- Explicit inventory capability negotiation. Missing legacy reports preserve only the existing read-only compatibility path.
- Optional Ed25519 signatures over inventory deliveries, verified against independently provisioned public trust. Existing unsigned inventory agents remain compatible; signature provisioning is manual and completion receipts are not signed.
- One-shot maintenance windows, bounded delivery leases and expiry on the next device poll. The dashboard creates schedules with local-time input and a UTC preview; mock workflows use the same interface.
- Runtime version reporting from the release VERSION file. The Control plane view shows the server version; agents report their actual source release instead of the old fixed 0.1.0 value.
- A repeatable independent Compose install, backup/staged restore and container-restart acceptance check in CI.

## Upgrade and recovery

Schema 6 migrates existing 0.4/schema-4 and 0.5/schema-5 databases forward. Historical job fields remain intact and earlier jobs have null maintenance-window bounds. Back up the database and preserve separate bootstrap/agent credentials before upgrade. Validate a copy first; never test migration against production by starting unreleased code there.

An older control plane cannot open schema 6. Rollback requires the previous image and a separately restored pre-upgrade database, with the new instance stopped. Do not allow divergent copies to accept fleet writes.

Docker Compose is the independent installation path. BoxPilot remains optional and must receive a catalog release referencing the published image before managed update is offered. Publishing a catalog entry does not update the running BoxPilot service. Keep public demo revision and dashboard bytes matched to the actual private image throughout rollout.

For an agent update, preserve its enrollment state file and receipt directory. Signing additionally requires the documented trust file and optional signing dependency. Foreground agents still need to be kept running; native install, reboot persistence and protected OS credential stores remain separate work.

## Verification limits

Unit/HTTP tests and disposable Compose verification cover delivery, receipts, scope, windows, cancellation, backup/restore and container restart. Native browser mock checks cover desktop/narrow scheduling and form submission. Actual managed deployment, live trust provisioning, native service reboot/update, real mobile browsers and future privileged-operation recovery remain separate gates. The release does not complete the entire M4 milestone or the platform roadmap.
