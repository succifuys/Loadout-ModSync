#!/bin/sh
# Administrator-reviewed deployment only. Does not restart PZ or change its INI.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run with explicit administrator approval'; exit 1; }
[ "${1:-}" = '--approved' ] || { echo 'Review deploy/ and docs/ADMIN.md first; pass --approved'; exit 1; }
src=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dest=/opt/dntsne-modsync
if [ -e "$dest" ]; then
    echo 'Existing installation found. Preserve it and use the documented upgrade procedure.'
    exit 1
fi
install -d -m 0755 "$dest" /var/lib/dntsne-monitor
install -d -o 1000 -g 1000 -m 0750 /var/lib/dntsne-modsync
cp -R "$src/dntsne" "$src/deploy" "$dest/"
cp "$src/pyproject.toml" "$src/requirements-server.lock" "$src/THIRD-PARTY-NOTICES.md" "$dest/"
install -m 0644 "$src/deploy/dntsne-monitor.service" /etc/systemd/system/dntsne-monitor.service
systemctl daemon-reload
systemctl enable --now dntsne-monitor.service
docker compose -f "$dest/deploy/compose.modsync.yaml" up -d --build
echo 'Sync service installed; license gate remains closed by default. PZ was not changed.'

