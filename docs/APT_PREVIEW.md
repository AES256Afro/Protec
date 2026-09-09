# Native APT preview foundation

`python3 -m protec.apt_preview --device <enrolled-device-id>` accepts a JSON request on standard input and prints a local read-only preview. It runs on a Debian/Ubuntu target with native APT. It is not yet exposed as a remotely delivered job, dashboard feature or approval. No installation/execution operation exists in this module.

Example request:

```json
{"action":"install","packages":[{"name":"git","version":"1:2.43.0-1ubuntu7.3"}]}
```

Use an exact version available in that device's configured APT metadata; the example is not a recommended or guaranteed available version. Removal uses `{"action":"remove","packages":[{"name":"git"}]}`. The supplied device ID is caller-provided context, not proof of enrollment or authentication.

Requests support 1 to 20 exact package names. Installs require an exact version; removal requires an exactly matched installed package. Native metadata is checked before simulation to prevent unresolved names from falling back to APT pattern matching. Paths, glob patterns, options, duplicate names and APT action suffixes are refused. Broader upgrades, purge, autoremove, pinning and repository changes are outside this initial contract. Unsupported native output, including downgrade summary formats, is refused rather than approximated.

The adapter uses an argument array, fixed native binaries, a clean environment and `--simulate --no-download --no-install-recommends`. Native queries have a 20-second execution limit and 512 KiB output limit, with process-group cleanup on failure. At most 100 package changes are accepted. Parsed installation/removal/configuration steps must agree with the native summary. Exact before/after versions and additional dependency changes are included.

Each plan contains its contract/version, target ID, canonical request, exact changes, creation/expiry times (15 minutes), native APT version, dpkg-status digest, simulation-output digest and canonical plan digest. `validate_plan` rejects target mismatches, expired previews, malformed changes and altered content. A digest provides content binding only; it is neither a signature nor approval. The plan explicitly requires revalidation.

APT simulations disable locking, and unprivileged users may not be able to read all relevant configuration. A status-file comparison before and after detects observed dpkg drift but does not establish a transactionally frozen package/repository state. Future execution must lock, re-resolve and compare the complete plan, bind authenticated approval to its digest and device, verify artifacts and resulting package state, and record interruptions without blindly retrying. See the official [Debian apt-get manual](https://manpages.debian.org/unstable/apt/apt-get.8.en.html) for simulation and package selection behavior.

## Native acceptance

`scripts/apt_preview_smoke.py` is exclusively for the existing marked disposable Ubuntu guest and requires guest root. It creates a local explicitly trusted fixture repository and a two-version inert package with one data file, no scripts and no dependencies. It verifies install, version-change, remove and no-op previews, directly installs version 1 only to prepare those tests, checks that previews did not alter dpkg state, then purges the fixture and removes its repository/configuration/lists. This fixture trust setting is not a production repository recommendation.

Ubuntu 24.04.4 with APT 2.8.3 passed the native fixture checks. The Mac and BigBox host package state were not changed. Remote delivery, protected approval, actual managed execution, restart/interruption recovery, dashboard and matching mock workflow remain the next integration work for M6.
