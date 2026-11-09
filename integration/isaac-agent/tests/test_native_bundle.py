"""The full in-memory controller must compile on the game's Lua version."""
from pathlib import Path
import sys
import unittest
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools/python-libs')]
from lupa.lua53 import LuaRuntime
from build_native_controller import build


class NativeBundleTests(unittest.TestCase):
    def generated(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=build(output=Path(temporary)/'native-controller.lua')
            return path.read_text(encoding='utf8')

    def test_complete_native_controller_compiles_on_lua53(self):
        source=self.generated()
        valid,error=LuaRuntime(unpack_returned_tuples=True).eval('function(source) local fn,err=load(source); return fn~=nil,err end')(source)
        self.assertTrue(valid,error)

    def test_generated_controller_cannot_bypass_normal_game_actions(self):
        source=self.generated()
        for forbidden in ('Isaac.ExecuteCommand(',':DropTrinket(',':FireTear(',':FireBomb(',
                          ':UseActiveItem(',':UseCard(',':UsePill(',':AddCollectible(',':TakeDamage('):
            self.assertNotIn(forbidden,source)

    def test_native_render_keeps_death_observation_without_operator_hud(self):
        source=self.generated()
        render=source.split('function mod:onRender()',1)[1].split('mod:AddCallback(ModCallbacks.MC_POST_UPDATE',1)[0]
        self.assertIn('safeSendState()',render)
        self.assertIn('handleDeathAndRestart(player)',render)
        self.assertNotIn('Isaac.RenderText(',render)

    def test_fresh_controller_cannot_restart_a_dead_run_even_with_frozen_game_clock(self):
        source=self.generated()
        part='local function playerIsDead(player)'+source.split('local function playerIsDead(player)',1)[1].split('local function collectState()',1)[0]
        lua=LuaRuntime(unpack_returned_tuples=True)
        api=lua.execute('''
          local now=0
          local deathDetectedFrame,deathDetectedAt,deathWaitTicks=-1,-1,0
          local controllerEnabled,manualOverride,lastControlMessageAt=true,false,0
          local restartPhase,restartAttempted,restartCount='alive',false,0
          local automatic=true
          game={GetFrameCount=function() return 100 end}
          Isaac={GetTime=function() return now end,ExecuteCommand=function() error('forbidden console call') end}
          Vector=function(x,y) return {X=x,Y=y} end
          local player={IsDead=function() return true end}
          resetRunObservations=function() end
        '''+part+'''
          return function(ms)
            now=ms;lastControlMessageAt=now
            return handleDeathAndRestart(player),automatic,restartPhase,restartCount
          end
        ''')
        for ms in (0,1999,2000,5000,60000):
            self.assertEqual(api(ms),(True,False,'death_wait',0))


if __name__=='__main__': unittest.main()
