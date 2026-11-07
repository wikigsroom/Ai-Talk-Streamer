"""The real first-floor exit stopped Isaac 22.34px before the fall trigger."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class TrapdoorApproachTests(unittest.TestCase):
    def drive(self, distance, closed=False, opening=False):
        source = (ROOT / 'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        branch = 'local bossExitGrid = tonumber' + source.split(
            'local bossExitGrid = tonumber', 1)[1].split(
            "    -- Use the engine's door position", 1)[0]
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().distance = distance
        lua.globals().closed = closed
        lua.globals().opening = opening
        return lua.execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__index={Length=function(v) return math.sqrt(v.X*v.X+v.Y*v.Y) end}
            local action={id='enter_boss_exit_37',mode='boss_exit'}
            local GRID_TRAPDOOR_TYPE=17
            local trapdoor={Position=Vector(320,200),GetType=function() return 17 end,
                GetSprite=function() return {GetAnimation=function() return closed and 'Closed' or opening and 'Open Animation' or 'Opened' end} end}
            local room={GetGridEntity=function() return trapdoor end}
            local player={Position=Vector(320,200-distance)}
            local function firstSafeMove(_,m) return m end
            local function drive()
        ''' + branch + '''
            end
            local move=drive()
            return move.X,move.Y
        ''')

    def test_real_stopped_position_continues_into_trigger(self):
        observed=json.loads((ROOT/'tests/fixtures/stage1-trapdoor-stop-native84.json').read_text(encoding='utf8'))
        distance=observed['boss_exit_position']['y']-observed['player']['pos']['y']
        self.assertGreater(distance,20)
        self.assertLess(distance,24)
        self.assertEqual(self.drive(distance),(0,1))

    def test_close_center_holds_for_normal_fall_transition(self):
        self.assertEqual(self.drive(6),(0,0))

    def test_closed_exit_is_given_space_to_open(self):
        self.assertEqual(self.drive(22.34,closed=True),(0,-1))
        self.assertEqual(self.drive(6,closed=True),(0,-1))
        self.assertEqual(self.drive(90,closed=True),(0,0))

    def test_opening_animation_finishes_before_approaching_again(self):
        self.assertEqual(self.drive(60,opening=True),(0,0))
        self.assertEqual(self.drive(60),(0,1))


if __name__=='__main__': unittest.main()
