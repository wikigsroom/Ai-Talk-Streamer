from pathlib import Path
from contextlib import closing
import http.client
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from mc_maintenance_dependencies import MaintenanceError, digest
from mc_maintenance_jobs import JobLedger, validate_request
from mc_maintenance_console import ConsoleService, ConsoleServer, public_job, public_result
import test_mc_maintenance_native as native

SCHEMA=json.loads((ROOT/'docs/technical/mc-live-v1/contracts/game.schema.json').read_text(encoding='utf-8'))
def validate(definition,value):
    Draft202012Validator({'$schema':SCHEMA['$schema'],'$ref':'#/$defs/'+definition,'$defs':SCHEMA['$defs']},
                         format_checker=FormatChecker()).validate(value)

def wait_for(predicate, seconds=20):
    deadline = time.monotonic()+seconds
    while time.monotonic()<deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.025)
    raise AssertionError('Condition did not become true within original deadline')


class LedgerTest(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('MC_MAINTENANCE_TEST_ROOT',ROOT/'outputs/mc-test-temp'))
        base.mkdir(parents=True,exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='maintenance-ledger-',dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = {'installation':str(self.root)}
        self.store = JobLedger(self.root,self.identity)
        self.addCleanup(lambda: self.store.close() if self.store.db is not None else None)

    def add(self, index, action='preview'):
        value = {'request_id':'req-'+str(index),'action':action}
        if action in {'apply','reconcile'}:
            value.update(plan_file='maintenance-'+'a'*36+'.json',plan_sha256='a'*64)
        return self.store.enqueue(value,'b'*64)[0]

    def test_idempotent_request_and_conflicting_reuse(self):
        row = self.add(1)
        duplicate, reused = self.store.enqueue({'request_id':'req-1','action':'preview'},'c'*64)
        self.assertTrue(reused)
        self.assertEqual(row['job_id'],duplicate['job_id'])
        with self.assertRaisesRegex(MaintenanceError,'REQUEST_CONFLICT'):
            self.store.enqueue({'request_id':'req-1','action':'status'},'b'*64)
        self.assertEqual(self.store.capacity()['jobs'],1)

    def test_queued_cancel_idempotent_and_running_cancel_refused(self):
        queued, running = self.add(1), self.add(2,'apply')
        self.assertEqual(self.store.cancel(queued['job_id'])['state'],'cancelled')
        self.assertEqual(self.store.cancel(queued['job_id'])['state'],'cancelled')
        self.assertEqual(self.store.take()['job_id'],running['job_id'])
        with self.assertRaisesRegex(MaintenanceError,'CANCEL_BLOCKED'):
            self.store.cancel(running['job_id'])

    def test_restart_never_replays_accepted_or_running_apply(self):
        apply = self.add(1,'apply'); self.store.take(); queued = self.add(2)
        self.store.close(); self.store = JobLedger(self.root,self.identity)
        self.assertEqual(self.store.get(apply['job_id'])['outcome'],'unknown')
        self.assertEqual(self.store.get(queued['job_id'])['outcome'],'not_dispatched')
        self.assertEqual(self.store.get(apply['job_id'])['state'],'interrupted')
        self.assertIsNone(self.store.take())
        self.assertEqual(self.add(1,'apply')['job_id'],apply['job_id'])

    def test_different_installation_rejected_without_rewrite(self):
        row = self.add(1); self.store.close()
        with self.assertRaisesRegex(MaintenanceError,'CONSOLE_BINDING'):
            JobLedger(self.root,{'installation':'different'})
        self.store = JobLedger(self.root,self.identity)
        self.assertEqual(self.store.get(row['job_id'])['state'],'interrupted')

    def test_os_owner_lock_rejects_second_console_and_releases(self):
        with self.assertRaisesRegex(MaintenanceError,'CONSOLE_BUSY'):
            JobLedger(self.root,self.identity)
        self.store.close(); self.store = JobLedger(self.root,self.identity)
        self.assertIsNotNone(self.store.db)

    def test_queue_limit_does_not_prevent_duplicate_lookup(self):
        for i in range(16): self.add(i)
        with self.assertRaisesRegex(MaintenanceError,'QUEUE_FULL'): self.add(17)
        self.assertEqual(self.add(0)['request_id'],'req-0')
        self.assertEqual(self.store.capacity()['pending'],16)

    def test_stable_page_keeps_original_high_water(self):
        with patch('mc_maintenance_jobs.MAX_PENDING',64):
            for i in range(25): self.add(i)
        page = self.store.page()
        self.assertEqual(len(page['items']),20)
        self.store.cancel(page['items'][0]['job_id'])
        with patch('mc_maintenance_jobs.MAX_PENDING',64): self.add(99)
        rest = self.store.page(page['next_before'],page['through'])
        self.assertEqual(len(rest['items']),5)
        self.assertFalse(any(row['request_id']=='req-99' for row in rest['items']))

    def test_record_size_failure_leaves_running_unknown(self):
        job = self.add(1,'apply'); self.store.take()
        with self.assertRaisesRegex(MaintenanceError,'RESULT_LIMIT'):
            self.store.finish(job['job_id'],'succeeded','confirmed_in_current_b_ledger',result={'large':'x'*17000})
        self.assertEqual(self.store.get(job['job_id'])['state'],'running')
        self.assertEqual(self.store.get(job['job_id'])['outcome'],'unknown')

    def test_record_count_limit_refuses_without_deleting(self):
        self.add(1)
        with patch('mc_maintenance_jobs.MAX_JOBS',1):
            with self.assertRaisesRegex(MaintenanceError,'CONSOLE_CAPACITY'): self.add(2)
        self.assertEqual(self.store.capacity()['jobs'],1)

    def test_unknown_schema_objects_rejected(self):
        self.store.close()
        with closing(sqlite3.connect(self.root/'console/jobs.sqlite3')) as db, db:
            db.execute('CREATE TABLE unexpected(value TEXT)')
        with self.assertRaisesRegex(MaintenanceError,'CONSOLE_SCHEMA'): JobLedger(self.root,self.identity)

    def test_request_whitelist_and_plan_not_a_path(self):
        for value in [{'request_id':'r','action':'shell'},{'request_id':'r','action':'preview','root':'C:/private'},
                      {'request_id':'r','action':'apply','plan_file':'../file','plan_sha256':'a'*64},
                      {'request_id':True,'action':'status'},{'request_id':'r','action':'reconcile'}]:
            with self.assertRaises(MaintenanceError): validate_request(value)

    def test_source_probe_does_not_consume_operator_input(self):
        code=('import sys; sys.path.insert(0,'+repr(str(ROOT/'scripts'))+'); import mc_deployment as m; '
              "value=m.output([sys.executable,'-c','import sys; print(len(sys.stdin.buffer.read()))'],cwd="+repr(str(ROOT))+
              ",timeout=3); print(value.decode().strip()); print(sys.stdin.buffer.readline().decode().strip())")
        result=subprocess.run([sys.executable,'-X','utf8','-B','-c',code],input=b'operator-owned-input\n',capture_output=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertEqual(result.stdout.decode().splitlines(),['0','operator-owned-input'])


class ControlledCoordinator:
    def __init__(self, root):
        self.work = root/'maintenance'; self.work.mkdir()
        self.plans = self.work/'plans'; self.plans.mkdir()
        self.database = root/'a.sqlite3'; self.database.touch()
        self.journal = root/'journal'; self.journal.mkdir()
        self.calls = []; self.release = threading.Event(); self.release.set()
        self.active = 0; self.peak = 0
    def dependencies(self):
        self.calls.append('dependencies'); self.active += 1; self.peak=max(self.active,self.peak)
        self.release.wait(timeout=10); self.active -= 1
        return {'game_instance_id':'fixture','task_ids':['private-task'],'protection_counts':{'recovery':1},'snapshot_sha256':'a'*64,'scanned_rows':1,'scanned_bytes':100}
    status = dependencies
    preview = dependencies
    def apply(self,*_):
        self.dependencies(); return {'outcome':'confirmed_in_current_b_ledger','duplicate':False,'apply_command_dispatched':True}
    def reconcile(self,*_):
        self.calls.append('reconcile'); return {'outcome':'not_found_in_current_b_ledger','apply_command_dispatched':False}


class ConsoleHttpTest(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('MC_MAINTENANCE_TEST_ROOT',ROOT/'outputs/mc-test-temp')); base.mkdir(parents=True,exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='maintenance-http-',dir=base); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'web').mkdir()
        for name in ['mc-maintenance.html','mc-maintenance.js','mc-maintenance.css','mc-control.css']:
            (self.root/'web'/name).write_bytes((ROOT/'web'/name).read_bytes())
        self.coordinator = ControlledCoordinator(self.root)
        self.service = ConsoleService(self.root,self.coordinator,lambda:None,'b'*64)
        self.server = ConsoleServer(('127.0.0.1',0),self.service)
        self.thread = threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.05}); self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.coordinator.release.set(); self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)
        if self.service.ledger.db is not None: self.service.close()
        self.assertFalse(self.thread.is_alive()); self.assertFalse(self.service.worker.is_alive())

    def http(self, method, path, body=None, headers=None):
        raw = json.dumps(body).encode() if isinstance(body,dict) else body
        connection = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            connection.request(method,path,body=raw,headers=headers or ({'Content-Type':'application/json'} if raw is not None else {}))
            response = connection.getresponse(); data=response.read()
            value=json.loads(data) if response.getheader('Content-Type','').startswith('application/json') else data
            if isinstance(value,dict):
                definition='MaintenanceError' if response.status>=400 else 'MaintenanceJobReceipt' if method=='POST' and path.endswith('/jobs') else 'MaintenanceJobPage' if path.split('?')[0].endswith('/jobs') else 'MaintenanceState' if path.endswith('/state') else 'MaintenanceStopReceipt' if path.endswith('/stop') else 'MaintenanceJob'
                validate(definition,value)
            return response.status,value,dict(response.getheaders())
        finally: connection.close()

    def submit(self,index,action='dependencies'):
        value={'request_id':'http-'+str(index),'action':action}
        if action in {'apply','reconcile'}: value.update(plan_file='maintenance-'+'a'*36+'.json',plan_sha256='a'*64)
        return self.http('POST','/api/mc-maintenance/jobs',value)

    def complete(self, job):
        return wait_for(lambda: (row if (row:=self.service.ledger.get(job))['state'] not in {'accepted','running'} else None))

    def test_real_http_open_access_persisted_request_lookup_and_redaction(self):
        status,result,_ = self.submit(1)
        self.assertEqual(status,202); job=result['job']['job_id']; self.complete(job)
        status,value,headers=self.http('GET','/api/mc-maintenance/requests/http-1')
        self.assertEqual(status,200); self.assertEqual(value['job_id'],job)
        self.assertEqual(value['result']['protected_tasks'],1)
        self.assertNotIn('private-task',json.dumps(value)); self.assertNotIn(str(self.root),json.dumps(value))
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(self.submit(1)[0],200)
        self.assertEqual(self.coordinator.calls,['dependencies'])

    def test_http_rejects_duplicate_keys_oversize_commands_and_unknown_routes(self):
        for raw,status in [(b'{"action":"status","action":"preview","request_id":"r"}',400),
                           (b'x'*4097,413),(b'{"action":"status","request_id":"r","command":"whoami"}',400),
                           (b'{"action":"status","request_id":NaN}',400)]:
            self.assertEqual(self.http('POST','/api/mc-maintenance/jobs',raw,{'Content-Type':'application/json'})[0],status)
        self.assertEqual(self.http('POST','/api/mc-maintenance/jobs',b'{}',{'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.http('GET','/../configs/mc-maintenance.private.json')[0],404)
        self.assertEqual(self.http('GET','/api/mc-maintenance/jobs?before=1&before=2')[0],400)
        self.assertEqual(self.http('GET','/api/mc-maintenance/requests/missing')[0],404)
        self.assertEqual(self.coordinator.calls,[])

    def test_serial_execution_and_queue_cancel_are_actual_http_operations(self):
        self.coordinator.release.clear()
        first=self.submit(1)[1]['job']['job_id']; wait_for(lambda:len(self.coordinator.calls)==1)
        second=self.submit(2)[1]['job']['job_id']; third=self.submit(3)[1]['job']['job_id']
        self.assertEqual(self.http('POST',f'/api/mc-maintenance/jobs/{first}/cancel',{})[0],409)
        self.assertEqual(self.http('POST',f'/api/mc-maintenance/jobs/{second}/cancel',{})[1]['state'],'cancelled')
        self.coordinator.release.set(); self.complete(first); self.complete(third)
        self.assertEqual(self.coordinator.peak,1); self.assertEqual(len(self.coordinator.calls),2)

    def test_installation_change_blocks_dispatch(self):
        def changed(): raise MaintenanceError('MC_MAINTENANCE_INSTALLATION_CHANGED')
        self.service.verify_installation=changed
        job=self.submit(1,'apply')[1]['job']['job_id']; row=self.complete(job)
        self.assertEqual(row['outcome'],'not_dispatched'); self.assertEqual(row['code'],'MC_MAINTENANCE_INSTALLATION_CHANGED')
        self.assertEqual(self.coordinator.calls,[])

    def test_lost_http_response_is_queried_without_second_apply(self):
        result=self.submit(1,'apply')[1]; job=result['job']['job_id']; self.complete(job)
        found=self.http('GET','/api/mc-maintenance/requests/http-1')[1]
        self.assertEqual(found['outcome'],'confirmed_in_current_b_ledger')
        self.assertEqual(self.submit(1,'apply')[1]['job']['job_id'],job)
        self.assertEqual(len(self.coordinator.calls),1)

    def test_result_record_failure_remains_unknown_after_restart(self):
        original=self.service.ledger.finish
        def failed(*_,**__): raise sqlite3.OperationalError('injected result write failure')
        self.service.ledger.finish=failed
        job=self.submit(1,'apply')[1]['job']['job_id']; wait_for(lambda:self.service.fault)
        self.service.ledger.finish=original
        self.service.close()
        reopened=JobLedger(self.coordinator.work,{'root':str(self.root),'database':str(self.coordinator.database),'journal':str(self.coordinator.journal)})
        try:
            self.assertEqual(reopened.get(job)['state'],'interrupted'); self.assertEqual(reopened.get(job)['outcome'],'unknown')
            self.assertIsNone(reopened.take())
        finally: reopened.close()

    def test_static_allowlist_no_private_files_or_external_assets(self):
        for path in ['/mc-maintenance','/mc-maintenance.js','/mc-maintenance.css','/mc-control.css']:
            status,raw,headers=self.http('GET',path)
            self.assertEqual(status,200); self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertEqual(self.http('GET','/web/mc-control.html')[0],404)

    def test_graceful_stop_finishes_current_and_preserves_queued_interruption(self):
        self.coordinator.release.clear()
        first=self.submit(1)[1]['job']['job_id']; wait_for(lambda:len(self.coordinator.calls)==1)
        queued=self.submit(2)[1]['job']['job_id']
        self.assertEqual(self.http('POST','/api/mc-maintenance/stop',{})[0],202)
        self.coordinator.release.set(); self.thread.join(timeout=5)
        self.service.close()
        ledger=JobLedger(self.coordinator.work,{'root':str(self.root),'database':str(self.coordinator.database),'journal':str(self.coordinator.journal)})
        try:
            self.assertEqual(ledger.get(first)['state'],'succeeded')
            self.assertEqual(ledger.get(queued)['state'],'interrupted')
            self.assertEqual(ledger.get(queued)['outcome'],'not_dispatched')
            self.assertEqual(len(self.coordinator.calls),1)
        finally: ledger.close()

    def test_public_projection_omits_sensitive_native_fields(self):
        raw={'task_ids':['secret-task'],'protection_counts':{'recovery':1},'a_backup':{'file':'a-safe.sqlite3','sha256':'a'*64,
             'bytes':100,'scope':'A_GAME_DATABASE_ONLY_NOT_MC_WORLD_OR_HUMANITY_BACKUP','application_database':'C:/secret/a.sqlite3'},
             'binding':{'channel_key':'secret-key'},'application_database':'C:/secret/a.sqlite3','private':'secret'}
        result=public_result(raw)
        self.assertEqual(result['protected_tasks'],1)
        self.assertNotIn('secret',json.dumps(result))

    def test_unreadable_plan_preserved_and_counts_cannot_expose_arbitrary_fields(self):
        path=self.coordinator.plans/('maintenance-'+'a'*36+'.json')
        value={'format_version':1,'plan_id':'maintenance-'+'a'*36,'created_at':'2026-10-31T00:00:00Z',
               'binding':{},'a_dependencies':{'game_instance_id':'fixture','snapshot_sha256':'b'*64,'task_ids':[],
               'protection_counts':{}},'b_preview':{'expires_at_ms':1793405400000,'counts':{'private_path':'C:/secret'}}}
        path.write_text(json.dumps(value),encoding='utf-8'); original=path.read_bytes()
        page=self.service.plans(); validate('MaintenancePlanPage',page)
        self.assertEqual(page['items'],[]); self.assertEqual(len(page['issues']),1)
        self.assertEqual(path.read_bytes(),original); self.assertNotIn('secret',json.dumps(page))


class NativeConsoleHttpTest(unittest.TestCase):
    def setUp(self):
        native.NativeCoordinatorTest.setUpClass()
        self.fixture=native.NativeCoordinatorTest(methodName='runTest'); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.service=ConsoleService(self.fixture.root,self.fixture.coordinator,lambda:None,digest(self.fixture.coordinator.binding()))
        self.server=ConsoleServer(('127.0.0.1',0),self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.05}); self.thread.start()
        self.addCleanup(self.stop)

    def tearDown(self):
        result=self._outcome.result
        if any(test is self for test,_ in [*result.failures,*result.errors]):
            destination=self.fixture.base.parent.parent/('failed-console-fixture-'+self._testMethodName)
            if not destination.exists(): shutil.copytree(self.fixture.root,destination)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5); self.service.close()
        self.assertFalse(self.thread.is_alive()); self.assertFalse(self.service.worker.is_alive())

    def request(self,value):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            connection.request('POST','/api/mc-maintenance/jobs',body=json.dumps(value).encode(),headers={'Content-Type':'application/json'})
            response=connection.getresponse(); result=json.loads(response.read()); self.assertIn(response.status,[200,202])
            validate('MaintenanceJobReceipt',result)
            job=result['job']['job_id']
        finally: connection.close()
        row=wait_for(lambda: row if (row:=self.service.ledger.get(job))['state'] not in {'running','accepted'} else None,40)
        validate('MaintenanceJob',public_job(row))
        return row

    def plan(self,index=1):
        row=self.request({'request_id':'preview-'+str(index),'action':'preview'})
        self.assertEqual(row['state'],'succeeded',row); result=json.loads(row['result'])
        return {'plan_file':result['plan_file'],'plan_sha256':result['plan_sha256']}

    def test_http_actual_a_b_preview_commit_duplicate_and_readback(self):
        plan=self.plan()
        reviewed=self.service.plans()['items'][0]
        validate('MaintenancePlanPage',self.service.plans())
        self.assertTrue(reviewed['binding_matches']); self.assertEqual(reviewed['protected_tasks'],1)
        self.assertEqual(reviewed['counts']['tasks'],1)
        first=self.request({'request_id':'apply-1','action':'apply',**plan})
        self.assertEqual(first['outcome'],'confirmed_in_current_b_ledger',first)
        self.assertEqual(self.fixture.b_count('tasks'),1)
        repeat=self.request({'request_id':'apply-2','action':'apply',**plan})
        self.assertTrue(json.loads(repeat['result'])['duplicate'])
        proof=self.request({'request_id':'proof-1','action':'reconcile',**plan})
        self.assertEqual(proof['outcome'],'confirmed_in_current_b_ledger')
        self.assertEqual(self.fixture.b_count('journal_retention_runs'),1)
        self.assertEqual(len(list((self.fixture.coordinator.work/'backups').glob('*.sqlite3'))),1)

    def test_http_actual_a_owner_blocks_even_expired_lease(self):
        owner=self.fixture.hold([self.fixture.node,'tests/mc-maintenance-fixture.mjs',str(self.fixture.database),self.fixture.instance,'hold'])
        with closing(sqlite3.connect(self.fixture.database)) as db,db:
            db.execute('UPDATE game_owner SET lease_until=0')
        row=self.request({'request_id':'blocked-preview','action':'preview'})
        self.assertEqual(row['state'],'failed'); self.assertEqual(row['outcome'],'not_dispatched')
        self.assertIn(row['code'],['MC_MAINTENANCE_A_RUNNING','MC_MAINTENANCE_A_BUSY','MC_MAINTENANCE_A_OWNED'])
        self.assertIsNone(owner.poll()); self.assertEqual(self.fixture.b_count('tasks'),2)

    def test_http_actual_a_change_invalidates_reviewed_plan(self):
        plan=self.plan()
        with closing(sqlite3.connect(self.fixture.database)) as db,db:
            db.execute("INSERT INTO meta VALUES('console-change','1')")
        row=self.request({'request_id':'changed-apply','action':'apply',**plan})
        self.assertEqual(row['code'],'MC_MAINTENANCE_A_CHANGED'); self.assertEqual(row['outcome'],'not_dispatched')
        self.assertEqual(self.fixture.b_count('journal_retention_runs'),0)

    def test_http_actual_commit_output_lost_keeps_unknown_and_reconciles(self):
        plan=self.plan(); invoke=self.fixture.runtime.invoke
        def lost(action,*args):
            result=invoke(action,*args)
            if action=='apply': raise MaintenanceError('MC_MAINTENANCE_NATIVE_RESULT')
            return result
        with patch.object(self.fixture.runtime,'invoke',side_effect=lost):
            row=self.request({'request_id':'lost-apply','action':'apply',**plan})
        self.assertEqual(row['outcome'],'unknown'); self.assertEqual(self.fixture.b_count('journal_retention_runs'),1)
        proof=self.request({'request_id':'lost-proof','action':'reconcile',**plan})
        self.assertEqual(proof['outcome'],'confirmed_in_current_b_ledger')
        self.assertEqual(self.service.ledger.get(row['job_id'])['outcome'],'unknown')

