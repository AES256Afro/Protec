# Delivery roadmap

Target: manage authorized devices through a dashboard with security visibility, configuration deployment, patching, logs, and remote access. Platform order: Linux, Windows, macOS.

| Slice | Result | Acceptance gate | Status |
| --- | --- | --- | --- |
| 1. Local inventory | Enrollment, device credentials, check-ins, dashboard, inventory jobs, revocation | Real HTTP agent round trip and authorization tests | Implemented prototype |
| 2. Remote control plane | Production server, HTTPS, SSO/MFA, operator roles, rate limits, backups, audit export | Remote Linux test host enrolls; role denials and restore verified | Planned |
| 3. Linux service and trust | Guided install/uninstall, systemd service, protected secrets, rotation, signed agent updates and jobs | Survives reboot; revoked/expired jobs rejected; clean uninstall | Planned |
| 4. Security and logs | Disk encryption/firewall/SSH posture, failed services, bounded journal collection, freshness | Compare each result with host state; unknown is never compliant; redact sensitive logs | Planned |
| 5. Configuration policies | Groups, versioned desired state, dry runs, staged rollout, drift detection, rollback where supported | Pilot policy changes host state and reports evidence; failed change recovers | Planned |
| 6. Patches | APT discovery, advisory status, maintenance windows, pilot groups, reboot policy | Disposable Ubuntu VM applies approved updates and reports package versions; interrupted job recovers safely | Planned |
| 7. Remote SSH | Short-lived identity-bound access, host-key verification, session lifecycle audit | Authorized access succeeds; expired, revoked, and wrong-target access fail | Planned |
| 8. Windows | Signed service, credential store, inventory, logs, configurations, updates | Native Windows VM acceptance tests for each capability | Planned |
| 9. macOS | Signed agent, Keychain, launchd, Apple enrollment integration | Native Mac tests and separate Apple MDM enrollment validation | Planned |
| 10. Fleet operations | Alerts, saved groups, reporting, retention, bulk operations, scaling | Restore drill, load tests, staged fleet rollback, and operator usability review | Planned |

Each slice should finish with tests, documentation, repository publication, and explicit verification of any deployed service. Privileged operations must have a tested local execution boundary before rollout to real devices. Scheduling, retry, and rollback guarantees should be described per operation, including operations that cannot be rolled back.
