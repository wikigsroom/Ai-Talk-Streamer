import asyncio,importlib.util,json,unittest
from unittest.mock import patch
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
        self.observed=[];self.broadcast=None;self.player_results={};self.player_status=200;self.player_waiters={};self.fragment_player=False
        async def endpoint(request):
            if request.path=='/api/dsh/status':return web.json_response({'broadcast':self.broadcast})
            if request.path=='/api/studio/stream':
                ws=web.WebSocketResponse(compress=False);await ws.prepare(request)
                if request.query.get('v')=='3':
                    self.observed.append(dict(request.query))
                    for message in [{'type':'media.init','stream_id':'first'},{'type':'media.reset','old_stream_id':'first','new_stream_id':'second'}, {'type':'media.init','stream_id':'second'}, {'type':'media.map','packet_seq':10}]:await ws.send_json(message)
                    await ws.send_bytes(b'v3-exact-AVCC-and-PCM\x00\xff')
                    async for message in ws:
                        if message.type==WSMsgType.TEXT:await ws.send_str(message.data)
                    return ws
                await ws.send_json({'type':'media.map','sample_count':640})
                await ws.send_bytes(b'\x00\x01portrait-pcm\x00\xff')
                async for message in ws:
                    if message.type==WSMsgType.TEXT:await ws.send_str(message.data)
                return ws
            body=await request.read()
            if request.path=='/api/dsh/platforms/output/player':
                data=json.loads(body);self.observed.append(data);consumer=data.get('consumer_id')
                if consumer in self.player_waiters:await self.player_waiters[consumer].wait()
                result=self.player_results.get(consumer,{'accepted':True,'claim':False,'consumer_id':consumer,'playback_authority':False,'broadcast_id':None})
                if self.fragment_player:
                    response=web.StreamResponse(status=self.player_status,headers={'Content-Type':'application/json'});await response.prepare(request)
                    payload=json.dumps(result).encode();await response.write(payload[:7]);await asyncio.sleep(.01);await response.write(payload[7:]);await response.write_eof();return response
                return web.json_response(result,status=self.player_status)
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
    async def test_v3_query_reset_init_map_and_binary_are_transparent(self):
        async with self.client.ws_connect('/api/studio/stream?v=3&codec=h264') as ws:
            messages=[await ws.receive_json(timeout=2) for _ in range(4)]
            self.assertEqual([m['type'] for m in messages],['media.init','media.reset','media.init','media.map'])
            self.assertEqual((await ws.receive(timeout=2)).data,b'v3-exact-AVCC-and-PCM\x00\xff')
            await ws.send_str('{"type":"video.keyframe"}');self.assertEqual((await ws.receive(timeout=2)).data,'{"type":"video.keyframe"}')
        self.assertEqual(self.observed,[{'v':'3','codec':'h264'}])
    async def test_mc_pages_and_layout_reach_fixed_upstream_and_status_lists_both_urls(self):
        for path in ['/mc/programme?renderer=livehime','/mc/preview','/mc/layout.json','/mc-programme.js']:
            response=await self.client.get(path);self.assertEqual(response.status,200);self.assertEqual(await response.read(),b'upstream-ok')
        status=await(await self.client.get('/receiver/status')).json()
        self.assertTrue(status['mc_programme_url'].endswith('/mc/programme?renderer=livehime'))
        self.assertTrue(status['mc_preview_url'].endswith('/mc/preview'))
    async def test_websocket_preserves_control_before_exact_pcm_packet(self):
        async with self.client.ws_connect('/api/studio/stream') as ws:
            first=await ws.receive(timeout=2);second=await ws.receive(timeout=2)
            self.assertEqual(first.type,WSMsgType.TEXT);self.assertEqual(json.loads(first.data)['type'],'media.map')
            self.assertEqual(second.type,WSMsgType.BINARY);self.assertEqual(second.data,b'\x00\x01portrait-pcm\x00\xff')
            await ws.send_str('receiver-to-a');self.assertEqual((await ws.receive(timeout=2)).data,'receiver-to-a')
        status=await (await self.client.get('/receiver/status')).json()
        self.assertEqual(status['media_packets'],1);self.assertFalse(status['authentication_required'])
    async def test_receiver_id_overrides_remote_player_input(self):
        response=await self.client.post('/api/dsh/platforms/output/player',json={'consumer_id':'x','renderer':'livehime','receiver_id':'spoofed','receiver_client_ready':True,
            'stream_metrics':{'codec':'h264_nvenc','fps':24.9,'fps_source':'canvas_draw','output_mode':'direct_canvas_audio','missing_packets':-1,'decode_errors':True,'private_key':'must-not-retain'}})
        self.assertEqual(response.status,200);self.assertEqual(self.observed[0]['receiver_id'],'test-b')
        self.assertFalse(self.observed[0]['receiver_client_ready'])
        self.assertNotIn('stream_metrics',self.observed[0])
        self.assertEqual(self.gateway.metrics['player_metrics'],{'codec':'h264_nvenc','fps':24.9,'fps_source':'canvas_draw','output_mode':'direct_canvas_audio'})
    async def test_upstream_disconnect_returns_actionable_error(self):
        await self.upstream.close()
        result=await self.client.get('/api/studio/status')
        self.assertEqual(result.status,502);self.assertEqual((await result.json())['error'],'AVATAR_DEVICE_UNREACHABLE')
        self.assertEqual(self.gateway.metrics['upstream_errors'],1)
    def player(self,consumer='official-player',transport='transport-first',stream='media-first',frames=100,underruns=2):
        return {'consumer_id':consumer,'renderer':'livehime','frames':frames,'stream_metrics':{'transport_id':transport,
            'media_stream_id':stream,'media_protocol_version':3,'frames':frames,'audio_underruns':underruns,'fps':25}}
    async def test_ignored_failed_and_mismatched_admission_cannot_replace_diagnostics(self):
        body=self.player();await self.client.post('/api/dsh/platforms/output/player',json=body)
        previous=self.gateway.metrics['player_metrics'];binding=self.gateway.metrics['player_metrics_binding']
        self.assertTrue(binding['complete']);self.assertFalse(binding['playback_authority'])
        for result,status in [({'ignored':True,'accepted':True,'consumer_id':'standby'},200),
                ({'accepted':True,'consumer_id':'someone-else'},200),({'claim':False},200),
                ({'accepted':True,'consumer_id':'standby'},503)]:
            self.player_results['standby']=result;self.player_status=status
            await self.client.post('/api/dsh/platforms/output/player',json=self.player('standby',frames=0))
            self.assertIs(self.gateway.metrics['player_metrics'],previous)
            self.assertIs(self.gateway.metrics['player_metrics_binding'],binding)
        self.assertEqual(self.gateway.metrics['player_reports_ignored'],4)
    async def test_legacy_or_invalid_stream_identity_is_explicitly_unbound(self):
        for patch_metrics in [{},{'transport_id':'../invalid','media_protocol_version':3,'media_stream_id':'media-first'},
                {'transport_id':'transport','media_protocol_version':True,'media_stream_id':'media-first'}]:
            body=self.player();body['stream_metrics']=patch_metrics
            await self.client.post('/api/dsh/platforms/output/player',json=body)
            self.assertFalse(self.gateway.metrics['player_metrics_binding']['complete'])
            self.assertIsNone(self.gateway.metrics['player_fps'])
    async def test_transport_stream_and_counter_resets_start_new_diagnostic_segments(self):
        async def report(at,**values):
            with patch.object(MODULE.time,'time',return_value=at):
                await self.client.post('/api/dsh/platforms/output/player',json=self.player(**values))
            return self.gateway.metrics['player_metrics_binding']['counter_segment']
        first=await report(100,frames=100)
        self.assertEqual(await report(102,frames=150),first);self.assertEqual(self.gateway.metrics['player_fps'],25)
        second=await report(104,transport='replacement',frames=0,underruns=0)
        self.assertGreater(second,first);self.assertIsNone(self.gateway.metrics['player_fps'])
        third=await report(106,transport='replacement',stream='media-second',frames=20)
        self.assertGreater(third,second);self.assertIsNone(self.gateway.metrics['player_fps'])
        fourth=await report(108,transport='replacement',stream='media-second',frames=1,underruns=0)
        self.assertGreater(fourth,third);self.assertIsNone(self.gateway.metrics['player_fps'])
        self.assertTrue(self.gateway.metrics['player_metrics_binding']['counter_discontinuity'])
        self.assertEqual(self.gateway.metrics['player_counter_discontinuities'],1)
    async def test_out_of_order_admission_response_cannot_restore_previous_renderer_metrics(self):
        self.player_waiters['older-player']=asyncio.Event()
        older=asyncio.create_task(self.client.post('/api/dsh/platforms/output/player',json=self.player('older-player')))
        try:
            for _ in range(100):
                if self.observed:break
                await asyncio.sleep(.01)
            self.assertTrue(self.observed)
            await self.client.post('/api/dsh/platforms/output/player',json=self.player('newer-player',frames=200))
            self.player_waiters['older-player'].set();await older
            self.assertEqual(self.gateway.metrics['player_metrics_binding']['consumer_id'],'newer-player')
            self.assertEqual(self.gateway.metrics['player_reports_reordered'],1)
        finally:
            self.player_waiters['older-player'].set();await older
    async def test_fragmented_response_is_read_completely_before_binding_and_request_cannot_claim_authority(self):
        self.fragment_player=True;body=self.player();body['playback_authority']=True
        response=await self.client.post('/api/dsh/platforms/output/player',json=body)
        self.assertEqual(response.status,200);self.assertTrue((await response.json())['accepted'])
        self.assertTrue(self.gateway.metrics['player_metrics_binding']['complete'])
        self.assertFalse(self.gateway.metrics['player_metrics_binding']['playback_authority'])
        self.player_results['official-player']={'accepted':True,'consumer_id':'official-player','playback_authority':True,'broadcast_id':'fixture-broadcast'}
        await self.client.post('/api/dsh/platforms/output/player',json=body)
        self.assertTrue(self.gateway.metrics['player_metrics_binding']['playback_authority'])
    async def test_websocket_disconnect_closes_b_and_a_new_connection_recovers(self):
        ws=await self.client.ws_connect('/api/studio/stream')
        await ws.receive(timeout=2);await ws.receive(timeout=2)
        await ws.close()
        async with self.client.ws_connect('/api/studio/stream') as recovered:
            self.assertEqual((await recovered.receive(timeout=2)).type,WSMsgType.TEXT)
            self.assertEqual((await recovered.receive(timeout=2)).data,b'\x00\x01portrait-pcm\x00\xff')
        self.assertEqual(self.gateway.metrics['websocket_connections'],2)
    async def test_offair_source_reload_reaches_existing_websocket(self):
        ws=await self.client.ws_connect('/api/studio/stream')
        await ws.receive(timeout=2);await ws.receive(timeout=2)
        pending=asyncio.create_task(self.client.post('/receiver/player/reload'))
        close=await ws.receive(timeout=3)
        self.assertEqual(close.type,WSMsgType.CLOSE);self.assertEqual(close.data,4001)
        result=await pending
        self.assertEqual(result.status,200);self.assertEqual((await result.json())['reload_requested'],1)
        await ws.close()
    async def test_source_reload_preserves_active_session(self):
        self.broadcast={'broadcast_id':'active-session'}
        result=await self.client.post('/receiver/player/reload')
        self.assertEqual(result.status,409)
        self.assertEqual((await result.json())['error'],'END_LOCAL_SESSION_BEFORE_RELOAD')
    async def test_local_dashboard_is_available_without_a(self):
        await self.upstream.close()
        self.assertEqual((await self.client.get('/receiver/')).status,200)
        status=await (await self.client.get('/receiver/status')).json();self.assertEqual(status['role'],'receiver')
        with patch.object(MODULE,'official_client',return_value=Path('official/livehime.exe')),patch.object(MODULE,'running_client',return_value=123),patch.object(MODULE.subprocess,'Popen') as launch:
            data=await (await self.client.post('/receiver/client/launch')).json()
            self.assertTrue(data['already_running']);self.assertFalse(data['public_broadcast_started']);launch.assert_not_called()
        error=OSError('requires elevation');error.winerror=740
        with patch.object(MODULE,'official_client',return_value=Path('official/livehime.exe')),patch.object(MODULE,'running_client',return_value=None),patch.object(MODULE.subprocess,'Popen',side_effect=error):
            response=await self.client.post('/receiver/client/launch')
            self.assertEqual(response.status,409);self.assertEqual((await response.json())['error'],'RECEIVER_CLIENT_ELEVATION_REQUIRED')

class ReceiverConfigTests(unittest.TestCase):
    def test_rejects_remote_bind_and_self_proxy(self):
        for config in [{'upstream':'http://127.0.0.1:8020'},{'upstream':'http://localhost:8010','bind':'0.0.0.0'},{'upstream':'http://example.com/path'},{'upstream':'http://user:pass@example.com'},{'upstream':'http://0.0.0.0:8010'}]:
            with self.subTest(config=config),self.assertRaises(ValueError):MODULE.validate_config(config)
    def test_private_vpn_origin_and_ipv6_supported(self):
        self.assertEqual(MODULE.validate_config({'upstream':'http://10.42.0.7:8010/'})['upstream'],'http://10.42.0.7:8010')
        self.assertEqual(MODULE.validate_config({'upstream':'http://[fd00::42]:8010'})['port'],8020)

if __name__=='__main__':unittest.main()
