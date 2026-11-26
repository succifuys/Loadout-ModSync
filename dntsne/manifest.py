import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from .common import SyncError, safe_relative


def revision_for(data: dict) -> str:
    content = {k: v for k, v in data.items() if k not in ('revision', 'created_at')}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class File:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Manifest:
    revision: str
    run_id: str
    pz_version: str
    created_at: str
    folders: tuple[str, ...]
    files: tuple[File, ...]
    active_mods: tuple[str, ...]
    maps: tuple[str, ...]

    @property
    def total_size(self):
        return sum(f.size for f in self.files)

    def to_dict(self):
        return dict(protocol_version=1, revision=self.revision, run_id=self.run_id,
                    pz_version=self.pz_version, created_at=self.created_at,
                    folders=list(self.folders), files=[vars(f) for f in self.files],
                    active_mods=list(self.active_mods), maps=list(self.maps), total_size=self.total_size)

    @classmethod
    def parse(cls, data):
        try:
            allowed = {'protocol_version','revision','run_id','pz_version','created_at','folders','files','active_mods','maps','total_size'}
            if set(data) != allowed or data['protocol_version'] != 1:
                raise SyncError('Unsupported manifest schema')
            for key in ('revision','run_id'):
                if not re.fullmatch('[a-f0-9]{64}', data[key]):
                    raise SyncError('Invalid revision or run identity')
            if not re.fullmatch(r'42\.\d+\.\d+', data['pz_version']):
                raise SyncError('Unsupported PZ version')
            date = datetime.fromisoformat(data['created_at'])
            if date.tzinfo is None or date > datetime.now(timezone.utc):
                raise SyncError('Invalid manifest timestamp')
            folders = tuple(data['folders'])
            if not folders or len(folders) > 10000:
                raise SyncError('Invalid mod folder count')
            seen = set()
            for folder in folders:
                safe_relative(folder)
                if '/' in folder or folder.casefold() in seen:
                    raise SyncError('Duplicate or nested mod folder')
                seen.add(folder.casefold())
            entries = []
            folder_set=set(folders)
            seen = set()
            directories = set()
            if len(data['files']) > 1000000:
                raise SyncError('Manifest too large')
            for item in data['files']:
                if set(item) != {'path','size','sha256'}:
                    raise SyncError('Invalid file entry')
                path = safe_relative(item['path'])
                if '/' not in path or path.split('/')[0] not in folder_set:
                    raise SyncError('File outside mod folders')
                folded = path.casefold()
                if folded in seen:
                    raise SyncError('Case-insensitive file collision')
                seen.add(folded)
                components = path.split('/')
                directories.update('/'.join(components[:i]).casefold() for i in range(1,len(components)))
                if type(item['size']) is not int or not 0 <= item['size'] <= 2**40:
                    raise SyncError('Invalid file size')
                if not re.fullmatch('[a-f0-9]{64}', item['sha256']):
                    raise SyncError('Invalid file checksum')
                entries.append(File(**item))
            if seen & directories:
                raise SyncError('File/directory collision')
            # Directory spelling must also be unique under Windows case folding.
            spelling = {}
            for file in entries:
                parts = file.path.split('/')
                for i in range(1,len(parts)):
                    prefix = '/'.join(parts[:i])
                    old = spelling.setdefault(prefix.casefold(), prefix)
                    if old != prefix:
                        raise SyncError('Directory case collision')
            for key in ('active_mods','maps'):
                if not isinstance(data[key],list) or any(not isinstance(x,str) or not x or len(x)>256 or any(ord(c)<32 for c in x) for x in data[key]):
                    raise SyncError('Invalid compatibility metadata')
            obj = cls(data['revision'],data['run_id'],data['pz_version'],data['created_at'],folders,tuple(entries),tuple(data['active_mods']),tuple(data['maps']))
            if obj.total_size != data['total_size'] or revision_for(data) != obj.revision:
                raise SyncError('Manifest content checksum mismatch')
            return obj
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise SyncError('Malformed manifest') from e
