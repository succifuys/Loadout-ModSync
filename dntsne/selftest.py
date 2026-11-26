"""Offline portable smoke test, no game files, tailnet, or Python install needed."""
import json
import tempfile
import time
from pathlib import Path
from .common import atomic_json
from .server_index import Index
from .manifest import Manifest


def main():
    with tempfile.TemporaryDirectory(prefix='dntsne-selftest-') as temporary:
        root=Path(temporary)
        source=root/'workshop/content/108600/1/mods/Example/common'
        source.mkdir(parents=True)
        fixture=b'id=Example\n'
        (source/'mod.info').write_bytes(fixture)
        evidence=root/'observation.json'
        atomic_json(evidence,dict(observed_at=time.time(),state='ready',run_id='1'*64,pz_version='42.21.0',folders={'Example':'content/108600/1/mods/Example'},active_mods=['Example'],maps=['Muldraugh, KY']))
        index=Index(root/'workshop',evidence,True)
        index.tick()
        manifest=Manifest.parse(index.require().to_dict())
        assert manifest.files[0].path=='Example/common/mod.info'
        assert manifest.total_size==len(fixture)
    result=dict(result='passed',protocol=1,version='0.1.3')
    if __import__('sys').stdout is not None:
        print(json.dumps(result))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
