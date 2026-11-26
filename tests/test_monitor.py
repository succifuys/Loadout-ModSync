import json
import time
from pathlib import Path,PurePosixPath
from dntsne.common import atomic_json
from dntsne.host_monitor import observe,Lifecycle


def test_readiness_scoped_to_run_and_native_process(tmp_path,monkeypatch):
    root=tmp_path
    (root/'data/Server').mkdir(parents=True)
    layer=root/'workshop/.dntsne-local-mods'
    (layer/'Example').mkdir(parents=True)
    (root/'data/Server/DNTSNE.ini').write_text('WorkshopItems=\nMods=Example\nMap=Muldraugh, KY\n')
    prepared={'format':1,'folders':{'Example':'content/108600/1/mods/Example'},'active_mods':['Example'],'files':{}}
    atomic_json(root/'data/.dntsne-local-mods.json',prepared)
    atomic_json(layer/'.dntsne-hardlink-owner.json',prepared)
    c=dict(Id='a'*64,State=dict(Running=True,StartedAt='2026-10-11T00:00:00Z'),Config=dict(Labels={'com.docker.compose.project':'pz','com.docker.compose.service':'pz'}),Mounts=[dict(Type='bind',Source=str(root/'data'),Destination='/var/lib/dntsne/pz/Zomboid'),dict(Type='bind',Source=str(root/'workshop'),Destination='/root/.local/share/Steam/steamapps/workshop'),dict(Type='bind',Source=str(layer),Destination='/var/lib/dntsne/pz/Zomboid/mods',RW=False)])
    logs='version=42.21.0\n*** SERVER STARTED ****'
    seen=[]
    def docker(*args):
        seen.append(args)
        if args[0]=='inspect':return json.dumps([c])
        if args[0]=='top':return 'PID COMMAND\n123 ProjectZomboid6\n'
        if args[0]=='logs':return logs
    monkeypatch.setattr('dntsne.host_monitor.docker',docker)
    monkeypatch.setattr('dntsne.host_monitor.game_ports',lambda pid:{16261,16262})
    cache={}
    first=observe(root,'pz-server',cache)
    assert first['state']=='ready'
    assert any(x[:3]==('logs','--timestamps','--since') and x[3]==c['State']['StartedAt'] for x in seen)
    c['State']['StartedAt']='2026-10-12T00:00:00Z'
    logs='version=42.21.0'
    second=observe(root,'pz-server',cache)
    assert second['state']=='starting'
    assert first['run_id']!=second['run_id']


def test_stop_event_immediately_closes_lease(tmp_path):
    output=tmp_path/'observation.json'
    lifecycle=Lifecycle(output,'pz-server')
    atomic_json(output,dict(state='ready'))
    lifecycle.event(dict(Action='kill',Actor=dict(ID='a'*64,Attributes={'name':'pz-server'})))
    assert json.loads(output.read_text())['state']=='offline'
    assert 'a'*64 in lifecycle.blocked
    lifecycle.event(dict(Action='start',Actor=dict(ID='a'*64,Attributes={'name':'pz-server'})))
    assert not lifecycle.blocked
    assert json.loads(output.read_text())['state']=='offline'

