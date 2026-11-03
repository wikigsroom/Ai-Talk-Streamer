from pathlib import Path
from contextlib import closing
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from mc_maintenance_dependencies import MaintenanceError, application_fence, capture, process_alive


class DependenciesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(os.environ.get('MC_MAINTENANCE_TEST_ROOT', ROOT / 'outputs/mc-test-temp'))
        cls.base.mkdir(parents=True, exist_ok=True)
        cls.template_dir = tempfile.TemporaryDirectory(prefix='maintenance-template-', dir=cls.base)
        cls.template = Path(cls.template_dir.name) / 'game.sqlite3'
        cls.node = os.environ.get('MC_TEST_NODE', str(ROOT.parent / 'tools/node/node-v24.22.1-win-x64/node.exe'))
        subprocess.run([cls.node, 'tests/mc-maintenance-fixture.mjs', str(cls.template)], cwd=ROOT, capture_output=True, check=True, timeout=10)

    @classmethod
    def tearDownClass(cls):
        cls.template_dir.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='maintenance-dependencies-', dir=self.base)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / 'game.sqlite3'
        shutil.copyfile(self.template, self.database)

    def sql(self, statement, *args):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute(statement, args)

    def put(self, kind, id, value):
        self.sql('INSERT INTO objects VALUES(?,?,?,?,?)', kind, id, value.get('world_session_id'), 1, json.dumps(value))

    def task(self, id, state='succeeded', effect='verified'):
        self.put('task', id, {'task_id': id, 'game_instance_id': 'mc-maintenance-fixture', 'state': state, 'effect_status': effect})

    def read(self):
        with application_fence(self.database) as db:
            return capture(db)

    def rejected(self, code):
        with self.assertRaises(MaintenanceError) as error:
            self.read()
        self.assertEqual(error.exception.code, code)

    def test_real_game_store_schema_and_stable_readonly_snapshot(self):
        before = self.database.read_bytes()
        first = self.read()
        self.assertEqual(first, self.read())
        self.assertEqual(first['a_schema_version'], 4)
        self.assertEqual(first['task_ids'], [])
        self.assertEqual(before, self.database.read_bytes())

    def test_active_unknown_and_partial_tasks_are_protected(self):
        for id, state, effect in [('active', 'running', 'unknown'), ('unknown', 'failed', 'unknown'),
                                  ('partial', 'succeeded', 'partial'), ('done', 'succeeded', 'verified')]:
            self.task(id, state, effect)
        self.assertEqual(self.read()['task_ids'], ['active', 'partial', 'unknown'])

    def test_unresolved_recovery_includes_ids_missing_from_task_projection(self):
        for id, status in [('missing-task', 'missing'), ('conflict-task', 'conflict'), ('waiting-task', 'waiting_terminal'), ('verified-task', 'verified')]:
            self.sql('INSERT INTO task_recovery VALUES(?,?,?)', id, status, json.dumps({'task_id': id, 'status': status}))
        self.assertEqual(self.read()['task_ids'], ['conflict-task', 'missing-task', 'waiting-task'])

    def test_unknown_disposition_remains_a_dependency(self):
        self.sql('INSERT INTO task_dispositions VALUES(?,?,?,?)', 'disposed', 1, 'closed_unknown', json.dumps({'task_id': 'disposed'}))
        self.assertEqual(self.read()['task_ids'], ['disposed'])

    def goal(self, id, status, tasks):
        # World table rows come from the actual schema, with its real FKs.
        self.sql('INSERT OR IGNORE INTO world_registry VALUES(?,?,?,?)', 'world', 'mc-maintenance-fixture', 1, '{}')
        self.sql('INSERT INTO world_goals VALUES(?,?,?,?,?)', id, 'world', 1, status,
                 json.dumps({'goal_id': id, 'status': status, 'steps': [{'task_ids': tasks}]}))
        for task in tasks:
            self.sql('INSERT INTO world_goal_tasks VALUES(?,?,?)', task, id, 'step')

    def test_live_goals_protect_even_previously_completed_step_tasks(self):
        self.goal('active-goal', 'blocked', ['earlier-step'])
        self.goal('finished-goal', 'completed', ['finished-step'])
        self.assertEqual(self.read()['task_ids'], ['earlier-step'])

    def test_orphan_goal_link_refuses_maintenance(self):
        self.sql('INSERT INTO world_goal_tasks VALUES(?,?,?)', 'orphan', 'missing-goal', 'step')
        self.rejected('MC_MAINTENANCE_A_DEPENDENCY_ORPHAN')

    def test_checkpoint_dependency_does_not_require_a_task_object(self):
        self.sql('INSERT INTO world_registry VALUES(?,?,?,?)', 'world', 'mc-maintenance-fixture', 1, '{}')
        self.sql('INSERT INTO world_checkpoints VALUES(?,?,?,?)', 'checkpoint', 'world', '2026-10-31', json.dumps({'proof': {'task_id': 'checkpoint-task'}}))
        self.assertEqual(self.read()['task_ids'], ['checkpoint-task'])

    def test_open_and_unknown_narration_protect_merged_task_sources(self):
        self.put('narration', 'open', {'state': 'pending', 'kind': 'task_result', 'source_id': 'first', 'source_ids': ['second']})
        self.put('narration', 'unknown', {'state': 'unknown', 'kind': 'task_result', 'source_id': 'third'})
        self.put('narration', 'closed', {'state': 'answered', 'kind': 'task_result', 'source_id': 'past'})
        self.assertEqual(self.read()['task_ids'], ['first', 'second', 'third'])

    def test_converted_suggestions_and_votes_keep_linked_evidence(self):
        self.put('suggestion', 'suggestion', {'state': 'converted', 'task_id': 'suggested-task'})
        self.put('vote', 'vote', {'state': 'closed', 'task_id': 'voted-task'})
        self.put('suggestion', 'rejected', {'state': 'rejected', 'task_id': 'rejected-task'})
        self.assertEqual(self.read()['task_ids'], ['suggested-task', 'voted-task'])

    def test_named_and_opaque_known_references_are_both_protected(self):
        self.task('known-task')
        self.sql('INSERT INTO meta VALUES(?,?)', 'recovery-input', json.dumps({'proof': ['known-task'], 'active_task_id': 'external-task'}))
        self.assertEqual(self.read()['task_ids'], ['external-task', 'known-task'])

    def test_readonly_imports_transitions_events_and_audit_do_not_pin_old_tasks(self):
        self.task('historical-task')
        value = json.dumps({'task_id': 'historical-task'})
        self.sql('INSERT INTO task_transitions VALUES(?,?,?)', 'historical-task', 1, value)
        self.sql('INSERT INTO game_events VALUES(?,?,?,?)', 'event', 'world', '2026-01-01', value)
        self.sql('INSERT INTO audit(at,action,value) VALUES(?,?,?)', '2026-01-01', 'old', value)
        self.sql('INSERT INTO bridge_history VALUES(?,?,?,?,?,?,?)', 'mc-maintenance-fixture', 'task_versions', 'key', 'world', '0' * 64, len(value), value)
        self.assertEqual(self.read()['task_ids'], [])

    def test_malformed_named_task_reference_refuses_instead_of_skipping(self):
        self.put('operation', 'bad', {'state': 'pending', 'task_id': 42})
        self.rejected('MC_MAINTENANCE_A_TASK_ID')

    def test_duplicate_json_keys_refuse_ambiguous_dependency(self):
        self.sql('INSERT INTO meta VALUES(?,?)', 'bad', '{"task_id":"first","task_id":"second"}')
        self.rejected('MC_MAINTENANCE_JSON_DUPLICATE')

    def test_unknown_object_kind_refuses_future_dependency_formats(self):
        self.put('future', 'future', {'task_id': 'unrecognized'})
        self.rejected('MC_MAINTENANCE_A_OBJECT_KIND')

    def test_excessive_nesting_refuses_export(self):
        value = {'task_id': 'nested'}
        for _ in range(34):
            value = {'nested': value}
        self.put('operation', 'deep', {'state': 'pending', 'params': value})
        self.rejected('MC_MAINTENANCE_A_NESTING')

    def test_dependency_limit_does_not_silently_truncate(self):
        self.sql('INSERT INTO meta VALUES(?,?)', 'large', json.dumps({'task_ids': ['task-' + str(n) for n in range(20001)]}))
        self.rejected('MC_MAINTENANCE_A_DEPENDENCY_LIMIT')

    def test_unfinished_history_import_requires_clean_shutdown(self):
        self.put('history_import', 'history', {'state': 'running'})
        self.rejected('MC_MAINTENANCE_A_HISTORY_UNFINISHED')

    def test_partial_history_payload_requires_clean_shutdown(self):
        self.sql('INSERT INTO history_partial VALUES(?,?)', 'history', '{}')
        self.rejected('MC_MAINTENANCE_A_HISTORY_UNFINISHED')

    def test_live_owner_is_rejected_even_with_expired_lease(self):
        self.assertTrue(process_alive(os.getpid()))
        self.sql('INSERT INTO game_owner VALUES(?,?,?,?)', 1, 'live', os.getpid(), 0)
        self.rejected('MC_MAINTENANCE_A_RUNNING')

    def test_dead_owner_with_unexpired_lease_is_safe_to_inspect(self):
        child = subprocess.Popen([sys.executable, '-c', 'pass'])
        child.wait(timeout=10)
        self.assertFalse(process_alive(child.pid))
        self.sql('INSERT INTO game_owner VALUES(?,?,?,?)', 1, 'old', child.pid, 2 ** 52)
        self.assertEqual(self.read()['task_ids'], [])

    def test_existing_writer_excludes_the_coordinator(self):
        with closing(sqlite3.connect(self.database, timeout=0)) as other, other:
            other.execute('BEGIN IMMEDIATE')
            self.rejected('MC_MAINTENANCE_A_BUSY')

    def test_fence_excludes_other_writers_and_releases_after_exit(self):
        with application_fence(self.database):
            with closing(sqlite3.connect(self.database, timeout=0)) as other, other:
                with self.assertRaises(sqlite3.OperationalError):
                    other.execute("INSERT INTO meta VALUES('other','true')")
        self.sql('INSERT INTO meta VALUES(?,?)', 'after-release', 'true')
        self.assertEqual(self.read()['task_ids'], [])

    def test_missing_database_is_not_created(self):
        missing = self.root / 'missing.sqlite3'
        with self.assertRaises(FileNotFoundError):
            with application_fence(missing):
                pass
        self.assertFalse(missing.exists())

    def test_future_database_version_is_not_migrated(self):
        self.sql('INSERT INTO schema_migrations VALUES(?,?)', 5, 'future')
        before = self.database.read_bytes()
        self.rejected('MC_MAINTENANCE_A_SCHEMA')
        self.assertEqual(before, self.database.read_bytes())

    def test_supported_legacy_schema_one_is_read_without_migration(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            for table in ['history_partial', 'bridge_history', 'world_goal_tasks', 'task_dispositions', 'world_goals',
                          'world_sessions', 'world_checkpoints', 'world_bases', 'world_registry', 'task_recovery']:
                db.execute('DROP TABLE ' + table)
            db.execute('DELETE FROM schema_migrations WHERE version>1')
        self.task('legacy', 'running', 'unknown')
        before = self.database.read_bytes()
        self.assertEqual(self.read()['a_schema_version'], 1)
        self.assertEqual(self.read()['task_ids'], ['legacy'])
        self.assertEqual(before, self.database.read_bytes())

    def test_unrecognized_table_refuses_unmodeled_dependencies(self):
        self.sql('CREATE TABLE future_dependencies(value TEXT)')
        self.rejected('MC_MAINTENANCE_A_SCHEMA')

    def test_row_scan_budget_refuses_before_partial_export(self):
        with patch('mc_maintenance_dependencies.MAX_ROWS', 1):
            self.rejected('MC_MAINTENANCE_A_SCAN_LIMIT')


if __name__ == '__main__':
    unittest.main()
