#!/bin/sh
# Administrator-reviewed deployment only. Does not restart PZ or change its INI.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run with explicit administrator approval'; exit 1; }
[ "${1:-}" = '--approved' ] || { echo 'Review deploy/ and docs/SERVER-SETUP-EN.md first; pass --approved'; exit 1; }
src=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dest=/opt/dntsne-modsync
if [ -e "$dest" ]; then
    echo 'Existing installation found. Preserve it and compare the settings with the new files.'
    exit 1
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo 'Host Python 3.10+ is required for the observer'; exit 1; }
systemctl is-active --quiet docker.service || { echo "Start the local docker.service first"; exit 1; }
docker compose version >/dev/null
# The first install starts local-only with downloads disabled, even if the
# caller has development variables or a .env in the current directory.
DNTSNE_BIND_IP=127.0.0.1
DNTSNE_LICENSES_APPROVED=0
export DNTSNE_BIND_IP DNTSNE_LICENSES_APPROVED
docker compose --env-file /dev/null -f "$src/deploy/compose.modsync.yaml" config --quiet

install -d -m 0755 "$dest" /var/lib/dntsne-monitor
install -d -o 1000 -g 1000 -m 0750 /var/lib/dntsne-modsync
cp -R "$src/dntsne" "$src/deploy" "$dest/"
chmod 0755 "$dest/deploy/pz-entrypoint.sh"
cp "$src/pyproject.toml" "$src/requirements-server.lock" "$src/THIRD-PARTY-NOTICES.md" "$src/.dockerignore" "$dest/"
install -m 0644 "$src/deploy/dntsne-monitor.service" /etc/systemd/system/dntsne-monitor.service
systemctl daemon-reload
systemctl enable --now dntsne-monitor.service
docker compose --env-file /dev/null -f "$dest/deploy/compose.modsync.yaml" up -d --build
echo 'Sync service installed on loopback; downloads are off. PZ was not changed.'
