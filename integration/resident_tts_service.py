"""One loopback broker serializes local O07/F07 synthesis and explicit failover."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse, hashlib, io, json, os, re, socket, subprocess, threading, time, traceback
import urllib.error, urllib.request, wave

ROOT = Path(__file__).resolve().parents[1]
ENGINES = {'O07': 'OmniVoice', 'F07': 'F5-TTS-v1'}


class Cancelled(Exception):
    pass


def json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    tmp.replace(path)


class Broker:
    def __init__(self, config, config_path):
        self.config, self.config_path = config, config_path
        self.guard, self.serial = threading.RLock(), threading.Lock()
        self.tasks, self.cancelled, self.children, self.workers = {}, {}, {}, {}
        self.active, self.error, self.initializing, self.recent = None, None, True, []
        self.selection_path = ROOT/'configs/tts-selection.private.json'
        self.selection = config['default_voice_id']
        if self.selection_path.is_file():
            saved = json.loads(self.selection_path.read_text('utf8'))
            if saved.get('voice_id') in ENGINES:
                self.selection = saved['voice_id']
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def rpc(self, voice, route, body=None, timeout=3):
        url = 'http://127.0.0.1:'+str(self.config['voices'][voice]['port'])+route
        data = json.dumps(body, ensure_ascii=False).encode('utf8') if body is not None else None
        request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        return self.opener.open(request, timeout=timeout)

    def poll(self, voice):
        try:
            with self.rpc(voice, '/health') as response:
                value = json.load(response)
            if value.get('engine') != ENGINES[voice] or value.get('voice_id') != voice or value.get('reference_sha256') != self.config['reference_sha256']:
                raise RuntimeError('Unexpected worker identity')
            self.workers[voice] = value
        except (OSError, ValueError, RuntimeError) as exc:
            self.workers[voice] = {'ready': False, 'voice_id': voice, 'error': type(exc).__name__}
        return self.workers[voice]

    def spawn(self, voice):
        port = self.config['voices'][voice]['port']
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError('Worker port already used; no existing process was replaced')
        spec = self.config['voices'][voice]
        env = os.environ.copy()
        env.update(PYTHONNOUSERSITE='1', PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1')
        (ROOT/'logs').mkdir(exist_ok=True)
        with (ROOT/'logs'/('tts-'+voice+'.stdout.log')).open('ab') as out, (ROOT/'logs'/('tts-'+voice+'.stderr.log')).open('ab') as err:
            child = subprocess.Popen([str(ROOT/spec['python']), '-u', '-X', 'utf8', '-B',
                str(ROOT/'integration/resident_tts_worker.py'), '--config', str(self.config_path),
                '--voice', voice, '--parent-pid', str(os.getpid())], cwd=ROOT, env=env,
                stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                creationflags=0x08000208 if os.name == 'nt' else 0)
        self.children[voice] = child
        deadline = time.monotonic()+180
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError(voice+' exited during loading')
            state = self.poll(voice)
            if state.get('error') and state['error'] not in ('URLError', 'ConnectionResetError'):
                raise RuntimeError(voice+' failed to initialize: '+state['error'])
            if state.get('ready'):
                return
            time.sleep(.5)
        raise TimeoutError(voice+' startup deadline exceeded')

    def initialize(self):
        try:
            for voice in ('O07', 'F07'):
                self.spawn(voice)
            self.error = None
        except Exception as exc:
            self.error = type(exc).__name__+': '+str(exc)
            traceback.print_exc()
        finally:
            self.initializing = False

    def status(self):
        with self.guard:
            states = dict(self.workers)
            primary_ready = bool(states.get(self.selection, {}).get('ready'))
            fallback_ready = self.selection == 'O07' and self.config['automatic_fallback'] and bool(states.get('F07', {}).get('ready'))
            ready = not self.initializing and (primary_ready or fallback_ready)
            return {'service': 'resident-tts', 'release': self.config['release'], 'ready': ready,
                'initializing': self.initializing, 'error': self.error, 'degraded': not primary_ready and fallback_ready, 'pid': os.getpid(),
                'engine': ENGINES[self.selection], 'voice_id': self.selection,
                'label': '夏栀 · 温柔清甜', 'primary_voice_id': 'O07', 'fallback_voice_id': 'F07',
                'reference_sha256': self.config['reference_sha256'], 'busy': bool(self.tasks),
                'active': self.active, 'precision': 'O07 FP16 / 32 steps; F07 FP32 / 32 NFE',
                'workers': states, 'recent': list(self.recent)}

    def select(self, voice):
        if voice not in ENGINES:
            raise ValueError('Only O07 or F07 may be selected')
        with self.guard:
            if self.tasks or self.initializing:
                raise RuntimeError('Wait until synthesis is idle before switching')
            if not self.poll(voice).get('ready'):
                raise RuntimeError('Selected worker is not ready')
            json_write(self.selection_path, {'voice_id': voice, 'updated_at': time.time(), 'release': self.config['release']})
            self.selection = voice
        return self.status()

    def cancel(self, request_id):
        with self.guard:
            self.cancelled = {k:v for k,v in self.cancelled.items() if time.monotonic()-v < 300}
            self.cancelled[request_id] = time.monotonic()
        for voice in ENGINES:
            try:
                with self.rpc(voice, '/cancel', {'request_id': request_id}, timeout=1):
                    pass
            except OSError:
                pass

    def check(self, request_id):
        with self.guard:
            if request_id in self.cancelled:
                raise Cancelled()

    def quiesce(self, voice, request_id):
        """A timed-out primary must stop before fallback can acquire GPU compute."""
        try:
            with self.rpc(voice, '/cancel', {'request_id': request_id}, timeout=1):
                pass
        except OSError:
            pass
        state = self.poll(voice)
        if state.get('busy') or (not state.get('ready') and self.children.get(voice) and self.children[voice].poll() is None):
            child = self.children.get(voice)
            if not child or child.poll() is not None:
                raise RuntimeError('Cannot establish that primary compute has stopped')
            self.stop_child(voice)
            self.poll(voice)

    def stop_child(self, voice):
        child = self.children.get(voice)
        if not child or child.poll() is not None:
            return
        if os.name == 'nt':
            # Windows venv python.exe may be a launcher with a real Python
            # descendant. Stopping just that launcher does not stop CUDA work.
            import psutil
            parent = psutil.Process(child.pid)
            owned = parent.children(recursive=True)
            expected = str(ROOT/'integration/resident_tts_worker.py').casefold()
            for process in owned:
                command = [arg.casefold() for arg in process.cmdline()]
                if expected not in command or not Path(process.exe()).resolve().is_relative_to(ROOT):
                    raise RuntimeError('Worker descendant ownership mismatch')
            for process in reversed(owned):
                try:
                    process.terminate()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(owned, timeout=10)
            if alive:
                raise RuntimeError('Worker compute has not stopped; fallback withheld')
        child.terminate()
        child.wait(timeout=10)

    def recover(self, voice):
        if voice not in ENGINES:
            raise ValueError('Unknown voice')
        with self.guard:
            if self.tasks or self.initializing:
                raise RuntimeError('Wait for idle before recovery')
            child = self.children.get(voice)
            if child and child.poll() is None:
                return self.poll(voice)
            self.initializing = True
        def run():
            try:
                self.spawn(voice)
                self.error = None
            except Exception as exc:
                self.error = type(exc).__name__+': '+str(exc)
            finally:
                self.initializing = False
        threading.Thread(target=run, daemon=True).start()
        return {'recovering': voice}

    def synthesize(self, text, request_id, requested=None, allow_fallback=True):
        with self.guard:
            self.check(request_id)
            if self.initializing:
                raise RuntimeError('Models are still initializing')
            if request_id in self.tasks:
                raise RuntimeError('Duplicate active request id')
            voice = requested or self.selection
            if voice not in ENGINES:
                raise ValueError('Unknown voice')
            self.tasks[request_id] = time.monotonic()
        start = time.monotonic()
        acquired = False
        try:
            while not acquired:
                self.check(request_id)
                acquired = self.serial.acquire(timeout=.1)
                if time.monotonic()-start > 120:
                    raise TimeoutError('Speech queue deadline exceeded')
            self.check(request_id)
            self.active = request_id
            candidates = [voice]
            if voice == 'O07' and allow_fallback and self.config['automatic_fallback']:
                candidates.append('F07')
            fallback_reason = None
            for selected in candidates:
                self.check(request_id)
                try:
                    if not self.poll(selected).get('ready'):
                        raise RuntimeError('Selected worker unavailable')
                    with self.rpc(selected, '/tts', {'text': text, 'request_id': request_id}, timeout=self.config['synthesis_timeout_seconds']) as response:
                        headers = dict(response.headers)
                        audio = response.read(32*1024*1024+1)
                    self.check(request_id)
                    if len(audio) > 32*1024*1024:
                        raise RuntimeError('Audio exceeds response limit')
                    if headers.get('X-TTS-Engine') != ENGINES[selected] or headers.get('X-TTS-Voice') != selected or headers.get('X-TTS-Reference-SHA256') != self.config['reference_sha256']:
                        raise RuntimeError('Worker voice identity mismatch')
                    with wave.open(io.BytesIO(audio), 'rb') as source:
                        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 24000) or not source.getnframes():
                            raise RuntimeError('Invalid speech waveform format')
                        duration = source.getnframes()/24000
                    metrics = {'request_id': request_id, 'requested_voice': voice, 'voice_id': selected,
                        'engine': ENGINES[selected], 'fallback': selected != voice, 'fallback_reason': fallback_reason,
                        'audio_seconds': duration, 'wall_seconds': time.monotonic()-start,
                        'model_seconds': float(headers.get('X-TTS-Model-Seconds', 0)),
                        'reference_sha256': self.config['reference_sha256'], 'audio_sha256': hashlib.sha256(audio).hexdigest()}
                    self.recent = [*self.recent[-19:], metrics]
                    print(json.dumps({'event': 'speech_ready', **metrics}, ensure_ascii=False), flush=True)
                    return audio, metrics
                except urllib.error.HTTPError as exc:
                    if exc.code == 409:
                        raise Cancelled() from exc
                    if exc.code == 400:
                        raise ValueError('Worker rejected speech text') from exc
                    fallback_reason = 'worker_http_'+str(exc.code)
                except Cancelled:
                    raise
                except (OSError, RuntimeError, ValueError, wave.Error) as exc:
                    fallback_reason = type(exc).__name__
                self.check(request_id)
                self.quiesce(selected, request_id)
                if selected == candidates[-1]:
                    raise RuntimeError('Speech failed for '+selected+'; inspect local logs')
        finally:
            if self.active == request_id:
                self.active = None
            if acquired:
                self.serial.release()
            with self.guard:
                self.tasks.pop(request_id, None)

    def close(self):
        for voice in self.children:
            try:
                self.stop_child(voice)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                traceback.print_exc()


def make_handler(broker):
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
            self.reply(200, broker.status()) if self.path == '/health' else self.reply(404, {'error': 'Unknown endpoint'})

        def do_POST(self):
            try:
                n = int(self.headers.get('Content-Length', 0))
                if not 0 < n <= 65536:
                    raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(n))
                if self.path == '/voice':
                    return self.reply(200, broker.select(data.get('voice_id')))
                if self.path == '/recover':
                    return self.reply(202, broker.recover(data.get('voice_id', 'O07')))
                rid = str(data.get('request_id', ''))
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', rid):
                    raise ValueError('Invalid request id')
                if self.path == '/cancel':
                    broker.cancel(rid)
                    return self.reply(200, {'ok': True})
                if self.path != '/tts':
                    return self.reply(404, {'error': 'Unknown endpoint'})
                text = str(data.get('text', '')).strip()
                if not 1 <= len(text) <= 1500:
                    raise ValueError('Expected 1–1500 characters')
                allow_fallback = data.get('allow_fallback', True)
                if not isinstance(allow_fallback, bool):
                    raise ValueError('allow_fallback must be a boolean')
                audio, metrics = broker.synthesize(text, rid, data.get('voice_id'), allow_fallback)
                self.send_response(200)
                self.send_header('Content-Type', 'audio/wav')
                self.send_header('Content-Length', str(len(audio)))
                for key, value in {'Engine': metrics['engine'], 'Voice': metrics['voice_id'],
                    'Requested-Voice': metrics['requested_voice'], 'Fallback': str(metrics['fallback']).lower(),
                    'Reference-SHA256': metrics['reference_sha256'], 'Wall-Seconds': metrics['wall_seconds']}.items():
                    self.send_header('X-TTS-'+key, str(value))
                self.end_headers()
                self.wfile.write(audio)
            except Cancelled:
                self.reply(409, {'cancelled': True, 'error': 'Interrupted; no fallback or playback'})
            except (ValueError, TypeError) as exc:
                self.reply(400, {'error': str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                traceback.print_exc()
                self.reply(503, {'error': 'Local speech service failed; inspect resident-tts logs'})
    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, default=ROOT/'configs/resident-tts.json')
    a = p.parse_args()
    config = json.loads(a.config.read_text('utf8'))
    broker = Broker(config, a.config.resolve())
    server = ThreadingHTTPServer(('127.0.0.1', 9880), make_handler(broker))
    server.daemon_threads = True
    threading.Thread(target=broker.initialize, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        broker.close()
        server.server_close()


if __name__ == '__main__':
    main()
