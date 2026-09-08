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
| M3 | Identity and secrets: SSO/MFA, admin/operator/viewer roles, scoped service tokens, expiry, rotation, device identity, protected secret storage | M1, M2 | Local role-scoped credentials, expiry, revocation and metadata paging delivered. Device scopes for viewer/operator inventory and refresh are delivered in 0.3. SSO/MFA, rotation recovery and protected storage remain. Role/target denials and recovery must be tested. |
| M4 | Reliable execution: typed versioned jobs, signatures, capabilities, leases, bounded retries, cancellation, local receipts, approvals, maintenance windows | M2, M3 | Duplicate delivery, restart, stale signature and wrong-device tests; side effects are never blindly retried. |
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

## Initial implementation priorities

The user removed the time limit on September 8, 2026. Continue until the roadmap is implemented and its acceptance gates are verified, or concrete external dependencies prevent further independent work. The original four-hour ordering below is a sequence of priorities, not a deadline or a claim that the complete production platform fits into four hours.

1. **First hour:** publish the expanded plan, complete M1 enrollment lifecycle and begin M2 migrations/backup validation.
2. **Second hour:** package inventory adapters and evidence/freshness reporting. Prioritize read-only inventory; execution depends on M3/M4.
3. **Third hour:** policy/configuration definitions and preview workflows with explicit unsupported/unknown states. No privileged apply before its dependencies pass.
4. **Fourth hour:** network/WireGuard and SSH capability inventory or validated plan schemas as progress allows, then integration tests, browser verification, documentation and a clean release checkpoint.

If foundational work takes longer, finish and verify it before advancing. Never mark an entire milestone complete because one preparatory slice exists. Update WORK_SESSION.md after each checkpoint.

## Cross-cutting operating rules

- Preserve this MacBook's connectivity. Do not use its routes, DNS, VPN, firewall, SSH settings or installed packages as a destructive test fixture.
- Use disposable Linux environments for package/configuration/network mutation tests. CI proves only the scenarios it executes; full VM reboot and native service tests remain separate.
- Separate the desired configuration, approved plan, dispatched job, applied state and verified evidence in the API and UI.
- Never store private keys in repository files, plaintext audit exports or browser state. Token listings expose metadata only; plaintext is shown only at issuance where necessary.
- Native package managers, OpenSSH and WireGuard own their protocols and execution. Protec supplies authorization, configuration, orchestration and evidence.
- Full cloud/IaaS provisioning, Kubernetes orchestration and hypervisor management are future integrations, not implied capabilities of the current endpoint control plane.
- Finish implemented slices with meaningful tests, docs, commit, publication to main and exact-commit CI verification. State all untested production and native behavior plainly.
