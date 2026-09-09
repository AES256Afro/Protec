# Groups and package-presence policies

The source after 0.6 adds static device groups, immutable group and policy revisions, and read-only package-presence evaluation in the dashboard and API. The Policies view creates and edits groups, assigns a policy to one group, disables a policy through a new revision, and displays explained results. It does not queue jobs or install packages. This is unreleased source; inspect WORK_SESSION.md for actual deployment.

A rule contains exactly `kind: package_present`, `manager: dpkg` or `homebrew`, an exact package name, and `max_age_seconds` from 60 to 86400. A policy with a package version constraint is not supported by this contract. Package names are exact identities; `git-lfs` does not satisfy `git`, and architecture-qualified dpkg names need their exact reported identity.

Evaluation returns a status, an explanation, the exact validated rule, evaluation time, package collection time when valid, a digest of the supplied inventory when serializable, and observed versions. The caller must attach policy identity/revision and group assignment and enforce device access before exposing results. This is evidence evaluation, not device attestation or authorization.

- **Compliant:** a fresh, valid report from the requested manager contains the exact package. A reported positive remains evidence even if other package rows were truncated.
- **Noncompliant:** a fresh, complete, untruncated report from the requested manager confirms absence.
- **Unknown:** revoked/unavailable device, missing inventory, invalid check-in or collection time, stale check-in or package evidence, unsupported/failed collection, wrong package manager, malformed report, or absence from a truncated subset.

A recent heartbeat does not make cached package data fresh. Both check-in and collection time must satisfy the rule's evidence limit. Exactly the age limit is allowed; older evidence is unknown. The existing inventory contract's maximum 300-second future clock-skew tolerance is preserved. The package report validator now accepts an optional evaluation clock, so report validation and policy evaluation use the same snapshot time without rewriting evidence timestamps.

Tests cover every status boundary, unsupported managers and malformed rules, timestamp problems, revoked devices, truncation, exact identity matching, observed versions, stable digests and input immutability. Persistence, optimistic revision checks, permission-filtered APIs and dashboard/mock workflows have integration tests. Tags, dynamic groups, general conflict precedence, revision-history browsing and enforcement remain open; the broader M5 milestone is partial.


## API and storage contract

Schema 7 adds `policy_objects`, storing each group and policy revision immutably with a composite kind/id/revision key. Updates and their audit events commit atomically. A pre-upgrade backup is required to return to schema 6 or an earlier image. The schema migration leaves device, credential, job and audit rows intact.

- `GET /api/groups` requires `groups.read`; `POST /api/groups` requires `groups.write` and exactly `name` and `members`.
- `GET /api/policies` requires `policies.read`; `POST /api/policies` requires `policies.write` and exactly `name`, `group_id`, `enabled` and `rule`.
- For an update, also supply `id` and the current integer `revision`. Stale edits are rejected with HTTP 400 and a reload message. Names contain 1 to 80 printable characters. Each collection supports 100 objects; a group contains at most 100 unique active device IDs. Empty groups are valid. Disabled policies remain visible but are not evaluated.
- `GET /api/compliance?limit=100&cursor=...` requires `policies.read`. Each page evaluates at most 100 pairs using one SQLite snapshot and evaluation time. The response includes results, scope-filtered total, evaluation time and next cursor. Pass the returned cursor unchanged. Pages are live evaluations, so reload from the beginning after membership or policy changes.

All three roles can read within their device scope; only administrators can write. Scoped readers see only permitted members, groups containing permitted members, policies assigned to those groups, and results for those members. Counts are scoped and filtered group listings are marked `scope_limited`. Membership retained after a device is revoked produces an unknown result rather than silently disappearing. Editing such a group requires removing revoked members.

The dashboard exposes `policy_management: 1`; clients hide the Policies view when the server lacks that capability. Group selection includes the latest 100 loaded devices and preserves existing members outside that list. The demo uses fictional groups and policies in tab memory and never sends requests to the control plane. Its page and policy edits are illustrative, not evidence from real devices. Each enabled policy is evaluated independently; no configuration conflict resolution is implied.
