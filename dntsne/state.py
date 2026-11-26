import json
import logging
import os
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from .common import SyncError, safe_join, is_link


def default_home():
    return Path(os.getenv('LOCALAPPDATA',str(Path.home()/'.local/share')))/'DNTSNE/ModSync'


def setup_log(home):
    home.mkdir(parents=True,exist_ok=True)
    if is_link(home):
        raise SyncError('Unsafe application data directory')
    logger=logging.getLogger('dntsne')
    filename=str((home/'modsync.log').absolute())
    if any(isinstance(h,RotatingFileHandler) and h.baseFilename==filename for h in logger.handlers):
        return
    handler=RotatingFileHandler(home/'modsync.log',maxBytes=1024*1024,backupCount=3,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def read_json(path,default):
    if not path.exists():
        return default
    if is_link(path):
        raise SyncError('Unsafe state file')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,OSError) as e:
        raise SyncError('State file unreadable; keep it for recovery') from e


@contextmanager
def installation_lock(mods:Path):
    # In the shared destination, so two users/state directories share one lock.
    mods.mkdir(parents=True,exist_ok=True)
    path=safe_join(mods,'.dntsne-modsync.lock')
    file=path.open('a+b')
    acquired=False
    try:
        if file.tell()==0:
            file.write(b'0')
            file.flush()
        file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            acquired=True
        except OSError as e:
            raise SyncError('Another client is using this mod directory') from e
        yield
    finally:
        if acquired:
            file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_UN)
        file.close()

