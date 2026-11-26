#!/bin/bash
# Root performs SteamCMD preparation; the actual game runs without write access
# to either the Workshop cache or its hard-linked local layer.
set -euo pipefail
source /scripts/server-base-variables.sh
if [[ $# -gt 0 ]]; then exec "$@"; fi
[[ "${DNTSNE_LOCAL_MODS:-0}" = 1 ]] || { echo 'Local entrypoint requires DNTSNE_LOCAL_MODS=1'; exit 1; }
[[ -z "${MODFOLDERS:-}" ]] || { echo 'Dedicated B42 does not support -modfolders'; exit 1; }
runtime_uid=10001
runtime_gid=10001
if ! id pz-runtime >/dev/null 2>&1; then
    useradd -u "$runtime_uid" -d /home/pz-runtime -M -s /usr/sbin/nologin pz-runtime
fi
[[ "$(id -u pz-runtime)" = "$runtime_uid" ]] || exit 1
runtime_gid=$(id -g pz-runtime)
mkdir -p /home/pz-runtime "$CACHE_DIR"
chown "$runtime_uid:$runtime_gid" /home/pz-runtime
chmod 0755 /root
cd /scripts/config
python3 main.py
python3 - <<'PY'
import json, os
from pathlib import Path
from dntsne_java_mods import approvals
cache = Path(os.environ['CACHE_DIR'])
active = [x.strip() for x in os.environ['MODS'].split(';') if x.strip()]
policy = cache/'.zombie_buddy'
policy.mkdir(exist_ok=True)
data = approvals(cache/'mods',active)
(policy/'mod_approvals.json').write_text(json.dumps(data),encoding='utf-8')
print('[DNTSNE] Selected Java JAR hash approvals:',len(data['mods']))
PY
# Never chmod/chown recursively through the read-only mod mount or its sources.
find "$CACHE_DIR" -path "$CACHE_DIR/mods" -prune -o -exec chown -h "$runtime_uid:$runtime_gid" {} +
chmod u+rwx "$CACHE_DIR"
python3 - <<'PY'
import os
from pathlib import Path
root = Path('/root/.local/share/Steam/steamapps/workshop')
for parent, dirs, files in os.walk(root, followlinks=False):
    for name in ['.'] + dirs + files:
        p = Path(parent) / name
        if p.is_symlink():
            raise RuntimeError('Workshop symlinks are not permitted')
        s = p.stat()
        if s.st_uid == 10001:
            raise RuntimeError('Game user owns Workshop source')
        p.chmod((s.st_mode & 0o777) & ~0o022 | 0o044 | (0o011 if p.is_dir() else 0))
PY
echo '[DNTSNE] Starting unprivileged game; prepared local mod mount must be read-only'
exec setpriv --reuid="$runtime_uid" --regid="$runtime_gid" --init-groups \
    --inh-caps=-all --ambient-caps=-all --bounding-set=-all \
    env HOME=/home/pz-runtime USER=pz-runtime /scripts/init-server.sh
