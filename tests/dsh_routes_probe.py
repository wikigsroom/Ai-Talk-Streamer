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

asyncio.run(check_legacy_guard())
print(json.dumps({'passed': True, 'route_count': len(list(app.router.routes())), 'cors_preflight': True, 'legacy_speech_bypass_blocked': True}))
