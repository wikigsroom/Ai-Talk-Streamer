from pathlib import Path
from contextlib import closing
import hashlib
import json
import os
import queue
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from mc_maintenance_dependencies import MaintenanceError, application_fence, capture
from mc_maintenance_core import MaintenanceCoordinator, NativeRuntime


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


class NativeCoordinatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.java = os.environ.get('MC_TEST_JAVA')
        cls.classpath = os.environ.get('MC_JAVA_TEST_CLASSPATH')
        if not cls.java or not cls.classpath:
            raise unittest.SkipTest('Requires the actual compiled native Java fixtures and pinned JDK21')
        cls.node = os.environ.get('MC_TEST_NODE', str(ROOT.parent / 'tools/node/node-v24.22.1-win-x64/node.exe'))
        cls.base = Path(os.environ.get('MC_MAINTENANCE_TEST_ROOT', ROOT / 'outputs/mc-test-temp'))
        cls.base.mkdir(parents=True, exist_ok=True)
        entries = []
        for name in cls.classpath.split(os.pathsep):
            path = Path(name)
            value = json_sha({p.relative_to(path).as_posix(): sha(p) for p in path.rglob('*') if p.is_file()}) if path.is_dir() else sha(path)
            entries.append({'path': str(path), 'sha256': value})
        cls.runtime_config = {'schema_version': 1, 'java': {'path': cls.java, 'sha256': sha(Path(cls.java))}, 'classpath': entries}

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='maintenance-native-', dir=self.base)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.owned = []
        self.addCleanup(self.stop_owned)
        self.journal = self.root / 'journal'
        self.seed_tmp = self.root / 'seed-native'
        self.seed_tmp.mkdir()
        seeded = subprocess.run([self.java, '-Dorg.sqlite.tmpdir=' + str(self.seed_tmp), '-cp', self.classpath,
                                 'dev.aitalkstreamer.mc.core.MaintenanceCoordinatorFixture', str(self.journal)],
                                capture_output=True, check=True, timeout=20)
        self.instance = json.loads(next(line for line in seeded.stdout.decode('utf-8-sig').splitlines() if line.startswith('{')))['game_instance_id']
        self.database = self.root / 'game.sqlite3'
        subprocess.run([self.node, 'tests/mc-maintenance-fixture.mjs', str(self.database), self.instance],
                       cwd=ROOT, capture_output=True, check=True, timeout=10)
        with closing(sqlite3.connect(self.journal / 'mc-control.sqlite3')) as b:
            task = b.execute("SELECT task FROM tasks WHERE task_id='task-protected'").fetchone()[0]
        with closing(sqlite3.connect(self.database)) as a, a:
            a.execute('INSERT INTO objects VALUES(?,?,?,?,?)', ('task', 'task-protected', 'coordinator-old-world', 1, task))
            a.execute('INSERT INTO task_recovery VALUES(?,?,?)', ('task-protected', 'required', json.dumps({'task_id': 'task-protected', 'status': 'required'})))
        self.configuration = self.root / 'runtime.json'
        self.configuration.write_text(json.dumps(self.runtime_config), encoding='utf-8')
        self.runtime = NativeRuntime(self.configuration)
        self.coordinator = MaintenanceCoordinator(self.database, self.journal, self.runtime, {'fixture_installation': str(self.root)})

    def tearDown(self):
        self.stop_owned()
        result = self._outcome.result
        if any(test is self for test, _ in [*result.failures, *result.errors]):
            destination = self.base.parent.parent / ('failed-fixture-' + self._testMethodName)
            if not destination.exists():
                shutil.copytree(self.root, destination)

    def stop_owned(self):
        for process in self.owned:
            if process.poll() is None:
                try:
                    process.communicate(b'\n', timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=10)
            for stream in [process.stdin, process.stdout, process.stderr]:
                if stream:
                    stream.close()
            self.assertIsNotNone(process.poll())

    def hold(self, argv):
        process = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.owned.append(process)
        ready = queue.Queue()
        def read_ready():
            for line in process.stdout:
                if line.startswith(b'{'):
                    ready.put(json.loads(line))
                    return
        reader = threading.Thread(target=read_ready, daemon=True)
        reader.start()
        value = ready.get(timeout=15)
        reader.join(timeout=1)
        self.assertTrue(value['ready'])
        return process

    def b_count(self, table):
        self.assertIn(table, ['tasks', 'journal_retired_tasks', 'journal_retention_runs'])
        with closing(sqlite3.connect(self.journal / 'mc-control.sqlite3')) as db:
            return db.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def preview(self):
        return self.coordinator.preview()

    def apply(self, plan):
        return self.coordinator.apply(plan['plan_file'], plan['plan_sha256'])

    def test_actual_maintenance_preserves_recovery_task_and_backs_up_committed_a_wal(self):
        with closing(sqlite3.connect(self.database)) as keeper:
            keeper.execute('PRAGMA journal_mode=WAL')
            keeper.execute('PRAGMA wal_autocheckpoint=0')
            keeper.execute('INSERT INTO audit(at,action,value) VALUES(?,?,?)', ('2026-10-31', 'committed-wal', '{}'))
            keeper.commit()
            before = self.coordinator.dependencies()
            plan = self.preview()
            self.assertEqual(plan['counts']['tasks'], 1)
            self.assertEqual(plan['counts']['events'], 1)
            result = self.apply(plan)
            self.assertEqual(result['outcome'], 'confirmed_in_current_b_ledger')
            self.assertTrue(result['apply_command_dispatched'])
            backup = self.coordinator.work / 'backups' / result['a_backup']['file']
            self.assertEqual(sha(backup), result['a_backup']['sha256'])
            with application_fence(backup) as db:
                self.assertEqual(capture(db), before)
                self.assertEqual(db.execute("SELECT count(*) FROM audit WHERE action='committed-wal'").fetchone()[0], 1)
        self.assertEqual(self.b_count('tasks'), 1)
        self.assertEqual(self.b_count('journal_retired_tasks'), 1)
        with closing(sqlite3.connect(self.journal / 'mc-control.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT task_id FROM tasks').fetchone()[0], 'task-protected')
        self.assertEqual(self.coordinator.dependencies(), before)

    def test_repeating_apply_queries_original_commit_without_new_backups(self):
        plan = self.preview()
        first, second = self.apply(plan), self.apply(plan)
        self.assertEqual(first['result'], second['result'])
        self.assertTrue(second['duplicate'])
        self.assertFalse(second['apply_command_dispatched'])
        self.assertEqual(self.b_count('journal_retention_runs'), 1)
        self.assertEqual(len(list((self.coordinator.work / 'backups').glob('*.sqlite3'))), 1)

    def test_any_a_logical_change_after_preview_refuses_dispatch(self):
        plan = self.preview()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("INSERT INTO meta VALUES('after-preview','true')")
        with self.assertRaises(MaintenanceError) as error:
            self.apply(plan)
        self.assertEqual(error.exception.code, 'MC_MAINTENANCE_A_CHANGED')
        self.assertEqual(error.exception.outcome, 'not_dispatched')
        self.assertEqual(self.b_count('tasks'), 2)
        self.assertFalse((self.coordinator.work / 'backups').exists())

    def test_b_snapshot_change_is_refused_and_uncertain_attempt_is_preserved(self):
        plan = self.preview()
        with closing(sqlite3.connect(self.journal / 'mc-control.sqlite3')) as db, db:
            db.execute('UPDATE reliable SET acked_at=acked_at+1')
        with self.assertRaises(MaintenanceError) as error:
            self.apply(plan)
        self.assertEqual(error.exception.code, 'GAME_RETENTION_PLAN_CHANGED')
        self.assertEqual(error.exception.outcome, 'unknown')
        self.assertEqual(self.b_count('tasks'), 2)
        self.assertEqual(self.b_count('journal_retention_runs'), 0)
        observation = self.coordinator.reconcile(plan['plan_file'], plan['plan_sha256'])
        self.assertEqual(observation['outcome'], 'not_found_in_current_b_ledger')
        self.assertFalse(observation['apply_command_dispatched'])

    def test_protection_file_mutation_is_not_accepted(self):
        plan = self.preview()
        path = self.coordinator.plans / plan['plan_file'].replace('.json', '.protection.json')
        path.write_text('{}', encoding='utf-8')
        with self.assertRaises(MaintenanceError) as error:
            self.apply(plan)
        self.assertEqual(error.exception.code, 'MC_MAINTENANCE_PROTECTION_CHANGED')
        self.assertEqual(self.b_count('tasks'), 2)

    def test_reviewed_file_hash_cannot_override_the_a_b_protection_relationship(self):
        plan = self.preview()
        a_path = self.coordinator.plans / plan['plan_file']
        a_plan = json.loads(a_path.read_text(encoding='utf-8'))
        b_path = self.journal / 'maintenance' / a_plan['b_preview']['plan_file']
        b_plan = json.loads(b_path.read_text(encoding='utf-8'))
        b_plan['protected_task_ids'] = []
        b_path.write_text(json.dumps(b_plan), encoding='utf-8')
        a_plan['b_preview']['plan_sha256'] = sha(b_path)
        a_path.write_text(json.dumps(a_plan), encoding='utf-8')
        with self.assertRaises(MaintenanceError) as error:
            self.coordinator.apply(plan['plan_file'], sha(a_path))
        self.assertEqual(error.exception.code, 'MC_MAINTENANCE_PROTECTION_CHANGED')
        self.assertEqual(self.b_count('tasks'), 2)

    def test_lost_apply_output_stays_unknown_until_readonly_reconciliation(self):
        plan = self.preview()
        original = self.runtime.invoke
        def lost(action, *args):
            result = original(action, *args)
            if action == 'apply':
                raise MaintenanceError('MC_MAINTENANCE_NATIVE_RESULT')
            return result
        with patch.object(self.runtime, 'invoke', side_effect=lost):
            with self.assertRaises(MaintenanceError) as error:
                self.apply(plan)
        self.assertEqual(error.exception.outcome, 'unknown')
        outcome_file = next(self.coordinator.attempts.glob('*.outcome.json'))
        self.assertEqual(json.loads(outcome_file.read_text())['outcome'], 'unknown')
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("INSERT INTO meta VALUES('later-a-change','true')")
        observation = self.coordinator.reconcile(plan['plan_file'], plan['plan_sha256'])
        self.assertEqual(observation['outcome'], 'confirmed_in_current_b_ledger')
        self.assertFalse(observation['apply_command_dispatched'])
        self.assertEqual(json.loads(outcome_file.read_text())['outcome'], 'unknown')
        self.assertEqual(len(list(self.coordinator.attempts.glob('*.observation.json'))), 1)
        self.assertEqual(self.b_count('journal_retention_runs'), 1)

    def test_outcome_record_partial_write_after_real_commit_remains_unknown(self):
        from mc_maintenance_core import exclusive_json
        plan = self.preview()
        partial = b'{"incomplete":'
        def full_disk(path, value):
            if path.name.endswith('.outcome.json'):
                with path.open('xb') as output:
                    output.write(partial)
                raise OSError('injected outcome storage failure after actual B commit')
            return exclusive_json(path, value)
        with patch('mc_maintenance_core.exclusive_json', side_effect=full_disk):
            with self.assertRaises(MaintenanceError) as error:
                self.apply(plan)
        self.assertEqual(error.exception.outcome, 'unknown')
        self.assertEqual(error.exception.code, 'MC_MAINTENANCE_OUTCOME_UNRECORDED')
        path = next(self.coordinator.attempts.glob('*.outcome.json'))
        self.assertEqual(path.read_bytes(), partial)
        self.assertEqual(self.b_count('journal_retention_runs'), 1)
        self.assertEqual(self.b_count('tasks'), 1)
        self.assertEqual(self.coordinator.reconcile(plan['plan_file'], plan['plan_sha256'])['outcome'],
                         'confirmed_in_current_b_ledger')
        self.assertEqual(path.read_bytes(), partial)

    def test_outcome_record_failure_after_lost_apply_output_keeps_uncertainty(self):
        from mc_maintenance_core import exclusive_json
        plan = self.preview()
        original = self.runtime.invoke
        def lost(action, *args):
            value = original(action, *args)
            if action == 'apply':
                raise MaintenanceError('MC_MAINTENANCE_NATIVE_RESULT')
            return value
        def full_disk(path, value):
            if path.name.endswith('.outcome.json'):
                raise OSError('injected failure while recording unknown outcome')
            return exclusive_json(path, value)
        with patch.object(self.runtime, 'invoke', side_effect=lost), \
             patch('mc_maintenance_core.exclusive_json', side_effect=full_disk):
            with self.assertRaises(MaintenanceError) as error:
                self.apply(plan)
        self.assertEqual(error.exception.outcome, 'unknown')
        self.assertEqual(error.exception.code, 'MC_MAINTENANCE_OUTCOME_UNRECORDED')
        self.assertEqual(self.b_count('journal_retention_runs'), 1)
        self.assertEqual(len(list(self.coordinator.attempts.glob('*.started.json'))), 1)
        self.assertEqual(len(list(self.coordinator.attempts.glob('*.outcome.json'))), 0)
        self.assertEqual(self.coordinator.reconcile(plan['plan_file'], plan['plan_sha256'])['outcome'],
                         'confirmed_in_current_b_ledger')

    def test_combined_backup_budget_refuses_before_b_apply(self):
        plan = self.preview()
        with patch('mc_maintenance_core.BACKUP_BYTES', 1):
            with self.assertRaises(MaintenanceError) as error:
                self.apply(plan)
        self.assertEqual(error.exception.code, 'MC_MAINTENANCE_BACKUP_BYTES')
        self.assertEqual(error.exception.outcome, 'not_dispatched')
        self.assertEqual(self.b_count('tasks'), 2)
        self.assertFalse((self.journal / 'backups').exists())

    def test_disk_reserve_refuses_before_b_apply(self):
        plan = self.preview()
        with patch('mc_maintenance_core.shutil.disk_usage', return_value=shutil._ntuple_diskusage(100, 100, 0)):
            with self.assertRaises(MaintenanceError) as error:
                self.apply(plan)
        self.assertEqual(error.exception.code, 'MC_MAINTENANCE_DISK_RESERVE')
        self.assertEqual(error.exception.outcome, 'not_dispatched')
        self.assertEqual(self.b_count('tasks'), 2)

    def test_same_volume_reserve_includes_both_new_backups(self):
        plan = self.preview()
        with closing(sqlite3.connect(self.database)) as db:
            a_bytes = db.execute('PRAGMA page_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0]
        b_bytes = sum(p.stat().st_size for p in [self.journal / 'mc-control.sqlite3', self.journal / 'mc-control.sqlite3-wal'] if p.exists())
        free = max(a_bytes, b_bytes) + 512 * 1024 ** 2
        with patch('mc_maintenance_core.shutil.disk_usage', return_value=shutil._ntuple_diskusage(free * 2, free, free)):
            with self.assertRaises(MaintenanceError) as error:
                self.apply(plan)
        self.assertEqual(error.exception.code, 'MC_MAINTENANCE_DISK_RESERVE')
        self.assertEqual(error.exception.outcome, 'not_dispatched')
        self.assertEqual(self.b_count('tasks'), 2)

    def test_expired_uncommitted_plan_does_not_retry_deletion(self):
        plan = self.preview()
        with patch('mc_maintenance_core.time.time', return_value=time.time() + 1000):
            with self.assertRaises(MaintenanceError) as error:
                self.apply(plan)
        self.assertEqual(error.exception.code, 'MC_MAINTENANCE_PLAN_EXPIRED')
        self.assertEqual(self.b_count('tasks'), 2)
        self.assertFalse((self.coordinator.work / 'backups').exists())

    def test_actual_running_a_process_blocks_preview_even_with_expired_lease(self):
        self.hold([self.node, 'tests/mc-maintenance-fixture.mjs', str(self.database), self.instance, 'hold'])
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('UPDATE game_owner SET lease_until=0')
        with self.assertRaises(MaintenanceError) as error:
            self.preview()
        self.assertEqual(error.exception.code, 'MC_MAINTENANCE_A_RUNNING')
        self.assertEqual(self.b_count('tasks'), 2)

    def test_actual_a_startup_cannot_acquire_ownership_during_the_fence(self):
        with application_fence(self.database):
            result = subprocess.run([self.node, 'tests/mc-maintenance-fixture.mjs', str(self.database), self.instance],
                                    cwd=ROOT, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.coordinator.dependencies()['task_ids'], ['task-protected'])

    def test_actual_b_owner_excludes_coordinator_preview(self):
        source = self.root / 'HoldMaintenance.java'
        source.write_text('import java.nio.file.*; import dev.aitalkstreamer.mc.core.LocalJournal; '
                          'class HoldMaintenance { public static void main(String[] a)throws Exception {'
                          'try(LocalJournal j=LocalJournal.openForMaintenance(Path.of(a[0]))) {'
                          'System.out.println("{\\"ready\\":true}"); System.out.flush(); System.in.read();}}}', encoding='utf-8')
        self.hold([self.java, '-Dorg.sqlite.tmpdir=' + str(self.seed_tmp), '-cp', self.classpath, str(source), str(self.journal)])
        with self.assertRaises(MaintenanceError) as error:
            self.preview()
        self.assertEqual(error.exception.code, 'GAME_LOCAL_STORE_BUSY')
        self.assertEqual(self.b_count('tasks'), 2)

    def test_runtime_configuration_change_invalidates_the_reviewed_plan(self):
        plan = self.preview()
        value = json.loads(self.configuration.read_text(encoding='utf-8'))
        value['java']['sha256'] = '0' * 64
        self.configuration.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaises(MaintenanceError) as error:
            self.apply(plan)
        self.assertEqual(error.exception.code, 'MC_MAINTENANCE_RUNTIME_CHANGED')
        self.assertEqual(self.b_count('tasks'), 2)

    def test_public_cli_uses_the_installed_profile_and_actual_native_workflow(self):
        installation = self.root / 'installation'
        installation.mkdir()
        names = ['.gitignore', 'configs/deployment-profiles/mc-native-3080-neoforge-v1.json',
                 'configs/deployment-targets.json', 'configs/deployment-target.json',
                 'configs/releases/current.json', 'configs/layouts/mc-landscape-v1.json',
                 'configs/releases/rtx3080-k02-runtime-lock.json', 'configs/mc-neoforge-client.lock.json', 'configs/mc-neoforge-bridge.lock.json',
                 'game-adapters/minecraft/fabric/gradle.properties',
                 'scripts/deployment_target.py', 'scripts/mc_deployment.py', 'scripts/mc_maintenance.py',
                 'scripts/mc_maintenance_core.py', 'scripts/mc_maintenance_dependencies.py']
        for name in names:
            destination = installation / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        # A separate real source checkout, no inference or preparation doubles.
        for arguments in [['init', '-b', 'mc'], ['add', '.'],
                          ['-c', 'user.name=Maintenance test', '-c', 'user.email=maintenance@example.invalid',
                           '-c', 'commit.gpgsign=false', 'commit', '-m', 'Owned temporary maintenance fixture']]:
            subprocess.run(['git', *arguments], cwd=installation, capture_output=True, check=True, timeout=15)
        database = installation / 'state/female-a-3080-k02/game/game.sqlite3'
        database.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.database)) as source, closing(sqlite3.connect(database)) as target:
            source.backup(target)
        private = installation / 'configs/mc-maintenance.private.json'
        private.write_text(json.dumps(self.runtime_config), encoding='utf-8')

        def invoke(action, plan=None):
            arguments = [sys.executable, '-X', 'utf8', '-B', 'scripts/mc_maintenance.py', action]
            if action != 'dependencies':
                arguments += ['--journal', str(self.journal)]
            if plan:
                arguments += ['--plan', plan['plan_file'], '--sha256', plan['plan_sha256']]
            result = subprocess.run(arguments, cwd=installation, capture_output=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout.decode('utf-8-sig') + result.stderr.decode('utf-8-sig'))
            value = json.loads(result.stdout)
            self.assertTrue(value['ok'])
            self.assertFalse(value['services_started'])
            self.assertFalse(value['models_loaded'])
            self.assertFalse(value['automatic_input_authorized'])
            return value

        self.assertEqual(invoke('dependencies')['task_ids'], ['task-protected'])
        self.assertEqual(invoke('status')['protected_tasks'], 1)
        plan = invoke('preview')
        sealed = json.loads((database.parent / 'maintenance/plans' / plan['plan_file']).read_text(encoding='utf-8'))
        self.assertEqual(sealed['binding']['application_database'], str(database.resolve()))
        self.assertEqual(sealed['binding']['installation']['root'], str(installation.resolve()))
        self.assertEqual(invoke('apply', plan)['outcome'], 'confirmed_in_current_b_ledger')
        self.assertEqual(invoke('reconcile', plan)['outcome'], 'confirmed_in_current_b_ledger')
        self.assertTrue(invoke('apply', plan)['duplicate'])
        self.assertEqual(self.b_count('tasks'), 1)
        self.assertFalse((installation / '.setup').exists())
        self.assertEqual(subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'],
                                                cwd=installation, text=True).strip(), '')


if __name__ == '__main__':
    unittest.main()
