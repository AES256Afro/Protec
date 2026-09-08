# Validation for 0.1

Validated on September 8, 2026:

- Eight Python tests passed on the development Mac with Python 3.14.7, including real HTTP enrollment and agent job completion.
- Resource warnings promoted to errors; database connections explicitly closed.
- JavaScript syntax check passed.
- Browser sign-in, inventory display, narrower-window layout, and inventory refresh queueing verified against a disposable local test server using inventory collected from the development Mac.
- Normal dashboard starts empty. Browser test data lives in a separate temporary database.

GitHub Actions checks the same suite on Ubuntu with Python 3.11 and 3.14. Consult the repository's Checks workflow for the current hosted result.

Not yet validated: a persistent Linux service, a separate remote Linux device, privileged operations, production deployment, native Windows/macOS management, mobile layout, assistive-technology interaction, or load/failure recovery beyond the tested inventory job lease.

## MacBook setup and folder migration follow-up

- Project moved to `/Users/chris/Projects/Protec`; all 65 existing files verified by content hashes, including Git history and local state.
- MacBook enrolled into the local control plane; a real inventory refresh completed and the foreground agent continued check-ins.
- macOS inventory now reports the product name and version. This remains inventory support, not full macOS management.
- Browser reproduction with Unicode masked dots now shows actionable token-copy guidance instead of the fetch header exception.
- Regression coverage added for malformed token rejection before network access and macOS product version reporting.

## M1 enrollment lifecycle

- Eleven Python tests and two JavaScript regression tests passed locally.
- Browser verified administrator login, metadata-only enrollment listing, and transition from active to revoked against a disposable local database.
- API tests verify metadata authentication, revocation authentication, rejected enrollment after revocation, and unchanged credentials for previously enrolled devices.

## Versioned schema migration

- Nineteen Python tests passed, including repeatable legacy upgrade, refused future/incomplete schemas, and transaction rollback after a migration error.
- A copy of the actual local database upgraded to version 1 with device records preserved. A separate pre-upgrade backup was created before restarting the live service.
- The live database integrity/schema check passed after restart.

## M2 history, readiness and retention

- Twenty-five Python tests and two JavaScript tests passed locally. Retention tests preserve active jobs, device credentials and audit history, and refuse deletion if the backup fails. No live retention apply was performed.
- Browser loaded 125 test audit records across pages of 50, 50 and 25, and disabled further paging. Readiness showed schema version and accurate record counts.

## Read-only package inventory

- Thirty Python tests and two JavaScript regression tests passed locally. Collector tests cover malformed output, partial package lifecycle states, output/time limits, truncation, invalid reports, cached scans, and forced refresh.
- The native Homebrew query on the development Mac returned 34 formulae. The browser displayed all 34 records, collection status and time, and a working empty search state.
- Current server and foreground agent restarted with package support. Linux CI exercises its native dpkg collector through the HTTP agent round-trip test. Package mutation, casks, security advisory matching and remote Linux production management remain unimplemented.

## M3 local role credentials

- Thirty-four Python tests and two JavaScript tests passed locally. HTTP tests verify role denials, operator refresh permission, audit attribution, device/service separation, expiry/revocation, invalid input and credential pagination.
- Browser verified viewer restrictions and administrator credential listing/issuance. The issuance dialog cleared its secret after closing. These tests used a disposable control plane.
- A copy of the live schema-1 database upgraded to schema 2 while preserving its device records. A pre-schema-v2 backup was created before local restart.
