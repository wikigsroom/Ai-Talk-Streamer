"""Windows process families assigned to a kill-on-close job at creation time.

Only the caller's newly created processes belong to this job. No process-name
search, external command, GPU import or virtual environment is involved.
"""
import ctypes as ct
from ctypes import wintypes as wt
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import time


class NativeProcessError(RuntimeError):
    pass


class STARTUPINFO(ct.Structure):
    _fields_ = [('cb', wt.DWORD), ('lpReserved', wt.LPWSTR), ('lpDesktop', wt.LPWSTR),
        ('lpTitle', wt.LPWSTR), ('dwX', wt.DWORD), ('dwY', wt.DWORD),
        ('dwXSize', wt.DWORD), ('dwYSize', wt.DWORD), ('dwXCountChars', wt.DWORD),
        ('dwYCountChars', wt.DWORD), ('dwFillAttribute', wt.DWORD),
        ('dwFlags', wt.DWORD), ('wShowWindow', wt.WORD), ('cbReserved2', wt.WORD),
        ('lpReserved2', ct.POINTER(wt.BYTE)), ('hStdInput', wt.HANDLE),
        ('hStdOutput', wt.HANDLE), ('hStdError', wt.HANDLE)]


class STARTUPINFOEX(ct.Structure):
    _fields_ = [('StartupInfo', STARTUPINFO), ('lpAttributeList', ct.c_void_p)]


class PROCESS_INFORMATION(ct.Structure):
    _fields_ = [('hProcess', wt.HANDLE), ('hThread', wt.HANDLE),
                ('dwProcessId', wt.DWORD), ('dwThreadId', wt.DWORD)]


class BASIC_LIMIT(ct.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ct.c_longlong),
        ('PerJobUserTimeLimit', ct.c_longlong), ('LimitFlags', wt.DWORD),
        ('MinimumWorkingSetSize', ct.c_size_t), ('MaximumWorkingSetSize', ct.c_size_t),
        ('ActiveProcessLimit', wt.DWORD), ('Affinity', ct.c_size_t),
        ('PriorityClass', wt.DWORD), ('SchedulingClass', wt.DWORD)]


class IO_COUNTERS(ct.Structure):
    _fields_ = [(name, ct.c_ulonglong) for name in
        ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
         'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class EXTENDED_LIMIT(ct.Structure):
    _fields_ = [('BasicLimitInformation', BASIC_LIMIT), ('IoInfo', IO_COUNTERS),
        ('ProcessMemoryLimit', ct.c_size_t), ('JobMemoryLimit', ct.c_size_t),
        ('PeakProcessMemoryUsed', ct.c_size_t), ('PeakJobMemoryUsed', ct.c_size_t)]


class ACCOUNTING(ct.Structure):
    _fields_ = [(name, ct.c_longlong) for name in
        ('TotalUserTime', 'TotalKernelTime', 'ThisPeriodTotalUserTime', 'ThisPeriodTotalKernelTime')]
    _fields_ += [(name, wt.DWORD) for name in
        ('TotalPageFaultCount', 'TotalProcesses', 'ActiveProcesses', 'TotalTerminatedProcesses')]


def api():
    if os.name != 'nt':
        raise NativeProcessError('MC_NATIVE_WINDOWS_REQUIRED')
    kernel = ct.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([ct.c_void_p, wt.LPCWSTR], wt.HANDLE),
        'SetInformationJobObject': ([wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD], wt.BOOL),
        'QueryInformationJobObject': ([wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD, ct.c_void_p], wt.BOOL),
        'TerminateJobObject': ([wt.HANDLE, wt.UINT], wt.BOOL),
        'TerminateProcess': ([wt.HANDLE, wt.UINT], wt.BOOL),
        'CloseHandle': ([wt.HANDLE], wt.BOOL),
        'InitializeProcThreadAttributeList': ([ct.c_void_p, wt.DWORD, wt.DWORD, ct.POINTER(ct.c_size_t)], wt.BOOL),
        'UpdateProcThreadAttribute': ([ct.c_void_p, wt.DWORD, ct.c_size_t, ct.c_void_p, ct.c_size_t, ct.c_void_p, ct.c_void_p], wt.BOOL),
        'DeleteProcThreadAttributeList': ([ct.c_void_p], None),
        'GetCurrentProcess': ([], wt.HANDLE),
        'DuplicateHandle': ([wt.HANDLE, wt.HANDLE, wt.HANDLE, ct.POINTER(wt.HANDLE), wt.DWORD, wt.BOOL, wt.DWORD], wt.BOOL),
        'CreateProcessW': ([wt.LPCWSTR, wt.LPWSTR, ct.c_void_p, ct.c_void_p, wt.BOOL, wt.DWORD, ct.c_void_p,
                            wt.LPCWSTR, ct.c_void_p, ct.POINTER(PROCESS_INFORMATION)], wt.BOOL),
        'WaitForSingleObject': ([wt.HANDLE, wt.DWORD], wt.DWORD),
        'GetExitCodeProcess': ([wt.HANDLE, ct.POINTER(wt.DWORD)], wt.BOOL),
        'GetProcessTimes': ([wt.HANDLE, ct.POINTER(wt.FILETIME), ct.POINTER(wt.FILETIME),
                             ct.POINTER(wt.FILETIME), ct.POINTER(wt.FILETIME)], wt.BOOL),
        'OpenProcess': ([wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
        'GetProcessId': ([wt.HANDLE], wt.DWORD),
        'IsProcessInJob': ([wt.HANDLE, wt.HANDLE, ct.POINTER(wt.BOOL)], wt.BOOL),
        'CreateFileW': ([wt.LPCWSTR, wt.DWORD, wt.DWORD, ct.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE], wt.HANDLE),
    }
    for name, (args, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    return kernel


def checked(value):
    if not value:
        raise ct.WinError(ct.get_last_error())
    return value


@contextmanager
def shared_read(path):
    """Read a Windows record with explicit read/write/delete sharing."""
    if os.name != 'nt':
        with open(path, 'rb') as stream:
            yield stream
        return
    import msvcrt
    kernel = api()
    deadline = time.monotonic() + 1
    while True:
        handle = kernel.CreateFileW(str(path), 0x80000000, 1 | 2 | 4, None, 3, 0x80, None)
        if handle != ct.c_void_p(-1).value:
            break
        error = ct.get_last_error()
        if error not in (5, 32, 33) or time.monotonic() >= deadline:
            raise ct.WinError(error)
        time.sleep(.01)
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, 'rb') as stream:
        yield stream


def creation_ticks(kernel, handle):
    values = [wt.FILETIME() for _ in range(4)]
    checked(kernel.GetProcessTimes(handle, *(ct.byref(value) for value in values)))
    return (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime


def identity_alive(identity):
    """Read only: PID reuse never counts as the recorded process still running."""
    if not isinstance(identity, dict) or type(identity.get('pid')) is not int or identity['pid'] <= 0 \
            or type(identity.get('creation_ticks')) is not int or identity['creation_ticks'] <= 0:
        raise NativeProcessError('MC_NATIVE_PROCESS_IDENTITY_INVALID')
    kernel = api()
    handle = kernel.OpenProcess(0x100000 | 0x1000, False, identity['pid'])
    if not handle:
        if ct.get_last_error() in (87, 1168):
            return False
        raise NativeProcessError('MC_NATIVE_PROCESS_IDENTITY_UNAVAILABLE')
    try:
        if creation_ticks(kernel, handle) != identity['creation_ticks']:
            return False
        result = kernel.WaitForSingleObject(handle, 0)
        if result == 0xFFFFFFFF:
            raise ct.WinError(ct.get_last_error())
        return result == 258
    finally:
        kernel.CloseHandle(handle)


class NativeProcess:
    def __init__(self, kernel, handle, pid):
        self.kernel, self.handle, self.pid = kernel, handle, pid
        self.creation_ticks = creation_ticks(kernel, handle)
        self.created_at = self.creation_ticks / 10_000_000 - 11644473600

    def identity(self):
        return {'pid': self.pid, 'creation_ticks': self.creation_ticks}

    def poll(self):
        result = self.kernel.WaitForSingleObject(self.handle, 0)
        if result == 258:
            return None
        if result != 0:
            raise ct.WinError(ct.get_last_error())
        code = wt.DWORD()
        checked(self.kernel.GetExitCodeProcess(self.handle, ct.byref(code)))
        return code.value

    def close(self):
        if getattr(self, 'handle', None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def terminate(self):
        if self.poll() is None:
            checked(self.kernel.TerminateProcess(self.handle, 1))

    def wait(self, timeout=10):
        result = self.kernel.WaitForSingleObject(self.handle, int(timeout * 1000))
        if result == 258:
            raise NativeProcessError('MC_NATIVE_PROCESS_WAIT_TIMEOUT')
        if result != 0:
            raise ct.WinError(ct.get_last_error())
        return self.poll()

    def __del__(self):
        self.close()


class NativeJob:
    def __init__(self):
        self.kernel = api()
        self.handle = checked(self.kernel.CreateJobObjectW(None, None))
        try:
            self._limits(0x2000)  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        except BaseException:
            self.close()
            raise

    def _limits(self, flags):
        limits = EXTENDED_LIMIT()
        limits.BasicLimitInformation.LimitFlags = flags
        checked(self.kernel.SetInformationJobObject(self.handle, 9, ct.byref(limits), ct.sizeof(limits)))

    def spawn(self, command, *, cwd, env=None, stdout, stderr):
        """JOB_LIST assigns membership before any child instruction can execute.

        The explicit HANDLE_LIST inherits only duplicate stdin/out/err handles;
        neither the job nor any unrelated application handle is inherited.
        """
        return spawn_process(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr, job=self)

    def active(self):
        value = ACCOUNTING()
        checked(self.kernel.QueryInformationJobObject(self.handle, 1, ct.byref(value), ct.sizeof(value), None))
        return value.ActiveProcesses

    def members(self):
        """Retain exact member handles before termination; PID reuse is excluded."""
        capacity = 16
        while capacity <= 4096:
            buffer = ct.create_string_buffer(8 + ct.sizeof(ct.c_size_t) * capacity)
            ok = self.kernel.QueryInformationJobObject(self.handle, 3, buffer, ct.sizeof(buffer), None)
            error = ct.get_last_error()
            assigned = wt.DWORD.from_buffer(buffer, 0).value
            count = wt.DWORD.from_buffer(buffer, 4).value
            if not ok and error != 234:
                raise ct.WinError(error)
            if ok and count == assigned and count <= capacity:
                break
            capacity = max(capacity * 2, assigned)
        else:
            raise NativeProcessError('MC_NATIVE_PROCESS_FAMILY_MEMBER_LIMIT')
        processes = []
        try:
            identifiers = (ct.c_size_t * count).from_buffer(buffer, 8)
            for pid in identifiers:
                handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
                if not handle:
                    if ct.get_last_error() in (87, 1168):
                        continue
                    raise ct.WinError(ct.get_last_error())
                try:
                    member = wt.BOOL()
                    checked(self.kernel.IsProcessInJob(handle, self.handle, ct.byref(member)))
                    if member.value:
                        processes.append(NativeProcess(self.kernel, handle, pid))
                        handle = None
                finally:
                    if handle:self.kernel.CloseHandle(handle)
            return processes
        except BaseException:
            for process in processes:process.close()
            raise

    def rollback(self, timeout=15):
        deadline = time.monotonic() + timeout
        members = []
        try:
            try:
                members = self.members()
            finally:
                checked(self.kernel.TerminateJobObject(self.handle, 1))
            while self.active() or any(process.poll() is None for process in members):
                if time.monotonic() >= deadline:
                    raise NativeProcessError('MC_NATIVE_PROCESS_FAMILY_STILL_ALIVE')
                time.sleep(.02)
        finally:
            for process in members:process.close()

    def commit(self):
        self.prepare_commit()
        self.close()

    def prepare_commit(self, *, supervised=False):
        # A persistent supervisor holds the other handle after handoff. Its
        # unexpected exit must retain Windows' last-handle family cleanup.
        self._limits(0x2000 if supervised else 0)

    def close(self):
        if getattr(self, 'handle', None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def __del__(self):
        self.close()


def spawn_process(command, *, cwd, env=None, stdout, stderr, job=None, inherited_handles=()):
    """Create a hidden process with only explicitly supplied handles.

    A supervisor uses no owned-job assignment; service roots require JOB_LIST.
    """
    import msvcrt
    if not command or not Path(command[0]).is_absolute() or any('\0' in str(arg) for arg in command):
        raise NativeProcessError('MC_NATIVE_COMMAND_INVALID')
    kernel = job.kernel if job is not None else api()
    size = ct.c_size_t()
    count = 2 if job is not None else 1
    kernel.InitializeProcThreadAttributeList(None, count, 0, ct.byref(size))
    storage = ct.create_string_buffer(size.value)
    checked(kernel.InitializeProcThreadAttributeList(storage, count, 0, ct.byref(size)))
    duplicates = []
    info = PROCESS_INFORMATION()
    try:
        with open(os.devnull, 'rb') as null:
            for stream in (null, stdout, stderr):
                duplicate = wt.HANDLE()
                checked(kernel.DuplicateHandle(kernel.GetCurrentProcess(), msvcrt.get_osfhandle(stream.fileno()),
                    kernel.GetCurrentProcess(), ct.byref(duplicate), 0, True, 2))
                duplicates.append(duplicate.value)
        all_handles = duplicates + list(inherited_handles)
        handles = (wt.HANDLE * len(all_handles))(*all_handles)
        checked(kernel.UpdateProcThreadAttribute(storage, 0, 0x20002, handles, ct.sizeof(handles), None, None))
        if job is not None:
            jobs = (wt.HANDLE * 1)(job.handle)
            checked(kernel.UpdateProcThreadAttribute(storage, 0, 0x2000D, jobs, ct.sizeof(jobs), None, None))
        startup = STARTUPINFOEX()
        startup.StartupInfo.cb = ct.sizeof(startup)
        startup.StartupInfo.dwFlags = 0x100  # STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = duplicates
        startup.lpAttributeList = ct.addressof(storage)
        environment = None
        if env is not None:
            if any(not isinstance(k, str) or not isinstance(v, str) or not k or '=' in k
                   or '\0' in k or '\0' in v for k, v in env.items()):
                raise NativeProcessError('MC_NATIVE_ENVIRONMENT_INVALID')
            environment = ct.create_unicode_buffer('\0'.join(k + '=' + v for k, v in
                sorted(env.items(), key=lambda item: item[0].casefold())) + '\0\0')
        line = ct.create_unicode_buffer(subprocess.list2cmdline([str(arg) for arg in command]))
        checked(kernel.CreateProcessW(str(command[0]), line, None, None, True,
            0x80000 | 0x400 | 0x200 | 0x8000000, environment, str(cwd), ct.byref(startup), ct.byref(info)))
        try:
            process = NativeProcess(kernel, info.hProcess, info.dwProcessId)
            info.hProcess = None
            return process
        finally:
            if info.hThread:
                kernel.CloseHandle(info.hThread)
            if info.hProcess:
                kernel.CloseHandle(info.hProcess)
    finally:
        kernel.DeleteProcThreadAttributeList(storage)
        for handle in duplicates:
            kernel.CloseHandle(handle)

