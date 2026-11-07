"""The observed combat retreat touched an unselected closed curse door."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class UnintendedRoomExitTests(unittest.TestCase):
    def setUp(self):
        self.raw=json.loads((ROOT/'tests/fixtures/stage1-door-overlap-native120.json').read_text(encoding='utf8'))
        lua=LuaRuntime(unpack_returned_tuples=True)
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        safety='local function safeMoveCandidate('+source.split('local function safeMoveCandidate(',1)[1].split('local function firstSafeMove',1)[0]
        self.api=lua.execute('''
            local mt={}
            Vector=function(x,y)return setmetatable({X=x,Y=y},mt)end
            mt.__add=function(a,b)return Vector(a.X+b.X,a.Y+b.Y)end
            mt.__sub=function(a,b)return Vector(a.X-b.X,a.Y-b.Y)end
            mt.__mul=function(a,b)return Vector(a.X*b,a.Y*b)end
            mt.__index={Length=function(a)return math.sqrt(a.X*a.X+a.Y*a.Y)end,
                Distance=function(a,b)return (a-b):Length()end}
            local action={}
            local room={GetGridIndex=function()return 0 end,GetGridPath=function()return 0 end,
                GetGridEntity=function()return nil end,GetDoor=function(_,slot)return slot==1 and {} or nil end}
            local function actualDoorPosition()return Vector(320,120)end
            local function doorSlotDirection()return Vector(0,-1)end
            game={GetRoom=function()return room end}
            Isaac={GetRoomEntities=function()return {}end}
            GRID_TRAPDOOR_TYPE=17
            local function gridEvent()return nil end
            local function redPoopGrid()return false end
            local function bombStillLive()return false end
        '''+safety+'''
            return function(x,y,mx,my,selected)
                action.mode=selected and 'navigate' or 'combat'
                action.id=selected and 'enter_door_'..selected or 'route_to_firing_lane'
                return safeMoveCandidate({Position=Vector(x,y)},Vector(mx,my),false)
            end
        ''')

    def test_combat_starts_braking_before_a_closed_curse_door(self):
        self.assertEqual(self.api(320,180,0,-1,None),(False,'unintended_room_exit'))
        self.assertTrue(self.api(320,180,-1,0,None)[0])

    def test_actual_overlap_can_retreat_inward_but_cannot_cross_outward(self):
        p=self.raw['player']['pos']
        self.assertTrue(self.api(p['x'],p['y'],0,1,None)[0])
        self.assertEqual(self.api(p['x'],p['y'],0,-1,None),(False,'unintended_room_exit'))

    def test_only_the_explicit_selected_slot_can_cross(self):
        self.assertTrue(self.api(320,180,0,-1,1)[0])
        self.assertEqual(self.api(320,180,0,-1,0),(False,'unintended_room_exit'))


if __name__=='__main__':unittest.main()
