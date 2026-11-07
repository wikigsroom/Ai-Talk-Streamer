"""Every bomb-only target must allow normal movement to the planned site."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class BombApproachTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text('utf8')
        branch='if action.mode == "bomb" and bombId then'+source.split('if action.mode == "bomb" and bombId then',1)[1].split('local nearest, distance',1)[0]
        self.choose=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end}
            local function liveGridHazardKind(e) return e and e.kind end
            local function liveHazardKind(e) return e.kind end
            local function bombOnlyFireKind(k) return k=='blue_fire' or k=='purple_fire' end
            local function firstSafeMove(_,move) return move end
            return function(kind,entity,atSite)
                local entities=entity and {{Index=12,kind=kind,Position=Vector(260,280)}} or {}
                Isaac={GetRoomEntities=function() return entities end}
                local room={GetGridSize=function() return 1 end,
                    GetGridEntity=function() return not entity and {kind=kind,Position=Vector(260,280)} or nil end}
                local action={mode='bomb',move=Vector(1,0),bombSite=Vector(200,280)}
                local bombId=entity and 12 or -100000
                local bombTarget
                local player={Position=Vector(atSite and 200 or 100,280)}
                local function move()
        '''+branch+'''
                    return Vector(0,0)
                end
                local result=move()
                return result.X,result.Y
            end
        ''')

    def test_ordinary_passage_rock_and_grid_bomb_hazards_approach_site(self):
        for kind in ('passage_rock','xrock','blue_fire','purple_fire'):
            self.assertEqual(self.choose(kind,False,False),(1,0),kind)
            self.assertEqual(self.choose(kind,False,True),(0,0),kind)

    def test_entity_fire_uses_its_native_entity_index(self):
        self.assertEqual(self.choose('blue_fire',True,False),(1,0))
        self.assertEqual(self.choose('purple_fire',True,False),(1,0))

    def test_non_bomb_target_cannot_become_a_bomb_approach(self):
        self.assertEqual(self.choose('poop',False,False),(0,0))
        self.assertEqual(self.choose('poop',True,False),(0,0))


if __name__=='__main__':unittest.main()
