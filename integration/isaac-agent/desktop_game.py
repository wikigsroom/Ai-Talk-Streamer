"""Native fallback for observing and pressing menu keys in the Isaac window only."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
from pathlib import Path
import time

from PIL import ImageGrab
import psutil
import win32con
import win32gui
import win32process


ROOT = Path(__file__).resolve().parent
INSTALL = json.loads((ROOT / "game-install.json").read_text(encoding="utf-8"))
GAME_EXE = Path(INSTALL["game_root"]) / INSTALL["executable"]
KEYS = {"enter": 0x0D, "escape": 0x1B, "left": 0x25, "up": 0x26,
        "right": 0x27, "down": 0x28, "space": 0x20, "f8": 0x77}
user32 = ctypes.windll.user32


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", wintypes.DWORD), ("value", INPUTUNION)]


def game_window(include_hidden: bool = False) -> tuple[int, int]:
    found = []

    def visit(hwnd: int, _extra: object) -> None:
        if not include_hidden and not win32gui.IsWindowVisible(hwnd):
            return
        _thread, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            executable = Path(psutil.Process(pid).exe())
        except (psutil.Error, OSError):
            return
        if executable == GAME_EXE and "Binding of Isaac" in win32gui.GetWindowText(hwnd):
            found.append((hwnd, pid))

    win32gui.EnumWindows(visit, None)
    if len(found) != 1:
        raise RuntimeError(f"Expected one visible Isaac game window; found {len(found)}")
    return found[0]


def activate(hwnd: int) -> None:
    current = win32gui.GetForegroundWindow()
    if current:
        _thread, pid = win32process.GetWindowThreadProcessId(current)
        if psutil.Process(pid).name().lower() in {"lockapp.exe", "logonui.exe"}:
            raise RuntimeError("Desktop is locked; no input was sent")
    if not win32gui.IsWindowVisible(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    if current != hwnd:
        win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    if win32gui.GetForegroundWindow() != hwnd:
        raise RuntimeError("Isaac could not be foregrounded; no input was sent")


def press(hwnd: int, name: str) -> None:
    if win32gui.GetForegroundWindow() != hwnd:
        raise RuntimeError("Foreground window changed; no input was sent")
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    key = KEYS[name]
    down = INPUT(type=1, ki=KEYBDINPUT(wVk=key))
    up = INPUT(type=1, ki=KEYBDINPUT(wVk=key, dwFlags=2))
    if user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT)) != 1:
        raise RuntimeError("Key-down injection failed")
    time.sleep(0.09)
    if user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT)) != 1:
        raise RuntimeError("Key-up injection failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", choices=KEYS)
    parser.add_argument("--label", default="observe")
    parser.add_argument("--close", action="store_true", help="Close only the selected game window normally")
    args = parser.parse_args()
    if not args.label.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("Invalid screenshot label")
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass
    hwnd, pid = game_window(include_hidden=True)
    if args.close:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        print(json.dumps({"pid": pid, "close_requested": True}))
        return
    activate(hwnd)
    if args.key:
        press(hwnd, args.key)
        time.sleep(0.8)
    rect = win32gui.GetWindowRect(hwnd)
    # Read the game surface even if another app covers the window meanwhile.
    import win32ui
    from PIL import Image
    width, height = rect[2] - rect[0], rect[3] - rect[1]
    window_dc = win32gui.GetWindowDC(hwnd)
    source_dc = win32ui.CreateDCFromHandle(window_dc)
    memory_dc = source_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source_dc, width, height)
    memory_dc.SelectObject(bitmap)
    try:
        if not user32.PrintWindow(hwnd, memory_dc.GetSafeHdc(), 2):
            raise RuntimeError("Game window capture failed")
        image = Image.frombuffer("RGB", (width, height), bitmap.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        memory_dc.DeleteDC()
        source_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)
    target = ROOT / "screenshots" / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}-{args.label}.png"
    target.parent.mkdir(exist_ok=True)
    image.save(target)
    print(json.dumps({"pid": pid, "window": hwnd, "title": win32gui.GetWindowText(hwnd),
                      "key": args.key, "rect": rect, "screenshot": str(target)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
