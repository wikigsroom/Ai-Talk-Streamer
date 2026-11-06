"""Native local speech using Naimei's frozen, single merged-reference voice."""
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
from integration.naimei_voice_contract import load_profile, voice_for_engine


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


class VoiceWorker:
    def __init__(self, root, shared, engine):
        self.root, self.shared, self.engine = root, shared, engine
        self.pack = root / 'assets/naimei/live-v1'
        self.profile = load_profile(root)
        self.voice = voice_for_engine(self.profile, engine)
        self.voice_id = self.voice['id']
        self.model_config = json.loads((root / self.profile['model_configuration']).read_text('utf-8'))
        self.spec = self.model_config['voices'][self.voice_id]
        self.reference = root / self.voice['reference']
        self.reference_text = self.voice['reference_text']
        self.seed = self.profile['seed']
        self.loaded_precision = None
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
            'engine': self.engine, 'voice_id': self.voice_id, 'busy': self.active is not None,
            'active_request': self.active, 'error': self.error, 'recent': self.recent[-8:],
            'reference_sha256': self.voice['sha256'], 'steps': self.spec['steps'],
            'precision': self.loaded_precision, 'model': self.spec['model'], 'seed': self.seed,
            'voice_freeze_id': self.profile.get('freeze_id'),
            'reference_preprocess_prompt': self.voice.get('preprocess_prompt', True),
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
            source = self.shared / self.spec['source']
            sys.path[:0] = [str(source), str(source / 'src')]
            ffmpeg = next((self.shared / 'tools/ffmpeg').rglob('ffmpeg.exe'))
            os.environ['PATH'] = str(ffmpeg.parent) + os.pathsep + os.environ.get('PATH', '')
            if self.engine == 'OmniVoice':
                from omnivoice import OmniVoice
                self.model = OmniVoice.from_pretrained(str(self.shared / self.spec['model']), device_map='cuda:0', dtype=torch.float16)
                self.prompts[self.voice_id] = self.model.create_voice_clone_prompt(ref_audio=str(self.reference),
                    ref_text=self.reference_text, preprocess_prompt=self.voice.get('preprocess_prompt', True))
                self.loaded_precision = str(next(self.model.parameters()).dtype)
            else:
                from f5_tts.api import F5TTS
                from f5_tts.infer.utils_infer import load_checkpoint
                checkpoint = next((self.shared / self.spec['model']).rglob('model_1250000.safetensors'))
                self.model = F5TTS(model='F5TTS_v1_Base', ckpt_file=str(checkpoint), vocab_file=str(checkpoint.parent / 'vocab.txt'),
                    device='cuda', vocoder_local_path=str(self.shared / self.spec['vocoder']), use_ema=True)
                # F5's CUDA default is FP16. Reload the original checkpoint in
                # the approved FP32 precision rather than upcasting rounded weights.
                self.model.ema_model = load_checkpoint(self.model.ema_model, str(checkpoint),
                    'cuda', dtype=torch.float32, use_ema=True)
                self.loaded_precision = str(next(self.model.ema_model.parameters()).dtype)
            if self.loaded_precision != ('torch.float16' if self.spec['precision'] == 'FP16' else 'torch.float32'):
                raise RuntimeError('APPROVED_MODEL_PRECISION_MISMATCH')
            self.ready = True
            torch.cuda.empty_cache()
            print(json.dumps({'event': 'voice.ready', **self.health()}, ensure_ascii=False), flush=True)
        except Exception as exc:
            self.error = type(exc).__name__ + ': ' + str(exc)
            traceback.print_exc()

    def synthesize(self, text, request_id, voice_id=None):
        if not self.ready:
            raise RuntimeError('VOICE_NOT_READY')
        voice_id = voice_id or self.voice_id
        if voice_id != self.voice_id:
            raise ValueError('VOICE_ID_INVALID')
        with self.lock:
            self.check(request_id)
            self.active = request_id
            started = time.monotonic()
            try:
                text = spoken_text(text)
                self.np.random.seed(self.seed)
                self.torch.manual_seed(self.seed)
                self.torch.cuda.manual_seed_all(self.seed)
                waves, captions, sample_position = [], [], 0
                for part in segments(text, limit=36):
                    self.check(request_id)
                    if self.engine == 'OmniVoice':
                        audio = self.model.generate(text=part, language='zh', voice_clone_prompt=self.prompts[voice_id],
                            num_step=self.spec['steps'], speed=self.profile['speed'], normalize_text=False)[0]
                    else:
                        audio, rate, _ = self.model.infer(ref_file=str(self.reference),
                            ref_text=self.reference_text, gen_text=part, nfe_step=self.spec['steps'], speed=self.profile['speed'], seed=self.seed)
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
                metrics = {'request_id': request_id, 'character_id': 'naimei', 'engine': self.engine, 'voice_id': voice_id,
                    'reference_sha256': hashlib.sha256(self.reference.read_bytes()).hexdigest(),
                    'precision': self.loaded_precision, 'steps': self.spec['steps'], 'seed': self.seed, 'model': self.spec['model'],
                    'voice_freeze_id': self.profile.get('freeze_id'),
                    'reference_preprocess_prompt': self.voice.get('preprocess_prompt', True),
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
            audio, metrics = await asyncio.to_thread(worker.synthesize, text, rid, data.get('voice_id'))
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
