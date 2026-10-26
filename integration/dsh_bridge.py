"""Loopback DSH connection. Credentials stay in the project configuration files."""
from pathlib import Path
import asyncio
import hashlib
import json
import requests
import threading
from aiohttp import web, ClientSession, ClientTimeout, ClientError

ROOT = Path(__file__).resolve().parents[3]
BRIDGE = 'http://127.0.0.1:3092'
_media_clients = threading.local()


def enabled():
    path = ROOT / 'configs/dsh-enabled.json'
    return path.is_file() and json.loads(path.read_text(encoding='utf-8-sig')).get('enabled') is True


@web.middleware
async def require_accounted_media(request, handler):
    if enabled() and request.method == 'POST' and request.path in (
            '/human', '/humanaudio', '/set_audiotype', '/interrupt_talk', '/record'):
        return web.json_response({'error': 'DSH_LEGACY_ROUTE_DISABLED',
                                  'message': 'Use the studio/DSH request and playback controls.'}, status=409)
    return await handler(request)


def media_headers():
    return {}


def post_media(path, payload, timeout=3):
    # One connection pool per native worker thread: a durable media map is
    # submitted for each 40 ms packet, without opening 25 TCP connections/s.
    if not hasattr(_media_clients, 'session'):
        _media_clients.session = requests.Session()
        _media_clients.session.trust_env = False
    with _media_clients.session.post(BRIDGE + '/internal/' + path, headers=media_headers(), json=payload, timeout=(1, timeout)) as result:
        result.raise_for_status()
        return result.json()


async def async_media(path, payload):
    return await asyncio.to_thread(post_media, path, payload)


async def proxy(request, path=None):
    path = path or '/api/dsh/' + request.match_info.get('tail', '')
    if not path.startswith('/api/dsh/'):
        raise web.HTTPNotFound()
    headers = {key: request.headers[key] for key in ('Content-Type', 'Last-Event-ID') if key in request.headers}
    if path == '/api/dsh/platforms/douyin/callback':
        for key in ('x-msg-type', 'x-nonce-str', 'x-roomid', 'x-timestamp', 'x-signature'):
            if key in request.headers:
                headers[key] = request.headers[key]
    target = BRIDGE + path + (('?' + request.query_string) if request.query_string else '')
    try:
        streaming = request.method == 'GET' and path == '/api/dsh/events'
        timeout = ClientTimeout(total=None, connect=3, sock_read=45) if streaming else ClientTimeout(total=100)
        async with ClientSession(timeout=timeout, trust_env=False) as client:
            async with client.request(request.method, target, data=await request.read(), headers=headers) as result:
                extra = {'Cache-Control': 'no-store', 'Content-Type': result.headers.get('Content-Type', 'application/json')}
                if streaming and result.status == 200 and result.headers.get('Content-Type', '').startswith('text/event-stream'):
                    response = web.StreamResponse(status=result.status, headers={**extra, 'X-Accel-Buffering': 'no'})
                    await response.prepare(request)
                    try:
                        async for chunk in result.content.iter_any():
                            await response.write(chunk)
                    except (asyncio.TimeoutError, OSError, ClientError):
                        pass
                    return response
                return web.Response(body=await result.read(), status=result.status, headers=extra)
    except (asyncio.TimeoutError, OSError, ClientError):
        return web.json_response({'error': 'DSH_BRIDGE_UNAVAILABLE'}, status=503)


async def avatar_command(request):
    from server.session_manager import session_manager
    data = await request.json()
    avatar = session_manager.get_session('studio')
    if avatar is None:
        raise web.HTTPServiceUnavailable(text='AVATAR_NOT_CONNECTED')
    action = request.match_info['action']
    broadcast = request.app['rtc_manager'].broadcast
    current = (int(getattr(avatar, '_dsh_runtime_epoch', 0) or 0), int(getattr(avatar, '_studio_generation', 0) or 0))
    if action == 'speak':
        if not enabled():
            raise web.HTTPConflict(text='DSH_DISABLED')
        incoming = (int(data['runtime_epoch']), int(data['generation']))
        command = (data['request_id'], data['utterance_id'], hashlib.sha256(data['text'].encode('utf-8')).hexdigest())
        if incoming < current:
            raise web.HTTPConflict(text='STALE_GENERATION')
        if incoming == current:
            if getattr(avatar, '_dsh_speech_command', None) == command:
                return web.json_response({'accepted': True, 'duplicate': True})
            raise web.HTTPConflict(text='GENERATION_COMMAND_CONFLICT')
        # A higher generation also clears orphaned audio if the previous cancel
        # response was lost. This fence has no receipt/ACK authority of its own.
        avatar.flush_talk()
        avatar._dsh_runtime_epoch, avatar._studio_generation = incoming
        avatar._dsh_speech_command = command
        if broadcast:
            broadcast.cancel({'request_id': None, 'runtime_epoch': incoming[0],
                              'new_generation': incoming[1], 'reason': 'generation_advanced'})
        info = {key: data[key] for key in ('request_id', 'utterance_id', 'runtime_epoch', 'generation')}
        info['dsh'] = True
        avatar.put_msg_txt(data['text'], info)
    elif action == 'cancel':
        incoming = (int(data['runtime_epoch']), int(data['new_generation']))
        if incoming <= current:
            return web.json_response({'accepted': False, 'reason': 'stale_or_duplicate_fence'})
        avatar._dsh_runtime_epoch, avatar._studio_generation = incoming
        avatar.flush_talk()
        if broadcast:
            broadcast.cancel(data)
    else:
        raise web.HTTPNotFound()
    return web.json_response({'accepted': True})


async def memory_page(_request):
    return web.FileResponse(ROOT / 'web/memory.html')


async def platforms_page(_request):
    return web.FileResponse(ROOT / 'web/platforms.html')

async def output_page(_request):
    return web.FileResponse(ROOT / 'integration/obs.html')


async def obs_session(request):
    return web.json_response(await async_media('obs-session', {}), headers={'Cache-Control': 'no-store'})


async def evidence_file(request):
    base = (ROOT / 'outputs/dsh-humanity/public').resolve()
    path = (base / request.match_info['path']).resolve()
    if not path.is_relative_to(base) or not path.is_file() or path.suffix.lower() not in ('.mp4', '.webm', '.gif', '.png', '.jpg', '.json', '.html'):
        raise web.HTTPNotFound()
    return web.FileResponse(path)


def configure(app):
    app.middlewares.append(require_accounted_media)
    app.router.add_post('/api/dsh/obs/session', obs_session)
    app.router.add_get('/api/dsh/{tail:.*}', proxy)
    app.router.add_post('/api/dsh/{tail:.*}', proxy)
    app.router.add_post('/internal/dsh/{action}', avatar_command)
    app.router.add_get('/memory', memory_page)
    app.router.add_get('/platforms', platforms_page)
    app.router.add_get('/output.html', output_page)
    app.router.add_get('/dsh-evidence/{path:.*}', evidence_file)
