"""Bound each viewer's JPEG backlog while retaining every queued PCM sample."""
import asyncio
from collections import deque
import struct


class ViewerBuffer:
    def __init__(self, max_images=3, max_packets=125):
        self.max_images = max_images
        self.max_packets = max_packets
        self.packets = deque()
        self.images = 0
        self.ready = asyncio.Event()
        self.skipped_images = 0

    def put(self, packet):
        if len(self.packets) >= self.max_packets:
            return False
        if self.images >= self.max_images:
            for index, pending in enumerate(self.packets):
                sequence, length, rate = struct.unpack_from('<III', pending)
                if length:
                    # Length zero denotes audio-only; sequence and PCM stay intact.
                    self.packets[index] = struct.pack('<III', sequence, 0, rate) + pending[12 + length:]
                    self.images -= 1
                    self.skipped_images += 1
                    break
        self.packets.append(packet)
        self.images += bool(struct.unpack_from('<I', packet, 4)[0])
        self.ready.set()
        return True

    async def get(self):
        while not self.packets:
            self.ready.clear()
            await self.ready.wait()
        packet = self.packets.popleft()
        self.images -= bool(struct.unpack_from('<I', packet, 4)[0])
        return packet
