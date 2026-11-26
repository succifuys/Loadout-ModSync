import hashlib
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from dntsne.common import SyncError
from dntsne.manifest import File
from dntsne.network import Network,DownloadControl,download


@pytest.fixture
def transfer_server():
    body=b'payload'*100000
    revision='a'*64
    checksum=hashlib.sha256(body).hexdigest()
    state=dict(offsets=[],drop_once=False,corrupt=False)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_GET(self):
            if self.path.startswith('/redirect'):
                self.send_response(302)
                self.send_header('Location','https://example.com')
                self.end_headers()
                return
            offset=int(self.headers.get('Range','bytes=0-').split('=')[1].split('-')[0])
            state['offsets'].append(offset)
            self.send_response(206 if offset else 200)
            self.send_header('Content-Length',str(len(body)-offset))
            self.send_header('X-DNTSNE-Revision',revision)
            self.send_header('ETag',f'"{checksum}"')
            if offset:
                self.send_header('Content-Range',f'bytes {offset}-{len(body)-1}/{len(body)}')
            self.end_headers()
            payload=body[offset:]
            if state['drop_once']:
                state['drop_once']=False
                self.wfile.write(payload[:300000])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
            else:
                self.wfile.write(b'x'*len(payload) if state['corrupt'] else payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        yield Network(f'http://127.0.0.1:{server.server_port}'),File('Example/42/a.bin',len(body),checksum),revision,state,body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_real_http_connection_loss_resumes(transfer_server,tmp_path):
    net,entry,revision,state,body=transfer_server
    state['drop_once']=True
    part=tmp_path/'part'
    download(net,entry,revision,part,DownloadControl())
    assert part.read_bytes()==body
    assert state['offsets'][0]==0
    assert any(offset>0 for offset in state['offsets'])


def test_real_http_preexisting_partial_and_cached_file(transfer_server,tmp_path):
    net,entry,revision,state,body=transfer_server
    part=tmp_path/'part'
    part.write_bytes(body[:12345])
    download(net,entry,revision,part,DownloadControl())
    assert state['offsets']==[12345]
    download(net,entry,revision,part,DownloadControl())
    assert state['offsets']==[12345]


def test_corrupted_download_is_not_accepted(transfer_server,tmp_path):
    net,entry,revision,state,body=transfer_server
    state['corrupt']=True
    with pytest.raises(SyncError,match='checksum'):
        download(net,entry,revision,tmp_path/'part',DownloadControl())
    assert not (tmp_path/'part').exists()


def test_paused_download_stays_paused_then_resumes(transfer_server,tmp_path):
    net,entry,revision,state,body=transfer_server
    control=DownloadControl()
    control.running.clear()
    errors=[]
    def work():
        try:
            download(net,entry,revision,tmp_path/'part',control)
        except Exception as e:
            errors.append(e)
    thread=threading.Thread(target=work)
    thread.start()
    thread.join(0.1)
    assert thread.is_alive() and not state['offsets']
    control.running.set()
    thread.join(5)
    assert not thread.is_alive() and not errors
    assert (tmp_path/'part').read_bytes()==body


def test_redirects_cannot_escape_tailnet(transfer_server):
    net,*_=transfer_server
    with pytest.raises(SyncError,match='redirect'):
        net.open('/redirect')


@pytest.mark.parametrize('url',['file:///etc/passwd','http://user:secret@127.0.0.1','https://host/path','http://host?token=x'])
def test_unsafe_origins_rejected(url):
    with pytest.raises(SyncError):
        Network(url)

