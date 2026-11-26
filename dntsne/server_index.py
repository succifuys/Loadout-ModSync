import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from .common import SyncError, digest, fingerprint, safe_join, atomic_json
from .manifest import Manifest, File, revision_for

LOG = logging.getLogger(__name__)


class Index:
    def __init__(self, workshop: Path, observation: Path, licenses_approved=False, persistence=None):
        self.workshop = workshop.absolute()
        self.observation = observation
        self.licenses_approved = licenses_approved
        self.manifest = None
        self.sources = {}
        self.stamps = {}
        self.state = 'offline'
        self.reason = 'No fresh game observation'
        self.tainted_run = None
        self.lock = threading.RLock()
        self.selection = None
        self.entries = {}
        self.persistence=persistence
        self.saved=None
        if persistence and persistence.exists():
            self.saved=json.loads(persistence.read_text())
            self.tainted_run=self.saved.get('tainted_run')
        self.read_slots=threading.BoundedSemaphore(3)

    def evidence(self):
        data = json.loads(self.observation.read_text())
        age = time.time() - data['observed_at']
        if not 0 <= age < 4:
            raise SyncError('Game observation is stale')
        return data

    def invalidate(self, reason, taint=True):
        with self.lock:
            if taint and self.manifest:
                self.tainted_run = self.manifest.run_id
                self.save_taint()
            self.manifest = None
            self.state = 'offline'
            self.reason = reason

    def save_taint(self):
        if self.persistence:
            self.saved=dict(self.saved or {},tainted_run=self.tainted_run)
            atomic_json(self.persistence,self.saved)

    def require(self, revision=None):
        with self.lock:
            try:
                e = self.evidence()
                if e['state'] != 'ready' or not self.manifest or e['run_id'] != self.manifest.run_id:
                    raise SyncError('Current game run is not ready')
                if self.selection != self.selection_key(e):
                    raise SyncError('Prepared configuration changed')
                if revision and revision != self.manifest.revision:
                    raise SyncError('Revision has changed')
                return self.manifest
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise SyncError('Game observation unavailable') from error

    @staticmethod
    def selection_key(e):
        return json.dumps({**{k:e[k] for k in ('folders','active_mods','maps','pz_version')},
                           'prepared_sha256':e.get('prepared_sha256')},sort_keys=True)

    def collect(self, e):
        sources = {}
        found_ids = set()
        folder_roots = []
        for name, relative in sorted(e['folders'].items()):
            base = safe_join(self.workshop,relative)
            if base.name != name or not base.is_dir():
                raise SyncError('Prepared mod source unavailable')
            folder_roots.append(base)
            for path in sorted(base.rglob('*')):
                relative_file = path.relative_to(base).as_posix()
                safe_join(base,relative_file)  # rejects links, even directories
                if path.is_file():
                    key = name+'/'+relative_file
                    sources[key] = path
                    if path.name=='mod.info':
                        for line in path.read_text(encoding='utf-8-sig',errors='replace').splitlines():
                            if line.startswith('id='):
                                found_ids.add(line[3:].strip())
        if set(e['active_mods'])-found_ids:
            raise SyncError('Active mod IDs not found in prepared sources')
        return sources

    def build(self, e):
        self.state = 'indexing'
        self.reason = 'Computing checksums'
        sources = self.collect(e)
        baseline = None
        if e.get('prepared_sha256'):
            marker = safe_join(self.workshop,'.dntsne-local-mods/.dntsne-hardlink-owner.json')
            if digest(marker)!=e['prepared_sha256']:
                raise SyncError('Startup preparation evidence changed')
            baseline = json.loads(marker.read_text())['files']
            if set(baseline)!=set(sources):
                raise SyncError('Prepared tree differs from startup baseline')
        entries, stamps = [], {}
        for key, path in sources.items():
            initial = fingerprint(path)
            sha = digest(path)
            if baseline and baseline[key] != {'size':initial[2],'sha256':sha}:
                raise SyncError('Prepared file differs from game startup baseline')
            if initial != fingerprint(path):
                raise SyncError('Source changed during indexing')
            stamps[key]=initial
            entries.append(File(key, initial[2], sha))
        if set(self.collect(e))!=set(sources) or any(fingerprint(sources[k])!=s for k,s in stamps.items()):
            raise SyncError('Source tree changed during indexing')
        data = dict(protocol_version=1, revision='',run_id=e['run_id'],pz_version=e['pz_version'],
                    created_at=datetime.now(timezone.utc).isoformat(),folders=sorted(e['folders']),
                    files=[vars(f) for f in entries],active_mods=e['active_mods'],maps=e['maps'],total_size=sum(f.size for f in entries))
        data['revision']=revision_for(data)
        manifest = Manifest.parse(data)
        if self.saved and self.saved.get('manifest',{}).get('run_id')==e['run_id']:
            previous=Manifest.parse(self.saved['manifest'])
            if previous.revision!=manifest.revision or self.saved['stamps']!={k:list(v) for k,v in stamps.items()}:
                raise SyncError('Current game run changed while API was offline')
            manifest=previous
        latest = self.evidence()
        if latest['state']!='ready' or latest['run_id']!=e['run_id'] or self.selection_key(latest)!=self.selection_key(e):
            raise SyncError('Game changed while indexing')
        with self.lock:
            if self.persistence:
                self.saved=dict(manifest=manifest.to_dict(),stamps={k:list(v) for k,v in stamps.items()},tainted_run=None)
                atomic_json(self.persistence,self.saved)
            self.sources,self.stamps,self.selection = sources,stamps,self.selection_key(e)
            self.entries={f.path:f for f in manifest.files}
            self.manifest = manifest
            self.state,self.reason = 'ready',''

    def tick(self, scan=False):
        e=None
        try:
            e = self.evidence()
            if e['state'] not in ('offline','starting','updating','ready'):
                raise SyncError('Invalid game observation')
            if e['state']!='ready':
                self.invalidate('Game is not ready',taint=False)
                self.state=e['state']
                return
            if not self.licenses_approved:
                self.invalidate('Mod redistribution review required',taint=False)
                return
            if e['run_id']==self.tainted_run:
                self.invalidate('Source changed; wait for a new game run',taint=False)
                return
            if self.manifest and self.manifest.run_id==e['run_id']:
                self.require()
                if scan:
                    sources=self.collect(e)
                    if set(sources)!=set(self.sources) or any(fingerprint(sources[k])!=s for k,s in self.stamps.items()):
                        self.invalidate('Prepared source files changed')
                return
            self.invalidate('Indexing new game run',taint=False)
            self.build(e)
        except Exception:
            LOG.exception('Manifest serving disabled')
            if e and e.get('state')=='ready':
                self.tainted_run=e.get('run_id')
                self.save_taint()
            self.invalidate('Observation or source validation failed')

    def checked_file(self, key, revision):
        with self.read_slots:
            return self._checked_file(key,revision)

    def _checked_file(self,key,revision):
        manifest = self.require(revision)
        if key not in self.sources:
            raise FileNotFoundError(key)
        path = self.sources[key]
        try:
            safe_join(self.workshop,path.relative_to(self.workshop).as_posix())
            if fingerprint(path)!=self.stamps[key]:
                raise SyncError('Source fingerprint changed')
            expected = self.entries[key]
            # Verify just the requested file, once before each transfer; bounded memory.
            if digest(path)!=expected.sha256 or fingerprint(path)!=self.stamps[key]:
                raise SyncError('Source checksum changed')
        except (OSError,SyncError):
            self.invalidate('Source file changed')
            raise SyncError('Source file changed')
        self.require(revision)
        return path,expected

