import os
import time
from pathlib import Path
import pytest
from dntsne.common import SyncError, atomic_json, digest
from dntsne.network import DownloadControl
from dntsne.state import installation_lock
from dntsne.sync import Sync, snapshot


class FakeNetwork:
    url='http://127.0.0.1:8787'
    def __init__(self,index):
        self.index=index
        self.downloaded=[]
        self.fail_at=None
        self.calls=0
    def manifest(self):
        return self.index.require()
    def require_revision(self,revision):
        self.calls+=1
        if self.fail_at==self.calls:
            raise SyncError('Simulated game restart')
        self.index.require(revision)


@pytest.fixture
def engine(build,tmp_path,monkeypatch):
    index,_,_=build
    network=FakeNetwork(index)
    def download(net,entry,revision,part,control,progress):
        control.checkpoint()
        path,_=index.checked_file(entry.path,revision)
        part.parent.mkdir(parents=True,exist_ok=True)
        part.write_bytes(path.read_bytes())
        net.downloaded.append(entry.path)
        progress(entry.path,entry.size,entry.size,entry.size)
    monkeypatch.setattr('dntsne.sync.download',download)
    return Sync(network,tmp_path/'mods',tmp_path/'state',running=lambda:False)


def next_run(build):
    index,_,e=build
    e['run_id']=str(int(e['run_id'][0])+1)*64
    e['observed_at']=time.time()
    atomic_json(index.observation,e)
    index.tick()


def test_first_install_and_noop(engine):
    plan=engine.check()
    assert len(plan.changed)==3
    engine.update(plan)
    assert (engine.mods/'Example/common/mod.info').exists()
    assert not (engine.mods/'123').exists()
    assert (engine.mods/'Example/42/media/java/plugin.jar').read_bytes()==b'jar-fixture'
    engine.network.downloaded.clear()
    engine.update(engine.check())
    assert engine.network.downloaded==[]


def test_new_run_with_identical_files_updates_only_registry(engine,build,monkeypatch):
    engine.update(engine.check())
    previous=engine.registry()
    next_run(build)
    plan=engine.check()
    assert not plan.changed and not plan.removed and not plan.conflicts
    assert plan.manifest.revision!=previous['revision']
    engine.network.downloaded.clear()
    def unexpected_transaction(*args):
        raise AssertionError('Identical build must not stage another transaction')
    monkeypatch.setattr(engine,'record_progress',unexpected_transaction)
    engine.update(plan)
    assert engine.registry()['revision']==plan.manifest.revision
    assert engine.registry()['managed']==previous['managed']
    assert engine.network.downloaded==[]


def observe_hashes(monkeypatch):
    import dntsne.sync as module
    calls=[]
    original=module.digest
    def observe(path,**kwargs):
        calls.append(Path(path))
        return original(path,**kwargs)
    monkeypatch.setattr(module,'digest',observe)
    return calls


def test_soft_same_revision_and_identical_restart_read_no_content(engine,build,monkeypatch):
    engine.update(engine.check())
    calls=observe_hashes(monkeypatch)
    # Recreate the engine to prove the persisted cache works across app launches.
    reopened=Sync(engine.network,engine.mods,engine.home,running=lambda:False)
    assert not reopened.check().changed
    assert calls==[]
    next_run(build)
    plan=reopened.check()
    reopened.update(plan)
    assert calls==[] and not plan.changed
    assert reopened.registry()['revision']==plan.manifest.revision


def test_new_revision_hashes_only_changed_mod(engine,build,monkeypatch):
    second=build[1].parent/'Other'
    (second/'common').mkdir(parents=True)
    (second/'common/mod.info').write_bytes(b'id=Other\n')
    build[2]['folders']['Other']='content/108600/123/mods/Other'
    next_run(build)
    engine.update(engine.check())
    (build[1]/'42/media/a.lua').write_bytes(b'changed lua')
    next_run(build)
    calls=observe_hashes(monkeypatch)
    plan=engine.check()
    assert len(calls)==3
    assert all(path.is_relative_to(engine.mods/'Example') for path in calls)
    assert [entry.path for entry in plan.changed]==['Example/42/media/a.lua']
    calls.clear()
    engine.network.downloaded.clear()
    engine.update(plan)
    assert engine.network.downloaded==['Example/42/media/a.lua']
    assert not any(path.is_relative_to(engine.mods/'Other') for path in calls)


def test_soft_changed_metadata_missing_and_replaced_file(engine,monkeypatch):
    engine.update(engine.check())
    lua=engine.mods/'Example/42/media/a.lua'
    original=lua.stat()
    lua.write_bytes(b'bad lua')  # Same size, different mtime.
    os.utime(lua,ns=(original.st_atime_ns,original.st_mtime_ns+10000000))
    jar=engine.mods/'Example/42/media/java/plugin.jar'
    jar.unlink()
    calls=observe_hashes(monkeypatch)
    plan=engine.check()
    assert calls==[lua]
    assert set(entry.path for entry in plan.changed)=={'Example/42/media/a.lua','Example/42/media/java/plugin.jar'}
    assert plan.conflicts==['Example/42/media/a.lua']
    engine.update(plan,consent_conflicts=True)
    assert not engine.check().changed


def test_legacy_install_warms_verification_once(engine,monkeypatch):
    engine.update(engine.check())
    engine.verification_path.unlink()
    reopened=Sync(engine.network,engine.mods,engine.home,running=lambda:False)
    calls=observe_hashes(monkeypatch)
    assert not reopened.check().changed
    assert len(calls)==3
    calls.clear()
    assert not reopened.check().changed
    assert calls==[]


def test_soft_replaced_file_with_preserved_size_and_mtime_is_hashed(engine,monkeypatch):
    engine.update(engine.check())
    target=engine.mods/'Example/42/media/a.lua'
    stamp=target.stat()
    replacement=engine.mods/'replacement.tmp'
    replacement.write_bytes(b'bad lua')
    os.utime(replacement,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    os.replace(replacement,target)
    calls=observe_hashes(monkeypatch)
    plan=engine.check()
    assert calls==[target]
    assert [entry.path for entry in plan.changed]==['Example/42/media/a.lua']


def test_noop_plan_does_not_scan_but_full_verification_detects_edit(engine):
    engine.update(engine.check())
    plan=engine.check()
    target=engine.mods/'Example/42/media/a.lua'
    target.write_bytes(b'local edit after cached check')
    engine.update(plan)
    assert target.read_bytes()==b'local edit after cached check'
    assert engine.check(full_check=True).changed
    assert engine.ready_receipt() is None


def test_cached_manifest_cannot_allow_stopped_server(engine):
    engine.update(engine.check())
    engine.network.status=lambda:{'state':'offline','revision':None}
    with pytest.raises(SyncError,match='Game server: offline'):
        engine.check()


def test_ready_receipt_survives_restart_and_migrates_without_mod_reads(engine,monkeypatch):
    engine.update(engine.check())
    receipt=engine.ready_receipt()
    assert receipt['revision']==engine.registry()['revision']
    reopened=Sync(engine.network,engine.mods,engine.home,running=lambda:False)
    calls=observe_hashes(monkeypatch)
    assert reopened.ready_receipt()==receipt
    assert calls==[]
    reopened.receipt_path.unlink()  # A successful previous launcher has no receipt.
    assert reopened.ready_receipt()==receipt
    assert calls==[]


def test_full_check_damage_and_interrupted_transaction_invalidate_receipt(engine):
    engine.update(engine.check())
    assert engine.ready_receipt()
    (engine.mods/'Example/42/media/a.lua').write_bytes(b'broken')
    assert engine.check(full_check=True).changed
    assert engine.ready_receipt() is None


def test_update_reuses_plan_instead_of_repeating_whole_scan(engine,monkeypatch):
    plan=engine.check()
    monkeypatch.setattr(engine,'_plan',lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('Repeated whole scan')))
    engine.update(plan)
    assert engine.ready_receipt()


def test_full_verification_ignores_cache(engine,monkeypatch):
    engine.update(engine.check())
    calls=observe_hashes(monkeypatch)
    assert not engine.check(full_check=True).changed
    assert len(calls)==3


@pytest.mark.parametrize('stage',['Validating changed files','Preparing','Installing','Verifying'])
def test_pause_blocks_scan_prepare_install_and_verify(engine,build,stage):
    import threading
    for number in range(5):
        (build[1]/f'42/media/pause-{number}.lua').write_bytes(b'fixture')
    next_run(build)
    plan=engine.check()
    control=DownloadControl()
    paused=threading.Event()
    finished=threading.Event()
    errors=[]
    def phase(name,done,total):
        if name==stage and not paused.is_set():
            control.running.clear()
            paused.set()
    def work():
        try:
            engine.update(plan,control,phase_progress=phase)
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()
    thread=threading.Thread(target=work)
    thread.start()
    try:
        assert paused.wait(3),stage
        assert not finished.wait(.15),stage
        assert engine.registry()['revision'] is None
    finally:
        control.running.set()
        thread.join(5)
    assert not thread.is_alive() and not errors
    assert engine.registry()['revision']==plan.manifest.revision


def test_pause_during_large_file_hash_stops_before_next_chunk(engine,monkeypatch):
    import threading
    from dntsne.common import digest as real_digest
    engine.update(engine.check())
    target=engine.mods/'Example/42/media/a.lua'
    target.write_bytes(b'x'*(3*1024*1024))
    control=DownloadControl()
    paused=threading.Event()
    completed=threading.Event()
    original_checkpoint=control.checkpoint
    checkpoints=0
    def checkpoint():
        nonlocal checkpoints
        checkpoints+=1
        if checkpoints==2:
            control.running.clear()
            paused.set()
        original_checkpoint()
    control.checkpoint=checkpoint
    errors=[]
    def work():
        try:
            real_digest(target,checkpoint=checkpoint)
        except BaseException as exc:
            errors.append(exc)
        finally:
            completed.set()
    thread=threading.Thread(target=work)
    thread.start()
    try:
        assert paused.wait(2)
        assert not completed.wait(.15)
        assert checkpoints==2
    finally:
        control.running.set()
        thread.join(3)
    assert completed.is_set() and not errors


def test_single_delta_add_remove_preserve_personal(engine,build):
    engine.update(engine.check())
    index,folder,_=build
    personal=engine.mods/'Personal/readme.txt'
    personal.parent.mkdir()
    personal.write_text('mine')
    (folder/'42/media/a.lua').write_bytes(b'changed lua')
    next_run(build)
    plan=engine.check()
    assert [x.path for x in plan.changed]==['Example/42/media/a.lua']
    engine.network.downloaded.clear()
    engine.update(plan)
    assert engine.network.downloaded==['Example/42/media/a.lua']
    (folder/'new.lua').write_bytes(b'new')
    (folder/'42/media/java/plugin.jar').unlink()
    next_run(build)
    plan=engine.check()
    assert plan.removed==['Example/42/media/java/plugin.jar']
    engine.update(plan)
    assert not (engine.mods/plan.removed[0]).exists()
    assert personal.read_text()=='mine'


def test_foreign_conflicts_consent_and_backup(engine):
    target=engine.mods/'Example/42/media/a.lua'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'my lua')
    plan=engine.check()
    assert plan.conflicts==['Example/42/media/a.lua']
    with pytest.raises(SyncError):
        engine.update(plan)
    assert target.read_bytes()==b'my lua'
    engine.update(plan,consent_conflicts=True)
    assert any(x.read_bytes()==b'my lua' for x in engine.mods.glob('.dntsne-transactions/*/backup/Example/42/media/a.lua'))


def test_identical_foreign_files_are_not_transferred_again(engine):
    for entry in engine.network.index.manifest.files:
        path=engine.mods/entry.path
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(engine.network.index.sources[entry.path].read_bytes())
    plan=engine.check()
    assert not plan.changed and len(plan.conflicts)==3
    engine.update(plan,consent_conflicts=True)
    assert engine.network.downloaded==[]
    assert len(engine.registry()['managed'])==3


def test_success_clears_download_cache_but_keeps_backups(engine):
    engine.update(engine.check())
    assert not engine.cache.exists()



def test_modified_owned_obsolete_file_preserved(engine,build):
    engine.update(engine.check())
    target=engine.mods/'Example/42/media/a.lua'
    target.write_bytes(b'mine')
    (build[1]/'42/media/a.lua').unlink()
    next_run(build)
    plan=engine.check()
    with pytest.raises(SyncError):
        engine.update(plan)
    assert target.read_bytes()==b'mine'


def test_rolls_back_failed_group(engine,build):
    engine.update(engine.check())
    old=engine.registry()
    (build[1]/'42/media/a.lua').write_bytes(b'new')
    (build[1]/'42/media/java/plugin.jar').write_bytes(b'new jar')
    next_run(build)
    plan=engine.check()
    engine.network.fail_at=engine.network.calls+4  # before second replacement
    with pytest.raises(SyncError):
        engine.update(plan)
    assert (engine.mods/'Example/42/media/a.lua').read_bytes()==b'old lua'
    assert (engine.mods/'Example/42/media/java/plugin.jar').read_bytes()==b'jar-fixture'
    assert engine.registry()==old
    assert not engine.journal_path.exists()


def test_crash_after_rename_before_registry_recover(engine):
    target=engine.mods/'Example/a.txt'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'old')
    old=snapshot(target)
    txn='.dntsne-transactions/'+'a'*32
    backup=engine.mods/txn/'backup/Example/a.txt'
    backup.parent.mkdir(parents=True)
    os.replace(target,backup)
    target.write_bytes(b'new')
    registry=engine.registry()
    atomic_json(engine.journal_path,dict(mods_root=str(engine.mods),transaction=txn,operations=[dict(path='Example/a.txt',old=old,new=snapshot(target))],attempted=1,previous_registry=registry,next_registry={'test':'uncommitted'}))
    engine.recover()
    assert target.read_bytes()==b'old'


def test_compact_progress_recovers_attempt_not_in_operation_table(engine):
    target=engine.mods/'Example/a.txt'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'old')
    old=snapshot(target)
    txn='.dntsne-transactions/'+'b'*32
    backup=engine.mods/txn/'backup/Example/a.txt'
    backup.parent.mkdir(parents=True)
    os.replace(target,backup)
    target.write_bytes(b'new')
    registry=engine.registry()
    atomic_json(engine.journal_path,dict(mods_root=str(engine.mods),transaction=txn,
        operations=[dict(path='Example/a.txt',old=old,new=snapshot(target))],attempted=0,
        previous_registry=registry,next_registry={'test':'uncommitted'}))
    engine.record_progress(txn,1)
    engine.recover()
    assert target.read_bytes()==b'old'
    assert not engine.progress_path.exists()


def test_full_operation_table_written_once(engine,monkeypatch):
    import dntsne.sync as module
    writes=[]
    original=module.atomic_json
    def observe(path,data):
        if path==engine.journal_path:writes.append(data)
        original(path,data)
    monkeypatch.setattr(module,'atomic_json',observe)
    engine.update(engine.check())
    assert len(writes)==1
    assert not engine.progress_path.exists()


def test_progress_fsyncs_are_bounded_by_batches(engine,build,monkeypatch):
    from dntsne.sync import JOURNAL_BATCH
    for number in range(130):
        (build[1]/f'42/media/batch-{number}.lua').write_bytes(b'fixture')
    next_run(build)
    plan=engine.check()
    writes=[]
    original=engine.record_progress
    def observe(txn,attempted):
        writes.append(attempted)
        original(txn,attempted)
    monkeypatch.setattr(engine,'record_progress',observe)
    engine.update(plan)
    assert writes[0]==0 and writes[-1]==len(plan.changed)
    assert len(writes)==1+(len(plan.changed)+JOURNAL_BATCH-1)//JOURNAL_BATCH


def test_reserved_unapplied_operation_preserves_foreign_file(engine,monkeypatch):
    plan=engine.check()
    keys=sorted(x.path for x in plan.manifest.files)
    foreign=engine.mods/keys[-1]
    original=os.replace
    installed=0
    def fail_mid_batch(source,target):
        nonlocal installed
        if '/new/' in Path(source).as_posix() and Path(target).is_relative_to(engine.mods):
            installed+=1
            if installed==2:
                foreign.parent.mkdir(parents=True,exist_ok=True)
                foreign.write_bytes(b'foreign-created-after-batch-reservation')
                raise RuntimeError('Simulated power loss within batch')
        return original(source,target)
    monkeypatch.setattr('dntsne.sync.os.replace',fail_mid_batch)
    with pytest.raises(RuntimeError,match='power loss'):
        engine.update(plan)
    assert foreign.read_bytes()==b'foreign-created-after-batch-reservation'
    assert not (engine.mods/keys[0]).exists()
    assert engine.registry()['revision'] is None
    assert not engine.journal_path.exists()


def test_running_game_and_concurrent_clients(engine):
    engine.running=lambda:True
    with pytest.raises(SyncError):
        engine.check()
    engine.running=lambda:False
    with installation_lock(engine.mods):
        with pytest.raises(SyncError):
            engine.check()


def test_local_edit_after_check(engine):
    plan=engine.check()
    target=engine.mods/'Example/42/media/a.lua'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'personal')
    with pytest.raises(SyncError):
        engine.update(plan)
    assert target.read_bytes()==b'personal'


def test_not_enough_space(engine,monkeypatch):
    plan=engine.check()
    monkeypatch.setattr('dntsne.sync.shutil.disk_usage',lambda _:type('Disk',(),{'free':0})())
    with pytest.raises(SyncError,match='disk space'):
        engine.update(plan)
    assert engine.network.downloaded==[]


def test_permission_error_is_not_ignored(engine,monkeypatch):
    monkeypatch.setattr('dntsne.game.tempfile.TemporaryFile',lambda **_:(_ for _ in ()).throw(PermissionError()))
    with pytest.raises(SyncError,match='write permission'):
        engine.check()


def test_uninstall_keeps_personal_files(engine):
    engine.update(engine.check())
    personal=engine.mods/'Example/personal.txt'
    personal.write_bytes(b'mine')
    engine.uninstall()
    assert personal.read_bytes()==b'mine'
    assert engine.registry()['managed']=={}


def test_pause_and_cancel(engine):
    control=DownloadControl()
    control.running.clear()
    control.cancelled.set()
    with pytest.raises(SyncError,match='cancelled'):
        engine.update(engine.check(),control)
    assert engine.registry()['revision'] is None


def test_game_started_during_preparation_prevents_install(engine):
    plan=engine.check()
    running=False
    engine.running=lambda:running
    def phase(name,done,total):
        nonlocal running
        if name=='Preparing':running=True
    with pytest.raises(SyncError,match='Close Project Zomboid'):
        engine.update(plan,phase_progress=phase)
    assert engine.registry()['revision'] is None
    assert not engine.journal_path.exists()
    assert not (engine.mods/'Example/42/media/a.lua').exists()


def test_game_started_during_install_recovers_after_game_closes(engine):
    plan=engine.check()
    running=False
    engine.running=lambda:running
    def phase(name,done,total):
        nonlocal running
        if name=='Installing':running=True
    with pytest.raises(SyncError,match='Close Project Zomboid'):
        engine.update(plan,phase_progress=phase)
    assert engine.journal_path.exists()
    assert engine.registry()['revision'] is None
    running=False
    engine.recover()
    assert not engine.journal_path.exists()
    assert not (engine.mods/'Example/42/media/a.lua').exists()
