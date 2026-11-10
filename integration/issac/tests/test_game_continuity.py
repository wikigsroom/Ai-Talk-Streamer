"""A failed media/AI owner and a cup event cannot pause a living game."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from integration.issac.common import AdmissionError
from integration.issac.continuity import NO_AUTOMATIC_PAUSE_GUARD,DISABLE_FOCUS_LOSS_PAUSE
from integration.issac.saves import SaveProtection,continuity_options_only
from integration.issac.live_cycle import LiveCycle
from integration.issac.live_supervisor import LiveSupervisor
from integration.issac.native_game import NativeGame
from integration.issac.strategy_host import StrategyHost
from integration.issac.application import Application


ROOT=Path(__file__).resolve().parents[3]


class GameContinuity(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);folder=self.root/'configs/issac';folder.mkdir(parents=True)
        (folder/'game-continuity.json').write_text(json.dumps({'uninterrupted_gameplay':True}),'utf8')

    def test_native_pause_is_rejected_before_any_game_input_or_observation(self):
        native=object.__new__(NativeGame);native.root=self.root;native.rpc=Mock();native.observe=Mock()
        with self.assertRaisesRegex(AdmissionError,'AUTOMATIC_GAME_PAUSE_FORBIDDEN'):native.pause()
        native.rpc.assert_not_called();native.observe.assert_not_called()

    def test_native_detach_preserves_living_game_without_pause(self):
        native=object.__new__(NativeGame);native.root=self.root;native.lock=threading.RLock()
        native.session=Mock();session=native.session;native.script=Mock();native.pause=Mock()
        native.process=Mock(is_running=Mock(return_value=True),status=Mock(return_value='running'))
        native.close();session.detach.assert_called_once();native.pause.assert_not_called()

    def test_faults_request_component_repair_and_keep_input_owner_armed(self):
        for reason in ('LIVE_MEDIA_UNAVAILABLE','NAIMEI_CORE_UNAVAILABLE','GAME_BRIDGE_STALE','CORE_TURN_STALLED'):
            host=object.__new__(StrategyHost);host.uninterrupted_gameplay=True;host.armed=True
            host.audit=Mock();host.native=Mock();host.control=Mock();host.lifecycle=Mock()
            result=host.watchdog_stop(reason)
            self.assertTrue(result['armed']);self.assertTrue(result['component_repair_requested'])
            host.control.assert_not_called();host.native.pause.assert_not_called()

    def test_automatic_pause_endpoints_cannot_change_revision_or_game(self):
        host=object.__new__(StrategyHost);host.action_lock=threading.RLock();host.control_revision=5
        host.uninterrupted_gameplay=True;host.native=Mock();host.control=Mock()
        for action in ('pause','natural_pause','natural_resume','recovery_pause'):
            with self.assertRaisesRegex(AdmissionError,'AUTOMATIC_GAME_INTERRUPTION_FORBIDDEN'):
                host.action({'action':action})
        self.assertEqual(host.control_revision,5);host.control.assert_not_called();host.native.pause.assert_not_called()

    def test_live_fault_keeps_cycle_playing_without_control_calls(self):
        host=SimpleNamespace(uninterrupted_gameplay=True,audit=Mock(),last_fault=None,control=Mock())
        cycle=LiveCycle(host);cycle.enabled=True;cycle.phase='playing'
        cycle.fault('LIVE_MEDIA_UNAVAILABLE');self.assertTrue(cycle.enabled);self.assertEqual(cycle.phase,'playing')
        self.assertFalse(cycle.alert['game_pause_requested']);host.control.assert_not_called()

    def test_full_stack_and_game_restart_entries_are_blocked(self):
        supervisor=object.__new__(LiveSupervisor);supervisor.root=self.root
        for action in (supervisor.restart_owned_game,supervisor.stop_owned_stack_for_restart):
            with self.assertRaises(AdmissionError):action()

    def test_game_is_not_a_replaceable_component(self):
        app=object.__new__(Application);app.root=self.root
        app.config={'native_paths':dict(node='node',game_python='game',media_python='media',voice_python='voice')}
        for name in ('isaac-game','game','unknown'):
            with self.assertRaisesRegex(AdmissionError,'GAME_RESTART_IS_NOT_A_COMPONENT_ACTION'):app.component_spec(name)

    def test_real_component_repair_keeps_game_and_replaces_only_stalled_narrator(self):
        owner=object.__new__(LiveSupervisor);owner.root=self.root;owner.authorized=Mock();owner.report=Mock()
        owner.audit=Mock();owner.state=SimpleNamespace(restarts=0,bad_since=1,platform_off=0)
        owner.owned_process=Mock(return_value=True);owner.platform_live=Mock(return_value=True)
        owner.restart_owned_game=Mock();owner.stop_owned_stack_for_restart=Mock()
        names=['gpu-geometry','game-controller','voice','flashhead','studio','narrator']
        status={'armed':True,'native_attached':True,'live_cycle':{'phase':'playing','alert':{'code':'CORE_TURN_STALLED'}}}
        def api(port,path,body=None,**_):
            if port==9541 and body is None:return {'children':{n:{'alive':True} for n in names}}
            if port==9534 and body is None:return {'service':'issac-native-game',**status}
            return {'ready':True,'automatic':True}
        owner.api=Mock(side_effect=api)
        game={'name':'isaac-game','pid':44,'created_at':100}
        with patch('integration.issac.live_supervisor.read_json',side_effect=lambda path:
                   {'processes':[game]} if path.name=='application.json' else {'health_port':9540}), \
             patch('integration.issac.official_window.identity'):
            owner.repair_live_components()
        replacements=[c.args[2] for c in owner.api.call_args_list if c.args[:2]==(9541,'/action')]
        self.assertEqual(replacements,[{'action':'restart_component','component':'narrator'}])
        owner.restart_owned_game.assert_not_called();owner.stop_owned_stack_for_restart.assert_not_called()
        self.assertFalse(any(c.args[:2]==(9534,'/control') and c.args[2].get('action')!='components_ready'
                             for c in owner.api.call_args_list))

    def test_real_lua_migration_guard_blocks_automatic_but_preserves_explicit_control(self):
        from lupa.lua53 import LuaRuntime
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''Game=function() return {IsPaused=function() return false end} end
            calls=0;local c={pauseHold=true,pauseRequest={},pauseAck={}}
            function c:requestPause(id) calls=calls+1;return id end
            _G.__NativeIsaacController={strategyControl=c}''')
        self.assertEqual(lua.execute(NO_AUTOMATIC_PAUSE_GUARD),'automatic pause forbidden')
        self.assertEqual(lua.eval('__NativeIsaacController.strategyControl:requestPause("lease")'),'automatic_pause_forbidden')
        self.assertEqual(lua.eval('calls'),0)
        self.assertEqual(lua.eval('__NativeIsaacController.strategyControl:requestPause("manual",true)'),'manual')
        self.assertFalse(lua.eval('__NativeIsaacController.strategyControl.pauseHold'))

    def test_unprobed_narrator_runs_real_persona_probe_without_restarting_game(self):
        owner=object.__new__(LiveSupervisor);owner.root=ROOT
        replies=[{'ready':False},{'dsh_ready':True},
                 {'passed':True,'model':'gpt-6-luna','protocol':'responses'},{'ready':True}]
        owner.api=Mock(side_effect=replies)
        self.assertTrue(owner.component_health('narrator',3104,'/api/dsh/issac/core/status')['ready'])
        self.assertEqual([c.args[1] for c in owner.api.call_args_list],
                         ['/api/dsh/issac/core/status','/health','/api/dsh/probe','/api/dsh/issac/core/status'])

    def test_probe_failure_cannot_enable_or_replace_game_or_accept_previous_model(self):
        for model in ('deepseek-flash','gpt-6.1-sol'):
            owner=object.__new__(LiveSupervisor);owner.root=ROOT
            owner.api=Mock(side_effect=[{'ready':False},{'dsh_ready':True},
                                       {'passed':True,'model':model,'protocol':'responses'}])
            with self.assertRaisesRegex(AdmissionError,'APPROVED_CHANNEL_PERSONA_PROBE_REQUIRED'):
                owner.component_health('narrator',3104,'/api/dsh/issac/core/status')
            self.assertEqual(len(owner.api.call_args_list),3)

    def test_actual_lua_controller_rejects_lease_pause_in_continuous_mode(self):
        from lupa.lua53 import LuaRuntime
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('Isaac={GetTime=function() return 1 end}')
        module=lua.execute((ROOT/'integration/isaac-agent/mods/IsaacJev/strategy_control.lua').read_text('utf8'))
        controller=module.new(lua.table());lua.globals().c=controller
        lua.globals().ISAAC_ALLOW_AUTOMATIC_GAME_PAUSE=False
        self.assertEqual(lua.eval('c:requestPause("lease")'),'automatic_pause_forbidden')
        self.assertIsNone(controller.pauseRequest)
        self.assertTrue(lua.eval('c:requestPause("operator",true)'))
        self.assertTrue(controller.pauseHold)

    def test_actual_option_api_disables_focus_pause_without_touching_gameplay(self):
        from lupa.lua53 import LuaRuntime
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('Options={PauseOnFocusLost=true};health=9;seed=123')
        self.assertEqual(lua.execute(DISABLE_FOCUS_LOSS_PAUSE),'false')
        self.assertFalse(lua.eval('Options.PauseOnFocusLost'))
        self.assertEqual(lua.eval('health'),9);self.assertEqual(lua.eval('seed'),123)

    def test_consecutive_completed_busy_turns_are_not_one_stalled_turn(self):
        cycle=LiveCycle(SimpleNamespace(audit=Mock()))
        core={'busy':True,'process_id':9,'continuous_session_id':'one','turns':0}
        self.assertFalse(cycle.core_turn_stalled(core,0))
        self.assertFalse(cycle.core_turn_stalled(core,60))
        self.assertFalse(cycle.core_turn_stalled({**core,'turns':1},70))
        self.assertFalse(cycle.core_turn_stalled({**core,'turns':2},140))
        self.assertFalse(cycle.core_turn_stalled({**core,'turns':2},215))
        self.assertTrue(cycle.core_turn_stalled({**core,'turns':2},216))
        self.assertFalse(cycle.core_turn_stalled({**core,'busy':False},217))
        self.assertFalse(cycle.core_turn_stalled(core,218))

    def test_recovered_narrator_rearms_through_current_native_admission(self):
        owner=object.__new__(LiveSupervisor)
        owner.api=Mock(side_effect=[{'ready':True,'automatic':False},{'armed':True}])
        owner.ensure_core_automatic({'armed':True,'manual_override':False,'live_cycle':{'phase':'playing'}})
        owner.api.assert_any_call(9534,'/control',{'action':'components_rearm'},timeout=20)
        owner.api=Mock(return_value={'automatic':True})
        self.assertTrue(owner.ensure_core_automatic({})['already_automatic']);self.assertEqual(owner.api.call_count,1)
        owner.api.reset_mock()
        with self.assertRaisesRegex(AdmissionError,'CANCELLED_BY_OPERATOR'):
            owner.ensure_core_automatic({'manual_override':True})
        owner.api.assert_not_called()

    def test_component_rearm_rechecks_current_manual_takeover_at_native_endpoint(self):
        host=object.__new__(StrategyHost);host.action_lock=threading.RLock();host.uninterrupted_gameplay=True
        host.service=SimpleNamespace(raw={'strategy':{'manual_override':True}})
        host.lifecycle=SimpleNamespace(phase='playing');host.control=Mock(return_value={'armed':True})
        with self.assertRaisesRegex(AdmissionError,'EXPLICIT_OPERATOR_CONTROL_PRESERVED'):
            host.action({'action':'components_rearm'})
        host.control.assert_not_called()
        host.service.raw['strategy']['manual_override']=False
        self.assertTrue(host.action({'action':'components_rearm'})['armed'])
        host.control.assert_called_once_with({'enabled':True,'live':True},origin='lifecycle')

    def test_native_focus_setting_is_fixed_and_legacy_policy_issues_no_rpc(self):
        n=object.__new__(NativeGame);n.root=self.root;n.rpc=Mock(return_value='false');n.audit=Mock()
        n.configure_continuity_options();n.rpc.assert_called_once_with('evaluate',DISABLE_FOCUS_LOSS_PAUSE)
        (self.root/'configs/issac/game-continuity.json').unlink();n.rpc.reset_mock()
        n.configure_continuity_options();n.rpc.assert_not_called()

    def test_longer_declared_choice_budget_is_not_preempted_by_legacy_watchdog(self):
        cycle=LiveCycle(SimpleNamespace(audit=Mock()))
        core={'busy':True,'process_id':9,'continuous_session_id':'one','turns':0,'decision_budget_ms':115000}
        self.assertFalse(cycle.core_turn_stalled(core,0))
        self.assertFalse(cycle.core_turn_stalled(core,100))
        self.assertFalse(cycle.core_turn_stalled(core,135))
        self.assertTrue(cycle.core_turn_stalled(core,136))

    def test_focus_option_writeback_preserves_exact_baseline_and_slot_guards(self):
        game=self.root/'game';game.mkdir();option=game/'options.ini'
        original=b'[Options]\r\nWindowPosX=1\r\nWindowPosY=2\r\nPauseOnFocusLost=1\r\nFoundHUD=1\r\n'
        option.write_bytes(original);slot=game/'rep_persistentgamedata1.dat';slot.write_bytes(b'original')
        guard=SaveProtection(self.root);baseline=guard.prepare([str(game)]);manifest=guard.manifest.read_bytes()
        option.write_bytes(original.replace(b'PauseOnFocusLost=1',b'PauseOnFocusLost=0'))
        self.assertTrue(guard.verify()['protected_unchanged']);self.assertEqual(guard.manifest.read_bytes(),manifest)
        self.assertEqual(next(Path(r['backup']).read_bytes() for r in baseline['files'] if r['relative']=='options.ini'),original)
        slot.write_bytes(b'altered')
        with self.assertRaisesRegex(AdmissionError,'PROTECTED_SAVE_CHANGED'):guard.verify()

    def test_focus_option_exception_cannot_allow_duplicates_other_options_or_reenable(self):
        original=b'WindowPosX=1\nWindowPosY=2\nPauseOnFocusLost=1\nFoundHUD=1\n'
        valid=original.replace(b'PauseOnFocusLost=1',b'PauseOnFocusLost=0')
        self.assertTrue(continuity_options_only(original,valid))
        for wrong in (original,valid+b'PauseOnFocusLost=0\n',valid.replace(b'FoundHUD=1',b'FoundHUD=0'),valid.replace(b'Lost=0',b'Lost=2')):
            self.assertFalse(continuity_options_only(original,wrong))

    def test_connected_collector_is_idempotent_but_disconnected_or_other_errors_are_not_hidden(self):
        owner=object.__new__(LiveSupervisor)
        owner.api=Mock(side_effect=[AdmissionError('RECOVERY_API_COLLECTOR_ALREADY_RUNNING'),{'collectors':{'bilibili':{'state':'CONNECTED','error':None}}}])
        self.assertTrue(owner.ensure_bilibili_collector()['already_connected'])
        owner.api=Mock(side_effect=[AdmissionError('RECOVERY_API_COLLECTOR_ALREADY_RUNNING'),{'collectors':{'bilibili':{'state':'FAILED','error':'network'}}}])
        with self.assertRaisesRegex(AdmissionError,'COLLECTOR_ALREADY_RUNNING'):owner.ensure_bilibili_collector()
        owner.api=Mock(side_effect=AdmissionError('RECOVERY_API_FORBIDDEN'))
        with self.assertRaisesRegex(AdmissionError,'FORBIDDEN'):owner.ensure_bilibili_collector()
        self.assertEqual(owner.api.call_count,1)

    def test_installer_path_checks_prevent_runtime_and_traversal_writes(self):
        spec=importlib.util.spec_from_file_location('continuous_installer',ROOT/'scripts/install_issac_continuous_candidate.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for name in ('../escape','state/file','runtime/python.exe','folder/private/key','C:/other','a\\b'):
            with self.assertRaises(ValueError):module.source_path(self.root,name)
        self.assertEqual(module.source_path(self.root,'src/runtime/service.py'),self.root/'src/runtime/service.py')


if __name__=='__main__':unittest.main()
