"""Naimei's native studio adapter for the existing DSH/live-source system.

No model weights, cloud provider, platform login or public broadcast are started
here. Existing FlashHead output is mapped to the shared player protocol. Only
official-source audio playback receipts complete an utterance.
"""
from pathlib import Path
import argparse
import asyncio
from collections import Counter, deque
import hashlib
import io
import json
import math
import struct
import subprocess
import time
import uuid
import wave
import cv2
import numpy as np
from aiohttp import web, ClientSession, ClientTimeout, WSMsgType
from scipy.signal import resample_poly
from integration.character_identity import character_identity
from integration.naimei_media import parse_source, packet, SpeechMapping, CommandFence, SILENCE
from integration.naimei_text import spoken_text


class Studio:
    def __init__(self, root):
        self.root = root
        self.config = json.loads((root / 'configs/naimei/live-runtime.json').read_text('utf-8'))
        self.character = character_identity('naimei', root=root)
        self.pack = json.loads((root / self.config['asset_pack']).read_text('utf-8'))
        if self.pack.get('character_id') != 'naimei' or self.pack.get('outfit_id') != 'O01':
            raise ValueError('NAIMEI_PACK_MISMATCH')
        self.http = None
        self.viewers = {}
        self.fence = CommandFence()
        self.mapping = None
        self.command = None
        self.speech_task = None
        self.cue_task = None
        self.sequence = 0
        self.transport_id = 'naimei-' + uuid.uuid4().hex
        self.voice_id = 'NMV01'
        self.stats = Counter()
        self.events = deque(maxlen=80)
        self.captions = {}
        self.intervals = deque(maxlen=1500)
        self.sent_at = None
        self.engine_health = {}
        self.tts_health = {}
        self.stage = 'starting'
        self.state = 'idle'
        self.programme = None
        self.sfx = None
        self.sfx_sequence = 0
        self.assets = {x['id']: x for x in self.pack.get('actions', []) if x.get('runtime_enabled')}
        self.frames = {}
        self.idles = []
        self.action = None
        self.action_index = 0
        self.idle_index = 0
        self.idle_variant = 0
        self.pending = deque()
        self.transitions = deque()
        self.source_queue = asyncio.Queue(maxsize=96)
        self.last_source = time.monotonic()
        self.source_connected = False
        self.closed_bgr = cv2.imdecode(np.fromfile(root / self.character['appearance_reference'], dtype=np.uint8), cv2.IMREAD_COLOR)
        if self.closed_bgr is None or self.closed_bgr.shape[:2] != (512, 512):
            raise ValueError('NAIMEI_REFERENCE_INVALID')
        self.closed_jpeg = self.jpeg(self.closed_bgr)
        self.last_jpeg = self.closed_jpeg
        self.tasks = []

    def event(self, kind, **fields):
        self.events.append({'type': kind, 'time': time.time(), **fields})

    @staticmethod
    def jpeg(frame):
        ok, data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise ValueError('JPEG_ENCODING_FAILED')
        return data.tobytes()

    async def api(self, path, value=None):
        async with self.http.request('POST' if value is not None else 'GET', self.config['bridge_url'] + path,
                json=value, timeout=ClientTimeout(total=6)) as response:
            result = await response.json()
            if response.status >= 400:
                raise RuntimeError(result.get('error', 'DSH_REQUEST_FAILED'))
            return result

    def load_actions(self):
        ffmpeg = next((Path(self.config['shared_installation_root']) / 'tools/ffmpeg').rglob('ffmpeg.exe'))
        for aid, asset in self.assets.items():
            path = (self.root / asset['path']).resolve()
            if not path.is_relative_to(self.root) or not path.is_file():
                raise ValueError('ACTION_PATH_INVALID')
            if hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha256']:
                raise ValueError('ACTION_CHECKSUM_MISMATCH')
            capture = subprocess.Popen([str(ffmpeg), '-v', 'error', '-i', str(path),
                '-f', 'rawvideo', '-pix_fmt', 'bgr24', 'pipe:1'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=0x08000000)
            frames = []
            while True:
                raw = capture.stdout.read(512 * 512 * 3)
                if not raw:
                    break
                if len(raw) != 512 * 512 * 3:
                    raise ValueError('ACTION_SIZE_INVALID')
                bgr = np.frombuffer(raw, dtype=np.uint8).reshape(512, 512, 3)
                frames.append(self.jpeg(bgr))
            capture.stdout.close()
            if capture.wait() or len(frames) < 2:
                raise ValueError('ACTION_EMPTY')
            # All entries/exits use the exact runtime JPEG, independent of H264
            # rounding at the generated clip endpoints.
            frames[0] = frames[-1] = self.closed_jpeg
            self.frames[aid] = frames
            if asset['state'] == 'idle':
                self.idles.append(aid)
        if not self.idles:
            raise ValueError('NAIMEI_DYNAMIC_IDLE_NOT_PREPARED')

    def blend_to_closed(self, source=None):
        original = cv2.imdecode(np.frombuffer(source or self.last_jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.transitions.clear()
        for step in range(1, 6):
            if step == 5:
                self.transitions.append(self.closed_jpeg)
            else:
                self.transitions.append(self.jpeg(cv2.addWeighted(original, 1 - step / 5, self.closed_bgr, step / 5, 0)))

    def idle_frame(self):
        if self.action:
            frames = self.frames[self.action]
            if self.action_index < len(frames):
                frame = frames[self.action_index]
                self.action_index += 1
                return frame
            self.action = None
            self.state = 'idle'
            self.idle_index = 0
        frames = self.frames[self.idles[self.idle_variant % len(self.idles)]]
        frame = frames[self.idle_index % len(frames)]
        self.idle_index += 1
        if self.idle_index >= len(frames):
            self.idle_variant += 1
            self.idle_index = 0
        return frame

    async def refresh_health(self):
        while True:
            for name, url in [('engine_health', self.config['engine_url']), ('tts_health', self.config['tts_primary_url'])]:
                try:
                    async with self.http.get(url + '/health', timeout=ClientTimeout(total=2)) as response:
                        value = await response.json()
                        setattr(self, name, value if response.status == 200 else {'ready': False})
                except (OSError, asyncio.TimeoutError):
                    setattr(self, name, {'ready': False})
            self.stage = 'ready' if self.engine_health.get('ready') and self.tts_health.get('ready') else 'waiting_for_local_services'
            await asyncio.sleep(2)

    async def source_reader(self):
        while True:
            try:
                url = self.config['engine_url'].replace('http://', 'ws://') + '/api/output'
                async with self.http.ws_connect(url, heartbeat=20, max_msg_size=5 * 1024 * 1024) as ws:
                    self.source_connected = True
                    async for message in ws:
                        if message.type == WSMsgType.BINARY:
                            source = parse_source(message.data)
                            await self.source_queue.put(source)
                            self.last_source = time.monotonic()
            except (OSError, asyncio.TimeoutError, ValueError) as exc:
                self.event('source_disconnected', error=type(exc).__name__)
            finally:
                self.source_connected = False
            if self.mapping:
                await self.fail(self.mapping.command['request_id'], 'source_disconnected')
            await asyncio.sleep(1)

    async def fail(self, request_id, reason):
        if self.mapping and self.mapping.command['request_id'] == request_id:
            self.mapping = None
        self.pending.clear()
        self.blend_to_closed()
        self.state = 'idle'
        self.event('speech_failed', request_id=request_id, reason=reason)
        try:
            await self.api('/internal/failed', {'request_id': request_id})
        except RuntimeError:
            pass

    async def emit(self, jpeg, pcm=SILENCE, metadata=None):
        if metadata:
            receipt = await self.api('/internal/media-map', metadata)
            if self.fence.matches(metadata):
                metadata = {'type': 'media.map', 'protocol': 2, **metadata, 'map_revision': receipt['map_revision']}
            else:
                metadata, jpeg, pcm = None, self.closed_jpeg, SILENCE
        body = packet(self.sequence, jpeg, pcm)
        self.sequence += 1
        for ws, queue in list(self.viewers.items()):
            try:
                queue.put_nowait((metadata, body))
            except asyncio.QueueFull:
                self.stats['slow_viewer_disconnects'] += 1
                self.viewers.pop(ws, None)
                asyncio.create_task(ws.close(code=1013, message=b'Playback connection too slow'))
        now = time.perf_counter()
        if self.sent_at is not None:
            self.intervals.append(now - self.sent_at)
        self.sent_at = now
        self.stats['output_frames'] += 1
        self.last_jpeg = jpeg

    async def pump(self):
        due = time.perf_counter() + .12
        while True:
            await asyncio.sleep(max(0, due - time.perf_counter()))
            due += .04
            source = None
            try:
                source = self.source_queue.get_nowait()
            except asyncio.QueueEmpty:
                if self.mapping:
                    self.stats['source_underflows_during_speech'] += 1
            if source and self.mapping and source.epoch == self.mapping.source_epoch and source.flags & 3 and source.sample_offset < self.mapping.total_samples:
                if self.state != 'speaking' and not self.pending:
                    self.action = None
                    self.blend_to_closed()
                    self.state = 'speaking'
                self.pending.append(source)
            metadata, pcm = None, SILENCE
            if self.transitions:
                jpeg = self.transitions.popleft()
            elif self.pending and self.mapping:
                source = self.pending.popleft()
                try:
                    metadata = self.mapping.range_for(source, self.sequence, self.transport_id)
                    if metadata:
                        jpeg, pcm = source.jpeg, source.pcm
                        self.stats['speech_frames'] += 1
                        if metadata['final']:
                            self.stats['utterances_generated'] += 1
                            self.mapping = None
                            self.state = 'returning'
                            self.blend_to_closed(jpeg)
                    else:
                        jpeg = self.idle_frame()
                except ValueError as exc:
                    request_id = self.mapping.command['request_id']
                    await self.fail(request_id, str(exc))
                    jpeg = self.closed_jpeg
            else:
                if self.state == 'returning':
                    self.state = 'idle'
                    self.idle_index = 0
                jpeg = self.idle_frame()
                self.stats['idle_action_frames'] += 1
            try:
                await self.emit(jpeg, pcm, metadata)
            except (RuntimeError, OSError, asyncio.TimeoutError):
                if metadata:
                    await self.fail(metadata['request_id'], 'media_mapping_failed')
                await self.emit(self.closed_jpeg)
            lag = time.perf_counter() - due
            if lag > .2:
                self.stats['pump_delays'] += 1
                due = time.perf_counter()

    async def cancel_source(self, request_id=None):
        if self.speech_task and not self.speech_task.done():
            self.speech_task.cancel()
        if request_id:
            for name in ('tts_primary_url', 'tts_fallback_url'):
                try:
                    async with self.http.post(self.config[name] + '/cancel', json={'request_id': request_id}, timeout=ClientTimeout(total=2)):
                        pass
                except (OSError, asyncio.TimeoutError):
                    pass
        try:
            async with self.http.post(self.config['engine_url'] + '/api/interrupt', timeout=ClientTimeout(total=3)):
                pass
        except (OSError, asyncio.TimeoutError):
            pass
        self.mapping = None
        self.pending.clear()
        self.action = None
        self.blend_to_closed()

    async def broadcast_control(self, barrier):
        for queue in list(self.viewers.values()):
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(({'type': 'playback.cancel', **barrier}, None))

    async def synthesize(self, text, request_id):
        profile = json.loads((self.root / self.config['voice_profile']).read_text('utf-8'))
        voice = next(x for x in profile['voices'] if x['id'] == self.voice_id)
        if self.voice_id == 'NMV01':
            for metadata_file in (self.root / 'assets/naimei/live-v1/voice/cues').glob('*.json'):
                cached = json.loads(metadata_file.read_text('utf-8'))
                wav_path = metadata_file.with_suffix('.wav')
                if cached.get('spoken_text') == spoken_text(text) and cached.get('reference_sha256') == voice['sha256'] and wav_path.exists():
                    audio = wav_path.read_bytes()
                    if hashlib.sha256(audio).hexdigest() == cached.get('sha256'):
                        return audio, cached['engine'], {**cached, 'request_id': request_id}
        for index, name in enumerate(('tts_primary_url', 'tts_fallback_url')):
            if index:
                # A timeout is not proof that primary computation stopped.
                async with self.http.post(self.config['tts_primary_url'] + '/cancel', json={'request_id': request_id}, timeout=ClientTimeout(total=3)):
                    pass
                async with self.http.get(self.config['tts_primary_url'] + '/health', timeout=ClientTimeout(total=3)) as response:
                    if (await response.json()).get('busy'):
                        raise RuntimeError('PRIMARY_STILL_COMPUTING_NO_FALLBACK')
            try:
                async with self.http.post(self.config[name] + '/tts', json={'text': spoken_text(text), 'request_id': request_id, 'voice_id': self.voice_id}, timeout=ClientTimeout(total=110)) as response:
                    if response.status != 200:
                        raise RuntimeError('LOCAL_TTS_FAILED')
                    if response.headers.get('X-TTS-Character') != 'naimei' or response.headers.get('X-TTS-Voice') != self.voice_id or response.headers.get('X-TTS-Reference-SHA256') != voice['sha256']:
                        raise ValueError('VOICE_REFERENCE_MISMATCH')
                    audio = await response.read()
                    engine = response.headers.get('X-TTS-Engine')
                async with self.http.get(self.config[name] + '/metrics/' + request_id, timeout=ClientTimeout(total=3)) as response:
                    metrics = await response.json()
                    if response.status != 200 or metrics.get('request_id') != request_id:
                        raise ValueError('CAPTION_METRICS_MISMATCH')
                return audio, engine, metrics
            except (RuntimeError, asyncio.TimeoutError, OSError):
                if index:
                    raise
        raise RuntimeError('LOCAL_TTS_UNAVAILABLE')

    async def speech(self, command):
        rid = command['request_id']
        self.state = 'thinking'
        if 'NM-LIVE-think-side' in self.frames:
            self.action, self.action_index = 'NM-LIVE-think-side', 0
        try:
            audio, engine, metrics = await self.synthesize(command['text'], rid)
            if not self.fence.matches(command):
                return
            with wave.open(io.BytesIO(audio), 'rb') as stream:
                if stream.getsampwidth() != 2 or stream.getnchannels() != 1:
                    raise ValueError('TTS_PCM_FORMAT_INVALID')
                rate = stream.getframerate()
                pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32)
            if rate != 16000:
                factor = math.gcd(rate, 16000)
                pcm = resample_poly(pcm, 16000 // factor, rate // factor)
            pcm = np.clip(np.round(pcm), -32768, 32767).astype('<i2')
            if not len(pcm):
                raise ValueError('TTS_PCM_EMPTY')
            self.captions[rid] = {'request_id': rid, 'sample_rate': 16000, 'segments': metrics['captions'],
                                  'alignment': metrics['alignment']}
            while len(self.captions) > 32:
                del self.captions[next(iter(self.captions))]
            await self.api('/internal/audio-ready', {**command, 'valid_sample_count': len(pcm), 'audio_sha256': hashlib.sha256(pcm.tobytes()).hexdigest()})
            wav = io.BytesIO()
            with wave.open(wav, 'wb') as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(pcm.tobytes())
            async with self.http.post(self.config['engine_url'] + '/api/utterance', data=wav.getvalue(), headers={'Content-Type': 'audio/wav'}, timeout=ClientTimeout(total=8)) as response:
                result = await response.json()
                if response.status != 200 or not result.get('accepted'):
                    raise RuntimeError('FLASHHEAD_INPUT_REJECTED')
            if not self.fence.matches(command):
                return
            self.mapping = SpeechMapping(command, result['epoch'], len(pcm))
            self.event('speech_input_ready', request_id=rid, voice_id=self.voice_id, engine=engine, samples=len(pcm))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self.fence.matches(command):
                await self.fail(rid, str(exc))

    async def dsh_command(self, request):
        if request.remote not in ('127.0.0.1', '::1'):
            raise web.HTTPForbidden(text='INTERNAL_LOOPBACK_ONLY')
        value = await request.json()
        try:
            if request.match_info['action'] == 'speak':
                if not self.fence.speak(value):
                    return web.json_response({'accepted': True, 'duplicate': True})
                previous = self.command
                await self.cancel_source(previous['request_id'] if previous else None)
                self.command = value
                await self.broadcast_control({'request_id': None, 'runtime_epoch': value['runtime_epoch'], 'new_generation': value['generation'], 'reason': 'generation_advanced'})
                self.speech_task = asyncio.create_task(self.speech(value))
            elif request.match_info['action'] == 'cancel':
                if not self.fence.cancel(value):
                    return web.json_response({'accepted': False, 'reason': 'stale_or_duplicate_fence'})
                await self.cancel_source(value.get('request_id'))
                await self.broadcast_control(value)
                self.state = 'idle'
            else:
                raise web.HTTPNotFound()
        except (ValueError, KeyError):
            return web.json_response({'error': 'STALE_OR_INVALID_COMMAND'}, status=409)
        return web.json_response({'accepted': True})

    async def stream(self, request):
        ws = web.WebSocketResponse(heartbeat=20, compress=False, max_msg_size=1024)
        await ws.prepare(request)
        queue = asyncio.Queue(maxsize=100)
        self.viewers[ws] = queue
        async def send():
            while not ws.closed:
                metadata, body = await queue.get()
                if metadata:
                    await ws.send_json(metadata)
                if body is not None:
                    await ws.send_bytes(body)
        sender = asyncio.create_task(send())
        try:
            async for _message in ws:
                pass
        finally:
            self.viewers.pop(ws, None)
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        return ws

    async def status(self, _request):
        return web.json_response({'character': self.character, 'avatar': '奶妹 · O01 橙子日常装',
            'avatar_ready': bool(self.engine_health.get('ready') and self.source_connected),
            'tts_ready': bool(self.tts_health.get('ready')), 'ready': self.stage == 'ready',
            'stage': self.stage, 'state': self.state, 'viewers': len(self.viewers), 'speaking': self.mapping is not None,
            'size': 512, 'fps': 25, 'voice_id': self.voice_id, 'profile': '奶妹 · 本地声音',
            'transport': 'local_websocket_jpeg_pcm', 'transport_instance_id': self.transport_id,
            'native_windows_only': True, 'cloud_inference_allowed': False,
            'character_quality_accepted': bool(self.config.get('quality_accepted')),
            'public_broadcast_allowed': False, 'programme': self.programme, 'sfx': self.sfx,
            'actions': list(self.assets.values()), 'counters': dict(self.stats),
            'output_fps_measured': len(self.intervals) / sum(self.intervals) if self.intervals else 0,
            'source_queue_frames': self.source_queue.qsize(), 'pending_speech_frames': len(self.pending), 'events': list(self.events)})

    async def proxy(self, request):
        if request.path.startswith('/api/dsh/requests') and request.method == 'POST':
            value = await request.json()
            if value.get('mode', 'chat') != 'echo':
                return web.json_response({'error': 'NAIMEI_A01_A14_MANUAL_SPEECH_ONLY'}, status=409)
            body = json.dumps(value).encode('utf-8')
        else:
            body = await request.read()
        timeout = ClientTimeout(total=None, sock_read=60) if request.path.endswith('/events') else ClientTimeout(total=120)
        try:
            async with self.http.request(request.method, self.config['bridge_url'] + request.rel_url.path_qs, data=body,
                    headers={k: request.headers[k] for k in ('Content-Type', 'Last-Event-ID', 'Range') if k in request.headers}, timeout=timeout) as upstream:
                headers = {k: upstream.headers[k] for k in ('Content-Type', 'Content-Range', 'Accept-Ranges') if k in upstream.headers}
                response = web.StreamResponse(status=upstream.status, headers=headers)
                await response.prepare(request)
                async for chunk in upstream.content.iter_any():
                    await response.write(chunk)
                return response
        except (OSError, asyncio.TimeoutError):
            return web.json_response({'error': 'NAIMEI_BRIDGE_UNAVAILABLE'}, status=503)

    async def action_command(self, request):
        value = await request.json()
        aid = value.get('action_id')
        if aid not in self.frames:
            return web.json_response({'error': 'ACTION_NOT_AVAILABLE'}, status=400)
        if self.mapping or self.speech_task and not self.speech_task.done():
            return web.json_response({'error': 'SPEECH_IN_PROGRESS'}, status=409)
        self.action, self.action_index = aid, 0
        self.state = self.assets[aid]['state']
        self.event('action', asset_id=aid)
        return web.json_response({'accepted': True, 'action_id': aid})

    async def cue_command(self, request):
        value = await request.json()
        cues = json.loads((self.root / 'assets/naimei/live-v1/programme-cues.json').read_text('utf-8'))
        cue = next((x for x in cues if x['id'] == value.get('cue_id')), None)
        if not cue:
            return web.json_response({'error': 'CUE_NOT_FOUND'}, status=400)
        if self.cue_task and not self.cue_task.done():
            return web.json_response({'error': 'CUE_IN_PROGRESS'}, status=409)
        self.programme = cue
        async def run():
            try:
                aid = cue.get('action_before')
                if aid in self.frames and not self.mapping:
                    self.action, self.action_index = aid, 0
                    await asyncio.sleep(len(self.frames[aid]) / 25)
                result = await self.api('/api/dsh/requests', {'text': cue['text'], 'mode': 'echo', 'idempotency_key': 'cue-' + uuid.uuid4().hex})
                self.event('programme_cue', cue_id=cue['id'], request_id=result.get('request_id'))
            except (RuntimeError, OSError, asyncio.TimeoutError) as exc:
                self.event('programme_cue_failed', cue_id=cue['id'], error=str(exc))
        self.cue_task = asyncio.create_task(run())
        return web.json_response({'accepted': True, 'cue': cue})

    async def voice_command(self, request):
        value = await request.json()
        profile = json.loads((self.root / self.config['voice_profile']).read_text('utf-8'))
        if value.get('voice_id') not in {v['id'] for v in profile['voices']}:
            return web.json_response({'error': 'VOICE_ID_INVALID'}, status=400)
        if self.mapping or self.speech_task and not self.speech_task.done():
            return web.json_response({'error': 'SPEECH_IN_PROGRESS'}, status=409)
        self.voice_id = value['voice_id']
        return web.json_response({'accepted': True, 'voice_id': self.voice_id})

    async def stop_command(self, _request):
        if self.cue_task:
            self.cue_task.cancel()
            await asyncio.gather(self.cue_task, return_exceptions=True)
        result = await self.api('/api/dsh/cancel', {})
        self.action = None
        self.blend_to_closed()
        return web.json_response({'accepted': True, 'dsh': result})

    async def sfx_command(self, request):
        value = await request.json()
        if value.get('id') not in {'gentle-arrival', 'gentle-close'}:
            return web.json_response({'error': 'SFX_NOT_FOUND'}, status=400)
        self.sfx_sequence += 1
        self.sfx = {'id': value['id'], 'sequence': self.sfx_sequence, 'time': time.time()}
        return web.json_response({'accepted': True, 'sfx': self.sfx})

    async def asset(self, request):
        path = (self.root / 'assets/naimei/live-v1' / request.match_info['path']).resolve()
        base = (self.root / 'assets/naimei/live-v1').resolve()
        if not path.is_relative_to(base) or not path.is_file() or path.suffix.lower() not in {'.png', '.jpg', '.json', '.wav', '.mp4', '.srt'}:
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def caption_data(self, request):
        value = self.captions.get(request.match_info['request_id'])
        return web.json_response(value or {'error': 'CAPTIONS_NOT_READY'}, status=200 if value else 404)

    async def static(self, request):
        name = request.match_info['name']
        allowed = {'naimei.css', 'naimei.js', 'naimei-output.js', 'local-stream.js', 'browser-id.js', 'dsh-playback.js', 'room-client.js', 'room-audio.js'}
        if name not in allowed:
            raise web.HTTPNotFound()
        return web.FileResponse(self.root / 'web' / name)

    async def startup(self, _app):
        cv2.setNumThreads(1)
        await asyncio.to_thread(self.load_actions)
        self.http = ClientSession(trust_env=False)
        self.tasks = [asyncio.create_task(fn()) for fn in (self.source_reader, self.refresh_health, self.pump)]

    async def cleanup(self, _app):
        for task in self.tasks + [self.speech_task, self.cue_task]:
            if task:
                task.cancel()
        await asyncio.gather(*(task for task in self.tasks + [self.speech_task, self.cue_task] if task), return_exceptions=True)
        for ws in list(self.viewers):
            await ws.close()
        if self.http:
            await self.http.close()

    def application(self):
        app = web.Application(client_max_size=1024 * 1024)
        app.add_routes([
            web.get('/', lambda _: web.FileResponse(self.root / 'web/naimei.html')),
            web.get('/output.html', lambda _: web.FileResponse(self.root / 'web/naimei-output.html')),
            web.get('/api/studio/status', self.status), web.get('/health', self.status),
            web.get('/api/studio/stream', self.stream), web.post('/internal/dsh/{action}', self.dsh_command),
            web.post('/api/naimei/action', self.action_command), web.post('/api/naimei/cue', self.cue_command),
            web.post('/api/naimei/voice', self.voice_command),
            web.post('/api/naimei/stop', self.stop_command),
            web.post('/api/naimei/sfx', self.sfx_command),
            web.get('/api/naimei/captions/{request_id}', self.caption_data),
            web.route('*', '/api/dsh/{tail:.*}', self.proxy),
            web.get('/naimei-assets/{path:.*}', self.asset), web.get('/{name}', self.static),
        ])
        app.on_startup.append(self.startup)
        app.on_cleanup.append(self.cleanup)
        return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    studio = Studio(args.root.resolve())
    web.run_app(studio.application(), host=studio.config['host'], port=studio.config['port'], access_log=None)
