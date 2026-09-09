#!/bin/sh
# Isolated acceptance test: unique project/volume, no published ports or external network.
set -eu
cd "$(dirname "$0")/.."
image=${PROTEC_TEST_IMAGE:-protec-compose-check:local}
project="protec-check-$(date +%s)-$$"
test_directory=$(mktemp -d)
cleanup() {
  docker compose -p "$project" -f compose.yaml -f "$test_directory/override.yaml" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$test_directory"
}
trap cleanup EXIT HUP INT TERM
# PROTEC_TEST_IMAGE is an operator-supplied local test image, not an API input.
case "$image" in *[!a-zA-Z0-9_./:@-]*|'') echo 'Invalid test image reference' >&2; exit 1;; esac
cat > "$test_directory/override.yaml" <<EOF
services:
  protec:
    image: $image
    ports: !reset []
    network_mode: none
    environment:
      PROTEC_PUBLIC_URL: http://127.0.0.1:8765
EOF
compose() { docker compose -p "$project" -f compose.yaml -f "$test_directory/override.yaml" "$@"; }
if [ -z "${PROTEC_TEST_IMAGE:-}" ]; then
  test_revision=${PROTEC_TEST_REVISION:-$(git rev-parse HEAD)}
  compose build --build-arg "PROTEC_REVISION=$test_revision"
fi
compose up -d --no-build --wait --wait-timeout 120
container=$(compose ps -q protec)
test "$(docker inspect --format '{{.HostConfig.NetworkMode}}' "$container")" = none
test "$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "$container")" = true
test "$(docker inspect --format '{{len .HostConfig.PortBindings}}' "$container")" = 0
compose exec -T protec python - seed < scripts/container_smoke.py
compose restart protec
compose up -d --no-build --wait --wait-timeout 120
compose exec -T protec python - verify < scripts/container_smoke.py
printf '%s\n' 'PASS: isolated independent Compose acceptance check'
