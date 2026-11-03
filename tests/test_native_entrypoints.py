"""Exercise production control entry points with stdlib helper process families.

Device/model/port/health boundaries are explicit doubles. No inference starts.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import contextlib
import io
import json
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import test_native_operation as fixtures
import native_operation as native
import launch
import start_studio as studio
import dsh_control as dsh
import receiver_control as receiver
import deployment_target
from native_windows_process import identity_alive


@unittest.skipUnless(os.name == 'nt', 'Actual Windows entry point checks')
class NativeEntrypointTests(unittest.TestCase):
    setUp = fixtures.NativeOperationTests.setUp
    cleanup_helpers = fixtures.NativeOperationTests.cleanup_helpers
    wait_for = fixtures.NativeOperationTests.wait_for
    spawn_helper = fixtures.NativeOperationTests.spawn
    capture_family = fixtures.NativeOperationTests.capture_family
    assert_family_closed = fixtures.NativeOperationTests.assert_family_closed

    @contextlib.contextmanager
    def studio_boundaries(self, *, ports=None, health=None, fail_second=False):
        config = self.root / 'configs/livetalking.yaml'
        config.parent.mkdir(exist_ok=True)
        config.write_text(json.dumps({'tts': 'resident-local', 'TTS_REFERENCE_SHA256': 'approved-reference'}))
        opened = dict(ports or {})
        health = health or {'service': 'resident-tts', 'ready': True,
            'workers': {'O07': {'ready': True}, 'F07': {'ready': True}},
            'reference_sha256': 'approved-reference'}
        def start_helper(name, profile, minimum, transaction):
            if fail_second and name == 'tts':
                raise RuntimeError('second component failed')
            process = self.spawn_helper(transaction, key=name, registry=self.root / '.setup/services.json')
            opened[8010 if name == 'avatar' else 9880] = True
            return process
        response = Mock()
        response.__enter__ = Mock(return_value=io.StringIO(json.dumps(health)))
        response.__exit__ = Mock(return_value=False)
        opener = Mock(); opener.open.return_value = response
        with patch.object(launch, 'ROOT', self.root), patch.object(studio, 'ROOT', self.root), \
             patch.object(deployment_target, 'validate_target'), \
             patch.object(launch, '_start_service', side_effect=start_helper), \
             patch.object(studio, 'port_open', side_effect=lambda port: opened.get(port, False)), \
             patch.object(studio.urllib.request, 'build_opener', return_value=opener):
            yield

    def test_second_component_failure_rolls_back_first_new_service(self):
        with self.studio_boundaries(fail_second=True), self.assertRaisesRegex(RuntimeError, 'second component'):
            studio.start()
        self.assert_family_closed()
        self.assertEqual(json.loads((self.root / '.setup/services.json').read_text()), {})

    def test_voice_identity_failure_rolls_back_both_new_services(self):
        health = {'service': 'resident-tts', 'ready': True,
            'workers': {'O07': {'ready': True}, 'F07': {'ready': True}}, 'reference_sha256': 'wrong'}
        with self.studio_boundaries(health=health), self.assertRaisesRegex(RuntimeError, 'approved voice pair'):
            studio.start()
        self.assertEqual(len(self.identities), 2)
        self.assert_family_closed()

    def test_voice_load_failure_preserves_preexisting_avatar(self):
        registry = self.root / '.setup/services.json'
        with native.operation(self.root, 'preexisting-avatar') as transaction:
            avatar = self.spawn_helper(transaction, key='avatar', registry=registry)
            identity = avatar.identity()
        health = {'error': 'fixture-worker-load-failed', 'initializing': False}
        with self.studio_boundaries(ports={8010: True}, health=health), \
             self.assertRaisesRegex(RuntimeError, 'O07/F07 startup failed'):
            studio.start()
        self.assertTrue(identity_alive(identity))
        self.assertFalse(identity_alive(self.identities[-1]))
        self.assertEqual(list(json.loads(registry.read_text())), ['avatar'])

    def test_approved_health_commits_both_new_services_in_one_operation(self):
        with self.studio_boundaries():
            studio.start()
        records = json.loads((self.root / '.setup/services.json').read_text())
        self.assertEqual(set(records), {'avatar', 'tts'})
        self.assertEqual(records['avatar']['native_operation_id'], records['tts']['native_operation_id'])
        self.assertTrue(all(identity_alive(value) for value in self.identities))
        self.assertEqual(native.status(self.root)['phase'], 'COMPLETED')

    def test_new_service_exit_aborts_before_health_poll(self):
        with self.studio_boundaries(), patch.object(studio, 'start_service', return_value=SimpleNamespace(poll=lambda: 3)), \
             self.assertRaisesRegex(RuntimeError, 'exited'):
            studio.start()
        self.assertEqual(self.identities, [])
        self.assertEqual(native.status(self.root)['phase'], 'ROLLED_BACK')

    def test_individual_start_still_runs_device_guard_before_any_spawn(self):
        with patch.object(launch, 'ROOT', self.root), \
             patch.object(deployment_target, 'validate_target', side_effect=RuntimeError('device mismatch')), \
             patch.object(launch, 'require_prepared') as prepared, \
             patch.object(native.NativeOperation, 'spawn') as spawn, \
             self.assertRaisesRegex(RuntimeError, 'device mismatch'):
            launch.start_service('tts', minimum=0)
        prepared.assert_not_called(); spawn.assert_not_called()

    def test_individual_start_still_runs_preparation_guard(self):
        with patch.object(launch, 'ROOT', self.root), patch.object(deployment_target, 'validate_target'), \
             patch.object(launch, 'require_prepared', side_effect=RuntimeError('not prepared')), \
             patch.object(native.NativeOperation, 'spawn') as spawn, \
             self.assertRaisesRegex(RuntimeError, 'not prepared'):
            launch.start_service('avatar', minimum=0)
        spawn.assert_not_called()

    def test_port_closed_does_not_duplicate_registered_model_loader(self):
        with native.operation(self.root, 'cold-existing-loader') as transaction:
            process = self.spawn_helper(transaction, key='tts', registry=self.root / '.setup/services.json')
            identity = process.identity()
        (self.root / 'configs').mkdir(exist_ok=True)
        (self.root / 'configs/livetalking.yaml').write_text('{"tts":"resident-local"}')
        with patch.object(launch, 'ROOT', self.root), patch.object(deployment_target, 'validate_target'), \
             patch.object(launch, 'require_prepared'), patch.object(launch, 'environment', return_value={}), \
             patch.object(launch, 'port_open', return_value=False), \
             self.assertRaisesRegex(native.OperationError, 'SERVICE_ALREADY_OWNED'):
            launch.start_service('tts', minimum=0)
        self.assertTrue(identity_alive(identity))
        self.assertEqual(len(self.identities), 1)

    def test_native_stop_finishes_recorded_owner_and_different_script_descendants(self):
        registry = self.root / '.setup/services.json'
        with native.operation(self.root, 'start') as transaction:
            self.spawn_helper(transaction, levels=2, key='tts', registry=registry)
            self.capture_family(2)
        with patch.object(launch, 'ROOT', self.root):
            launch.stop_services('tts')
        self.assert_family_closed()
        self.assertEqual(json.loads(registry.read_text()), {})

    def test_failed_stop_retains_registry(self):
        registry = self.root / '.setup/services.json'
        with native.operation(self.root, 'start') as transaction:
            self.spawn_helper(transaction, key='tts', registry=registry)
        before = registry.read_bytes()
        with patch.object(launch, 'ROOT', self.root), patch('psutil.Process.terminate'), \
             patch('psutil.wait_procs', return_value=([], [Mock()])), \
             self.assertRaisesRegex(RuntimeError, 'ownership record was retained'):
            launch.stop_services('tts')
        self.assertEqual(registry.read_bytes(), before)

    def test_individual_native_stop_keeps_other_committed_service_alive(self):
        import native_supervision
        registry = self.root / '.setup/services.json'
        with native.operation(self.root, 'paired-start') as transaction:
            avatar = self.spawn_helper(transaction, key='avatar', registry=registry)
            tts = self.spawn_helper(transaction, key='tts', registry=registry)
        with patch.object(launch, 'ROOT', self.root):
            launch.stop_services('avatar')
            self.assertFalse(identity_alive(avatar.identity()))
            self.assertTrue(identity_alive(tts.identity()))
            self.assertEqual(set(json.loads(registry.read_text())), {'tts'})
            launch.stop_services('tts')
        self.assert_family_closed()
        path = native_supervision.paths(self.root, transaction.value['operation_id'])['status']
        self.wait_for(lambda: native.read_json(path)['phase'] == 'STOPPED')

    def test_receiver_stop_records_expected_exit_for_actual_native_owner(self):
        import native_supervision
        config = self.root/'configs/receiver.private.json'
        config.parent.mkdir()
        value = {'upstream': 'http://127.0.0.1:8010', 'port': 8020, 'bind': '127.0.0.1', 'receiver_id': 'fixture'}
        config.write_text(json.dumps(value))
        registry = self.root/'outputs/receiver/process.json'
        with native.operation(self.root, 'receiver-start') as transaction:
            self.spawn_helper(transaction, registry=registry)
        with patch.object(receiver, 'ROOT', self.root), patch.object(receiver, 'CONFIG', config), \
             patch.object(receiver, 'RECORD', registry), patch.object(receiver, 'validate_config', side_effect=lambda v: v), \
             patch('sys.argv', ['receiver_control.py', 'stop']):
            receiver.main()
        self.assert_family_closed()
        path = native_supervision.paths(self.root, transaction.value['operation_id'])['status']
        self.wait_for(lambda: native.read_json(path)['phase'] == 'STOPPED')

    def test_other_entrypoints_refuse_before_configuration_when_gate_busy(self):
        code = '''import sys
sys.path.insert(0,sys.argv[1])
import dsh_control,receiver_control
from pathlib import Path
module=dsh_control if sys.argv[3]=='dsh' else receiver_control
module.ROOT=Path(sys.argv[2])
sys.argv=['control','start']
try:module.main()
except RuntimeError as error:
    print(str(error));raise SystemExit(23)
raise SystemExit(99)
'''
        import subprocess
        with native.operation(self.root, 'studio-loading'):
            for name in ['dsh', 'receiver']:
                with self.subTest(entry=name):
                    result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'scripts'), str(self.root), name],
                        capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertEqual(result.returncode, 23, result.stderr)
                    self.assertIn('MC_NATIVE_OPERATION_BUSY', result.stdout)

    def test_dsh_open_broadcast_shutdown_refusal_is_preserved(self):
        import urllib.error
        with patch.object(dsh, 'ROOT', self.root), patch.object(dsh, 'owned_processes', return_value=[Mock()]), \
             patch.object(dsh, 'status', return_value={'process_alive': True}), \
             patch.object(dsh.urllib.request, 'build_opener') as opener, patch('psutil.wait_procs') as wait:
            opener.return_value.open.side_effect = urllib.error.HTTPError('http://fixture/', 409, 'broadcast open', {}, None)
            with patch('sys.argv', ['dsh_control.py', 'stop']), self.assertRaises(urllib.error.HTTPError):
                dsh.main()
            wait.assert_not_called()


if __name__ == '__main__':
    unittest.main()
