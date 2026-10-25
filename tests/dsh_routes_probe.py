"""Exercise the installed aiohttp CORS adapter with every new route."""
from pathlib import Path
import importlib.util
import json
import asyncio
import sys
import types
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import aiohttp_cors

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dsh_route_probe', root / 'integration/dsh_bridge.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
app = web.Application(); module.configure(app)
cors = aiohttp_cors.setup(app, defaults={'*': aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers='*', allow_headers='*')})
for route in list(app.router.routes()):
    cors.add(route)
assert not any(route.method == '*' for route in app.router.routes())
async def check_legacy_guard():
    calls = []
    async def legacy(_request):
        calls.append(True)
        return web.json_response({'legacy': True})
    app.router.add_post('/human', legacy)
    async with TestClient(TestServer(app)) as client:
        module.enabled = lambda: True
        response = await client.post('/human', json={'text': 'must not enter old speech'})
        assert response.status == 409 and (await response.json())['error'] == 'DSH_LEGACY_ROUTE_DISABLED'
        assert not calls
        module.enabled = lambda: False
        response = await client.post('/human', json={})
        assert response.status == 200 and calls == [True]

async def check_streaming_proxy():
    release = asyncio.Event()
    async def events(request):
        assert request.headers['Last-Event-ID'] == '41'
        response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
        await response.prepare(request)
        await response.write(b'id: 42\nevent: state\ndata: {}\n\n')
        await release.wait()
        await response.write(b': heartbeat\n\n')
        return response
    upstream = web.Application()
    upstream.router.add_get('/api/dsh/events', events)
    server = TestServer(upstream)
    await server.start_server()
    saved_bridge = module.BRIDGE
    module.BRIDGE = str(server.make_url('')).rstrip('/')
    forwarded = web.Application()
    forwarded.router.add_get('/api/dsh/{tail:.*}', module.proxy)
    try:
        async with TestClient(TestServer(forwarded)) as client:
            result = await client.get('/api/dsh/events', headers={'Last-Event-ID': '41'})
            assert result.status == 200
            # Must arrive while the upstream response is still open. A buffered
            # proxy would time out here instead of delivering the first event.
            first = await asyncio.wait_for(result.content.readuntil(b'\n\n'), 2)
            assert b'id: 42' in first
            release.set()
            assert b'heartbeat' in await asyncio.wait_for(result.read(), 2)
    finally:
        release.set()
        module.BRIDGE = saved_bridge
        await server.close()


async def check_media_fences():
    class Avatar:
        def __init__(self):
            self.flushes = 0
            self.queued = []
        def flush_talk(self):
            self.flushes += 1
        def put_msg_txt(self, text, info):
            self.queued.append((text, info))
    avatar = Avatar()
    controls = []
    manager = types.SimpleNamespace(get_session=lambda _name: avatar)
    saved_module = sys.modules.get('server.session_manager')
    sys.modules['server.session_manager'] = types.SimpleNamespace(session_manager=manager)
    saved_headers, saved_enabled = module.media_headers, module.enabled
    module.media_headers = lambda: {'Authorization': 'Bearer fixture-only'}
    module.enabled = lambda: True
    control_app = web.Application()
    control_app['rtc_manager'] = types.SimpleNamespace(broadcast=types.SimpleNamespace(cancel=controls.append))
    control_app.router.add_post('/internal/dsh/{action}', module.avatar_command)
    headers = {'Authorization': 'Bearer fixture-only'}
    first = {'request_id': 'one', 'utterance_id': 'u-one', 'runtime_epoch': 4, 'generation': 8, 'text': '旧句'}
    cancel = {'request_id': 'one', 'runtime_epoch': 4, 'generation': 8, 'new_generation': 9, 'barrier_id': 'fixture-barrier'}
    try:
        async with TestClient(TestServer(control_app)) as client:
            async def post(action, body):
                result = await client.post('/internal/dsh/' + action, json=body, headers=headers)
                return result
            assert (await post('speak', first)).status == 200
            assert len(avatar.queued) == 1 and avatar.flushes == 1
            assert (await (await post('speak', first)).json())['duplicate']
            assert len(avatar.queued) == 1 and avatar.flushes == 1
            assert (await post('speak', {**first, 'text': '同 ID 换词'})).status == 409
            assert (await post('cancel', cancel)).status == 200
            assert avatar.flushes == 2
            assert (await post('speak', first)).status == 409
            second = {**first, 'request_id': 'two', 'utterance_id': 'u-two', 'generation': 10, 'text': '新句'}
            assert (await post('speak', second)).status == 200
            before = (avatar.flushes, len(controls))
            stale = await (await post('cancel', cancel)).json()
            assert stale['accepted'] is False and (avatar.flushes, len(controls)) == before
            old_epoch = {**cancel, 'runtime_epoch': 3, 'new_generation': 999}
            assert (await (await post('cancel', old_epoch)).json())['accepted'] is False
            assert (avatar.flushes, len(controls)) == before
            next_epoch = {**first, 'runtime_epoch': 5, 'generation': 1}
            assert (await post('speak', next_epoch)).status == 200
            assert (avatar._dsh_runtime_epoch, avatar._studio_generation) == (5, 1)
            assert len(avatar.queued) == 3
            assert controls[-1]['request_id'] is None  # reset cannot confirm playback
    finally:
        module.media_headers, module.enabled = saved_headers, saved_enabled
        if saved_module is None:
            sys.modules.pop('server.session_manager', None)
        else:
            sys.modules['server.session_manager'] = saved_module

async def main():
    await check_legacy_guard()
    await check_streaming_proxy()
    await check_media_fences()

asyncio.run(main())
print(json.dumps({'passed': True, 'route_count': len(list(app.router.routes())), 'cors_preflight': True, 'legacy_speech_bypass_blocked': True, 'sse_forwarded_before_eof': True, 'last_event_id_forwarded': True, 'media_commands_idempotent': True, 'stale_cancel_does_not_flush_new_speech': True, 'old_epoch_cannot_override_new': True}))
