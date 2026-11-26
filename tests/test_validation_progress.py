from pathlib import Path
import pytest
from test_sync import engine
from dntsne.common import SyncError
from dntsne.network import DownloadControl

def test_absent_mod_folder_is_batched_and_preflight_reports_progress(engine, monkeypatch):
    original=engine._local
    seen=[]
    def record(*args,**kw):
        seen.append(args[0])
        return original(*args,**kw)
    monkeypatch.setattr(engine,'_local',record)
    plan=engine.check()
    assert len(plan.changed)==3 and not seen
    events=[]
    engine._validate_plan(plan,DownloadControl(),lambda i,n:events.append((i,n)))
    assert events==[(0,3),(3,3)]
    assert not seen

def test_new_foreign_file_after_absent_folder_scan_is_preserved(engine):
    plan=engine.check()
    target=engine.mods/plan.changed[0].path
    target.parent.mkdir(parents=True)
    target.write_bytes(b'do not replace me')
    with pytest.raises(SyncError,match='Local installation changed'):
        engine.update(plan)
    assert target.read_bytes()==b'do not replace me'
    assert not engine.network.downloaded
