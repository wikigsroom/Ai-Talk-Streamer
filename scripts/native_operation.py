"""Serialize native installation operations and roll back only their new family.

The persistent file is an OS byte-range lock, never an existence/PID lease.
Nested same-thread entry points share one transaction and one Windows job.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import stat
import tempfile
import threading
import time
import uuid
import sys

from native_windows_process import NativeJob, identity_alive, shared_read

LOCK = '.setup/native-runtime.operation.lock'
_states = {}
_states_lock = threading.Lock()
UNCERTAIN = {'STARTING', 'COMMITTING', 'ROLLBACK_INCOMPLETE', 'RECOVERY_REQUIRED'}


class OperationError(RuntimeError):
    pass


def registered_worker(record, script):
    """Match a direct worker or the one child of a Windows venv redirector.

    Keep the registered native owner unchanged; its job still owns both PIDs.
    No arbitrary ancestor, process name or PID-only adoption is accepted.
    """
    if not record or not identity_alive(record):
        return False
    command = record.get('command', [])
    if not command or Path(command[0]).resolve() != Path(sys.executable).resolve() \
            or str(Path(script).resolve()) not in command:
        return False
    if record['pid'] == os.getpid():
        return True
    import psutil
    current = psutil.Process()
    if current.ppid() != record['pid']:
        return False
    parent = psutil.Process(record['pid'])
    return parent.cmdline() == command and identity_alive(record)


def safe_path(root, path):
    root = Path(root).resolve()
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(root):
        raise OperationError('MC_NATIVE_OPERATION_PATH')
    for part in [path, *path.parents]:
        try:
            attributes = getattr(part.lstat(), 'st_file_attributes', 0)
        except FileNotFoundError:
            attributes = 0
        if part.is_symlink() or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise OperationError('MC_NATIVE_OPERATION_LINK')
        if part == root:
            break
    return path


def read_json(path):
    try:
        with shared_read(path) as stream:
            data = stream.read(1024 * 1024 + 1)
    except FileNotFoundError:
        return {}
    if len(data) > 1024 * 1024:
        raise OperationError('MC_NATIVE_REGISTRY_INVALID')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise OperationError('MC_NATIVE_REGISTRY_INVALID')
    return value


def atomic_json(root, path, value):
    path = safe_path(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        safe_path(root, path)
        deadline = time.monotonic() + 1
        while True:
            try:
                os.replace(name, path)
                break
            except PermissionError as error:
                if getattr(error, 'winerror', None) not in (5, 32, 33) or time.monotonic() >= deadline:
                    raise
                safe_path(root, path)
                time.sleep(.01)
    finally:
        Path(name).unlink(missing_ok=True)


def _state(root):
    key = os.path.normcase(str(Path(root).resolve()))
    with _states_lock:
        return _states.setdefault(key, {'lock': threading.RLock(), 'current': None})


def _open_lock(root):
    if os.name != 'nt':
        raise OperationError('MC_NATIVE_WINDOWS_REQUIRED')
    path = safe_path(root, Path(root) / LOCK)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(path, 'a+b', buffering=0)
    # Reopen without O_APPEND: metadata must replace, never append past old data.
    stream.close()
    stream = open(safe_path(root, path), 'r+b', buffering=0)
    stream.seek(0)
    return stream


def _lock(stream):
    import msvcrt
    stream.seek(0)
    try:
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise OperationError('MC_NATIVE_OPERATION_BUSY') from None


def _unlock(stream):
    import msvcrt
    stream.seek(0)
    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def _metadata(stream):
    stream.seek(1)
    data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise OperationError('MC_NATIVE_OPERATION_RECORD_INVALID')
    try:
        value = json.loads(data) if data else {}
    except (ValueError, UnicodeError):
        raise OperationError('MC_NATIVE_OPERATION_RECORD_INVALID') from None
    if not isinstance(value, dict):
        raise OperationError('MC_NATIVE_OPERATION_RECORD_INVALID')
    return value


def _pending(metadata):
    if metadata.get('phase') not in UNCERTAIN:
        return []
    own, inherited = metadata.get('processes', []), metadata.get('recovery_pending', [])
    if not isinstance(own, list) or not isinstance(inherited, list) or len(own) + len(inherited) > 128:
        raise OperationError('MC_NATIVE_OPERATION_RECORD_INVALID')
    values = own + inherited
    result = []
    for value in values:
        if identity_alive(value) and value not in result:
            result.append(value)
    return result


class NativeOperation:
    def __init__(self, root, action, stream, previous):
        self.root, self.stream = Path(root).resolve(), stream
        self.job, self.processes, self.registries, self.aborted = None, [], [], False
        self.supervisor = None
        self.value = {'schema_version': 1, 'operation_id': uuid.uuid4().hex,
            'action': action, 'phase': 'STARTING', 'controller_pid': os.getpid(),
            'started_at': datetime.now(timezone.utc).isoformat(), 'processes': [],
            'recovery_pending': _pending(previous),
            'previous_operation': {key: previous.get(key) for key in ('operation_id', 'phase', 'action')}}

    def write(self):
        self.stream.seek(1)
        data = json.dumps(self.value, ensure_ascii=False).encode('utf-8')
        if self.stream.write(data) != len(data):
            raise OSError('MC_NATIVE_OPERATION_RECORD_SHORT_WRITE')
        self.stream.truncate(); self.stream.flush(); os.fsync(self.stream.fileno())

    def spawn(self, command, *, cwd, stdout, stderr, registry, key=None, env=None):
        path = safe_path(self.root, registry)
        existing = read_json(path)
        selected = existing.get(key, {}) if key is not None else existing
        if selected:
            if not isinstance(selected, dict) or type(selected.get('pid')) is not int:
                raise OperationError('MC_NATIVE_REGISTRY_INVALID')
            if 'creation_ticks' in selected:
                alive = identity_alive(selected)
            else:
                # Legacy records cannot prove exact ownership. An extant PID
                # requires review rather than risking a second model loader.
                import psutil
                alive = psutil.pid_exists(selected['pid'])
            if alive:
                raise OperationError('MC_NATIVE_SERVICE_ALREADY_OWNED')
        if self.job is None:
            self.job = NativeJob()
        process = self.job.spawn(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr)
        self.processes.append(process)
        self.value['processes'].append(process.identity())
        self.write()
        record = {**process.identity(), 'command': [str(arg) for arg in command],
            'started': process.created_at, 'started_at': process.created_at,
            'native_operation_id': self.value['operation_id'], 'native_supervision_version': 1}
        self.registries.append((path, key, record))
        value = {**existing, key: record} if key is not None else record
        atomic_json(self.root, path, value)
        return process

    def _remove_records(self):
        for path, key, record in reversed(self.registries):
            value = read_json(safe_path(self.root, path))
            selected = value.get(key) if key is not None else value
            if selected != record:
                continue
            if key is None:
                path.unlink()
            else:
                del value[key]
                atomic_json(self.root, path, value)

    def rollback(self):
        failures = []
        try:
            if self.job:
                self.job.rollback()
            # Job accounting can reach zero before the root process handles
            # become signalled. A completed rollback promises exited owners.
            for process in self.processes:
                process.wait(timeout=15)
            self._remove_records()
        except BaseException as error:
            failures.append(type(error).__name__)
        try:
            if self.supervisor:
                self.supervisor.abort()
        except BaseException as error:
            failures.append(type(error).__name__)
        try:
            pending = [p for p in self.value['recovery_pending'] if identity_alive(p)]
            self.value['recovery_pending'] = pending
        except BaseException as error:
            failures.append(type(error).__name__)
        self.value.update(phase='ROLLBACK_INCOMPLETE' if failures else
            ('RECOVERY_REQUIRED' if self.value['recovery_pending'] else 'ROLLED_BACK'),
            cleanup_errors=failures, finished_at=datetime.now(timezone.utc).isoformat())
        try:
            self.write()
        except BaseException as error:
            failures.append(type(error).__name__)
        if self.job:
            self.job.close()
        if failures:
            raise OperationError('MC_NATIVE_ROLLBACK_INCOMPLETE')

    def commit(self):
        if self.aborted:
            raise OperationError('MC_NATIVE_NESTED_OPERATION_ABORTED')
        if any(process.poll() is not None for process in self.processes):
            raise OperationError('MC_NATIVE_SERVICE_EXITED_DURING_START')
        self.value['recovery_pending'] = [p for p in self.value['recovery_pending'] if identity_alive(p)]
        if self.value['recovery_pending']:
            raise OperationError('MC_NATIVE_RECOVERY_INCOMPLETE')
        self.value['phase'] = 'COMMITTING'; self.write()
        # Keep the job handle until the durable commit record is written. If
        # that write fails, TerminateJobObject still rolls the whole family back.
        if self.job:
            from native_supervision import Handoff
            self.supervisor = Handoff(self)
            self.job.prepare_commit(supervised=True)
            if any(process.poll() is not None for process in self.processes):
                raise OperationError('MC_NATIVE_SERVICE_EXITED_DURING_HANDOFF')
        self.value.update(phase='COMPLETED', finished_at=datetime.now(timezone.utc).isoformat())
        self.write()
        if self.job:
            self.supervisor.wait('RUNNING')
            self.job.close()


@contextmanager
def operation(root, action, *, recovery=False):
    root = Path(root).resolve()
    state = _state(root)
    if not state['lock'].acquire(blocking=False):
        raise OperationError('MC_NATIVE_OPERATION_BUSY')
    stream, locked = None, False
    try:
        if state['current'] is not None:
            try:
                yield state['current']
            except BaseException:
                state['current'].aborted = True
                raise
            return
        stream = _open_lock(root)
        _lock(stream); locked = True
        previous = _metadata(stream)
        if _pending(previous) and not recovery:
            raise OperationError('MC_NATIVE_OPERATION_RECOVERY_REQUIRED')
        current = NativeOperation(root, action, stream, previous)
        state['current'] = current
        try:
            current.write()
            yield current
            current.commit()
        except BaseException:
            current.rollback()
            raise
        finally:
            for process in current.processes:
                process.close()
            if current.supervisor:
                current.supervisor.close()
            state['current'] = None
    finally:
        if stream:
            try:
                if locked:
                    _unlock(stream)
            finally:
                stream.close()
        state['lock'].release()


def status(root):
    """An operation status is never a service/model readiness assertion."""
    path = safe_path(root, Path(root).resolve() / LOCK)
    if not path.exists():
        return {'busy': False, 'phase': 'NO_OPERATION', 'service_readiness_checked': False}
    stream, locked = _open_lock(root), False
    try:
        try:
            _lock(stream); locked = True
        except OperationError:
            pass
        try:
            value = _metadata(stream)
        except OperationError:
            value = {'phase': 'RECORD_UNAVAILABLE'}
        if locked and value.get('phase') in UNCERTAIN:
            value = {**value, 'recovery_required': bool(_pending(value))}
        return {**value, 'busy': not locked, 'service_readiness_checked': False}
    finally:
        if locked:
            _unlock(stream)
        stream.close()
