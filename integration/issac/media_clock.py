"""Own-process Windows scheduling; no foreign service or priority changes."""
import asyncio
import ctypes
import os
import time

from .common import AdmissionError


def new_media_loop():
    if os.name!='nt':raise AdmissionError('NATIVE_WINDOWS_MEDIA_CLOCK_REQUIRED')
    loop=asyncio.ProactorEventLoop()
    # Python 3.10's Windows monotonic clock is GetTickCount64. Its 15.625 ms
    # resolution also permits asyncio to release timers that much too early.
    # Use QPC for both deadline creation and timer lookahead in this process.
    loop.time=time.perf_counter
    loop._clock_resolution=time.get_clock_info('perf_counter').resolution
    return loop


def run_media(serve):
    if os.name!='nt':raise AdmissionError('NATIVE_WINDOWS_MEDIA_CLOCK_REQUIRED')
    class MediaPolicy(asyncio.WindowsProactorEventLoopPolicy):
        def new_event_loop(self):return new_media_loop()
    previous=asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(MediaPolicy())
    try:
        # Retain asyncio.run's cancellation, async-generator and executor cleanup.
        return asyncio.run(serve())
    finally:
        asyncio.set_event_loop_policy(previous)


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
