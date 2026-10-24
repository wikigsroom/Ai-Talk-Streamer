"""Resident, loopback-only MOSS-TTSD service using an existing native installation."""
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import gc
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]


class Cancelled(RuntimeError):
    pass


def split_text(text, limit=70):
    """Keep every character; bound KV-cache size without shortening the utterance."""
    pieces, current = [], ''
    for part in re.findall(r'[^。！？!?；;\n]*[。！？!?；;\n]|[^。！？!?；;\n]+$', text):
        if len(current) + len(part) > limit and current:
            pieces.append(current)
            current = ''
        while len(part) > limit:
            cut = max(part.rfind(mark, 0, limit + 1) for mark in ('，', ',', '、', ' '))
            cut = cut + 1 if cut >= limit // 3 else limit
            if current:
                pieces.append(current)
                current = ''
            pieces.append(part[:cut])
            part = part[cut:]
        current += part
    if current:
        pieces.append(current)
    assert ''.join(pieces) == text
    return pieces


class MossEngine:
    def __init__(self, config):
        self.config = config
        self.ready = False
        self.error = None
        self.loading_seconds = 0
        self.started = time.monotonic()
        self.guard = threading.Lock()
        self.serial = threading.Lock()
        self.tasks = {}
        self.cancelled_ids = OrderedDict()
        self.recent = []
        self.active = None

    def initialize(self):
        try:
            config = self.config
            runtime = (ROOT / config['runtime_root']).resolve()
            models = (ROOT / config['models_root']).resolve()
            sys.path.insert(0, str(runtime / 'vendor'))
            os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                              HF_HUB_DISABLE_TELEMETRY='1', PYTHONNOUSERSITE='1',
                              TORCHAO_FORCE_SKIP_LOADING_SO_FILES='1')
            os.environ.setdefault('HF_HOME', str(ROOT / 'cache/huggingface'))
            os.environ.setdefault('HF_MODULES_CACHE', str(ROOT / 'cache/huggingface/modules'))
            import torch
            import soundfile as sf
            import torchaudio
            from transformers import AutoConfig, AutoProcessor, BitsAndBytesConfig
            from transformers.dynamic_module_utils import get_class_from_dynamic_module
            torch.set_num_threads(config.get('cpu_threads', 8))
            self.torch, self.sf = torch, sf
            model_dir = models / 'MOSS-TTSD-v1.0'
            self.processor = AutoProcessor.from_pretrained(
                str(model_dir), codec_path=str(models / 'MOSS-Audio-Tokenizer'), trust_remote_code=True)
            self.processor.audio_tokenizer.eval().to('cpu')
            model_config = AutoConfig.from_pretrained(str(model_dir), trust_remote_code=True, local_files_only=True)
            model_class = get_class_from_dynamic_module(
                model_config.auto_map['AutoModel'], str(model_dir), local_files_only=True)
            original = model_class.get_input_embeddings

            def input_embeddings(model, input_ids=None):
                return model.language_model.get_input_embeddings() if input_ids is None else original(model, input_ids)

            model_class.get_input_embeddings = input_embeddings
            model_class.get_output_embeddings = lambda model: model.lm_heads[0]
            quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                                      bnb_4bit_compute_dtype=torch.bfloat16,
                                      bnb_4bit_use_double_quant=True, llm_int8_skip_modules=['lm_heads'])
            self.model = model_class.from_pretrained(
                str(model_dir), config=model_config, local_files_only=True,
                attn_implementation='sdpa', dtype=torch.bfloat16,
                quantization_config=quant, device_map={'': 'cuda:0'}).eval()
            # The installed MOSS generate() has no stopping_criteria argument.
            # A forward hook checks cancellation once per autoregressive step.
            def check_cancel(module, args):
                if self.active is not None and self.active.is_set():
                    raise Cancelled('Speech was interrupted')
            self.model.register_forward_pre_hook(check_cancel)
            profiles = json.loads((ROOT / config['references']).read_text(encoding='utf-8'))['profiles']
            profile = next(item for item in profiles if item['id'] == config['voice_id'])
            reference = ROOT / profile['reference']
            self.reference_sha256 = hashlib.sha256(reference.read_bytes()).hexdigest()
            self.reference_text = profile['reference_text']
            array, rate = sf.read(str(reference), dtype='float32', always_2d=True)
            audio = torch.from_numpy(array.T.copy()).mean(0, keepdim=True)
            if rate != 24000:
                audio = torchaudio.functional.resample(audio, rate, 24000)
            with torch.inference_mode():
                self.reference_codes = self.processor.encode_audios_from_wav([audio], sampling_rate=24000)[0]
                # This is the same single-speaker continuation conditioning as the audition.
                self.prompt_codes = self.processor.encode_audios_from_wav([audio], sampling_rate=24000)[0]
            gc.collect()
            torch.cuda.empty_cache()
            self.loading_seconds = round(time.monotonic() - self.started, 3)
            self.ready = True
            print(json.dumps({'event': 'ready', **self.status()}, ensure_ascii=False), flush=True)
        except Exception as exc:
            self.error = type(exc).__name__ + ': ' + str(exc)
            traceback.print_exc()

    def status(self):
        return {'ready': self.ready, 'engine': 'MOSS-TTSD-v1.0',
                'voice_id': self.config['voice_id'], 'label': self.config['label'],
                'precision': 'NF4 4-bit / BF16 compute; codec FP32 CPU',
                'reference_sha256': getattr(self, 'reference_sha256', None),
                'load_seconds': self.loading_seconds, 'busy': bool(self.tasks),
                'error': self.error, 'recent': self.recent[-8:]}

    def cancel(self, request_id):
        with self.guard:
            event = self.tasks.get(request_id)
            if event is not None:
                event.set()
            self.cancelled_ids[request_id] = True
            while len(self.cancelled_ids) > 64:
                self.cancelled_ids.popitem(last=False)

    def synthesize(self, text, request_id):
        if not self.ready:
            raise RuntimeError('MOSS is still loading' if self.error is None else 'MOSS failed to load; inspect its log')
        cancelled = threading.Event()
        with self.guard:
            if request_id in self.cancelled_ids:
                raise Cancelled('Speech was interrupted before generation')
            if len(self.tasks) >= 4:
                raise RuntimeError('Speech queue is full')
            if request_id in self.tasks:
                raise ValueError('Duplicate request ID')
            self.tasks[request_id] = cancelled
        started = time.monotonic()
        with self.serial:
            try:
                if cancelled.is_set():
                    raise Cancelled('Queued speech was interrupted')
                self.active = cancelled
                torch, processor = self.torch, self.processor
                torch.manual_seed(self.config['seed'])
                torch.cuda.manual_seed_all(self.config['seed'])
                torch.cuda.reset_peak_memory_stats()
                waves = []
                generation_seconds = decode_seconds = 0.0
                parts = split_text(text, self.config.get('segment_characters', 70))
                for part in parts:
                    if cancelled.is_set():
                        raise Cancelled('Speech was interrupted')
                    user = processor.build_user_message(
                        text='[S1] ' + self.reference_text + ' [S1] ' + part,
                        language='zh', reference=[self.reference_codes])
                    assistant = processor.build_assistant_message(audio_codes_list=[self.prompt_codes])
                    batch = processor([[user, assistant]], mode='continuation')
                    ids, mask = batch['input_ids'].to('cuda'), batch['attention_mask'].to('cuda')
                    torch.cuda.synchronize()
                    tick = time.monotonic()
                    with torch.inference_mode():
                        outputs = self.model.generate(
                            input_ids=ids, attention_mask=mask,
                            max_new_tokens=self.config.get('max_new_tokens', 800),
                            audio_temperature=self.config['temperature'], audio_top_p=self.config['top_p'],
                            audio_top_k=self.config['top_k'], audio_repetition_penalty=self.config['repetition_penalty'])
                    torch.cuda.synchronize()
                    generation_seconds += time.monotonic() - tick
                    if any(int(codes[-1, 0]) != self.model.config.im_end_token_id for _, codes in outputs):
                        raise RuntimeError('MOSS reached its token limit; no truncated speech was played')
                    outputs = [(start, codes.cpu()) for start, codes in outputs]
                    del ids, mask, batch
                    if cancelled.is_set():
                        raise Cancelled('Speech was interrupted')
                    tick = time.monotonic()
                    with torch.inference_mode():
                        messages = processor.decode(outputs)
                    decode_seconds += time.monotonic() - tick
                    segments = [audio.reshape(-1) for message in messages if message is not None
                                for audio in message.audio_codes_list if isinstance(audio, torch.Tensor)]
                    if not segments:
                        raise RuntimeError('MOSS returned no waveform')
                    waves.append(torch.cat(segments).float().cpu())
                if cancelled.is_set():
                    raise Cancelled('Speech was interrupted')
                audio = torch.cat(waves)
                if not torch.isfinite(audio).all() or not audio.numel() or float(audio.square().mean().sqrt()) < 1e-5:
                    raise RuntimeError('MOSS returned empty or invalid audio')
                # Uniform gain only. Preserve natural timing and the selected timbre.
                peak = float(audio.abs().max())
                gain = min(1.0, 0.89 / max(peak, 1e-9))
                stream = io.BytesIO()
                self.sf.write(stream, (audio * gain).numpy(), 24000, format='WAV', subtype='PCM_16')
                metrics = {'request_id': request_id, 'engine': 'MOSS-TTSD-v1.0', 'voice_id': self.config['voice_id'],
                           'characters': len(text), 'parts': len(parts), 'audio_seconds': round(audio.numel() / 24000, 3),
                           'generation_seconds': round(generation_seconds, 3), 'codec_seconds': round(decode_seconds, 3),
                           'wall_seconds': round(time.monotonic() - started, 3),
                           'peak_allocated_mib': round(torch.cuda.max_memory_allocated() / 2**20, 1), 'gain': gain}
                self.recent = [*self.recent[-7:], metrics]
                print(json.dumps({'event': 'synthesized', **metrics}), flush=True)
                return stream.getvalue(), metrics
            finally:
                self.active = None
                with self.guard:
                    self.tasks.pop(request_id, None)
                # Return transient KV-cache blocks while retaining the actual loaded model.
                if hasattr(self, 'torch'):
                    gc.collect()
                    self.torch.cuda.empty_cache()


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, value):
            data = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/health':
                return self.reply(200, engine.status())
            if self.path == '/openapi.json':
                return self.reply(200, {'openapi': '3.1.0', 'info': {'title': 'Local MOSS-TTSD', 'version': '1'}, 'paths': {'/tts': {'post': {}}}})
            self.reply(404, {'error': 'Unknown endpoint'})

        def do_POST(self):
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 65536:
                    return self.reply(400, {'error': 'Invalid request size'})
                data = json.loads(self.rfile.read(length).decode('utf-8'))
                request_id = str(data.get('request_id', ''))
                if not re.fullmatch(r'[a-zA-Z0-9_-]{1,96}', request_id):
                    return self.reply(400, {'error': 'A valid request_id is required'})
                if self.path == '/cancel':
                    engine.cancel(request_id)
                    return self.reply(200, {'ok': True, 'request_id': request_id})
                if self.path != '/tts':
                    return self.reply(404, {'error': 'Unknown endpoint'})
                text = str(data.get('text', '')).strip()
                if not 1 <= len(text) <= 1500:
                    return self.reply(400, {'error': 'Expected 1–1500 characters'})
                if re.search(r'\[S\d+\]', text):
                    return self.reply(400, {'error': 'Speaker tags are managed by the selected voice'})
                audio, metrics = engine.synthesize(text, request_id)
                self.send_response(200)
                self.send_header('Content-Type', 'audio/wav')
                self.send_header('Content-Length', str(len(audio)))
                self.send_header('X-TTS-Engine', 'MOSS-TTSD-v1.0')
                self.send_header('X-TTS-Voice', engine.config['voice_id'])
                self.send_header('X-TTS-Wall-Seconds', str(metrics['wall_seconds']))
                self.end_headers()
                self.wfile.write(audio)
            except Cancelled:
                self.reply(409, {'error': 'Speech was interrupted', 'cancelled': True})
            except (ValueError, json.JSONDecodeError) as exc:
                self.reply(400, {'error': str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                traceback.print_exc()
                self.reply(503, {'error': 'MOSS synthesis failed; inspect the local service log'})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/moss-live.json')
    parser.add_argument('--port', type=int, default=9880)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    engine = MossEngine(config)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(engine))
    server.daemon_threads = True
    threading.Thread(target=engine.initialize, daemon=True).start()
    print(json.dumps({'event': 'loading', 'engine': 'MOSS-TTSD-v1.0', 'voice_id': config['voice_id']}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
