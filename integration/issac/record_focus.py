"""Keep the proven owned game foreground between local-record UI operations.

Isaac's protected PauseOnFocusLost option is deliberately left unchanged.
Changing focus does not resume or rearm a normal operator/fault pause.
"""
from contextlib import contextmanager
import ctypes
from pathlib import Path

from .common import AdmissionError,file_hash,inside,read_json
from .saves import GAME_SHA256


def game_owner(root):
    import psutil
    row=read_json(inside(root,'state/isaac-strategy/native-session.json'))
    process=psutil.Process(row['game_pid']);executable=inside(root,'game/isaac-ng.exe')
    if (process.create_time()!=row['game_created_at'] or Path(process.exe()).resolve()!=executable
            or row.get('game_sha256')!=GAME_SHA256 or file_hash(executable)!=GAME_SHA256):
        raise AdmissionError('CURRENT_OWNED_GAME_FOCUS_IDENTITY_REQUIRED')
    return process


def foreground(hwnd,pid):
    u=ctypes.windll.user32
    u.GetForegroundWindow.restype=ctypes.c_void_p
    u.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    u.SetForegroundWindow.argtypes=[ctypes.c_void_p]
    actual=ctypes.c_ulong();u.GetWindowThreadProcessId(hwnd,ctypes.byref(actual))
    if actual.value!=pid:raise AdmissionError('OWNED_FOCUS_WINDOW_CHANGED')
    if u.GetForegroundWindow()!=hwnd and not u.SetForegroundWindow(hwnd):
        raise AdmissionError('OWNED_WINDOW_FOREGROUND_NOT_CONFIRMED')
    if u.GetForegroundWindow()!=hwnd:raise AdmissionError('OWNED_WINDOW_FOREGROUND_NOT_CONFIRMED')
    return {'pid':pid,'hwnd':hwnd,'foreground':True,'game_control_changed':False}


def game_foreground(root):
    process=game_owner(root);u=ctypes.windll.user32;windows=[]
    u.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    u.IsWindowVisible.argtypes=[ctypes.c_void_p]
    @ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_ssize_t)
    def each(hwnd,_):
        pid=ctypes.c_ulong();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value==process.pid and u.IsWindowVisible(hwnd):windows.append(hwnd)
        return True
    u.EnumWindows(each,0)
    if len(windows)!=1:raise AdmissionError('UNIQUE_OWNED_GAME_FOCUS_WINDOW_REQUIRED')
    game_owner(root) # Recheck PID lifetime immediately before changing focus.
    return foreground(windows[0],process.pid)


@contextmanager
def record_controls(client):
    game=game_owner(client.root);owner=client.owner()
    windows=client.native_window('windows')['windows']
    if len(windows)!=1:raise AdmissionError('ONE_VISIBLE_OWNED_OFFICIAL_WINDOW_REQUIRED')
    window=windows[0]
    try:
        foreground(window['hwnd'],window['pid'])
        yield
    finally:
        current=game_owner(client.root)
        if current.pid!=game.pid or current.create_time()!=game.create_time():
            raise AdmissionError('GAME_FOCUS_OWNER_CHANGED_DURING_RECORD_CONTROL')
        game_foreground(client.root)
