"""Durable operator jobs and real HTTP; fixture application never starts models or MC."""
from pathlib import Path
from unittest.mock import patch
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from mc_application import ApplicationError, NativeServices
from mc_application_console import RuntimeService, ConsoleHost, PinnedServices, public_result, validate_request
from mc_maintenance_console import ConsoleServer, ConsoleService
from mc_maintenance_dependencies import MaintenanceError, digest
from mc_maintenance_jobs import JobLedger


def wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.01)
    raise AssertionError('Owned console operation did not settle')


class FixtureApplication:
    def __init__(self):
        self.calls = []
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()
        self.broadcast = False
        self.running = False

    def status(self):
        self.calls.append('status')
        checks = {key: {'ready': self.running if key in ('dsh', 'studio', 'speech', 'receiver') else False}
                  for key in ('dsh', 'studio', 'speech', 'receiver', 'minecraft', 'vision', 'official_playback', 'avatar_packs')}
        checks['official_playback']['code'] = 'MC_APPLICATION_OFFICIAL_CAPTURE_NOT_VERIFIED'
        checks['avatar_packs']['code'] = 'MC_APPLICATION_NEW_AVATAR_PACKS_NOT_ACCEPTED'
        return {'ok': False, 'services_ready': self.running, 'application_ready': False, 'checks': checks,
                'private_path': 'C:/private-fixture/config.env', 'api_key': 'fixture-secret-must-not-project', 'pid': 998877}

    def start(self, timeout=1800):
        self.calls.append('start'); self.entered.set()
        if not self.release.wait(timeout=10):
            raise RuntimeError('Fixture release not provided')
        self.running = True
        return {**self.status(), 'ok': True, 'code': 'MC_APPLICATION_SERVICES_STARTED_REQUIRED_INTEGRATION_PENDING',
                'operation_phase': 'COMPLETED', 'new_process_count': 4}

    def stop(self):
        self.calls.append('stop')
        if self.broadcast:
            return {'ok': False, 'code': 'MC_APPLICATION_STOP_REQUIRES_OFFAIR', 'operation_phase': 'NOT_STARTED'}
        self.running = False
        return {'ok': True}


class RuntimeTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mc-runtime-console-原生 ')
        self.root = Path(self.temp.name)
        self.application = FixtureApplication()
        self.services = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.application.release.set()
        for service in self.services:
            if service.ledger.db is not None:
                service.close()
        self.temp.cleanup()

    def service(self, **extra):
        value = RuntimeService(self.root, {'root': str(self.root), 'source': 'fixture'}, lambda: None,
                               application_factory=lambda root, check: self.application, **extra)
        self.services.append(value)
        return value

    def complete(self, service, job):
        def settled():
            row = service.ledger.get(job)
            return row if row['state'] not in ('accepted', 'running') else None
        return wait_for(settled)


class RuntimeServiceTests(RuntimeTestCase):

    def test_requests_allow_only_fixed_actions_and_bounded_start_timeout(self):
        for value in ({'action': 'shell', 'request_id': 'r'}, {'action': [], 'request_id': 'r'},
                      {'action': 'start', 'request_id': 'r', 'root': '../elsewhere'},
                      {'action': 'stop', 'request_id': 'r', 'timeout': 10},
                      {'action': 'start', 'request_id': 'r', 'timeout': True},
                      {'action': 'start', 'request_id': 'r', 'timeout': float('nan')},
                      {'action': 'start', 'request_id': 'r', 'timeout': 1801}):
            with self.subTest(value=value), self.assertRaises(MaintenanceError):
                validate_request(value)
        self.assertEqual(validate_request({'action': 'start', 'request_id': 'r', 'timeout': 1})['timeout'], 1)

    def test_public_result_excludes_secrets_paths_pids_and_unrecognized_checks(self):
        value = self.application.status(); value['checks']['injected'] = {'ready': True, 'path': 'private'}
        result = public_result(value); encoded = json.dumps(result)
        for secret in ('fixture-secret', 'C:/private', '998877', 'injected'):
            self.assertNotIn(secret, encoded)
        self.assertFalse(result['complete_application']); self.assertEqual(result['real_acceptance_passed'], 0)

    def test_live_job_state_and_preflight_match_closed_public_contracts(self):
        from jsonschema import Draft202012Validator, FormatChecker, ValidationError
        schema = json.loads((ROOT/'docs/technical/mc-live-v1/contracts/game.schema.json').read_text('utf-8'))
        def validator(name):
            return Draft202012Validator({'$schema': schema['$schema'], '$defs': schema['$defs'], '$ref': '#/$defs/'+name}, format_checker=FormatChecker())
        service = self.service(preflight=lambda: {'ok': False, 'checks': [{'name': 'device', 'ok': False, 'code': 'MC_DEVICE_UNAVAILABLE'}]})
        receipt = service.enqueue({'action': 'preflight', 'request_id': 'contract'})
        validator('ApplicationJobReceipt').validate(receipt)
        row = self.complete(service, receipt['job']['job_id'])
        validator('ApplicationReadiness').validate(json.loads(row['result']))
        validator('ApplicationConsoleState').validate({**service.state(), 'maintenance_configured': False})
        with self.assertRaises(ValidationError):
            validator('ApplicationReadiness').validate({**json.loads(row['result']), 'private_path': 'secret'})

    def test_duplicate_request_starts_once_and_survives_console_restart(self):
        self.application.release.clear(); service = self.service()
        request = {'action': 'start', 'request_id': 'same-start'}
        first = service.enqueue(request); wait_for(self.application.entered.is_set)
        duplicate = service.enqueue(request)
        self.assertTrue(duplicate['duplicate']); self.assertEqual(first['job']['job_id'], duplicate['job']['job_id'])
        self.application.release.set(); row = self.complete(service, first['job']['job_id'])
        self.assertEqual(row['state'], 'succeeded'); self.assertEqual(row['outcome'], 'committed')
        service.close(); other = self.service()
        self.assertTrue(other.enqueue(request)['duplicate']); self.assertEqual(self.application.calls.count('start'), 1)

    def test_conflicting_request_reuse_cannot_dispatch_another_action(self):
        service = self.service(); first = service.enqueue({'action': 'status', 'request_id': 'same'})
        self.complete(service, first['job']['job_id'])
        with self.assertRaisesRegex(MaintenanceError, 'REQUEST_CONFLICT'):
            service.enqueue({'action': 'stop', 'request_id': 'same'})
        self.assertNotIn('stop', self.application.calls)

    def test_query_not_ready_completes_without_claiming_application_ready(self):
        service = self.service(); job = service.enqueue({'action': 'status', 'request_id': 'check'})['job']
        row = self.complete(service, job['job_id']); result = json.loads(row['result'])
        self.assertEqual(row['state'], 'succeeded'); self.assertEqual(row['outcome'], 'not_applicable')
        self.assertFalse(result['application_ready']); self.assertFalse(result['ok'])

    def test_queued_stop_can_be_cancelled_without_stopping_running_service(self):
        self.application.release.clear(); service = self.service()
        running = service.enqueue({'action': 'start', 'request_id': 'start'})['job']; wait_for(self.application.entered.is_set)
        queued = service.enqueue({'action': 'stop', 'request_id': 'stop'})['job']
        service.ledger.cancel(queued['job_id']); self.application.release.set()
        self.complete(service, running['job_id']); self.assertNotIn('stop', self.application.calls)
        self.assertTrue(self.application.running)

    def test_closing_console_waits_for_current_job_and_keeps_application_running(self):
        self.application.release.clear(); service = self.service()
        job = service.enqueue({'action': 'start', 'request_id': 'start'})['job']; wait_for(self.application.entered.is_set)
        closing = threading.Thread(target=service.close); closing.start()
        wait_for(lambda: service.stopping); self.assertTrue(closing.is_alive())
        self.application.release.set(); closing.join(timeout=10)
        self.assertFalse(closing.is_alive()); self.assertTrue(self.application.running)
        self.assertNotIn('stop', self.application.calls)

    def test_stop_refusal_is_failed_and_does_not_mark_services_stopped(self):
        self.application.running = True; self.application.broadcast = True; service = self.service()
        job = service.enqueue({'action': 'stop', 'request_id': 'stop'})['job']
        row = self.complete(service, job['job_id']); result = json.loads(row['result'])
        self.assertEqual(row['state'], 'failed'); self.assertTrue(self.application.running)
        self.assertEqual(result['code'], 'MC_APPLICATION_STOP_REQUIRES_OFFAIR')

    def test_successful_stop_replaces_old_ready_badges_with_confirmed_stopped_facts(self):
        self.application.running = True; service = self.service()
        job = service.enqueue({'action': 'stop', 'request_id': 'stop'})['job']
        result = json.loads(self.complete(service, job['job_id'])['result'])
        self.assertFalse(result['services_ready'])
        self.assertEqual(set(result['checks']), {'dsh', 'studio', 'speech', 'receiver'})
        self.assertTrue(all(v['code'] == 'MC_APPLICATION_MANAGED_SERVICE_STOPPED' for v in result['checks'].values()))

    def test_interrupted_running_start_is_unknown_and_never_replayed(self):
        work = self.root / 'outputs/mc-application-console'; work.mkdir(parents=True)
        ledger = JobLedger(work, {'root': str(self.root), 'kind': 'mc_application_console_v1'},
                           request_validator=validate_request, uncertain_actions={'start', 'stop'})
        row, _ = ledger.enqueue({'action': 'start', 'request_id': 'old'}, 'a' * 64); ledger.take(); ledger.close()
        service = self.service(); previous = service.ledger.get(row['job_id'])
        self.assertEqual(previous['state'], 'interrupted'); self.assertEqual(previous['outcome'], 'unknown')
        self.assertEqual(self.application.calls, [])

    def test_failed_durable_completion_does_not_retry_committed_start(self):
        self.application.release.clear(); service = self.service()
        with patch.object(service.ledger, 'finish', side_effect=OSError('fixture storage failure')):
            job = service.enqueue({'action': 'start', 'request_id': 'start'})['job']; wait_for(self.application.entered.is_set)
            self.application.release.set(); wait_for(lambda: service.fault is not None)
        self.assertEqual(self.application.calls.count('start'), 1); self.assertTrue(self.application.running)
        self.assertEqual(service.ledger.get(job['job_id'])['state'], 'running')

    def test_start_waits_for_shared_maintenance_execution_lock(self):
        shared = threading.RLock(); service = self.service(execution_lock=shared)
        with shared:
            job = service.enqueue({'action': 'start', 'request_id': 'start'})['job']
            wait_for(lambda: service.ledger.get(job['job_id'])['state'] == 'running')
            self.assertFalse(self.application.entered.is_set())
        self.complete(service, job['job_id']); self.assertTrue(self.application.running)

    def test_pinned_start_rejects_source_change_before_old_start_guard(self):
        def changed():
            raise MaintenanceError('MC_MAINTENANCE_INSTALLATION_CHANGED')
        service = PinnedServices(self.root, changed)
        with patch.object(NativeServices, 'guard') as original:
            with self.assertRaisesRegex(ApplicationError, 'MC_MAINTENANCE_INSTALLATION_CHANGED'):
                service.guard()
            original.assert_not_called()

    def test_real_maintenance_worker_excludes_application_start_until_its_operation_finishes(self):
        from types import SimpleNamespace
        shared = threading.RLock(); entered, release = threading.Event(), threading.Event()
        work = self.root / 'maintenance'; work.mkdir()
        def dependencies():
            entered.set()
            if not release.wait(10):
                raise RuntimeError('Owned maintenance fixture was not released')
            return {}
        coordinator = SimpleNamespace(work=work, database=self.root/'a.db', journal=self.root/'journal', dependencies=dependencies)
        maintenance = ConsoleService(self.root, coordinator, lambda: None, 'a'*64, execution_lock=shared)
        self.addCleanup(maintenance.close); self.addCleanup(release.set)
        service = self.service(execution_lock=shared)
        old = maintenance.enqueue({'action': 'dependencies', 'request_id': 'maintenance'})['job']
        try:
            wait_for(entered.is_set)
            job = service.enqueue({'action': 'start', 'request_id': 'start'})['job']
            wait_for(lambda: service.ledger.get(job['job_id'])['state'] == 'running')
            self.assertFalse(self.application.entered.is_set())
        finally:
            release.set()
        self.complete(service, job['job_id'])
        wait_for(lambda: maintenance.ledger.get(old['job_id'])['state'] == 'succeeded')
        self.assertTrue(self.application.running)


class RuntimeHttpTests(RuntimeTestCase):
    # Keep HTTP cases separate from service cases so inherited methods are not counted twice.
    def setUp(self):
        super().setUp()
        for name in ('mc-runtime.html', 'mc-runtime.js', 'mc-runtime.css', 'mc-control.css', 'mc-maintenance.html'):
            target = self.root / 'web' / name; target.parent.mkdir(exist_ok=True); shutil.copyfile(ROOT / 'web' / name, target)
        self.runtime = self.service(); self.host = ConsoleHost(self.root, self.runtime)
        self.server = ConsoleServer(('127.0.0.1', 0), self.host)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}); self.thread.start()
        self.addCleanup(self.stop_http)

    def stop_http(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=10)
        self.assertFalse(self.thread.is_alive())

    def http(self, method, path, value=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            body = json.dumps(value).encode() if value is not None else None
            connection.request(method, path, body=body, headers={'Content-Type': 'application/json', **(headers or {})})
            response = connection.getresponse(); raw = response.read()
            content = response.getheader('Content-Type')
            return response.status, json.loads(raw) if content.startswith('application/json') else raw.decode(), dict(response.getheaders())
        finally:
            connection.close()

    def test_http_job_is_durable_and_queryable_by_original_request(self):
        status, result, _ = self.http('POST', '/api/mc-runtime/jobs', {'action': 'status', 'request_id': 'http'})
        self.assertEqual(status, 202); self.complete(self.runtime, result['job']['job_id'])
        status, result, _ = self.http('GET', '/api/mc-runtime/requests/http')
        self.assertEqual(status, 200); self.assertEqual(result['state'], 'succeeded')
        self.assertNotIn('fixture-secret', json.dumps(result)); self.assertFalse(result['result']['application_ready'])

    def test_cross_origin_and_rebound_host_reject_before_dispatch(self):
        request = {'action': 'start', 'request_id': 'cross'}
        self.assertEqual(self.http('POST', '/api/mc-runtime/jobs', request, {'Origin': 'https://foreign.example'})[0], 400)
        self.assertEqual(self.http('POST', '/api/mc-runtime/jobs', request, {'Host': 'rebound.example:' + str(self.server.server_port)})[0], 400)
        self.assertEqual(self.application.calls, [])

    def test_unknown_actions_extra_parameters_and_non_json_are_rejected(self):
        self.assertEqual(self.http('POST', '/api/mc-runtime/jobs', {'action': 'shell', 'request_id': 'r'})[0], 400)
        self.assertEqual(self.http('GET', '/api/mc-runtime/state?root=elsewhere')[0], 400)
        self.assertEqual(self.http('POST', '/api/mc-runtime/jobs', {}, {'Content-Type': 'text/plain'})[0], 415)

    def test_page_and_assets_are_independent_and_maintenance_configuration_is_explicit(self):
        for path in ('/', '/mc-runtime', '/mc-runtime.js', '/mc-runtime.css', '/mc-control.css'):
            status, body, headers = self.http('GET', path)
            self.assertEqual(status, 200); self.assertIn("default-src 'self'", headers['Content-Security-Policy'])
        state = self.http('GET', '/api/mc-runtime/state')[1]
        self.assertFalse(state['maintenance_configured']); self.assertFalse(state['full_application_lifecycle_complete'])
        self.assertEqual(self.http('GET', '/api/mc-maintenance/state')[0], 503)

    def test_reading_state_does_not_probe_or_start_application(self):
        for _ in range(3):
            self.assertEqual(self.http('GET', '/api/mc-runtime/state')[0], 200)
        self.assertEqual(self.application.calls, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
