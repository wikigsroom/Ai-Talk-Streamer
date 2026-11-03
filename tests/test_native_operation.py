"""Actual native Windows process/lock tests using temporary stdlib-only helpers.

No application service, model, game, browser, network listener or GPU is started.
"""
from pathlib import Path
from unittest.mock import patch
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
import native_operation as native
from native_windows_process import identity_alive

HELPER = '''from pathlib import Path
import json, os, subprocess, sys, time
folder=Path(sys.argv[1]); level=int(sys.argv[2])
(folder/('pid-'+str(level)+'.json')).write_text(json.dumps({'pid':os.getpid()}))
if level:
    subprocess.Popen([sys.executable, __file__, str(folder), str(level-1)], creationflags=subprocess.CREATE_NO_WINDOW)
while not (folder/'stop').exists():time.sleep(.02)
'''


@unittest.skipUnless(os.name == 'nt', 'Actual native Windows lifecycle checks')
class NativeOperationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='mc-native-原生 ')
        self.root = Path(self.folder.name)
        self.helper = self.root / 'helper with spaces.py'
        self.helper.write_text(HELPER, encoding='utf-8')
        self.identities = []
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.cleanup_helpers)

    def cleanup_helpers(self):
        import psutil
        (self.root / 'stop').touch()
        for identity in reversed(self.identities):
            try:
                if identity_alive(identity):
                    process = psutil.Process(identity['pid'])
                    process.kill(); process.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
        # Committed groups now have an independent, bounded cleanup worker.
        # Wait for its exact identity before removing this test's directory.
        for path in (self.root / '.setup/native-supervision').glob('*.json'):
            if len(path.stem) != 32:
                continue
            worker = json.loads(path.read_text(encoding='utf-8'))['supervisor']
            try:
                if identity_alive(worker):
                    process = psutil.Process(worker['pid'])
                    try:
                        process.wait(timeout=12)
                    except psutil.TimeoutExpired:
                        if identity_alive(worker):
                            process.kill(); process.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
        evidence = os.environ.get('MC_NATIVE_SUPERVISION_EVIDENCE_ROOT')
        if evidence and (self.root / '.setup').exists():
            import shutil
            target = Path(evidence) / self.id()
            target.mkdir(parents=True, exist_ok=False)
            shutil.copytree(self.root / '.setup', target / '.setup')

    def wait_for(self, condition):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.02)
        self.fail('Temporary process condition timed out')

    def spawn(self, transaction, levels=0, key=None, registry=None):
        with (self.root / 'stdout.log').open('ab') as out, (self.root / 'stderr.log').open('ab') as err:
            process = transaction.spawn([sys.executable, '-X', 'utf8', '-B', str(self.helper), str(self.root), str(levels)],
                cwd=self.root, stdout=out, stderr=err,
                registry=registry or self.root / '.setup/owned.json', key=key)
        self.identities.append(process.identity())
        return process

    def capture_family(self, levels):
        import psutil
        self.wait_for(lambda: all((self.root / ('pid-' + str(n) + '.json')).exists() for n in range(levels + 1)))
        for level in range(levels + 1):
            path = self.root / ('pid-' + str(level) + '.json')
            self.wait_for(lambda: path.stat().st_size > 0)
            process = psutil.Process(json.loads(path.read_text())['pid'])
            ticks = round((process.create_time() + 11644473600) * 10_000_000)
            # Read the immutable native creation time rather than round-trip a float.
            from native_windows_process import api, creation_ticks, checked
            kernel = api(); handle = checked(kernel.OpenProcess(0x1000, False, process.pid))
            try:
                ticks = creation_ticks(kernel, handle)
            finally:
                kernel.CloseHandle(handle)
            self.identities.append({'pid': process.pid, 'creation_ticks': ticks})

    def assert_family_closed(self):
        self.wait_for(lambda: not any(identity_alive(value) for value in self.identities))

    def test_real_parent_child_grandchild_rollback_and_registry_cleanup(self):
        with self.assertRaisesRegex(RuntimeError, 'later component failed'):
            with native.operation(self.root, 'whole-start') as transaction:
                self.spawn(transaction, levels=2, key='avatar')
                self.capture_family(2)
                self.assertGreaterEqual(transaction.job.active(), 3)
                raise RuntimeError('later component failed')
        self.assert_family_closed()
        self.assertEqual(json.loads((self.root / '.setup/owned.json').read_text()), {})
        self.assertEqual(native.status(self.root)['phase'], 'ROLLED_BACK')

    def test_committed_family_survives_controller_context_exit(self):
        with native.operation(self.root, 'single-start') as transaction:
            process = self.spawn(transaction, levels=1)
            identity = process.identity()
            self.capture_family(1)
        self.assertTrue(identity_alive(identity))
        record = json.loads((self.root / '.setup/owned.json').read_text())
        self.assertEqual(record['creation_ticks'], identity['creation_ticks'])
        self.assertEqual(record['native_operation_id'], transaction.value['operation_id'])
        self.assertEqual(native.status(self.root)['phase'], 'COMPLETED')
        (self.root / 'stop').touch()
        self.assert_family_closed()

    def test_other_process_cannot_enter_while_operation_owns_os_lock(self):
        code = '''import sys
sys.path.insert(0,sys.argv[1])
from native_operation import operation,OperationError
try:
    with operation(sys.argv[2],'contending-start'):pass
except OperationError as error:
    print(str(error));sys.exit(23)
sys.exit(99)
'''
        with native.operation(self.root, 'first'):
            result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'scripts'), str(self.root)],
                capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertIn('MC_NATIVE_OPERATION_BUSY', result.stdout)

    def test_other_thread_is_busy_but_same_thread_nests_one_transaction(self):
        errors = []
        def contender():
            try:
                with native.operation(self.root, 'other-thread'):pass
            except native.OperationError as error:
                errors.append(str(error))
        with native.operation(self.root, 'outer') as outer:
            with native.operation(self.root, 'inner') as inner:
                self.assertIs(outer, inner)
            thread = threading.Thread(target=contender)
            thread.start(); thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ['MC_NATIVE_OPERATION_BUSY'])

    def test_caught_nested_failure_still_aborts_outer_new_processes(self):
        with self.assertRaisesRegex(native.OperationError, 'NESTED_OPERATION_ABORTED'):
            with native.operation(self.root, 'outer') as transaction:
                self.spawn(transaction)
                try:
                    with native.operation(self.root, 'inner'):
                        raise ValueError('nested failure')
                except ValueError:
                    pass
        self.assert_family_closed()

    def test_registry_replace_failure_rolls_back_new_family(self):
        replace = native.os.replace
        registry = self.root / '.setup/owned.json'
        def fail_record(source, destination):
            if Path(destination) == registry:
                raise OSError('injected registry write failure')
            return replace(source, destination)
        with self.assertRaisesRegex(OSError, 'registry write failure'):
            with native.operation(self.root, 'start') as transaction:
                with patch.object(native.os, 'replace', side_effect=fail_record):
                    self.spawn(transaction)
        # The spawn error happens before the helper is returned to the caller.
        self.identities.extend(transaction.value['processes'])
        self.assert_family_closed()
        self.assertFalse(registry.exists())

    def test_final_commit_record_failure_still_terminates_new_process(self):
        with self.assertRaisesRegex(OSError, 'commit record failure'):
            with native.operation(self.root, 'start') as transaction:
                self.spawn(transaction)
                write = transaction.write
                def fail_commit():
                    if transaction.value['phase'] == 'COMPLETED':
                        raise OSError('commit record failure')
                    return write()
                transaction.write = fail_commit
        self.assert_family_closed()
        self.assertEqual(native.status(self.root)['phase'], 'ROLLED_BACK')

    def test_existing_running_record_is_not_overwritten_or_duplicated(self):
        with native.operation(self.root, 'first') as transaction:
            old = self.spawn(transaction)
            identity = old.identity()
        registry = self.root / '.setup/owned.json'
        before = registry.read_bytes()
        with self.assertRaisesRegex(native.OperationError, 'SERVICE_ALREADY_OWNED'):
            with native.operation(self.root, 'second') as transaction:
                self.spawn(transaction)
        self.assertEqual(registry.read_bytes(), before)
        self.assertTrue(identity_alive(identity))

    def test_rollback_preserves_unrelated_registry_entry(self):
        registry = self.root / '.setup/owned.json'
        existing = {'external': {'note': 'leave unchanged'}}
        native.atomic_json(self.root, registry, existing)
        with self.assertRaisesRegex(ValueError, 'abort'):
            with native.operation(self.root, 'start') as transaction:
                self.spawn(transaction, key='avatar')
                raise ValueError('abort')
        self.assertEqual(json.loads(registry.read_text()), existing)
        self.assert_family_closed()

    def test_stale_pid_with_different_creation_time_is_not_the_owner(self):
        from native_windows_process import api, creation_ticks, checked
        kernel = api(); handle = checked(kernel.OpenProcess(0x1000, False, os.getpid()))
        try:
            ticks = creation_ticks(kernel, handle)
        finally:
            kernel.CloseHandle(handle)
        self.assertFalse(identity_alive({'pid': os.getpid(), 'creation_ticks': ticks - 1}))
        self.assertTrue(identity_alive({'pid': os.getpid(), 'creation_ticks': ticks}))

    def test_failed_rollback_remains_blocked_until_exact_owner_exits(self):
        with native.operation(self.root, 'first') as transaction:
            process = self.spawn(transaction)
            identity = process.identity()
        path = self.root / native.LOCK
        value = native.status(self.root)
        value['phase'] = 'ROLLBACK_INCOMPLETE'
        path.write_bytes(b'\0' + json.dumps(value).encode('utf-8'))
        with self.assertRaisesRegex(native.OperationError, 'RECOVERY_REQUIRED'):
            with native.operation(self.root, 'start'):pass
        self.assertTrue(identity_alive(identity))
        with self.assertRaisesRegex(native.OperationError, 'RECOVERY_INCOMPLETE'):
            with native.operation(self.root, 'stop', recovery=True):pass
        self.assertTrue(native.status(self.root)['recovery_required'])
        (self.root / 'stop').touch()
        self.assert_family_closed()
        # A committed group's independent supervisor removes its registries
        # under the same installation lock after the last process exits.
        from native_supervision import status as supervision_status
        self.wait_for(lambda: all(group.get('registry_cleanup_confirmed') is True
                                 for group in supervision_status(self.root)['groups']))
        with native.operation(self.root, 'start-after-confirmed-exit'):pass
        self.assertFalse(native.status(self.root)['busy'])

    def test_controller_crash_closes_job_and_releases_real_os_lock(self):
        code = '''from pathlib import Path
import sys,time
sys.path.insert(0,sys.argv[1])
from native_operation import operation
root=Path(sys.argv[2])
with operation(root,'controller-crash') as transaction:
    with (root/'crash-out.log').open('ab') as out:
        transaction.spawn([sys.executable,str(root/'helper with spaces.py'),str(root),'2'],
            cwd=root,stdout=out,stderr=out,registry=root/'.setup/owned.json')
    (root/'controller-ready').touch()
    while True:time.sleep(.02)
'''
        controller = subprocess.Popen([sys.executable, '-c', code, str(ROOT / 'scripts'), str(self.root)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.wait_for(lambda: (self.root / 'controller-ready').exists())
            self.capture_family(2)
            controller.kill(); controller.wait(timeout=5)
            self.assert_family_closed()
            with native.operation(self.root, 'after-crash'):pass
            self.assertEqual(native.status(self.root)['phase'], 'COMPLETED')
        finally:
            if controller.poll() is None:
                controller.kill(); controller.wait(timeout=5)

    def test_registry_path_outside_installation_is_rejected_before_spawn(self):
        with self.assertRaisesRegex(native.OperationError, 'OPERATION_PATH'):
            with native.operation(self.root, 'start') as transaction:
                self.spawn(transaction, registry=self.root.parent / 'outside-owned.json')
        self.assertEqual(transaction.value['processes'], [])

    def test_no_operation_status_does_not_create_setup_or_claim_readiness(self):
        value = native.status(self.root)
        self.assertEqual(value['phase'], 'NO_OPERATION')
        self.assertFalse(value['service_readiness_checked'])
        self.assertFalse((self.root / '.setup').exists())

    def test_status_from_other_process_reports_busy_without_releasing_owner(self):
        code = '''import json,sys
sys.path.insert(0,sys.argv[1])
from native_operation import status
print(json.dumps(status(sys.argv[2])))
'''
        with native.operation(self.root, 'loading') as transaction:
            result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'scripts'), str(self.root)],
                capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertTrue(value['busy'])
            self.assertFalse(value['service_readiness_checked'])
            self.assertEqual(value['operation_id'], transaction.value['operation_id'])
            transaction.write()

    def test_unicode_environment_and_explicit_stdin_stdout_handles(self):
        code = 'import os,sys;print(os.environ["MC_NATIVE_TEST_VALUE"]);print(repr(sys.stdin.read()));sys.stdout.flush()'
        environment = dict(os.environ, MC_NATIVE_TEST_VALUE='原生中文路径 with spaces')
        with self.assertRaisesRegex(ValueError, 'fixture complete'):
            with native.operation(self.root, 'environment-test') as transaction:
                with (self.root / 'stdout.log').open('ab') as out, (self.root / 'stderr.log').open('ab') as err:
                    process = transaction.spawn([sys.executable, '-X', 'utf8', '-c', code], cwd=self.root,
                        env=environment, stdout=out, stderr=err, registry=self.root / '.setup/owned.json')
                self.identities.append(process.identity())
                self.wait_for(lambda: process.poll() is not None)
                self.assertEqual(process.poll(), 0)
                output = (self.root / 'stdout.log').read_text(encoding='utf-8')
                self.assertIn(environment['MC_NATIVE_TEST_VALUE'], output)
                self.assertIn("''", output)
                raise ValueError('fixture complete')
        self.assert_family_closed()

    def test_legitimate_exit_code_259_is_not_mistaken_for_running(self):
        with self.assertRaisesRegex(ValueError, 'fixture complete'):
            with native.operation(self.root, 'exit-code-test') as transaction:
                with (self.root / 'stdout.log').open('ab') as out:
                    process = transaction.spawn([sys.executable, '-c', 'raise SystemExit(259)'], cwd=self.root,
                        stdout=out, stderr=out, registry=self.root / '.setup/owned.json')
                self.identities.append(process.identity())
                self.wait_for(lambda: process.poll() is not None)
                self.assertEqual(process.poll(), 259)
                raise ValueError('fixture complete')
        self.assert_family_closed()


if __name__ == '__main__':
    unittest.main()
