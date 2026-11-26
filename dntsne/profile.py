"""One-time migration of game preferences into the dedicated mod profile."""
import shutil
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from .common import SyncError, atomic_json, safe_join

PREFERENCES=('options.ini','Lua/keysB42.ini','Lua/layout.ini','Lua/ModOptions.ini',
    'Lua/screenresolution.ini','viewpoint.properties','viewpoint-live.properties',
    'viewpoint-framecap.properties')
FAVORITES=('db/ServerListSteam.db','db/ServerList.db')


def import_preferences(target,source=None,force=False):
    target=Path(target).absolute()
    source=Path(source or Path.home()/'Zomboid').absolute()
    marker=safe_join(target,'.dntsne-preferences-import.json')
    if marker.exists() and not force:
        return []
    if target==source or not source.is_dir():
        return []
    target.mkdir(parents=True,exist_ok=True)
    backup='.dntsne-preferences-backups/'+uuid.uuid4().hex
    copied=[]
    for relative in (*PREFERENCES,*FAVORITES):
        original=safe_join(source,relative)
        if not original.is_file():
            continue
        destination=safe_join(target,relative)
        staged=safe_join(target,'.dntsne-preferences-tmp/'+backup.split('/')[-1]+'/'+relative)
        staged.parent.mkdir(parents=True,exist_ok=True)
        if relative in FAVORITES:
            # SQLite backup includes committed changes from WAL/journal safely.
            deadline=time.monotonic()+5
            def progress(*args):
                if time.monotonic()>deadline:
                    raise SyncError('Saved server database is busy; close the game and retry')
            with closing(sqlite3.connect(original.as_uri()+'?mode=ro',uri=True,timeout=2)) as src:
                with closing(sqlite3.connect(staged)) as dst:
                    src.backup(dst,pages=64,progress=progress,sleep=.05)
        else:
            shutil.copyfile(original,staged)
        if destination.exists():
            previous=safe_join(target,backup+'/'+relative)
            previous.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(destination,previous)
        destination.parent.mkdir(parents=True,exist_ok=True)
        staged.replace(destination)
        copied.append(relative)
    if copied:
        atomic_json(marker,dict(source=str(source),files=copied,backup=backup))
    return copied
