"""Application orchestration uses real Windows process ownership, never GPU/game inference."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
import mc_application as app
import native_operation as native
import test_native_operation as fixtures
from native_windows_process import identity_alive


def checks(managed=True):
    return {name: {'ready': managed if name in ('dsh', 'studio', 'speech', 'receiver', 'minecraft', 'vision') else False}
            for name in ('dsh', 'studio', 'speech', 'receiver', 'minecraft', 'vision', 'official_playback', 'avatar_packs')}


class FixtureServices:
    def __init__(self, case):
        self.case, self.order, self.records = case, [], []
        self.fail_at, self.ready, self.guard_failure, self.stop_refused = None, True, False, False
        self.exit_at = None

    def guard(self):
        if self.guard_failure:
            raise app.ApplicationError('FIXTURE_PREPARATION_FAILED')

    def start(self, name, transaction):
        import psutil
        for component in (('avatar', 'tts') if name == 'studio' else (name,)):
            self.order.append(component)
            if component == self.fail_at:
                raise app.ApplicationError('FIXTURE_COMPONENT_FAILED')
            registry = self.case.root / '.setup' / (component + '.json')
            process = self.case.spawn_helper(transaction, registry=registry)
            self.records.append((registry, None, native.read_json(registry)))
            if component == self.exit_at:
                child = psutil.Process(process.pid); child.kill(); child.wait(timeout=5)

    def observe(self):
        return checks(self.ready)

    def stop(self, transaction):
        import psutil
        from native_supervision import expected_stops
        if self.stop_refused:
            raise app.ApplicationError('MC_APPLICATION_STOP_REQUIRES_OFFAIR')
        with expected_stops(self.case.root, self.records):
            for path, _, record in self.records:
                if identity_alive(record):
                    process = psutil.Process(record['pid']); process.terminate(); process.wait(timeout=5)


@unittest.skipUnless(os.name == 'nt', 'Real Windows job/supervisor integration')
class NativeApplicationTests(unittest.TestCase):
    setUp = fixtures.NativeOperationTests.setUp
    cleanup_helpers = fixtures.NativeOperationTests.cleanup_helpers
    wait_for = fixtures.NativeOperationTests.wait_for
    spawn_helper = fixtures.NativeOperationTests.spawn
    assert_family_closed = fixtures.NativeOperationTests.assert_family_closed

    def application(self):
        service = FixtureServices(self)
        return app.Application(self.root, service), service

    def test_ordered_start_commits_six_real_owners_without_claiming_business_readiness(self):
        controller, service = self.application()
        result = controller.start()
        self.assertTrue(result['ok']); self.assertTrue(result['services_ready'])
        self.assertFalse(result['application_ready']); self.assertFalse(result['complete_application'])
        self.assertEqual(result['operation_phase'], 'COMPLETED')
        self.assertEqual(service.order, ['dsh', 'avatar', 'tts', 'receiver', 'vision', 'minecraft'])
        self.assertEqual(result['new_process_count'], 6)
        self.assertTrue(all(identity_alive(p) for p in self.identities))
        stopped = controller.stop()
        self.assertTrue(stopped['ok']); self.assert_family_closed()

    def test_partial_start_failure_rolls_back_only_new_family(self):
        with native.operation(self.root, 'preexisting-fixture') as transaction:
            previous = self.spawn_helper(transaction, registry=self.root / '.setup/preexisting.json').identity()
        controller, service = self.application(); service.fail_at = 'tts'
        result = controller.start()
        self.assertEqual(result['code'], 'FIXTURE_COMPONENT_FAILED')
        self.assertTrue(result['rollback_complete']); self.assertEqual(result['new_process_count'], 2)
        self.assertTrue(identity_alive(previous))
        self.assertTrue(all(not identity_alive(p) for p in self.identities[1:]))
        self.assertTrue((self.root / '.setup/preexisting.json').is_file())
        self.assertFalse((self.root / '.setup/dsh.json').exists())

    def test_readiness_timeout_releases_all_new_owners(self):
        controller, service = self.application(); service.ready = False
        clock = [0.0]; controller.clock = lambda: clock[0]
        controller.sleep = lambda delay: clock.__setitem__(0, clock[0] + delay)
        result = controller.start(timeout=1)
        self.assertEqual(result['code'], 'MC_APPLICATION_START_TIMEOUT')
        self.assertEqual(result['new_process_count'], 6); self.assertTrue(result['rollback_complete'])
        self.assert_family_closed()

    def test_dead_new_root_cannot_be_masked_by_healthy_response(self):
        controller, service = self.application(); service.exit_at = 'avatar'
        result = controller.start()
        self.assertEqual(result['code'], 'MC_APPLICATION_SERVICE_EXITED_DURING_START')
        self.assertTrue(result['rollback_complete']); self.assert_family_closed()

    def test_failed_preparation_does_not_spawn_a_process(self):
        controller, service = self.application(); service.guard_failure = True
        result = controller.start()
        self.assertEqual(result['code'], 'FIXTURE_PREPARATION_FAILED')
        self.assertEqual(service.order, []); self.assertEqual(result['new_process_count'], 0)

    def test_old_four_service_readiness_cannot_commit_before_game_and_vision(self):
        controller, service = self.application()
        observed = checks(); observed['minecraft']['ready'] = False; observed['vision']['ready'] = False
        service.observe = lambda: observed
        clock = [0.0]; controller.clock = lambda: clock[0]
        controller.sleep = lambda delay: clock.__setitem__(0, clock[0] + delay)
        result = controller.start(timeout=1)
        self.assertFalse(result['ok']); self.assertEqual(result['code'], 'MC_APPLICATION_START_TIMEOUT')
        self.assertTrue(result['rollback_complete']); self.assert_family_closed()

    def test_competing_operation_cannot_start_duplicate_roots(self):
        controller, service = self.application(); results = []
        with native.operation(self.root, 'competing-installation-operation'):
            thread = threading.Thread(target=lambda: results.append(controller.start()))
            thread.start(); thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertFalse(results[0]['ok']); self.assertEqual(results[0]['operation_phase'], 'NOT_STARTED')
        self.assertEqual(results[0]['code'], 'MC_NATIVE_OPERATION_BUSY')
        self.assertEqual(service.order, [])

    def test_refused_broadcast_stop_keeps_every_running_dependency(self):
        controller, service = self.application(); self.assertTrue(controller.start()['ok'])
        service.stop_refused = True
        result = controller.stop()
        self.assertFalse(result['ok']); self.assertEqual(result['code'], 'MC_APPLICATION_STOP_REQUIRES_OFFAIR')
        self.assertTrue(all(identity_alive(p) for p in self.identities))
        service.stop_refused = False; self.assertTrue(controller.stop()['ok'])

    def test_alive_owner_does_not_authorize_a_port_listened_by_another_process(self):
        from http.server import HTTPServer
        server = HTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
        self.addCleanup(server.server_close)
        services = app.NativeServices(self.root)
        services.PORTS = {'dsh': server.server_port}
        services.SCRIPTS = {'dsh': self.helper.relative_to(self.root).as_posix()}
        with native.operation(self.root, 'owned-process-unrelated-port') as transaction:
            self.spawn_helper(transaction, registry=self.root / '.setup/dsh-process.json')
            with self.assertRaisesRegex(app.ApplicationError, 'MC_APPLICATION_PORT_NOT_OWNED'):
                services.ownership('dsh', reject=True)

    def test_exact_owned_process_and_listener_are_both_required_and_accepted(self):
        self.helper.write_text('''from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import sys,time
root=Path(sys.argv[1])
server=HTTPServer(('127.0.0.1',0),BaseHTTPRequestHandler)
(root/'listening-port').write_text(str(server.server_port))
while not (root/'stop').exists():time.sleep(.02)
server.server_close()
''', encoding='utf-8')
        services = app.NativeServices(self.root)
        services.SCRIPTS = {'dsh': self.helper.relative_to(self.root).as_posix()}
        with native.operation(self.root, 'owned-listening-process') as transaction:
            self.spawn_helper(transaction, registry=self.root / '.setup/dsh-process.json')
            self.wait_for(lambda: (self.root / 'listening-port').is_file()
                          and bool((self.root / 'listening-port').read_text()))
            services.PORTS = {'dsh': int((self.root / 'listening-port').read_text())}
            result = services.ownership('dsh', reject=True)
            self.assertTrue(result['owned']); self.assertTrue(result['listener_owned'])


class ApplicationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='mc-application-原生 ')
        self.root = Path(self.folder.name); self.addCleanup(self.folder.cleanup)
        self.services = app.NativeServices(self.root)

    def write_config(self, name, value):
        folder = self.root / 'configs'; folder.mkdir(exist_ok=True)
        (folder / name).write_text(json.dumps(value), encoding='utf-8')

    def test_fresh_owned_dsh_checks_the_selected_channel_before_media_start(self):
        health = {'process_alive':True, 'dsh_ready':True, 'persona_injection_ready':False,
                  'channel':{'configured':True,'has_key':True}}
        with patch.object(self.services, 'ownership', return_value={'owned':True,'listener_owned':True}), \
             patch.object(self.services, 'get', return_value=health), \
             patch.object(self.services, 'post', return_value={'passed':True}) as post:
            self.services.ensure_channel_compatibility()
            post.assert_called_once_with('http://127.0.0.1:3092/api/dsh/probe', {})

    def test_failed_or_unconfigured_channel_never_becomes_ready(self):
        health = {'process_alive':True,'dsh_ready':True,'channel':{'configured':True,'has_key':True}}
        with patch.object(self.services, 'ownership', return_value={'owned':True,'listener_owned':True}), \
             patch.object(self.services, 'get', return_value=health), \
             patch.object(self.services, 'post', return_value={'passed':False}) as post:
            with self.assertRaisesRegex(app.ApplicationError, 'CHANNEL_COMPATIBILITY_FAILED'):
                self.services.ensure_channel_compatibility()
            health['channel']['has_key'] = False
            with self.assertRaisesRegex(app.ApplicationError, 'SELECTED_CHANNEL_NOT_CONFIGURED'):
                self.services.ensure_channel_compatibility()
            self.assertEqual(post.call_count, 1)

    def test_ready_channel_is_reused_without_another_model_call(self):
        with patch.object(self.services, 'ownership', return_value={'owned':True,'listener_owned':True}), \
             patch.object(self.services, 'get', return_value={'process_alive':True,'dsh_ready':True,'persona_injection_ready':True}), \
             patch.object(self.services, 'post') as post:
            self.services.ensure_channel_compatibility()
            post.assert_not_called()

    def vision(self):
        lock = {'base_url': 'http://127.0.0.1:8019/', 'build_info': 'fixture-native-build'}
        for key in ('executable', 'model', 'projector'):
            data = (key + '-fixture-only').encode(); path = self.root / (key + '.fixture'); path.write_bytes(data)
            lock[key] = {'path': path.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        self.write_config('mc-vision.json', lock)
        return lock

    def test_status_is_read_only_and_does_not_start_or_import_model_runtime(self):
        before = sorted(self.root.rglob('*'))
        result = app.Application(self.root).status()
        self.assertEqual(sorted(self.root.rglob('*')), before)
        self.assertFalse(result['ok']); self.assertFalse(result['services_ready'])
        self.assertFalse(result['checks']['official_playback']['ready'])
        self.assertFalse(result['checks']['avatar_packs']['ready'])
        self.assertFalse(result['automatic_input_authorized']); self.assertEqual(result['real_acceptance_passed'], 0)

    def test_invalid_deadlines_fail_before_creating_operation_state(self):
        for value in (0, -1, 1801, True, float('nan'), float('inf')):
            with self.subTest(value=value):
                result = app.Application(self.root).start(value)
                self.assertEqual(result['code'], 'MC_APPLICATION_TIMEOUT_INVALID')
                self.assertEqual(result['new_process_count'], 0)
        self.assertFalse((self.root / '.setup').exists())

    def test_vision_verifies_every_pin_before_runtime_admission(self):
        lock = self.vision()
        self.assertEqual(self.services.vision_lock(verify=True), lock)
        self.assertEqual(len(self.services.pins), 3)

    def test_channel_vision_requires_exact_existing_model_and_no_second_endpoint(self):
        lock = {'schema_version':2,'provider':'studio_channel','model':'gpt-6-luna','observe_interval_ms':20000}
        self.write_config('mc-vision.json',lock)
        channel=self.root/'configs/channel.env'
        channel.write_text('AVATAR_LLM_MODEL=gpt-6-luna\nAVATAR_LLM_PROTOCOL=responses\nAVATAR_LLM_API_KEY=FIXTURE_NOT_A_CREDENTIAL\n',encoding='utf-8')
        self.assertEqual(self.services.vision_lock(),lock)
        channel.write_text('AVATAR_LLM_MODEL=other\nAVATAR_LLM_API_KEY=FIXTURE_NOT_A_CREDENTIAL\n',encoding='utf-8')
        with self.assertRaisesRegex(app.ApplicationError,'VISION_CHANNEL_MISMATCH'): self.services.vision_lock()
        self.write_config('mc-vision.json',{**lock,'base_url':'https://another.invalid/v1'})
        with self.assertRaisesRegex(app.ApplicationError,'VISION_CHANNEL_CONFIG'): self.services.vision_lock()

    def test_same_size_vision_model_mutation_is_rejected(self):
        lock = self.vision(); self.services.vision_lock(verify=True)
        path = self.root / lock['model']['path']; data = path.read_bytes()
        path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        with self.assertRaisesRegex(app.ApplicationError, 'MC_APPLICATION_VISION_PIN_CHANGED'):
            self.services.vision_lock(verify=True)

    def test_model_escape_and_remote_vision_origin_are_rejected(self):
        lock = self.vision()
        for url in ('https://127.0.0.1:8019/', 'http://example.com:8019/',
                    'http://127.0.0.1:8019/other', 'http://user@127.0.0.1:8019/'):
            lock['base_url'] = url; self.write_config('mc-vision.json', lock)
            with self.assertRaisesRegex(app.ApplicationError, 'MC_APPLICATION_VISION_LOCAL_ONLY'):
                self.services.vision_lock(verify=True)
        lock['base_url'] = 'http://127.0.0.1:8019/'; lock['model']['path'] = '../outside.gguf'
        self.write_config('mc-vision.json', lock)
        with self.assertRaisesRegex(app.ApplicationError, 'MC_APPLICATION_VISION_LOCK'):
            self.services.vision_lock(verify=True)

    def test_live_broadcast_blocks_stop_before_any_dependency_is_touched(self):
        state = {'owned': True, 'path': self.root / '.setup/fake.json', 'key': None, 'record': {}}
        with patch.object(app, 'ROOT', self.root), patch.object(self.services, 'ownership', return_value=state), \
             patch.object(self.services, 'get', return_value={'broadcast': {'broadcast_id': 'active'}}), \
             patch('dsh_control.control') as dsh, patch('receiver_control.control') as receiver, \
             patch('launch.stop_services') as studio:
            with self.assertRaisesRegex(app.ApplicationError, 'MC_APPLICATION_STOP_REQUIRES_OFFAIR'):
                self.services.stop(None)
            dsh.assert_not_called(); receiver.assert_not_called(); studio.assert_not_called()

    def test_missing_broadcast_state_is_not_treated_as_offair(self):
        state = {'owned': True, 'path': self.root / '.setup/fake.json', 'key': None, 'record': {}}
        with patch.object(app, 'ROOT', self.root), patch.object(self.services, 'ownership', return_value=state), patch.object(self.services, 'get', return_value={}):
            with self.assertRaisesRegex(app.ApplicationError, 'MC_APPLICATION_STOP_REQUIRES_OFFAIR'):
                self.services.stop(None)

    def test_stop_from_another_installation_cannot_dispatch_this_installations_controllers(self):
        with patch('dsh_control.control') as dsh, patch('receiver_control.control') as receiver, \
             patch('launch.stop_services') as studio, patch.object(self.services, 'ownership') as ownership:
            with self.assertRaisesRegex(app.ApplicationError, 'MC_APPLICATION_ROOT_MISMATCH'):
                self.services.stop(None)
            ownership.assert_not_called(); dsh.assert_not_called()
            receiver.assert_not_called(); studio.assert_not_called()

    @contextmanager
    def endpoint(self, payload, redirect=False):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302 if redirect else 200)
                if redirect:
                    self.send_header('Location', 'http://127.0.0.1:1/must-not-follow')
                self.end_headers(); self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            yield 'http://127.0.0.1:' + str(server.server_port) + '/status'
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=5)
            self.assertFalse(worker.is_alive())

    def test_readiness_http_refuses_redirects(self):
        with self.endpoint(b'{}', redirect=True) as url:
            with self.assertRaises(app.urllib.error.HTTPError) as failure:
                self.services.get(url)
            self.assertEqual(failure.exception.code, 302)

    def test_readiness_http_bounds_response_size(self):
        with self.endpoint(b' ' * 65537) as url:
            with self.assertRaisesRegex(app.ApplicationError, 'MC_APPLICATION_RESPONSE_TOO_LARGE'):
                self.services.get(url)

    def test_readiness_http_requires_an_object(self):
        with self.endpoint(b'[]') as url:
            with self.assertRaisesRegex(app.ApplicationError, 'MC_APPLICATION_RESPONSE_INVALID'):
                self.services.get(url)

    def test_status_command_does_not_create_a_missing_installation(self):
        destination = self.root / 'missing installation'
        process = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT / 'scripts/mc_runtime.py'),
                                  'application-status', '--root', str(destination)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 1)
        result = json.loads(process.stdout); self.assertFalse(result['application_ready'])
        self.assertFalse(destination.exists())

    def test_cli_rejects_start_deadline_on_status(self):
        process = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT / 'scripts/mc_runtime.py'),
                                  'application-status', '--timeout', '1'], capture_output=True, text=True)
        self.assertEqual(process.returncode, 2)
        self.assertIn('--timeout is only valid with application-start', process.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
