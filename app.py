import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import sys
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from security import canonical_url

BASE = Path(__file__).resolve().parent
ROOT = Path(os.getenv('MEDIA_ROOT', '/tmp/framesave'))
TTL = 900
MAX_BYTES = 300 * 1024 * 1024
jobs, tickets = {}, {}
rates = defaultdict(deque)
queue = asyncio.Queue(maxsize=8)
info_slots = asyncio.Semaphore(2)
active_info = 0
salt = secrets.token_bytes(32)

def owner(request):
    return request.state.session

def client_ip(request):
    # Conservative IP rate limit; untrusted forwarding headers are never accepted.
    return hashlib.sha256(salt + (request.client.host if request.client else 'unknown').encode()).hexdigest()

def limit(request, bucket, count):
    now = time.monotonic()
    key = (client_ip(request), bucket)
    q = rates[key]
    while q and now-q[0] > 60: q.popleft()
    if len(q) >= count: raise HTTPException(429, 'Слишком много запросов. Повторите через минуту.')
    q.append(now)
    if len(rates) > 10000:
        for k in list(rates):
            if not rates[k] or now-rates[k][-1] > 60: rates.pop(k, None)

def cleanup(now=None):
    now = now or time.time()
    for key, job in list(jobs.items()):
        if job['status'] in ('ready','error') and now-job['finished'] > TTL and not job.get('readers'):
            shutil.rmtree(ROOT/key, ignore_errors=True)
            jobs.pop(key,None)
    for key, t in list(tickets.items()):
        if now-t['created'] > TTL: tickets.pop(key,None)

async def run_child(payload, folder, timeout, job=None):
    folder.mkdir(parents=True, exist_ok=True)
    req = folder/'request.json'
    req.write_text(json.dumps(payload))
    env = {k:v for k,v in os.environ.items() if k in ('PATH','LANG','SSL_CERT_FILE')}
    proc = await asyncio.create_subprocess_exec(sys.executable, str(BASE/'worker.py'), str(req),
        cwd=folder, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
    result = {}
    async def read():
        nonlocal result
        while line := await proc.stdout.readline():
            data = json.loads(line)
            if 'progress' in data:
                if job is not None: job['progress'] = data['progress']
            else: result = data
        await proc.wait()
    async def monitor():
        while True:
            await asyncio.sleep(.5)
            if sum(p.stat().st_size for p in folder.iterdir() if p.is_file()) > MAX_BYTES*3:
                raise ValueError('Превышен лимит диска для задачи.')
    reader = asyncio.create_task(read())
    watcher = asyncio.create_task(monitor())
    try:
        done, _ = await asyncio.wait([reader,watcher], timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if not done: raise TimeoutError('Время обработки истекло.')
        for task in done: task.result()
        if proc.returncode or 'error' in result:
            raise ValueError(result.get('error','Не удалось обработать видео.'))
        return result
    finally:
        for t in (reader,watcher):
            t.cancel()
            with suppress(asyncio.CancelledError): await t
        with suppress(ProcessLookupError): os.killpg(proc.pid, signal.SIGKILL)
        await proc.wait()
        req.unlink(missing_ok=True)

async def consumer():
    while True:
        key, payload = await queue.get()
        job = jobs[key]
        job['status'] = 'processing'
        try:
            result = await run_child(payload, ROOT/key, 300, job)
            path = ROOT/key/result['file']
            if path.name not in ('media.mp4','media.mp3') or not path.is_file(): raise ValueError('Файл не создан.')
            job.update(status='ready', progress=100, filename=path.name)
        except Exception as e:
            job.update(status='error', error=str(e) or 'Не удалось обработать видео.')
            shutil.rmtree(ROOT/key, ignore_errors=True)
        finally:
            job['finished'] = time.time()
            queue.task_done()

async def sweeper():
    while True:
        await asyncio.sleep(30)
        cleanup()

@asynccontextmanager
async def lifespan(app):
    ROOT.mkdir(parents=True, exist_ok=True)
    # Single replica, single Uvicorn worker. Never share this directory.
    for p in ROOT.iterdir():
        if p.is_dir(): shutil.rmtree(p)
    workers = [asyncio.create_task(consumer()) for _ in range(2)] + [asyncio.create_task(sweeper())]
    yield
    for t in workers: t.cancel()
    await asyncio.gather(*workers, return_exceptions=True)

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

@app.middleware('http')
async def headers(request, call_next):
    cookie = request.cookies.get('framesave_session', '')
    parts = cookie.split('.')
    valid = len(parts) == 2 and len(parts[0]) == 32 and hmac.compare_digest(
        parts[1], hmac.new(salt, parts[0].encode(), hashlib.sha256).hexdigest())
    session = parts[0] if valid else secrets.token_hex(16)
    request.state.session = session
    if request.method == 'POST':
        # Bound streamed bodies too, rather than trusting Content-Length.
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > 4096: return JSONResponse({'detail':'Запрос слишком большой.'},413)
        request._body = bytes(body)
        origin = request.headers.get('origin')
        if origin:
            from urllib.parse import urlsplit
            if urlsplit(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail':'Недопустимый источник запроса.'},403)
    response = await call_next(request)
    if not valid:
        signature = hmac.new(salt, session.encode(), hashlib.sha256).hexdigest()
        response.set_cookie('framesave_session', session+'.'+signature, httponly=True,
            secure=bool(os.getenv('RENDER')), samesite='strict', max_age=3600)
    response.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
        'X-Frame-Options':'DENY','Cache-Control':'no-store',
        'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
    return response

class Info(BaseModel):
    url: str = Field(max_length=2048)
    rights: bool

class Download(BaseModel):
    ticket: str = Field(max_length=64)
    index: int = Field(ge=0, le=19)
    format: str = Field(max_length=30)

@app.get('/health')
async def health(): return {'status':'ok'}

@app.post('/api/info')
async def info(body: Info, request: Request):
    global active_info
    limit(request,'info',6)
    if not body.rights: raise HTTPException(400,'Подтвердите право на скачивание.')
    try: url = canonical_url(body.url.strip())
    except ValueError as e: raise HTTPException(400,str(e))
    cleanup()
    if active_info >= 2 or len(tickets) >= 300: raise HTTPException(503,'Сервис занят. Повторите немного позже.')
    active_info += 1
    folder = ROOT/('info-'+secrets.token_hex(16))
    try:
        async with info_slots: result = await run_child({'mode':'info','url':url},folder,45)
    except Exception as e:
        raise HTTPException(422,str(e) or 'Платформа не ответила.')
    finally:
        active_info -= 1
        shutil.rmtree(folder,ignore_errors=True)
    key = secrets.token_urlsafe(24)
    tickets[key] = dict(created=time.time(), owner=owner(request), url=url, items=result['items'])
    return dict(ticket=key, platform='YouTube' if 'youtube.com' in url else 'Instagram', **result)

@app.post('/api/download',status_code=202)
async def download(body: Download,request: Request):
    limit(request,'download',3)
    cleanup()
    t = tickets.get(body.ticket)
    if not t or t['owner'] != owner(request): raise HTTPException(410,'Результат устарел. Найдите видео снова.')
    if not any(i['index']==body.index and any(f['id']==body.format for f in i['formats']) for i in t['items']):
        raise HTTPException(400,'Недоступный формат.')
    if sum(j['owner']==owner(request) and j['status'] in ('queued','processing') for j in jobs.values()) >= 2:
        raise HTTPException(429,'Дождитесь завершения текущих загрузок.')
    if queue.full() or len(jobs) >= 24: raise HTTPException(503,'Очередь заполнена. Повторите позже.')
    key = secrets.token_urlsafe(24)
    jobs[key] = dict(status='queued',progress=0,owner=owner(request),finished=0)
    queue.put_nowait((key,dict(mode='download',url=t['url'],index=body.index,format=body.format)))
    return {'id':key}

def get_job(key, request):
    limit(request,'status',120)
    cleanup()
    job = jobs.get(key)
    if not job or job['owner'] != owner(request): raise HTTPException(404,'Файл не найден или срок хранения истёк.')
    return job

@app.get('/api/status/{key}')
async def status(key: str, request: Request):
    job = get_job(key,request)
    return {k:job[k] for k in ('status','progress','error') if k in job}

@app.get('/api/file/{key}')
async def file(key: str,request: Request):
    job = get_job(key,request)
    limit(request,'file',6)
    if job['status'] != 'ready': raise HTTPException(409,'Файл ещё не готов.')
    from starlette.background import BackgroundTask
    job['readers'] = job.get('readers',0)+1
    def release(): job['readers'] -= 1
    ext = Path(job['filename']).suffix
    return FileResponse(ROOT/key/job['filename'],filename='FrameSave-'+key[:8]+ext,
        media_type='audio/mpeg' if ext=='.mp3' else 'video/mp4',background=BackgroundTask(release))

app.mount('/', StaticFiles(directory=BASE/'static',html=True),name='frontend')
