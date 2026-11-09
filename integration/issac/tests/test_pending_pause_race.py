"""An old pause waiter must not undo a completed explicit resume."""
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from integration.issac.strategy_host import StrategyHost


class PendingPauseRace(unittest.TestCase):
    def test_resume_wins_while_watchdog_waits_for_control_lock(self):
        host=object.__new__(StrategyHost)
        host.pause_pending=True;host.armed=False;host.last_fault=None
        host.stop_event=Mock();host.stop_event.wait.side_effect=[False,True]
        host.last_core_check=time.monotonic()
        host.native=Mock();host.audit=Mock();host.service=Mock()
        host.service.fresh.return_value=True
        host.runtime=SimpleNamespace(controller=SimpleNamespace(autopilot_enabled=True))
        class ResumeCompletesBeforeLock:
            def __enter__(self):host.pause_pending=False;host.armed=True
            def __exit__(self,*_):pass
        host.action_lock=ResumeCompletesBeforeLock()
        host.watchdog()
        host.native.pause.assert_not_called()
        self.assertTrue(host.armed);self.assertFalse(host.pause_pending)

    def test_current_disarmed_pending_request_still_gets_confirmed(self):
        import threading
        host=object.__new__(StrategyHost)
        host.pause_pending=True;host.armed=False;host.last_fault=None
        host.stop_event=Mock();host.stop_event.wait.side_effect=[False,True]
        host.action_lock=threading.RLock();host.native=Mock();host.audit=Mock()
        host.watchdog()
        host.native.pause.assert_called_once();self.assertFalse(host.pause_pending)

    def test_packet_recovery_before_control_lock_does_not_pause_fresh_run(self):
        host=object.__new__(StrategyHost)
        host.pause_pending=False;host.armed=True;host.last_fault=None
        host.stop_event=Mock();host.stop_event.wait.side_effect=[False,True]
        host.last_core_check=time.monotonic();host.native=Mock();host.audit=Mock();host.service=Mock()
        host.service.fresh.side_effect=[False,True]
        host.runtime=SimpleNamespace(controller=SimpleNamespace(autopilot_enabled=True))
        class PacketFinishesBeforeLock:
            def __enter__(self):pass
            def __exit__(self,*_):pass
        host.action_lock=PacketFinishesBeforeLock()
        host.watchdog()
        self.assertTrue(host.armed);self.assertIsNone(host.last_fault)
        host.native.pause.assert_not_called();host.service.configure.assert_not_called()


if __name__=='__main__':unittest.main()
