import asyncio,importlib.util,json,unittest
from pathlib import Path
from aiohttp import web,WSMsgType
from aiohttp.test_utils import TestClient,TestServer

SPEC=importlib.util.spec_from_file_location('receiver_service',Path(__file__).resolve().parents[1]/'scripts/receiver_service.py')
MODULE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MODULE)

class ReceiverTests(unittest.IsolatedAsyncioTestCase):
    async def test_recording_gallery_is_local_and_does_not_open_a_media_connection(self):
        response=await self.client.get('/receiver/evidence/')
        self.assertEqual(response.status,200);self.assertIn('split-s05.mp4',await response.text())
        self.assertEqual(self.gateway.metrics['websocket_connections'],0)
    async def test_recording_download_cannot_select_a_private_config(self):
        response=await self.client.get('/receiver/evidence/channel.env')
        self.assertEqual(response.status,404)
    async def asyncSetUp(self):
        self.observed=[]
        async def endpoint(request):
            if request.path=='/api/studio/stream':
                ws=web.WebSocketResponse(compress=False);await ws.prepare(request)
                await ws.send_json({'type':'media.map','sample_count':640})
                await ws.send_bytes(b'\x00\x01portrait-pcm\x00\xff')
                async for message in ws:
                    if message.type==WSMsgType.TEXT:await ws.send_str(message.data)
                return ws
            body=await request.read()
            if request.path=='/api/dsh/platforms/output/player':
                self.observed.append(json.loads(body));return web.json_response({'claim':False})
            return web.Response(body=body or b'upstream-ok',headers={'Content-Type':'application/octet-stream'})
        app=web.Application();app.router.add_route('*','/{tail:.*}',endpoint)
        self.upstream=TestServer(app);await self.upstream.start_server()
        self.gateway=MODULE.ReceiverGateway({'upstream':str(self.upstream.make_url('/')),'receiver_id':'test-b'})
        self.client=TestClient(TestServer(self.gateway.application()));await self.client.start_server()
    async def asyncTearDown(self):
        await self.client.close();await self.upstream.close()
    async def test_same_origin_http_preserves_post_body(self):
        response=await self.client.post('/api/dsh/requests?echo=1',data=b'\x00\x01request')
        self.assertEqual(response.status,200);self.assertEqual(await response.read(),b'\x00\x01request')
    async def test_websocket_preserves_control_before_exact_pcm_packet(self):
        async with self.client.ws_connect('/api/studio/stream') as ws:
            first=await ws.receive(timeout=2);second=await ws.receive(timeout=2)
            self.assertEqual(first.type,WSMsgType.TEXT);self.assertEqual(json.loads(first.data)['type'],'media.map')
            self.assertEqual(second.type,WSMsgType.BINARY);self.assertEqual(second.data,b'\x00\x01portrait-pcm\x00\xff')
            await ws.send_str('receiver-to-a');self.assertEqual((await ws.receive(timeout=2)).data,'receiver-to-a')
        status=await (await self.client.get('/receiver/status')).json()
        self.assertEqual(status['media_packets'],1);self.assertFalse(status['authentication_required'])
    async def test_receiver_id_overrides_remote_player_input(self):
        response=await self.client.post('/api/dsh/platforms/output/player',json={'consumer_id':'x','receiver_id':'spoofed','receiver_client_ready':True})
        self.assertEqual(response.status,200);self.assertEqual(self.observed[0]['receiver_id'],'test-b')
        self.assertFalse(self.observed[0]['receiver_client_ready'])
    async def test_upstream_disconnect_returns_actionable_error(self):
        await self.upstream.close()
        result=await self.client.get('/api/studio/status')
        self.assertEqual(result.status,502);self.assertEqual((await result.json())['error'],'AVATAR_DEVICE_UNREACHABLE')
        self.assertEqual(self.gateway.metrics['upstream_errors'],1)
    async def test_websocket_disconnect_closes_b_and_a_new_connection_recovers(self):
        ws=await self.client.ws_connect('/api/studio/stream')
        await ws.receive(timeout=2);await ws.receive(timeout=2)
        await ws.close()
        async with self.client.ws_connect('/api/studio/stream') as recovered:
            self.assertEqual((await recovered.receive(timeout=2)).type,WSMsgType.TEXT)
            self.assertEqual((await recovered.receive(timeout=2)).data,b'\x00\x01portrait-pcm\x00\xff')
        self.assertEqual(self.gateway.metrics['websocket_connections'],2)
    async def test_local_dashboard_is_available_without_a(self):
        await self.upstream.close()
        self.assertEqual((await self.client.get('/receiver/')).status,200)
        status=await (await self.client.get('/receiver/status')).json();self.assertEqual(status['role'],'receiver')

class ReceiverConfigTests(unittest.TestCase):
    def test_rejects_remote_bind_and_self_proxy(self):
        for config in [{'upstream':'http://127.0.0.1:8020'},{'upstream':'http://localhost:8010','bind':'0.0.0.0'},{'upstream':'http://example.com/path'},{'upstream':'http://user:pass@example.com'},{'upstream':'http://0.0.0.0:8010'}]:
            with self.subTest(config=config),self.assertRaises(ValueError):MODULE.validate_config(config)
    def test_private_vpn_origin_and_ipv6_supported(self):
        self.assertEqual(MODULE.validate_config({'upstream':'http://10.42.0.7:8010/'})['upstream'],'http://10.42.0.7:8010')
        self.assertEqual(MODULE.validate_config({'upstream':'http://[fd00::42]:8010'})['port'],8020)

if __name__=='__main__':unittest.main()
