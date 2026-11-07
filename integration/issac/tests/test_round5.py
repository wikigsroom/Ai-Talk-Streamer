"""Real R4 menu/startup regressions, written before the R5 source freeze."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
import urllib.error

from integration.issac.common import AdmissionError
from integration.issac.native_game import OBSERVE


def script(name):
    path=Path(__file__).resolve().parents[3]/'scripts'/name
    spec=importlib.util.spec_from_file_location('round5_'+path.stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class NativeMenuTests(unittest.TestCase):
    def test_a_real_menu_can_have_no_game_object_at_all(self):
        from lupa.lua53 import LuaRuntime
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('function Game() return nil end;Isaac=nil;json=nil')
        value=json.loads(lua.execute(OBSERVE))
        self.assertEqual(value,{'paused':False,'frame':0,'players':0,'dead':False,'hp':0,'stage':0,'room':0,'seed':0,'controller_installed':False})

    def test_callable_game_class_is_supported_but_missing_api_is_not_idle(self):
        from lupa.lua53 import LuaRuntime,LuaError
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('Game=setmetatable({}, {__call=function() return nil end})')
        self.assertEqual(json.loads(lua.execute(OBSERVE))['players'],0)
        lua.execute('Game=nil')
        with self.assertRaisesRegex(LuaError,'GAME_API_NOT_READY'):lua.execute(OBSERVE)

    def test_diagnostic_waits_for_an_actual_observation_after_lua_pointer(self):
        module=script('diagnose_issac.py');actual={'observation':{'players':0},'progress':{'slot':0}}
        with patch.object(module,'json_http',side_effect=[AdmissionError('NATIVE_BRIDGE_REQUEST_FAILED'),actual]) as request,patch.object(module.time,'sleep'):
            self.assertEqual(module.wait_native_observation(Path('.'),45),actual)
        self.assertEqual(request.call_count,2)
        with patch.object(module,'json_http',side_effect=AdmissionError('NATIVE_STATE_RESPONSE_INVALID')):
            with self.assertRaisesRegex(AdmissionError,'RESPONSE_INVALID'):module.wait_native_observation(Path('.'),45)

    def test_http_conflict_keeps_only_a_bounded_stable_error_code(self):
        module=script('diagnose_issac.py')
        for payload,expected in [(b'{"error":"NATIVE_BRIDGE_REQUEST_FAILED"}','NATIVE_BRIDGE_REQUEST_FAILED'),
                                 (b'{"error":"private transcript must not escape"}','LOCAL_DIAGNOSTIC_HTTP_REJECTED_409')]:
            error=urllib.error.HTTPError('http://127.0.0.1:9534/control',409,'Conflict',{},io.BytesIO(payload))
            opener=Mock();opener.open.side_effect=error
            with patch.object(module,'bridge_token',return_value='test'),patch.object(module.urllib.request,'build_opener',return_value=opener):
                with self.assertRaisesRegex(AdmissionError,'^'+expected+'$'):module.json_http(Path('.'),'http://127.0.0.1:9534/control',{'action':'observe'})

    def test_living_missing_or_noninteger_players_cannot_close_a_window(self):
        module=script('diagnose_issac.py')
        for observations in [({'players':1},{'players':0}),({'players':0},{'players':1}),({},{}),({'players':False},{'players':False})]:
            with self.subTest(observations=observations),patch.object(module.time,'sleep'),patch.object(module,'process_identity') as identity:
                with self.assertRaisesRegex(AdmissionError,'LIVING_OR_UNKNOWN_GAME_PRESERVED'):
                    module.close_idle_window(Path('.'),{'pid':123},Mock(side_effect=observations))
                identity.assert_not_called()


class PreparationAndOrderingTests(unittest.TestCase):
    def test_waiting_for_the_existing_job_does_not_hash_or_launch_before_capacity(self):
        from integration.issac import local_model as module
        model=module.LocalModel.__new__(module.LocalModel)
        model.config={'model':'retained'};model.progress=Mock();model.models=Mock(side_effect=AdmissionError('not running'))
        model.admit_retained_files=Mock(side_effect=AdmissionError('STOP_AFTER_CAPACITY_PROOF'))
        model.start_application=Mock()
        busy={'gpu_free_mib':6000,'gpu_utilization_percent':100,'host_available_bytes':40*1024**3,'comfy_running_jobs':1}
        free={**busy,'gpu_free_mib':40000,'gpu_utilization_percent':0,'comfy_running_jobs':0}
        def wait(_seconds):
            model.admit_retained_files.assert_not_called();model.start_application.assert_not_called()
        with patch.object(module,'snapshot',side_effect=[busy,free]),patch.object(module.time,'sleep',side_effect=wait) as sleep:
            with self.assertRaisesRegex(AdmissionError,'STOP_AFTER_CAPACITY_PROOF'):model.prepare(capacity_wait_seconds=30)
        sleep.assert_called_once();model.admit_retained_files.assert_called_once();model.start_application.assert_not_called()

    def test_model_qualification_is_blocked_until_prepare_passes(self):
        module=script('run_issac_round.py')
        for rows in ([],[{'check':'local-model-prepare','passed':False}]):
            blocked=module.blocked_by_prerequisite('local-model-qualification',rows)
            self.assertFalse(blocked['passed']);self.assertEqual(blocked['state'],'blocked')
            self.assertEqual(blocked['inference_requests_attempted'],0)
        self.assertIsNone(module.blocked_by_prerequisite('local-model-qualification',[{'check':'local-model-prepare','passed':True}]))
        self.assertIsNone(module.blocked_by_prerequisite('official-client-signature',[]))


if __name__=='__main__':unittest.main()
