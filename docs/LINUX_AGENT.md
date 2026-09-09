# Linux inventory service installation

This installation helper is a source checkpoint after the 0.6.0 release. It is not included in that release tag. Use the checkout containing `scripts/linux_agent.sh`. The helper installs the existing read-only inventory agent as a persistent systemd service on Linux with Python 3.11 or newer. It does not install Python or OS packages.

The agent runs under a dedicated **protec-agent** account with no login shell, Linux capabilities or privilege escalation. Root is required to install the service and its protected files; the running agent reports standard privileges. Privileged package/configuration/network execution remains separate roadmap work.

## Install and enroll

Copy a trusted Protec source checkout to the intended Linux device. Review its source/revision before running its installer with sudo:

```sh
sudo sh scripts/linux_agent.sh install "$PWD"
sudo /opt/protec-agent/manage.sh enroll https://protec.example.com
```

Create an enrollment token in the private portal and paste it into the hidden prompt. The command does not take tokens as command-line arguments. Enrollment creates the device state and performs a check-in, then starts the service. Existing state is never overwritten by the enrollment command.

Installation enables boot startup. Before enrollment, the service's state-file condition keeps it inactive. Verify the resulting device and package inventory in the portal:

```sh
sudo /opt/protec-agent/manage.sh status
sudo journalctl -u protec-agent.service -n 30 --no-pager
```

This service configuration uses the existing unsigned read-only inventory compatibility path. It does not yet provision pinned signature trust, install the optional signing dependency, or provide a service configuration UI. Explicit pinned trust is available for the separately launched foreground agent as described in JOB_SIGNATURES.md. Do not interpret a service install as enabling signed mode or administrative management capabilities.

## Files and updates

- `/opt/protec-agent/releases/VERSION-FINGERPRINT/`: root-owned Python source and VERSION, readable but not writable by the agent. The fingerprint identifies copied bytes; it is not a release signature or proof of publisher identity.
- `/opt/protec-agent/current`: atomically switched link to the selected release. Existing release directories are not overwritten.
- `/opt/protec-agent/manage.sh`: installed management helper.
- `/var/lib/protec-agent/agent.json`: device enrollment, owned by the service account with mode 0600, inside a 0700 state directory.
- `/var/lib/protec-agent/agent.json.receipts/`: protected local receipt journal retained across service restarts and source upgrades.
- `/etc/systemd/system/protec-agent.service`: installer-managed unit. Future installer runs replace it; custom unit configuration is not an exposed interface in this slice.

Update from another trusted source checkout:

```sh
sudo /opt/protec-agent/manage.sh install /path/to/new/Protec
```

The helper validates and fingerprints regular source files, stages a separate release, rechecks the staged fingerprint and imports the agent before activation. A known previous release is restored if service activation fails. A service that stays running can still have an unreachable portal, expired/revoked credentials or a failed package query; verify fresh inventory and a completed refresh in the portal after every update. The short activation check alone does not establish end-to-end health.

The installer serializes operations with a temporary lock under `/run`. An interrupted install may leave an unused staged release or temporary link for an administrator to inspect. Full power-loss recovery during installer mutation, automatic downloads, publisher signature verification, APT packaging, automated rollback after later health degradation and signing/trust provisioning remain open work.

## Uninstall and recovery

```sh
sudo /opt/protec-agent/manage.sh uninstall
```

This disables/stops the service and removes its unit and installed code. It preserves enrollment, receipts and the non-login account to prevent accidental identity loss and support reinstallation. Reinstalling reconnects the same enrolled device. Revoking the device in the portal is the separate action that invalidates its access. Permanent state/account purging is deliberately not part of this helper.

If enrollment created state but the first check-in failed, resolve connectivity/certificate issues and start the service; do not delete state and consume another token by default. Review the portal for the existing enrollment and use normal revocation when retiring an orphan identity.

## Disposable native acceptance

`scripts/linux_agent_smoke.py` is a destructive lab harness, not an endpoint diagnostic. It requires a disposable guest marker at `/opt/protec-lab/disposable-marker`, root and a source copy at `/opt/protec-lab/source`. It creates a fictional loopback control plane and modifies service/user state only in that guest. Run `before`, reboot the actual guest, then run `after`. The after phase rejects an unchanged kernel boot ID.

The scenarios cover non-root execution, real dpkg inventory, protected enrollment/source, receipts, symlinked-source rejection, duplicate enrollment refusal, failed activation rollback, code update/repeated installation, actual reboot persistence and uninstall/reinstall with the same device identity. Synthetic 0.6.98/0.6.99 test versions exist only in the guest. See WORK_SESSION.md for actual results and limitations.

The initial lab uses a Canonical [Ubuntu 24.04 cloud image](https://cloud-images.ubuntu.com/releases/noble/release/) with a verified SHA-256 from the same HTTPS source and a [NoCloud seed](https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html). Software-emulated QEMU avoids changing host KVM permissions. Its disk is isolated; guest-initiated network access is restricted and the SSH test forward binds to host loopback. No Mac or BigBox host agent is installed by this test.
