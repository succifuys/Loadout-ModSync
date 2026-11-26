import asyncio
import threading
from types import SimpleNamespace
import flet as ft
from dntsne import gui
from dntsne.common import SyncError


def walk(control):
    yield control
    for child in getattr(control,'controls',[]) or []:
        yield from walk(child)
    content=getattr(control,'content',None)
    if isinstance(content,ft.Control):yield from walk(content)


class Page:
    def __init__(self):self.window=SimpleNamespace();self.controls=[]
    def add(self,*controls):self.controls=list(controls)
    def update(self):pass
    def show_dialog(self,dialog):self.dialog=dialog
    def pop_dialog(self):self.dialog=None


def buttons(page):
    return {c.content:c for root in page.controls for c in walk(root) if isinstance(c,(ft.Button,ft.TextButton))}


def configure(monkeypatch,tmp_path):
    monkeypatch.setattr(gui,'default_home',lambda:tmp_path/'state')
    monkeypatch.setattr(gui,'default_mods',lambda:tmp_path/'profile/mods')
    monkeypatch.setattr(gui,'setup_log',lambda _:None)
    monkeypatch.setattr(gui,'read_json',lambda path,default:{'server':'http://127.0.0.1:8787'})
    monkeypatch.setattr(gui,'find_games',lambda:[tmp_path/'game'])
    monkeypatch.setattr(gui,'require_compatibility',lambda *args:None)
    monkeypatch.setattr(gui,'import_preferences',lambda *args,**kwargs:[])


def test_single_button_logs_and_advanced_full_check(tmp_path,monkeypatch):
    configure(monkeypatch,tmp_path)
    class Engine:
        def __init__(self,*args):pass
        def ready_receipt(self):return None
    monkeypatch.setattr(gui,'Sync',Engine)
    page=Page()
    async def run():
        await gui.main(page)
        assert page.window.width==920
        assert set(buttons(page))=={'Synchronize','Pause','Launch Project Zomboid','Settings','Open log file'}
        assert any(isinstance(c,ft.ListView) for root in page.controls for c in walk(root))
        buttons(page)['Settings'].on_click(None)
        assert any(isinstance(c,ft.TextButton) and c.content=='Full verification (reads every file)' for c in page.dialog.content.controls)
        await page.on_disconnect(None)
    asyncio.run(run())


def test_sync_pause_one_scan_launch_no_scan_restart_same_revision(tmp_path,monkeypatch):
    configure(monkeypatch,tmp_path)
    started=threading.Event()
    finish=threading.Event()
    receipt=dict(revision='a'*64,pz_version='42.21.0',folders=1,files=3)
    plan=SimpleNamespace(changed=[],removed=[],conflicts=[],download_size=0,
        manifest=SimpleNamespace(revision='a'*64,pz_version='42.21.0',folders=['Example'],files=[1,2,3]))
    engine=SimpleNamespace(check_calls=0,update_calls=0,ready=None,launches=0)
    class Network:
        def status(self):return dict(state='ready',revision='a'*64)
        def require_revision(self,revision):assert revision=='a'*64
    engine.network=Network()
    engine.ready_receipt=lambda:engine.ready
    engine.require_stopped=lambda:None
    def check(**kwargs):
        engine.check_calls+=1
        engine.control=kwargs['control']
        started.set()
        while not finish.wait(.01):engine.control.checkpoint()
        engine.control.checkpoint()
        return plan
    def update(*args):
        engine.update_calls+=1
        engine.ready=receipt
        return {'synced_at':'now'}
    engine.check=check
    engine.update=update
    monkeypatch.setattr(gui,'Sync',lambda *args:engine)
    def launched(*args,**kwargs):engine.launches+=1
    monkeypatch.setattr(gui,'launch',launched)
    async def run():
        page=Page()
        await gui.main(page)
        b=buttons(page)
        task=asyncio.create_task(b['Synchronize'].on_click(None))
        try:
            assert await asyncio.to_thread(started.wait,2)
            b['Pause'].on_click(None)
            assert b['Pause'].content=='Resume'
            finish.set()
            await asyncio.sleep(.15)
            assert not task.done()
            b['Pause'].on_click(None)
            await asyncio.wait_for(task,3)
            assert engine.check_calls==1 and engine.update_calls==1
            await b['Launch Project Zomboid'].on_click(None)
            assert engine.launches==1 and engine.check_calls==1
            await b['Synchronize'].on_click(None)
            assert engine.check_calls==1 and engine.update_calls==1
            await page.on_disconnect(None)
            reopened=Page()
            await gui.main(reopened)
            assert not buttons(reopened)['Launch Project Zomboid'].disabled
            assert any(isinstance(c,ft.Text) and 'Revision aaaaaaaaaaaa' in str(c.value) for root in reopened.controls for c in walk(root))
            await buttons(reopened)['Synchronize'].on_click(None)
            assert engine.check_calls==1
            def offline(revision):raise SyncError('Server stopped or changed build; check again')
            engine.network.require_revision=offline
            await buttons(reopened)['Launch Project Zomboid'].on_click(None)
            assert buttons(reopened)['Launch Project Zomboid'].disabled
            assert engine.launches==1
            await reopened.on_disconnect(None)
        finally:
            finish.set()
            if hasattr(engine,'control'):engine.control.running.set()
    asyncio.run(run())
