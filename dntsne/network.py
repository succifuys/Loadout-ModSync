import hashlib
import http.client
import gzip
import ipaddress
import json
import socket
import threading
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from .common import SyncError, digest, is_link, safe_join
from .manifest import Manifest


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise SyncError('Server redirects are disabled')


class Network:
    def __init__(self, url: str, timeout=20, rate_limit=0):
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            raise SyncError('Use a plain HTTP(S) server origin without credentials')
        self.url=url.rstrip('/')
        self.host=parsed.hostname
        self.port=parsed.port or (443 if parsed.scheme=='https' else 80)
        self.timeout=timeout
        self.rate_limit=rate_limit
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def validate_peer(self):
        try:
            addresses=socket.getaddrinfo(self.host,self.port,type=socket.SOCK_STREAM)
        except OSError as e:
            raise SyncError('Server name unavailable. Check Tailscale and DNS.') from e
        for item in addresses:
            addr=ipaddress.ip_address(item[4][0])
            if not (addr.is_loopback or addr in ipaddress.ip_network('100.64.0.0/10') or addr in ipaddress.ip_network('fd7a:115c:a1e0::/48')):
                raise SyncError('Server must be inside the Tailscale network (or localhost for tests)')

    def open(self,path,headers=None,data=None):
        self.validate_peer()
        request_headers={'Accept-Encoding':'identity','User-Agent':'DNTSNE-ModSync/0.1'}
        request_headers.update(headers or {})
        req=urllib.request.Request(self.url+path,data=data,headers=request_headers)
        return self.opener.open(req,timeout=self.timeout)

    def json(self,path):
        try:
            with self.open(path,{'Accept-Encoding':'gzip'}) as response:
                coding=response.headers.get('Content-Encoding','identity').lower()
                if coding not in ('identity','gzip'):
                    raise SyncError('Unsupported server response encoding')
                stream=gzip.GzipFile(fileobj=response) if coding=='gzip' else response
                body=stream.read(64*1024*1024+1)
                if len(body)>64*1024*1024:
                    raise SyncError('Server response is too large')
                return json.loads(body)
        except (urllib.error.URLError,OSError,ValueError) as e:
            raise SyncError('Server unavailable or invalid response. Check Tailscale, address and game readiness.') from e

    def status(self):
        data=self.json('/api/v1/status')
        if not isinstance(data,dict) or data.get('state') not in ('offline','starting','updating','indexing','ready'):
            raise SyncError('Unsupported status response')
        self.bundle_supported=data.get('bundles') is True
        return data

    def manifest(self):
        state=self.status()
        if state['state']!='ready':
            raise SyncError('Game server: '+state['state'])
        m=Manifest.parse(self.json('/api/v1/manifest'))
        if state.get('revision')!=m.revision:
            raise SyncError('Build changed during check; check again')
        return m

    def require_revision(self,revision):
        state=self.status()
        if state['state']!='ready' or state.get('revision')!=revision:
            raise SyncError('Server stopped or changed build; check again')


class DownloadControl:
    def __init__(self):
        self.running=threading.Event()
        self.running.set()
        self.cancelled=threading.Event()

    def checkpoint(self):
        while not self.running.wait(0.1):
            if self.cancelled.is_set():
                raise SyncError('Operation cancelled; partial downloads retained')
        if self.cancelled.is_set():
            raise SyncError('Operation cancelled; partial downloads retained')


def download_many(network, entries, revision, cache, control, progress, cache_progress=None):
    """Bounded compressed batches avoid one TCP request per tiny mod file.

    Completed blobs survive a broken batch; partial blobs resume via normal Range.
    Nothing from an archive determines a filesystem destination.
    """
    pending={}
    unique={}
    for i,entry in enumerate(entries):
        if i%256==0:
            control.checkpoint()
        unique.setdefault(entry.sha256,entry)
    cache_dir=safe_join(cache,revision)
    cached={path.name.casefold() for path in cache_dir.iterdir()} if cache_dir.is_dir() else set()
    total=len(unique)
    if cache_progress:
        cache_progress(0,total)
    for i,entry in enumerate(unique.values(),1):
        if i%256==1 or i==total:
            control.checkpoint()
        if entry.sha256+'.part' in cached:
            part=safe_join(cache,revision+'/'+entry.sha256+'.part')
            if part.exists():
                size=part.stat().st_size
                if size==entry.size and digest(part,checkpoint=control.checkpoint)==entry.sha256:
                    pass
                elif size:
                    download(network,entry,revision,part,control,progress)
                else:
                    pending[entry.sha256]=entry
            else:
                pending[entry.sha256]=entry
        else:
            pending[entry.sha256]=entry
        if cache_progress and (i%1000==0 or i==total):
            cache_progress(i,total)
    values=list(pending.values())
    for start in range(0,len(values),4096):
        control.checkpoint()
        batch=values[start:start+4096]
        expected={entry.path:entry for entry in batch}
        body=json.dumps({'paths':list(expected)}).encode()
        received=set()
        try:
            with network.open('/api/v1/bundle?revision='+revision,
                              {'Content-Type':'application/json'},body) as response:
                if response.headers.get('X-DNTSNE-Revision')!=revision:
                    raise SyncError('Bundle belongs to another revision')
                with tarfile.open(fileobj=response,mode='r|gz') as archive:
                    for member in archive:
                        control.checkpoint()
                        if not member.isfile() or member.name not in expected or member.name in received:
                            raise SyncError('Unexpected bundle entry')
                        entry=expected[member.name]
                        if member.size!=entry.size:
                            raise SyncError('Bundle size differs from manifest')
                        part=safe_join(cache,revision+'/'+entry.sha256+'.part')
                        part.parent.mkdir(parents=True,exist_ok=True)
                        stream=archive.extractfile(member)
                        offset=0
                        sha=hashlib.sha256()
                        with part.open('wb') as target:
                            while offset<entry.size:
                                control.checkpoint()
                                began=time.monotonic()
                                chunk=stream.read(min(256*1024,entry.size-offset))
                                if not chunk:
                                    raise EOFError('Bundle entry truncated')
                                target.write(chunk)
                                sha.update(chunk)
                                offset+=len(chunk)
                                progress(entry.path,offset,entry.size,len(chunk))
                                if network.rate_limit>0:
                                    control.cancelled.wait(max(0,len(chunk)/network.rate_limit-(time.monotonic()-began)))
                        if sha.hexdigest()!=entry.sha256:
                            part.unlink(missing_ok=True)
                            raise SyncError('Bundle checksum mismatch')
                        received.add(member.name)
            if received!=set(expected):
                raise EOFError('Bundle incomplete')
        except (OSError,urllib.error.URLError,http.client.IncompleteRead,tarfile.TarError,EOFError):
            # Same manifest, same ownership rules. Individual Range retries also
            # recover older servers without the optional batch endpoint.
            network.require_revision(revision)
            for entry in batch:
                download(network,entry,revision,safe_join(cache,revision+'/'+entry.sha256+'.part'),control,progress)


def download(network, entry, revision, part:Path, control, progress=lambda *args:None):
    if is_link(part) or is_link(part.parent):
        raise SyncError('Unsafe download cache')
    part.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(4):
        control.checkpoint()
        offset=part.stat().st_size if part.exists() else 0
        if offset>entry.size:
            part.unlink()
            offset=0
        if offset==entry.size and part.exists():
            if digest(part,checkpoint=control.checkpoint)==entry.sha256:
                return
            part.unlink()
            offset=0
        headers={'If-Range':f'"{entry.sha256}"'}
        if offset:
            headers['Range']=f'bytes={offset}-'
        query='/api/v1/files/'+urllib.parse.quote(entry.path,safe='/')+'?revision='+revision
        try:
            with network.open(query,headers) as response:
                if response.headers.get('X-DNTSNE-Revision')!=revision or response.headers.get('ETag')!=f'"{entry.sha256}"':
                    raise SyncError('File belongs to a different build')
                if response.status==206:
                    if response.headers.get('Content-Range')!=f'bytes {offset}-{entry.size-1}/{entry.size}':
                        raise SyncError('Invalid resumed transfer')
                elif response.status==200:
                    offset=0
                else:
                    raise SyncError('Unexpected transfer response')
                if int(response.headers.get('Content-Length','-1'))!=entry.size-offset:
                    raise SyncError('Incorrect transfer length')
                with part.open('ab' if offset else 'wb') as f:
                    while offset<entry.size:
                        control.checkpoint()
                        started=time.monotonic()
                        chunk=response.read(min(256*1024,entry.size-offset))
                        if not chunk:
                            raise http.client.IncompleteRead(b'')
                        f.write(chunk)
                        offset+=len(chunk)
                        progress(entry.path,offset,entry.size,len(chunk))
                        if network.rate_limit>0:
                            delay=len(chunk)/network.rate_limit-(time.monotonic()-started)
                            if delay>0:
                                control.cancelled.wait(delay)
                    f.flush()
            if part.stat().st_size!=entry.size or digest(part,checkpoint=control.checkpoint)!=entry.sha256:
                part.unlink(missing_ok=True)
                raise SyncError('Downloaded checksum mismatch')
            return
        except urllib.error.HTTPError as e:
            if e.code not in (429,502,503,504) or attempt==3:
                raise SyncError(f'Transfer rejected by server ({e.code}); check again') from e
        except (urllib.error.URLError,TimeoutError,ConnectionError,http.client.IncompleteRead) as e:
            if attempt==3:
                raise SyncError('Connection lost; run Update to resume this revision') from e
        control.cancelled.wait(2**attempt)

