"""Persist ownership of committed native jobs; no model or service imports.

The worker inherits explicit job/process handles, never joins the owned job,
and keeps KILL_ON_JOB_CLOSE. It observes process handles rather than PID leases.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import ctypes as ct
from ctypes import wintypes as wt
import json
import os
import re
import sys
import time

import native_operation as native
from native_windows_process import NativeJob, NativeProcess, api, checked, creation_ticks, identity_alive, spawn_process, shared_read

DIRECTORY = '.setup/native-supervision'
ID = re.compile(r'[0-9a-f]{32}')


def paths(root, operation_id):
    if not isinstance(operation_id, str) or not ID.fullmatch(operation_id):
        raise native.OperationError('MC_NATIVE_SUPERVISION_ID_INVALID')
    base = native.safe_path(root, Path(root) / DIRECTORY / operation_id)
    return {name: native.safe_path(root, base.with_suffix(suffix)) for name, suffix in
            [('input', '.input.json'), ('status', '.json'), ('stop', '.stop.json'), ('log', '.log')]}


def identity(value):
    if not isinstance(value, dict) or any(type(value.get(k)) is not int or value[k] <= 0
                                         for k in ('pid', 'creation_ticks')):
        raise native.OperationError('MC_NATIVE_SUPERVISION_IDENTITY_INVALID')
    return {k: value[k] for k in ('pid', 'creation_ticks')}


def own_identity():
    kernel = api()
    return {'pid': os.getpid(), 'creation_ticks': creation_ticks(kernel, kernel.GetCurrentProcess())}


def members(value):
    processes = value.get('processes')
    if not isinstance(processes, list) or not 1 <= len(processes) <= 128:
        raise native.OperationError('MC_NATIVE_SUPERVISION_MEMBERS_INVALID')
    result = [identity(p) for p in processes]
    if len({(p['pid'], p['creation_ticks']) for p in result}) != len(result):
        raise native.OperationError('MC_NATIVE_SUPERVISION_MEMBERS_INVALID')
    return result


def expected(root, files, value):
    control = native.read_json(native.safe_path(root, files['stop']))
    if not control:
        return []
    if control.get('schema_version') != 1 or control.get('operation_id') != value['operation_id'] \
            or not isinstance(control.get('expected'), list) or len(control['expected']) > 128:
        raise native.OperationError('MC_NATIVE_SUPERVISION_STOP_INVALID')
    allowed = members(value)
    result = [identity(p) for p in control['expected']]
    if any(p not in allowed for p in result) or len(result) != len({p['pid'] for p in result}):
        raise native.OperationError('MC_NATIVE_SUPERVISION_STOP_INVALID')
    return result


class Handoff:
    def __init__(self, transaction):
        self.root, self.operation_id = transaction.root, transaction.value['operation_id']
        self.files = paths(self.root, self.operation_id)
        self.process = None
        duplicates = []
        kernel = transaction.job.kernel
        def duplicate(handle):
            result = wt.HANDLE()
            checked(kernel.DuplicateHandle(kernel.GetCurrentProcess(), handle, kernel.GetCurrentProcess(),
                                           ct.byref(result), 0, True, 2))
            duplicates.append(result.value)
            return result.value
        try:
            value = {'schema_version': 1, 'operation_id': self.operation_id, 'root': str(self.root),
                     'parent': own_identity(), 'job_handle': duplicate(transaction.job.handle),
                     'processes': [{**p.identity(), 'handle': duplicate(p.handle)} for p in transaction.processes],
                     'registries': [{'path': p.relative_to(self.root).as_posix(), 'key': key, 'record': record}
                                    for p, key, record in transaction.registries]}
            if self.files['input'].exists() or self.files['status'].exists():
                raise native.OperationError('MC_NATIVE_SUPERVISION_ALREADY_EXISTS')
            native.atomic_json(self.root, self.files['input'], value)
            with self.files['log'].open('ab') as log:
                # Windows venv python.exe is a redirector: CreateProcess returns
                # its PID, but the worker runs in a second process. The stdlib-only
                # supervisor must run directly in the base interpreter so the
                # exact handle/PID/creation-time handoff remains meaningful.
                executable = Path(getattr(sys, '_base_executable', sys.executable)).resolve()
                if not executable.is_file():
                    raise native.OperationError('MC_NATIVE_SUPERVISOR_INTERPRETER_MISSING')
                self.process = spawn_process([str(executable), '-E', '-s', '-B', '-X', 'utf8',
                    str(Path(__file__).resolve()), '--worker', str(self.root), self.operation_id],
                    cwd=self.root, stdout=log, stderr=log, inherited_handles=duplicates)
            self.wait('ARMED')
        except BaseException:
            self.abort()
            self.close()
            raise
        finally:
            for handle in duplicates:
                kernel.CloseHandle(handle)

    def wait(self, phase, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise native.OperationError('MC_NATIVE_SUPERVISOR_EXITED_DURING_HANDOFF')
            value = native.read_json(self.files['status'])
            if value.get('phase') == phase:
                worker = identity(value.get('supervisor'))
                if value.get('operation_id') != self.operation_id or worker['pid'] != self.process.pid \
                        or not identity_alive(worker):
                    raise native.OperationError('MC_NATIVE_SUPERVISION_HANDOFF_MISMATCH')
                return value
            if value.get('phase', '') not in ('', 'ARMED', phase):
                raise native.OperationError('MC_NATIVE_SUPERVISION_HANDOFF_FAILED')
            time.sleep(.02)
        raise native.OperationError('MC_NATIVE_SUPERVISION_HANDOFF_TIMEOUT')

    def abort(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait(timeout=10)

    def close(self):
        if self.process is not None:
            self.process.close()


def _operation_record(root):
    path = native.safe_path(root, Path(root) / native.LOCK)
    with shared_read(path) as stream:
        return native._metadata(stream)


def _cleanup(root, value):
    """Share the installation lock; never remove a replacement owner's record."""
    deadline = time.monotonic() + 8
    while True:
        try:
            with native.operation(root, 'supervision-cleanup', recovery=True):
                records = value.get('registries')
                if not isinstance(records, list) or len(records) > 128:
                    raise native.OperationError('MC_NATIVE_SUPERVISION_REGISTRY_INVALID')
                for item in records:
                    path = native.safe_path(root, Path(root) / item['path'])
                    current = native.read_json(path)
                    key = item['key']
                    selected = current.get(key) if key is not None else current
                    if selected != item['record']:
                        continue
                    if key is None:
                        path.unlink()
                    else:
                        del current[key]
                        native.atomic_json(root, path, current)
            return True
        except native.OperationError as error:
            if str(error) != 'MC_NATIVE_OPERATION_BUSY' or time.monotonic() >= deadline:
                return False
            time.sleep(.05)
        except (OSError, ValueError, KeyError, TypeError):
            return False


def worker(root, operation_id):
    root = Path(root).resolve()
    files = paths(root, operation_id)
    value = native.read_json(files['input'])
    if value.get('schema_version') != 1 or value.get('operation_id') != operation_id or value.get('root') != str(root):
        raise native.OperationError('MC_NATIVE_SUPERVISION_INPUT_INVALID')
    identities = members(value)
    kernel = api()
    job = NativeJob.__new__(NativeJob)
    job.kernel, job.handle = kernel, value['job_handle']
    processes = []
    state = {'schema_version': 1, 'operation_id': operation_id, 'supervisor': own_identity(),
             'members': identities, 'service_readiness_checked': False, 'family_empty_confirmed': False}
    def report(phase, **extra):
        state.update(phase=phase, updated_at=datetime.now(timezone.utc).isoformat(), **extra)
        native.atomic_json(root, files['status'], state)
    try:
        job.active()  # Validate inherited job before claiming ownership.
        for item, recorded in zip(value['processes'], identities):
            process = NativeProcess(kernel, item['handle'], checked(kernel.GetProcessId(item['handle'])))
            processes.append(process)
            inside = wt.BOOL()
            checked(kernel.IsProcessInJob(process.handle, job.handle, ct.byref(inside)))
            if process.identity() != recorded or not inside.value:
                raise native.OperationError('MC_NATIVE_SUPERVISION_HANDLE_MISMATCH')
        report('ARMED')
        deadline = time.monotonic() + 25
        while True:
            try:
                record = _operation_record(root)
            except (ValueError, native.OperationError):
                record = {}
            if record.get('operation_id') == operation_id and record.get('phase') == 'COMPLETED':
                break
            if not identity_alive(value['parent']) or time.monotonic() >= deadline:
                raise native.OperationError('MC_NATIVE_SUPERVISION_COMMIT_NOT_CONFIRMED')
            time.sleep(.02)
        report('RUNNING')
        while True:
            ended = [(p, p.poll()) for p in processes]
            # The caller persists intent before stopping. Read intent after
            # exit observations so a simultaneous legitimate stop is visible.
            planned = expected(root, files, value)
            unexpected = [(p, code) for p, code in ended if code is not None and p.identity() not in planned]
            if unexpected or all(code is not None for _, code in ended):
                report('FAULTING' if unexpected else 'STOPPING', reason='UNEXPECTED_ROOT_EXIT' if unexpected else 'EXPECTED_STOP',
                       exited=[{**p.identity(), 'exit_code': code} for p, code in ended if code is not None])
                job.rollback()
                clean = _cleanup(root, value)
                report('FAULTED' if unexpected else 'STOPPED', family_empty_confirmed=job.active() == 0,
                       registry_cleanup_confirmed=clean)
                return
            time.sleep(.05)
    except BaseException as error:
        job.rollback()
        clean = _cleanup(root, value)
        report('FAULTED', reason='SUPERVISION_FAILURE', error_type=type(error).__name__,
               family_empty_confirmed=job.active() == 0, registry_cleanup_confirmed=clean)
        raise
    finally:
        for process in processes:
            process.close()
        job.close()


@contextmanager
def expected_stops(root, entries):
    """Must surround the actual stop while its existing operation lock is held."""
    root = Path(root).resolve()
    if native._state(root)['current'] is None:
        raise native.OperationError('MC_NATIVE_SUPERVISION_STOP_REQUIRES_OPERATION')
    groups = {}
    for path, key, record in entries:
        if record.get('native_supervision_version') != 1:
            continue  # Legacy records are never adopted by a new supervisor.
        operation_id = record.get('native_operation_id')
        files = paths(root, operation_id)
        value = native.read_json(files['input'])
        target = {'path': native.safe_path(root, path).relative_to(root).as_posix(), 'key': key, 'record': record}
        if value.get('operation_id') != operation_id or target not in value.get('registries', []):
            raise native.OperationError('MC_NATIVE_SUPERVISION_STOP_OWNER_MISMATCH')
        group = groups.setdefault(operation_id, {'files': files, 'value': value, 'before': expected(root, files, value), 'added': []})
        item = identity(record)
        if item not in group['before'] and item not in group['added']:
            group['added'].append(item)
    def save(operation_id, group, values):
        native.atomic_json(root, group['files']['stop'], {'schema_version': 1, 'operation_id': operation_id, 'expected': values})
    try:
        for operation_id, group in groups.items():
            save(operation_id, group, group['before'] + group['added'])
        yield
    except BaseException:
        for operation_id, group in groups.items():
            save(operation_id, group, group['before'] + [p for p in group['added'] if not identity_alive(p)])
        raise


def status(root):
    root = Path(root).resolve()
    folder = native.safe_path(root, root / DIRECTORY)
    groups = []
    for path in sorted(folder.glob('*.json')) if folder.exists() else []:
        if not ID.fullmatch(path.stem):
            continue
        value = native.read_json(native.safe_path(root, path))
        if value.get('operation_id') != path.stem:
            raise native.OperationError('MC_NATIVE_SUPERVISION_STATUS_INVALID')
        alive = identity_alive(identity(value.get('supervisor')))
        groups.append({**value, 'supervisor_alive': alive,
                       'phase': 'SUPERVISOR_EXITED' if not alive and value.get('phase') in {'ARMED', 'RUNNING', 'FAULTING', 'STOPPING'} else value.get('phase'),
                       'service_readiness_checked': False})
    return {'groups': groups, 'service_readiness_checked': False, 'services_started_by_query': False}


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--worker':
        raise SystemExit('MC_NATIVE_SUPERVISION_WORKER_ARGUMENTS_REQUIRED')
    worker(sys.argv[2], sys.argv[3])
