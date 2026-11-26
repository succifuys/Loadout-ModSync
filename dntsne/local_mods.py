"""Prepare real B42 directories with shared file inodes, never directory symlinks.

Run only BEFORE the game starts. The layer lives inside the Workshop mount so
link(2) does not cross container mount boundaries. The game mounts it read-only.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

MARKER = '.dntsne-hardlink-owner.json'


def discover(workshop, item_ids):
    workshop = Path(workshop)
    desired = {}
    for item in item_ids:
        if not str(item).isdigit():
            raise ValueError('Invalid Workshop ID')
        root = workshop / 'content/108600' / str(item) / 'mods'
        if not root.is_dir() or root.is_symlink():
            raise ValueError(f'Missing real mod directory: {item}')
        for folder in sorted(root.iterdir()):
            if folder.is_symlink():
                raise ValueError(f'Symlink mod source: {folder.name}')
            if not folder.is_dir():
                continue
            if folder.name in desired:
                raise ValueError(f'Duplicate mod folder: {folder.name}')
            desired[folder.name] = folder
    if not desired:
        raise ValueError('No mod folders found')
    return desired


def prepare(workshop, item_ids, active_mods, layer=None):
    workshop = Path(workshop).absolute()
    layer = Path(layer) if layer else workshop / '.dntsne-local-mods'
    if layer.parent != workshop or layer.is_symlink():
        raise ValueError('Layer must be a real direct child of Workshop root')
    desired = discover(workshop, item_ids)
    found = set()
    for folder in desired.values():
        for info in folder.rglob('mod.info'):
            for line in info.read_text(encoding='utf-8-sig', errors='replace').splitlines():
                if line.startswith('id='):
                    found.add(line[3:].strip())
    missing = set(active_mods) - found
    if missing:
        raise ValueError(f'Active IDs missing: {sorted(missing)}')
    layer.mkdir(exist_ok=True)
    marker = layer / MARKER
    if any(layer.iterdir()) and not marker.is_file():
        raise ValueError('Refusing to replace an unowned layer')
    previous = json.loads(marker.read_text()) if marker.exists() else {'folders': {}}
    if previous.get('format', 1) != 1:
        raise ValueError('Unsupported layer format')
    previous_names = set(previous['folders'])
    if any(not isinstance(n, str) or n in ('', '.', '..') or '/' in n or '\\' in n
           for n in previous_names):
        raise ValueError('Unsafe previous layer folder')
    if any(p.name not in previous_names | {MARKER} for p in layer.iterdir()):
        raise ValueError('Foreign contents in managed layer')
    stage = workshop / ('.dntsne-stage-' + uuid.uuid4().hex)
    stage.mkdir(mode=0o755)
    hashes = {}
    try:
        for name, source in desired.items():
            destination = stage / name
            destination.mkdir()
            for parent, dirs, files in os.walk(source, followlinks=False):
                parent = Path(parent)
                target = destination / parent.relative_to(source)
                for child in dirs:
                    if (parent / child).is_symlink():
                        raise ValueError(f'Symlink inside mod: {name}/{child}')
                    (target / child).mkdir()
                for child in files:
                    original = parent / child
                    if original.is_symlink() or not original.is_file():
                        raise ValueError(f'Non-regular mod file: {original}')
                    before = original.stat()
                    os.link(original, target / child)  # EXDEV fails; never silently copies.
                    sha = hashlib.sha256()
                    with original.open('rb') as handle:
                        for block in iter(lambda: handle.read(1024 * 1024), b''):
                            sha.update(block)
                    after = original.stat()
                    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                        raise ValueError('Workshop file changed during preparation')
                    key = name + '/' + original.relative_to(source).as_posix()
                    hashes[key] = {'size': after.st_size, 'sha256': sha.hexdigest()}
        # Preserve the root inode: Docker may already have this directory mounted.
        for name in previous_names:
            child = layer / name
            if child.parent != layer or child.is_symlink() or not child.is_dir():
                raise ValueError('Invalid previous layer folder')
            shutil.rmtree(child)
        for child in stage.iterdir():
            child.rename(layer / child.name)
        result = dict(format=1, folders={name: source.relative_to(workshop).as_posix()
                                        for name, source in desired.items()},
                      active_mods=list(active_mods), files=hashes)
        temp = layer / (MARKER + '.tmp')
        temp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        temp.replace(marker)
        return result
    finally:
        shutil.rmtree(stage)
