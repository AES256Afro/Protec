# Package-presence policy evaluation foundation

The source after the Linux service checkpoint adds `protec.policies`, a read-only evaluation engine. It does not yet expose group assignment, policy storage, a dashboard or enforcement. Those are the next integration slice. This module does not queue jobs or install packages.

A rule contains exactly `kind: package_present`, `manager: dpkg` or `homebrew`, an exact package name, and `max_age_seconds` from 60 to 86400. A policy with a package version constraint is not supported by this contract. Package names are exact identities; `git-lfs` does not satisfy `git`, and architecture-qualified dpkg names need their exact reported identity.

Evaluation returns a status, an explanation, the exact validated rule, evaluation time, package collection time when valid, a digest of the supplied inventory when serializable, and observed versions. The caller must attach policy identity/revision and group assignment and enforce device access before exposing results. This is evidence evaluation, not device attestation or authorization.

- **Compliant:** a fresh, valid report from the requested manager contains the exact package. A reported positive remains evidence even if other package rows were truncated.
- **Noncompliant:** a fresh, complete, untruncated report from the requested manager confirms absence.
- **Unknown:** revoked/unavailable device, missing inventory, invalid check-in or collection time, stale check-in or package evidence, unsupported/failed collection, wrong package manager, malformed report, or absence from a truncated subset.

A recent heartbeat does not make cached package data fresh. Both check-in and collection time must satisfy the rule's evidence limit. Exactly the age limit is allowed; older evidence is unknown. The existing inventory contract's maximum 300-second future clock-skew tolerance is preserved. The package report validator now accepts an optional evaluation clock, so report validation and policy evaluation use the same snapshot time without rewriting evidence timestamps.

Tests cover every status boundary, unsupported managers and malformed rules, timestamp problems, revoked devices, truncation, exact identity matching, observed versions, stable digests and input immutability. Persistence, optimistic revision checks, group membership, permission-filtered result APIs, history, UI and mock workflows remain open; do not mark M5 complete based on this engine alone.
