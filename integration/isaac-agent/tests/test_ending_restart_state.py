"""A victory restart must publish a fresh run despite the frame counter rewind."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class EndingRestartStateTests(unittest.TestCase):
    def test_first_new_run_state_replaces_the_old_ending_and_actions(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        reset='local function resetRunObservations()'+source.split('local function resetRunObservations()',1)[1].split('local function vectorTable',1)[0]
        started='function mod:onGameStarted()'+source.split('function mod:onGameStarted()',1)[1].split('function mod:onGameEnd',1)[0]
        send='local function sendState()'+source.split('local function sendState()',1)[1].split('local lastBridgeStateErrorAt',1)[0]
        result=LuaRuntime(unpack_returned_tuples=True).execute('''
            Vector=function(x,y) return {X=x,Y=y} end
            local mod={}
            local lastStateFrame,lastActionFrame,lastUtilityFrame,lastPyroHealFrame=68429,68420,68300,68000
            local pendingState,pendingGameEvent='old state','old victory'
            local action={id='old_action',sourceRoomIndex=21}
            local automatic,manualOverride=true,true
            local damageEvents={{frame=63363}}
            local published=nil
            game={GetFrameCount=function() return 5 end}
            Isaac={GetPlayer=function() return nil end}
            Json={encode=function(state) return tostring(state.seed) end}
            local function ensureClient() return true end
            local function readActions() end
            local function closeClient() end
            local function flushPendingState()
                if pendingState then published,pendingState=pendingState,nil end
            end
            local function collectState() return {seed=799112684} end
        '''+reset+started+send+'''
            mod:onGameStarted()
            sendState()
            return published,lastStateFrame,action.sourceRoomIndex,#damageEvents,
                pendingGameEvent==nil,automatic,manualOverride,lastUtilityFrame,lastPyroHealFrame
        ''')
        self.assertEqual(result,('799112684\n',5,-1,0,True,False,True,-10000,-10000))


if __name__=='__main__':unittest.main()
