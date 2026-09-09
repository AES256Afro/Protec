#!/bin/sh
# Install the read-only inventory agent from a trusted local source checkout.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
unset PYTHONPATH PYTHONHOME
base=/opt/protec-agent
state=/var/lib/protec-agent
unit=/etc/systemd/system/protec-agent.service
account=protec-agent
marker='Protec inventory installer v1'
source_identity() {
  python3 - "$1" <<'PY'
import hashlib,re,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(strict=True)
if (root/'protec').is_symlink():raise SystemExit('Source package must not be a symlink')
files=[root/'VERSION',*sorted((root/'protec').glob('*.py'))]
if not (root/'protec'/'agent.py').is_file():raise SystemExit('Missing agent source')
hash=hashlib.sha256()
for path in files:
 if path.is_symlink() or not path.is_file():raise SystemExit('Source must contain regular files only')
 hash.update(str(path.relative_to(root)).encode()+b'\0'+path.read_bytes()+b'\0')
version=(root/'VERSION').read_text().strip()
if not re.fullmatch(r'\d+\.\d+\.\d+',version):raise SystemExit('Invalid VERSION')
print(version+'-'+hash.hexdigest()[:16])
PY
}
usage() { printf '%s\n' 'Usage: linux_agent.sh install [SOURCE] | enroll SERVER_ORIGIN | status | uninstall'; }
[ "${1:-}" != --help ] || { usage; exit 0; }
[ "$(uname -s)" = Linux ] || { echo 'This installer requires Linux with systemd.' >&2; exit 1; }
[ "$(id -u)" = 0 ] || { echo 'Run this installer with sudo on the intended Linux device.' >&2; exit 1; }
[ -d /run/systemd/system ] || { echo 'A running systemd system is required.' >&2; exit 1; }
command -v python3 >/dev/null
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11 or newer is required"'
[ ! -L "$base" ] && [ ! -L "$base/releases" ] && [ ! -L "$base/managed" ] && [ ! -L "$state" ] && [ ! -L "$unit" ] || { echo 'Refusing symlinked installation locations.' >&2; exit 1; }
if [ -e "$base" ]; then
  [ -f "$base/managed" ] && [ "$(cat "$base/managed")" = "$marker" ] || { echo 'Existing installation directory is not managed by this installer.' >&2; exit 1; }
fi
if [ -e "$unit" ]; then
  [ "$(head -n 1 "$unit")" = "# $marker" ] || { echo 'Existing service unit is not managed by this installer.' >&2; exit 1; }
fi
mkdir /run/protec-agent-installer.lock 2>/dev/null || { echo 'Another agent installation operation is running.' >&2; exit 1; }
staging=
cleanup() {
  [ -z "$staging" ] || rm -rf "$staging"
  rmdir /run/protec-agent-installer.lock
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
case "${1:-}" in
  install)
    [ "$#" -le 2 ] || { usage; exit 1; }
    source_dir=${2:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
    release=$(source_identity "$source_dir")
    if ! getent passwd "$account" >/dev/null; then
      useradd --system --user-group --home-dir "$state" --no-create-home --shell /usr/sbin/nologin "$account"
    fi
    python3 - <<'PY'
import pwd
p=pwd.getpwnam('protec-agent')
if p.pw_uid==0 or p.pw_dir!='/var/lib/protec-agent' or p.pw_shell not in ('/usr/sbin/nologin','/sbin/nologin'):
 raise SystemExit('Existing agent account has unexpected identity or login settings')
PY
    install -d -o root -g root -m 0755 "$base" "$base/releases"
    printf '%s\n' "$marker" > "$base/managed"
    chmod 0644 "$base/managed"
    install -d -o "$account" -g "$account" -m 0700 "$state"
    staging=$(mktemp -d "$base/releases/.staging.XXXXXXXX")
    mkdir "$staging/protec"
    install -m 0644 "$source_dir/VERSION" "$staging/VERSION"
    for file in "$source_dir"/protec/*.py; do install -m 0644 "$file" "$staging/protec/"; done
    chmod 0755 "$staging" "$staging/protec"
    [ "$(source_identity "$staging")" = "$release" ] || { echo 'Source changed during staging.' >&2; exit 1; }
    (cd "$staging" && PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 python3 -c 'from protec.agent import inventory; from protec.version import VERSION')
    if [ -e "$base/releases/$release" ]; then
      # Verify existing code before selecting it; never overwrite a release in place.
      diff -r "$staging" "$base/releases/$release" >/dev/null || { echo 'Existing release differs from staged source.' >&2; exit 1; }
      rm -rf "$staging"
    else
      mv "$staging" "$base/releases/$release"
    fi
    staging=
    previous=
    if [ -e "$base/current" ] || [ -L "$base/current" ]; then
      [ -L "$base/current" ] || { echo 'Current installation must be a managed symlink.' >&2; exit 1; }
      previous=$(readlink "$base/current")
      python3 - "$previous" <<'PYVALIDATE'
import re,sys
if not re.fullmatch(r'releases/\d+\.\d+\.\d+-[a-f0-9]{16}',sys.argv[1]):raise SystemExit('Unexpected current release link')
PYVALIDATE
    fi
    # Persist the manager so removal does not require keeping the original checkout.
    if [ "$(readlink -f "$0")" != "$base/manage.sh" ]; then install -m 0755 "$0" "$base/manage.sh"; fi
    [ ! -f "$unit" ] || cp "$unit" "$base/previous-unit"
    cat > "$unit" <<'UNIT'
# Protec inventory installer v1
[Unit]
Description=Protec inventory agent
Wants=network-online.target
After=network-online.target
ConditionPathExists=/var/lib/protec-agent/agent.json

[Service]
Type=simple
User=protec-agent
Group=protec-agent
WorkingDirectory=/opt/protec-agent/current
Environment=PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
ExecStart=/usr/bin/python3 -m protec.agent --state /var/lib/protec-agent/agent.json
Restart=on-failure
RestartSec=15
TimeoutStopSec=15
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/protec-agent
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
CapabilityBoundingSet=
AmbientCapabilities=

[Install]
WantedBy=multi-user.target
UNIT
    chmod 0644 "$unit"
    ln -s "releases/$release" "$base/.current-new"
    mv -Tf "$base/.current-new" "$base/current"
    activated=0
    if systemctl daemon-reload && systemctl enable protec-agent.service >/dev/null; then
      if [ ! -f "$state/agent.json" ]; then activated=1
      elif systemctl restart protec-agent.service && sleep 2 && systemctl is-active --quiet protec-agent.service; then activated=1
      fi
    fi
    if [ "$activated" = 0 ]; then
      systemctl stop protec-agent.service || true
      if [ -n "$previous" ]; then
        ln -s "$previous" "$base/.current-rollback"
        mv -Tf "$base/.current-rollback" "$base/current"
        [ ! -f "$base/previous-unit" ] || cp "$base/previous-unit" "$unit"
        systemctl daemon-reload || true
        systemctl start protec-agent.service || true
      else
        systemctl disable protec-agent.service || true
      fi
      echo 'Agent activation failed; previous code restored when available. Inspect journalctl -u protec-agent.' >&2
      exit 1
    fi
    rm -f "$base/previous-unit"
    printf 'Installed inventory agent %s. Enrollment state is preserved.\n' "$release"
    ;;
  enroll)
    [ "$#" = 2 ] || { usage; exit 1; }
    [ -d "$base/current" ] || { echo 'Install the agent first.' >&2; exit 1; }
    [ ! -e "$state/agent.json" ] && [ ! -L "$state/agent.json" ] || { echo 'Enrollment state already exists; it will not be replaced.' >&2; exit 1; }
    cd "$base/current"
    runuser -u "$account" -- env -i PATH=/usr/bin:/bin HOME="$state" PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 /usr/bin/python3 -m protec.agent --enroll --once --state "$state/agent.json" --server "$2"
    systemctl restart protec-agent.service
    printf '%s\n' 'Enrolled. Check service status and the portal for fresh inventory.'
    ;;
  status)
    [ "$#" = 1 ] || { usage; exit 1; }
    systemctl status protec-agent.service --no-pager
    ;;
  uninstall)
    [ "$#" = 1 ] || { usage; exit 1; }
    [ -f "$base/managed" ] || { echo 'No managed installation found.' >&2; exit 1; }
    systemctl disable --now protec-agent.service
    rm -f "$unit"
    systemctl daemon-reload
    rm -rf "$base"
    printf '%s\n' 'Removed agent service and code. Enrollment, receipts and the non-login account are retained for recovery. Revoke the device in the portal to remove its access.'
    ;;
  *) usage; exit 1;;
esac
