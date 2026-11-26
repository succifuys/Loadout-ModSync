import io
import tarfile
import pytest
from fastapi.testclient import TestClient
from dntsne.server import create_app


@pytest.mark.parametrize('name,kind',[('../../foreign',tarfile.REGTYPE),('Example/a.lua',tarfile.SYMTYPE)])
def test_client_rejects_archive_paths_and_links(tmp_path,name,kind):
    from dntsne.network import download_many,DownloadControl
    from dntsne.manifest import File
    from dntsne.common import SyncError
    import hashlib
    blob=io.BytesIO()
    with tarfile.open(fileobj=blob,mode='w:gz') as archive:
        member=tarfile.TarInfo(name)
        member.type=kind
        if kind==tarfile.REGTYPE:
            member.size=1
            archive.addfile(member,io.BytesIO(b'a'))
        else:
            member.linkname='../../foreign'
            archive.addfile(member)
    class Response(io.BytesIO):
        headers={'X-DNTSNE-Revision':'1'*64}
    class Fake:
        rate_limit=0
        def open(self,*args):return Response(blob.getvalue())
    entry=File('Example/a.lua',1,hashlib.sha256(b'a').hexdigest())
    with pytest.raises(SyncError,match='Unexpected bundle'):
        download_many(Fake(),[entry],'1'*64,tmp_path/'cache',DownloadControl(),lambda *args:None)
    assert not (tmp_path/'foreign').exists()
    assert not list(tmp_path.rglob('*.part'))


def test_bundle_contains_only_requested_regular_files(build):
    index,_,_=build
    revision=index.manifest.revision
    selected=[index.manifest.files[0].path,index.manifest.files[-1].path]
    with TestClient(create_app(index,False)) as client:
        response=client.post('/api/v1/bundle',params={'revision':revision},json={'paths':selected})
        assert response.status_code==200
        assert response.headers['x-dntsne-revision']==revision
        with tarfile.open(fileobj=io.BytesIO(response.content),mode='r:gz') as archive:
            assert archive.getnames()==selected
            for member in archive:
                assert member.isfile()
                assert archive.extractfile(member).read()==index.sources[member.name].read_bytes()
        assert client.post('/api/v1/bundle',params={'revision':revision},json={'paths':['../../.env']}).status_code==404
        assert client.post('/api/v1/bundle',params={'revision':'f'*64},json={'paths':selected}).status_code==409
        assert client.post('/api/v1/bundle',params={'revision':revision},json={'paths':selected*2}).status_code==400


def test_client_batches_against_real_server(build,tmp_path):
    import threading
    import socket
    import uvicorn
    import time
    from dntsne.network import Network,DownloadControl,download_many
    from dntsne.common import digest
    index,_,_=build
    listener=socket.socket()
    listener.bind(('127.0.0.1',0))
    port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(create_app(index,False),log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True)
    thread.start()
    try:
        while not server.started:
            time.sleep(0.01)
        network=Network(f'http://127.0.0.1:{port}')
        manifest=network.manifest()
        assert network.bundle_supported
        download_many(network,list(manifest.files),manifest.revision,tmp_path/'cache',DownloadControl(),lambda *args:None)
        for entry in manifest.files:
            assert digest(tmp_path/'cache'/manifest.revision/(entry.sha256+'.part'))==entry.sha256
    finally:
        server.should_exit=True
        thread.join(5)
        listener.close()
