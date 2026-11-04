"""Actual Windows CPU-import progress, deadlines and family cleanup; no models loaded."""
from pathlib import Path
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
from native_import_check import ImportCheckError, run_imports
from native_windows_process import NativeJob, identity_alive


@unittest.skipUnless(os.name == 'nt', 'Actual Windows job and venv redirector checks')
class NativeImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='mc-import-原生 ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.modules = self.root / 'modules'; self.modules.mkdir()
        candidate = Path(sys.prefix) / 'Scripts/python.exe'
        self.python = candidate if candidate.is_file() else Path(sys.executable)
        self.env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '-1', 'PYTHONDONTWRITEBYTECODE': '1',
                    'PYTHONPATH': str(ROOT / 'scripts'), 'PYTHONUTF8': '1'}
        self.updates = []

    def run_probe(self, modules, **kwargs):
        return run_imports(self.root, self.python, modules, env=self.env, label='fixture',
                           source_paths=['modules'], progress=kwargs.pop('progress', self.updates.append), **kwargs)

    def module(self, name, source):
        (self.modules / (name + '.py')).write_text(source, encoding='utf8')

    def assert_closed(self, details):
        self.assertTrue(details['family_closed'])
        self.assertFalse(identity_alive(details['owner']))

    def test_success_records_each_real_import_and_closed_family(self):
        self.module('first', 'VALUE=1\n')
        self.module('second', 'from first import VALUE\nassert VALUE==1\n')
        result = self.run_probe(['first', 'second'], timeout=20, module_timeout=10)
        self.assertTrue(result['ok']); self.assertTrue(result['cpu_only'])
        self.assertEqual([r['module'] for r in result['completed']], ['first', 'second'])
        self.assertEqual(result['phase'], 'SUCCEEDED'); self.assert_closed(result)
        log = (self.root / result['log']).read_text(encoding='utf8')
        self.assertIn('"phase": "IMPORTING", "module": "first"', log)
        self.assertIn('"phase": "IMPORTING", "module": "second"', log)
        self.assertTrue(all(type(r['elapsed_ms']) is int and r['elapsed_ms'] >= 0 for r in result['completed']))

    def test_interpreter_start_deadline_reports_no_module_and_closes_venv(self):
        self.module('sitecustomize', 'import time;time.sleep(60)\n')
        self.env['PYTHONPATH'] = str(self.modules)
        with self.assertRaises(ImportCheckError) as failed:
            self.run_probe(['json'], timeout=1, module_timeout=30)
        self.assertEqual(failed.exception.code, 'MC_IMPORT_CHECK_TIMEOUT')
        self.assertEqual(failed.exception.details['phase'], 'WAITING_FOR_INTERPRETER')
        self.assertIsNone(failed.exception.details['module']); self.assert_closed(failed.exception.details)

    def test_group_deadline_stops_a_module_before_its_longer_individual_limit(self):
        self.module('slow', 'import time;time.sleep(60)\n')
        with self.assertRaises(ImportCheckError) as failed:
            self.run_probe(['slow'], timeout=1.5, module_timeout=30)
        self.assertEqual(failed.exception.code, 'MC_IMPORT_CHECK_TIMEOUT')
        self.assert_closed(failed.exception.details)

    def test_import_error_exposes_module_without_exception_secret(self):
        self.module('broken', "raise RuntimeError('SECRET_FIXTURE_ERROR_VALUE')\n")
        with self.assertRaises(ImportCheckError) as failed:
            self.run_probe(['json', 'broken'], timeout=20, module_timeout=10)
        details = failed.exception.details
        self.assertEqual(details['module'], 'broken'); self.assertEqual(details['error_type'], 'RuntimeError')
        self.assertEqual(details['completed'][0]['module'], 'json')
        self.assertNotIn('SECRET_FIXTURE_ERROR_VALUE', json.dumps(details))
        self.assertNotIn('SECRET_FIXTURE_ERROR_VALUE', (self.root / details['log']).read_text(encoding='utf8'))
        self.assert_closed(details)

    def test_module_timeout_closes_real_child_grandchild_but_preserves_unrelated(self):
        helper = self.root / 'descendant.py'
        helper.write_text('''from pathlib import Path
import json,os,subprocess,sys,time
from native_windows_process import api,checked,creation_ticks
root=Path(sys.argv[1]);level=int(sys.argv[2]);kernel=api();handle=checked(kernel.OpenProcess(0x1000,False,os.getpid()))
try:value={'pid':os.getpid(),'creation_ticks':creation_ticks(kernel,handle)}
finally:kernel.CloseHandle(handle)
(root/('owner-'+str(level)+'.json')).write_text(json.dumps(value))
if level:subprocess.Popen([sys.executable,__file__,str(root),str(level-1)],creationflags=0x08000000)
while True:time.sleep(.02)
''', encoding='utf8')
        external = self.root / 'external'; external.mkdir()
        external_job = NativeJob()
        with (self.root / 'unrelated.log').open('wb') as log:
            unrelated = external_job.spawn([str(self.python), '-X', 'utf8', '-B', str(helper), str(external), '0'],
                                            cwd=self.root, env=self.env, stdout=log, stderr=log)
        self.module('family', 'from pathlib import Path\nimport subprocess,sys,time\n'
                    + 'root=Path(' + repr(str(self.root)) + ')\n'
                    + "subprocess.Popen([sys.executable,str(root/'descendant.py'),str(root),'1'],creationflags=0x08000000)\n"
                    + 'while True:time.sleep(.02)\n')
        identities = []
        def ready(value):
            self.updates.append(value)
            if value['phase'] != 'IMPORTING' or identities:
                return
            limit = time.monotonic() + 8
            paths = [self.root / ('owner-' + str(n) + '.json') for n in [0, 1]]
            while time.monotonic() < limit:
                try:
                    identities.extend(json.loads(p.read_text(encoding='utf8')) for p in paths)
                    return
                except (FileNotFoundError, json.JSONDecodeError):
                    identities.clear(); time.sleep(.02)
            self.fail('actual child and grandchild were not observed')
        try:
            with self.assertRaises(ImportCheckError) as failed:
                self.run_probe(['family'], timeout=30, module_timeout=10, progress=ready)
            self.assertEqual(failed.exception.code, 'MC_IMPORT_MODULE_TIMEOUT')
            self.assertEqual(failed.exception.details['module'], 'family')
            self.assertEqual(len(identities), 2)
            self.assertTrue(all(not identity_alive(v) for v in identities))
            self.assertIsNone(unrelated.poll()); self.assert_closed(failed.exception.details)
        finally:
            external_job.rollback(timeout=10)
            unrelated.close(); external_job.close()

    def test_lingering_background_child_cannot_turn_probe_exit_into_success(self):
        self.module('background', 'import subprocess,sys\n'
                    + "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],creationflags=0x08000000)\n")
        with self.assertRaises(ImportCheckError) as failed:
            self.run_probe(['background'], timeout=20, module_timeout=10)
        self.assertEqual(failed.exception.code, 'MC_IMPORT_FAMILY_STILL_RUNNING')
        self.assertFalse(failed.exception.details['ok']); self.assert_closed(failed.exception.details)

    def test_non_cpu_environment_is_rejected_before_starting_process_or_writing_state(self):
        self.env.pop('CUDA_VISIBLE_DEVICES')
        with self.assertRaisesRegex(ValueError, 'CPU_ENVIRONMENT_REQUIRED'):
            self.run_probe(['json'])
        self.assertFalse((self.root / '.setup').exists())

    def held_progress_reader(self, *, release_after=None):
        self.module('reader_fixture', 'from pathlib import Path\nimport time\n'
                    + 'root=Path(' + repr(str(self.root)) + ')\n'
                    + "(root/'module-entered').touch()\n"
                    + "while not(root/'release-module').exists():time.sleep(.01)\n")
        readers = []
        def hold(value):
            self.updates.append(value)
            if value['phase'] != 'IMPORTING' or readers:
                return
            deadline = time.monotonic() + 5
            while not (self.root / 'module-entered').exists():
                if time.monotonic() >= deadline:
                    self.fail('fixture module did not enter')
                time.sleep(.01)
            # Ordinary Windows readers deny replacement while their handle is open.
            reader = (self.root / value['progress']).open('rb')
            readers.append(reader)
            if release_after is not None:
                timer = threading.Timer(release_after, reader.close)
                timer.daemon = True
                timer.start()
                self.addCleanup(timer.join)
            (self.root / 'release-module').touch()
        return hold, readers

    def test_transient_windows_reader_does_not_fail_an_import(self):
        hold, readers = self.held_progress_reader(release_after=.3)
        try:
            result = self.run_probe(['reader_fixture'], progress=hold, timeout=20, module_timeout=10)
            self.assertTrue(result['ok']); self.assert_closed(result)
        finally:
            for reader in readers:reader.close()

    def test_persistent_windows_reader_has_bounded_failure_and_closed_family(self):
        hold, readers = self.held_progress_reader()
        try:
            with self.assertRaises(ImportCheckError) as failed:
                self.run_probe(['reader_fixture'], progress=hold, timeout=20, module_timeout=10)
            self.assertEqual(failed.exception.code, 'MC_IMPORT_CHECK_FAILED')
            self.assertGreaterEqual(failed.exception.details['elapsed_ms'], 1000)
            self.assertLess(failed.exception.details['elapsed_ms'], 10000)
            self.assert_closed(failed.exception.details)
        finally:
            for reader in readers:reader.close()

    def test_progress_write_failure_still_closes_family_without_exposing_text(self):
        def unavailable(value):
            raise OSError('SECRET_PROGRESS_DESTINATION')
        with self.assertRaises(ImportCheckError) as failed:
            self.run_probe(['json'], progress=unavailable)
        self.assertEqual(failed.exception.code, 'MC_IMPORT_PROGRESS_PUBLISH_FAILED')
        self.assertNotIn('SECRET_PROGRESS_DESTINATION', json.dumps(failed.exception.details))
        self.assert_closed(failed.exception.details)


if __name__ == '__main__':unittest.main(verbosity=2)
