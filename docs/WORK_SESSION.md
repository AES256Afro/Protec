# Platform build until complete

- Authorization: continue until the requested platform roadmap is complete. User removed the time cutoff on 2026-09-08 at 16:43 UTC.
- Project: `/Users/chris/Projects/Protec`; remote: `AES256Afro/Protec`; branch: `main`.
- Continuation automation: `protec-four-hour-platform-build`, every 10 minutes without a time cutoff. Do not duplicate it.
- Local device: MacBook, already enrolled. Existing foreground control plane listens on 127.0.0.1:8765 and agent uses `.protec/agent.json`.
- Source of milestone scope/dependencies: `docs/ROADMAP.md`.
- Baseline: `9e3019a`, 9 Python tests and 2 JavaScript tests passed, hosted Linux CI passed.

The earlier four-hour schedules are superseded. Continue independent work until milestone acceptance criteria are satisfied. If actual hardware, credentials, or a deployment decision is required, complete independent slices before asking a concrete question.

## Current work

- M0/M1: local inventory, enrollment lifecycle and MacBook onboarding delivered.
- M2: backup/staged restore, transactional migrations, paginated history, readiness and conservative retention delivered. Audit retention is intentionally preserved; production resilience remains M15.
- M6 preparation: read-only Homebrew formula and installed Debian package inventory delivered at d29ccac with hosted CI passing. Last local package report contained 34 formulae. Package mutation awaits M3/M4.
- M3 first slice: local service credentials with viewer/operator/administrator roles, 1-720 hour expiry, revocation, metadata pagination and actor attribution implemented. UI hides actions outside the role; server independently rejects unauthorized routes. Bootstrap token remains intact. SSO/MFA, device-specific scopes, rotation recovery and protected secret stores remain.

## Latest verification

- 34 Python tests plus 2 JavaScript tests passed locally. Tests exercise role escalation denials, device/service identity separation, expiry/revocation, safe metadata and pagination.
- Browser verified viewer restrictions, administrator Access view, test credential issuance and clearing its one-time secret on close. Credential tests used a disposable database, not the live workspace.
- Pre-schema-v2.db backup created. Copy of the live schema-1 database upgraded to schema 2 with device records intact and no issued service credentials. Live control plane restarted on schema 2; bootstrap administrator and device check-ins verified. No live service credentials issued. Verify latest exact-commit CI at the next checkpoint.
- Current foreground control plane and agent use .protec; inspect process ids before restarting. The agent reports packages every five minutes or upon an inventory refresh.

## Next work

1. Live schema-2 verification completed; publish this checkpoint and verify hosted CI.
2. Continue M3: device-specific authorization scopes and recoverable credential rotation. Keep role/target checks centralized; avoid parallel implementations per feature.
3. Continue M4 typed, signed, bounded execution. M5 policy/configuration previews and read-only network/SSH/WireGuard inventory can proceed while external identity/native dependencies remain.

There is no deadline. Continue all meaningful independent milestones. Only pause for completion, user cancellation, or a concrete external dependency after independent work is exhausted. Do not mark the full M3 or platform complete based on this local credential foundation.

## Hosting milestone in progress, September 8

User explicitly authorized deployment on BigBox, an independent deployment path, an optional BoxPilot catalog entry, and a public website/demo on foragefournuts.com. The demo must track shipped milestones with mock data and matching screens. These requirements take priority over the older next-work list.

Implemented: Gunicorn WSGI adapter with shared route authorization, explicit HTTPS origin checking, readiness endpoint, non-root persistent container and Compose setup, catalog manifest in the BoxPilot checkout, and static public demo exported from the real dashboard. Tests currently pass locally: 40 Python, 4 JavaScript, BoxPilot full check with 1,628 tests. Publication and host verification are tracked below when complete.

BigBox Docker access works through the bigbox SSH account. Adding a Tailscale Serve mapping requires sudo; unattended sudo is unavailable. The existing antifascist.work tab is a fictional BoxPilot demo, not an authenticated live session. Do not use it as evidence of host access. The private live BoxPilot portal requires application login.

## Published hosting checkpoint

- Protec v0.2.0: source/image revision `07261023f45d956466074538f866e661964b374b`. Main and tag pushed. Checks 34258018439/34258022414 and image workflow 34258021933 succeeded. Public GHCR image supports linux/amd64 and linux/arm64; anonymous manifest access verified. Manifest digest `sha256:ee66f8ccc3a137eac5ab4b22907c5e0acec9497e38c04383922c6244ee987c03`.
- BigBox persistent independent Compose container is healthy. Administrator identity and a consistent database snapshot were copied securely from the local prototype. Original local server and Mac agent remain active pending the HTTPS cutover; do not claim that device check-ins have moved. There can be new writes to the local database, so repeat the backup transfer after stopping the local server and agent before cutover. Do not overwrite a remote database if new management writes have occurred there.
- Website and mock demo deployed to foragefournuts.com through Cloudflare, deployment `2211461c-e756-432e-abdd-f9033c761101`. Both public source revision and served dashboard hash match the running BigBox image. `/demo/` returned 200 with network-blocking CSP; `/api/dashboard` returned 404. Public DNS records are present; the Mac OS resolver retained a negative result during checks, while explicit public-DNS resolution verified the domain and BigBox curl resolved it normally. Worker fallback: https://protec-website.chris-c39.workers.dev.
- BoxPilot manifest committed to main as `35b3201e0dc120bea44aa9bf997eb2adc45c62dc`. Full local check: 1,628 tests. Hosted CI 34258085029 and install smoke 34258085112 succeeded. This is a catalog-source publication, not a new BoxPilot release or a verified live catalog install.
- User was asked to run the exact reviewed sudo command to install the staged catalog file and add the private Tailscale HTTPS listener. Check for their reply and inspect actual state before continuing. The running portal is independent of BoxPilot's managed-app inventory; catalog availability does not mean this existing container was installed by BoxPilot.
- Agent HTTPS fallback fixed after the image release: macOS Python without bundled CAs now uses the system CA bundle unless an explicit trust path was configured. 44 Python tests pass, and a certificate-verified HTTPS connection to BigBox succeeded. The control-plane image remains v0.2.0; this client fix does not change its dashboard.
- Existing heartbeat automation updated to require BigBox deployment, optional BoxPilot/independent installation, and public demo parity after shipped milestones. It remains active with no cutoff.

Next: complete the administrator-dependent HTTPS/catalog step, transfer the final local state without losing either side's writes, point the Mac agent to the private BigBox HTTPS origin and verify check-in/refresh, then continue M3/M4. Never call the complete infrastructure roadmap finished based on this hosting milestone.

## Device scope milestone, September 8

Implemented M3 device scopes for viewer/operator credentials: select 1-100 active device IDs at issuance, enforce targets on inventory refresh, filter dashboard counts and job/device history before paging, and deny fleet-level health/administration to scoped credentials. Administrator credentials retain fleet scope. Invalid stored scopes fail authentication. Schema 3 preserves existing schema-2 fleet credentials. The demo credential form and mock validation mirror the shipped form.

Local validation: 49 Python tests, 5 JavaScript tests, exported demo DOM scoped-issuance checks, and a migration of a consistent live database copy preserving bootstrap identity and its device record. The original Mac database and running agent remain on the prior local service until the pending HTTPS cutover. Version 0.3.0 image/site/catalog publication and BigBox upgrade are the next release checks for this checkpoint. Do not treat this as completion of all M3 identity work: SSO/MFA, protected secret storage and recoverable rotation remain.

### Verified 0.3.0 deployment

- Released source/image revision `a28698122c1ee2e1ee50157ad0524f135377911e`. Main and v0.3.0 tag pushed; hosted Checks 34260661963 and 34260664293 succeeded. Image workflow 34260664259 succeeded; multi-platform image digest `sha256:bce40718a7ffa955197d05791fa87e53cd3d70c7db7a6271e2c8f58cad2fa316`.
- Tested the published Gunicorn image in a disposable BigBox container with two fictional devices: scoped target denial, authorized refresh, filtered history/counts, fleet-health denial, and schema 3 passed. The temporary container and its data volume were removed afterward.
- Backed up the persistent portal database inside its volume to `/data/pre-scope-20260908.db` before upgrading. Preserved the previous Compose configuration on the host. Upgraded the independent persistent portal to 0.3.0; healthy and database integrity/schema 3 verified. Logical SHA-256 checks across all original table columns and bootstrap file matched before and after upgrade: 1 device, 1 job, 4 audit events, 1 enrollment, 0 service credentials. No real scoped credentials or additional devices were issued during testing.
- Published the matching public site/demo to foragefournuts.com. Cloudflare deployment `a4bed36c-be75-4bf9-b74b-38cb8c44d790`. Release metadata and actually served dashboard JavaScript match image source `a286981...`; the actual running container's dashboard checksum was compared too. Normal domain resolution now works from the Mac.
- BoxPilot catalog source updated to 0.3.0 on main at `d8bceb31546ae40e28c159dfdcce2ffe09cb5bdb`. Full local check: 1,628 tests. Hosted install smoke 34260723695 passed; verify the corresponding CI run 34260723691 before final publication report. The staged host catalog file was refreshed for the still-pending administrator step.
- The private HTTPS listener and live BoxPilot catalog install remain pending the previously requested sudo command. Do not repeatedly ask the same question. Local Mac server/agent still use the original schema-2 state. Before final cutover, compare both databases for new writes, stop local writers, take a fresh backup, and migrate safely without overwriting new BigBox records. The new BigBox image will migrate schema-2 input to schema 3.

Next independent M3 work: recoverable credential rotation with bounded overlap, explicit invalidation, and audit evidence. SSO/MFA and native protected secret stores remain. Continue typed/signed job foundations afterward. Keep demo and actual deployed release aligned at each shipped checkpoint.

## BoxPilot catalog release, September 8

- Published BoxPilot **v1.116.0** at `dbdef02b7ef5966f5d2ac27c2ea7325dc21a49ea`, including Protec 0.3.0 as catalog application 166. Both main and the tag were verified remotely. Local full check passed with 1,628 tests; hosted CI 34262553702, install smoke 34262553698, and release 34262557260 all succeeded. Release: https://github.com/AES256Afro/BoxPilot/releases/tag/v1.116.0.
- The live private BoxPilot session is now authenticated as owner. It still runs 1.114.0. Refreshed the System release check, opened **Update to v1.116.0**, and filled the version confirmation. The normal approval dialog requires the owner's password, which has not been provided. The browser tab is retained for that handoff. Do not claim the live catalog has updated until the owner completes the update and the host/UI are verified.
- Rechecked the persistent Protec container: healthy, readiness returned ok, image revision still `a28698122c1ee2e1ee50157ad0524f135377911e`. The public release check passed against that exact revision and actual served dashboard bytes. Private Tailscale port 8765 is still absent. The earlier HTTPS setup/cutover dependency remains; the BoxPilot update alone does not publish the independent container's port or migrate the Mac agent.
- Deployment documentation now explicitly makes Docker Compose the default portal installation, BoxPilot optional, and native agents separate. Docs-only Protec commit `d6c1c81` passed hosted Checks 34262709529; it does not require replacing the matching 0.3.0 portal/demo release.
- The existing every-ten-minute continuation automation remains active and already requires private deployment and matching public mock features after shipped milestones. Do not create a duplicate automation or repeatedly stage additional pending update jobs.
