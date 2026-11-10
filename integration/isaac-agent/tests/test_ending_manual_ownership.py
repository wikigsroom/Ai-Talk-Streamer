"""Execute the actual terminal callback: victory is never an F8 takeover."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class EndingManualOwnershipTests(unittest.TestCase):
    def callback(self,manual,death=False):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text('utf8')
        callback='function mod:onGameEnd'+source.split('function mod:onGameEnd',1)[1].split('function mod:onRender',1)[0]
        run=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mod={}
            local automatic,controllerEnabled,manualOverride=true,true,false
            local strategyControl={generation='current'}
            local restartCount,MOD_VERSION=0,'frozen'
            local published
            local level={GetStage=function() return 6 end,GetStageType=function() return 0 end}
            local game={GetSeeds=function() return {GetStartSeed=function() return 123 end} end,
                GetLevel=function() return level end,GetFrameCount=function() return 42 end}
            local function canonicalRoomIndex() return 163 end
            local function flushGameEvent() end
            local Json={encode=function(event) published=event;return 'terminal' end}
            Isaac={DebugString=function() end}
            Vector=function(x,y) return {X=x,Y=y} end
        '''+callback+'''
            return function(manual,death)
                manualOverride=manual
                mod:onGameEnd(death)
                return automatic,controllerEnabled,manualOverride,published.manual_override,
                    published.callback,published.is_game_over,published.start_seed
            end
        ''')
        return run(manual,death)

    def test_victory_withdraws_controller_without_fabricating_manual_input(self):
        self.assertEqual(self.callback(False),(False,False,False,False,'MC_POST_GAME_END',False,123))

    def test_victory_preserves_an_actual_prior_human_takeover(self):
        self.assertEqual(self.callback(True),(False,False,True,True,'MC_POST_GAME_END',False,123))

    def test_death_callback_retains_existing_default_behavior_and_reports_owner(self):
        self.assertEqual(self.callback(False,True),(True,True,False,False,'MC_POST_GAME_END',True,123))


if __name__=='__main__':unittest.main()
