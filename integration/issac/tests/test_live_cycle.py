"""Exercise cross-run ownership, ordinary retry and bounded fault recovery."""
from copy import deepcopy
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

from integration.issac.common import AdmissionError
from integration.issac.live_cycle import LiveCycle
from integration.issac.live_supervisor import SupervisorState, LiveSupervisor, operator_paused


class LiveCycleTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.identity = {'controller': 'owner', 'seed': 123, 'restart': 0, 'bridge': 'old',
                         'room': 1, 'stage': 1}
        service = SimpleNamespace(snapshot={'identity': deepcopy(self.identity), 'frame': 20,
            'room': {'dead': False, 'paused': False}}, raw={'strategy': {}}, lock=threading.RLock(),
            fresh=Mock(return_value=True), configure=Mock())
        self.host = SimpleNamespace(service=service, audit=Mock(), native=Mock(), armed=True,
            pause_pending=False, last_fault=None, runtime=SimpleNamespace(controller=SimpleNamespace(
                set_autopilot=Mock(), terminal_receipt=None)), strategy_automatic=Mock(),
            control=Mock(return_value={'armed': True}), core_status=Mock(return_value={'ready': True}),
            approved_core=Mock(return_value=True), live_media_ready=Mock(return_value=True), watchdog_stop=Mock())
        self.living = {'players': 1, 'dead': False, 'hp': 6, 'seed': 123, 'paused': False, 'frame': 20}
        self.host.native.observe.return_value = deepcopy(self.living)
        self.cycle = LiveCycle(self.host, clock=lambda: self.now)
        self.cycle.start()

    def proof(self, **overrides):
        return {'callback': 'MC_POST_GAME_END', 'is_game_over': True, 'start_seed': 123,
                'bridge_generation': 'old', 'restart_count': 0, **overrides}

    def end(self, victory=False):
        self.host.native.observe.return_value = {**self.living, 'dead': not victory, 'hp': 6 if victory else 0}
        self.host.runtime.controller.terminal_receipt = self.proof(is_game_over=not victory)
        self.assertTrue(self.cycle.tick())
        self.assertEqual(self.cycle.phase, 'terminal_reaction')

    def test_death_withdraws_gameplay_but_does_not_cancel_terminal_voice(self):
        self.end()
        self.assertFalse(self.host.armed)
        self.host.runtime.controller.set_autopilot.assert_called_with(False)
        self.host.service.configure.assert_called_with(enabled=False, live=False)
        self.host.strategy_automatic.assert_not_called()
        self.host.native.menu_key.assert_not_called()

    def test_successful_ending_uses_real_callback_even_while_player_is_alive(self):
        self.end(victory=True)
        self.assertEqual(self.cycle.terminal['result'], 'ending')
        self.now += 10
        self.cycle.tick()
        self.host.native.menu_key.assert_called_once_with('space')
        self.assertFalse(self.host.armed)

    def test_old_or_forged_terminal_cannot_authorize_retry(self):
        for overrides in ({'start_seed': 999}, {'bridge_generation': 'prior'},
                          {'restart_count': 1}, {'is_game_over': 'true'}, {'callback': 'fake'}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(AdmissionError):
                    self.cycle.hold_terminal(self.proof(**overrides))
        self.host.native.menu_key.assert_not_called()

    def test_only_bounded_ordinary_space_is_issued_after_reaction(self):
        self.end()
        self.now += 9
        self.cycle.tick()
        self.host.native.menu_key.assert_not_called()
        for _ in range(5):
            self.now += 3
            self.cycle.tick()
        self.assertEqual(self.host.native.menu_key.call_count, 5)
        self.now += 3
        self.cycle.tick()
        self.assertEqual(self.cycle.phase, 'restart_required')
        self.assertFalse(self.cycle.enabled)

    def test_operator_stop_cancels_retry_and_recovery_without_any_key(self):
        self.end()
        self.cycle.stop()
        self.now += 40
        self.assertFalse(self.cycle.tick())
        self.host.native.menu_key.assert_not_called()
        self.host.control.assert_not_called()

    def test_new_seed_rebinds_native_then_waits_for_actual_fresh_packet(self):
        self.end()
        self.now += 10
        self.host.native.observe.return_value = {**self.living, 'seed': 456}
        self.cycle.tick()
        self.host.native.install_controller.assert_called_once_with()
        self.assertEqual(self.cycle.phase, 'binding_new_run')
        self.host.control.assert_not_called()
        self.now += 1
        self.cycle.tick()
        self.host.control.assert_not_called()
        self.host.service.snapshot['identity'] = {**self.identity, 'seed': 456, 'bridge': 'new'}
        self.now += 1
        self.cycle.tick()
        self.host.control.assert_called_once_with({'enabled': True, 'live': True}, origin='lifecycle')
        self.assertEqual(self.cycle.phase, 'playing')
        self.assertEqual(self.cycle.completed_runs, 1)
        self.assertEqual(self.cycle.last_new_run['previous_seed'], 123)
        self.assertIsNone(self.host.runtime.controller.terminal_receipt)

    def test_actual_resurrection_never_receives_a_new_run_key(self):
        self.end()
        self.host.native.observe.return_value = deepcopy(self.living)
        self.now += 10
        self.cycle.tick()
        self.host.native.menu_key.assert_not_called()
        self.assertEqual(self.cycle.phase, 'playing')

    def test_protected_slot_failure_prevents_every_input_and_keeps_watchdog_alive(self):
        self.end()
        self.now += 10
        self.host.native.protection.admit_current.side_effect = AdmissionError('CHANGED')
        self.assertTrue(self.cycle.tick())
        self.assertEqual(self.cycle.phase, 'restart_required')
        self.host.native.menu_key.assert_not_called()

    def test_confirmed_death_without_callback_has_bounded_fallback(self):
        self.host.service.snapshot['room']['dead'] = True
        self.host.native.observe.return_value = {**self.living, 'dead': True, 'hp': 0}
        self.cycle.tick()
        self.now += 3
        self.cycle.tick()
        self.assertEqual(self.cycle.phase, 'terminal_reaction')
        self.assertTrue(self.cycle.terminal['observed_dead'])

    def owned_fault(self):
        self.host.armed = False
        self.host.native.observe.return_value = {**self.living, 'paused': True}
        self.host.service.raw['strategy']['pause_ack'] = {'id': 'owned'}
        self.cycle.fault('NAIMEI_CORE_UNAVAILABLE', {'normal_game_pause_acknowledged': True,
            'stable_frame': 20, 'pause_input_ack': {'id': 'owned'}})
        self.now += 2

    def test_transient_recovery_requires_original_pause_identity(self):
        self.owned_fault()
        self.cycle.tick()
        self.host.control.assert_called_once_with({'enabled': True, 'live': True}, origin='lifecycle')
        self.assertEqual(self.cycle.phase, 'playing')

    def test_manual_intervention_or_new_run_cannot_be_auto_resumed(self):
        for mutation in ('pause_id', 'frame', 'seed', 'override'):
            with self.subTest(mutation=mutation):
                self.setUp()
                self.owned_fault()
                if mutation == 'pause_id':
                    self.host.service.raw['strategy']['pause_ack']['id'] = 'operator'
                elif mutation == 'frame':
                    self.host.native.observe.return_value['frame'] = 21
                elif mutation == 'seed':
                    self.host.native.observe.return_value['seed'] = 124
                else:
                    self.host.service.raw['strategy']['manual_override'] = True
                self.cycle.tick()
                self.host.control.assert_not_called()
                self.assertEqual(self.cycle.phase, 'restart_required')

    def test_auth_budget_and_model_mismatch_are_not_retried(self):
        for error in ('MODEL_AUTH_FAILED', 'MODEL_CONTEXT_EXCEEDED', 'STREAM_CONTEXT_BUDGET'):
            self.setUp()
            self.owned_fault()
            self.host.core_status.return_value = {'ready': True, 'last_error': error}
            self.cycle.tick()
            self.assertEqual(self.cycle.phase, 'restart_required')
            self.host.control.assert_not_called()

    def test_offline_core_observation_retries_have_a_finite_budget(self):
        self.owned_fault()
        self.host.core_status.side_effect = TimeoutError
        for _ in range(4):
            self.cycle.tick()
            self.now += 16
        self.assertEqual(self.cycle.phase, 'restart_required')
        self.assertEqual(self.cycle.recovery_attempts, 3)

    def test_repeated_successful_recoveries_still_open_the_circuit(self):
        for _ in range(4):
            self.owned_fault()
            self.cycle.tick()
        self.assertEqual(self.cycle.reason, 'REPEATED_LIVE_FAULT_CIRCUIT_OPEN')
        self.assertFalse(self.cycle.enabled)

    def test_manual_pause_is_not_undone_after_fifteen_seconds(self):
        self.host.service.snapshot['room']['paused'] = True
        self.cycle.tick()
        self.now += 16
        self.cycle.tick()
        self.assertEqual(self.cycle.reason, 'EXTERNAL_PAUSE_OR_FOCUS_LOSS')
        self.host.control.assert_called_once_with({'enabled': False, 'live': False}, origin='lifecycle')

    def test_frozen_simulation_requests_owned_fault_recovery(self):
        self.cycle.tick()
        self.now += 16
        self.cycle.tick()
        self.host.watchdog_stop.assert_called_once_with('GAME_SIMULATION_STALLED')

    def test_media_requires_three_failures_and_real_readiness_recovery(self):
        self.host.live_media_ready.return_value = False
        for index in range(3):
            self.now += 5
            self.host.service.snapshot['frame'] += 1
            self.cycle.tick()
            self.assertEqual(self.host.watchdog_stop.call_count, 1 if index == 2 else 0)

    def test_native_manual_override_withdraws_session_intent(self):
        self.host.service.raw['strategy']['manual_override'] = True
        self.cycle.tick()
        self.host.control.assert_called_once_with({'enabled': False, 'live': False})


class PublicSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.now = 1.0
        self.guard = SupervisorState(clock=lambda: self.now)

    def test_bounded_fault_recovers_without_stopping_public_live(self):
        self.assertEqual(self.guard.assess(False, True), 'observe')
        self.now += 59
        self.assertEqual(self.guard.assess(True, True), 'observe')
        self.now += 100
        self.assertEqual(self.guard.assess(True, True), 'observe')

    def test_long_unhealthy_pause_or_exit_requests_full_restart(self):
        self.guard.assess(False, True)
        self.now += 60
        self.assertEqual(self.guard.assess(False, True), 'restart_owned_stack')

    def test_two_actual_off_samples_restart_but_unknown_is_not_off(self):
        self.guard.assess(True, True)
        self.assertEqual(self.guard.assess(True, None), 'observe')
        self.assertEqual(self.guard.assess(True, False), 'observe')
        self.assertEqual(self.guard.assess(True, False), 'restart_owned_stack')

    def test_internal_live_is_not_public_recovery_evidence(self):
        self.assertEqual(self.guard.assess(True, False), 'observe')
        self.assertEqual(self.guard.assess(True, False), 'restart_owned_stack')

    def test_native_restart_request_does_not_wait_for_idle_deadline(self):
        self.assertEqual(self.guard.assess(False, True, restart_requested=True), 'restart_owned_stack')

    def test_explicit_operator_pause_is_never_undone_by_watchdog(self):
        for _ in range(5):
            self.now += 30
            self.assertEqual(self.guard.assess(False, False, manual_pause=True), 'respect_operator_pause')


class RecoveryOwnershipTests(unittest.TestCase):
    def supervisor(self):
        owner = object.__new__(LiveSupervisor)
        owner.root = Path(__file__).resolve().parents[3]
        owner.state = SupervisorState()
        owner.audit = Mock()
        owner.report = Mock()
        owner.api = Mock(return_value={})
        owner.authorized = Mock()
        for name in ('stop_owned_stack_for_restart', 'restart_owned_game', 'start_stack',
                     'restart_official_client', 'restore_game', 'preflight_live_game', 'restore_official'):
            setattr(owner, name, Mock())
        return owner

    def test_bad_save_protection_cannot_rebaseline_or_restart_other_programmes(self):
        owner = self.supervisor()
        with patch('integration.issac.saves.SaveProtection') as protection:
            protection.return_value.verify.side_effect = AdmissionError('PROTECTED_SAVE_CHANGED')
            with self.assertRaises(AdmissionError):
                owner.recover()
        owner.stop_owned_stack_for_restart.assert_not_called()
        owner.restore_official.assert_not_called()
        owner.api.assert_not_called()

    def test_game_is_rearmed_only_after_official_stream_restore_has_completed(self):
        owner = self.supervisor()
        owner.restore_official.side_effect = AdmissionError('PUBLIC_NOT_YET_RESTORED')
        with patch('integration.issac.saves.SaveProtection'), patch('integration.issac.record_focus.game_foreground'):
            with self.assertRaises(AdmissionError):
                owner.recover()
        self.assertFalse(any(call.args[:2] == (9534, '/control') and
            call.args[2].get('action') in {'live', 'recovery_live', 'resume'}
            for call in owner.api.call_args_list))

    def test_full_recovery_keeps_model_persona_and_saves_out_of_mutation_path(self):
        owner = self.supervisor()
        with patch('integration.issac.saves.SaveProtection') as protection, patch('integration.issac.record_focus.game_foreground'):
            owner.recover()
        self.assertEqual(protection.return_value.verify.call_count, 2)
        owner.restart_owned_game.assert_called_once()
        owner.restore_official.assert_called_once()
        owner.api.assert_any_call(9534, '/control', {'action': 'recovery_live'}, timeout=20)
        completed = next(call for call in owner.audit.append.call_args_list if call.args == ('owned_full_stack_restart_completed',))
        self.assertFalse(completed.kwargs['memory_cleared'])
        self.assertFalse(completed.kwargs['model_changed'])
        self.assertFalse(completed.kwargs['public_stop_requested'])

    def test_reused_pid_or_foreign_binary_cannot_be_terminated_as_a_worker(self):
        owner = self.supervisor()
        process = Mock()
        process.create_time.return_value = 200
        process.exe.return_value = str(owner.root/'runtime/pinned.exe')
        row = {'pid': 123, 'created_at': 100, 'executable': str(owner.root/'runtime/pinned.exe'), 'executable_sha256': 'pinned'}
        with patch('psutil.Process', return_value=process):
            with self.assertRaisesRegex(AdmissionError, 'IDENTITY_CHANGED'):
                owner.owned_process(row)
        process.terminate.assert_not_called()

    def test_capture_client_is_replaced_before_new_game_and_native_bridge(self):
        owner = self.supervisor(); order = []
        for name in ('restart_official_client', 'restore_game', 'preflight_live_game', 'restore_official'):
            getattr(owner, name).side_effect = lambda name=name: order.append(name)
        with patch('integration.issac.saves.SaveProtection'), patch('integration.issac.record_focus.game_foreground'):
            owner.recover()
        self.assertEqual(order, ['restart_official_client', 'restore_game', 'preflight_live_game', 'restore_official'])
        owner.api.assert_any_call(9534, '/control', {'action': 'recovery_live'}, timeout=20)

    def test_native_game_exit_before_publish_cannot_start_public_stream(self):
        owner = self.supervisor(); owner.preflight_live_game.side_effect = AdmissionError('GAME_EXITED')
        with patch('integration.issac.saves.SaveProtection'):
            with self.assertRaisesRegex(AdmissionError, 'GAME_EXITED'):owner.recover()
        owner.restore_official.assert_not_called()

    def test_recorded_official_child_with_reused_pid_cannot_be_killed(self):
        owner = self.supervisor(); process = Mock()
        process.create_time.return_value = 200
        process.exe.return_value = str(owner.root/'official/client.exe')
        row = {'pid': 42, 'created_at': 100, 'executable': str(owner.root/'official/client.exe'), 'executable_sha256': 'pinned'}
        with patch('psutil.Process', return_value=process):
            with self.assertRaisesRegex(AdmissionError, 'CHILD_IDENTITY_CHANGED'):
                owner.official_child(row, owner.root/'official')
        process.terminate.assert_not_called()

    def test_preflight_cannot_publish_a_wrong_or_dead_slot(self):
        owner = self.supervisor()
        owner.api.return_value = {'progress': {'slot': 1, 'readonly': False}, 'observation': {'players': 1, 'dead': False}}
        with self.assertRaisesRegex(AdmissionError, 'LIVING_SLOT3_REQUIRED'):
            LiveSupervisor.preflight_live_game(owner)

    def test_recovery_owned_observation_pause_is_not_operator_takeover(self):
        self.assertFalse(operator_paused({'manual_override': False, 'live_cycle': {'phase': 'observation_only'}}))
        self.assertTrue(operator_paused({'manual_override': True, 'live_cycle': {'phase': 'observation_only'}}))
        self.assertTrue(operator_paused({'manual_override': False, 'live_cycle': {'phase': 'operator_paused'}}))

    def test_f8_takeover_during_preflight_cancels_recovery(self):
        owner = self.supervisor(); owner.api.return_value = {'manual_override': True}
        with self.assertRaisesRegex(AdmissionError, 'CANCELLED_BY_OPERATOR'):
            LiveSupervisor.preflight_live_game(owner)

    def test_recovery_pause_keeps_observation_lifecycle_and_refuses_armed_game(self):
        from integration.issac.strategy_host import StrategyHost
        owner = object.__new__(StrategyHost)
        owner.action_lock = threading.RLock(); owner.armed = False
        owner.lifecycle = SimpleNamespace(enabled=False, phase='observation_only')
        owner.service = SimpleNamespace(raw={'strategy': {'manual_override': False}})
        owner.control = Mock(return_value={'armed': False})
        owner.action({'action': 'recovery_pause'})
        owner.control.assert_called_once_with({'enabled': False, 'live': False}, origin='lifecycle')
        owner.armed = True
        with self.assertRaisesRegex(AdmissionError, 'OBSERVATION_ONLY'):
            owner.action({'action': 'recovery_pause'})

    def recovery_host(self):
        from integration.issac.strategy_host import StrategyHost
        owner = object.__new__(StrategyHost)
        owner.action_lock = threading.RLock(); owner.armed = False
        owner.lifecycle = SimpleNamespace(enabled=False, phase='observation_only', start=Mock())
        owner.service = SimpleNamespace(raw={'strategy': {'manual_override': False}})
        owner.control = Mock(return_value={'armed': True})
        return owner

    def test_recovery_resume_starts_lifecycle_only_after_successful_native_control(self):
        owner = self.recovery_host()
        self.assertEqual(owner.action({'action': 'recovery_live'}), {'armed': True})
        owner.control.assert_called_once_with({'enabled': True, 'live': True}, origin='lifecycle')
        owner.lifecycle.start.assert_called_once_with()

    def test_recovery_resume_failure_does_not_fabricate_an_operator_pause(self):
        owner = self.recovery_host(); owner.control.side_effect = AdmissionError('CORE_NOT_READY')
        with self.assertRaisesRegex(AdmissionError, 'CORE_NOT_READY'):
            owner.action({'action': 'recovery_live'})
        self.assertEqual(owner.lifecycle.phase, 'observation_only')
        self.assertFalse(operator_paused({'live_cycle': {'phase': owner.lifecycle.phase}}))
        owner.lifecycle.start.assert_not_called()

    def test_recovery_resume_cannot_bypass_manual_or_native_f8_pause(self):
        for phase, native_manual in [('operator_paused', False), ('observation_only', True)]:
            with self.subTest(phase=phase, native_manual=native_manual):
                owner = self.recovery_host(); owner.lifecycle.phase = phase
                owner.service.raw['strategy']['manual_override'] = native_manual
                with self.assertRaisesRegex(AdmissionError, 'OBSERVATION_ONLY'):
                    owner.action({'action': 'recovery_live'})
                owner.control.assert_not_called(); owner.lifecycle.start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
