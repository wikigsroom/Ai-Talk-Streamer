"""Operation-scoped digests protected by native Windows read sharing."""
import ctypes as ct
from ctypes import wintypes as wt
import hashlib
import os


class ArtifactPinError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def locked_reader(path):
    """Permit other readers while denying data writes, deletion and replacement."""
    if os.name != 'nt':
        raise ArtifactPinError('MC_ARTIFACT_WINDOWS_REQUIRED')
    import msvcrt
    kernel = ct.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ct.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    create.restype = wt.HANDLE
    close = kernel.CloseHandle; close.argtypes = [wt.HANDLE]; close.restype = wt.BOOL
    handle = create(str(path), 0x80000000, 0x00000001, None, 3, 0x08000080, None)
    if handle == wt.HANDLE(-1).value:
        raise ct.WinError(ct.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        close(handle)
        raise
    try:
        os.set_inheritable(descriptor, False)
        return os.fdopen(descriptor, 'rb')
    except BaseException:
        os.close(descriptor)
        raise


def identity(stream):
    row = os.fstat(stream.fileno())
    return row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns


class FileHashPins:
    def __init__(self):
        self.pins = {}
        self.statistics = {'policy': 'WINDOWS_READ_HANDLES_UNTIL_OPERATION_EXIT',
                           'hashed_files': 0, 'hashed_bytes': 0, 'cache_hits': 0}

    def digest(self, path):
        key = os.path.normcase(str(path))
        stream = locked_reader(path)
        keep = False
        try:
            signature = identity(stream)
            previous = self.pins.get(key)
            if previous:
                held, expected, digest = previous
                if signature != expected or identity(held) != expected:
                    raise ArtifactPinError('MC_ARTIFACT_PIN_CHANGED')
                self.statistics['cache_hits'] += 1
                return digest
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
            if identity(stream) != signature:
                raise ArtifactPinError('MC_ARTIFACT_CHANGED_DURING_HASH')
            result = digest.hexdigest()
            self.pins[key] = stream, signature, result
            self.statistics['hashed_files'] += 1
            self.statistics['hashed_bytes'] += signature[2]
            keep = True
            return result
        finally:
            if not keep:
                stream.close()

    def close(self):
        from contextlib import ExitStack
        with ExitStack() as pending:
            for stream, _, _ in self.pins.values():
                pending.callback(stream.close)
            self.pins.clear()
