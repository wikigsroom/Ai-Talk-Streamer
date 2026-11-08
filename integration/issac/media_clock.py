"""Own-process Windows timer lease; no global service or priority changes."""
import ctypes
import os

from .common import AdmissionError


class MediaTimer:
    def __init__(self):
        self.active=False

    def start(self):
        if self.active:return
        if os.name!='nt':raise AdmissionError('NATIVE_WINDOWS_MEDIA_CLOCK_REQUIRED')
        self.library=ctypes.WinDLL('winmm')
        if self.library.timeBeginPeriod(1)!=0:raise AdmissionError('MEDIA_TIMER_NOT_ACQUIRED')
        self.active=True

    def close(self):
        if self.active:
            self.library.timeEndPeriod(1)
            self.active=False
