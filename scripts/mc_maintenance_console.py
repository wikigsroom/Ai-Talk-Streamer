"""Independent native HTTP console; fixed maintenance operations, no application auth."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from datetime import datetime
import hashlib
import json
import re
import sqlite3
import threading

from mc_maintenance_dependencies import MaintenanceError, canonical, digest, parse, require, safe_path
from mc_maintenance_core import PLAN, SHA, file_sha, read_json
from mc_maintenance_jobs import JobLedger, REQUEST, validate_request

PREFIX = '/api/mc-maintenance'
JOB = re.compile(r'job-[0-9a-f-]{36}\Z')
COUNT_KEYS = {'events','tasks','task_deliveries','task_versions','summary_groups'}


def counts(value, keys=None):
    require(isinstance(value,dict) and len(value)<=64 and (keys is None or set(value)==keys)
            and all(isinstance(key,str) and re.fullmatch(r'[a-z_]{1,64}',key) and type(item) is int
                    and 0<=item<=9007199254740991 for key,item in value.items()), 'MC_MAINTENANCE_NATIVE_RESULT')
    return value


def configuration(root):
    value = read_json(root / 'configs/mc-maintenance-console.json', 4096)
    require(isinstance(value, dict) and set(value) == {'schema_version','host','port'}
            and type(value['schema_version']) is int and value['schema_version'] == 1
            and value['host'] in {'127.0.0.1','0.0.0.0'} and type(value['port']) is int
            and 1024 <= value['port'] <= 65535, 'MC_MAINTENANCE_CONSOLE_CONFIG')
    return value


def public_result(value):
    """Project bounded counters and receipts; never return raw DB/native/config paths or task bodies."""
    result = {}
    for key in ['game_instance_id','snapshot_sha256','a_snapshot_sha256','plan_file','plan_sha256','expires_at_ms',
                'applied','outcome','duplicate','apply_command_dispatched','protected_tasks','scanned_rows','scanned_bytes']:
        if key in value:
            result[key] = value[key]
    if 'task_ids' in value:
        result['protected_tasks'] = len(value['task_ids'])
    if 'protection_counts' in value:
        result['protection_counts'] = counts(value['protection_counts'])
    if 'counts' in value:
        result['counts'] = counts(value['counts'],COUNT_KEYS)
    native = value.get('b_status')
    if isinstance(native, dict):
        result['journal'] = {key:native[key] for key in ['schema_version','tasks','reliable','task_versions','retired_tasks','summary_groups','runs']}
    committed = value.get('result') or value.get('b_observation',{}).get('result')
    if isinstance(committed, dict):
        result['committed'] = {key:committed[key] for key in ['run_id','generation','counts','completed_at','originals_in_backup','disk_bytes_reclaimed']}
    backup = value.get('a_backup')
    if isinstance(backup, dict):
        result['a_backup'] = {key:backup[key] for key in ['file','sha256','bytes','scope']}
    return result


def public_job(row):
    result = {key:row[key] for key in ['seq','job_id','request_id','action','state','outcome','code','created_at','started_at','finished_at']}
    request = parse(row['request'])
    result['plan_file'] = request.get('plan_file')
    result['plan_sha256'] = request.get('plan_sha256')
    result['result'] = parse(row['result']) if row['result'] is not None else None
    return result


class ConsoleService:
    def __init__(self, root, coordinator, verify_installation, binding_sha256, *, execution_lock=None):
        self.root, self.coordinator = safe_path(root, directory=True), coordinator
        self.verify_installation, self.binding_sha256 = verify_installation, binding_sha256
        self.execution_lock = execution_lock if execution_lock is not None else threading.RLock()
        self.ledger = JobLedger(coordinator.work, {'root':str(self.root), 'database':str(coordinator.database),
                                               'journal':str(coordinator.journal)})
        self.condition = threading.Condition()
        self.stopping, self.fault = False, None
        self.worker = threading.Thread(target=self._work, name='mc-maintenance-worker', daemon=False)
        self.worker.start()

    def enqueue(self, value):
        with self.condition:
            require(not self.stopping and self.fault is None, 'MC_MAINTENANCE_CONSOLE_STOPPING')
            row, duplicate = self.ledger.enqueue(value, self.binding_sha256)
            self.condition.notify_all()
            return {'job':public_job(row),'duplicate':duplicate}

    def _work(self):
        while True:
            try:
                with self.condition:
                    if self.stopping:
                        return
                    row = self.ledger.take()
                    if row is None:
                        self.condition.wait(timeout=1)
                        continue
                value, state, code = None, 'failed', None
                outcome = 'not_dispatched'
                try:
                    require(row['binding_sha256'] == self.binding_sha256, 'MC_MAINTENANCE_CONSOLE_BINDING')
                    raw = self.execute(row)
                    # A projection/recording failure after apply remains uncertain.
                    outcome = raw.get('outcome','not_applicable')
                    value = public_result(raw)
                    state = 'succeeded'
                except Exception as error:
                    code = error.code if isinstance(error,MaintenanceError) else 'MC_MAINTENANCE_CONSOLE_JOB_FAILED'
                    outcome = getattr(error,'outcome', 'unknown' if row['action']=='apply' else 'not_applicable')
                self.ledger.finish(row['job_id'],state,outcome,code,value)
            except Exception:
                # Do not overwrite or rerun a job if durable completion itself failed.
                # The running record is interrupted/unknown on the next start.
                self.fault = 'MC_MAINTENANCE_CONSOLE_STORAGE_FAILED'
                return

    def execute(self, row):
        with self.execution_lock:
            self.verify_installation()
            request = validate_request(parse(row['request']))
            if row['action'] in {'apply','reconcile'}:
                return getattr(self.coordinator,row['action'])(request['plan_file'],request['plan_sha256'])
            return getattr(self.coordinator,row['action'])()

    def state(self):
        return {'schema_version':1, 'binding_sha256':self.binding_sha256, 'capacity':self.ledger.capacity(),
                'stopping':self.stopping, 'fault':self.fault, 'services_started':False,'models_loaded':False,
                'automatic_input_authorized':False, 'unified_lifecycle_available':False}

    def plans(self):
        files = sorted(self.coordinator.plans.glob('maintenance-*.json'))
        require(len(files) <= 32, 'MC_MAINTENANCE_PLAN_LIMIT')
        items, issues = [], []
        for path in files:
            if not PLAN.fullmatch(path.name):
                continue
            try:
                path = safe_path(path)
                require(path.stat().st_size<=4*1024*1024,'MC_MAINTENANCE_FILE_LIMIT')
                with path.open('rb') as stream:
                    raw = stream.read(4*1024*1024+1)
                require(len(raw)<=4*1024*1024,'MC_MAINTENANCE_FILE_LIMIT')
                plan = parse(raw)
                require(plan['plan_id']+'.json' == path.name and plan['format_version'] == 1,
                        'MC_MAINTENANCE_PLAN_BINDING')
                dep, preview = plan['a_dependencies'], plan['b_preview']
                require(isinstance(dep['game_instance_id'],str) and REQUEST.fullmatch(dep['game_instance_id'])
                        and isinstance(dep['snapshot_sha256'],str) and SHA.fullmatch(dep['snapshot_sha256'])
                        and isinstance(dep['task_ids'],list) and len(dep['task_ids'])<=20000
                        and all(isinstance(item,str) and REQUEST.fullmatch(item) for item in dep['task_ids'])
                        and type(preview['expires_at_ms']) is int and 0<=preview['expires_at_ms']<=9007199254740991
                        and isinstance(plan['created_at'],str) and len(plan['created_at'])<=64
                        and datetime.fromisoformat(plan['created_at'].replace('Z','+00:00')).tzinfo is not None,
                        'MC_MAINTENANCE_PLAN_BINDING')
                counts(preview['counts'],COUNT_KEYS); counts(dep['protection_counts'])
                items.append({'plan_file':path.name,'plan_sha256':hashlib.sha256(raw).hexdigest(),'created_at':plan['created_at'],
                              'game_instance_id':dep['game_instance_id'],'a_snapshot_sha256':dep['snapshot_sha256'],
                              'protected_tasks':len(dep['task_ids']),'protection_counts':dep['protection_counts'],
                              'expires_at_ms':preview['expires_at_ms'],'counts':preview['counts'],
                              'binding_matches':digest(plan['binding'])==self.binding_sha256})
            except (MaintenanceError, OSError, ValueError, KeyError, TypeError):
                issues.append({'plan_file':path.name,'code':'MC_MAINTENANCE_PLAN_UNREADABLE'})
        return {'items':sorted(items,key=lambda item:item['created_at'],reverse=True),'issues':issues}

    def close(self):
        self.begin_stop()
        # Native calls are already individually bounded. Finish the owned current
        # job instead of killing a potentially committed apply midway.
        while self.worker.is_alive():
            self.worker.join(timeout=.2)
        try:
            self.ledger.interrupt_pending()
        finally:
            self.ledger.close()

    def begin_stop(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()


def error_status(code):
    if code.endswith('_NOT_FOUND'):
        return 404
    if code in {'MC_MAINTENANCE_REQUEST_CONFLICT','MC_MAINTENANCE_CANCEL_BLOCKED'}:
        return 409
    if code in {'MC_MAINTENANCE_QUEUE_FULL','MC_MAINTENANCE_CONSOLE_CAPACITY'}:
        return 429
    if code == 'MC_MAINTENANCE_BODY_LIMIT':
        return 413
    if code == 'MC_MAINTENANCE_CONTENT_TYPE':
        return 415
    if code in {'MC_MAINTENANCE_CONSOLE_STOPPING','MC_MAINTENANCE_CONSOLE_STORAGE_FAILED',
                'MC_MAINTENANCE_NOT_CONFIGURED','MC_MAINTENANCE_RUNTIME_NOT_CONFIGURED'}:
        return 503
    return 400


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = False
    allow_reuse_address = False
    request_queue_size = 16

    def __init__(self, address, service):
        self.service = service
        super().__init__(address, ConsoleHandler)


class ConsoleHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_args):
        pass

    def send(self, status, value, content_type='application/json; charset=utf-8'):
        body = value if isinstance(value,bytes) else canonical(value)
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header('Connection','close')
        self.end_headers()
        self.close_connection = True
        self.wfile.write(body)

    def body(self):
        require(self.headers.get('Content-Type','').lower().split(';',1)[0].strip()=='application/json'
                and 'Content-Encoding' not in self.headers, 'MC_MAINTENANCE_CONTENT_TYPE')
        sizes = self.headers.get_all('Content-Length',[])
        require(len(sizes)==1 and re.fullmatch(r'[0-9]{1,8}',sizes[0]) and 'Transfer-Encoding' not in self.headers,
                'MC_MAINTENANCE_REQUEST_INVALID')
        size = int(sizes[0])
        require(0<size<=4096,'MC_MAINTENANCE_BODY_LIMIT')
        data = self.rfile.read(size)
        require(len(data)==size,'MC_MAINTENANCE_REQUEST_INVALID')
        return parse(data)

    def do_GET(self):
        self.handle_route(False)

    def do_POST(self):
        self.handle_route(True)

    def handle_route(self, post):
        try:
            require(len(self.path)<=2048,'MC_MAINTENANCE_REQUEST_INVALID')
            path = urlsplit(self.path)
            query = parse_qs(path.query,keep_blank_values=True,max_num_fields=4)
            service = self.server.service
            if path.path.startswith('/api/mc-runtime/'):
                runtime = getattr(service, 'runtime', None)
                require(runtime is not None, 'MC_MAINTENANCE_RUNTIME_NOT_CONFIGURED')
                runtime.handle(self, path.path, query, post)
                return
            if not post and path.path in {'/','/mc-maintenance','/mc-maintenance.js','/mc-maintenance.css','/mc-control.css',
                                         '/mc-runtime','/mc-runtime.js','/mc-runtime.css'}:
                require(not query,'MC_MAINTENANCE_REQUEST_INVALID')
                name = ('mc-runtime.html' if path.path == '/mc-runtime' or path.path == '/' and getattr(service,'runtime_default',False)
                        else 'mc-maintenance.html' if path.path in {'/','/mc-maintenance'} else path.path[1:])
                asset = safe_path(service.root/'web'/name)
                content = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8'}[asset.suffix]
                self.send(200,asset.read_bytes(),content)
                return
            if not post and path.path==PREFIX+'/jobs':
                require(set(query)<={'before','through'} and all(len(v)==1 and re.fullmatch(r'[0-9]{1,10}',v[0]) for v in query.values()),
                        'MC_MAINTENANCE_REQUEST_INVALID')
                page = service.ledger.page(int(query.get('before',['0'])[0]),int(query.get('through',['0'])[0]))
                page['items'] = [public_job(row) for row in page['items']]
                self.send(200,page)
                return
            require(not query,'MC_MAINTENANCE_REQUEST_INVALID')
            if not post and path.path==PREFIX+'/state':
                self.send(200,service.state())
            elif not post and path.path==PREFIX+'/plans':
                self.send(200,service.plans())
            elif post and path.path==PREFIX+'/jobs':
                result = service.enqueue(self.body())
                self.send(200 if result['duplicate'] else 202,result)
            elif post and path.path==PREFIX+'/stop':
                require(self.body()=={},'MC_MAINTENANCE_REQUEST_INVALID')
                service.begin_stop()
                self.send(202,{'stopping':True,'services_started':False})
                threading.Thread(target=self.server.shutdown,name='mc-maintenance-shutdown',daemon=True).start()
            elif not post and path.path.startswith(PREFIX+'/requests/'):
                key = path.path[len(PREFIX+'/requests/'):]
                require(REQUEST.fullmatch(key),'MC_MAINTENANCE_REQUEST_INVALID')
                self.send(200,public_job(service.ledger.get(key,request=True)))
            elif path.path.startswith(PREFIX+'/jobs/'):
                tail = path.path[len(PREFIX+'/jobs/'):]
                if post and tail.endswith('/cancel'):
                    job = tail[:-7]
                    require(JOB.fullmatch(job) and self.body()=={},'MC_MAINTENANCE_REQUEST_INVALID')
                    self.send(200,public_job(service.ledger.cancel(job)))
                else:
                    require(not post and JOB.fullmatch(tail),'MC_MAINTENANCE_REQUEST_INVALID')
                    self.send(200,public_job(service.ledger.get(tail)))
            else:
                self.send(404,{'code':'MC_MAINTENANCE_ROUTE_NOT_FOUND','outcome':'not_dispatched'})
        except MaintenanceError as error:
            self.send(error_status(error.code),{'code':error.code,'outcome':error.outcome})
        except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,RecursionError):
            self.send(503,{'code':'MC_MAINTENANCE_CONSOLE_UNAVAILABLE','outcome':'unknown' if post else 'not_applicable'})


def serve(root, coordinator, verify_installation):
    config = configuration(root)
    service = ConsoleService(root,coordinator,verify_installation,digest(coordinator.binding()))
    server = None
    try:
        server = ConsoleServer((config['host'],config['port']),service)
        print(json.dumps({'ok':True,'maintenance_console_listening':True,'host':config['host'],'port':server.server_port,
                          'services_started':False,'models_loaded':False,'automatic_input_authorized':False}),flush=True)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.server_close()
        service.close()
