import json
import time
import pytest
from fastapi.testclient import TestClient
from dntsne.common import SyncError, atomic_json, safe_relative
from dntsne.manifest import Manifest, revision_for
from dntsne.server import create_app
from dntsne.server_index import Index


@pytest.mark.parametrize('value',['../x','/x','C:/x','a\\b','a//b','a/CON.txt','a/foo.','a/foo ','a:b','a/../b','a\x00b'])
def test_unsafe_paths(value):
    with pytest.raises(SyncError):
        safe_relative(value)


def test_manifest_hash_and_case_collision(build):
    index,_,_=build
    data=index.manifest.to_dict()
    data['files'].append(dict(data['files'][0],path=data['files'][0]['path'].upper()))
    data['revision']=revision_for(data)
    with pytest.raises(SyncError):
        Manifest.parse(data)
    data=index.manifest.to_dict()
    data['files'][0]['sha256']='f'*64
    with pytest.raises(SyncError):
        Manifest.parse(data)


def test_api_range_and_allowlist(build):
    index,_,_=build
    with TestClient(create_app(index,False)) as client:
        m=client.get('/api/v1/manifest').json()
        revision=m['revision']
        base='/api/v1/files/Example/42/media/a.lua'
        response=client.get(base,params={'revision':revision},headers={'Range':'bytes=2-'})
        assert response.status_code==206
        assert response.content==b'd lua'
        assert response.headers['content-range']=='bytes 2-6/7'
        assert response.headers['cache-control']=='no-store'
        assert client.get(base,params={'revision':revision},headers={'Range':'bytes=99-'}).status_code==416
        assert client.get(base,params={'revision':revision},headers={'Range':'bytes=-3'}).content==b'lua'
        assert client.get(base,params={'revision':revision},headers={'Range':'bytes=0-1,3-4'}).status_code==416
        assert client.get('/api/v1/files/unknown',params={'revision':revision}).status_code==404
        assert client.get(base,params={'revision':'f'*64}).status_code==409
        assert client.get(base,params={'revision':revision},headers={'If-Range':'"wrong"','Range':'bytes=2-'}).status_code==200


def test_source_change_disables_until_new_run(build):
    index,folder,e=build
    (folder/'42/media/a.lua').write_bytes(b'new lua')
    index.tick(scan=True)
    assert index.manifest is None
    index.tick()
    assert index.manifest is None
    atomic_json(index.observation,dict(e,observed_at=time.time(),run_id='2'*64))
    index.tick()
    assert index.require().run_id=='2'*64


def test_changes_before_first_publish_cannot_replace_startup_version(tmp_path):
    from dntsne.local_mods import prepare, MARKER
    from dntsne.common import digest
    workshop = tmp_path/'workshop'
    original = workshop/'content/108600/123/mods/Example/42'
    original.mkdir(parents=True)
    (original/'mod.info').write_text('id=Example\n')
    (original/'payload.txt').write_text('version A')
    prepare(workshop, ['123'], ['Example'])
    layer = workshop/'.dntsne-local-mods'
    observation = tmp_path/'observation.json'
    evidence = dict(observed_at=time.time(),state='ready',run_id='1'*64,
        pz_version='42.21.0',folders={'Example':'.dntsne-local-mods/Example'},
        active_mods=['Example'],maps=['Muldraugh, KY'],prepared_sha256=digest(layer/MARKER))
    atomic_json(observation,evidence)
    # Even before the API's first index, an in-place write must fail closed.
    (original/'payload.txt').write_text('version B')
    index=Index(workshop,observation,True)
    index.tick()
    assert index.manifest is None
    assert index.state == 'offline'
    with pytest.raises(SyncError):
        index.require()


def test_addition_and_stale_heartbeat(build):
    index,folder,e=build
    (folder/'new.txt').write_bytes(b'new')
    index.tick(scan=True)
    assert index.manifest is None
    atomic_json(index.observation,dict(e,observed_at=time.time()-10))
    with pytest.raises(SyncError):
        index.require()


def test_offline_and_restart_never_serve_old(build):
    index,_,e=build
    old=index.manifest.revision
    for state in ('offline','starting','updating'):
        atomic_json(index.observation,dict(e,observed_at=time.time(),state=state,run_id='2'*64))
        with TestClient(create_app(index,False)) as client:
            assert client.get('/api/v1/manifest').status_code==503
        index.tick()
        assert index.manifest is None
        assert index.state==state
    atomic_json(index.observation,dict(e,observed_at=time.time(),run_id='2'*64))
    index.tick()
    assert index.manifest.revision!=old


def test_license_gate(build):
    index,_,_=build
    unapproved=Index(index.workshop,index.observation,False)
    unapproved.tick()
    assert unapproved.manifest is None


def test_missing_active_id(build):
    index,_,e=build
    atomic_json(index.observation,dict(e,active_mods=['Missing']))
    index.invalidate('test',False)
    index.tick()
    assert index.manifest is None


def test_configuration_mutation(build):
    index,_,e=build
    atomic_json(index.observation,dict(e,maps=['other']))
    with pytest.raises(SyncError):
        index.require()
    index.tick()
    assert index.manifest is None


def test_same_run_manifest_survives_api_restart_and_rejects_change(build,tmp_path):
    index,folder,e=build
    state=tmp_path/'persist/index.json'
    original=Index(index.workshop,index.observation,True,state)
    original.tick()
    old=original.require().to_dict()
    restarted=Index(index.workshop,index.observation,True,state)
    restarted.tick()
    assert restarted.require().to_dict()==old
    (folder/'42/media/a.lua').write_bytes(b'changed while service down')
    changed=Index(index.workshop,index.observation,True,state)
    changed.tick()
    assert changed.manifest is None
    assert changed.tainted_run==e['run_id']
    again=Index(index.workshop,index.observation,True,state)
    again.tick()
    assert again.manifest is None

