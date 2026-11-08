import unittest
from unittest.mock import MagicMock,patch

from integration.issac.common import AdmissionError
from integration.issac.media_clock import MediaTimer


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
