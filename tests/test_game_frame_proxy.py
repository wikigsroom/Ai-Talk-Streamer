"""Bounded native HTTP proxy checks. Synthetic bytes are not MC capture or vision inference."""
import asyncio
import hashlib
import importlib.util
import unittest
from pathlib import Path
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from integration import dsh_bridge

SPEC = importlib.util.spec_from_file_location('frame_receiver', Path(__file__).resolve().parents[1] / 'scripts/receiver_service.py')
RECEIVER = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(RECEIVER)
LIMIT = 4 * 1024 * 1024
HEADERS = {'Content-Type': 'image/jpeg', 'X-MC-Operation-Id': 'operation-fixture', 'X-MC-Bridge-Boot-Id': 'boot-fixture',
           'X-MC-World-Session-Id': 'world-fixture', 'X-MC-Seq': '14', 'X-MC-Captured-At': '2026-10-30T04:00:00.123456789Z',
           'X-MC-Width': '1920', 'X-MC-Height': '1080'}
PATH = '/api/dsh/game/frames/frame-fixture'


class FrameProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen = []; self.response_bytes = b'\xff\xd8' + b'TEST_FIXTURE_ONLY' * 150000 + b'\xff\xd9'
        async def frame(request):
            if request.method == 'GET':
                return web.Response(body=self.response_bytes, content_type='image/jpeg')
            digest = hashlib.sha256(); size = 0
            try:
                async for chunk in request.content.iter_chunked(65536):
                    digest.update(chunk); size += len(chunk)
            except ConnectionError:
                return web.Response(status=499)
            self.seen.append({'headers': dict(request.headers), 'bytes': size, 'sha256': digest.hexdigest()})
            return web.json_response({'byte_length': size, 'sha256': digest.hexdigest(), 'fixture': True}, status=201)
        app = web.Application(); app.router.add_route('*', PATH, frame)
        self.upstream = TestServer(app); await self.upstream.start_server()
        self.saved_bridge = dsh_bridge.BRIDGE; dsh_bridge.BRIDGE = str(self.upstream.make_url('')).rstrip('/')
        app = web.Application(); app.router.add_route('*', '/api/dsh/{tail:.*}', dsh_bridge.proxy)
        self.proxy = TestServer(app); await self.proxy.start_server()
        self.gateway = RECEIVER.ReceiverGateway({'upstream': str(self.proxy.make_url('/')), 'receiver_id': 'frame-test'})
        self.receiver = TestServer(self.gateway.application()); await self.receiver.start_server()
        self.client = ClientSession()

    async def asyncTearDown(self):
        await self.client.close(); await self.receiver.close(); await self.proxy.close(); await self.upstream.close()
        dsh_bridge.BRIDGE = self.saved_bridge

    async def test_three_megabytes_cross_both_json_limits_and_preserve_exact_bytes_and_metadata(self):
        data = b'\xff\xd8' + b'fixture' * 450000 + b'\xff\xd9'
        self.assertGreater(len(data), 2 * 1024 * 1024)
        async with self.client.post(self.receiver.make_url(PATH), data=data, headers=HEADERS) as response:
            self.assertEqual(response.status, 201); result = await response.json()
        self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(result['byte_length'], len(data))
        for key, value in HEADERS.items(): self.assertEqual(self.seen[0]['headers'].get(key), value, key)
        async with self.client.get(self.receiver.make_url(PATH)) as response:
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(await response.read(), self.response_bytes)

    async def test_each_proxy_rejects_declared_and_chunked_overflow_and_wrong_media_type(self):
        async def chunks():
            for _ in range(65): yield b'x' * 65536
        for server in (self.proxy, self.receiver):
            async with self.client.post(server.make_url(PATH), data=b'x' * (LIMIT + 1), headers=HEADERS) as response:
                self.assertEqual(response.status, 413); await response.read()
            async with self.client.post(server.make_url(PATH), data=chunks(), headers=HEADERS) as response:
                body=await response.read()
                self.assertEqual(response.status,413,{'proxy':'A' if server is self.proxy else 'B','body':body.decode('utf-8',errors='replace'),'production_timeout_seconds':6})
            async with self.client.post(server.make_url(PATH), data=b'x', headers={**HEADERS, 'Content-Encoding': 'gzip'}) as response:
                self.assertEqual(response.status, 415); await response.read()
            async with self.client.post(server.make_url(PATH), data=b'x', headers={'Content-Type': 'application/json'}) as response:
                self.assertEqual(response.status, 415); await response.read()
        self.assertEqual(self.seen, [])

    async def test_each_proxy_has_one_stream_and_clears_its_slot_after_completion(self):
        release = asyncio.Event()
        async def slow():
            yield b'\xff\xd8'
            await release.wait()
            yield b'\xff\xd9'
        pending = asyncio.create_task(self.client.post(self.receiver.make_url(PATH), data=slow(), headers=HEADERS))
        try:
            async with asyncio.timeout(2):
                while not (self.gateway.frame_uploading and dsh_bridge._frame_uploading): await asyncio.sleep(.005)
            for server in (self.proxy, self.receiver):
                async with self.client.post(server.make_url(PATH), data=b'x', headers=HEADERS) as response:
                    self.assertEqual(response.status, 429); await response.read()
        finally:
            release.set(); response = await pending; await response.read(); response.release()
        self.assertFalse(self.gateway.frame_uploading); self.assertFalse(dsh_bridge._frame_uploading)

    async def test_downloads_are_also_bounded_and_frame_route_does_not_enlarge_generic_json_limit(self):
        self.response_bytes = b'x' * (LIMIT + 1)
        for server in (self.proxy, self.receiver):
            async with self.client.get(server.make_url(PATH)) as response:
                self.assertEqual(response.status, 502)
                self.assertEqual((await response.json())['error'], 'GAME_FRAME_RESPONSE_TOO_LARGE')
        async with self.client.post(self.receiver.make_url('/api/dsh/game/queries'), data=b'x' * (2 * 1024 * 1024 + 1)) as response:
            self.assertEqual(response.status, 413)


if __name__ == '__main__': unittest.main()
