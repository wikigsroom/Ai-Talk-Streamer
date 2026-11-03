"""Independent durable operator console for the guarded native MC application."""
from pathlib import Path
from urllib.parse import urlsplit
import json
import math
import re
import threading

import mc_deployment as mc
from mc_application import Application, ApplicationError, NativeServices
from mc_maintenance_console import ConsoleServer, ConsoleService, configuration, public_job, JOB
from mc_maintenance_core import MaintenanceCoordinator, NativeRuntime, folder
from mc_maintenance_dependencies import MaintenanceError, canonical, digest, parse, require, safe_path
from mc_maintenance_jobs import JobLedger, REQUEST

PREFIX = '/api/mc-runtime'
ACTIONS = {'start', 'stop', 'status', 'preflight'}
CHECKS = {'dsh', 'studio', 'speech', 'receiver', 'minecraft', 'vision', 'official_playback', 'avatar_packs'}


def public_code(value, fallback='MC_APPLICATION_CONSOLE_UNAVAILABLE'):
    return value if isinstance(value, str) and re.fullmatch(r'(?:MC_|GAME_)[A-Z0-9_]{1,110}', value) else fallback


def validate_request(value):
    require(isinstance(value, dict) and isinstance(value.get('action'), str) and value['action'] in ACTIONS
            and isinstance(value.get('request_id'), str) and REQUEST.fullmatch(value['request_id']),
            'MC_MAINTENANCE_REQUEST_INVALID')
    fields = {'action', 'request_id'}
    if value['action'] == 'start' and 'timeout' in value:
        fields.add('timeout')
        timeout = value['timeout']
        require(type(timeout) in (int, float) and math.isfinite(timeout) and 1 <= timeout <= 1800,
                'MC_MAINTENANCE_REQUEST_INVALID')
    require(set(value) == fields, 'MC_MAINTENANCE_REQUEST_INVALID')
    return value


def public_result(value):
    """Project fixed readiness facts, never paths, commands, PIDs, channels or exception text."""
    require(isinstance(value, dict) and type(value.get('ok')) is bool, 'MC_MAINTENANCE_NATIVE_RESULT')
    result = {'ok': value['ok'], 'code': public_code(value['code']) if value.get('code') else None,
              'automatic_input_authorized': False, 'public_broadcast_started': False,
              'real_acceptance_passed': 0, 'complete_application': False}
    for key in ('services_ready', 'application_ready', 'rollback_complete'):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    if value.get('operation_phase') in {'NOT_STARTED', 'STARTING', 'COMMITTING', 'COMPLETED',
                                      'ROLLED_BACK', 'ROLLBACK_INCOMPLETE', 'RECOVERY_REQUIRED'}:
        result['operation_phase'] = value['operation_phase']
    if type(value.get('new_process_count')) is int and 0 <= value['new_process_count'] <= 64:
        result['new_process_count'] = value['new_process_count']
    checks = value.get('checks')
    if isinstance(checks, dict):
        result['checks'] = {name: {'ready': item.get('ready') is True,
                                 'code': public_code(item['code']) if item.get('code') else None}
                            for name, item in checks.items() if name in CHECKS and isinstance(item, dict)}
    elif isinstance(checks, list):
        names = {'profile', 'source', 'game_files', 'device', 'native', 'runtime_files', 'idle'}
        result['preflight'] = [{'name': item['name'], 'ready': item.get('ok') is True,
                                'code': public_code(item['code']) if item.get('code') else None}
                               for item in checks if isinstance(item, dict) and item.get('name') in names]
    return result


class PinnedServices(NativeServices):
    def __init__(self, root, verify):
        super().__init__(root)
        self.verify = verify

    def guard(self):
        # Called inside Application's native operation lock, before any service starts.
        try:
            self.verify()
        except MaintenanceError as error:
            raise ApplicationError(error.code) from None
        super().guard()


class RuntimeService:
    def __init__(self, root, binding, verify, *, execution_lock=None, application_factory=None, preflight=None):
        self.root = safe_path(root, directory=True)
        self.binding, self.binding_sha256, self.verify = binding, digest(binding), verify
        self.execution_lock = execution_lock if execution_lock is not None else threading.RLock()
        self.condition = threading.Condition()
        self.stopping, self.fault = False, None
        self.latest = None
        self.preflight = preflight if preflight is not None else lambda: mc.preflight(self.root)[0]
        factory = application_factory if application_factory is not None else lambda root, check: Application(root, PinnedServices(root, check))
        self.application = factory(self.root, verify)
        work = folder(folder(self.root, 'outputs'), 'mc-application-console')
        self.ledger = JobLedger(work, {'root': str(self.root), 'kind': 'mc_application_console_v1'},
                                request_validator=validate_request, uncertain_actions={'start', 'stop'})
        self.worker = threading.Thread(target=self._work, name='mc-application-worker', daemon=False)
        try:
            for row in self.ledger.page()['items']:
                if row['result'] is not None:
                    self.latest = {'job_id': row['job_id'], 'finished_at': row['finished_at'], 'result': parse(row['result'])}
                    break
            self.worker.start()
        except BaseException:
            self.ledger.close()
            raise

    def enqueue(self, value):
        validate_request(value)
        with self.condition:
            require(not self.stopping, 'MC_MAINTENANCE_CONSOLE_STOPPING')
            require(self.fault is None, 'MC_MAINTENANCE_CONSOLE_STORAGE_FAILED')
            row, duplicate = self.ledger.enqueue(value, self.binding_sha256)
            self.condition.notify_all()
            return {'job': public_job(row), 'duplicate': duplicate}

    def _work(self):
        while True:
            try:
                with self.condition:
                    if self.stopping:
                        return
                    row = self.ledger.take()
                    if row is None:
                        self.condition.wait(timeout=1)
                        continue
                state, outcome, code, value = 'failed', 'not_dispatched', None, None
                try:
                    request = validate_request(parse(row['request']))
                    require(row['binding_sha256'] == self.binding_sha256, 'MC_MAINTENANCE_CONSOLE_BINDING')
                    with self.execution_lock:
                        if request['action'] == 'preflight':
                            raw = self.preflight()
                        elif request['action'] == 'start':
                            raw = self.application.start(timeout=request.get('timeout', 1800))
                        else:
                            raw = getattr(self.application, request['action'])()
                    value = public_result(raw)
                    if request['action'] == 'stop' and value['ok']:
                        value.update(services_ready=False, application_ready=False,
                                     checks={key: {'ready': False, 'code': 'MC_APPLICATION_MANAGED_SERVICE_STOPPED'}
                                             for key in ('dsh', 'studio', 'speech', 'receiver')})
                    if request['action'] in {'status', 'preflight'}:
                        state, outcome = 'succeeded', 'not_applicable'
                    else:
                        state = 'succeeded' if value['ok'] else 'failed'
                        outcome = 'committed' if value['ok'] else 'not_committed' if value.get('rollback_complete') is True \
                            or value.get('operation_phase') == 'NOT_STARTED' else 'unknown'
                    code = value['code']
                except Exception as error:
                    code = public_code(getattr(error, 'code', None), 'MC_APPLICATION_CONSOLE_EXECUTION_FAILED')
                    outcome = 'unknown' if row['action'] in {'start', 'stop'} else 'not_applicable'
                self.ledger.finish(row['job_id'], state, outcome, code, value)
                if value is not None:
                    finished = self.ledger.get(row['job_id'])
                    with self.condition:
                        self.latest = {'job_id': row['job_id'], 'finished_at': finished['finished_at'], 'result': value}
            except Exception:
                # Never redispatch when durable completion itself failed.
                self.fault = 'MC_MAINTENANCE_CONSOLE_STORAGE_FAILED'
                return

    def state(self):
        with self.condition:
            return {'schema_version': 1, 'binding_sha256': self.binding_sha256,
                    'capacity': self.ledger.capacity(), 'stopping': self.stopping, 'fault': self.fault,
                    'latest': self.latest, 'unified_managed_service_lifecycle_available': True,
                    'full_application_lifecycle_complete': False, 'automatic_input_authorized': False}

    def begin_stop(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()

    def close(self):
        self.begin_stop()
        while self.worker.is_alive():
            self.worker.join(timeout=.2)
        try:
            self.ledger.interrupt_pending()
        finally:
            self.ledger.close()

    def handle(self, handler, path, query, post):
        host = urlsplit('http://' + handler.headers.get('Host', ''))
        permitted = {'127.0.0.1', 'localhost', '::1', handler.connection.getsockname()[0]}
        require(host.hostname in permitted and host.port == handler.server.server_port
                and not host.username and not host.password and not host.path and not host.query and not host.fragment,
                'MC_MAINTENANCE_REQUEST_INVALID')
        origin = handler.headers.get('Origin')
        require(not post or origin is None or origin == 'http://' + handler.headers['Host'],
                'MC_MAINTENANCE_REQUEST_INVALID')
        if path == PREFIX + '/jobs' and not post:
            require(set(query) <= {'before', 'through'} and all(len(v) == 1 and re.fullmatch(r'[0-9]{1,10}', v[0])
                    for v in query.values()), 'MC_MAINTENANCE_REQUEST_INVALID')
            page = self.ledger.page(int(query.get('before', ['0'])[0]), int(query.get('through', ['0'])[0]))
            page['items'] = [public_job(row) for row in page['items']]
            handler.send(200, page)
            return
        require(not query, 'MC_MAINTENANCE_REQUEST_INVALID')
        if path == PREFIX + '/state' and not post:
            handler.send(200, {**self.state(), 'maintenance_configured': handler.server.service.maintenance is not None})
        elif path == PREFIX + '/jobs' and post:
            result = self.enqueue(handler.body())
            handler.send(200 if result['duplicate'] else 202, result)
        elif path.startswith(PREFIX + '/requests/') and not post:
            key = path[len(PREFIX + '/requests/'):]
            require(REQUEST.fullmatch(key), 'MC_MAINTENANCE_REQUEST_INVALID')
            handler.send(200, public_job(self.ledger.get(key, request=True)))
        elif path.startswith(PREFIX + '/jobs/'):
            key = path[len(PREFIX + '/jobs/'):]
            if post and key.endswith('/cancel'):
                key = key[:-7]
                require(JOB.fullmatch(key) and handler.body() == {}, 'MC_MAINTENANCE_REQUEST_INVALID')
                handler.send(200, public_job(self.ledger.cancel(key)))
            else:
                require(not post and JOB.fullmatch(key), 'MC_MAINTENANCE_REQUEST_INVALID')
                handler.send(200, public_job(self.ledger.get(key)))
        elif path == PREFIX + '/close' and post:
            require(handler.body() == {}, 'MC_MAINTENANCE_REQUEST_INVALID')
            handler.server.service.begin_stop()
            handler.send(202, {'stopping': True, 'live_services_stopped': False})
            threading.Thread(target=handler.server.shutdown, name='mc-runtime-http-stop', daemon=True).start()
        else:
            handler.send(404, {'code': 'MC_MAINTENANCE_ROUTE_NOT_FOUND', 'outcome': 'not_dispatched'})


class ConsoleHost:
    runtime_default = True

    def __init__(self, root, runtime, maintenance=None):
        self.root, self.runtime, self.maintenance = root, runtime, maintenance

    def __getattr__(self, name):
        if self.maintenance is None:
            raise MaintenanceError('MC_MAINTENANCE_NOT_CONFIGURED')
        return getattr(self.maintenance, name)

    def begin_stop(self):
        self.runtime.begin_stop()
        if self.maintenance is not None:
            self.maintenance.begin_stop()

    def close(self):
        self.begin_stop()
        try:
            self.runtime.close()
        finally:
            if self.maintenance is not None:
                self.maintenance.close()


def serve(root, *, journal=None, runtime_config=None):
    root = safe_path(root, directory=True)
    require(root == Path(__file__).resolve().parents[1], 'MC_MAINTENANCE_INSTALLATION_INVALID')
    config = configuration(root)
    _, _, _, profile = mc.load_profile(root)
    source = mc.source_identity(root)
    binding = {'root': str(root), 'source_snapshot_sha256': source['snapshot_sha256'],
               'profile_sha256': mc.sha(root / mc.PROFILE)}
    def verify():
        require(mc.source_identity(root)['snapshot_sha256'] == binding['source_snapshot_sha256']
                and mc.sha(root / mc.PROFILE) == binding['profile_sha256'], 'MC_MAINTENANCE_INSTALLATION_CHANGED')
    shared = threading.RLock()
    runtime = RuntimeService(root, binding, verify, execution_lock=shared)
    host, server = ConsoleHost(root, runtime), None
    try:
        if journal is not None:
            native = NativeRuntime(runtime_config or root / 'configs/mc-maintenance.private.json')
            database = root / profile['inference']['state_path'] / 'game/game.sqlite3'
            coordinator = MaintenanceCoordinator(database, journal, native, {**binding, 'state_path': profile['inference']['state_path']})
            def verify_maintenance():
                verify()
                native.verify()
            host.maintenance = ConsoleService(root, coordinator, verify_maintenance, digest(coordinator.binding()), execution_lock=shared)
        server = ConsoleServer((config['host'], config['port']), host)
        print(json.dumps({'ok': True, 'application_console_listening': True, 'host': config['host'],
                          'port': server.server_port, 'maintenance_configured': host.maintenance is not None,
                          'services_started': False, 'models_loaded': False, 'automatic_input_authorized': False}), flush=True)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if server is not None:
                server.server_close()
        finally:
            host.close()
