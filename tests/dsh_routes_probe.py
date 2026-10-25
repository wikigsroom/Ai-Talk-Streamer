"""Exercise the installed aiohttp CORS adapter with every new route."""
from pathlib import Path
import importlib.util
import json
import asyncio
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

async def main():
    await check_legacy_guard()
    await check_streaming_proxy()

asyncio.run(main())
print(json.dumps({'passed': True, 'route_count': len(list(app.router.routes())), 'cors_preflight': True, 'legacy_speech_bypass_blocked': True, 'sse_forwarded_before_eof': True, 'last_event_id_forwarded': True}))
