# Package inventory

The agent collects read-only package inventory on its first check-in, every five minutes, and when an inventory refresh is requested. The Packages action on a device opens its latest report with a name filter, collection time, platform scope, and complete/error/unsupported status. Reports older than 15 minutes are labelled stale when opened. The dialog is a snapshot; reopen it after refreshing the device to see a new report.

Supported adapters:

- macOS with Homebrew at `/opt/homebrew/bin/brew` or `/usr/local/bin/brew`: installed formulae and versions using `brew list --formula --versions`. Casks, App Store applications, installer receipts and unmanaged applications are not included.
- Linux with `/usr/bin/dpkg-query`: Debian package name, version and installed status. Removed packages with residual configuration are excluded. APT repositories, update availability and vulnerability/security advisories are not queried in this slice.
- Other hosts or absent package managers report unsupported. They never report a successful empty inventory just because the collector is unavailable.

The native command uses a fixed argument vector without a shell, a 20-second timeout, and a 512 KiB output limit. Homebrew auto-update and analytics are disabled for that invocation. Native stderr is not uploaded. Each report contains at most 500 package records with an explicit total and truncation indicator; the server validates fields and bounds the full request to 256 KiB. Package data is still self-reported by the agent, not independently attested.

Local diagnostic command:

```sh
python3 -m protec.packages
```

It prints collection status and counts, not the package list. No package is installed, updated, removed or pinned. Those operations require the later role/identity, signed-job, package-source and rollout controls in the roadmap.

Sources: [Homebrew command reference](https://docs.brew.sh/Manpage), [Debian dpkg-query manual](https://manpages.debian.org/bookworm/dpkg/dpkg-query.1.en.html).
