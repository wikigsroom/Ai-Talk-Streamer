"""Capture the Isaac window without taking the foreground from another app."""
import ctypes
from datetime import datetime
import json
from pathlib import Path
import time

from PIL import Image
import win32con
import win32gui
import win32ui

from desktop_game import ROOT, game_window


def main():
    hwnd, pid = game_window()
    before = win32gui.GetForegroundWindow()
    # OpenGL windows may keep returning a valid but stale PrintWindow bitmap.
    # Prefer the framebuffer captured on the identified game's render thread.
    identity_path = ROOT / "native-bridge-process.json"
    if identity_path.exists():
        import psutil
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        if identity.get("game_pid") == pid and abs(psutil.Process(pid).create_time()-identity.get("game_created_at",0)) < .01:
            from native_request import request
            frame = request(op="capture")
            if not frame.get("path"):
                raise RuntimeError("Native framebuffer capture did not return an image")
            print(json.dumps({"pid":pid,"screenshot":frame["path"],"capture_source":"native_framebuffer",
                "live_frame_verified":True,"foreground_unchanged":win32gui.GetForegroundWindow()==before}))
            return
    minimized = bool(win32gui.IsIconic(hwnd))
    if minimized:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
        time.sleep(0.5)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right-left, bottom-top
    window_dc = win32gui.GetWindowDC(hwnd)
    source_dc = win32ui.CreateDCFromHandle(window_dc)
    memory_dc = source_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source_dc, width, height)
    memory_dc.SelectObject(bitmap)
    try:
        ok = ctypes.windll.user32.PrintWindow(hwnd, memory_dc.GetSafeHdc(), 2)
        if not ok:
            raise RuntimeError("Background window capture failed")
        picture = Image.frombuffer("RGB", (width,height), bitmap.GetBitmapBits(True), "raw", "BGRX", 0, 1)
        target = ROOT / "screenshots" / f"{datetime.now():%Y%m%d_%H%M%S}-background-passive.png"
        picture.save(target)
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        memory_dc.DeleteDC()
        source_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)
        if minimized:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    print(json.dumps({"pid":pid,"screenshot":str(target),"capture_source":"window_bitmap",
        "live_frame_verified":False,"foreground_unchanged":win32gui.GetForegroundWindow()==before},ensure_ascii=True))


if __name__ == "__main__":
    main()
