"""An old pause waiter must not undo a completed explicit resume."""
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from integration.issac.strategy_host import StrategyHost


class PendingPauseRace(unittest.TestCase):
    def test_resume_wins_while_watchdog_waits_for_control_lock(self):
        host=object.__new__(StrategyHost)
        host.pause_pending=True;host.armed=False;host.last_fault=None;host.control_revision=1
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
        host.pause_pending=True;host.armed=False;host.last_fault=None;host.control_revision=1
        host.stop_event=Mock();host.stop_event.wait.side_effect=[False,True]
        host.action_lock=threading.RLock();host.native=Mock();host.audit=Mock()
        host.watchdog()
        host.native.pause.assert_called_once();self.assertFalse(host.pause_pending)

    def test_packet_recovery_before_control_lock_does_not_pause_fresh_run(self):
        host=object.__new__(StrategyHost)
        host.pause_pending=False;host.armed=True;host.last_fault=None;host.control_revision=1
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

    def make_armed(self, before_lock=lambda h:None):
        host=object.__new__(StrategyHost)
        host.pause_pending=False;host.armed=True;host.last_fault=None;host.control_revision=3
        host.last_core_check=time.monotonic();host.native=Mock();host.audit=Mock();host.service=Mock()
        host.service.fresh.return_value=True
        host.stop_event=Mock();host.stop_event.wait.side_effect=[False,True]
        host.runtime=SimpleNamespace(controller=SimpleNamespace(autopilot_enabled=True))
        host.control=Mock(side_effect=lambda _:setattr(host,'armed',False))
        class OwnerCompletesBeforeLock:
            def __enter__(self):before_lock(host)
            def __exit__(self,*_):pass
        host.action_lock=OwnerCompletesBeforeLock()
        return host

    def test_terminal_observation_during_owned_pause_does_not_increment_revision(self):
        def pause_done(h):h.armed=False;h.control_revision=4
        host=self.make_armed(pause_done)
        host.runtime.controller.autopilot_enabled=False
        host.watchdog()
        host.control.assert_not_called();self.assertEqual(host.control_revision,4)
        self.assertIsNone(host.last_fault)

    def test_terminal_observation_from_prior_resume_does_not_stop_new_revision(self):
        def resume_done(h):h.control_revision=4;h.runtime.controller.autopilot_enabled=True
        host=self.make_armed(resume_done)
        host.runtime.controller.autopilot_enabled=False
        host.watchdog()
        host.control.assert_not_called();self.assertTrue(host.armed)

    def test_current_terminal_still_withdraws_authority(self):
        host=self.make_armed();host.runtime.controller.autopilot_enabled=False
        host.watchdog()
        host.control.assert_called_once_with({'enabled':False,'live':False})
        self.assertFalse(host.armed)

    def test_old_core_response_cannot_pause_a_new_control_revision(self):
        import io
        host=self.make_armed(lambda h:setattr(h,'control_revision',4));host.last_core_check=0
        opener=Mock();opener.open.return_value=io.BytesIO(b'{"ready":true,"automatic":false,"actor_id":"naimei"}')
        with patch('integration.issac.strategy_host.urllib.request.build_opener',return_value=opener):host.watchdog()
        host.control.assert_not_called();self.assertIsNone(host.last_fault);self.assertTrue(host.armed)

    def test_current_core_loss_still_withdraws_authority(self):
        host=self.make_armed();host.last_core_check=0
        with patch('integration.issac.strategy_host.urllib.request.build_opener',side_effect=OSError):host.watchdog()
        host.control.assert_called_once_with({'enabled':False,'live':False})
        self.assertFalse(host.armed);self.assertEqual(host.last_fault,'NAIMEI_CORE_UNAVAILABLE')

    def test_core_timeout_has_finite_diagnostic_and_keeps_original_stop(self):
        host=self.make_armed();host.last_core_check=0
        with patch('integration.issac.strategy_host.urllib.request.build_opener',side_effect=TimeoutError('private message')):host.watchdog()
        event,=host.audit.append.call_args.args
        detail=host.audit.append.call_args.kwargs
        self.assertEqual(event,'core_loss_stop');self.assertEqual(detail['check_error'],'TimeoutError')
        self.assertNotIn('private message',str(detail));self.assertGreaterEqual(detail['elapsed_ms'],0)
        host.control.assert_called_once_with({'enabled':False,'live':False})

    def test_unhealthy_core_response_is_distinct_from_http_timeout(self):
        import io
        host=self.make_armed();host.last_core_check=0
        opener=Mock();opener.open.return_value=io.BytesIO(b'{"ready":true,"automatic":false,"actor_id":"naimei","failures":1,"last_error":"CORE_TURN_DID_NOT_SUBMIT_A_CHOICE"}')
        with patch('integration.issac.strategy_host.urllib.request.build_opener',return_value=opener):host.watchdog()
        detail=host.audit.append.call_args.kwargs
        self.assertIsNone(detail['check_error']);self.assertEqual(detail['core']['failures'],1)
        self.assertEqual(detail['core']['last_error'],'CORE_TURN_DID_NOT_SUBMIT_A_CHOICE')
        self.assertFalse(host.armed)

    def test_old_protection_failure_does_not_stop_a_new_revision(self):
        host=self.make_armed(lambda h:setattr(h,'control_revision',4))
        host.native.protection.admit_current.side_effect=RuntimeError
        host.watchdog()
        host.control.assert_not_called();self.assertIsNone(host.last_fault);self.assertTrue(host.armed)

    def test_current_protection_failure_still_withdraws_authority(self):
        host=self.make_armed();host.native.protection.admit_current.side_effect=RuntimeError
        host.watchdog()
        host.control.assert_called_once_with({'enabled':False,'live':False})
        self.assertFalse(host.armed);self.assertEqual(host.last_fault,'SLOT_OR_NATIVE_IDENTITY_CHANGED')


if __name__=='__main__':unittest.main()
