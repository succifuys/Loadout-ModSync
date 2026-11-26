import hashlib
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from .common import SyncError, atomic_json, digest, fingerprint, safe_join, safe_relative, is_link
from .manifest import File, Manifest
from .network import DownloadControl, download, download_many
from .state import installation_lock, read_json
from .game import game_running, write_probe

LOG=logging.getLogger(__name__)
JOURNAL_BATCH=64


@dataclass
class Plan:
    manifest: Manifest
    changed: list[File]
    removed: list[str]
    conflicts: list[str]
    snapshots: dict
    registry: dict
    full_check: bool=False
    registry_stamp: tuple | None=None

    @property
    def download_size(self):
        return sum(x.size for x in self.changed)


def snapshot(path,control=None):
    if control:
        control.checkpoint()
    if not path.exists():
        if is_link(path):
            raise SyncError('Dangling symlink in destination')
        return None
    if not path.is_file():
        raise SyncError('A directory conflicts with a managed file')
    before=fingerprint(path)
    checksum=digest(path,checkpoint=control.checkpoint) if control else digest(path)
    if before!=fingerprint(path):
        raise SyncError('Local file changed during scan')
    return dict(size=before[2],sha256=checksum)


class Sync:
    def __init__(self,network,mods:Path,home:Path,running=game_running):
        self.network=network
        self.mods=mods.absolute()
        self.home=home.absolute()
        self.running=running
        safe_join(self.mods,'.dntsne-modsync.lock')
        safe_join(self.home,'installs')
        key=hashlib.sha256(str(self.mods).casefold().encode()).hexdigest()
        self.store=self.home/'installs'/key
        self.store.mkdir(parents=True,exist_ok=True)
        self.registry_path=self.store/'registry.json'
        self.journal_path=self.store/'journal.json'
        self.progress_path=self.store/'journal-progress.json'
        self.cache=self.store/'cache'
        self.verification_path=self.store/'verification.json'
        self.manifest_path=self.store/'manifest.json'
        self.receipt_path=self.store/'ready.json'
        self._verified=None
        self._verification_dirty=False

    def require_stopped(self):
        if self.running():
            raise SyncError('Close Project Zomboid and Java launchers before updating')

    def registry(self):
        r=read_json(self.registry_path,dict(mods_root=str(self.mods),server=self.network.url,revision=None,managed={},synced_at=None))
        if r.get('mods_root')!=str(self.mods) or r.get('server')!=self.network.url:
            raise SyncError('Managed installation belongs to a different directory or server')
        if not isinstance(r.get('managed'),dict):
            raise SyncError('Invalid ownership registry')
        for key,value in r['managed'].items():
            safe_relative(key)
            if '/' not in key or not isinstance(value,dict) or set(value)!={'size','sha256'}:
                raise SyncError('Invalid ownership record')
        return r

    def _verification(self):
        if self._verified is None:
            data=read_json(self.verification_path,{})
            self._verified=data.get('files',{}) if isinstance(data,dict) else {}
            if not isinstance(self._verified,dict):
                self._verified={}
        return self._verified

    def _local(self,key,force=False,control=None):
        if control:
            control.checkpoint()
        path=safe_join(self.mods,key)
        records=self._verification()
        cached=records.get(key)
        stamp=None
        if path.exists():
            stamp=list(fingerprint(path))
            if not force and isinstance(cached,dict) and cached.get('fingerprint')==stamp:
                value=cached.get('value')
                if isinstance(value,dict) and set(value)=={'size','sha256'} and value['size']==stamp[2] and isinstance(value['sha256'],str) and len(value['sha256'])==64:
                    return value
        value=snapshot(path,control)
        if value is None:
            if key in records:
                del records[key]
                self._verification_dirty=True
        else:
            if stamp!=list(fingerprint(path)):
                raise SyncError('Local file changed during scan')
            record=dict(fingerprint=stamp,value=value)
            if record!=cached:
                records[key]=record
                self._verification_dirty=True
        return value

    def _save_verification(self):
        if self._verification_dirty:
            atomic_json(self.verification_path,dict(files=self._verification()))
            self._verification_dirty=False

    @staticmethod
    def folder_fingerprints(files):
        groups={}
        for key,value in files.items():
            groups.setdefault(key.split('/')[0],[]).append((key,value['size'],value['sha256']))
        # Computed from the existing manifest; no server protocol change is needed.
        import json
        return {folder:hashlib.sha256(json.dumps(sorted(entries),separators=(',',':')).encode()).hexdigest()
                for folder,entries in groups.items()}

    def _plan(self,manifest,scan_progress=None,full_check=False,control=None):
        stamp=fingerprint(self.registry_path) if self.registry_path.exists() else None
        r=self.registry()
        if stamp!=(fingerprint(self.registry_path) if self.registry_path.exists() else None):
            raise SyncError('Ownership registry changed during check')
        changed,removed,conflicts,snapshots=[],[],[],{}
        desired={x.path:x for x in manifest.files}
        old_folders=self.folder_fingerprints(r['managed'])
        new_folders=self.folder_fingerprints({x.path:dict(size=x.size,sha256=x.sha256) for x in manifest.files})
        changed_folders={folder for folder in new_folders if new_folders[folder]!=old_folders.get(folder)}
        previous_case={k.casefold():k for k in r['managed']}
        for key in desired:
            if key.casefold() in previous_case and previous_case[key.casefold()]!=key:
                raise SyncError('Managed filename changed only in capitalization; manual migration required')
        existing_case={}
        # Catch foreign folders with different capitalization even on case-sensitive fixtures.
        if self.mods.exists():
            for path in self.mods.iterdir():
                existing_case[path.name.casefold()]=path.name
        for folder in manifest.folders:
            if folder.casefold() in existing_case and existing_case[folder.casefold()]!=folder:
                raise SyncError('Existing mod folder differs only by capitalization')
        for count,entry in enumerate(manifest.files,1):
            folder=entry.path.split('/',1)[0]
            # A missing top-level mod folder cannot contain any of these files.
            # Recheck the inventory under the update lock, then check each target
            # again immediately before replacing it. Existing folders are still
            # checked normally, including links, hashes and personal conflicts.
            if folder.casefold() not in existing_case:
                safe_relative(entry.path)
                if control and (count%256==1 or count==len(manifest.files)):
                    control.checkpoint()
                local=None
            else:
                local=self._local(entry.path,full_check or folder in changed_folders,control)
            snapshots[entry.path]=local
            old=r['managed'].get(entry.path)
            if local and not old:
                conflicts.append(entry.path)
            if local and old and local!=old:
                conflicts.append(entry.path)
            if local!=dict(size=entry.size,sha256=entry.sha256):
                changed.append(entry)
            if scan_progress and (count%1000==0 or count==len(manifest.files)):
                scan_progress(count,len(manifest.files))
        for key,old in r['managed'].items():
            if key not in desired:
                local=self._local(key,True,control)
                snapshots[key]=local
                if local:
                    if local!=old:
                        conflicts.append(key)
                    removed.append(key)
        self._save_verification()
        if changed or removed or conflicts:
            atomic_json(self.receipt_path,dict(invalid=True))
        return Plan(manifest,changed,removed,sorted(set(conflicts)),snapshots,r,full_check,stamp)

    def remember_ready(self,manifest):
        receipt=dict(server=self.network.url,mods_root=str(self.mods),revision=manifest.revision,
            pz_version=manifest.pz_version,folders=len(manifest.folders),files=len(manifest.files),
            registry_stamp=list(fingerprint(self.registry_path)))
        atomic_json(self.receipt_path,receipt)
        return receipt

    def ready_receipt(self):
        if self.journal_path.exists() or not self.registry_path.exists() or not self.mods.is_dir():
            return None
        receipt=read_json(self.receipt_path,None)
        stamp=list(fingerprint(self.registry_path))
        fields={'server','mods_root','revision','pz_version','folders','files','registry_stamp'}
        if isinstance(receipt,dict) and set(receipt)==fields and receipt.get('server')==self.network.url and receipt.get('mods_root')==str(self.mods) and receipt.get('registry_stamp')==stamp:
            return receipt
        # Migrate successful 0.1.0/0.1.1 installs using their committed registry,
        # without rereading mod files. A completed check alone is insufficient.
        if not self.receipt_path.exists() and self.manifest_path.exists():
            registry=self.registry()
            manifest=Manifest.parse(read_json(self.manifest_path,None))
            desired={f.path:dict(size=f.size,sha256=f.sha256) for f in manifest.files}
            if registry.get('synced_at') and registry['revision']==manifest.revision and registry['managed']==desired and stamp==list(fingerprint(self.registry_path)):
                return self.remember_ready(manifest)
        return None

    def _validate_plan(self,plan,control,progress=None):
        stamp=fingerprint(self.registry_path) if self.registry_path.exists() else None
        if stamp!=plan.registry_stamp:
            raise SyncError('Local installation changed since check; check again')
        # Use a fresh directory inventory for each pass. A new competing file
        # is still detected here or by the strict check immediately before writes.
        safe_join(self.mods,'.probe')
        present={p.name.casefold():p.name for p in self.mods.iterdir()}
        keys=set(f.path for f in plan.changed)|set(plan.removed)|set(plan.conflicts)
        total=len(keys)
        if progress:
            progress(0,total)
        for count,key in enumerate(keys,1):
            if count%256==1 or count==total:
                control.checkpoint()
            folder=safe_relative(key).split('/',1)[0]
            name=present.get(folder.casefold())
            if name is not None and name!=folder:
                raise SyncError('Existing mod folder differs only by capitalization')
            previous=plan.snapshots[key]
            local=None if name is None and previous is None else self._local(key,True,control)
            if local!=previous:
                raise SyncError('Local installation changed since check; check again')
            if progress and (count%1000==0 or count==total):
                progress(count,total)
        return plan

    def check(self,manifest=None,scan_progress=None,full_check=False,control=None):
        self.require_stopped()
        write_probe(self.mods)
        with installation_lock(self.mods):
            self.recover()
            m=manifest
            if m is None and self.manifest_path.exists() and hasattr(self.network,'status'):
                status=self.network.status()
                if status['state']!='ready':
                    raise SyncError('Game server: '+status['state'])
                cached=read_json(self.manifest_path,None)
                if isinstance(cached,dict) and cached.get('revision')==status.get('revision'):
                    m=Manifest.parse(cached)
            m=m or self.network.manifest()
            result=self._plan(m,scan_progress,full_check,control)
            if read_json(self.manifest_path,None)!=m.to_dict():
                atomic_json(self.manifest_path,m.to_dict())
            return result

    def recover(self):
        journal=read_json(self.journal_path,None)
        if not journal:
            return
        self.require_stopped()
        if journal['mods_root']!=str(self.mods):
            raise SyncError('Recovery journal belongs to another installation')
        txn=safe_relative(journal['transaction'])
        if not txn.startswith('.dntsne-transactions/') or len(txn.split('/'))!=2 or len(txn.split('/')[1])!=32:
            raise SyncError('Invalid transaction journal')
        # Registry is the commit point; a crash immediately afterward must not undo it.
        if read_json(self.registry_path,None)==journal.get('next_registry'):
            self.journal_path.unlink()
            self.progress_path.unlink(missing_ok=True)
            return
        progress=read_json(self.progress_path,None)
        if progress:
            if progress.get('transaction')!=journal['transaction']:
                raise SyncError('Recovery progress belongs to another transaction')
            journal['attempted']=progress.get('attempted')
        if type(journal['attempted']) is not int or not 0<=journal['attempted']<=len(journal['operations']):
            raise SyncError('Invalid recovery progress')
        for op in reversed(journal['operations'][:journal['attempted']]):
            target=safe_join(self.mods,op['path'])
            backup=safe_join(self.mods,txn+'/backup/'+op['path'])
            staged=safe_join(self.mods,txn+'/new/'+op['path'])
            current=snapshot(target)
            if backup.exists():
                if snapshot(backup)!=op['old']:
                    raise SyncError('Recovery backup changed; manual recovery required')
                if current is not None and current!=op['new']:
                    raise SyncError('Local file changed after interrupted install; preserved for manual recovery')
                target.parent.mkdir(parents=True,exist_ok=True)
                os.replace(backup,target)
            elif op['old'] is not None:
                if current!=op['old']:
                    raise SyncError('Cannot restore missing backup; manual recovery required')
            elif staged.exists():
                # This new-file operation was reserved durably but never applied.
                # A file another program created meanwhile is foreign; preserve it.
                continue
            elif current is not None:
                if current!=op['new']:
                    raise SyncError('Foreign file encountered during recovery; preserved')
                target.unlink()
        atomic_json(self.registry_path,journal['previous_registry'])
        self.journal_path.unlink()
        self.progress_path.unlink(missing_ok=True)
        LOG.info('Interrupted installation rolled back')

    def record_progress(self,transaction,attempted):
        # The complete immutable operation table is written ONCE. Rewriting it
        # for each of 174k files would create quadratic disk traffic.
        atomic_json(self.progress_path,dict(transaction=transaction,attempted=attempted))

    def update(self,plan:Plan,control=None,progress=lambda *args:None,consent_conflicts=False,phase_progress=None):
        control=control or DownloadControl()
        self.require_stopped()
        write_probe(self.mods)
        def phase(name,done,total):
            if phase_progress:
                phase_progress(name,done,total)
            control.checkpoint()
        last_process_check=0.0
        def guard_process():
            nonlocal last_process_check
            now=time.monotonic()
            if now-last_process_check>=0.1:
                self.require_stopped()
                last_process_check=now
        with installation_lock(self.mods):
            self.recover()
            control.checkpoint()
            self.network.require_revision(plan.manifest.revision)
            fresh=self._validate_plan(plan,control,
                lambda done,total:phase('Validating changed files',done,total))
            if fresh.snapshots!=plan.snapshots or fresh.registry!=plan.registry:
                raise SyncError('Local installation changed since check; check again')
            if fresh.conflicts and not consent_conflicts:
                raise SyncError('Files conflict with personal or modified mods; explicit consent required')
            if not fresh.changed and not fresh.removed and not fresh.conflicts:
                if fresh.registry['revision']==plan.manifest.revision:
                    self.remember_ready(plan.manifest)
                    return fresh.registry
                # A new server run may contain identical bytes. Every desired
                # file was just hashed under the installation lock; only the
                # atomic ownership/revision record needs to change.
                control.checkpoint()
                self.network.require_revision(plan.manifest.revision)
                self.require_stopped()
                registry=dict(mods_root=str(self.mods),server=self.network.url,
                    revision=plan.manifest.revision,
                    managed={f.path:dict(size=f.size,sha256=f.sha256) for f in plan.manifest.files},
                    synced_at=datetime.now(timezone.utc).isoformat())
                atomic_json(self.registry_path,registry)
                self.remember_ready(plan.manifest)
                LOG.info('Adopted unchanged files for server revision %s',plan.manifest.revision)
                return registry
            # Preserve a foreign original even when adopting an identical file.
            changed={x.path:x for x in fresh.changed}
            conflicting=set(fresh.conflicts)
            for entry in fresh.manifest.files:
                if entry.path in conflicting:
                    changed[entry.path]=entry
            needed=sum(x.size for x in changed.values())
            self.cache.mkdir(parents=True,exist_ok=True)
            safe_join(self.cache,'.probe')
            same_volume=self.mods.stat().st_dev==self.store.stat().st_dev
            mods_needed=needed*(2 if same_volume else 1)+64*1024*1024
            if shutil.disk_usage(self.mods).free<mods_needed or shutil.disk_usage(self.store).free<needed+64*1024*1024:
                raise SyncError('Not enough disk space for download and transaction')
            transfers=[entry for entry in changed.values()
                       if fresh.snapshots[entry.path]!=dict(size=entry.size,sha256=entry.sha256)]
            if getattr(self.network,'bundle_supported',False) and len(transfers)>4:
                download_many(self.network,transfers,plan.manifest.revision,self.cache,control,progress,
                    cache_progress=lambda done,total:phase('Checking download cache',done,total))
                self.require_stopped()
            for entry in ([] if getattr(self.network,'bundle_supported',False) and len(transfers)>4 else transfers):
                if fresh.snapshots[entry.path]==dict(size=entry.size,sha256=entry.sha256):
                    continue  # Adoption with consent never retransfers an identical local file.
                part=safe_join(self.cache,f'{plan.manifest.revision}/{entry.sha256}.part')
                download(self.network,entry,plan.manifest.revision,part,control,progress)
                self.require_stopped()
            control.checkpoint()
            self.network.require_revision(plan.manifest.revision)
            self.require_stopped()
            self._validate_plan(plan,control,
                lambda done,total:phase('Rechecking before install',done,total))
            phase('Preparing',0,len(changed)+len(fresh.removed))
            txn='.dntsne-transactions/'+uuid.uuid4().hex
            work=safe_join(self.mods,txn)
            work.mkdir(parents=True,exist_ok=False)
            operations=[]
            keys=sorted(set(changed)|set(fresh.removed))
            for staged_count,key in enumerate(keys,1):
                guard_process()
                control.checkpoint()
                entry=changed.get(key)
                new=dict(size=entry.size,sha256=entry.sha256) if entry else None
                operations.append(dict(path=key,old=fresh.snapshots[key],new=new))
                if entry:
                    staged=safe_join(self.mods,txn+'/new/'+key)
                    staged.parent.mkdir(parents=True,exist_ok=True)
                    source=(safe_join(self.mods,key) if fresh.snapshots[key]==new else safe_join(self.cache,f'{plan.manifest.revision}/{entry.sha256}.part'))
                    with source.open('rb') as source_file, staged.open('wb') as staged_file:
                        while True:
                            control.checkpoint()
                            chunk=source_file.read(1024*1024)
                            if not chunk:
                                break
                            staged_file.write(chunk)
                    if snapshot(staged,control)!=new:
                        raise SyncError('Staged file corrupted; no files installed')
                if staged_count%1000==0 or staged_count==len(keys):
                    phase('Preparing',staged_count,len(keys))
            self.require_stopped()
            self.network.require_revision(plan.manifest.revision)
            registry=dict(mods_root=str(self.mods),server=self.network.url,revision=plan.manifest.revision,
                          managed={f.path:dict(size=f.size,sha256=f.sha256) for f in plan.manifest.files},
                          synced_at=datetime.now(timezone.utc).isoformat())
            journal=dict(mods_root=str(self.mods),transaction=txn,operations=operations,attempted=0,
                         previous_registry=fresh.registry,next_registry=registry)
            atomic_json(self.journal_path,journal)
            self.record_progress(txn,0)
            try:
                last_lease_check=0.0
                for number,op in enumerate(operations):
                    control.checkpoint()
                    guard_process()
                    if number%JOURNAL_BATCH==0:
                        # Reserve the entire next batch BEFORE any rename. Recovery
                        # safely distinguishes untouched, backed-up and installed files.
                        journal['attempted']=min(number+JOURNAL_BATCH,len(operations))
                        self.record_progress(txn,journal['attempted'])
                    if time.monotonic()-last_lease_check>=1:
                        self.network.require_revision(plan.manifest.revision)
                        last_lease_check=time.monotonic()
                    target=safe_join(self.mods,op['path'])
                    if snapshot(target,control)!=op['old']:
                        raise SyncError('Local file changed during installation')
                    if op['old'] is not None:
                        backup=safe_join(self.mods,txn+'/backup/'+op['path'])
                        backup.parent.mkdir(parents=True,exist_ok=True)
                        os.replace(target,backup)
                    if op['new'] is not None:
                        target.parent.mkdir(parents=True,exist_ok=True)
                        os.replace(safe_join(self.mods,txn+'/new/'+op['path']),target)
                    if (number+1)%1000==0 or number+1==len(operations):
                        phase('Installing',number+1,len(operations))
                self.require_stopped()
                self.network.require_revision(plan.manifest.revision)
                # Unchanged files were checked by the plan (or explicitly trusted
                # by a same-revision receipt). Verify only installed differences.
                installed_entries=list(changed.values())
                for validated_count,entry in enumerate(installed_entries,1):
                    guard_process()
                    if self._local(entry.path,entry.path in changed,control)!=dict(size=entry.size,sha256=entry.sha256):
                        raise SyncError('Installed build failed final integrity check')
                    if validated_count%1000==0 or validated_count==len(installed_entries):
                        phase('Verifying',validated_count,len(installed_entries))
                for key in fresh.removed:
                    if self._local(key,True,control) is not None:
                        raise SyncError('Removed file reappeared during installation')
                control.checkpoint()
                phase('Saving state',1,1)
                self.network.require_revision(plan.manifest.revision)
                self.require_stopped()
                self._save_verification()
                atomic_json(self.registry_path,registry)
                self.journal_path.unlink()
                self.progress_path.unlink(missing_ok=True)
                self.remember_ready(plan.manifest)
                LOG.info('Installed revision %s (%s changed files)',plan.manifest.revision,len(changed))
            except BaseException:
                self.recover()
                raise
            # Backups contain only replaced/removed files, retained for administrator rollback.
            # Do not discard personal originals automatically or mark an unverified build ready.
            try:
                self._clear_cache()
            except (OSError,SyncError):
                LOG.warning('Installed successfully; temporary cache cleanup needs retry')
            return registry

    def _clear_cache(self):
        if self.cache.exists():
            safe_join(self.store,'cache')
            files=list(self.cache.rglob('*'))
            for path in files:
                safe_join(self.cache,path.relative_to(self.cache).as_posix())
            for path in sorted(files,key=lambda p:len(p.parts),reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            self.cache.rmdir()

    def clean_cache(self):
        self.require_stopped()
        with installation_lock(self.mods):
            self.recover()
            self._clear_cache()

    def uninstall(self):
        """Remove exactly owned, unmodified files. Keep personal edits and backups."""
        self.require_stopped()
        with installation_lock(self.mods):
            self.recover()
            r=self.registry()
            modified=[]
            for key,value in r['managed'].items():
                path=safe_join(self.mods,key)
                current=snapshot(path)
                if current and current!=value:
                    modified.append(key)
            if modified:
                raise SyncError('Modified owned files found; uninstall stopped without deleting them')
            # Use the same durable rollback engine for removal via an empty ownership registry.
            txn='.dntsne-transactions/'+uuid.uuid4().hex
            safe_join(self.mods,txn).mkdir(parents=True,exist_ok=False)
            operations=[dict(path=k,old=snapshot(safe_join(self.mods,k)),new=None) for k in r['managed']]
            new=dict(r,revision=None,managed={},synced_at=None)
            journal=dict(mods_root=str(self.mods),transaction=txn,operations=operations,attempted=0,previous_registry=r,next_registry=new)
            atomic_json(self.journal_path,journal)
            self.record_progress(txn,0)
            try:
                for number,op in enumerate(operations):
                    self.require_stopped()
                    if number%JOURNAL_BATCH==0:
                        journal['attempted']=min(number+JOURNAL_BATCH,len(operations))
                        self.record_progress(txn,journal['attempted'])
                    if op['old']:
                        target=safe_join(self.mods,op['path'])
                        if snapshot(target)!=op['old']:
                            raise SyncError('File changed during uninstall')
                        backup=safe_join(self.mods,txn+'/backup/'+op['path'])
                        backup.parent.mkdir(parents=True,exist_ok=True)
                        os.replace(target,backup)
                atomic_json(self.registry_path,new)
                self.journal_path.unlink()
                self.progress_path.unlink(missing_ok=True)
            except BaseException:
                self.recover()
                raise
