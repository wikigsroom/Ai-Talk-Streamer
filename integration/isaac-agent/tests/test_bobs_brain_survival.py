"""The observed familiar explosion must not be invited by close-range fire."""
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class BobsBrainSurvivalTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='local function bobsBrainShotSafe('+source.split('local function bobsBrainShotSafe(',1)[1].split('local function chargedShootDirection',1)[0]
        self.safe=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end}
            local entities={}
            Isaac={GetRoomEntities=function() return entities end}
            local function isCombatEnemy(e) return not e.friendly end
        '''+helper+'''
            return function(px,py,pvx,pvy,ex,ey,evx,evy,owned,immune,friendly)
                entities={{Position=Vector(ex,ey),Velocity=Vector(evx,evy),friendly=friendly}}
                local player={Position=Vector(px,py),Velocity=Vector(pvx,pvy),
                    HasCollectible=function(_,id) return (id==273 and owned) or id==immune end}
                return bobsBrainShotSafe(player)
            end
        ''')

    def test_actual_explosion_approach_suppresses_fire_but_earlier_distance_does_not(self):
        rows=json.loads((ROOT/'tests/fixtures/stage1-bobs-brain-native128.json').read_text(encoding='utf8'))
        states={r['state']['frame']:r['state'] for r in rows}
        for frame,expected in ((2373,True),(2406,False)):
            s=states[frame];p=s['player'];e=s['enemies'][0]
            self.assertEqual(self.safe(p['pos']['x'],p['pos']['y'],p['vel']['x'],p['vel']['y'],
                e['pos']['x'],e['pos']['y'],e['vel']['x'],e['vel']['y'],True,0,False),expected)

    def test_charging_enemy_reserves_motion_margin(self):
        self.assertFalse(self.safe(0,0,0,0,190,0,-5,0,True,0,False))
        self.assertTrue(self.safe(0,0,0,0,220,0,0,0,True,0,False))

    def test_ordinary_weapons_explosion_immunity_and_friendly_entities_are_not_blocked(self):
        for owned,immune,friendly in ((False,0,False),(True,223,False),(True,375,False),(True,0,True)):
            self.assertTrue(self.safe(0,0,0,0,40,0,0,0,owned,immune,friendly))


if __name__=='__main__': unittest.main()
