"""Verified native clicks for the signed client's unlabelled local-record icon.

This version exposes no UIA recording button. The fixed geometry and actual
visible icon must both match a reviewed binding before any ordinary mouse input.
No caller can supply coordinates, key presses, images, or an alternate window.
"""
from __future__ import annotations

from pathlib import Path

from .common import AdmissionError, FileLease, file_hash, inside, read_json


def geometry(rect, dpi, binding):
    left, top, right, bottom = rect
    if (right-left, bottom-top) != tuple(binding['window_size']) or dpi != binding['dpi']:
        raise AdmissionError('REVIEWED_OFFICIAL_RECORD_GEOMETRY_REQUIRED')
    box = binding['icon_box']
    point = binding['click_point']
    # This reviewed area is separate from the public broadcast button. Reject
    # changed bindings, including a modified width that moves that button here.
    if box != [805, 860, 829, 884] or point != [817, 872]:
        raise AdmissionError('FIXED_LOCAL_RECORD_ICON_ONLY')
    return tuple((left if i % 2 == 0 else top)+v for i, v in enumerate(box)), (left+point[0], top+point[1])


def verify_icon(actual, expected):
    from PIL import ImageChops, ImageStat
    if actual.size != (24, 24) or expected.size != (24, 24):
        raise AdmissionError('REVIEWED_RECORD_ICON_SIZE_REQUIRED')
    diff = ImageStat.Stat(ImageChops.difference(actual.convert('RGB'), expected.convert('RGB')))
    if max(diff.mean) > 5 or max(diff.rms) > 15:
        raise AdmissionError('VISIBLE_LOCAL_RECORD_ICON_NOT_CONFIRMED')


def writers(client):
    """Read actual handles once per process, restricted to this owned client."""
    import psutil
    owner = client.owner()
    parent = psutil.Process(owner['pid'])
    raw = inside(client.root, 'outputs/issac/recordings/raw')
    result = []
    for process in [parent, *parent.children(recursive=True)]:
        try:
            executable = Path(process.exe()).resolve()
            if not executable.is_relative_to(client.executable.parent):
                continue
            for opened in process.open_files():
                path = Path(opened.path).resolve()
                if path.is_relative_to(raw) and path.suffix.lower() in {'.mp4', '.mkv', '.flv', '.mov'}:
                    result.append({'path': path.relative_to(client.root).as_posix(), 'pid': process.pid,
                                   'created_at': process.create_time(), 'method': 'native_process_open_file_handle'})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def operate(client, action):
    if action not in {'record-start', 'record-stop'}:
        raise AdmissionError('LOCAL_RECORD_ACTION_REQUIRED')
    import ctypes
    import win32api
    import win32con
    import win32gui
    from PIL import Image, ImageGrab

    owner = client.owner()
    binding = read_json(inside(client.root, 'configs/issac/official-record-control.json'))
    if binding['application_sha256'] != owner['executable_sha256']:
        raise AdmissionError('REVIEWED_SIGNED_OFFICIAL_VERSION_REQUIRED')
    template = binding['icons'][action]
    path = inside(client.root, template['path'])
    if file_hash(path) != template['sha256']:
        raise AdmissionError('REVIEWED_RECORD_ICON_CHANGED')
    with FileLease(inside(client.root, 'state/issac-stream/official-record-ui.lock')):
        observed = client.native_window('windows')['windows']
        if len(observed) != 1:
            raise AdmissionError('ONE_VISIBLE_OWNED_OFFICIAL_WINDOW_REQUIRED')
        window = observed[0]
        hwnd = window['hwnd']
        get_dpi = ctypes.windll.user32.GetDpiForWindow
        get_dpi.argtypes = [ctypes.c_void_p]
        get_dpi.restype = ctypes.c_uint
        dpi = get_dpi(hwnd)
        box, point = geometry(window['rect'], dpi, binding)

        def owned_foreground():
            foreground = win32gui.GetForegroundWindow()
            return foreground == hwnd or bool(foreground and win32gui.GetAncestor(foreground, 3) == hwnd)

        if not owned_foreground():
            raise AdmissionError('BRING_OWNED_OFFICIAL_CLIENT_TO_FRONT_FOR_LOCAL_RECORDING')
        active = writers(client)
        paths = {row['path'] for row in active}
        if action == 'record-start' and paths:
            raise AdmissionError('EXISTING_OFFICIAL_RECORDING_LEFT_UNCHANGED')
        if action == 'record-stop' and len(paths) != 1:
            raise AdmissionError('ONE_ACTUAL_OWNED_RECORDING_WRITER_REQUIRED_TO_STOP')
        actual = ImageGrab.grab(bbox=box, all_screens=True, include_layered_windows=True)
        with Image.open(path) as expected:
            verify_icon(actual, expected)
        if not owned_foreground() or list(win32gui.GetWindowRect(hwnd)) != window['rect']:
            raise AdmissionError('OFFICIAL_FOREGROUND_OR_GEOMETRY_CHANGED')
        previous = win32gui.GetCursorPos()
        win32api.SetCursorPos(point)
        hit = win32gui.WindowFromPoint(point)
        if hit != hwnd and win32gui.GetAncestor(hit, 3) != hwnd:
            raise AdmissionError('LOCAL_RECORD_ICON_OCCLUDED')
        if not owned_foreground():
            raise AdmissionError('OFFICIAL_FOREGROUND_CHANGED_BEFORE_RECORD_CLICK')
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        if win32gui.GetCursorPos() == point:
            win32api.SetCursorPos(previous)
        return {'action': action, 'process_id': owner['pid'], 'invoked': True,
                'method': 'reviewed_visible_native_local_record_icon', 'template_sha256': template['sha256'],
                'actual_recording_writers_before_click': active, 'writer_confirmation_still_required': True,
                'public_broadcast_started': False}
