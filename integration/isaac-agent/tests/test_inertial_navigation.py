"""Run the actual Lua safety and routing together using measured inertia."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/python-libs"))
from lupa.lua53 import LuaRuntime


class InertialNavigationTests(unittest.TestCase):
    def setUp(self):
        self.load_fixture("stage6-room124-spikes.json")

    def load_fixture(self, filename):
        source = (ROOT / "mods/IsaacJev/main.lua").read_text(encoding="utf-8")
        safety = "local function safeMoveCandidate(" + source.split("local function safeMoveCandidate(", 1)[1].split("local function firstSafeMove", 1)[0]
        route = "local liveGridRoute = nil" + source.split("local liveGridRoute = nil", 1)[1].split("local function clearTearLine", 1)[0]
        route=route.replace('include("timed_spikes")','(function()\n'+(ROOT/'mods/IsaacJev/timed_spikes.lua').read_text(encoding='utf8')+'\nend)()')
        escape = "local function gridDangerClearance(" + source.split("local function gridDangerClearance(", 1)[1].split("local function hostileLaser", 1)[0]
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        state = json.loads((ROOT / "tests/fixtures" / filename).read_text(encoding="utf8"))
        self.lua.globals().blocked = self.lua.table_from({i: True for i in state["layout"]["blocked"]})
        self.lua.globals().spikes = self.lua.table_from({e["grid_index"]: True for e in state["layout"]["grid_events"]})
        self.api = self.lua.execute("""
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local frame=0
            local room={GetGridWidth=function() return 15 end,GetGridSize=function() return 135 end,
                GetGridIndex=function(_,p) return math.floor((p.Y-100)/40)*15+math.floor((p.X-20)/40) end,
                GetGridPosition=function(_,i) return Vector(40+i%15*40,120+math.floor(i/15)*40) end,
                GetGridPath=function(_,i) return (i<0 or i>=135 or blocked[i]) and 1000 or 0 end}
            function room:GetGridEntity(i)
                return spikes[i] and {Position=self:GetGridPosition(i)} or nil
            end
            local function gridEvent(g)
                return g and {kind='spike',active=true,pos={x=g.Position.X,y=g.Position.Y}} or nil
            end
            local function currentRoomKey() return 'native-room124' end
            local function contactObstacle() return nil end
            local function isCombatEnemy(e) return e.Type==12 end
            local function redPoopGrid() return false end
            local function liveGridHazardKind() return nil end
            local function liveHazardKind() return nil end
            local function bombOnlyFireKind() return false end
            local function bombStillLive() return false end
            local function trackingBombInfo() return nil end
            local function isMovingSpikeTrap() return false end
            local function dangerousCreep() return false end
            EntityType={ENTITY_PROJECTILE=9}
            local entities={}
            Isaac={GetRoomEntities=function() return entities end}
            game={GetRoom=function() return room end,GetFrameCount=function() return frame end}
            local gridRouteControlled=false
        """ + safety + route + escape + """
            return {simulate=function(x,y,vx,vy,tx,ty,ex,ey)
                liveGridRoute=nil
                entities=ex and {{Type=12,Position=Vector(ex,ey),Size=12}} or {}
                local p={Position=Vector(x,y),Velocity=Vector(vx,vy),Size=10,MoveSpeed=1}
                local target=Vector(tx or 320,ty or 160)
                local minimum=math.huge
                for tick=1,600 do
                    frame=tick
                    local move=escapeGridDanger(p) or followGridRoute(p,target,8) or Vector(0,0)
                    local old=p.Velocity
                    p.Velocity=old*0.7+move*1.14
                    local nextPosition=p.Position+old+p.Velocity
                    if room:GetGridPath(room:GetGridIndex(nextPosition))<1000 then p.Position=nextPosition
                    else p.Velocity=Vector(0,0) end
                    for index in pairs(spikes) do
                        minimum=math.min(minimum,gridDangerClearance(p,p.Position,room:GetGridPosition(index)))
                    end
                    for _,enemy in ipairs(entities) do
                        minimum=math.min(minimum,p.Position:Distance(enemy.Position)-(p.Size+enemy.Size+26))
                    end
                    if p.Position:Distance(target)<10 then return true,tick,minimum,p.Position.X,p.Position.Y end
                end
                return false,600,minimum,p.Position.X,p.Position.Y
            end}
        """)

    def test_leaves_observed_spike_corner_without_oscillation(self):
        completed,ticks,clearance,x,y = self.api.simulate(325.1,214.6,1,-.7)
        self.assertTrue(completed, (ticks,clearance,x,y))
        self.assertLess(ticks,180)
        self.assertGreater(clearance,-1)

    def test_crosses_spike_room_from_the_actual_entry_lane(self):
        completed,ticks,clearance,x,y = self.api.simulate(80,280,1,0)
        self.assertTrue(completed, (ticks,clearance,x,y))
        self.assertGreater(clearance,-1)

    def test_firing_lane_route_does_not_plan_through_enemy_contact(self):
        self.load_fixture("stage2-inertial-lane-stop.json")
        completed,ticks,clearance,x,y = self.api.simulate(389.1,234.8,0,-1.1,440,160,440,280)
        self.assertTrue(completed, (ticks,clearance,x,y))
        self.assertGreater(clearance,-1)


if __name__ == "__main__":
    unittest.main()
