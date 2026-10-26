"""Verify map/PCM pairing survives picture shedding and cancellation."""
from pathlib import Path
import importlib.util
import struct
import unittest

spec = importlib.util.spec_from_file_location('viewer_buffer', Path(__file__).resolve().parents[1] / 'integration/viewer_buffer.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class BufferTests(unittest.IsolatedAsyncioTestCase):
    async def test_h264_retains_all_reference_frames_and_pcm_until_disconnect_limit(self):
        buffer = module.ViewerBuffer(max_images=1, max_packets=3, preserve_video=True)
        packets = [struct.pack('<III', seq, 9, 16000) + b'AVC1video' + bytes([seq])*1280 for seq in range(4)]
        for packet in packets[:3]:self.assertTrue(buffer.put(packet))
        self.assertFalse(buffer.put(packets[3]))
        self.assertEqual(buffer.skipped_images, 0)
        for packet in packets[:3]:self.assertEqual(await buffer.get(), packet)

    async def test_shedding_keeps_map_and_pcm_together(self):
        buffer = module.ViewerBuffer(max_images=1)
        for seq in range(3):
            packet = struct.pack('<III', seq, 3, 16000) + b'jpg' + bytes([seq]) * 1280
            self.assertTrue(buffer.put(packet, {'type': 'media.map', 'packet_seq': seq}))
        for seq in range(3):
            control, packet = await buffer.get()
            self.assertEqual(control['packet_seq'], seq)
            header = struct.unpack_from('<III', packet)
            self.assertEqual(header[0], seq)
            self.assertEqual(packet[12 + header[1]:], bytes([seq]) * 1280)
        self.assertEqual(buffer.skipped_images, 2)

    async def test_cancel_is_an_explicit_barrier_and_removes_all_old_pcm(self):
        buffer = module.ViewerBuffer()
        buffer.put(struct.pack('<III', 1, 0, 16000) + b'old-audio')
        buffer.clear({'type': 'playback.cancel', 'barrier_id': 'cancel'})
        self.assertEqual((await buffer.get())['barrier_id'], 'cancel')
        self.assertEqual(len(buffer.packets), 0)

    async def test_slow_consumer_is_rejected_without_silently_cutting_pcm(self):
        buffer = module.ViewerBuffer(max_packets=1)
        packet = struct.pack('<III', 1, 0, 16000) + b'old-audio'
        self.assertTrue(buffer.put(packet)); self.assertFalse(buffer.put(packet))
        self.assertEqual(await buffer.get(), packet)


if __name__ == '__main__':
    unittest.main()
