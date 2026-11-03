"""Exercise the actual HTML/static/receiver chain with an older vendor web root."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit
import importlib.util
import re
import unittest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from integration import dsh_bridge

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('programme_receiver', ROOT / 'scripts/receiver_service.py')
RECEIVER = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(RECEIVER)


class ProgrammeAssetsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);source=self.root/'web';source.mkdir()
        vendor=self.root/'vendor-web';vendor.mkdir();self.expected={}
        for name in [*dsh_bridge.MC_PROGRAMME_ASSETS,'mc-programme.html']:
            data=(ROOT/'web'/name).read_bytes();self.expected[name]=data
            (source/name).write_bytes(data);(vendor/name).write_bytes(b'OLD VENDOR ASSET')
        patched=patch.object(dsh_bridge,'ROOT',self.root);patched.start();self.addCleanup(patched.stop)
        app=web.Application();dsh_bridge.configure(app)
        app.router.add_static('/',vendor)
        self.studio=TestServer(app);await self.studio.start_server()
        gateway=RECEIVER.ReceiverGateway({'upstream':str(self.studio.make_url('/')),'receiver_id':'asset-fixture'})
        self.receiver=TestServer(gateway.application());await self.receiver.start_server()
        self.client=ClientSession()

    async def asyncTearDown(self):
        await self.client.close();await self.receiver.close();await self.studio.close()

    async def test_html_dependency_graph_uses_current_project_bytes_through_both_http_hops(self):
        for server in (self.studio,self.receiver):
            async with self.client.get(server.make_url('/mc/programme')) as response:
                self.assertEqual(response.status,200);html=await response.text()
            names={urlsplit(value).path.removeprefix('/')for value in re.findall(r'(?:src|href)="([^"]+)"',html)}
            self.assertEqual(names,dsh_bridge.MC_PROGRAMME_ASSETS)
            for name in names:
                with self.subTest(port=server.port,asset=name):
                    async with self.client.get(server.make_url('/'+name+'?v=mc-098')) as response:
                        self.assertEqual(response.status,200)
                        self.assertEqual(await response.read(),self.expected[name])
                        self.assertEqual(response.headers.get('Cache-Control'),'no-store')

    async def test_conditional_stale_asset_reload_returns_current_identity_fields(self):
        for server in (self.studio,self.receiver):
            async with self.client.get(server.make_url('/local-stream.js?v=mc-098'),headers={
                    'If-None-Match':'"old-vendor-etag"','If-Modified-Since':'Sun, 01 Nov 2026 07:00:19 GMT'}) as response:
                self.assertEqual(response.status,200);data=await response.read()
                self.assertEqual(data,self.expected['local-stream.js'])
                self.assertIn(b'media_stream_id',data);self.assertIn(b'metricsTransportId',data)
                self.assertEqual(response.headers.get('Cache-Control'),'no-store')

    async def test_unlisted_paths_and_writes_do_not_gain_an_asset_route(self):
        (self.root/'configs').mkdir();(self.root/'configs/private.json').write_text('PRIVATE FIXTURE')
        for server in (self.studio,self.receiver):
            async with self.client.get(server.make_url('/configs/private.json')) as response:
                self.assertEqual(response.status,404)
            async with self.client.post(server.make_url('/local-stream.js'),data=b'not-a-source-update') as response:
                self.assertEqual(response.status,405)
        self.assertEqual((self.root/'web/local-stream.js').read_bytes(),self.expected['local-stream.js'])


if __name__=='__main__':unittest.main()
