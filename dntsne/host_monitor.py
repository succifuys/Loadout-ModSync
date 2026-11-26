"""Privileged host-only observer; does not change containers or game files.

Only this small process needs Docker access. The web service receives a sanitized
heartbeat through a read-only mount, never a Docker socket or game INI secrets.
"""
import argparse
import hashlib
import json
import logging
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from .common import SyncError, atomic_json, safe_relative, digest, fingerprint

LOG = logging.getLogger(__name__)
WORKSHOP_CONTAINER = PurePosixPath('/root/.local/share/Steam/steamapps/workshop')


class Lifecycle:
    """Close the lease immediately on Docker kill/die/stop/pause events."""
    def __init__(self,output,container):
        self.output,self.container=output,container
        self.lock=threading.Lock()
        self.generation=0
        self.blocked=set()
        self.connected=False
        self.process=None

    def offline(self):
        atomic_json(self.output,dict(state='offline',run_id='',observed_at=time.time(),pz_version='',folders={},active_mods=[],maps=[]))

    def event(self,event):
        actor=event.get('Actor',{})
        if actor.get('Attributes',{}).get('name')!=self.container:
            return
        action=event.get('Action')
        identifier=actor.get('ID','')
        with self.lock:
            if action in ('kill','die','stop','pause','destroy'):
                self.generation+=1
                self.blocked.add(identifier)
                self.offline()
            elif action in ('start','restart','unpause'):
                self.generation+=1
                self.blocked.discard(identifier)
                self.offline()

    def watch(self):
        while True:
            try:
                self.process=subprocess.Popen(['docker','events','--filter','type=container','--format','{{json .}}'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
                with self.lock:
                    self.connected=True
                for line in self.process.stdout:
                    self.event(json.loads(line))
                self.process.wait()
            except Exception:
                LOG.error('Docker event subscription lost')
            finally:
                with self.lock:
                    self.connected=False
                    self.generation+=1
                    self.offline()
            time.sleep(3)


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.STDOUT, timeout=15)


def parse_ini(path):
    selected = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        key, sep, value = line.partition('=')
        if sep and key in ('Mods', 'Map', 'WorkshopItems'):
            if key in selected:
                raise SyncError('Duplicate INI setting')
            selected[key] = value.strip()
    if set(selected) != {'Mods','Map','WorkshopItems'} or selected['WorkshopItems']:
        raise SyncError('Local mode is not confirmed')
    return selected


def game_ports(pid):
    """Require sockets owned by the actual game process, not merely a live JVM."""
    process=Path('/proc')/str(int(pid))
    sockets=set()
    for descriptor in (process/'fd').iterdir():
        try:
            target=str(descriptor.readlink())
        except FileNotFoundError:
            continue
        match=re.fullmatch(r'socket:\[(\d+)\]',target)
        if match:
            sockets.add(match[1])
    ports=set()
    for name in ('udp','udp6'):
        path=process/'net'/name
        if path.exists():
            for row in path.read_text().splitlines()[1:]:
                fields=row.split()
                if len(fields)>9 and fields[9] in sockets:
                    ports.add(int(fields[1].split(':')[-1],16))
    return ports


def observe(root, container, cache):
    c = json.loads(docker('inspect', container))[0]
    labels = c['Config']['Labels'] or {}
    if labels.get('com.docker.compose.service') != 'pz' or labels.get('com.docker.compose.project') != 'pz':
        raise SyncError('Unexpected Compose identity')
    run_id = hashlib.sha256((c['Id'] + '/' + c['State']['StartedAt']).encode()).hexdigest()
    basic = dict(run_id=run_id, state='offline', pz_version='', folders={}, active_mods=[], maps=[])
    state = c['State']
    if not state['Running'] or state.get('Paused') or state.get('Restarting') or state.get('Dead'):
        return basic
    top = docker('top', container, '-eo', 'pid,comm')
    game_pids=[line.split()[0] for line in top.splitlines()[1:] if re.search(r'\b(java|ProjectZomboid\w*)\s*$',line)]
    game_alive=bool(game_pids)
    # Poll only NEW log lines after the first bounded startup scan, scoped by run.
    now = datetime.now(timezone.utc).isoformat()
    if cache.get('run_id') != run_id:
        cache.clear()
        cache.update(run_id=run_id, ready=False, updating=False, stopping=False, version='', since=state['StartedAt'])
    logs = docker('logs', '--timestamps', '--since', cache['since'], container)
    cache['since'] = now
    for line in logs.splitlines():
        if '*** SERVER STARTED ****' in line:
            cache['ready'] = True
            cache['updating'] = False
        if any(marker in line.lower() for marker in ('server is shutting down', 'server shutdown', 'server quit', 'saving before quit')):
            cache['stopping'] = True
        if 'Workshop management' in line or 'Downloading Workshop' in line:
            cache['updating'] = True
        match = re.search(r'version=(42\.\d+\.\d+)', line)
        if match:
            cache['version'] = match[1]
    if game_alive:
        cache['updating']=False  # Java/native game starts only after Workshop preparation.
    if cache['stopping'] or (cache['ready'] and not game_alive):
        return basic
    if cache['ready'] and not any(16261 in game_ports(pid) for pid in game_pids):
        cache['stopping']=True
        return basic
    basic['state'] = 'updating' if cache['updating'] else 'starting'
    if not cache['ready'] or not game_alive or not cache['version']:
        return basic
    mounts = {x['Destination']:Path(x['Source']).resolve() for x in c['Mounts'] if x['Type']=='bind'}
    runtime_cache = '/var/lib/dntsne/pz/Zomboid'
    if mounts.get(runtime_cache) != (root/'data').resolve() or mounts.get(str(WORKSHOP_CONTAINER)) != (root/'workshop').resolve():
        raise SyncError('Unexpected game mount mapping')
    ini = parse_ini(root/'data/Server/DNTSNE.ini')
    layer = root/'workshop/.dntsne-local-mods'
    layer_mount = next((m for m in c['Mounts'] if m['Destination']==runtime_cache+'/mods'),None)
    if not layer_mount or Path(layer_mount['Source']).resolve()!=layer.resolve() or layer_mount.get('RW',True):
        raise SyncError('Real local mod layer must be mounted read-only')
    state_path = root/'data/.dntsne-local-mods.json'
    marker = layer/'.dntsne-hardlink-owner.json'
    stamps = (fingerprint(state_path), fingerprint(marker))
    if cache.get('prepared_stamps') != stamps:
        prepared = json.loads(state_path.read_text())
        if prepared.get('format')!=1 or prepared!=json.loads(marker.read_text()):
            raise SyncError('Prepared layer does not match startup evidence')
        cache.update(prepared_stamps=stamps,prepared=prepared,prepared_sha=digest(marker))
    prepared = cache['prepared']
    links = prepared['folders']
    if not links or prepared['active_mods']!=[x.lstrip('\\') for x in ini['Mods'].split(';') if x]:
        raise SyncError('No prepared mod folders')
    folders = {}
    for name, target in links.items():
        if '/' in safe_relative(name):
            raise SyncError('Invalid folder name')
        rel = target
        safe_relative(rel)
        parts = rel.split('/')
        if len(parts)!=5 or parts[:2]!=['content','108600'] or not parts[2].isdigit() or parts[3]!='mods' or parts[4]!=name:
            raise SyncError('Unexpected prepared folder mapping')
        folder = layer/name
        if folder.is_symlink() or not folder.is_dir():
            raise SyncError('Prepared folder must be a real directory')
        folders[name] = '.dntsne-local-mods/'+name
    # Recheck after disk/log work; never bind evidence from one run to another.
    final = json.loads(docker('inspect',container))[0]
    if final['Id']!=c['Id'] or final['State']['StartedAt']!=state['StartedAt'] or not final['State']['Running']:
        return dict(basic,state='offline')
    return dict(basic, container_id=c['Id'],state='ready', pz_version=cache['version'], folders=folders,
                prepared_sha256=cache['prepared_sha'],
                active_mods=[x.lstrip('\\') for x in ini['Mods'].split(';') if x],
                maps=[x for x in ini['Map'].split(';') if x])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path('/srv/servers/pz'))
    p.add_argument('--output',type=Path,default=Path('/var/lib/dntsne-monitor/observation.json'))
    p.add_argument('--container',default='pz-server')
    p.add_argument('--once',action='store_true')
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    cache = {}
    lifecycle=Lifecycle(args.output,args.container)
    if not args.once:
        threading.Thread(target=lifecycle.watch,daemon=True).start()
    while True:
        with lifecycle.lock:
            generation=lifecycle.generation
        try:
            data = observe(args.root,args.container,cache)
        except Exception:
            LOG.error('Observation failed; serving disabled (details kept out of public API)')
            data = dict(state='offline',run_id='',pz_version='',folders={},active_mods=[],maps=[])
        with lifecycle.lock:
            if not args.once and (not lifecycle.connected or generation!=lifecycle.generation or data.get('container_id') in lifecycle.blocked):
                lifecycle.offline()
            else:
                data.pop('container_id',None)
                atomic_json(args.output,dict(data,observed_at=time.time()))
        if args.once:
            break
        time.sleep(1)


if __name__ == '__main__':
    main()

