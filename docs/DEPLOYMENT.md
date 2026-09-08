# Deploy Protec

Protec 0.3 is a private fleet inventory pilot. Docker Compose is the default installation method for the control plane and dashboard. It can run independently of BoxPilot, which offers an optional catalog installation of the same container image. SQLite data lives under `/data` in persistent storage and survives container replacement.

Device agents run directly on their Linux or macOS hosts and connect outbound over HTTPS. Endpoint management will use native services and appropriate host permissions as those capabilities ship. Installing the portal container does not grant it administrative access to enrolled devices. The portal does not need root, a Docker socket, or host network access.

## Independent Docker Compose install

Install Docker Engine and Compose on your server, then:

```sh
git clone https://github.com/AES256Afro/Protec.git
cd Protec
cp .env.example .env
# Set PROTEC_PUBLIC_URL to the exact HTTPS origin used by your browsers and agents.
docker compose pull
docker compose up -d --wait
```

For a source build, use `docker compose up -d --build --wait` instead. The supplied Compose file binds only to `127.0.0.1:8765`. Configure an HTTPS reverse proxy on that host, or use a private Tailscale address:

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

1. Choose **Tailnet** access, or prepare an HTTPS reverse proxy on the host.
2. Enter the exact **Portal HTTPS origin**, including the chosen port. Default port: 8765.
3. Keep the generated **Administrator token**. If replacing it, use 32 to 128 letters, digits, underscores, or hyphens.
4. Review the install and wait for its health check.
5. Open the app's sign-in details, copy the generated token, and connect to Protec.

BoxPilot manages the data directory and uses the same published image as independent installs. Its `PROTEC_ADMIN_TOKEN` environment value is authoritative: changing it and restarting the app replaces bootstrap access immediately. In that mode, a pre-existing `/data/admin-token` file is ignored. Named service credentials and device credentials are separate and are not rotated by that setting.

The catalog entry is delivered with BoxPilot releases. Publishing the manifest to GitHub does not update a running BoxPilot installation automatically.

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

This is not yet a complete Intune replacement. Package installation, patching, policy enforcement, SSH sessions, VPN management, SSO/MFA, signed jobs, and native Windows services remain roadmap work. Use a private network for the management pilot. Inventory and privilege reports come from the enrolled device and are not independent compliance attestation.

After publishing, read the running image's `org.opencontainers.image.revision` label and verify the served demo, including its actual JavaScript bytes:

```sh
python3 scripts/check_release.py --revision FULL_DEPLOYED_COMMIT
```

The ongoing Protec build automation also carries this parity requirement. A docs-only or agent-only commit may be newer than the deployed control-plane release; use the running image revision when checking the public demo.
