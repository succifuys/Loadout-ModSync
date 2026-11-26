import time
from pathlib import Path
import pytest
from dntsne.common import atomic_json
from dntsne.server_index import Index


@pytest.fixture
def build(tmp_path):
    workshop=tmp_path/'workshop'
    folder=workshop/'content/108600/123/mods/Example'
    (folder/'common').mkdir(parents=True)
    (folder/'common/mod.info').write_text('id=Example\n',encoding='utf-8')
    (folder/'42/media/java').mkdir(parents=True)
    (folder/'42/media/java/plugin.jar').write_bytes(b'jar-fixture')
    (folder/'42/media/a.lua').write_bytes(b'old lua')
    observation=tmp_path/'observation.json'
    evidence=dict(observed_at=time.time(),state='ready',run_id='1'*64,pz_version='42.21.0',folders={'Example':'content/108600/123/mods/Example'},active_mods=['Example'],maps=['Muldraugh, KY'])
    atomic_json(observation,evidence)
    index=Index(workshop,observation,True)
    index.tick()
    assert index.manifest
    return index,folder,evidence

