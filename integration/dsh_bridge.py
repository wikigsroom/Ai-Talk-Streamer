"""Loopback DSH connection. Credentials stay in the project configuration files."""
from pathlib import Path
import asyncio
import hashlib
import json
import re
import requests
import threading
from urllib.parse import urlsplit
from yarl import URL
from aiohttp import web, ClientSession, ClientTimeout, ClientError, WSMsgType

_SOURCE = Path(__file__).resolve()
ROOT = _SOURCE.parents[3] if _SOURCE.parent.name == 'server' else _SOURCE.parents[1]
BRIDGE = 'http://127.0.0.1:3092'
_media_clients = threading.local()
_frame_uploading = False
FRAME_MAX_BYTES = 4 * 1024 * 1024
FRAME_PATH = re.compile(r'/api/dsh/game/frames/[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')


async def game_frame_proxy(request, target):
    """Raw JPEG has a separate, bounded stream; never use the generic JSON body reader."""
    global _frame_uploading
    upload = request.method == 'POST'
    if request.method not in ('GET', 'POST'):
        raise web.HTTPMethodNotAllowed(request.method, ['GET', 'POST'])
    if upload:
        if request.headers.get('Content-Type') != 'image/jpeg' or 'Content-Encoding' in request.headers:
            return web.json_response({'error': 'GAME_FRAME_CONTENT_TYPE'}, status=415)
        if request.content_length is not None and not 0 < request.content_length <= FRAME_MAX_BYTES:
            result = web.json_response({'error': 'GAME_FRAME_TOO_LARGE'}, status=413); result.force_close(); return result
        if _frame_uploading:
            result = web.json_response({'error': 'GAME_FRAME_UPLOAD_BUSY'}, status=429); result.force_close(); return result
        _frame_uploading = True
    failure = None

    async def bounded_body():
        nonlocal failure
        size = 0
        async for chunk in request.content.iter_chunked(65536):
            size += len(chunk)
            if size > FRAME_MAX_BYTES:
                failure = 'GAME_FRAME_TOO_LARGE'
                raise ValueError(failure)
            yield chunk

    keys = ('Content-Type', 'Content-Length', 'X-MC-Operation-Id', 'X-MC-Bridge-Boot-Id',
            'X-MC-World-Session-Id', 'X-MC-Seq', 'X-MC-Captured-At', 'X-MC-Width', 'X-MC-Height')
    headers = {key: request.headers[key] for key in keys if key in request.headers}
    try:
        async with asyncio.timeout(6):
            async with ClientSession(timeout=ClientTimeout(total=6), trust_env=False, auto_decompress=False) as client:
                async with client.request(request.method, target, data=bounded_body() if upload else None,
                                          headers=headers, allow_redirects=False) as upstream:
                    chunks = []; size = 0
                    async for chunk in upstream.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > FRAME_MAX_BYTES:
                            failure = 'GAME_FRAME_RESPONSE_TOO_LARGE'; raise ValueError(failure)
                        chunks.append(chunk)
                    result = web.Response(body=b''.join(chunks), status=upstream.status, headers={
                        'Content-Type': upstream.headers.get('Content-Type', 'application/json'),
                        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
                    if upload: result.force_close()
                    return result
    except (asyncio.TimeoutError, OSError, ClientError, ValueError):
        result = web.json_response({'error': failure or 'GAME_FRAME_UPSTREAM_UNAVAILABLE'},
                                   status=413 if failure == 'GAME_FRAME_TOO_LARGE' else 502)
        result.force_close(); return result
    finally:
        if upload: _frame_uploading = False


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
    if request.headers.get('Upgrade', '').lower() == 'websocket':
        if path != '/api/dsh/game/bridge':
            raise web.HTTPNotFound()
        return await game_websocket(request)
    headers = {key: request.headers[key] for key in ('Content-Type', 'Last-Event-ID', 'Range') if key in request.headers}
    if path == '/api/dsh/platforms/douyin/callback':
        for key in ('x-msg-type', 'x-nonce-str', 'x-roomid', 'x-timestamp', 'x-signature'):
            if key in request.headers:
                headers[key] = request.headers[key]
    target = BRIDGE + path + (('?' + request.query_string) if request.query_string else '')
    if FRAME_PATH.fullmatch(path):
        return await game_frame_proxy(request, target)
    try:
        streaming = request.method == 'GET' and path in ('/api/dsh/events', '/api/dsh/room/events', '/api/dsh/game/events')
        audio = path.startswith('/api/dsh/room/audio/')
        upload = path == '/api/dsh/room/tracks/upload'
        timeout = ClientTimeout(total=None, connect=3, sock_read=45) if streaming else ClientTimeout(total=300 if upload else 100)
        body = request.content.iter_chunked(256 * 1024) if upload else await request.read()
        async with ClientSession(timeout=timeout, trust_env=False) as client:
            async with client.request(request.method, target, data=body, headers=headers) as result:
                extra = {'Cache-Control': 'no-store', 'Content-Type': result.headers.get('Content-Type', 'application/json')}
                for key in ('Content-Range', 'Accept-Ranges', 'Content-Length'):
                    if key in result.headers:
                        extra[key] = result.headers[key]
                if audio or streaming and result.status == 200 and result.headers.get('Content-Type', '').startswith('text/event-stream'):
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


async def game_websocket(request):
    """Forward the bounded game protocol to the fixed local DSH host."""
    try:
        async with ClientSession(timeout=ClientTimeout(total=None, connect=3), trust_env=False) as client:
            async with client.ws_connect(BRIDGE + '/api/dsh/game/bridge', heartbeat=15,
                                         compress=0, max_msg_size=131072) as upstream:
                local = web.WebSocketResponse(heartbeat=15, compress=False, max_msg_size=131072)
                await local.prepare(request)

                async def forward(source, destination):
                    async for message in source:
                        if message.type == WSMsgType.TEXT:
                            await asyncio.wait_for(destination.send_str(message.data), 5)
                        elif message.type == WSMsgType.BINARY:
                            await destination.close(code=1003, message=b'game_text_protocol_only')
                            break
                        elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                            break

                tasks = [asyncio.create_task(forward(local, upstream)),
                         asyncio.create_task(forward(upstream, local))]
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await local.close()
                return local
    except (asyncio.TimeoutError, OSError, ClientError):
        return web.json_response({'error': 'GAME_BRIDGE_UNAVAILABLE'}, status=503)


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
        motion=getattr(avatar,'motion',None)
        if motion and hasattr(motion,'express'):
            motion.express(data.get('expression','attentive'))
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


async def admin_page(_request):
    return web.FileResponse(ROOT / 'web/admin.html')


async def mc_control_page(_request):
    return web.FileResponse(ROOT / 'web/mc-control.html')


async def mc_maintenance_page(request):
    return await mc_console_page(request, '/mc-maintenance')


async def mc_runtime_page(request):
    return await mc_console_page(request, '/mc-runtime')


async def mc_console_page(request, path):
    """Open the independent console directly so normal A shutdown keeps it usable."""
    try:
        value = json.loads((ROOT / 'configs/mc-maintenance-console.json').read_text(encoding='utf-8'))
        if (set(value) != {'schema_version', 'host', 'port'} or type(value['schema_version']) is not int
                or value['schema_version'] != 1 or value['host'] not in ('127.0.0.1', '0.0.0.0')
                or type(value['port']) is not int or not 1024 <= value['port'] <= 65535):
            raise ValueError('invalid console configuration')
        host = urlsplit('http://' + request.host).hostname
        target = URL.build(scheme='http', host=host, port=value['port'], path=path)
    except (OSError, ValueError, KeyError, TypeError):
        return web.json_response({'error': 'MC_MAINTENANCE_CONSOLE_CONFIG'}, status=503)
    raise web.HTTPTemporaryRedirect(location=str(target), headers={'Cache-Control': 'no-store'})


async def mc_programme_page(_request):
    return web.FileResponse(ROOT / 'web/mc-programme.html',headers={'Cache-Control':'no-store'})


async def mc_layout(_request):
    return web.FileResponse(ROOT / 'configs/layouts/mc-landscape-v1.json',headers={'Cache-Control':'no-store'})


async def mc_control_asset(request):
    name = request.match_info['name']
    if name not in ('css', 'js'):
        raise web.HTTPNotFound()
    return web.FileResponse(ROOT / f'web/mc-control.{name}')


async def mc_task_failures_asset(_request):
    return web.FileResponse(ROOT / 'web/mc-task-failures.js')


async def mc_player_safety_asset(_request):
    return web.FileResponse(ROOT / 'web/mc-player-safety.mjs',headers={'Content-Type':'text/javascript; charset=utf-8'})


async def overlay_page(_request):
    return web.FileResponse(ROOT / 'web/room-overlay.html')


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
    app.router.add_get('/admin', admin_page)
    app.router.add_get('/mc-control', mc_control_page)
    app.router.add_get('/mc-maintenance', mc_maintenance_page)
    app.router.add_get('/mc-runtime', mc_runtime_page)
    app.router.add_get('/mc/programme', mc_programme_page)
    app.router.add_get('/mc/preview', mc_programme_page)
    app.router.add_get('/mc/layout.json', mc_layout)
    app.router.add_get('/mc-control.{name:css|js}', mc_control_asset)
    app.router.add_get('/mc-task-failures.js', mc_task_failures_asset)
    app.router.add_get('/mc-player-safety.mjs', mc_player_safety_asset)
    app.router.add_get('/overlay', overlay_page)
    app.router.add_get('/dsh-evidence/{path:.*}', evidence_file)
