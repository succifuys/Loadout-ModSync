"""Read B42 Java metadata without installing anything into the Steam game."""
import hashlib
from pathlib import Path
import re


def selected_jars(mods, active, minor=21):
    mods = Path(mods).resolve()
    active = set(active)
    result = []
    for folder in sorted(mods.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        versions = []
        for p in folder.iterdir():
            if p.is_dir() and re.fullmatch(r'42(?:\.\d+)?', p.name):
                version = int(p.name.split('.')[1]) if '.' in p.name else 0
                if version <= minor:
                    versions.append((version, p))
        if not versions:
            continue
        version = max(versions, key=lambda v: v[0])[1]
        props = {}
        for info in (folder/'common/mod.info', version/'mod.info'):
            if info.is_file():
                for line in info.read_text(encoding='utf-8-sig',errors='replace').splitlines():
                    key, sep, value = line.partition('=')
                    if sep:
                        props[key.strip().lower()] = value.strip()
        if props.get('id') not in active or not props.get('javajarfile') or not props.get('javapkgname'):
            continue
        jar = (version/props['javajarfile']).resolve()
        if not jar.is_relative_to(folder.resolve()) or not jar.is_file():
            raise ValueError('Java JAR must exist inside its own mod folder')
        result.append((props['javapkgname'], jar))
    return result


def approvals(mods, active, minor=21):
    from datetime import datetime, timezone
    receipts = []
    for package, jar in selected_jars(mods, active, minor):
        sha = hashlib.sha256()
        with jar.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                sha.update(block)
        receipts.append(dict(id=package,jar_hash=sha.hexdigest(),decision=True,
                             time=datetime.now(timezone.utc).isoformat()))
    return dict(formatVersion=2, mods=receipts)
