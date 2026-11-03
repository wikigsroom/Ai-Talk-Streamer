"""Source-check failure boundaries with explicit process/source doubles.

Actual no-Git installation and Node execution are a separate integration probe.
"""
from pathlib import Path
from unittest.mock import patch
import copy
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import mc_source_checks as checks

PASS_TAP = b'1..2\n# tests 2\n# pass 2\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n'


class McSourceCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'; self.root.mkdir()
        self.manifest = json.loads((ROOT / checks.MANIFEST).read_text(encoding='utf-8'))
        self.write(checks.MANIFEST, json.dumps(self.manifest).encode())
        for name in self.manifest['suites']['core']['tests'] + self.manifest['suites']['core']['support']:
            self.write(name, b'// explicit local test source double\n')
        self.node = self.root / 'node.exe'; self.node.write_bytes(b'not executed')
        files = [p for p in self.root.rglob('*') if p.is_file() and p != self.node]
        self.source = {'files': {p.relative_to(self.root).as_posix(): checks.mc.sha(p) for p in files},
                       'snapshot_sha256':'a' * 64, 'kind':'EXPLICIT_SOURCE_DOUBLE'}
        self.output = 'outputs/source-checks/one'
        self.identity = self.enter(patch.object(checks.mc, 'source_identity', return_value=self.source))
        self.probe = self.enter(patch.object(checks, 'native_probe', return_value=(self.node, {'fixture':True}, {}, {})))

    def enter(self, manager):
        value = manager.__enter__(); self.addCleanup(manager.__exit__, None, None, None); return value

    def write(self, name, data):
        path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)

    def run_check(self):
        return checks.run(self.root, node=self.node, output=self.output)

    def fake_child(self, tap=PASS_TAP, code=0, observe=None):
        def run(argv, **kwargs):
            if observe: observe(argv, kwargs)
            kwargs['stdout'].write(tap)
            return subprocess.CompletedProcess(argv, code)
        return self.enter(patch.object(checks.subprocess, 'run', side_effect=run))

    def test_modified_test_is_rejected_before_launch_or_output_creation(self):
        self.write(self.manifest['suites']['core']['tests'][0], b'modified source')
        with self.assertRaisesRegex(checks.mc.PreparationError, 'TEST_NOT_BOUND'): self.run_check()
        self.probe.assert_not_called(); self.assertFalse((self.root / self.output).exists())

    def test_unbound_test_path_cannot_be_executed(self):
        self.source['files'].pop(self.manifest['suites']['core']['tests'][0])
        with self.assertRaisesRegex(checks.mc.PreparationError, 'TEST_NOT_BOUND'): self.run_check()
        self.probe.assert_not_called()

    def test_output_cannot_target_state_or_replace_previous_evidence(self):
        for output in ['state/checks/one', 'outputs/../state/one', 'outputs/source-checks/one']:
            with self.subTest(output=output):
                self.output = output
                if output == 'outputs/source-checks/one':
                    self.write(output + '/keep.txt', b'previous evidence')
                with self.assertRaises(checks.mc.PreparationError): self.run_check()
        self.assertEqual((self.root / self.output / 'keep.txt').read_bytes(), b'previous evidence')
        self.probe.assert_not_called()

    def test_nonzero_test_exit_keeps_raw_tap_and_failure_report(self):
        tap = PASS_TAP.replace(b'# pass 2', b'# pass 1').replace(b'# fail 0', b'# fail 1')
        self.fake_child(tap, 1); result = self.run_check()
        self.assertFalse(result['ok']); self.assertEqual(result['code'], 'MC_SOURCE_CHECK_TESTS_FAILED')
        self.assertEqual(result['node_exit_code'], 1); self.assertEqual(result['tests']['fail'], 1)
        self.assertEqual((self.root / self.output / 'test-output.tap').read_bytes(), tap)
        self.assertEqual(json.loads((self.root / self.output / 'report.json').read_text())['tests'], result['tests'])

    def test_missing_tap_summary_cannot_be_reported_as_success(self):
        self.fake_child(b'partial test output\n'); result = self.run_check()
        self.assertFalse(result['ok']); self.assertEqual(result['code'], 'MC_SOURCE_CHECK_TAP_INCOMPLETE')

    def test_todo_tests_are_not_accepted_as_completed_checks(self):
        self.fake_child(PASS_TAP.replace(b'# todo 0', b'# todo 1'))
        result = self.run_check()
        self.assertFalse(result['ok']); self.assertEqual(result['code'], 'MC_SOURCE_CHECK_TESTS_FAILED')

    def test_source_change_during_checks_invalidates_a_passing_child(self):
        changed = copy.deepcopy(self.source); changed['snapshot_sha256'] = 'b' * 64
        self.identity.side_effect = [self.source, self.source, changed]
        self.fake_child(); result = self.run_check()
        self.assertFalse(result['ok']); self.assertFalse(result['source_unchanged'])
        self.assertEqual(result['code'], 'MC_SOURCE_CHECK_SOURCE_CHANGED')

    def test_test_process_uses_bound_files_closed_stdin_and_scoped_temp(self):
        def observe(argv, kwargs):
            self.assertEqual(argv[5:], self.manifest['suites']['core']['tests'])
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL); self.assertEqual(kwargs['cwd'], self.root)
            self.assertTrue(Path(kwargs['env']['TEMP']).is_relative_to(self.root / self.output))
        self.fake_child(observe=observe); result = self.run_check()
        self.assertTrue(result['ok']); self.assertEqual(result['tests']['pass'], 2)
        for key in ['services_started', 'models_loaded', 'real_minecraft', 'native_dsh_booted', 'native_environment_prepared']:
            self.assertFalse(result[key])

    def test_runtime_version_mismatch_cannot_launch_tests(self):
        self.probe.side_effect = checks.mc.PreparationError('MC_SOURCE_CHECK_NODE')
        with self.assertRaisesRegex(checks.mc.PreparationError, 'MC_SOURCE_CHECK_NODE'): self.run_check()
        self.assertFalse((self.root / self.output).exists())


if __name__ == '__main__': unittest.main()
