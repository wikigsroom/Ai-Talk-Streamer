"""Bound each viewer's JPEG backlog while retaining every queued PCM sample."""
import asyncio
from collections import deque
import struct


class ViewerBuffer:
    def __init__(self, max_images=3, max_packets=125, preserve_video=False):
        self.max_images = max_images
        self.max_packets = max_packets
        self.packets = deque()
        self.images = 0
        self.ready = asyncio.Event()
        self.skipped_images = 0
        self.preserve_video = preserve_video

    @staticmethod
    def _packet(item):
        return item[1] if isinstance(item, tuple) else None if isinstance(item, dict) else item

    def put(self, packet, control=None):
        if len(self.packets) >= self.max_packets:
            return False
        if not self.preserve_video and self.images >= self.max_images:
            for index, pending in enumerate(self.packets):
                value = self._packet(pending)
                if value is None:
                    continue
                sequence, length, rate = struct.unpack_from('<III', value)
                if length:
                    # Length zero denotes audio-only; sequence and PCM stay intact.
                    audio_only = struct.pack('<III', sequence, 0, rate) + value[12 + length:]
                    self.packets[index] = (pending[0], audio_only) if isinstance(pending, tuple) else audio_only
                    self.images -= 1
                    self.skipped_images += 1
                    break
        self.packets.append((control, packet) if control is not None else packet)
        self.images += bool(struct.unpack_from('<I', packet, 4)[0])
        self.ready.set()
        return True

    def clear(self, control=None):
        self.packets.clear()
        self.images = 0
        if control is not None:
            self.packets.append(control)
        self.ready.set()

    async def get(self):
        while not self.packets:
            self.ready.clear()
            await self.ready.wait()
        packet = self.packets.popleft()
        value = self._packet(packet)
        if value is not None:
            self.images -= bool(struct.unpack_from('<I', value, 4)[0])
        return packet
