import asyncio
import os
import time
import unittest
from unittest.mock import MagicMock,patch

from integration.issac.common import AdmissionError
from integration.issac.media_clock import MediaTimer,run_media


class TimerLifetime(unittest.TestCase):
    def test_one_owned_timer_is_released_exactly_once(self):
        library=MagicMock();library.timeBeginPeriod.return_value=0
        with patch('integration.issac.media_clock.os.name','nt'),patch('integration.issac.media_clock.ctypes.WinDLL',return_value=library):
            timer=MediaTimer();timer.start();timer.start();timer.close();timer.close()
        library.timeBeginPeriod.assert_called_once_with(1);library.timeEndPeriod.assert_called_once_with(1)

    def test_failed_acquisition_cannot_be_advertised_as_active(self):
        library=MagicMock();library.timeBeginPeriod.return_value=1
        with patch('integration.issac.media_clock.os.name','nt'),patch('integration.issac.media_clock.ctypes.WinDLL',return_value=library):
            timer=MediaTimer()
            with self.assertRaises(AdmissionError):timer.start()
            timer.close();self.assertFalse(timer.active)
        library.timeEndPeriod.assert_not_called()


@unittest.skipUnless(os.name=='nt','native Windows scheduling contract')
class PreciseLoopLifetime(unittest.TestCase):
    def test_asyncio_deadlines_use_the_performance_clock_and_policy_is_restored(self):
        previous=asyncio.get_event_loop_policy()
        async def serve():
            loop=asyncio.get_running_loop()
            self.assertLess(abs(loop.time()-time.perf_counter()),.01)
            self.assertLess(loop._clock_resolution,.000001)
            # A coarse monotonic clock must not be used for asyncio deadlines.
            started=time.perf_counter()
            await asyncio.sleep(.008)
            self.assertGreaterEqual(time.perf_counter()-started,.007)
            return loop
        with patch('integration.issac.media_clock.time.monotonic',return_value=0):
            loop=run_media(serve)
        self.assertTrue(loop.is_closed());self.assertIs(asyncio.get_event_loop_policy(),previous)

    def test_cleanup_and_policy_restoration_also_run_on_a_service_failure(self):
        previous=asyncio.get_event_loop_policy();closed=[]
        async def serve():
            async def child():
                try:await asyncio.Future()
                finally:closed.append(True)
            asyncio.create_task(child());await asyncio.sleep(0)
            raise RuntimeError('controlled service failure')
        with self.assertRaisesRegex(RuntimeError,'controlled service failure'):run_media(serve)
        self.assertEqual(closed,[True]);self.assertIs(asyncio.get_event_loop_policy(),previous)
