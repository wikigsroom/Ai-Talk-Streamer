"""Execute the real generated native observation hook against engine fixtures."""
from pathlib import Path
import importlib.util,tempfile,unittest
from lupa.lua53 import LuaRuntime

class NativeObservationHook(unittest.TestCase):
    def fixture(self,players=1,dead=False):
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('native_pulse_builder',root/'build_native_controller.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            source=module.build(output=Path(folder)/'controller.lua').read_text('utf8')
        start=source.index('function mod:NativeRefreshObservation()')
        end=source.index('function mod:NativeControlStatus()',start)
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''mod={};lastStateFrame=70999;lease=123;ordinaryPause=true;automatic=false;reads=0
          game={GetNumPlayers=function() return players end};Isaac={GetPlayer=function() return {} end}
          playerIsDead=function() return dead end
          safeSendState=function() reads=reads+1 end''')
        lua.globals().players=players;lua.globals().dead=dead;lua.execute(source[start:end])
        return lua

    def test_frozen_simulation_can_request_the_existing_real_full_state_exchange(self):
        lua=self.fixture();self.assertEqual(lua.globals().mod.NativeRefreshObservation(lua.globals().mod),'observation_requested')
        self.assertEqual(lua.globals().reads,1);self.assertEqual(lua.globals().lastStateFrame,-10000)

    def test_observation_request_never_resumes_input_or_renews_a_lease(self):
        lua=self.fixture();lua.globals().mod.NativeRefreshObservation(lua.globals().mod)
        self.assertEqual(lua.globals().lease,123);self.assertTrue(lua.globals().ordinaryPause)
        self.assertFalse(lua.globals().automatic)

    def test_no_live_player_never_sends_a_packet(self):
        for players,dead in [(0,False),(2,False),(1,True)]:
            lua=self.fixture(players,dead);self.assertEqual(lua.globals().mod.NativeRefreshObservation(lua.globals().mod),'no_live_player')
            self.assertEqual(lua.globals().reads,0);self.assertEqual(lua.globals().lastStateFrame,70999)

    def test_failed_exchange_never_claims_freshness(self):
        lua=self.fixture();lua.execute('safeSendState=function() reads=reads+1; return nil end')
        result=lua.globals().mod.NativeRefreshObservation(lua.globals().mod)
        self.assertEqual(result,'observation_requested');self.assertNotIn('fresh',result)
