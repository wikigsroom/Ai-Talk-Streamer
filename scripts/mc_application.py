"""Native MC application lifecycle. Observations never grant AUTO or broadcast authority."""
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import hashlib
import io
import json
import math
import re
import socket
import subprocess
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

from native_operation import OperationError, operation, read_json, safe_path
from native_windows_process import identity_alive

ROOT = Path(__file__).resolve().parents[1]


class ApplicationError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise ApplicationError(code)


def startup_diagnostic(error, stage, elapsed_ms):
    """Expose code locations and fixed reason codes, never exception text or locals."""
    chain, seen = [], set()
    while error is not None and id(error) not in seen and len(chain) < 4:
        seen.add(id(error))
        category = next((kind.__name__ for kind in (
            subprocess.TimeoutExpired, subprocess.CalledProcessError, TimeoutError,
            ConnectionError, OSError, ValueError, KeyError, TypeError, RuntimeError)
            if isinstance(error, kind)), 'Exception')
        item = {'type': category, 'frames': []}
        if type(error).__module__ in {'mc_application', 'native_operation', 'start_studio', 'mc_deployment'}:
            code = getattr(error, 'code', None) or (error.args[0] if len(error.args) == 1 else None)
            if isinstance(code, str) and re.fullmatch(r'(?:MC|STUDIO)_[A-Z0-9_]{1,90}', code):
                item['reason_code'] = code
        for frame, line in traceback.walk_tb(error.__traceback__):
            try:
                name = Path(frame.f_code.co_filename).resolve().relative_to(ROOT)
            except (OSError, ValueError):
                continue
            if name.parts[0] in ('scripts', 'integration'):
                item['frames'].append({'file': name.as_posix(), 'line': line,
                                       'function': frame.f_code.co_name})
        item['frames'] = item['frames'][-8:]
        if isinstance(error, OSError):
            for key in ('errno', 'winerror'):
                value = getattr(error, key, None)
                if type(value) is int:
                    item[key] = value
        chain.append(item)
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return {'stage': stage, 'elapsed_ms': elapsed_ms, 'exception_chain': chain}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NativeServices:
    """Compose existing guarded entry points; do not launch unmanaged game/client/model processes."""
    PORTS = {'dsh': 3092, 'avatar': 8010, 'tts': 9880, 'receiver': 8020, 'vision': 8019}
    SCRIPTS = {'dsh': 'backend/dsh-bridge/server.mjs', 'avatar': 'src/LiveTalking/app.py',
               'tts': 'integration/resident_tts_service.py', 'receiver': 'scripts/receiver_service.py',
               'minecraft': 'scripts/mc_game_service.py', 'vision': 'scripts/mc_vision_service.py'}

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.pins = {}
        self.startup_progress = None

    @property
    def candidate_mode(self):
        path = self.root / 'configs/mc-dsh-candidate.private.json'
        return path.is_file() and json.loads(path.read_text(encoding='utf-8'))['enabled'] is True

    def config(self, name):
        path = safe_path(self.root, self.root / 'configs' / name)
        require(path.is_file() and path.stat().st_size <= 65536, 'MC_APPLICATION_CONFIG_UNAVAILABLE')
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        require(isinstance(value, dict), 'MC_APPLICATION_CONFIG_INVALID')
        return value

    def guard(self):
        # Imported only for a real start. Status never imports an inference engine.
        from deployment_target import validate_target
        from launch import require_prepared
        require(self.root == ROOT, 'MC_APPLICATION_ROOT_MISMATCH')
        validate_target(self.root)
        require_prepared()
        studio = self.config('livetalking.yaml')
        require(studio.get('tts') == 'resident-local' and bool(studio.get('TTS_REFERENCE_SHA256')),
                'MC_APPLICATION_APPROVED_VOICE_REQUIRED')
        self.receiver_config()
        self.vision_lock(verify=True)
        from mc_game_service import configuration
        configuration(self.root)
        for name in self.PORTS:
            self.ownership(name, reject=True)
        self.ownership('minecraft', reject=True)

    def receiver_config(self):
        value = self.config('receiver.private.json')
        from receiver_control import validate_config
        value = validate_config(value)
        require(value.get('port') == 8020 and value.get('bind') == '127.0.0.1'
                and value.get('upstream') == 'http://127.0.0.1:8010', 'MC_APPLICATION_RECEIVER_TOPOLOGY')
        executable = Path(value.get('client_executable', ''))
        require(executable.is_absolute() and executable.is_file() and executable.name.casefold() == 'livehime.exe',
                'MC_APPLICATION_OFFICIAL_CLIENT_UNAVAILABLE')
        return value

    def registry(self, name):
        if name in ('minecraft', 'vision'):
            return self.root / ('.setup/mc-game-owner.json' if name == 'minecraft' else '.setup/mc-vision-owner.json'), None
        if name in ('avatar', 'tts'):
            return self.root / '.setup/services.json', name
        return self.root / ('.setup/dsh-process.json' if name == 'dsh' else 'outputs/receiver/process.json'), None

    def ownership(self, name, reject=False):
        try:
            import psutil
            return self._ownership(name, reject)
        except ImportError:
            raise ApplicationError('MC_APPLICATION_PROCESS_INSPECTION_UNAVAILABLE') from None
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            raise ApplicationError('MC_APPLICATION_OWNERSHIP_CHANGED_OR_UNAVAILABLE') from None

    def _ownership(self, name, reject=False):
        path, key = self.registry(name)
        data = read_json(safe_path(self.root, path))
        record = data.get(key, {}) if key else data
        alive = False
        if record:
            require(isinstance(record, dict) and type(record.get('pid')) is int,
                    'MC_APPLICATION_OWNERSHIP_INVALID')
            if 'creation_ticks' in record:
                alive = identity_alive(record)
            else:
                import psutil
                require(not psutil.pid_exists(record['pid']), 'MC_APPLICATION_LEGACY_OWNER_REQUIRES_REVIEW')
        if alive:
            import psutil
            process = psutil.Process(record['pid'])
            command = record.get('command', [])
            expected = str((self.root / self.SCRIPTS[name]).resolve()).casefold()
            actual = [str(arg).replace('/', '\\').casefold() for arg in process.cmdline()]
            require(isinstance(command, list) and bool(command)
                    and Path(process.exe()).resolve() == Path(command[0]).resolve()
                    and expected in actual, 'MC_APPLICATION_OWNERSHIP_MISMATCH')
            if name == 'dsh':
                require(str(self.root).casefold() in actual, 'MC_APPLICATION_OWNERSHIP_MISMATCH')
        occupied = False
        if name in self.PORTS:
            with socket.socket() as probe:
                probe.settimeout(.1)
                occupied = probe.connect_ex(('127.0.0.1', self.PORTS[name])) == 0
        listener_owned = False
        if occupied and alive:
            family = {process.pid, *(p.pid for p in process.children(recursive=True))}
            listener_owned = any(c.status == psutil.CONN_LISTEN and c.laddr.port == self.PORTS[name]
                                 and c.pid in family for c in psutil.net_connections(kind='tcp'))
        if reject:
            require(not occupied or listener_owned, 'MC_APPLICATION_PORT_NOT_OWNED')
        return {'owned': alive, 'port_open': occupied, 'listener_owned': listener_owned,
                'record': record, 'path': path, 'key': key}

    def get(self, url, timeout=1.5):
        with self.http.open(url, timeout=timeout) as reply:
            require(reply.status == 200, 'MC_APPLICATION_HTTP_STATUS')
            data = reply.read(65537)
        require(len(data) <= 65536, 'MC_APPLICATION_RESPONSE_TOO_LARGE')
        value = json.loads(data)
        require(isinstance(value, dict), 'MC_APPLICATION_RESPONSE_INVALID')
        return value

    def post(self, url, value, timeout=120):
        request = urllib.request.Request(url, data=json.dumps(value).encode('utf-8'),
                                         headers={'Content-Type': 'application/json'})
        with self.http.open(request, timeout=timeout) as reply:
            require(reply.status == 200, 'MC_APPLICATION_HTTP_STATUS')
            data = reply.read(65537)
        require(len(data) <= 65536, 'MC_APPLICATION_RESPONSE_TOO_LARGE')
        result = json.loads(data)
        require(isinstance(result, dict), 'MC_APPLICATION_RESPONSE_INVALID')
        return result

    def ensure_channel_compatibility(self):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            owner = self.ownership('dsh', reject=True)
            require(owner['owned'], 'MC_APPLICATION_DSH_EXITED_DURING_START')
            if owner['listener_owned']:
                try:
                    health = self.get('http://127.0.0.1:3092/health')
                except (OSError, ValueError):
                    health = {}
                if health.get('process_alive') and health.get('dsh_ready'):
                    if health.get('persona_injection_ready') is True:
                        return
                    channel = health.get('channel', {})
                    require(channel.get('configured') and channel.get('has_key'),
                            'MC_APPLICATION_SELECTED_CHANNEL_NOT_CONFIGURED')
                    receipt = self.post('http://127.0.0.1:3092/api/dsh/probe', {})
                    require(receipt.get('passed') is True, 'MC_APPLICATION_CHANNEL_COMPATIBILITY_FAILED')
                    return
            time.sleep(.2)
        raise ApplicationError('MC_APPLICATION_DSH_START_TIMEOUT')

    def vision_lock(self, verify=False):
        lock = self.config('mc-vision.json')
        if lock.get('schema_version') == 2:
            require(set(lock) == {'schema_version','provider','model','observe_interval_ms'}
                    and lock.get('provider') == 'studio_channel' and lock.get('model') == 'gpt-6-luna'
                    and type(lock.get('observe_interval_ms')) is int and 10000 <= lock['observe_interval_ms'] <= 120000,
                    'MC_APPLICATION_VISION_CHANNEL_CONFIG')
            # The existing private studio channel is the sole credential source.
            # Status/guard never sends a paid image probe or starts a local model.
            values = {}
            for line in safe_path(self.root,self.root/'configs/channel.env').read_text(encoding='utf-8-sig').splitlines():
                if line.startswith('AVATAR_LLM_') and '=' in line:
                    key,value=line.split('=',1); values[key.strip()]=value.strip()
            require(values.get('AVATAR_LLM_MODEL') == lock['model'] and bool(values.get('AVATAR_LLM_API_KEY'))
                    and values.get('AVATAR_LLM_PROTOCOL','chat_completions') in ('responses','chat_completions'),
                    'MC_APPLICATION_VISION_CHANNEL_MISMATCH')
            return lock
        base = urllib.parse.urlsplit(lock.get('base_url', ''))
        require(base.scheme == 'http' and base.hostname in ('127.0.0.1', '::1') and base.port is not None
                and base.path == '/' and not base.username and not base.password and not base.query and not base.fragment,
                'MC_APPLICATION_VISION_LOCAL_ONLY')
        require(type(lock.get('build_info')) is str and bool(lock['build_info']), 'MC_APPLICATION_VISION_LOCK')
        for key in ('executable', 'model', 'projector'):
            pin = lock.get(key, {})
            name = pin.get('path', '')
            require(type(name) is str and bool(name) and not Path(name).is_absolute()
                    and '..' not in Path(name).parts, 'MC_APPLICATION_VISION_LOCK')
            path = safe_path(self.root, self.root / name)
            before = path.stat()
            require(path.is_file() and type(pin.get('bytes')) is int and pin['bytes'] > 0
                    and before.st_size == pin['bytes'] and type(pin.get('sha256')) is str
                    and len(pin['sha256']) == 64, 'MC_APPLICATION_VISION_LOCK')
            signature = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            if verify and self.pins.get(str(path)) != (signature, pin['sha256']):
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                after = path.stat()
                require(signature == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                        and digest.hexdigest() == pin['sha256'], 'MC_APPLICATION_VISION_PIN_CHANGED')
                self.pins[str(path)] = (signature, pin['sha256'])
        return lock

    def start(self, name, transaction):
        require(self.root == ROOT, 'MC_APPLICATION_ROOT_MISMATCH')
        # Suppress legacy console output so the public command has one JSON response.
        with redirect_stdout(io.StringIO()):
            if name == 'dsh':
                import dsh_control
                if not self.ownership('dsh', reject=True)['owned']:
                    dsh_control.control('start', transaction)
                self.ensure_channel_compatibility()
            elif name == 'studio':
                import start_studio
                for component in ('avatar', 'tts'):
                    state = self.ownership(component, reject=True)
                    # A previously started owner still loading must not produce a duplicate.
                    require(not state['owned'] or state['port_open'], 'MC_APPLICATION_SERVICE_STILL_STARTING')
                start_studio.start(progress=self.startup_progress)
            elif name == 'receiver':
                import receiver_control
                if not self.ownership('receiver', reject=True)['owned']:
                    receiver_control.control(SimpleNamespace(action='start'), transaction)
            elif name == 'candidate':
                require(self.candidate_mode, 'MC_APPLICATION_CANDIDATE_DISABLED')
                value = self.get('http://127.0.0.1:3092/api/dsh/mc-candidate/status')
                if not value.get('connected'):
                    self.post('http://127.0.0.1:3092/api/dsh/mc-candidate/connect', {})
                self.post('http://127.0.0.1:3092/api/dsh/mc-candidate/observe', {})
            elif name in ('minecraft', 'vision'):
                if name == 'vision' and self.vision_lock().get('provider') == 'studio_channel':
                    require(not self.ownership('vision',reject=True)['owned'], 'MC_APPLICATION_LEGACY_VISION_STILL_RUNNING')
                    return
                state = self.ownership(name, reject=True)
                if not state['owned']:
                    from mc_deployment import native_binaries
                    python = native_binaries(self.root)['python']['path']
                    logs = safe_path(self.root, self.root / 'logs'); logs.mkdir(exist_ok=True)
                    prefix = 'mc-game' if name == 'minecraft' else 'mc-vision'
                    with (logs / (prefix + '.stdout.log')).open('ab') as stdout, (logs / (prefix + '.stderr.log')).open('ab') as stderr:
                        transaction.spawn([python, '-X', 'utf8', '-B', str(self.root / self.SCRIPTS[name])],
                            cwd=self.root, stdout=stdout, stderr=stderr, registry=self.registry(name)[0])
            else:
                raise ApplicationError('MC_APPLICATION_COMPONENT_UNKNOWN')

    def observe(self):
        result = {}
        def check(name, fn):
            try:
                require(fn() is True, 'MC_APPLICATION_DEPENDENCY_NOT_READY')
                result[name] = {'ready': True}
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
                result[name] = {'ready': False, 'code': error.code if isinstance(error, ApplicationError)
                                else 'MC_APPLICATION_DEPENDENCY_UNAVAILABLE'}
        def owned(name):
            value = self.ownership(name)
            require(value['owned'] and value['listener_owned'], 'MC_APPLICATION_SERVICE_NOT_OWNED_OR_LISTENING')
        def dsh():
            owned('dsh'); value = self.get('http://127.0.0.1:3092/health')
            return all(value.get(k) is True for k in ('process_alive', 'state_store_ready', 'dsh_ready',
                       'persona_injection_ready', 'memory_ready', 'projection_synced')) and not value.get('stopping')
        def studio():
            owned('avatar'); value = self.get('http://127.0.0.1:8010/api/studio/status')
            config = self.config('livetalking.yaml')
            return all(value.get(k) is True for k in ('ready', 'avatar_ready', 'tts_ready', 'local_media')) \
                and bool(config.get('avatar_id')) and value.get('avatar_id') == config['avatar_id'] \
                and value.get('transport') == 'local_websocket_jpeg_pcm'
        def speech():
            owned('tts'); value = self.get('http://127.0.0.1:9880/health')
            expected = self.config('livetalking.yaml').get('TTS_REFERENCE_SHA256')
            return value.get('service') == 'resident-tts' and value.get('ready') is True and bool(expected) \
                and value.get('reference_sha256') == expected \
                and all(value.get('workers', {}).get(k, {}).get('ready') is True for k in ('O07', 'F07'))
        def receiver():
            owned('receiver'); expected = self.receiver_config()
            value = self.get('http://127.0.0.1:8020/receiver/status')
            return value.get('role') == 'receiver' and value.get('receiver_id') == expected['receiver_id'] \
                and value.get('upstream') == expected['upstream']
        def game():
            if self.candidate_mode:
                owned('dsh'); value = self.get('http://127.0.0.1:3092/api/dsh/mc-candidate/status')
                return value.get('connected') is True and value.get('username') == 'NAIMEI' \
                    and bool(value.get('world_session_id')) and value.get('mode') == 'PAUSED' \
                    and value.get('viewer', {}).get('ready') is True
            require(self.ownership('minecraft')['owned'], 'MC_APPLICATION_GAME_NOT_OWNED')
            owned('dsh'); value = self.get('http://127.0.0.1:3092/api/dsh/game/state')
            return value.get('connected') is True and value.get('freshness') == 'fresh' \
                and bool(value.get('world_session_id')) and value.get('mode') == 'PAUSED' \
                and value.get('inputs_released') is True
        def vision():
            lock = self.vision_lock(verify=True)
            if self.candidate_mode:
                owned('dsh'); value = self.get('http://127.0.0.1:3092/api/dsh/mc-candidate/status').get('vision') or {}
                return value.get('model') == 'gpt-6-luna' and value.get('source') == 'dsh_mc_observe_reconstruction'
            if lock.get('provider') == 'studio_channel':
                owned('dsh'); value=self.get('http://127.0.0.1:3092/health').get('vision') or {}
                return value.get('ready') is True and value.get('provider') == 'studio_channel' \
                    and value.get('model_id') == lock['model'] and value.get('local_model_process_required') is False \
                    and not self.ownership('vision',reject=True)['owned']
            owned('vision')
            props = self.get(lock['base_url'] + 'props')
            return props.get('modalities', {}).get('vision') is True and props.get('build_info') == lock['build_info'] \
                and type(props.get('total_slots')) is int and props['total_slots'] == 1 \
                and Path(props.get('model_path', '')).is_absolute() \
                and Path(props['model_path']).resolve() == (self.root / lock['model']['path']).resolve() \
                and props.get('is_sleeping') is False
        for name, fn in [('dsh', dsh), ('studio', studio), ('speech', speech), ('receiver', receiver),
                         ('minecraft', game), ('vision', vision)]:
            check(name, fn)
        # Receiver metrics and installed Livehime are diagnostics, not official capture proof.
        result['official_playback'] = {'ready': False, 'code': 'MC_APPLICATION_OFFICIAL_CAPTURE_NOT_VERIFIED'}
        result['avatar_packs'] = {'ready': False, 'code': 'MC_APPLICATION_NEW_AVATAR_PACKS_NOT_ACCEPTED'}
        return result

    def stop(self, transaction):
        require(self.root == ROOT, 'MC_APPLICATION_ROOT_MISMATCH')
        import dsh_control
        import launch
        import receiver_control
        from native_supervision import expected_stops
        entries = []
        states = {}
        for name in (*self.PORTS, 'minecraft'):
            state = self.ownership(name, reject=True); states[name] = state
            if state['owned']:
                entries.append((state['path'], state['key'], state['record']))
        if states['dsh']['owned']:
            state = self.get('http://127.0.0.1:3092/api/dsh/status')
            require('broadcast' in state and state['broadcast'] is None, 'MC_APPLICATION_STOP_REQUIRES_OFFAIR')
        with redirect_stdout(io.StringIO()), expected_stops(self.root, entries):
            # DSH refuses shutdown during an open broadcast. Do this before stopping any dependency.
            if states['minecraft']['owned']:
                from native_operation import atomic_json
                if states['dsh']['owned']:
                    value = self.get('http://127.0.0.1:3092/api/dsh/game/state')
                    if value.get('connected') is True and value.get('world_session_id'):
                        payload = json.dumps({'request_id': 'application-stop-' + str(time.time_ns()),
                                              'target_mode': 'PAUSED', 'reason': 'operator_application_stop',
                                              'bridge_boot_id': value['bridge_boot_id'],
                                              'world_session_id': value['world_session_id'],
                                              'expected_control_epoch': value['control_epoch']}).encode()
                        request = urllib.request.Request('http://127.0.0.1:3092/api/dsh/game/control', data=payload,
                                                         headers={'Content-Type': 'application/json'}, method='POST')
                        with self.http.open(request, timeout=5) as response:
                            require(response.status == 202, 'MC_APPLICATION_GAME_PAUSE_FAILED')
                        deadline = time.monotonic() + 10
                        while True:
                            paused = self.get('http://127.0.0.1:3092/api/dsh/game/state')
                            if paused.get('world_session_id') == value['world_session_id'] \
                                    and paused.get('mode') == 'PAUSED' and paused.get('inputs_released') is True:
                                break
                            require(time.monotonic() < deadline, 'MC_APPLICATION_GAME_PAUSE_NOT_CONFIRMED')
                            time.sleep(.1)
                owner = {key: states['minecraft']['record'][key] for key in ('pid', 'creation_ticks')}
                atomic_json(self.root, self.root / '.setup/mc-game-stop.json', {'owner': owner})
                deadline = time.monotonic() + 50
                while identity_alive(owner) and time.monotonic() < deadline:
                    time.sleep(.1)
                require(not identity_alive(owner), 'MC_APPLICATION_GAME_STOP_TIMEOUT')
            if states['vision']['owned']:
                from native_operation import atomic_json
                owner = {key: states['vision']['record'][key] for key in ('pid', 'creation_ticks')}
                atomic_json(self.root, self.root / '.setup/mc-vision-stop.json', {'owner': owner})
                deadline = time.monotonic() + 30
                while identity_alive(owner) and time.monotonic() < deadline: time.sleep(.1)
                require(not identity_alive(owner), 'MC_APPLICATION_VISION_STOP_TIMEOUT')
            if states['dsh']['owned']:
                require(self.get('http://127.0.0.1:3092/health').get('process_alive') is True,
                        'MC_APPLICATION_DSH_STOP_STATE_UNAVAILABLE')
                dsh_control.control('stop', transaction)
            if states['receiver']['owned']:
                receiver_control.control(SimpleNamespace(action='stop'), transaction)
            for name in ('tts', 'avatar'):
                if states[name]['owned']:
                    launch.stop_services(only=name)


class Application:
    def __init__(self, root, services=None, *, clock=time.monotonic, sleep=time.sleep):
        self.root = Path(root).resolve()
        self.services = services if services is not None else NativeServices(self.root)
        self.clock, self.sleep = clock, sleep

    @staticmethod
    def report(checks, **extra):
        managed = ('dsh', 'studio', 'speech', 'receiver', 'minecraft', 'vision')
        ready = bool(checks) and all(v.get('ready') is True for v in checks.values())
        return {'schema_version': 1, 'scope': 'NATIVE_APPLICATION_LIFECYCLE_NOT_RELEASE_ACCEPTANCE',
                'ok': ready, 'application_ready': ready,
                'services_ready': all(checks.get(k, {}).get('ready') is True for k in managed),
                'checks': checks, 'automatic_input_authorized': False, 'public_broadcast_started': False,
                'real_acceptance_passed': 0, 'complete_application': False, **extra}

    def status(self):
        return self.report(self.services.observe(), action='status', writes_performed=False)

    def start(self, timeout=1800):
        checks, transaction = {}, None
        started, stage = self.clock(), 'validate_request'
        def progress(value):
            nonlocal stage
            stage = value
            transaction.value['startup'] = {'stage': stage,
                'elapsed_ms': round(max(0, self.clock() - started) * 1000)}
            transaction.write()
        try:
            require(type(timeout) in (int, float) and math.isfinite(timeout) and 1 <= timeout <= 1800,
                    'MC_APPLICATION_TIMEOUT_INVALID')
            stage = 'acquire_operation'
            with operation(self.root, 'mc-application-start') as transaction:
                if isinstance(self.services, NativeServices):
                    self.services.startup_progress = progress
                progress('guard')
                self.services.guard()
                deadline = self.clock() + timeout
                names = ('dsh', 'studio', 'receiver', 'candidate') if getattr(self.services, 'candidate_mode', False) else ('dsh', 'studio', 'receiver', 'vision', 'minecraft')
                for name in names:
                    progress('start_' + name)
                    self.services.start(name, transaction)
                    require(self.clock() < deadline, 'MC_APPLICATION_START_TIMEOUT')
                    require(not any(p.poll() is not None for p in transaction.processes),
                            'MC_APPLICATION_SERVICE_EXITED_DURING_START')
                progress('observe_services')
                while self.clock() < deadline:
                    require(not any(p.poll() is not None for p in transaction.processes),
                            'MC_APPLICATION_SERVICE_EXITED_DURING_START')
                    checks = self.services.observe()
                    if self.report(checks)['services_ready']:
                        break
                    self.sleep(min(.5, max(0, deadline - self.clock())))
                else:
                    raise ApplicationError('MC_APPLICATION_START_TIMEOUT')
            return self.report(checks, ok=True, action='start',
                               code='MC_APPLICATION_SERVICES_STARTED' if self.report(checks)['application_ready']
                               else 'MC_APPLICATION_SERVICES_STARTED_REQUIRED_INTEGRATION_PENDING',
                               new_process_count=len(transaction.processes),
                               operation_phase=transaction.value['phase'])
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
            phase = transaction.value['phase'] if transaction else 'NOT_STARTED'
            return self.report(checks, ok=False, action='start',
                code=error.code if isinstance(error, ApplicationError) else str(error)
                     if isinstance(error, OperationError) else 'MC_APPLICATION_START_FAILED',
                new_process_count=len(transaction.processes) if transaction else 0,
                operation_phase=phase, rollback_complete=phase == 'ROLLED_BACK',
                diagnostic=startup_diagnostic(error, stage, round(max(0, self.clock() - started) * 1000)))
        finally:
            if isinstance(self.services, NativeServices):
                self.services.startup_progress = None

    def stop(self):
        transaction = None
        try:
            with operation(self.root, 'mc-application-stop', recovery=True) as transaction:
                self.services.stop(transaction)
            return {'ok': True, 'action': 'stop', 'scope': 'OWNED_MANAGED_SERVICES_ONLY',
                    'unmanaged_official_client_stopped': False, 'public_broadcast_started': False}
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            return {'ok': False, 'action': 'stop', 'code': error.code if isinstance(error, ApplicationError)
                    else 'MC_APPLICATION_STOP_FAILED', 'operation_phase': transaction.value['phase'] if transaction else 'NOT_STARTED',
                    'public_broadcast_started': False}
