"""The observed Eye Drops pickup route crossed the open trapdoor first."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class UnintendedFloorExitTests(unittest.TestCase):
    def setUp(self):
        rows=json.loads((ROOT/'tests/fixtures/stage1-boss-item-missed-native63.json').read_text())
        row=next(d['input'] for d in rows if d['frame']==4851)
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.globals().blocked=lua.table_from({i:True for i in row['room']['blocked']})
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        safety='local function safeMoveCandidate('+source.split('local function safeMoveCandidate(',1)[1].split('local function firstSafeMove',1)[0]
        route='local liveGridRoute = nil'+source.split('local liveGridRoute = nil',1)[1].split('local function clearTearLine',1)[0]
        route=route.replace('include("timed_spikes")','(function()\n'+(ROOT/'mods/IsaacJev/timed_spikes.lua').read_text(encoding='utf8')+'\nend)()')
        self.replay=lua.execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local frame=0
            local action={mode='item',id='take_item_1814'}
            GRID_TRAPDOOR_TYPE=17
            local room={GetGridWidth=function() return 15 end,GetGridSize=function() return 135 end,
                GetGridIndex=function(_,p) return math.floor((p.Y-100)/40)*15+math.floor((p.X-20)/40) end,
                GetGridPosition=function(_,i) return Vector(40+i%15*40,120+math.floor(i/15)*40) end,
                GetGridPath=function(_,i) return (i<0 or i>=135 or blocked[i]) and 1000 or 0 end}
            function room:GetGridEntity(i)
                if i==37 then return {GetType=function() return 17 end,Position=Vector(320,200)} end
            end
            local function gridEvent() return nil end
            local function currentRoomKey() return 'actual-boss-item-missed' end
            local function contactObstacle() return nil end
            local function isCombatEnemy() return false end
            local function redPoopGrid() return false end
            local function liveGridHazardKind() return nil end
            local function liveHazardKind() return nil end
            local function bombOnlyFireKind() return false end
            local function bombStillLive() return false end
            local function trackingBombInfo() return nil end
            local function isMovingSpikeTrap() return false end
            local function dangerousCreep() return false end
            EntityType={}
            Isaac={GetRoomEntities=function() return {} end}
            game={GetRoom=function() return room end,GetFrameCount=function() return frame end}
            local gridRouteControlled=false
        '''+safety+route+'''
            return function(exit)
                action.mode=exit and 'boss_exit' or 'item'
                action.id=exit and 'enter_boss_exit_37' or 'take_item_1814'
                liveGridRoute=nil
                local p={Position=Vector(490.2,193.5),Velocity=Vector(0,0),Size=10,MoveSpeed=1}
                local target=exit and Vector(320,200) or Vector(320,280)
                local minimum=math.huge
                for tick=1,300 do
                    frame=tick
                    local move=followGridRoute(p,target,8) or Vector(0,0)
                    local following=p.Velocity*.7+move*1.14
                    p.Position=p.Position+p.Velocity+following
                    p.Velocity=following
                    minimum=math.min(minimum,p.Position:Distance(Vector(320,200)))
                    if not exit and minimum<25 then return false,'premature floor transition' end
                    if p.Position:Distance(target)<10 then return true,tick,minimum end
                end
                return false,'did not reach target'
            end
        ''')

    def test_boss_reward_route_detours_around_open_trapdoor(self):
        completed,ticks,clearance=self.replay(False)
        self.assertTrue(completed,ticks)
        self.assertGreater(clearance,25)

    def test_explicit_exit_can_still_enter_the_same_trapdoor(self):
        completed,ticks,clearance=self.replay(True)
        self.assertTrue(completed,ticks)
        self.assertLess(clearance,10)


if __name__=='__main__': unittest.main()
