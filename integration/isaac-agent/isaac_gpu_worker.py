"""Optional local trajectory-distance accelerator. No game inputs or decisions.

Uses an existing native Windows x64 PyTorch/CUDA environment. The x86 game
client sends one bounded, identity-fenced batch over a persistent loopback socket.
"""
from __future__ import annotations
import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import socket
import select
import struct
import threading
import time

HEADER = struct.Struct('<4sIIIiIII')
DIRECTIONS, POINTS, MAX_TRACKS = 9, 11, 256
FORECAST_VALUES = DIRECTIONS * POINTS * 2
TRACK_VALUES = POINTS * 2 + 2


def unpack_header(data):
    magic, seq, frame, seed, room, stage, count, horizon = HEADER.unpack(data)
    if magic != b'IGP1' or not 1 <= count <= MAX_TRACKS or horizon != 10:
        raise ValueError('INVALID_BOUNDED_GEOMETRY_HEADER')
    return seq, frame, seed, room, stage, count


def receive_exact(client, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = client.recv(size - len(chunks))
        if not part:
            raise EOFError('GEOMETRY_CLIENT_CLOSED')
        chunks.extend(part)
    return bytes(chunks)


def reference_distances(forecasts, tracks):
    """Independent scalar oracle, including immunity and initial-position rules."""
    result = []
    for forecast in forecasts:
        row = []
        for points, first, initial in tracks:
            previous = [points[0][axis] - forecast[0][axis] for axis in (0, 1)]
            separation = math.hypot(*previous) if initial else math.inf
            for tick in range(1, POINTS):
                relative = [points[tick][axis] - forecast[tick][axis] for axis in (0, 1)]
                segment = [relative[axis] - previous[axis] for axis in (0, 1)]
                vv = sum(value * value for value in segment)
                fraction = max(0, min(1, -sum(previous[a] * segment[a] for a in (0, 1)) / vv)) if vv > .01 else 0
                if tick >= first:
                    separation = min(separation, math.hypot(*(previous[a] + segment[a] * fraction for a in (0, 1))))
                previous = relative
            row.append(separation)
        result.append(row)
    return result


class CudaGeometry:
    def __init__(self):
        import numpy as np
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA_REQUIRED_FOR_GPU_GEOMETRY')
        torch.set_num_threads(1)
        self.np, self.torch = np, torch
        self.stream = torch.cuda.Stream(priority=0)
        self.buckets = {}
        # Warm all graphs before announcing readiness. Nothing is captured or
        # compiled inside the game callback. No model weights are involved.
        for capacity in (16, 64, MAX_TRACKS):
            size = FORECAST_VALUES + capacity * TRACK_VALUES
            host = torch.zeros(size, dtype=torch.float64, pin_memory=True)
            device = torch.zeros(size, dtype=torch.float64, device='cuda')
            self.stream.wait_stream(torch.cuda.current_stream())
            def calculate():
                forecast = device[:FORECAST_VALUES].view(DIRECTIONS, 1, POINTS, 2)
                records = device[FORECAST_VALUES:].view(capacity, TRACK_VALUES)
                tracks = records[:, :POINTS * 2].view(1, capacity, POINTS, 2)
                relative = tracks - forecast
                previous = relative[:, :, :-1]
                segment = relative[:, :, 1:] - previous
                vv = segment.square().sum(-1)
                fraction = (-(previous * segment).sum(-1) / vv.clamp_min(.01)).clamp(0, 1)
                fraction = torch.where(vv > .01, fraction, 0)
                distances = (previous + segment * fraction.unsqueeze(-1)).square().sum(-1).sqrt()
                ticks = torch.arange(1, POINTS, device='cuda').view(1, 1, -1)
                distances = distances.masked_fill(ticks < records[:, -2].view(1, -1, 1), float('inf'))
                initial = relative[:, :, 0].square().sum(-1).sqrt()
                initial = initial.masked_fill(records[:, -1].view(1, -1) == 0, float('inf'))
                return torch.minimum(distances.amin(-1), initial)
            with torch.cuda.stream(self.stream):
                for _ in range(3): calculate()
            self.stream.synchronize()
            graph = torch.cuda.CUDAGraph()
            with torch.cuda.graph(graph, stream=self.stream):
                output = calculate()
            destination = torch.empty((DIRECTIONS, capacity), dtype=torch.float64, pin_memory=True)
            self.buckets[capacity] = (host, device, graph, output, destination)
        self.requests, self.failures = 0, 0
        self.times = deque(maxlen=300)
        self.lock = threading.Lock()

    def evaluate(self, body, count):
        np = self.np
        data = np.frombuffer(body, dtype='<f8')
        if data.size != FORECAST_VALUES + count * TRACK_VALUES or not np.isfinite(data).all():
            raise ValueError('INVALID_GEOMETRY_PAYLOAD')
        records = data[FORECAST_VALUES:].reshape(count, TRACK_VALUES)
        if (np.abs(data[:FORECAST_VALUES]).max() > 8192 or np.abs(records[:, :-2]).max() > 8192
                or not np.isin(records[:, -2], np.arange(1, 12)).all()
                or not np.isin(records[:, -1], (0, 1)).all()):
            raise ValueError('OUT_OF_BOUNDS_GEOMETRY')
        capacity = next(value for value in self.buckets if value >= count)
        with self.lock:
            started = time.perf_counter()
            host, device, graph, output, destination = self.buckets[capacity]
            host_array = host.numpy()
            host_array[:data.size] = data
            host_array[data.size:] = 0
            host_array[FORECAST_VALUES:].reshape(capacity, TRACK_VALUES)[count:, -2] = 11
            with self.torch.cuda.stream(self.stream):
                device.copy_(host, non_blocking=True)
                graph.replay()
                destination.copy_(output, non_blocking=True)
            self.stream.synchronize()
            result = destination.numpy()[:, :count].copy()
            # Infinite distance is legitimate only for a projectile immune for
            # the entire horizon, with the initial-position check disabled.
            allowed_inf = (records[:, -2] == 11) & (records[:, -1] == 0)
            if np.isnan(result).any() or (np.isinf(result) & ~allowed_inf[None, :]).any():
                raise ValueError('INVALID_GPU_DISTANCE')
            self.requests += 1
            self.times.append((time.perf_counter() - started) * 1000)
            return result.astype('<f8', copy=False).tobytes()

    def health(self):
        values = sorted(self.times)
        return {'ready': True, 'backend': 'torch_cuda_graph_fp64', 'gpu': self.torch.cuda.get_device_name(),
                'requests': self.requests, 'failures': self.failures, 'samples': len(values),
                'compute_roundtrip_median_ms': values[len(values)//2] if values else None,
                'compute_roundtrip_p95_ms': values[max(0, math.ceil(len(values)*.95)-1)] if values else None,
                'allocated_bytes': self.torch.cuda.memory_allocated(),
                'reserved_bytes': self.torch.cuda.memory_reserved(),
                'scope': 'geometry_only_no_items_no_input_no_strategic_model'}


def serve(port=9536, health_port=9537, stop_event=None):
    if port == health_port or not all(1024 <= value <= 65535 for value in (port, health_port)):
        raise ValueError('DISTINCT_LOCAL_USER_PORTS_REQUIRED')
    stop = stop_event or threading.Event()
    backend = CudaGeometry()
    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/health': self.send_error(404); return
            body = json.dumps(backend.health()).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *_): pass
    health = ThreadingHTTPServer(('127.0.0.1', health_port), Health)
    threading.Thread(target=health.serve_forever, daemon=True).start()
    stop_file = os.environ.get('ISSAC_STOP_FILE')
    def watch():
        while not stop.wait(.2):
            if stop_file and Path(stop_file).is_file(): stop.set()
    threading.Thread(target=watch, daemon=True).start()
    try:
        with socket.socket() as server:
            server.bind(('127.0.0.1', port)); server.listen(1); server.settimeout(.5)
            while not stop.is_set():
                try: client, _ = server.accept()
                except socket.timeout: continue
                with client:
                    client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    client.settimeout(.1)
                    while not stop.is_set():
                        try:
                            if not select.select([client], [], [], .2)[0]: continue
                            header = receive_exact(client, HEADER.size)
                            *_, count = unpack_header(header)
                            body = receive_exact(client, 8 * (FORECAST_VALUES + count * TRACK_VALUES))
                            result = backend.evaluate(body, count)
                            client.sendall(b'IGR1' + header[4:] + result)
                        except socket.timeout:
                            # A partially received request must never become a
                            # new request. Closing also discards stale replies.
                            break
                        except (EOFError, ConnectionError): break
                        except Exception:
                            backend.failures += 1
                            break
    finally:
        health.shutdown(); health.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=9536)
    parser.add_argument('--health-port', type=int, default=9537)
    options = parser.parse_args()
    serve(options.port, options.health_port)
