# Deploy Protec

Protec is a private fleet inventory pilot. Docker Compose is the default installation method for the control plane and dashboard. It can run independently of BoxPilot, which offers an optional catalog installation of the same container image. SQLite data lives under `/data` in persistent storage and survives container replacement.

Device agents run directly on their Linux or macOS hosts and connect outbound over HTTPS. Endpoint management will use native services and appropriate host permissions as those capabilities ship. Installing the portal container does not grant it administrative access to enrolled devices. The portal does not need root, a Docker socket, or host network access.

## Independent Docker Compose install

Install Docker Engine and Compose on your server, then:

```sh
git clone --branch v0.5.0 https://github.com/AES256Afro/Protec.git
cd Protec
cp .env.example .env
# Set PROTEC_PUBLIC_URL to the exact HTTPS origin used by your browsers and agents.
docker compose pull
docker compose up -d --wait
```

The example pins the published 0.5.0 release; use the release tag you intend to deploy. For a source build of that release, use `docker compose up -d --build --wait` instead. Main can contain unreleased changes, so do not build it under a published release image name. The supplied Compose file binds only to `127.0.0.1:8765`. Configure an HTTPS reverse proxy on that host, or use a private Tailscale address:

```sh
sudo tailscale serve --bg --https=8765 http://127.0.0.1:8765
```

Set `PROTEC_PUBLIC_URL` to the HTTPS URL Tailscale reports, including port 8765. Apply an updated environment with `docker compose up -d`. The configured origin is authoritative for browser writes. Forwarded headers do not change it. For a local-only test, leave the default `http://127.0.0.1:8765` and use an SSH tunnel if needed. Keep remote traffic on HTTPS.

Retrieve the generated administrator token privately:

```sh
docker compose exec -T protec cat /data/admin-token
```

Paste the token contents into the portal. It stays in browser memory until reload or lock. Issue named, expiring credentials from **Access** for everyday use. Do not share the bootstrap token or publish it in logs.

The default image runs as UID/GID `10001:10001`. Compose uses a named persistent volume. Bind-mounted data directories must be owned by that identity with mode 0700; database and token files should be 0600. The image runs with a read-only root filesystem, a small temporary filesystem, dropped Linux capabilities, and no privilege escalation in the supplied Compose configuration.

## BoxPilot app catalog

Update BoxPilot to **1.116.0 or later**, which includes `catalog/protec.yaml`, then open **App catalog**, search **Protec**, and select **Install**.

1. Plan a private Tailscale HTTPS address, or prepare an HTTPS reverse proxy on the host.
2. Enter the exact **Portal HTTPS origin**, including the chosen port. Default port: 8765.
3. Keep the generated **Administrator token**. If replacing it, use 32 to 128 letters, digits, underscores, or hyphens.
4. Review the install and wait for its health check.
5. Publish its loopback port through Tailscale Serve using the command above, or point your HTTPS reverse proxy at that port. An existing mapping to the same port can stay in place.
6. Open the app's sign-in details, copy the generated token, and connect to Protec.

BoxPilot manages the data directory and uses the same published image as independent installs. Its `PROTEC_ADMIN_TOKEN` environment value is authoritative: changing it and restarting the app replaces bootstrap access immediately. In that mode, a pre-existing `/data/admin-token` file is ignored. Named service credentials and device credentials are separate and are not rotated by that setting.

The catalog entry is delivered with BoxPilot releases. Publishing the manifest to GitHub does not update a running BoxPilot installation automatically.

### Moving an existing independent installation into BoxPilot

BoxPilot's catalog tracks installations created by its deployer. An independent Compose stack can appear under **Also on this server** while its catalog card says **Not installed**. Installing another copy on the same port causes a conflict; catalog availability alone does not transfer management.

For a migration, take consistent backups and compare the source databases for new writes. Install a managed copy on an unused loopback port, stop its container, and transfer the verified database into its declared `/data` mount with owner `10001:10001` and mode 0600. Stop the independent stack before changing the managed copy to the original port through **Settings**. Verify database integrity, private HTTPS, agent check-in and a completed inventory refresh before retiring the old container. Preserve its volume and Compose file for recovery. Finish with a BoxPilot **Back up** operation.

The managed installation uses the administrator token from BoxPilot's **Sign in** or **Secrets** panel. Device credentials and named service credentials live in the transferred database and remain valid. Future image updates, port/origin settings, backups, and restarts should use the managed app. Do not start the retired independent stack on the same port.

## Enroll a device

From a Protec checkout on Linux or macOS, create a single-use enrollment token in the portal and run:

```sh
python3 -m protec.agent --enroll --server https://protec.example.com
```

Paste the token at the prompt. On macOS, if Python has no default CA certificates, the agent uses `/etc/ssl/cert.pem`. Explicit `SSL_CERT_FILE` or `SSL_CERT_DIR` settings are preserved. Certificate and hostname verification remain mandatory.

The foreground agent stores its own credential in `.protec/agent.json` and sends inventory every 30 seconds. Keep it running for check-ins. This version does not install an OS service or elevate privileges.

## Back up, update, and roll back

Create an online, consistent SQLite backup before updating:

```sh
docker compose exec -T protec python -m protec.database backup --source /data/protec.db --destination /data/pre-upgrade.db
```

Use a new backup filename each time. Copy the backup off the server and preserve the administrator-token file separately in secure storage. For BoxPilot, preserve its generated app secrets through the BoxPilot backup process. See [backup and restore](BACKUP_RESTORE.md) for staging and integrity checks. Never commit state or secrets to the repository.

Pin a released image tag or digest, pull it, and run `docker compose up -d --wait`. Check `/healthz` for readiness and the authenticated **Control plane** page for schema and record counts. Test an agent check-in and an inventory refresh after each update. The running container retains its volume through restart/recreation.

For rollback, stop the new container and restore a checked pre-upgrade database to a separate directory/volume before starting the previous image against that restored data. Do not run an older image against a newer schema or keep two control planes accepting changes to divergent copies.

## Website and demo release parity

The public site is at https://foragefournuts.com and its mock fleet is at `/demo/`. `python3 scripts/build_website.py` exports the dashboard from `static/` unchanged except for asset URLs and a demo banner. The mock transport in `website/demo.js` replaces API requests in memory. It is excluded from the management container. The public site's CSP blocks all network connections from the demo, and the static deployment has no device API or database.

Release metadata at `/release.json` records the source revision, version, and dashboard SHA-256. Build and publish the site from the same commit deployed to BigBox. For each new supported workflow, update the mock transport and its tests in the same change. Keep planned capability labels aligned with actual implementation.

```sh
python3 scripts/build_website.py
npx wrangler deploy --config website/wrangler.jsonc
```

Cloudflare authentication and access to the domain are required for website publication. The authenticated BigBox management portal remains separate from this public mock site.

## Current limits

This is not yet a complete Intune replacement. Package installation, patching, policy enforcement, SSH sessions, VPN management, SSO/MFA and native Windows services remain roadmap work. Use a private network for the management pilot. Inventory and privilege reports come from the enrolled device and are not independent compliance attestation.

After publishing, read the running image's `org.opencontainers.image.revision` label and verify the served demo, including its actual JavaScript bytes:

```sh
python3 scripts/check_release.py --revision FULL_DEPLOYED_COMMIT
```

The ongoing Protec build automation also carries this parity requirement. A docs-only or agent-only commit may be newer than the deployed control-plane release; use the running image revision when checking the public demo.


## Disposable Compose acceptance check

Before publishing a new release, run `sh scripts/check_compose.sh` from a checkout on a Docker/Compose host. The check builds a local image, uses a unique Compose project and fresh named volume, removes all port publications, and disables the container's external network. It exercises the real Gunicorn entrypoint and independent file-token bootstrap path. It does not use the managed fleet or a host directory mount. An existing image can be tested with `PROTEC_TEST_IMAGE=IMAGE_REFERENCE sh scripts/check_compose.sh`.

The check verifies enrollment and authorization denials, versioned receipt replay, scheduled-window admission, cancellation, protected files, online backup and a separately staged restore. It restarts the container and verifies identities, pending windows, receipts and audit records survived. The disposable container and volumes are removed on exit. This is container restart and application recovery evidence, not host reboot or native agent-service verification. Never run the internal `container_smoke.py` helper against an existing installation; it is designed only for the fresh volume created by the wrapper.

Image publication runs only for version tags that match VERSION. Manual dispatch from a newer main branch must not overwrite the published version image.
