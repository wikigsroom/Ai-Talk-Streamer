"""Use the real Lua spike observation; pass-through tiles can still hurt."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class GridDangerTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='local function gridEvent(grid, index)'+source.split('local function gridEvent(grid, index)',1)[1].split('local function currentDimension',1)[0]
        self.observe=LuaRuntime().execute('''
            local GRID_SPIKES_TYPE,GRID_SPIKES_ONOFF_TYPE,GRID_PRESSURE_PLATE_TYPE,GRID_TNT_TYPE=8,9,20,12
            local function gridState(g) return g.State end
            local function vectorTable(v) return v end
        '''+helper+'''
            return function(kind,state,collision)
                return gridEvent({State=state,CollisionClass=collision,Position={x=100,y=100},
                    GetType=function() return kind end},1).active
            end
        ''')

    def test_ordinary_spikes_with_no_blocking_collision_are_still_dangerous(self):
        self.assertTrue(self.observe(8,0,0))

    def test_raised_timed_spikes_are_dangerous_even_without_blocking_collision(self):
        self.assertTrue(self.observe(9,0,0))
        self.assertFalse(self.observe(9,1,0))


if __name__=='__main__':
    unittest.main()
