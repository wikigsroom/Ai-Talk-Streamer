"""Native liveness requests can never stand in for a current game packet."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from integration.issac.common import AdmissionError
from integration.issac.native_game import NativeGame
from integration.issac.strategy_host import StrategyHost

class NativeObservationPulse(unittest.TestCase):
    def native(self,result):
        value=object.__new__(NativeGame);value.lock=threading.RLock();value.rpc=Mock(return_value=result)
        return value

    def test_rpc_ack_only_requests_a_packet_and_does_not_certify_freshness(self):
        value=self.native('observation_requested');receipt=value.refresh_observation()
        self.assertFalse(receipt['freshness_proved']);self.assertTrue(receipt['observation_requested'])
        self.assertEqual(value.rpc.call_args.kwargs['timeout'],.2)

    def test_missing_controller_or_live_player_is_not_a_success(self):
        for result in ['not_installed','no_live_player',None]:
            with self.assertRaises(AdmissionError):self.native(result).refresh_observation()

    def host(self,age=.8):
        host=object.__new__(StrategyHost);host.armed=True;host.native=Mock();host.audit=Mock()
        host.service=SimpleNamespace(received=100.0,clock=lambda:100+age)
        return host

    def test_quiet_window_requests_only_a_native_snapshot_without_changing_received(self):
        host=self.host()
        with patch('integration.issac.strategy_host.time.monotonic',return_value=10):host.refresh_quiet_observation()
        host.native.refresh_observation.assert_called_once_with()
        self.assertEqual(host.service.received,100.0);self.assertTrue(host.armed)

    def test_regular_packets_and_operator_pause_never_need_a_pulse(self):
        for age,armed in [(.1,True),(.8,False),(1.25,True),(1.6,True)]:
            host=self.host(age);host.armed=armed;host.refresh_quiet_observation()
            host.native.refresh_observation.assert_not_called()

    def test_requests_are_rate_limited_independently_of_the_packet_deadline(self):
        host=self.host()
        with patch('integration.issac.strategy_host.time.monotonic',side_effect=[10,10.2,10.41]):
            host.refresh_quiet_observation();host.refresh_quiet_observation();host.refresh_quiet_observation()
        self.assertEqual(host.native.refresh_observation.call_count,2)
        self.assertEqual(host.service.received,100.0)

    def test_pulse_error_has_finite_diagnostic_and_cannot_rearm_or_extend_state(self):
        host=self.host();host.native.refresh_observation.side_effect=TimeoutError('private diagnostic')
        host.refresh_quiet_observation()
        self.assertEqual(host.service.received,100.0);self.assertTrue(host.armed)
        self.assertNotIn('private diagnostic',str(host.audit.append.call_args))
        self.assertEqual(host.audit.append.call_args.kwargs['exception_type'],'TimeoutError')

    def watch(self,host):
        import time
        host.pause_pending=False;host.last_fault=None;host.control_revision=1;host.last_core_check=time.monotonic()
        host.stop_event=Mock();host.stop_event.wait.side_effect=[False,True]
        host.action_lock=threading.RLock()
        host.runtime=SimpleNamespace(controller=SimpleNamespace(autopilot_enabled=True,set_autopilot=Mock(),packet_status=lambda:{}))
        host.strategy_automatic=Mock();host.service.configure=Mock()
        host.service.fresh=lambda:host.service.clock()-host.service.received<1.5
        host.service.native_engine_hold_grace=lambda:False
        host.watchdog()

    def test_previous_rpc_success_without_a_real_packet_cannot_prevent_stale_stop(self):
        host=self.host();host.refresh_quiet_observation()
        host.service.clock=lambda:101.6
        self.watch(host)
        self.assertFalse(host.armed);self.assertEqual(host.last_fault,'GAME_BRIDGE_STALE')
        host.native.pause.assert_called_once();self.assertEqual(host.service.received,100.0)

    def test_new_actual_packet_from_the_exchange_removes_the_gap(self):
        host=self.host()
        host.native.refresh_observation.side_effect=lambda:setattr(host.service,'received',host.service.clock())
        self.watch(host)
        self.assertTrue(host.armed);self.assertIsNone(host.last_fault);host.native.pause.assert_not_called()
