# Protec infrastructure platform roadmap

This roadmap tracks the current 0.x implementation slices. The multi-year destination, covering native Apple and Windows MDM, deep Linux management and everything else a Jamf or Intune replacement needs, is the [Platform Program plan](PLATFORM_ROADMAP.md); its Appendix A maps every milestone below into that program.

Protec will manage the lifecycle of authorized endpoints and servers: enrollment, identity, packages, desired configuration, updates, network access, remote administration, and operational evidence. Linux is the first complete management target, followed by Windows and macOS. A MacBook is the available local development/test host, so local inventory and dashboard workflows must work there throughout development.

## Delivery milestones

Each milestone owns one capability. Shared execution, identity, audit, scheduling, and secrets services must be reused rather than rebuilt for each feature.

| ID | Milestone and deliverable | Dependencies | Acceptance evidence |
| --- | --- | --- | --- |
| M0 | Local control plane, Mac/Linux inventory, single-use enrollment, refresh jobs, revocation, dashboard | None | Authenticated agent round trip, clean migration, local browser verification and Linux CI. Delivered. |
| M1 | Enrollment lifecycle: list token metadata, expiry/use/revocation status, revoke unused tokens, enrollment audit | M0 | Used, expired, revoked and unknown tokens cannot enroll; credentials never appear in lists or audit. Delivered. |
| M2 | Durable platform data: schema migrations, database backup/restore, health checks, pagination, retention | M0 | Upgrade from existing database, restore drill, full-history counts, controlled retention. Implemented and locally tested; production resilience remains M15. |
| M3 | Identity and secrets: SSO/MFA, admin/operator/viewer roles, scoped service tokens, expiry, rotation, device identity, protected secret storage | M1, M2 | Local role-scoped credentials, expiry, revocation and metadata paging delivered. Device scopes for viewer/operator inventory and refresh are delivered in 0.3. Recoverable service-token rotation is implemented for 0.4 with a bounded handover and atomic cancel/finish. Deployment verification is tracked in WORK_SESSION.md. SSO/MFA and protected storage remain. Role/target denials and recovery must be tested. |
| M4 | Reliable execution: typed versioned jobs, signatures, capabilities, leases, bounded retries, cancellation, local receipts, approvals, maintenance windows | M2, M3 | Versioned read-only inventory delivery, attempt-specific leases, bounded redelivery and server completion receipts implemented for 0.5; rollout tracked in WORK_SESSION.md. Cancellation, local receipts, capability admission and opt-in Ed25519 inventory signatures with operator-pinned trust are consolidated for 0.6; actual release and rollout evidence is in WORK_SESSION.md. One-shot inventory maintenance windows and a guarded scheduling dialog are implemented in schema 6 for 0.6. Live signing/trust and window rollout, recurring calendar policies, privileged-job recovery and approvals remain. Duplicate delivery, restart, stale signature and wrong-device tests; side effects are never blindly retried. |
| M5 | Groups and policies: tags, static/dynamic groups, versioned policy definitions, assignments, conflict precedence, compliance evaluation | M2, M3 | Deterministic assignment/precedence; missing or stale evidence reports unknown; policy version included with each result. |
| M6 | Package management: installed inventory, repository/catalog sources, package versions, install/update/remove/pin plans, OS adapters | M4, M5 | Inventory matches host; preview shows exact package changes; install/remove exercised on disposable Linux target. Read-only dpkg and Homebrew formula inventory delivered. APT execution first, DNF next, Homebrew and winget execution later. |
| M7 | Configuration management: typed templates, schema validation, diff/preview, staged assignment, drift repair, supported rollback | M4, M5 | Preview and applied bytes agree, file permissions preserved, invalid settings refused, failed change recovers on disposable host. |
| M8 | Patching: security advisories, update rings, package/OS updates, reboot requirements, deferrals, maintenance windows | M6, M7 | Pilot rollout verifies installed versions and reboot state; interrupted update has a documented recovery path. |
| M9 | Security, services and logs: encryption/firewall/SSH posture, service health, bounded log queries, redaction, alerts | M4, M5 | Compare with native host checks; unavailable permission is explicit; sensitive log fields redacted; retention enforced. |
| M10 | Network inventory and configuration: interfaces, addresses, routes, DNS, reachability, firewall rules and change plans | M4, M7 | Routes/DNS/firewall previewed, connectivity watchdog tested, automatic recovery exercised before live rollout. |
| M11 | VPN/WireGuard: profiles, peer inventory, endpoint/AllowedIPs validation, split/full tunnel plans, handshake age, peer expiry, key rotation | M3, M10 | Keys generated/stored at endpoints where practical; private keys never in listings; overlapping routes rejected; tunnel and rollback tested in isolated network. |
| M12 | SSH control: host-key trust, users/principals, short-lived certificates, role-bound access grants, session lifecycle audit, revocation | M3, M4, M10 | Wrong host, expired certificate and revoked identity denied; session end/revocation limitations documented and enforced by gateway where required. |
| M13 | Remote operations: constrained runbooks, file transfer, service control, remote support/session transport adapters | M4, M9, M12 | Least-privilege allowlist, artifact integrity, size limits, operator identity and complete execution receipts. |
| M14 | Agent lifecycle and native platforms: signed install/update, systemd/launchd/Windows service, Keychain/Windows protected storage, native MDM integrations | M3, M4 | Install, reboot persistence, upgrade, credential recovery and uninstall on each actual OS; Apple MDM separately verified. |
| M15 | Fleet operations and resilience: API/CLI, notifications/webhooks, dashboards, reports, audit export, scaling and recovery | M2 through M14 incrementally | Backup restore, migration rollback, rate limiting, load tests, operator review and staged production deployment. |

## Current work window and next priorities

The latest September 9 request authorizes five hours from **2026-09-09 12:22:49 UTC through 17:22:49 UTC (12:22:49 p.m. America/Chicago)**. This supersedes the earlier unlimited continuation and previous deadlines for this scheduled run. Work in bounded verified slices, then safely finish in-flight verification, report actual results and pause at the deadline. Elapsed time does not establish roadmap completion. Keep source, CI, native verification and deployed state distinct.

Following the September 9 plan review, prioritize a usable Linux management pilot:

1. **Consolidate and release the tested foundations.** Verify migration/recovery, independent Docker Compose installation and the optional BoxPilot catalog path. Complete managed deployment and exact-revision public demo parity. Protec 0.6.0 and BoxPilot 1.116.4 are published; inspect their pending managed rollout before further release work; never move published tags or confuse an image publication with a live update.
2. **Establish a disposable Linux target and persistent agent.** Implement and verify protected enrollment/state, systemd installation, service restart, update and uninstall. Actual reboot evidence is a separate gate; a container smoke test does not satisfy it. Continue this independent work while a managed rollout needs owner authentication.
3. **Add narrow groups and policies.** Start with tags, static groups, versioned assignments and package-presence rules. Explain which policy version produced each result and report stale or missing evidence as unknown.
4. **Deliver one complete APT package workflow.** Preview exact changes, bind approval to the device and immutable plan, execute on a disposable Ubuntu/Debian target and verify installed state. Prove interruption recovery without blindly retrying side effects. Build approvals with this workflow, rather than a standalone approval queue for read-only inventory. Different service tokens alone do not prove different human approvers.
5. **Extend through configurations and bounded logs to network control.** Reuse the execution foundations. Test connectivity recovery before enabling network, VPN/WireGuard or SSH changes on a live target.

Finish and verify bounded slices before advancing. Release consolidation and the Linux installation checkpoint are the immediate targets; later items remain ordered backlog. Record actual results and remaining native/deployment gates in WORK_SESSION.md.

## Cross-cutting operating rules

- Preserve this MacBook's connectivity. Do not use its routes, DNS, VPN, firewall, SSH settings or installed packages as a destructive test fixture.
- Use disposable Linux environments for package/configuration/network mutation tests. CI proves only the scenarios it executes; full VM reboot and native service tests remain separate.
- Separate the desired configuration, approved plan, dispatched job, applied state and verified evidence in the API and UI.
- Never store private keys in repository files, plaintext audit exports or browser state. Token listings expose metadata only; plaintext is shown only at issuance where necessary.
- Native package managers, OpenSSH and WireGuard own their protocols and execution. Protec supplies authorization, configuration, orchestration and evidence.
- Full cloud/IaaS provisioning, Kubernetes orchestration and hypervisor management are future integrations, not implied capabilities of the current endpoint control plane.
- Finish implemented slices with meaningful tests, docs, commit, publication to main and exact-commit CI verification. State all untested production and native behavior plainly.
