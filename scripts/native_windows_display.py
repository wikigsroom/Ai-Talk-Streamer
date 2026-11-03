"""Thread-scoped display requirement for an owned native media/game service.

No global power-plan edits, synthetic input, system/away-mode request or focus change.
"""
import ctypes
from ctypes import wintypes as wt
from datetime import datetime, timezone
import os
import threading
import time

ES_CONTINUOUS = 0x80000000
ES_DISPLAY_REQUIRED = 0x00000002
DISPLAY_REFRESH_SECONDS = 5


def _native_setter():
    if os.name != 'nt':
        raise RuntimeError('NATIVE_DISPLAY_REQUIRES_WINDOWS')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    call = kernel.SetThreadExecutionState
    call.argtypes = [wt.DWORD]
    call.restype = wt.DWORD
    return call


class NativeDisplayLease:
    def __init__(self, setter=None, *, clock=time.monotonic):
        self._setter = setter
        self._clock = clock
        self._thread = None
        self._previous = None
        self._active = False
        self._acquired_at = None
        self._released_at = None
        self._last_refresh_attempt = None
        self._last_refresh_at = None
        self._refresh_count = 0
        self._refresh_failures = 0
        self._last_refresh_error = None

    def acquire(self):
        if self._active:
            raise RuntimeError('NATIVE_DISPLAY_ALREADY_REQUIRED')
        call = self._setter if self._setter is not None else _native_setter()
        previous = int(call(ES_CONTINUOUS | ES_DISPLAY_REQUIRED))
        if not previous:
            raise RuntimeError('NATIVE_DISPLAY_REQUEST_FAILED')
        self._setter = call
        self._previous = previous
        self._thread = threading.get_ident()
        self._active = True
        self._released_at = None
        self._acquired_at = datetime.now(timezone.utc).isoformat()
        self._last_refresh_attempt = self._clock()
        self._last_refresh_at = None
        self._refresh_count = 0
        self._refresh_failures = 0
        self._last_refresh_error = None
        return self

    def refresh(self):
        """Attempt an idle-timer reset when due; return whether proof changed.

        A failed reset is recorded and retried after the same interval. It must
        not terminate a live survival world merely because display refresh failed.
        The original thread requirements remain the release target.
        """
        if not self._active:
            raise RuntimeError('NATIVE_DISPLAY_NOT_ACTIVE')
        if threading.get_ident() != self._thread:
            raise RuntimeError('NATIVE_DISPLAY_WRONG_THREAD')
        now = self._clock()
        if now - self._last_refresh_attempt < DISPLAY_REFRESH_SECONDS:
            return False
        self._last_refresh_attempt = now
        if not self._setter(ES_DISPLAY_REQUIRED):
            self._refresh_failures += 1
            self._last_refresh_error = 'NATIVE_DISPLAY_REFRESH_FAILED'
            return True
        self._refresh_count += 1
        self._last_refresh_at = datetime.now(timezone.utc).isoformat()
        self._last_refresh_error = None
        return True

    def release(self):
        if not self._active:
            return
        if threading.get_ident() != self._thread:
            raise RuntimeError('NATIVE_DISPLAY_WRONG_THREAD')
        if not self._setter(self._previous | ES_CONTINUOUS):
            raise RuntimeError('NATIVE_DISPLAY_RELEASE_FAILED')
        self._active = False
        self._released_at = datetime.now(timezone.utc).isoformat()

    def proof(self):
        return {'scope': 'owned_minecraft_service_thread', 'active': self._active,
                'requested_flags': ES_CONTINUOUS | ES_DISPLAY_REQUIRED,
                'previous_thread_flags': self._previous, 'acquired_at': self._acquired_at,
                'released_at': self._released_at, 'power_plan_changed': False,
                'input_actions_issued': 0, 'refresh_interval_seconds': DISPLAY_REFRESH_SECONDS,
                'refresh_count': self._refresh_count, 'last_refresh_at': self._last_refresh_at,
                'refresh_failures': self._refresh_failures, 'last_refresh_error': self._last_refresh_error}

    def __enter__(self):
        return self.acquire()

    def __exit__(self, kind, error, trace):
        self.release()
