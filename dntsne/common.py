import hashlib
import json
import os
import re
import stat
import unicodedata
from pathlib import Path


class SyncError(Exception):
    """A user-actionable error; no secret-bearing network URLs in messages."""


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise SyncError('Invalid relative path')
    if unicodedata.normalize('NFC', value) != value:
        raise SyncError('Non-normalized Unicode filename')
    parts = value.split('/')
    for part in parts:
        if part in ('', '.', '..') or part[-1:] in (' ', '.'):
            raise SyncError('Unsafe relative path')
        if any(ord(c) < 32 or c in '\\:<>"|?*' for c in part):
            raise SyncError('Filename is not safe on Windows')
        if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I):
            raise SyncError('Reserved Windows filename')
    return value


def is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def safe_join(root: Path, relative: str) -> Path:
    relative = safe_relative(relative)
    root = root.absolute()
    parts = relative.split('/')
    target = root.joinpath(*parts)
    # Walk existing components once, from the anchor down, without following
    # either symlinks or Windows junctions. If a parent is absent, none of its
    # descendants can exist, so stop at the first missing component.
    mount_point = getattr(stat, 'IO_REPARSE_TAG_MOUNT_POINT', 0xA0000003)
    def check(path, directory):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_reparse_tag', 0) == mount_point:
            raise SyncError('Symlink or junction in destination path')
        if directory and not stat.S_ISDIR(info.st_mode):
            raise SyncError('A parent in the destination path is not a directory')
        return True
    for p in (*reversed(root.parents), root):
        if not check(p,True):
            return target
    current = root
    for i,part in enumerate(parts,1):
        current /= part
        if not check(current,i<len(parts)):
            break
    return target


def digest(path: Path, checkpoint=None) -> str:
    with path.open('rb') as f:
        if checkpoint is None:
            return hashlib.file_digest(f, 'sha256').hexdigest()
        result=hashlib.sha256()
        while True:
            checkpoint()
            chunk=f.read(1024*1024)
            if not chunk:
                return result.hexdigest()
            result.update(chunk)


def fingerprint(path: Path) -> tuple:
    s = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(s.st_mode) or is_link(path):
        raise SyncError('Source must be a regular file')
    return stat_fingerprint(s)


def stat_fingerprint(s):
    # Windows stat uses creation time for ctime, while CRT fstat can report
    # last-write time there. birthtime has the same meaning in both APIs.
    extra=getattr(s,'st_birthtime_ns',0) if os.name=='nt' else s.st_ctime_ns
    return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,extra)


def secure_source_open(root:Path,relative:str):
    """No symlink-following during Linux path traversal; validate fd at caller."""
    path=safe_join(root,relative)
    if os.name=='nt':
        return path.open('rb')
    parts=relative.split('/')
    descriptor=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
            os.close(descriptor)
            descriptor=child
        file=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW,dir_fd=descriptor)
        return os.fdopen(file,'rb')
    finally:
        os.close(descriptor)


def descriptor_fingerprint(file):
    s=os.fstat(file.fileno())
    if not stat.S_ISREG(s.st_mode):
        raise SyncError('Source descriptor is not a regular file')
    return stat_fingerprint(s)


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if is_link(path) or is_link(path.parent):
        raise SyncError('Unsafe state path')
    temp = path.with_name(path.name + '.tmp')
    if is_link(temp):
        raise SyncError('Unsafe temporary state path')
    with temp.open('w', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)

