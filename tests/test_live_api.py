import socket
import threading
import time
import uvicorn
import pytest
from dntsne.common import atomic_json
from dntsne.network import Network
from dntsne.server import create_app
from dntsne.sync import Sync


@pytest.mark.parametrize('iteration',range(3))
def test_real_client_against_real_api(build,tmp_path,iteration):
    index,folder,e=build
    sock=socket.socket()
    sock.bind(('127.0.0.1',0))
    port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(create_app(index,False),log_level='critical',lifespan='on'))
    worker=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True)
    worker.start()
    deadline=time.monotonic()+10
    while not server.started and time.monotonic()<deadline:
        time.sleep(0.02)
    assert server.started
    try:
        net=Network(f'http://127.0.0.1:{port}')
        engine=Sync(net,tmp_path/'client/mods',tmp_path/'client/state',running=lambda:False)
        plan=engine.check()
        assert len(plan.changed)==3
        engine.update(plan)
        assert not engine.check().changed
        assert (engine.mods/'Example/42/media/java/plugin.jar').read_bytes()==b'jar-fixture'
        # A fresh game run with one changed Workshop file must not fetch
        # the other two files again, even though its revision changed.
        updated = b'new Lua file'
        (folder/'42/media/a.lua').write_bytes(updated)
        atomic_json(index.observation,dict(e,observed_at=time.time(),run_id='2'*64))
        index.tick()
        delta = engine.check()
        assert delta.manifest.revision != plan.manifest.revision
        assert [entry.path for entry in delta.changed] == ['Example/42/media/a.lua']
        assert delta.download_size == len(updated)
        received = []
        engine.update(delta,progress=lambda *args: received.append(args[-1]))
        assert sum(received) == len(updated)
        assert (engine.mods/'Example/42/media/a.lua').read_bytes() == updated
        assert not engine.check().changed
        atomic_json(index.observation,dict(e,observed_at=time.time(),state='offline'))
        assert net.status()['state']=='offline'
    finally:
        server.should_exit=True
        worker.join(5)
        sock.close()
