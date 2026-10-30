"""Native local Naimei voice design + reference-locked speech, on separate ports.

Only installed OmniVoice/F5 weights and their existing Python environments are
read. New references/caches belong to the Naimei installation, never female-A.
"""
from pathlib import Path
import argparse
import asyncio
import hashlib
import importlib.util
import io
import json
import os
import threading
import time
import traceback
from aiohttp import web
from integration.naimei_text import spoken_text, segments

DESIGNS = [
    ('NMV01', '橙光暖甜', 'female, moderate pitch'),
    ('NMV02', '元气清亮', 'female, high pitch'),
    ('NMV03', '柔和陪伴', 'female, low pitch'),
]
REFERENCE_TEXT = '大家好，我是奶妹。今天也想陪你，慢慢聊一会儿。'


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


class VoiceWorker:
    def __init__(self, root, shared, engine):
        self.root, self.shared, self.engine = root, shared, engine
        self.pack = root / 'assets/naimei/live-v1'
        self.ready = False
        self.error = None
        self.active = None
        self.cancelled = set()
        self.guard = threading.RLock()
        self.lock = threading.Lock()
        self.prompts = {}
        self.recent = []

    def health(self):
        return {'service': 'naimei-voice', 'character_id': 'naimei', 'ready': self.ready,
            'engine': self.engine, 'voice_id': 'NMV01', 'busy': self.active is not None,
            'active_request': self.active, 'error': self.error, 'recent': self.recent[-8:],
            'cloud_inference_allowed': False, 'new_model_weight_bytes': 0}

    def check(self, request_id):
        with self.guard:
            if request_id in self.cancelled:
                raise RuntimeError('SPEECH_CANCELLED')

    def initialize(self):
        try:
            os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1',
                HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false',
                HF_HOME=str(self.root / 'cache/voice/huggingface'), TORCH_HOME=str(self.root / 'cache/voice/torch'),
                NUMBA_CACHE_DIR=str(self.root / 'cache/voice/numba'), NLTK_DATA=str(self.shared / 'cache/nltk_data'),
                OMP_NUM_THREADS='6', MKL_NUM_THREADS='6')
            import sys
            import torch
            import torchaudio
            import numpy as np
            import soundfile as sf
            self.torch, self.np, self.sf = torch, np, sf
            spec = importlib.util.spec_from_file_location('naimei_native_audio_compat', self.shared / 'integration/resident_tts_worker.py')
            compat = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(compat)
            compat.native_audio(torch, torchaudio, np, sf)
            torch.set_num_threads(6)
            source = self.shared / ('src/tts-benchmark/omnivoice' if self.engine == 'OmniVoice' else 'src/tts-benchmark/f5')
            sys.path[:0] = [str(source), str(source / 'src')]
            ffmpeg = next((self.shared / 'tools/ffmpeg').rglob('ffmpeg.exe'))
            os.environ['PATH'] = str(ffmpeg.parent) + os.pathsep + os.environ.get('PATH', '')
            if self.engine == 'OmniVoice':
                from omnivoice import OmniVoice
                self.model = OmniVoice.from_pretrained(str(self.shared / 'models/tts-benchmark/omnivoice'), device_map='cuda:0', dtype=torch.float16)
                self.make_references()
                for voice_id, _, _ in DESIGNS:
                    path = self.pack / 'voice' / (voice_id + '-reference.wav')
                    self.prompts[voice_id] = self.model.create_voice_clone_prompt(ref_audio=str(path), ref_text=REFERENCE_TEXT)
            else:
                from f5_tts.api import F5TTS
                checkpoint = next((self.shared / 'models/tts-benchmark/f5').rglob('model_1250000.safetensors'))
                self.model = F5TTS(model='F5TTS_v1_Base', ckpt_file=str(checkpoint), vocab_file=str(checkpoint.parent / 'vocab.txt'),
                    device='cuda', vocoder_local_path=str(self.shared / 'models/tts-benchmark/vocos-mel24'), use_ema=True)
                if not (self.pack / 'voice/NMV01-reference.wav').is_file():
                    raise RuntimeError('NAIMEI_REFERENCE_NOT_PREPARED')
            self.ready = True
            torch.cuda.empty_cache()
            print(json.dumps({'event': 'voice.ready', **self.health()}, ensure_ascii=False), flush=True)
        except Exception as exc:
            self.error = type(exc).__name__ + ': ' + str(exc)
            traceback.print_exc()

    def make_references(self):
        voices = []
        for index, (voice_id, label, instruction) in enumerate(DESIGNS):
            path = self.pack / 'voice' / (voice_id + '-reference.wav')
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                self.torch.manual_seed(2026103101 + index)
                self.torch.cuda.manual_seed_all(2026103101 + index)
                audio = self.model.generate(text=REFERENCE_TEXT, language='zh', instruct=instruction, num_step=32, speed=1.0, normalize_text=False)[0]
                audio = self.np.asarray(audio, dtype=self.np.float32).reshape(-1)
                if not audio.size or not self.np.isfinite(audio).all() or self.np.max(self.np.abs(audio)) < .005:
                    raise RuntimeError('VOICE_DESIGN_INVALID')
                audio *= min(1.0, .89 / max(float(self.np.max(self.np.abs(audio))), 1e-8))
                self.sf.write(str(path), audio, 24000, subtype='PCM_16')
            voices.append({'id': voice_id, 'label': label, 'instruction': instruction,
                'reference': path.relative_to(self.root).as_posix(), 'reference_text': REFERENCE_TEXT,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'seed': 2026103101 + index})
        save_json(self.pack / 'voice/profile.json', {'schema_version': 1, 'character_id': 'naimei',
            'default_voice_id': 'NMV01', 'label': '奶妹 · 橙光暖甜', 'engine': 'OmniVoice',
            'fallback_engine': 'F5-TTS-v1', 'fallback_voice_id': 'NMV01', 'fallback_requires_stopped_primary_request': True,
            'voice_origin': 'local OmniVoice instruction-based voice design; no female-A reference reused',
            'reference_text': REFERENCE_TEXT, 'voices': voices, 'sample_rate': 24000,
            'steps': 32, 'speed': 1.0, 'seed': 2026103114,
            'user_audition_confirmed': False, 'new_model_weight_bytes': 0, 'cloud_inference_allowed': False})

    def synthesize(self, text, request_id, voice_id='NMV01'):
        if not self.ready:
            raise RuntimeError('VOICE_NOT_READY')
        if voice_id not in {x[0] for x in DESIGNS}:
            raise ValueError('VOICE_ID_INVALID')
        with self.lock:
            self.check(request_id)
            self.active = request_id
            started = time.monotonic()
            try:
                text = spoken_text(text)
                self.torch.manual_seed(2026103114)
                self.torch.cuda.manual_seed_all(2026103114)
                waves, captions, sample_position = [], [], 0
                for part in segments(text, limit=36):
                    self.check(request_id)
                    if self.engine == 'OmniVoice':
                        audio = self.model.generate(text=part, language='zh', voice_clone_prompt=self.prompts[voice_id],
                            num_step=32, speed=1.0, normalize_text=False)[0]
                    else:
                        audio, rate, _ = self.model.infer(ref_file=str(self.pack / 'voice' / (voice_id + '-reference.wav')),
                            ref_text=REFERENCE_TEXT, gen_text=part, nfe_step=32, speed=1.0, seed=2026103114)
                        if rate != 24000:
                            raise RuntimeError('VOICE_RATE_INVALID')
                    audio = self.np.asarray(audio, dtype=self.np.float32).reshape(-1)
                    if not audio.size or not self.np.isfinite(audio).all():
                        raise RuntimeError('VOICE_AUDIO_INVALID')
                    if waves:
                        waves.append(self.np.zeros(2400, dtype=self.np.float32))
                        sample_position += 2400
                    captions.append({'text': part, 'sample_start': sample_position * 2 // 3,
                                     'sample_end': (sample_position + len(audio)) * 2 // 3})
                    waves.append(audio)
                    sample_position += len(audio)
                self.check(request_id)
                audio = self.np.concatenate(waves)
                if float(self.np.sqrt(self.np.mean(audio ** 2))) < .0001:
                    raise RuntimeError('VOICE_SILENT_OUTPUT')
                audio *= min(1., .89 / max(float(self.np.max(self.np.abs(audio))), 1e-8))
                stream = io.BytesIO()
                self.sf.write(stream, audio, 24000, format='WAV', subtype='PCM_16')
                reference = self.pack / 'voice' / (voice_id + '-reference.wav')
                metrics = {'request_id': request_id, 'character_id': 'naimei', 'engine': self.engine, 'voice_id': voice_id,
                    'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
                    'audio_seconds': len(audio) / 24000, 'wall_seconds': time.monotonic() - started, 'spoken_text': text,
                    'captions': captions, 'caption_sample_rate': 16000, 'alignment': 'actual_generated_segment_boundaries'}
                self.recent.append(metrics)
                self.recent = self.recent[-16:]
                return stream.getvalue(), metrics
            finally:
                self.active = None
                self.torch.cuda.empty_cache()


async def serve(root, shared, engine, port):
    worker = VoiceWorker(root, shared, engine)
    app = web.Application(client_max_size=32 * 1024)
    async def health(_request):
        return web.json_response(worker.health())
    async def tts(request):
        data = await request.json()
        text = spoken_text(data.get('text', ''))
        rid = str(data.get('request_id', ''))
        if not rid or len(rid) > 160:
            return web.json_response({'error': 'REQUEST_ID_REQUIRED'}, status=400)
        if worker.active:
            return web.json_response({'error': 'VOICE_BUSY'}, status=409)
        try:
            audio, metrics = await asyncio.to_thread(worker.synthesize, text, rid, data.get('voice_id', 'NMV01'))
            return web.Response(body=audio, content_type='audio/wav', headers={
                'X-TTS-Engine': worker.engine, 'X-TTS-Voice': metrics['voice_id'],
                'X-TTS-Character': 'naimei', 'X-TTS-Reference-SHA256': metrics['reference_sha256'],
                'X-TTS-Wall-Seconds': str(metrics['wall_seconds'])})
        except (RuntimeError, ValueError) as exc:
            return web.json_response({'error': str(exc)}, status=503)
    async def cancel(request):
        data = await request.json()
        with worker.guard:
            worker.cancelled.add(str(data.get('request_id', '')))
        return web.json_response({'accepted': True, 'still_computing': worker.active == data.get('request_id')})
    async def metrics(request):
        result = next((x for x in reversed(worker.recent) if x['request_id'] == request.match_info['request_id']), None)
        return web.json_response(result or {'error': 'METRICS_NOT_FOUND'}, status=200 if result else 404)
    app.add_routes([web.get('/health', health), web.post('/tts', tts), web.post('/cancel', cancel),
                    web.get('/metrics/{request_id}', metrics)])
    async def startup(_app):
        threading.Thread(target=worker.initialize, daemon=True, name='naimei-voice-init').start()
    app.on_startup.append(startup)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, '127.0.0.1', port).start()
    await asyncio.Event().wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--shared-root', type=Path, required=True)
    parser.add_argument('--engine', choices=['OmniVoice', 'F5-TTS-v1'], default='OmniVoice')
    parser.add_argument('--port', type=int, default=9891)
    args = parser.parse_args()
    asyncio.run(serve(args.root.resolve(), args.shared_root.resolve(), args.engine, args.port))
