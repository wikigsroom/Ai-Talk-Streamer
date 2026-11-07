"""Regression for the observed stage 6 alternating-spike corridor."""
import json
import math
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools/python-libs"))
from isaac_jev.models import GameState, Vec2
from isaac_jev.navigation import door_path_distance, path_distance
from isaac_jev.runtime import Controller
from lupa.lua53 import LuaRuntime


class TimedSpikeRouteTests(unittest.TestCase):
    def setUp(self):
        self.state = GameState.from_message(json.loads(
            (ROOT / "tests/fixtures/stage6-timed-spike-corridor.json").read_text(encoding="utf-8")))
        events = tuple(replace(event, active=True) for event in self.state.layout.grid_events)
        self.state = replace(self.state, layout=replace(self.state.layout,
            grid_events=events, danger_grid_indices=frozenset(event.grid_index for event in events)))
        self.east = next(door for door in self.state.layout.doors if door.slot == 2)

    def test_temporarily_closed_branch_remains_a_navigation_goal(self):
        self.assertTrue(all(event.timed for event in self.state.layout.grid_events))
        self.assertTrue(math.isfinite(door_path_distance(self.state, self.east)))
        # Admitting a future route never makes the current movement path safe.
        self.assertTrue(math.isinf(path_distance(self.state, Vec2(), 73)))

    def test_permanent_spikes_are_never_relaxed_for_navigation(self):
        state = replace(self.state, layout=replace(self.state.layout,
            grid_events=tuple(replace(event, timed=False) for event in self.state.layout.grid_events)))
        self.assertTrue(math.isinf(door_path_distance(state, self.east)))

    def test_unvisited_branch_replaces_commitment_to_entry_door(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = Controller(log_dir=folder)
            try:
                controller._current_room_index = 122
                controller._visited_rooms = {121, 122}
                controller._room_graph[122] = self.state.layout.doors
                controller._room_intel[56] = {"room_type": "treasure", "clear": True}
                controller._committed_door_room = 122
                controller._committed_door_slot = 0
                self.assertEqual(controller._plan_next_door(self.state)[0], 2)
            finally:
                controller.shutdown()

    def test_native_route_waits_for_a_safe_window_and_then_crosses(self):
        source = (ROOT / "mods/IsaacJev/main.lua").read_text(encoding="utf-8")
        helper = "local liveGridRoute = nil" + source.split("local liveGridRoute = nil", 1)[1].split(
            "local function clearTearLine", 1)[0]
        helper=helper.replace('include("timed_spikes")','(function()\n'+(ROOT/'mods/IsaacJev/timed_spikes.lua').read_text(encoding='utf8')+'\nend)()')
        api = LuaRuntime(unpack_returned_tuples=True).execute("""
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local frame=0
            local detour=false
            local room={GetGridWidth=function() return 9 end,GetGridSize=function() return 27 end,
                GetGridPosition=function(_,i) return Vector(i%9*40+20,math.floor(i/9)*40+20) end,
                GetGridIndex=function(_,p) return math.floor(p.Y/40)*9+math.floor(p.X/40) end}
            function room:GetGridPath(i)
                if detour and math.floor(i/9)==2 and i%9>0 and i%9<8 then return 0 end
                return (math.floor(i/9)~=1 or i%9==0 or i%9==8) and 1000 or 0
            end
            function room:GetGridEntity(i) return {index=i} end
            game={GetRoom=function() return room end,GetFrameCount=function() return frame end}
            Isaac={GetRoomEntities=function() return {} end}
            local function currentRoomKey() return 'timed-corridor' end
            local function contactObstacle() return nil end
            local function redPoopGrid() return false end
            local function gridEvent(grid,index)
                if index>=12 and index<=14 then
                    return {kind='spike',timed=true,active=frame<60}
                end
                return nil
            end
            local function safeMoveCandidate(player,move)
                for step=1,28 do
                    local index=room:GetGridIndex(player.Position+move*step)
                    if room:GetGridPath(index)>=1000 then return false,'grid_wall' end
                    local event=gridEvent(nil,index)
                    if event and event.active then return false,'spike_or_tnt' end
                end
                return true,'safe'
            end
            local gridRouteControlled=false
        """ + helper + """
            return function(useDetour)
                detour=useDetour==true
                liveGridRoute=nil
                local player={Position=Vector(60,60)}
                local target=Vector(300,60)
                local waited=false
                for tick=1,360 do
                    frame=tick
                    local move=followGridRoute(player,target,8)
                    if not move then return false,'lost temporal route' end
                    local nextPosition=player.Position+move*6
                    local event=gridEvent(nil,room:GetGridIndex(nextPosition))
                    if detour and event then return false,'ignored a stable detour' end
                    if event and event.active then return false,'stepped on raised spike' end
                    if tick<60 and move:Length()==0 then waited=true end
                    player.Position=nextPosition
                    if player.Position:Distance(target)<=8 then
                        followGridRoute(player,target,8)
                        if timedSpikeNavigator.active then return false,'arrived route still owns movement' end
                        return detour or waited,tick
                    end
                end
                return false,'never crossed'
            end
        """)
        completed, result = api()
        self.assertTrue(completed, result)
        self.assertLess(result, 330)
        completed,result=api(True)
        self.assertTrue(completed,result)
        self.assertLess(result,60)


if __name__ == "__main__":
    unittest.main()
