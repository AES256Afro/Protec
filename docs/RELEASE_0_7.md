# Protec 0.7.0: groups, package-presence policies and APT previews

This release consolidates the tested work since 0.6. It remains an inventory pilot: it evaluates and previews, and it does not change packages on managed devices. Policy enforcement, remote package changes, system logs, configuration deployment and remote sessions are still planned. Actual publication and live deployment evidence is recorded in WORK_SESSION.md.

## Included

- Static device groups and package-presence policies with immutable revisions, stale-edit protection and scoped, explained compliance results (compliant, noncompliant or unknown). Missing, stale or truncated evidence is unknown, never compliant. See [groups and policies](POLICY_EVALUATION.md).
- Read-only native APT change previews for exact install and removal requests, delivered as a typed `preview_packages` job with dashboard and mock workflows. Plans are version 2, binding exact before/after versions and repository artifact checksums and sizes. See [APT previews](APT_PREVIEW.md).
- A root-only locked revalidation prerequisite that re-resolves a plan under native APT locks and refuses any change in actions, versions or artifacts.
- A signed local package-change core, a protected local worker and an uninstalled systemd template, with durable results that block further changes after an unresolved attempt. **These are not registered for remote delivery, the agent does not advertise them, and the portal has no install or approval action.** See [signed package mutation core](PACKAGE_CHANGES.md).
- A persistent Linux inventory service installer running the read-only agent under a dedicated unprivileged account, with receipt-schema checks around updates and failed activation. See [Linux inventory service](LINUX_AGENT.md).

## Upgrade and recovery

Schema 7 adds immutable group and policy storage; schema 8 adds job payload and preview result fields. Both migrate existing schema-6 databases forward, preserving device, credential, job and audit rows. Back up the database and preserve separate bootstrap/agent credentials before upgrade. Validate a copy first; never test migration against production by starting unreleased code there.

An older control plane cannot open schema 7 or 8. Rollback requires the previous image and a separately restored pre-upgrade database, with the new instance stopped. Do not allow divergent copies to accept fleet writes.

Agents move their local receipt journal to schema 3, through schema 2. Older agent code may refuse a migrated journal. Before a cross-schema agent update, keep a stopped, consistent copy of the enrollment state and receipt journal. Agents that do not negotiate the new capability keep receiving read-only inventory jobs; earlier version-1 preview plans remain readable as history but cannot pass locked revalidation.

Docker Compose is the independent installation path. BoxPilot remains optional and must receive a catalog release referencing the published image before managed update is offered. Publishing a catalog entry does not update the running BoxPilot service. Keep public demo revision and dashboard bytes matched to the actual private image throughout rollout.

## Verification limits

Unit/HTTP tests cover groups and policies, preview delivery and receipts, device scope, the schema 6-to-7 and 7-to-8 upgrades (including a failed schema-8 upgrade rolling back) and the agent journal upgrade. CI repeats the disposable Compose install, backup/staged restore and container-restart acceptance. A marked disposable Ubuntu 24.04 guest with APT 2.8.3 passed native previews, lock competition, artifact-change denial, and the local signed install, upgrade, removal, crash/replay and worker-service checks using an inert fixture package, a dedicated test signer and fictional approval identities. No Mac or BigBox host package and no real managed device was changed.

Owner-authenticated approval, remote package-change submission, server result transport and inspected resolution of uncertain changes remain gates before package changes can be offered. Tags, dynamic groups and conflict precedence remain open. The release does not complete the M5 or M6 milestones or the platform roadmap.
