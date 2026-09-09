# Signed package mutation core

The source now contains a constrained local execution core in `protec.package_changes`. Native install, upgrade, removal and crash/replay tests passed in the disposable Ubuntu guest. It is **not registered for remote delivery**, the agent does not advertise it, and the portal has no installation/approval action yet. The normal package workflow remains read-only previews.

An execution attempt requires an artifact-bound version-2 plan, approval metadata binding that exact plan digest and expiry, a protocol-1 signed `apply_packages` envelope for the same device, pinned signing trust, a local endpoint package policy, root privileges and a journal bound to the same device and control-plane origin. Only attempt 1 is valid. The signed approval field describes an attested approver identity; the owner-authenticated server workflow that issues it is still an integration gate. Native tests use a dedicated fixture signing key and fictional administrator identity, not a real user's approval.

The local policy contains version 1, 1 to 100 exact permitted package names, and `allow_remove`. Its loader requires a root-owned mode-0600 regular file inside a root-owned mode-0700 directory, using the existing checked-descriptor protection. Every requested and resolved package must be permitted locally, including dependencies. The future worker must load this policy from the endpoint, never accept it from a network job.

The core verifies signature and target, writes a durable started attempt, checks the local policy, revalidates package state/actions/artifacts under native APT locks, rechecks the job's lease and approval before starting, and commits through python3-apt with unauthenticated acquisition disabled. It preserves local conffiles and suppresses interactive debconf; process-local settings are restored afterward. Post-change native cache observations must match the planned package versions or removals. This uses normal APT/dpkg behavior, including package scripts and configured native hooks. The package allowlist is not a sandbox for those scripts.

A preflight refusal is recorded without starting a package operation. Failure after commit was attempted is uncertain. A process interruption before completion recording leaves a durable started attempt. Reusing that job is refused even when it appears that installation succeeded. The core never assumes that a missing response means no change occurred. It records a completion digest locally; server acknowledgement/recovery is not yet wired for this job kind.

## Native acceptance

Only in the existing marked disposable guest, `scripts/apt_preview_smoke.py --with-changes` adds the mutation checks from `scripts/package_change_smoke.py`. It uses the inert `protec-preview-fixture` package and a local fixture repository, verifies a signed 1.0-to-2.0 upgrade and removal, then installs 1.0 in a child process that deliberately exits after the package changed but before completion was recorded. The parent verifies the actual installed version, retained started record and refusal to execute that attempt again. It also rejects an insecure local policy file. All fixture packages, repository configuration and temporary keys/journals are cleaned up afterward.

The earlier preview checks still verify that simulation alone leaves installed state unchanged. The mutation checks are separate evidence of actual guest changes. No Mac package, BigBox host package, real managed device or private live agent was changed by this acceptance run.

## Gates before enabling remote mutation

The next integration must deliver owner-authorized approval and queueing, a supervised privileged worker with bounded runtime and child-process cleanup, durable completion recovery after worker/agent restart, an explicit unresolved-mutation recovery workflow, and portal/mock views for those outcomes. It must preserve signing and endpoint-policy requirements, deny unsigned delivery, and prevent automatic retries of package side effects. Keep the default capability allowlist closed until that complete path is tested through the actual portal-to-guest transport.
