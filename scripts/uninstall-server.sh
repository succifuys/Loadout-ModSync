#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || exit 1
[ "${1:-}" = '--approved' ] || { echo 'Pass --approved after review'; exit 1; }
# Keep sources, observations and all game data for rollback. No volume deletion.
docker compose -f /opt/dntsne-modsync/deploy/compose.modsync.yaml down
systemctl disable --now dntsne-monitor.service
echo 'Sync stopped. Game service and all data retained.'

