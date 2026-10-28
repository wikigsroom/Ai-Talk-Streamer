"""An isolated, resident OmniVoice or F5 worker using only pinned local assets."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse, hashlib, io, json, os, re, sys, threading, time, traceback

ROOT = Path(__file__).resolve().parents[1]


class Cancelled(Exception):
    pass


def watch_parent(pid):
    """Keep a Windows process handle, so PID reuse cannot preserve orphan models."""
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        os._exit(0)
    while kernel.WaitForSingleObject(handle, 2000) == 258:
        pass
    os._exit(0)


def partition(text, limit=140):
    parts, pending = [], ''
    for piece in re.findall(r'[^。！？!?；;\n]*[。！？!?；;\n]|[^。！？!?；;\n]+$', text):
        if len(pending) + len(piece) > limit and pending:
            parts.append(pending)
            pending = ''
        while len(piece) > limit:
            parts.append(piece[:limit])
            piece = piece[limit:]
        pending += piece
    if pending:
        parts.append(pending)
    if ''.join(parts) != text:
        raise ValueError('Text partition lost content')
    return parts


def native_audio(torch, torchaudio, np, sf):
    # Existing tested Windows compatibility: no TorchCodec/DLL stack or downloads.
    def load(uri, frame_offset=0, num_frames=-1, channels_first=True, **kwargs):
        wave, rate = sf.read(uri, start=frame_offset, frames=num_frames,
                             dtype='float32', always_2d=True)
        return torch.from_numpy(wave.T.copy() if channels_first else wave.copy()), rate
    def save(uri, wave, sample_rate, channels_first=True, **kwargs):
        wave = wave.detach().float().cpu().numpy()
        opts = {'format': kwargs.get('format') or 'WAV'} if hasattr(uri, 'write') else {}
        sf.write(uri, wave.T if channels_first else wave, sample_rate, subtype='PCM_16', **opts)
    torchaudio.load, torchaudio.save = load, save
    if not hasattr(torchaudio, 'list_audio_backends'):
        torchaudio.list_audio_backends = lambda: ['soundfile']
    import sentencepiece as spm
    previous = spm.SentencePieceProcessor.LoadFromFile
    def load_sp(self, filename):
        p = Path(filename)
        return self.LoadFromSerializedProto(p.read_bytes()) if p.is_file() else previous(self, filename)
    spm.SentencePieceProcessor.LoadFromFile = load_sp


class Engine:
    def __init__(self, config, voice):
        self.config, self.voice = config, voice
        self.spec = config['voices'][voice]
        self.ready, self.error, self.active = False, None, None
        self.lock, self.guard = threading.Lock(), threading.RLock()
        self.cancelled, self.recent = {}, []

    def status(self):
        return {'service': 'resident-tts-worker', 'ready': self.ready, 'error': self.error,
                'engine': self.spec['engine'], 'voice_id': self.voice, 'pid': os.getpid(),
                'parent_pid': os.getppid(), 'busy': self.active is not None,
                'reference_sha256': self.config['reference_sha256'],
                'load_seconds': getattr(self, 'load_seconds', None), 'recent': self.recent,
                'cuda_memory': getattr(self, 'cuda_memory', None)}

    def release_idle_cache(self):
        """Return completed utterance workspaces while retaining all model weights.

        On a 10 GB card a second resident voice must not retain the first voice's
        freed activations. This runs at utterance boundaries, never per video frame.
        """
        torch = self.torch
        torch.cuda.empty_cache()
        self.cuda_memory = {'allocated_mib': torch.cuda.memory_allocated()/2**20,
                            'reserved_mib': torch.cuda.memory_reserved()/2**20}

    def initialize(self):
        try:
            started = time.monotonic()
            os.environ.update(HF_HOME=str(ROOT/'cache/tts-benchmark/huggingface'),
                TORCH_HOME=str(ROOT/'cache/tts-benchmark/torch'), HF_HUB_OFFLINE='1',
                TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='8', MKL_NUM_THREADS='8',
                NUMBA_CACHE_DIR=str(ROOT/'cache/tts-benchmark/numba'), NLTK_DATA=str(ROOT/'cache/nltk_data'))
            import numpy as np
            import soundfile as sf
            import torch, torchaudio
            self.np, self.sf, self.torch = np, sf, torch
            native_audio(torch, torchaudio, np, sf)
            torch.set_num_threads(8)
            reference = ROOT / self.config['reference_audio']
            if hashlib.sha256(reference.read_bytes()).hexdigest() != self.config['reference_sha256']:
                raise ValueError('Selected O07 reference checksum mismatch')
            source = ROOT/self.spec['source']
            sys.path[:0] = [str(source), str(source/'src')]
            ffmpeg = next((ROOT/'tools/ffmpeg').rglob('ffmpeg.exe'))
            os.environ['PATH'] = str(ffmpeg.parent)+os.pathsep+os.environ.get('PATH', '')
            model_dir = ROOT/self.spec['model']
            if self.voice == 'O07':
                from omnivoice import OmniVoice
                self.model = OmniVoice.from_pretrained(str(model_dir), device_map='cuda:0', dtype=torch.float16)
                self.prompt = self.model.create_voice_clone_prompt(
                    ref_audio=str(reference), ref_text=self.config['reference_text'])
            else:
                from f5_tts.api import F5TTS
                checkpoint = next(model_dir.rglob('model_1250000.safetensors'))
                self.model = F5TTS(model='F5TTS_v1_Base', ckpt_file=str(checkpoint),
                    vocab_file=str(checkpoint.parent/'vocab.txt'), device='cuda',
                    vocoder_local_path=str(ROOT/self.spec['vocoder']), use_ema=True)
            self.load_seconds = time.monotonic()-started
            self._generate('晚上好，我是林知夏。', 'warmup')
            torch.cuda.synchronize()
            self.release_idle_cache()
            self.ready = True
            print(json.dumps({'event': 'ready', **self.status()}, ensure_ascii=False), flush=True)
        except Exception as exc:
            self.error = type(exc).__name__+': '+str(exc)
            traceback.print_exc()

    def cancel(self, request_id):
        with self.guard:
            self.cancelled = {k:v for k,v in self.cancelled.items() if time.monotonic()-v < 300}
            self.cancelled[request_id] = time.monotonic()

    def check(self, request_id):
        with self.guard:
            if request_id in self.cancelled:
                raise Cancelled()

    def _generate(self, text, request_id):
        np, torch = self.np, self.torch
        np.random.seed(self.config['seed'])
        torch.manual_seed(self.config['seed'])
        torch.cuda.manual_seed_all(self.config['seed'])
        waves = []
        for part in partition(text):
            self.check(request_id)
            if not part.strip():
                continue
            if self.voice == 'O07':
                wave = self.model.generate(text=part, language='zh', num_step=32,
                    speed=1.0, normalize_text=False, voice_clone_prompt=self.prompt)[0]
            else:
                wave, rate, _ = self.model.infer(ref_file=str(ROOT/self.config['reference_audio']),
                    ref_text=self.config['reference_text'], gen_text=part,
                    nfe_step=32, speed=1.0, seed=self.config['seed'])
                if rate != 24000:
                    raise RuntimeError('Unexpected F5 sample rate')
            if hasattr(wave, 'detach'):
                wave = wave.detach().float().cpu().numpy()
            wave = np.asarray(wave, dtype=np.float32).reshape(-1)
            if waves:
                waves.append(np.zeros(2400, np.float32))
            waves.append(wave)
            self.check(request_id)
        return np.concatenate(waves)

    def synthesize(self, text, request_id):
        if not self.ready:
            raise RuntimeError('Worker not ready')
        with self.lock:
            self.check(request_id)
            self.active = request_id
            started = time.monotonic()
            try:
                self.torch.cuda.reset_peak_memory_stats()
                wave = self._generate(text, request_id)
                self.torch.cuda.synchronize()
                model_seconds = time.monotonic()-started
                self.check(request_id)
                np = self.np
                if not wave.size or not np.isfinite(wave).all() or float(np.sqrt(np.mean(wave*wave))) < .0001:
                    raise RuntimeError('Model returned empty, silent or non-finite audio')
                gain = min(1., .89/max(float(np.max(np.abs(wave))), 1e-9))
                stream = io.BytesIO()
                self.sf.write(stream, wave*gain, 24000, format='WAV', subtype='PCM_16')
                metrics = {'request_id': request_id, 'engine': self.spec['engine'], 'voice_id': self.voice,
                    'model_seconds': model_seconds, 'audio_seconds': len(wave)/24000,
                    'wall_seconds': time.monotonic()-started, 'gain': gain,
                    'torch_peak_allocated_mib': self.torch.cuda.max_memory_allocated()/2**20}
                self.recent = [*self.recent[-9:], metrics]
                print(json.dumps({'event': 'synthesized', **metrics}, ensure_ascii=False), flush=True)
                return stream.getvalue(), metrics
            finally:
                self.active = None
                try:
                    self.release_idle_cache()
                except Exception:
                    # Preserve the original synthesis error if the CUDA context
                    # itself failed. The broker still reports that failed request.
                    traceback.print_exc()


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, value):
            data = json.dumps(value, ensure_ascii=False).encode('utf8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.reply(200, engine.status()) if self.path == '/health' else self.reply(404, {'error': 'Unknown endpoint'})

        def do_POST(self):
            try:
                n = int(self.headers.get('Content-Length', 0))
                if not 0 < n <= 65536:
                    raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(n))
                rid = str(data.get('request_id', ''))
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', rid):
                    raise ValueError('Invalid request id')
                if self.path == '/cancel':
                    engine.cancel(rid)
                    return self.reply(200, {'ok': True})
                if self.path != '/tts':
                    return self.reply(404, {'error': 'Unknown endpoint'})
                text = str(data.get('text', '')).strip()
                if not 1 <= len(text) <= 1500:
                    raise ValueError('Expected 1–1500 characters')
                wave, metrics = engine.synthesize(text, rid)
                self.send_response(200)
                self.send_header('Content-Type', 'audio/wav')
                self.send_header('Content-Length', str(len(wave)))
                self.send_header('X-TTS-Engine', engine.spec['engine'])
                self.send_header('X-TTS-Voice', engine.voice)
                self.send_header('X-TTS-Reference-SHA256', engine.config['reference_sha256'])
                self.send_header('X-TTS-Model-Seconds', str(metrics['model_seconds']))
                self.send_header('X-TTS-Wall-Seconds', str(metrics['wall_seconds']))
                self.end_headers()
                self.wfile.write(wave)
            except Cancelled:
                self.reply(409, {'cancelled': True, 'error': 'Interrupted'})
            except (ValueError, TypeError) as exc:
                self.reply(400, {'error': str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                traceback.print_exc()
                self.reply(503, {'error': 'Worker synthesis failed'})
    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--voice', choices=['O07', 'F07'], required=True)
    p.add_argument('--parent-pid', type=int, required=True)
    a = p.parse_args()
    threading.Thread(target=watch_parent, args=(a.parent_pid,), daemon=True).start()
    config = json.loads(a.config.read_text('utf8'))
    engine = Engine(config, a.voice)
    server = ThreadingHTTPServer(('127.0.0.1', config['voices'][a.voice]['port']), make_handler(engine))
    server.daemon_threads = True
    threading.Thread(target=engine.initialize, daemon=True).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
