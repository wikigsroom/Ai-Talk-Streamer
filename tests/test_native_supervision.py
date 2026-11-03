"""Real Windows supervision with isolated stdlib processes, never models."""
from pathlib import Path
from unittest.mock import Mock, patch
import json
import os
import subprocess
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import native_operation as native
import test_native_operation as fixtures
import native_supervision as supervision
from native_windows_process import identity_alive, shared_read


@unittest.skipUnless(os.name == 'nt', 'Actual native Windows process groups')
class NativeSupervisionTests(unittest.TestCase):
    setUp = fixtures.NativeOperationTests.setUp
    cleanup_helpers = fixtures.NativeOperationTests.cleanup_helpers
    wait_for = fixtures.NativeOperationTests.wait_for
    spawn = fixtures.NativeOperationTests.spawn
    capture_family = fixtures.NativeOperationTests.capture_family
    assert_family_closed = fixtures.NativeOperationTests.assert_family_closed

    def receipt(self, transaction):
        return supervision.paths(self.root, transaction.value['operation_id'])['status']

    def wait_terminal(self, transaction):
        path = self.receipt(transaction)
        self.wait_for(lambda: native.read_json(path)['phase'] in {'FAULTED', 'STOPPED'})
        return native.read_json(path)

    def kill(self, process):
        import psutil
        target = psutil.Process(process.pid)
        target.kill(); target.wait(timeout=5)

    def test_unexpected_root_exit_reaps_committed_descendants(self):
        with native.operation(self.root, 'unexpected-exit') as transaction:
            process = self.spawn(transaction, levels=2)
            self.capture_family(2)
        self.kill(process)
        self.assert_family_closed()
        receipt = self.wait_terminal(transaction)
        self.assertEqual(receipt['reason'], 'UNEXPECTED_ROOT_EXIT')
        self.assertTrue(receipt['family_empty_confirmed'])
        self.assertTrue(receipt['registry_cleanup_confirmed'])

    def test_supervisor_crash_closes_job_and_query_does_not_claim_running(self):
        with native.operation(self.root, 'supervisor-crash') as transaction:
            self.spawn(transaction, levels=2)
            self.capture_family(2)
        value = native.read_json(self.receipt(transaction))
        self.assertTrue(identity_alive(value['supervisor']))
        self.kill(Mock(pid=value['supervisor']['pid']))
        self.assert_family_closed()
        view = supervision.status(self.root)['groups'][0]
        self.assertEqual(view['phase'], 'SUPERVISOR_EXITED')
        self.assertFalse(view['supervisor_alive'])
        self.assertFalse(view['family_empty_confirmed'])
        self.assertFalse(view['service_readiness_checked'])

    def test_one_expected_stop_preserves_other_service_until_last_stop(self):
        registry = self.root / '.setup/owned.json'
        with native.operation(self.root, 'pair') as transaction:
            first = self.spawn(transaction, key='avatar')
            second = self.spawn(transaction, key='tts')
        records = json.loads(registry.read_text())
        with native.operation(self.root, 'stop-avatar', recovery=True):
            with supervision.expected_stops(self.root, [(registry, 'avatar', records['avatar'])]):
                self.kill(first)
        self.assertTrue(identity_alive(second.identity()))
        self.assertEqual(native.read_json(self.receipt(transaction))['phase'], 'RUNNING')
        with native.operation(self.root, 'stop-tts', recovery=True):
            with supervision.expected_stops(self.root, [(registry, 'tts', records['tts'])]):
                self.kill(second)
        self.assert_family_closed()
        self.assertEqual(self.wait_terminal(transaction)['phase'], 'STOPPED')
        self.assertEqual(json.loads(registry.read_text()), {})

    def test_failed_planned_stop_restores_unexpected_exit_monitoring(self):
        registry = self.root / '.setup/owned.json'
        with native.operation(self.root, 'pair') as transaction:
            first = self.spawn(transaction, key='avatar')
            self.spawn(transaction, key='tts')
        record = json.loads(registry.read_text())['avatar']
        with self.assertRaisesRegex(RuntimeError, 'stop rejected'):
            with native.operation(self.root, 'rejected-stop', recovery=True):
                with supervision.expected_stops(self.root, [(registry, 'avatar', record)]):
                    raise RuntimeError('stop rejected')
        files = supervision.paths(self.root, transaction.value['operation_id'])
        self.assertEqual(json.loads(files['stop'].read_text())['expected'], [])
        self.kill(first)
        self.assert_family_closed()
        self.assertEqual(self.wait_terminal(transaction)['phase'], 'FAULTED')

    def test_failure_does_not_stop_preexisting_other_job(self):
        registry = self.root / '.setup/owned.json'
        with native.operation(self.root, 'existing') as older:
            old = self.spawn(older, key='external')
        with native.operation(self.root, 'new-pair') as transaction:
            first = self.spawn(transaction, key='avatar')
            second = self.spawn(transaction, key='tts')
        self.kill(first)
        self.wait_for(lambda: not identity_alive(second.identity()))
        self.wait_terminal(transaction)
        self.assertTrue(identity_alive(old.identity()))
        self.assertEqual(set(json.loads(registry.read_text())), {'external'})

    def test_cleanup_preserves_replacement_registry_owner(self):
        registry = self.root / '.setup/owned.json'
        with native.operation(self.root, 'owner') as transaction:
            process = self.spawn(transaction)
        replacement = {'pid': 17, 'note': 'replacement must survive'}
        with native.operation(self.root, 'replace-record'):
            native.atomic_json(self.root, registry, replacement)
        self.kill(process)
        self.wait_terminal(transaction)
        self.assertEqual(json.loads(registry.read_text()), replacement)

    def test_controller_exits_after_commit_but_worker_keeps_group_owned(self):
        script = '''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from native_operation import operation
root=Path(sys.argv[2])
with operation(root,'short-controller') as transaction:
    with (root/'stdout.log').open('ab') as out,(root/'stderr.log').open('ab') as err:
        transaction.spawn([sys.executable,'-B',str(root/'helper with spaces.py'),str(root),'2'],cwd=root,
            stdout=out,stderr=err,registry=root/'.setup/owned.json')
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT/'scripts'), str(self.root)],
                                capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.capture_family(2)
        record = json.loads((self.root/'.setup/owned.json').read_text())
        self.assertTrue(identity_alive(record))
        self.kill(Mock(pid=record['pid']))
        self.assert_family_closed()
        self.wait_for(lambda: supervision.status(self.root)['groups'][0]['phase'] == 'FAULTED')

    def test_controller_dies_during_handoff_and_worker_aborts_uncommitted_group(self):
        script = '''import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from native_operation import operation
from native_supervision import Handoff
root=Path(sys.argv[2])
with operation(root,'uncommitted-controller') as transaction:
    with (root/'stdout.log').open('ab') as out,(root/'stderr.log').open('ab') as err:
        transaction.spawn([sys.executable,'-B',str(root/'helper with spaces.py'),str(root),'2'],cwd=root,
            stdout=out,stderr=err,registry=root/'.setup/owned.json')
    transaction.value['phase']='COMMITTING';transaction.write()
    transaction.supervisor=Handoff(transaction)
    os._exit(27)
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT/'scripts'), str(self.root)],
                                capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 27, result.stderr)
        self.wait_for(lambda: supervision.status(self.root)['groups'] and
                      supervision.status(self.root)['groups'][0]['phase'] == 'FAULTED')
        view = supervision.status(self.root)['groups'][0]
        self.assertTrue(view['family_empty_confirmed'])
        self.assertTrue(view['registry_cleanup_confirmed'])
        self.assertTrue(all(not identity_alive(p) for p in view['members']))

    def test_failed_final_commit_terminates_armed_worker_too(self):
        with self.assertRaisesRegex(OSError, 'commit failed'):
            with native.operation(self.root, 'failed-commit') as transaction:
                self.spawn(transaction, levels=1)
                self.capture_family(1)
                write = transaction.write
                def fail():
                    if transaction.value['phase'] == 'COMPLETED':
                        raise OSError('commit failed')
                    write()
                transaction.write = fail
        self.assert_family_closed()
        self.assertFalse(identity_alive(native.read_json(self.receipt(transaction))['supervisor']))
        self.assertEqual(native.status(self.root)['phase'], 'ROLLED_BACK')

    def test_bad_stop_member_fails_closed_and_reaps_only_group(self):
        with native.operation(self.root, 'bad-control') as transaction:
            self.spawn(transaction, levels=1)
            self.capture_family(1)
        files = supervision.paths(self.root, transaction.value['operation_id'])
        native.atomic_json(self.root, files['stop'], {'schema_version': 1,
            'operation_id': transaction.value['operation_id'], 'expected': [{'pid': 123, 'creation_ticks': 456}]})
        self.assert_family_closed()
        self.assertEqual(self.wait_terminal(transaction)['reason'], 'SUPERVISION_FAILURE')

    def test_stop_requires_lock_and_exact_original_registry_record(self):
        registry = self.root / '.setup/owned.json'
        with native.operation(self.root, 'owner') as transaction:
            process = self.spawn(transaction)
        record = json.loads(registry.read_text())
        with self.assertRaisesRegex(native.OperationError, 'REQUIRES_OPERATION'):
            with supervision.expected_stops(self.root, [(registry, None, record)]):
                self.fail('stop must not execute')
        with native.operation(self.root, 'bad-owner', recovery=True):
            with self.assertRaisesRegex(native.OperationError, 'OWNER_MISMATCH'):
                with supervision.expected_stops(self.root, [(registry, None, {**record, 'command': ['changed']})]):
                    self.fail('stop must not execute')
        self.assertTrue(identity_alive(process.identity()))

    def test_legacy_stop_and_empty_status_do_not_start_a_worker(self):
        self.assertEqual(supervision.status(self.root)['groups'], [])
        with native.operation(self.root, 'legacy-stop', recovery=True):
            with supervision.expected_stops(self.root, [(self.root/'old.json', None, {'pid': 42})]):
                pass
        self.assertFalse((self.root/supervision.DIRECTORY).exists())

    def test_query_rejects_status_identity_mismatch(self):
        operation_id = 'a' * 32
        files = supervision.paths(self.root, operation_id)
        native.atomic_json(self.root, files['status'], {'operation_id': 'b' * 32})
        with self.assertRaisesRegex(native.OperationError, 'STATUS_INVALID'):
            supervision.status(self.root)
        files['status'].unlink()

    def test_handoff_creation_failure_rolls_back_new_family(self):
        with patch.object(supervision, 'spawn_process', side_effect=OSError('handoff creation failed')):
            with self.assertRaisesRegex(OSError, 'handoff creation failed'):
                with native.operation(self.root, 'handoff-failure') as transaction:
                    self.spawn(transaction, levels=1)
                    self.capture_family(1)
        self.assert_family_closed()
        self.assertEqual(native.status(self.root)['phase'], 'ROLLED_BACK')

    def test_job_limit_failure_after_arming_reaps_worker_and_new_family(self):
        with patch.object(native.NativeJob, 'prepare_commit', side_effect=OSError('job limits failed')):
            with self.assertRaisesRegex(OSError, 'job limits failed'):
                with native.operation(self.root, 'limit-failure') as transaction:
                    self.spawn(transaction, levels=1)
                    self.capture_family(1)
        self.assert_family_closed()
        self.assertFalse(identity_alive(native.read_json(self.receipt(transaction))['supervisor']))

    def test_root_exit_after_arming_is_rejected_before_durable_commit(self):
        with self.assertRaisesRegex(native.OperationError, 'EXITED_DURING_HANDOFF'):
            with native.operation(self.root, 'exit-at-handoff') as transaction:
                process = self.spawn(transaction, levels=1)
                self.capture_family(1)
                prepare = transaction.job.prepare_commit
                def exit_at_handoff(**options):
                    prepare(**options)
                    self.kill(process)
                transaction.job.prepare_commit = exit_at_handoff
        self.assert_family_closed()
        self.assertFalse(identity_alive(native.read_json(self.receipt(transaction))['supervisor']))

    def test_dsh_broadcast_refusal_with_owned_group_restores_monitoring(self):
        import dsh_control as dsh
        import psutil
        import urllib.error
        registry = self.root / '.setup/dsh-process.json'
        with native.operation(self.root, 'dsh-pair') as transaction:
            first = self.spawn(transaction, registry=registry)
            self.spawn(transaction, registry=self.root/'.setup/other.json')
        with patch.object(dsh, 'ROOT', self.root), patch.object(dsh, 'owned_processes', return_value=[psutil.Process(first.pid)]), \
             patch.object(dsh, 'status', return_value={'process_alive': True}), \
             patch.object(dsh.urllib.request, 'build_opener') as opener, \
             patch('sys.argv', ['dsh_control.py', 'stop']):
            opener.return_value.open.side_effect = urllib.error.HTTPError('http://fixture/', 409, 'broadcast open', {}, None)
            with self.assertRaises(urllib.error.HTTPError):
                dsh.main()
        files = supervision.paths(self.root, transaction.value['operation_id'])
        self.assertEqual(json.loads(files['stop'].read_text())['expected'], [])
        self.kill(first)
        self.assert_family_closed()
        self.assertEqual(self.wait_terminal(transaction)['phase'], 'FAULTED')

    def test_shared_reader_and_replacement_keep_complete_consistent_records(self):
        path = self.root/'record.json'
        native.atomic_json(self.root, path, {'revision': 1})
        errors = []
        started = threading.Event()
        def write():
            started.set()
            try:
                native.atomic_json(self.root, path, {'revision': 2})
            except BaseException as error:
                errors.append(error)
        with shared_read(path) as reader:
            thread = threading.Thread(target=write)
            thread.start()
            self.assertTrue(started.wait(timeout=1))
            self.assertEqual(json.load(reader), {'revision': 1})
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(native.read_json(path), {'revision': 2})

    def test_short_ordinary_reader_contention_retries_then_preserves_new_record(self):
        path = self.root/'record.json'
        native.atomic_json(self.root, path, {'revision': 1})
        collision = threading.Event()
        errors = []
        replace = native.os.replace
        def observed_replace(source, destination):
            try:
                return replace(source, destination)
            except PermissionError:
                collision.set()
                raise
        def write():
            try:
                native.atomic_json(self.root, path, {'revision': 2})
            except BaseException as error:
                errors.append(error)
        with path.open('rb') as reader, patch.object(native.os, 'replace', side_effect=observed_replace):
            thread = threading.Thread(target=write)
            thread.start()
            collided = collision.wait(timeout=.5)
            self.assertEqual(json.load(reader), {'revision': 1})
        thread.join(timeout=3)
        self.assertTrue(collided, 'Actual Windows replacement sharing violation was not observed')
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(native.read_json(path), {'revision': 2})

    def test_persistent_record_contention_retains_old_data_and_fails_in_time(self):
        path = self.root/'record.json'
        native.atomic_json(self.root, path, {'revision': 1})
        with path.open('rb') as reader:
            with self.assertRaises(PermissionError):
                native.atomic_json(self.root, path, {'revision': 2})
            self.assertEqual(json.load(reader), {'revision': 1})
        self.assertEqual(native.read_json(path), {'revision': 1})
        self.assertEqual(list(self.root.glob('record.json.*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
