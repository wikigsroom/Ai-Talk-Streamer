"""Native closed-door overlap must allow a forecast back into the room."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class WallOverlapForecastTests(unittest.TestCase):
    def setUp(self):
        self.raw=json.loads((ROOT/'tests/fixtures/stage1-door-overlap-native120.json').read_text(encoding='utf8'))
        lua=LuaRuntime(unpack_returned_tuples=True)
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='local function movementForecast'+source.split('local function movementForecast',1)[1].split('local function predictiveCombatMove',1)[0]
        self.api=lua.execute('''
            local mt={}
            Vector=function(x,y)return setmetatable({X=x,Y=y},mt)end
            mt.__add=function(a,b)return Vector(a.X+b.X,a.Y+b.Y)end
            mt.__sub=function(a,b)return Vector(a.X-b.X,a.Y-b.Y)end
            mt.__mul=function(a,b)return Vector(a.X*b,a.Y*b)end
            mt.__index={Length=function(a)return math.sqrt(a.X*a.X+a.Y*a.Y)end,
                Distance=function(a,b)return (a-b):Length()end}
            local blocked={}
            local room={GetGridSize=function()return 135 end,
                GetGridIndex=function(_,p)return math.floor((p.Y-100)/40)*15+math.floor((p.X-20)/40)end,
                GetGridPosition=function(_,i)return Vector(i%15*40+40,math.floor(i/15)*40+120)end,
                GetGridPath=function(_,i)return blocked[i] and 1000 or 0 end}
            '''+helper+'''
            return function(cells,x,y,vx,vy,mx,my)
                blocked={};for _,i in ipairs(cells)do blocked[i]=true end
                local player={Position=Vector(x,y),Velocity=Vector(vx,vy),MoveSpeed=1,Size=10}
                local p=movementForecast(player,Vector(mx,my),10,room)
                return p[10].X,p[10].Y
            end
        ''')
        self.cells=lua.table_from(self.raw['layout']['blocked'])

    def test_actual_overlap_can_leave_the_closed_door_during_grace_period(self):
        p=self.raw['player']
        self.assertIn(self.raw['player_grid_index'],self.raw['layout']['blocked'])
        x,y=self.api(self.cells,p['pos']['x'],p['pos']['y'],p['vel']['x'],p['vel']['y'],0,1)
        self.assertGreater(y,170)
        self.assertAlmostEqual(x,p['pos']['x'],places=1)

    def test_zero_input_does_not_claim_escape_and_up_cannot_cross_the_boundary(self):
        p=self.raw['player']['pos']
        _,stay=self.api(self.cells,p['x'],p['y'],0,0,0,0)
        _,up=self.api(self.cells,p['x'],p['y'],0,0,0,-1)
        self.assertAlmostEqual(stay,p['y'])
        self.assertGreaterEqual(up,p['y'])

    def test_new_wall_still_blocks_a_normal_approach(self):
        x,y=self.api(self.cells,320,160,0,0,0,-1)
        self.assertGreaterEqual(y,149)
        self.assertLessEqual(y,160)


if __name__=='__main__':unittest.main()
