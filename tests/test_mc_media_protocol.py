"""CPU codec fixtures and actual loopback WS paths; no avatar/model/NVENC startup."""
import asyncio
import base64
import importlib.util
from pathlib import Path
import struct
import sys
import threading
import types
import unittest
from unittest.mock import patch
from aiohttp import web, WSMsgType
from aiohttp.test_utils import TestClient, TestServer
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


protocol = load('mc_media_protocol', 'integration/media_protocol.py')
buffer = load('mc_viewer_buffer', 'integration/viewer_buffer.py')
PICTURES = {(640, 640): (ROOT / 'tests/fixtures/stream-green-640x640.h264').read_bytes(),
            (960, 540): (ROOT / 'tests/fixtures/stream-blue-960x540.h264').read_bytes()}


def encoded(size=(640, 640), key=True):
    return b'AVC1' + struct.pack('<I', int(key)) + PICTURES[size]


class ProtocolTests(unittest.TestCase):
    def test_real_parameter_sets_produce_exact_avcc_and_length_prefixed_units(self):
        payload, init = protocol.MediaProfile().packet(encoded(), 640, 640)
        units = protocol.annex_b_nalus(PICTURES[(640, 640)])
        sps = next(u for u in units if u[0] & 31 == 7)
        pps = next(u for u in units if u[0] & 31 == 8)
        description = base64.b64decode(init['avc_description_base64'], validate=True)
        self.assertEqual(description, b'\x01' + sps[1:4] + b'\xff\xe1' + struct.pack('>H', len(sps)) + sps + b'\x01' + struct.pack('>H', len(pps)) + pps)
        self.assertEqual(init['codec'], 'avc1.' + sps[1:4].hex())
        self.assertEqual(init['audio'], {'format': 's16le', 'sample_rate': 16000, 'channels': 1})
        offset = 8
        for unit in units:
            length = struct.unpack_from('>I', payload, offset)[0]
            self.assertEqual(payload[offset + 4:offset + 4 + length], unit)
            offset += 4 + length
        self.assertEqual(offset, len(payload))

    def test_delta_keeps_stream_id_and_reconfiguration_changes_it(self):
        profile = protocol.MediaProfile()
        _, first = profile.packet(encoded(), 640, 640)
        delta = b'AVC1' + struct.pack('<I', 0) + b'\x00\x00\x01\x41\x11\x22'
        _, same = profile.packet(delta, 640, 640)
        self.assertIs(first, same)
        with self.assertRaisesRegex(ValueError, 'PARAMETER_SETS'):
            profile.packet(delta, 960, 540)
        _, second = profile.packet(encoded((960, 540)), 960, 540)
        self.assertNotEqual(first['stream_id'], second['stream_id'])
        self.assertEqual((second['width'], second['height']), (960, 540))

    def test_missing_headers_empty_units_bad_dimensions_and_non_idr_fail_closed(self):
        for invalid in [b'bad', b'AVC1' + bytes(4) + b'invalid', b'AVC1' + bytes(4) + b'\x00\x00\x01']:
            with self.assertRaises(ValueError):
                protocol.MediaProfile().packet(invalid, 640, 640)
        with self.assertRaisesRegex(ValueError, 'DIMENSIONS'):
            protocol.MediaProfile().packet(encoded(), 1, 640)
        with self.assertRaisesRegex(ValueError, 'IDR'):
            protocol.MediaProfile().packet(encoded(key=False), 640, 640)
        with self.assertRaisesRegex(ValueError, 'PARAMETER_SETS'):
            protocol.MediaProfile().packet(b'AVC1' + bytes(4) + b'\x00\x00\x01\x41\x11', 640, 640)

    def test_unsupported_version_and_v3_jpeg_are_rejected(self):
        self.assertIsNone(protocol.stream_request_error({}))
        self.assertIsNone(protocol.stream_request_error({'v': '2'}))
        self.assertIsNone(protocol.stream_request_error({'v': '3', 'codec': 'h264'}))
        self.assertEqual(protocol.stream_request_error({'v': '3'}), 'MEDIA_V3_REQUIRES_H264')
        self.assertEqual(protocol.stream_request_error({'v': '9'}), 'MEDIA_VERSION_UNSUPPORTED')


class BroadcastTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        class Encoder:
            def __init__(self, width, height):
                self.codec = types.SimpleNamespace(width=width, height=height)
            def encode(self, frame, sequence, keyframe):
                size = (self.codec.width, self.codec.height)
                return encoded(size), True
        logger = types.SimpleNamespace(exception=lambda *a: None, warning=lambda *a: None)
        self.maps = []
        async def mapped(kind, data):
            self.maps.append((kind, data))
            if getattr(self, 'map_block', None):
                self.map_started.set(); await self.map_block.wait()
            return {'map_revision': len(self.maps)}
        modules = {'cv2': types.SimpleNamespace(setNumThreads=lambda n: None), 'utils.logger': types.SimpleNamespace(logger=logger),
                   'server.viewer_buffer': buffer, 'server.stream_encoder': types.SimpleNamespace(H264Encoder=Encoder),
                   'server.media_protocol': protocol, 'server.dsh_bridge': types.SimpleNamespace(async_media=mapped)}
        self.patches = patch.dict(sys.modules, modules); self.patches.start()
        self.module = load('mc_local_broadcast', 'integration/local_broadcast.py')
        self.avatar = types.SimpleNamespace(output=types.SimpleNamespace(), render=lambda quit: quit.wait(), notify=lambda e: None,
                                            _studio_generation=1, _dsh_runtime_epoch=1)
        self.broadcast = self.module.LocalBroadcast(self.avatar)
        app = web.Application(); app.router.add_get('/stream', self.broadcast.handle)
        self.client = TestClient(TestServer(app)); await self.client.start_server()

    async def asyncTearDown(self):
        await self.broadcast.close(); await self.client.close()
        self.broadcast.thread.join(timeout=2)
        self.assertFalse(self.broadcast.thread.is_alive())
        self.patches.stop()

    def push(self, size=(640, 640), speech=False):
        events = [(0, {'dsh': True, 'valid_samples': 320, 'generation': 1, 'runtime_epoch': 1, 'request_id': 'r1',
                       'utterance_id': 'u1', 'valid_sample_count': 320, 'sample_offset': 0, 'sample_final': True})] if speech else []
        self.broadcast.queue.put((np.zeros((size[1], size[0], 3), dtype=np.uint8), np.arange(640, dtype=np.int16), events))

    async def test_v3_init_map_binary_and_resize_reset_are_ordered_and_pcm_exact(self):
        ws = await self.client.ws_connect('/stream?v=3&codec=h264')
        self.push(speech=True)
        init = await ws.receive_json(timeout=3); mapping = await ws.receive_json(timeout=3); packet = await ws.receive(timeout=3)
        self.assertEqual(init['type'], 'media.init'); self.assertEqual(mapping['type'], 'media.map')
        self.assertEqual(packet.type, WSMsgType.BINARY)
        seq, length, rate = struct.unpack_from('<III', packet.data)
        self.assertEqual((seq, rate), (0, 16000)); self.assertEqual(mapping['ranges'][0]['packet_seq'], seq)
        self.assertEqual(packet.data[12 + length:], np.arange(640, dtype=np.int16).tobytes())
        self.push((960, 540))
        reset = await ws.receive_json(timeout=3); second = await ws.receive_json(timeout=3); binary = await ws.receive(timeout=3)
        self.assertEqual(reset['type'], 'media.reset'); self.assertEqual(reset['old_stream_id'], init['stream_id'])
        self.assertEqual(reset['new_stream_id'], second['stream_id']); self.assertEqual(second['width'], 960)
        self.assertEqual(binary.type, WSMsgType.BINARY)
        await ws.close()

    async def test_cancel_before_sender_retains_configuration_for_next_keyframe(self):
        ws = await self.client.ws_connect('/stream?v=3&codec=h264')
        # Clear a queued init+PCM atomically before the sender observes it.
        viewer = next(iter(self.broadcast.viewers.values()))
        viewer.put(b'not-sent', [{'type': 'media.init', 'stream_id': 'discarded'}])
        self.broadcast.cancel({'runtime_epoch': 1, 'new_generation': 2, 'barrier_id': 'barrier'})
        self.assertEqual((await ws.receive_json(timeout=3))['type'], 'playback.cancel')
        self.push()
        self.assertEqual((await ws.receive_json(timeout=3))['type'], 'media.init')
        self.assertEqual((await ws.receive(timeout=3)).type, WSMsgType.BINARY)
        await ws.close()

    async def test_v2_still_carries_annex_b_without_new_control_header(self):
        ws = await self.client.ws_connect('/stream?v=2&codec=h264'); self.push()
        packet = await ws.receive(timeout=3)
        self.assertEqual(packet.type, WSMsgType.BINARY)
        self.assertEqual(packet.data[12:20], b'AVC1' + struct.pack('<I', 1))
        self.assertEqual(packet.data[20:20 + len(PICTURES[(640, 640)])], PICTURES[(640, 640)])
        await ws.close()

    async def test_bad_request_never_creates_a_model_session(self):
        rtc = types.SimpleNamespace(RTCManager=object)
        with patch.dict(sys.modules, {'server.rtc_manager': rtc, 'server.session_manager': types.SimpleNamespace(session_manager=None),
                                      'server.local_broadcast': self.module}):
            module = load('mc_studio_rtc', 'integration/studio_rtc.py')
        instance = object.__new__(module.StudioRTCManager)
        async def forbidden():
            self.fail('bad media requests must not load a model')
        instance.ensure_session = forbidden
        response = await instance.handle_local_stream(types.SimpleNamespace(query={'v': '3', 'codec': 'jpeg'}))
        self.assertEqual(response.status, 400)

    async def test_viewer_joining_during_mapping_waits_for_its_own_complete_packet(self):
        self.map_block=asyncio.Event();self.map_started=asyncio.Event()
        old=await self.client.ws_connect('/stream?v=2&codec=h264');self.push(speech=True)
        await asyncio.wait_for(self.map_started.wait(),2)
        new=await self.client.ws_connect('/stream?v=3&codec=h264');self.map_block.set()
        self.assertEqual((await old.receive_json(timeout=3))['type'],'media.map')
        self.assertEqual((await old.receive(timeout=3)).type,WSMsgType.BINARY)
        self.push()
        self.assertEqual((await new.receive_json(timeout=3))['type'],'media.init')
        self.assertEqual((await new.receive(timeout=3)).type,WSMsgType.BINARY)
        self.assertFalse(self.broadcast.task.done());await new.close();await old.close()

    async def test_cancel_during_mapping_drops_inflight_pcm_before_the_new_generation(self):
        self.map_block=asyncio.Event();self.map_started=asyncio.Event()
        ws=await self.client.ws_connect('/stream?v=3&codec=h264');self.push(speech=True)
        await asyncio.wait_for(self.map_started.wait(),2)
        self.broadcast.cancel({'runtime_epoch':1,'new_generation':2,'barrier_id':'cancel-inflight'})
        self.assertEqual((await ws.receive_json(timeout=3))['type'],'playback.cancel')
        self.map_block.set();self.push()
        self.assertEqual((await ws.receive_json(timeout=3))['type'],'media.init')
        self.assertEqual((await ws.receive(timeout=3)).type,WSMsgType.BINARY)
        await ws.close()


class ProgrammeRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_formal_preview_layout_and_assets_are_served_by_real_a_routes(self):
        from integration import dsh_bridge
        app=web.Application();dsh_bridge.configure(app);app.router.add_static('/',ROOT/'web')
        async with TestClient(TestServer(app)) as client:
            for route in ['/mc/programme','/mc/preview','/mc-programme.js','/mc-programme-overlay.js','/mc-game-client.js','/mc-programme.css']:
                response=await client.get(route);self.assertEqual(response.status,200)
                self.assertGreater(len(await response.read()),100)
            response=await client.get('/mc/layout.json');self.assertEqual(response.status,200)
            self.assertEqual(await response.read(),(ROOT/'configs/layouts/mc-landscape-v1.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
