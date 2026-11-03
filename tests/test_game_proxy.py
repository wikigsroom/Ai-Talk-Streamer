"""Native loopback proxy checks only; no Minecraft, model or public stream."""
import asyncio
import unittest
from aiohttp import ClientSession, WSMsgType, WSServerHandshakeError, web
from aiohttp.test_utils import TestClient, TestServer
from integration import dsh_bridge


class GameProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stop = asyncio.Event()
        self.messages = []

        async def protocol(request):
            socket = web.WebSocketResponse(max_msg_size=131072)
            await socket.prepare(request)
            async for message in socket:
                if message.type == WSMsgType.TEXT:
                    self.messages.append(message.data)
                    await socket.send_str(message.data)
            return socket

        async def events(request):
            response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
            await response.prepare(request)
            await response.write(b'event: snapshot\ndata: {"fixture":true}\n\n')
            await self.stop.wait()
            return response

        upstream = web.Application()
        upstream.router.add_get('/api/dsh/game/bridge', protocol)
        upstream.router.add_get('/api/dsh/game/events', events)
        self.upstream = TestServer(upstream)
        await self.upstream.start_server()
        self.saved_bridge = dsh_bridge.BRIDGE
        dsh_bridge.BRIDGE = str(self.upstream.make_url('')).rstrip('/')
        app = web.Application()
        app.router.add_get('/api/dsh/{tail:.*}', dsh_bridge.proxy)
        self.proxy = TestServer(app)
        await self.proxy.start_server()
        self.client = ClientSession()

    async def asyncTearDown(self):
        self.stop.set()
        await self.client.close()
        await self.proxy.close()
        await self.upstream.close()
        dsh_bridge.BRIDGE = self.saved_bridge

    async def test_game_protocol_is_forwarded_to_fixed_upstream(self):
        async with self.client.ws_connect(self.proxy.make_url('/api/dsh/game/bridge')) as socket:
            await socket.send_str('{"fixture":"same-player"}')
            response = await asyncio.wait_for(socket.receive(), 2)
            self.assertEqual(response.type, WSMsgType.TEXT)
            self.assertEqual(response.data, '{"fixture":"same-player"}')
            self.assertEqual(self.messages, [response.data])

    async def test_arbitrary_websocket_paths_are_not_forwarded(self):
        with self.assertRaises(WSServerHandshakeError) as caught:
            await self.client.ws_connect(self.proxy.make_url('/api/dsh/unknown/bridge'))
        self.assertEqual(caught.exception.status, 404)

    async def test_game_binary_payload_is_rejected(self):
        async with self.client.ws_connect(self.proxy.make_url('/api/dsh/game/bridge')) as socket:
            await socket.send_bytes(b'not-a-game-text-frame')
            response = await asyncio.wait_for(socket.receive(), 2)
            self.assertIn(response.type, (WSMsgType.CLOSE, WSMsgType.CLOSED))
            self.assertEqual(self.messages, [])

    async def test_game_sse_is_streamed_without_buffering_the_whole_response(self):
        async with self.client.get(self.proxy.make_url('/api/dsh/game/events')) as response:
            self.assertEqual(response.status, 200)
            line = await asyncio.wait_for(response.content.readline(), 2)
            self.assertEqual(line, b'event: snapshot\n')

    async def test_mc_operator_page_and_fixed_assets_are_served_from_the_project(self):
        app = web.Application()
        dsh_bridge.configure(app)
        async with TestClient(TestServer(app)) as client:
            for path, marker in (('/mc-control', 'MC 世界管理'), ('/mc-control.css', '--accent'), ('/mc-control.js', 'Task'), ('/mc-task-failures.js', '合成材料尚未备齐'), ('/mc-player-safety.mjs', 'playerSafety')):
                response = await client.get(path)
                self.assertEqual(response.status, 200, path)
                self.assertIn(marker, await response.text())
                if path.endswith('.mjs'):
                    self.assertEqual(response.content_type, 'text/javascript')
            self.assertEqual((await client.get('/mc-control.secret')).status, 404)
            self.assertEqual((await client.post('/mc-control')).status, 405)


if __name__ == '__main__':
    unittest.main()
