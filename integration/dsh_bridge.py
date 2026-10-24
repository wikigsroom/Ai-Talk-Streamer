"""Loopback DSH connection. Credentials stay in the project configuration files."""
from pathlib import Path
import asyncio
import hmac
import json
import requests
from aiohttp import web, ClientSession, ClientTimeout, ClientError

ROOT = Path(__file__).resolve().parents[3]
BRIDGE = 'http://127.0.0.1:3092'


def enabled():
    path = ROOT / 'configs/dsh-enabled.json'
    return path.is_file() and json.loads(path.read_text(encoding='utf-8-sig')).get('enabled') is True


@web.middleware
async def require_accounted_media(request, handler):
    if enabled() and request.method == 'POST' and request.path in (
            '/human', '/humanaudio', '/set_audiotype', '/interrupt_talk', '/record'):
        return web.json_response({'error': 'DSH_LEGACY_ROUTE_DISABLED',
                                  'message': 'Use the authenticated studio/DSH request and playback controls.'}, status=409)
    return await handler(request)


def media_headers():
    return {'Authorization': 'Bearer ' + (ROOT / 'configs/dsh-media.token').read_text(encoding='utf-8').strip()}


def post_media(path, payload, timeout=3):
    with requests.Session() as client:
        client.trust_env = False
        result = client.post(BRIDGE + '/internal/' + path, headers=media_headers(), json=payload, timeout=(1, timeout))
        result.raise_for_status()
        return result.json()


async def async_media(path, payload):
    return await asyncio.to_thread(post_media, path, payload)


async def proxy(request, path=None):
    origin = request.headers.get('Origin')
    if origin:
        from urllib.parse import urlsplit
        if urlsplit(origin).netloc != request.host:
            raise web.HTTPForbidden(text='ORIGIN_DENIED')
    path = path or '/api/dsh/' + request.match_info.get('tail', '')
    if not path.startswith('/api/dsh/'):
        raise web.HTTPForbidden()
    headers = {key: request.headers[key] for key in ('Cookie', 'Authorization', 'Content-Type', 'Origin') if key in request.headers}
    headers['X-Stream-Original-Host'] = request.host
    target = BRIDGE + path + (('?' + request.query_string) if request.query_string else '')
    try:
        async with ClientSession(timeout=ClientTimeout(total=100), trust_env=False) as client:
            async with client.request(request.method, target, data=await request.read(), headers=headers) as result:
                extra = {'Cache-Control': 'no-store', 'Content-Type': result.headers.get('Content-Type', 'application/json')}
                if 'Set-Cookie' in result.headers:
                    extra['Set-Cookie'] = result.headers['Set-Cookie']
                return web.Response(body=await result.read(), status=result.status, headers=extra)
    except (asyncio.TimeoutError, OSError, ClientError):
        return web.json_response({'error': 'DSH_BRIDGE_UNAVAILABLE'}, status=503)


async def require_operator(request):
    async with ClientSession(timeout=ClientTimeout(total=3), trust_env=False) as client:
        async with client.get(BRIDGE + '/api/dsh/whoami', headers={key: request.headers[key] for key in ('Cookie', 'Authorization') if key in request.headers}) as result:
            value = await result.json()
            if result.status != 200 or value.get('role') != 'operator':
                raise web.HTTPForbidden(text='请先在人格与记忆页面登录管理员。')


async def avatar_command(request):
    from server.session_manager import session_manager
    expected = media_headers()['Authorization']
    if request.remote not in ('127.0.0.1', '::1') or not hmac.compare_digest(request.headers.get('Authorization', ''), expected):
        raise web.HTTPForbidden()
    data = await request.json()
    avatar = session_manager.get_session('studio')
    if avatar is None:
        raise web.HTTPServiceUnavailable(text='AVATAR_NOT_CONNECTED')
    action = request.match_info['action']
    if action == 'speak':
        if not enabled():
            raise web.HTTPConflict(text='DSH_DISABLED')
        avatar._studio_generation = int(data['generation'])
        avatar._dsh_runtime_epoch = int(data['runtime_epoch'])
        info = {key: data[key] for key in ('request_id', 'utterance_id', 'runtime_epoch', 'generation')}
        info['dsh'] = True
        avatar.put_msg_txt(data['text'], info)
    elif action == 'cancel':
        avatar._studio_generation = int(data['new_generation'])
        avatar.flush_talk()
        broadcast = request.app['rtc_manager'].broadcast
        if broadcast:
            broadcast.cancel(data)
    else:
        raise web.HTTPNotFound()
    return web.json_response({'accepted': True})


async def memory_page(_request):
    return web.FileResponse(ROOT / 'web/memory.html')


async def obs_session(request):
    if request.remote not in ('127.0.0.1', '::1'):
        raise web.HTTPForbidden()
    origin = request.headers.get('Origin')
    if origin:
        from urllib.parse import urlsplit
        if urlsplit(origin).netloc != request.host:
            raise web.HTTPForbidden()
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
    app.router.add_get('/dsh-evidence/{path:.*}', evidence_file)
