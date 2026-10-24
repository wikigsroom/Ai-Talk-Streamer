"""Exercise audio integrity and independent backpressure for slow viewers."""
import asyncio
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integration'))
from viewer_buffer import ViewerBuffer


def packet(sequence):
    picture = bytes([sequence % 251]) * 100
    pcm = struct.pack('<640h', *[(sequence * 640 + i) % 32000 for i in range(640)])
    return struct.pack('<III', sequence, len(picture), 16000) + picture + pcm


class ViewerBufferTests(unittest.IsolatedAsyncioTestCase):
    async def test_fast_viewer_gets_identical_packets(self):
        buffer = ViewerBuffer()
        for sequence in range(100):
            original = packet(sequence)
            self.assertTrue(buffer.put(original))
            self.assertEqual(await buffer.get(), original)
        self.assertEqual(buffer.skipped_images, 0)

    async def test_slow_viewer_keeps_every_audio_sample_in_order(self):
        buffer = ViewerBuffer()
        originals = [packet(sequence) for sequence in range(100)]
        for original in originals:
            self.assertTrue(buffer.put(original))
        delivered = [await buffer.get() for _ in originals]
        self.assertEqual([struct.unpack_from('<I', p)[0] for p in delivered], list(range(100)))
        self.assertEqual(b''.join(p[12 + struct.unpack_from('<I', p, 4)[0]:] for p in delivered), b''.join(p[112:] for p in originals))
        self.assertEqual(sum(bool(struct.unpack_from('<I', p, 4)[0]) for p in delivered), 3)
        self.assertEqual(buffer.skipped_images, 97)

    async def test_pending_reader_wakes(self):
        buffer = ViewerBuffer()
        reader = asyncio.create_task(buffer.get())
        await asyncio.sleep(0)
        self.assertFalse(reader.done())
        buffer.put(packet(0))
        self.assertEqual(await asyncio.wait_for(reader, 1), packet(0))

    async def test_queue_bound_refuses_without_discarding_audio(self):
        buffer = ViewerBuffer(max_packets=5)
        for sequence in range(5):
            self.assertTrue(buffer.put(packet(sequence)))
        self.assertFalse(buffer.put(packet(5)))
        self.assertEqual([struct.unpack_from('<I', await buffer.get())[0] for _ in range(5)], list(range(5)))

    async def test_slow_viewer_does_not_degrade_fast_viewer(self):
        slow, fast = ViewerBuffer(), ViewerBuffer()
        for sequence in range(30):
            original = packet(sequence)
            slow.put(original)
            fast.put(original)
            self.assertEqual(await fast.get(), original)
        self.assertEqual(slow.skipped_images, 27)
        self.assertEqual(fast.skipped_images, 0)


if __name__ == '__main__':
    unittest.main()
