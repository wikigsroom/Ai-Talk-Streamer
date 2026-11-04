"""Measure CPU dependency imports inside one bounded native Windows process family."""
from pathlib import Path
import json
import math
import re
import time
import uuid

from native_operation import atomic_json, read_json, safe_path
from native_windows_process import NativeJob


class ImportCheckError(RuntimeError):
    def __init__(self, code, details):
        self.code, self.details = code, details
        super().__init__(code)


PROBE = r'''
from pathlib import Path
import importlib,json,os,sys,tempfile,time
spec=json.loads(sys.argv[1]);path=Path(spec['progress']);started=time.monotonic();completed=[]
def publish(phase,module=None,error_type=None):
    value={'run_id':spec['run_id'],'phase':phase,'module':module,'completed':completed,
           'elapsed_ms':round((time.monotonic()-started)*1000)}
    if error_type:value['error_type']=error_type
    fd,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf8')as out:
            json.dump(value,out);out.flush();os.fsync(out.fileno())
    deadline=time.monotonic()+1
    while True:
        try:os.replace(name,path);break
        except PermissionError as error:
            if getattr(error,'winerror',None)not in(5,32,33)or time.monotonic()>=deadline:raise
            time.sleep(.01)
    finally:
        if os.path.exists(name):os.unlink(name)
    print(json.dumps(value),flush=True)
sys.path[:0]=spec['source_paths']
publish('INTERPRETER_READY')
for module in spec['modules']:
    publish('IMPORTING',module);tick=time.monotonic()
    try:importlib.import_module(module)
    except BaseException as error:
        category=next((kind.__name__ for kind in (ImportError,OSError,ValueError,RuntimeError)
                       if isinstance(error,kind)),'Exception')
        publish('FAILED',module,category);raise SystemExit(1)
    completed.append({'module':module,'elapsed_ms':round((time.monotonic()-tick)*1000)})
    publish('IMPORTED',module)
publish('SUCCEEDED')
'''


def probe_progress(path, run_id, modules):
    value = read_json(path)
    if value.get('run_id') != run_id or value.get('phase') not in {
            'WAITING_FOR_INTERPRETER', 'INTERPRETER_READY', 'IMPORTING', 'IMPORTED', 'SUCCEEDED', 'FAILED'}:
        raise ValueError('MC_IMPORT_PROGRESS_INVALID')
    module = value.get('module')
    completed = value.get('completed')
    if module is not None and module not in modules or not isinstance(completed, list) or len(completed) > len(modules):
        raise ValueError('MC_IMPORT_PROGRESS_INVALID')
    rows = []
    for index, row in enumerate(completed):
        if not isinstance(row, dict) or row.get('module') != modules[index] \
                or type(row.get('elapsed_ms')) is not int or not 0 <= row['elapsed_ms'] <= 86400000:
            raise ValueError('MC_IMPORT_PROGRESS_INVALID')
        rows.append({'module': row['module'], 'elapsed_ms': row['elapsed_ms']})
    result = {'phase': value['phase'], 'module': module, 'completed': rows}
    if value.get('error_type') in {'ImportError', 'OSError', 'ValueError', 'RuntimeError', 'Exception'}:
        result['error_type'] = value['error_type']
    return result


def run_imports(root, executable, modules, *, env, label, source_paths=(), timeout=300,
                module_timeout=180, progress=None):
    """The group and each module have deadlines; failures close all descendants."""
    root = Path(root).resolve()
    executable = Path(executable)
    if not isinstance(modules, (list, tuple)) or any(not isinstance(m, str) for m in modules):
        raise ValueError('MC_IMPORT_REQUEST_INVALID')
    modules = list(modules)
    if not executable.is_absolute() or not executable.is_file() or not re.fullmatch(r'[a-z0-9-]{1,80}', label) \
            or not 1 <= len(modules) <= 32 or len(set(modules)) != len(modules) \
            or any(not isinstance(m, str) or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*){0,15}', m) for m in modules):
        raise ValueError('MC_IMPORT_REQUEST_INVALID')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 600
           for v in (timeout, module_timeout)):
        raise ValueError('MC_IMPORT_DEADLINE_INVALID')
    if env.get('CUDA_VISIBLE_DEVICES') != '-1':
        raise ValueError('MC_IMPORT_CPU_ENVIRONMENT_REQUIRED')
    paths = [str(safe_path(root, root / p)) for p in source_paths]
    run_id = uuid.uuid4().hex
    folder = safe_path(root, root / '.setup/mc-dependency-checks')
    folder.mkdir(parents=True, exist_ok=True)
    status_path = safe_path(root, folder / (label + '-' + run_id + '.progress.json'))
    result_path = safe_path(root, folder / (label + '-' + run_id + '.result.json'))
    log_path = safe_path(root, root / 'logs' / ('mc-readiness-' + label + '-' + run_id + '.log'))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {'phase': 'WAITING_FOR_INTERPRETER', 'module': None, 'completed': []}
    atomic_json(root, status_path, {'run_id': run_id, **snapshot})
    result = {'ok': False, 'run_id': run_id, 'cpu_only': env.get('CUDA_VISIBLE_DEVICES') == '-1',
              'modules': modules, 'log': log_path.relative_to(root).as_posix(),
              'progress': status_path.relative_to(root).as_posix(),
              'timeout_seconds': timeout, 'module_timeout_seconds': module_timeout,
              'family_closed': False}
    spec = {'run_id': run_id, 'modules': modules, 'progress': str(status_path), 'source_paths': paths}
    job = process = None
    caught = None
    code = 'MC_IMPORT_CHECK_FAILED'
    started = time.monotonic()
    last_key = None
    module_started = started
    last_publish = -math.inf
    root_exited = None
    callback_failed = False
    try:
        job = NativeJob()
        with log_path.open('xb') as output:
            process = job.spawn([str(executable), '-u', '-X', 'utf8', '-B', '-c', PROBE,
                                 json.dumps(spec)], cwd=root, env=env, stdout=output, stderr=output)
            result['owner'] = process.identity()
            while True:
                snapshot = probe_progress(status_path, run_id, modules)
                now = time.monotonic()
                key = snapshot['phase'], snapshot['module'], len(snapshot['completed'])
                if key != last_key:
                    module_started = now
                if progress and (key != last_key or now - last_publish >= 5):
                    try:
                        progress({**result, **snapshot, 'elapsed_ms': round((now - started) * 1000)})
                    except Exception:
                        callback_failed = True
                        code = 'MC_IMPORT_PROGRESS_PUBLISH_FAILED'
                        raise
                    last_publish = now
                last_key = key
                if now - started >= timeout:
                    code = 'MC_IMPORT_CHECK_TIMEOUT'
                    raise RuntimeError(code)
                exit_code = process.poll()
                if exit_code is not None:
                    result['exit_code'] = exit_code
                    if exit_code != 0:
                        raise RuntimeError('MC_IMPORT_CHECK_FAILED')
                    if job.active() == 0:
                        if snapshot['phase'] != 'SUCCEEDED' or len(snapshot['completed']) != len(modules):
                            code = 'MC_IMPORT_COMPLETION_MISSING'
                            raise RuntimeError(code)
                        result['ok'] = True
                        break
                    if root_exited is None:
                        root_exited = now
                    if now - root_exited >= 5:
                        code = 'MC_IMPORT_FAMILY_STILL_RUNNING'
                        raise RuntimeError(code)
                if snapshot['phase'] == 'IMPORTING' and now - module_started >= module_timeout:
                    code = 'MC_IMPORT_MODULE_TIMEOUT'
                    raise RuntimeError(code)
                time.sleep(min(.1, max(0, timeout - (now - started))))
    except BaseException as error:
        caught = error
    finally:
        try:
            if job is not None:
                if job.active():
                    job.rollback(timeout=15)
                result['family_closed'] = job.active() == 0
        except BaseException as cleanup:
            result['ok'] = False
            code = 'MC_IMPORT_FAMILY_CLEANUP_FAILED'
            if caught is None:
                caught = cleanup
        finally:
            if process is not None:
                process.close()
            if job is not None:
                job.close()
        result.update(snapshot)
        result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
        result['code'] = 'MC_IMPORT_CHECK_PASSED' if result['ok'] else code
        result['result'] = result_path.relative_to(root).as_posix()
        atomic_json(root, result_path, result)
        if progress and not callback_failed:
            try:
                progress(result.copy())
            except Exception as error:
                result['ok'] = False
                code = result['code'] = 'MC_IMPORT_PROGRESS_PUBLISH_FAILED'
                atomic_json(root, result_path, result)
                if caught is None:
                    caught = error
    if caught is not None:
        if not isinstance(caught, Exception):
            raise caught
        raise ImportCheckError(code, result) from None
    return result
