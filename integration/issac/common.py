"""Small native, local-only boundaries shared by the Isaac services."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit
import uuid


class AdmissionError(ValueError):
    """A stable error code, safe to expose without raw private exception text."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def file_hash(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1024 * 1024):
            sha.update(data)
    return sha.hexdigest()


def inside(root, relative):
    root = Path(root).resolve()
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ':' in relative:
        raise AdmissionError('PROJECT_RELATIVE_PATH_REQUIRED')
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise AdmissionError('PATH_OUTSIDE_INSTALLATION')
    return target


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    data = (canonical(value) + '\n').encode('utf-8')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers (including status inspection) can briefly deny rename.
        # Keep the old complete file and retry only sharing/lock errors, bounded.
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except OSError as error:
                if getattr(error, 'winerror', None) not in {5, 32, 33} or attempt == 7:
                    raise
                time.sleep(min(.02 * 2**attempt, .16))
    finally:
        if temporary.exists():
            temporary.unlink()


def local_url(value, *, path_allowed=True):
    try:
        parsed = urlsplit(value)
        valid_port = parsed.port is not None and 1 <= parsed.port <= 65535
    except (ValueError, TypeError):
        raise AdmissionError('LOOPBACK_HTTP_ENDPOINT_REQUIRED') from None
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not valid_port
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not path_allowed and parsed.path not in ('', '/')):
        raise AdmissionError('LOOPBACK_HTTP_ENDPOINT_REQUIRED')
    return value.rstrip('/')


def native_only():
    if os.name != 'nt':
        raise AdmissionError('NATIVE_WINDOWS_REQUIRED')


def port_available(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', int(port)))
        except OSError:
            return False
    return True


class Audit:
    """Private append-only events. Never map this directory to an HTTP file route."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def append(self, kind, **fields):
        row = {'at_unix': time.time(), 'kind': kind, **fields}
        with self.lock, self.path.open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(canonical(row) + '\n')
            stream.flush()
        return row


class FileLease:
    """Kernel-backed single owner; stale JSON alone never proves a process is alive."""
    def __init__(self, path):
        self.path = Path(path)
        self.stream = None

    def acquire(self):
        native_only()
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        try:
            stream.seek(0, 2)
            if not stream.tell():
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            stream.close()
            raise AdmissionError('ANOTHER_INSTALLATION_OWNER_IS_ACTIVE') from None
        self.stream = stream
        return self

    def close(self):
        if self.stream:
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            self.stream.close()
            self.stream = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.close()
