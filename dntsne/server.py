import asyncio
import logging
import os
import gzip
import json
import re
import queue
import tarfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from starlette.background import BackgroundTask
from .common import SyncError, fingerprint, secure_source_open, descriptor_fingerprint
from .server_index import Index


def range_bounds(value, size):
    if not value:
        return 0,size-1,200
    m = re.fullmatch(r'bytes=(\d*)-(\d*)',value)
    if not m or not any(m.groups()) or size==0:
        raise HTTPException(416,'Invalid range',headers={'Content-Range':f'bytes */{size}'})
    a,b=m.groups()
    start = int(a) if a else max(0,size-int(b))
    end = min(int(b),size-1) if a and b else size-1
    if start> end or start>=size or (not a and int(b)==0):
        raise HTTPException(416,'Unsatisfiable range',headers={'Content-Range':f'bytes */{size}'})
    return start,end,206


def create_app(index=None, background=True):
    index=index or Index(Path(os.getenv('DNTSNE_WORKSHOP','/workshop')),Path(os.getenv('DNTSNE_OBSERVATION','/observation/observation.json')),os.getenv('DNTSNE_LICENSES_APPROVED')=='1',Path(os.getenv('DNTSNE_PERSISTENCE','/state/current-index.json')))
    stop=threading.Event()
    slots=asyncio.Semaphore(int(os.getenv('DNTSNE_MAX_DOWNLOADS','3')))

    def watch():
        last_scan=0
        while not stop.is_set():
            scan=time.monotonic()-last_scan>15
            index.tick(scan)
            if scan:
                last_scan=time.monotonic()
            stop.wait(1)

    @asynccontextmanager
    async def lifespan(app):
        worker=None
        if background:
            worker=threading.Thread(target=watch,daemon=True)
            worker.start()
        yield
        stop.set()
        if worker:
            await asyncio.to_thread(worker.join,5)

    app=FastAPI(title='DNTSNE Mod Sync',version='1',lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.index=index

    @app.middleware('http')
    async def no_cache(request,call_next):
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.get('/api/v1/status')
    def status():
        try:
            m=index.require()
            return dict(state='ready',revision=m.revision,pz_version=m.pz_version,reason='',folders=len(m.folders),files=len(m.files),bundles=True)
        except SyncError:
            state=index.state if index.state!='ready' else 'offline'
            return dict(state=state,revision=None,pz_version=None,reason=index.reason or 'Current run unavailable')

    @app.get('/api/v1/manifest')
    def manifest(request: Request):
        try:
            data=index.require().to_dict()
        except SyncError:
            raise HTTPException(503,'Game build unavailable')
        # Avoid recursive FastAPI encoding and transferring a 30 MiB JSON body
        # for 174k files. Compression applies only to metadata, never Range.
        body=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()
        headers={'Vary':'Accept-Encoding'}
        if 'gzip' in request.headers.get('accept-encoding','').lower().split(','):
            body=gzip.compress(body,compresslevel=3,mtime=0)
            headers['Content-Encoding']='gzip'
        return Response(body,media_type='application/json',headers=headers)

    @app.get('/api/v1/files/{relative_path:path}')
    async def file(relative_path:str, revision:str, request:Request):
        try:
            await asyncio.wait_for(slots.acquire(),timeout=0.1)
        except TimeoutError:
            raise HTTPException(429,'Too many transfers',headers={'Retry-After':'2'})
        stream=None
        try:
            try:
                path,entry=await asyncio.to_thread(index.checked_file,relative_path,revision)
            except FileNotFoundError:
                raise HTTPException(404,'Unknown file')
            except SyncError:
                raise HTTPException(409,'Revision unavailable')
            if request.headers.get('if-range') not in (None,f'"{entry.sha256}"'):
                start,end,code=0,entry.size-1,200
            else:
                start,end,code=range_bounds(request.headers.get('range'),entry.size)
            stream=secure_source_open(index.workshop,path.relative_to(index.workshop).as_posix())
            if fingerprint(path)!=index.stamps[relative_path] or descriptor_fingerprint(stream)!=index.stamps[relative_path]:
                index.invalidate('Source changed before transfer')
                raise HTTPException(409,'Source changed')
            stream.seek(start)
        except BaseException:
            if stream:
                stream.close()
            slots.release()
            raise

        closed=False
        async def cleanup():
            nonlocal closed
            if not closed:
                closed=True
                stream.close()
                slots.release()

        async def chunks():
            remaining=max(0,end-start+1)
            try:
                while remaining:
                    index.require(revision)
                    if fingerprint(path)!=index.stamps[relative_path]:
                        index.invalidate('Source changed during transfer')
                        raise SyncError('Source changed during transfer')
                    chunk=await asyncio.to_thread(stream.read,min(256*1024,remaining))
                    if descriptor_fingerprint(stream)!=index.stamps[relative_path]:
                        index.invalidate('Source descriptor changed during transfer')
                        raise SyncError('Source changed during transfer')
                    if not chunk:
                        raise SyncError('Source truncated')
                    remaining-=len(chunk)
                    yield chunk
            finally:
                await cleanup()

        headers={'Accept-Ranges':'bytes','ETag':f'"{entry.sha256}"','X-DNTSNE-Revision':revision,'Content-Length':str(max(0,end-start+1))}
        if code==206:
            headers['Content-Range']=f'bytes {start}-{end}/{entry.size}'
        return StreamingResponse(chunks(),status_code=code,headers=headers,media_type='application/octet-stream',background=BackgroundTask(cleanup))

    @app.post('/api/v1/bundle')
    async def bundle(revision:str,request:Request):
        body_parts=[]
        length=0
        async for chunk in request.stream():
            length+=len(chunk)
            if length>2*1024*1024:
                raise HTTPException(413,'Bundle selection too large')
            body_parts.append(chunk)
        body=b''.join(body_parts)
        import json
        try:
            data=json.loads(body)
            if set(data)!={'paths'} or not isinstance(data['paths'],list):
                raise ValueError()
            paths=data['paths']
            if not 1<=len(paths)<=4096 or any(not isinstance(p,str) for p in paths) or len(set(paths))!=len(paths):
                raise ValueError()
            index.require(revision)
            if any(p not in index.entries for p in paths):
                raise HTTPException(404,'Unknown file')
        except (ValueError,TypeError):
            raise HTTPException(400,'Invalid bundle selection')
        except SyncError:
            raise HTTPException(409,'Revision unavailable')
        try:
            await asyncio.wait_for(slots.acquire(),timeout=0.1)
        except TimeoutError:
            raise HTTPException(429,'Too many transfers',headers={'Retry-After':'2'})
        chunks=queue.Queue(maxsize=8)
        aborted=threading.Event()
        closed=False

        class Writer:
            def write(self,value):
                for offset in range(0,len(value),256*1024):
                    while not aborted.is_set():
                        try:
                            chunks.put(value[offset:offset+256*1024],timeout=0.1)
                            break
                        except queue.Full:
                            pass
                    else:
                        raise OSError('Transfer closed')
                return len(value)

        class Guard:
            def __init__(self,stream,path,key):
                self.stream,self.path,self.key=stream,path,key
            def read(self,size):
                if aborted.is_set():
                    raise OSError('Transfer closed')
                index.require(revision)
                stamp=index.stamps[self.key]
                if fingerprint(self.path)!=stamp or descriptor_fingerprint(self.stream)!=stamp:
                    index.invalidate('Bundle source changed')
                    raise SyncError('Bundle source changed')
                value=self.stream.read(size)
                if descriptor_fingerprint(self.stream)!=stamp:
                    index.invalidate('Bundle source descriptor changed')
                    raise SyncError('Bundle source changed')
                return value

        def produce():
            try:
                with tarfile.open(fileobj=Writer(),mode='w|gz',copybufsize=256*1024) as archive:
                    for key in paths:
                        path,entry=index.checked_file(key,revision)
                        with secure_source_open(index.workshop,path.relative_to(index.workshop).as_posix()) as source:
                            info=tarfile.TarInfo(key)
                            info.size=entry.size
                            info.mode=0o644
                            archive.addfile(info,Guard(source,path,key))
                result=None
            except Exception as error:
                result=error
            while not aborted.is_set():
                try:
                    chunks.put(result,timeout=0.1)
                    break
                except queue.Full:
                    pass

        async def cleanup():
            nonlocal closed
            if not closed:
                closed=True
                aborted.set()
                slots.release()

        async def stream():
            worker=threading.Thread(target=produce,daemon=True)
            worker.start()
            try:
                while True:
                    try:
                        value=await asyncio.to_thread(chunks.get,True,0.2)
                    except queue.Empty:
                        continue
                    if value is None:
                        break
                    if isinstance(value,Exception):
                        raise SyncError('Bundle interrupted; verified files can be resumed')
                    yield value
            finally:
                await cleanup()

        return StreamingResponse(stream(),media_type='application/gzip',
                                 headers={'X-DNTSNE-Revision':revision},background=BackgroundTask(cleanup))
    return app


app=create_app()
