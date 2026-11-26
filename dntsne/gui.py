import asyncio
import logging
import os
import time
from pathlib import Path
import flet as ft
from .common import SyncError, atomic_json
from .game import find_games, launch, require_compatibility, default_mods
from .network import Network, DownloadControl
from .state import default_home, read_json, setup_log
from .profile import import_preferences
from .sync import Sync

ACCENT='#69E6CF'
LOG=logging.getLogger(__name__)


def mb(size):
    return f'{size/1024/1024:.1f} MB'


async def main(page:ft.Page):
    home=default_home()
    setup_log(home)
    config=read_json(home/'settings.json',{})
    games=await asyncio.to_thread(find_games)
    for key,value in dict(game=str(games[0]) if games else '',mods=str(default_mods()),
            server='',auto_check=False,rate_limit=0).items():
        config.setdefault(key,value)
    # Version-independent state; unpacking a new release never resets it.
    atomic_json(home/'settings.json',config)
    page.title='Loadout ModSync'
    page.window.width=920
    page.window.height=520
    page.window.min_width=800
    page.window.min_height=460
    page.theme_mode=ft.ThemeMode.DARK
    page.theme=ft.Theme(color_scheme_seed=ACCENT)
    page.bgcolor='#111919'
    page.padding=20
    state=ft.Text('Server · not checked',color=ACCENT,size=14)
    build=ft.Text('Build — / Revision —',size=12,color='#9BAEAB')
    counts=ft.Text('Synchronize to check the server',size=12)
    detail=ft.Text('Local status · not checked',size=12,max_lines=3)
    overall=ft.ProgressBar(value=0,color=ACCENT,bgcolor='#233331',height=5)
    current=ft.ProgressBar(value=0,color='#9BAEAB',bgcolor='#233331',height=3)
    speed=ft.Text('',size=11,color='#9BAEAB')
    last=ft.Text('Your settings and mods persist across launcher updates',size=10,color='#9BAEAB')
    sync_btn=ft.Button('Synchronize',bgcolor=ACCENT,color='#102421')
    pause_btn=ft.TextButton('Pause',disabled=True)
    launch_btn=ft.Button('Launch Project Zomboid',disabled=True,width=440)
    settings_btn=ft.TextButton('Settings')
    logs_btn=ft.TextButton('Open log file')
    log_list=ft.ListView(expand=True,spacing=4,auto_scroll=True)
    loop=asyncio.get_running_loop()
    alive=True
    busy=False
    ready=None
    engine=None
    control=DownloadControl()

    def add_logs(messages):
        if not alive:
            return
        log_list.controls.extend(ft.Text(message,size=11,font_family='Consolas',selectable=True) for message in messages)
        if len(log_list.controls)>200:
            del log_list.controls[:-200]
        page.update()

    def add_log(message):
        add_logs([message])

    async def watch_game(child,path,offset):
        while alive:
            if path.exists():
                size=path.stat().st_size
                with path.open('rb') as stream:
                    stream.seek(max(0,size-32768) if size-offset>32768 else offset)
                    block=stream.read(32768)
                    offset=stream.tell()
                if block:
                    add_logs(['PZ '+line for line in block.decode('utf-8',errors='replace').splitlines()[-40:]])
            if child.poll() is not None:
                LOG.info('Game process finished (exit %s)',child.returncode)
                return
            await asyncio.sleep(1)

    class PanelHandler(logging.Handler):
        def emit(self,record):
            if alive:
                loop.call_soon_threadsafe(add_log,self.format(record))
    panel_handler=PanelHandler()
    panel_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s',datefmt='%H:%M:%S'))
    logging.getLogger('dntsne').addHandler(panel_handler)

    def set_busy(value,pausable=False):
        nonlocal busy
        busy=value
        sync_btn.disabled=value
        settings_btn.disabled=value
        launch_btn.disabled=value or ready is None
        pause_btn.disabled=not pausable
        if not value:
            pause_btn.content='Pause'
            speed.value=''
        page.update()

    def make_engine():
        if not config['server']:
            raise SyncError('Enter the ModSync server URL in Settings')
        if not config['game'] or not config['mods']:
            raise SyncError('Choose the game and mod folders in Settings')
        return Sync(Network(config['server'],rate_limit=config['rate_limit']),Path(config['mods']),home)

    def show_receipt(receipt):
        build.value=f"Build {receipt['pz_version']} / Revision {receipt['revision'][:12]}"
        counts.value=f"{receipt['folders']} folders · {receipt['files']:,} files"

    def error(exc):
        nonlocal ready
        ready=None
        detail.value=str(exc) if isinstance(exc,(SyncError,OSError)) else 'Operation failed. See the log panel.'
        LOG.error('%s',detail.value)
        overall.value=0
        page.update()

    async def confirm_conflicts(plan):
        if not plan.conflicts:
            return True
        result=loop.create_future()
        def answer(value):
            page.pop_dialog()
            if not result.done():result.set_result(value)
        shown=plan.conflicts[:100]
        dialog=ft.AlertDialog(modal=True,title=ft.Text('Personal or modified files'),
            content=ft.Column([ft.Text(f'{len(plan.conflicts):,} files will be backed up before replacement.'),
                ft.Text('\n'.join(shown),size=11,selectable=True)],height=220,width=400,scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton('Cancel',on_click=lambda e:answer(False)),
                ft.TextButton('Back up and replace',on_click=lambda e:answer(True))])
        page.show_dialog(dialog)
        return await result

    async def synchronize(event=None,full=False):
        nonlocal control,engine,ready
        if busy:return
        control=DownloadControl()
        ready=None
        set_busy(True,True)
        detail.value='Checking server revision…'
        overall.value=None
        page.update()
        try:
            engine=make_engine()
            LOG.info('Checking server revision')
            status=await asyncio.to_thread(engine.network.status)
            state.value='Server · '+status['state']
            if status['state']!='ready':raise SyncError('Game server: '+status['state'])
            receipt=await asyncio.to_thread(engine.ready_receipt)
            if not full and receipt and receipt['revision']==status.get('revision'):
                ready=receipt
                show_receipt(ready)
                detail.value='Synchronized · same revision, file scan skipped'
                overall.value=1
                LOG.info('Server revision unchanged; no file scan or download needed')
                return
            # Fail fast before the expensive filesystem scan on a mismatched game.
            if status.get('pz_version'):
                await asyncio.to_thread(require_compatibility,Path(config['game']),status['pz_version'])
            LOG.info('Full verification requested' if full else 'Revision changed or installation incomplete; checking mod differences')
            def scanned(done,total):
                def draw():
                    if not busy:return
                    detail.value=f'Checking files · {done:,} / {total:,}'
                    overall.value=done/max(1,total)
                    page.update()
                loop.call_soon_threadsafe(draw)
            plan=await asyncio.to_thread(engine.check,scan_progress=scanned,full_check=full,control=control)
            await asyncio.to_thread(require_compatibility,Path(config['game']),plan.manifest.pz_version)
            show_receipt(dict(revision=plan.manifest.revision,pz_version=plan.manifest.pz_version,
                folders=len(plan.manifest.folders),files=len(plan.manifest.files)))
            LOG.info('Need to download %s files (%s), remove %s files',len(plan.changed),mb(plan.download_size),len(plan.removed))
            if not await confirm_conflicts(plan):
                detail.value='Cancelled · personal files preserved'
                LOG.info('Synchronization cancelled before replacement')
                return
            transfer=0
            last_draw=0.0
            last_phase=None
            started=None
            def paint(path,offset,size,delta):
                nonlocal transfer,last_draw,last_phase,started
                now=time.monotonic()
                if started is None:
                    started=now
                transfer+=max(0,delta)
                if last_phase!='Downloading':
                    last_phase='Downloading'
                    LOG.info('Downloading changed files')
                if now-last_draw<.15:return
                last_draw=now
                done=transfer
                rate=done/max(.1,now-started)
                def draw():
                    if not busy:return
                    detail.value=f'Downloaded {mb(done)} · {path}'
                    # Resumes and identical blobs can skip transfers, so an
                    # exact byte total is not known from the install plan.
                    overall.value=None
                    current.value=offset/max(1,size)
                    if control.running.is_set():speed.value=f'{mb(rate)}/s'
                    page.update()
                loop.call_soon_threadsafe(draw)
            def phase(name,done,total):
                nonlocal last_phase
                if last_phase!=name:
                    last_phase=name
                    LOG.info('%s (%s files)',name,total)
                def draw():
                    if not busy:return
                    detail.value=f'{name} · {done:,} / {total:,}'
                    overall.value=done/max(1,total)
                    if control.running.is_set():speed.value=''
                    page.update()
                loop.call_soon_threadsafe(draw)
            await asyncio.to_thread(engine.update,plan,control,paint,True,phase)
            ready=await asyncio.to_thread(engine.ready_receipt)
            if ready is None:raise SyncError('Synchronization did not produce a completed installation')
            detail.value='Synchronized · ready to launch'
            overall.value=1
            current.value=1
            LOG.info('Synchronization completed; ready to launch')
        except Exception as exc:
            error(exc)
        finally:
            set_busy(False)

    def pause(event):
        if control.running.is_set():
            control.running.clear()
            pause_btn.content='Resume'
            speed.value='Paused · Resume to continue'
            LOG.info('Paused')
        else:
            control.running.set()
            pause_btn.content='Pause'
            speed.value=''
            LOG.info('Resumed')
        page.update()

    async def launch_game(event):
        nonlocal ready
        if busy:return
        set_busy(True)
        try:
            if not engine or not ready:raise SyncError('Synchronize before launching')
            detail.value='Checking server revision before launch…'
            LOG.info('Launch: checking server revision only; no mod scan')
            await asyncio.to_thread(engine.network.require_revision,ready['revision'])
            current_receipt=await asyncio.to_thread(engine.ready_receipt)
            if current_receipt!=ready:raise SyncError('Installation state changed; synchronize again')
            await asyncio.to_thread(engine.require_stopped)
            detail.value='Preparing game preferences…'
            page.update()
            copied=await asyncio.to_thread(import_preferences,Path(config['mods']).parent)
            if copied:LOG.info('Imported %s game preference/server-list files; previous profile files backed up',len(copied))
            await asyncio.to_thread(require_compatibility,Path(config['game']),ready['pz_version'])
            detail.value='Starting Project Zomboid…'
            page.update()
            game_log=home/'game-console.log'
            offset=game_log.stat().st_size if game_log.exists() else 0
            child=await asyncio.to_thread(launch,Path(config['game']),Path(config['mods']),log_path=game_log)
            if child is not None:
                asyncio.create_task(watch_game(child,game_log,offset))
            detail.value='Game process started · waiting for the game window'
            LOG.info('Original installed Project Zomboid started with the dedicated mod profile')
        except Exception as exc:
            error(exc)
        finally:
            set_busy(False)

    def settings(event):
        game=ft.TextField(label='Game folder',value=config['game'],text_size=12)
        mods=ft.TextField(label='Mod folder',value=config['mods'],text_size=12)
        server=ft.TextField(label='Tailscale server URL',value=config['server'],text_size=12)
        rate=ft.TextField(label='Download limit (MB/s; 0 = unlimited)',value=str(config['rate_limit']/1024/1024),text_size=12)
        auto=ft.Checkbox(label='Synchronize automatically on startup',value=config['auto_check'])
        notice=ft.Text('',size=11,color=ACCENT)
        async def clear(event):
            try:
                await asyncio.to_thread(make_engine().clean_cache)
                notice.value='Temporary download cache cleared; installed state retained'
            except Exception as exc:notice.value=str(exc)
            page.update()
        async def full_check(event):
            page.pop_dialog()
            await synchronize(full=True)
        async def import_game(event):
            try:
                local_engine=make_engine()
                await asyncio.to_thread(local_engine.require_stopped)
                copied=await asyncio.to_thread(import_preferences,Path(config['mods']).parent,force=True)
                notice.value=f'Imported {len(copied)} preference/server-list files; backups preserved'
                LOG.info('%s',notice.value)
            except Exception as exc:notice.value=str(exc)
            page.update()
        def save(event):
            nonlocal ready,engine
            try:
                Network(server.value)
                limit=float(rate.value)
                if not 0<=limit<=10000:raise ValueError('Invalid download limit')
                changed=any(config[key]!=value for key,value in dict(game=game.value.strip(),mods=mods.value.strip(),server=server.value.strip()).items())
                config.update(game=game.value.strip(),mods=mods.value.strip(),server=server.value.strip(),rate_limit=int(limit*1024*1024),auto_check=auto.value)
                atomic_json(home/'settings.json',config)
                if changed:
                    ready=None
                    engine=None
                    launch_btn.disabled=True
                page.pop_dialog()
                detail.value='Settings saved'
                LOG.info('Settings saved in the persistent application data folder')
            except (SyncError,ValueError) as exc:notice.value=str(exc)
            page.update()
        page.show_dialog(ft.AlertDialog(modal=True,title=ft.Text('Settings'),content=ft.Column([
            game,mods,server,rate,auto,
            ft.Text('Same revision skips file scanning. Use Full verification if local files may be damaged.',size=11),
            ft.TextButton('Full verification (reads every file)',on_click=full_check),
            ft.TextButton('Import usual game settings and saved servers',on_click=import_game),
            ft.TextButton('Clear temporary download cache',on_click=clear),notice],width=430,height=390,scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton('Cancel',on_click=lambda e:page.pop_dialog()),ft.TextButton('Save',on_click=save)]))

    def logs(event):
        if os.name=='nt':os.startfile(str(home/'modsync.log'))

    async def disconnect(event):
        nonlocal alive
        alive=False
        control.cancelled.set()
        control.running.set()
        logging.getLogger('dntsne').removeHandler(panel_handler)
        panel_handler.close()
    page.on_disconnect=disconnect
    sync_btn.on_click=synchronize
    pause_btn.on_click=pause
    launch_btn.on_click=launch_game
    settings_btn.on_click=settings
    logs_btn.on_click=logs
    left=ft.Column([ft.Row([ft.Text('LOADOUT',weight=ft.FontWeight.W_700,size=21,color=ACCENT),ft.Text('/ MOD SYNC',size=12,color='#9BAEAB')]),
        ft.Divider(color='#233331'),state,build,counts,detail,overall,current,speed,
        ft.Row([sync_btn,pause_btn]),launch_btn,ft.Row([settings_btn,logs_btn]),last],width=450,spacing=12)
    right=ft.Container(content=ft.Column([ft.Text('Live log',color=ACCENT,size=15),log_list],expand=True),
        expand=True,padding=12,bgcolor='#172222',border_radius=8)
    page.add(ft.Row([left,ft.VerticalDivider(color='#233331'),right],expand=True,vertical_alignment=ft.CrossAxisAlignment.STRETCH))
    try:
        if config['game'] and config['server']:
            engine=make_engine()
            ready=await asyncio.to_thread(engine.ready_receipt)
            if ready:
                show_receipt(ready)
                detail.value='Last synchronized build restored · server checked before launch'
                launch_btn.disabled=False
                LOG.info('Restored the last synchronized build; no mod scan')
    except Exception as exc:
        LOG.warning('Could not restore installed state: %s',exc)
    LOG.info('Persistent launcher data: %s',home)
    page.update()
    if config['auto_check']:await synchronize()


def run(smoke_report=None):
    if not smoke_report:
        ft.run(main)
        return
    async def smoke(page):
        errors=[]
        page.on_error=lambda event:errors.append(str(event.data))
        await main(page)
        await asyncio.sleep(1)
        atomic_json(Path(smoke_report),dict(result='failed' if errors else 'passed',errors=errors,width=page.window.width,height=page.window.height,controls=len(page.controls)))
        await page.window.close()
    ft.run(smoke,view=ft.AppView.FLET_APP_HIDDEN)
