"""Replay the fatal native 120-frame rolling spikes with measured player inertia."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools/python-libs')]
from lupa.lua53 import LuaRuntime
from isaac_jev.models import Action,Entity,GameState,Vec2
from isaac_jev.runtime import Controller


class RollingSpikeWindowTests(unittest.TestCase):
    def setUp(self):
        trace=json.loads((ROOT/'tests/fixtures/stage5-timed-spike-fatal-trace.json').read_text(encoding='utf8'))
        lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua=lua
        lua.globals().blocked=lua.table_from({index:True for index in trace['input']['room']['blocked']})
        module=(ROOT/'mods/IsaacJev/timed_spikes.lua').read_text(encoding='utf8')
        self.cross=lua.execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local Navigator=(function()
        '''+module+'''
            end)()
            local room={GetGridWidth=function() return 15 end,GetGridSize=function() return 135 end,
                GetGridIndex=function(_,p) return math.floor((p.Y-100)/40)*15+math.floor((p.X-20)/40) end,
                GetGridPosition=function(_,i) return Vector(40+i%15*40,120+math.floor(i/15)*40) end,
                GetGridEntity=function(_,i) return i end}
            local frame=0
            local function active(index,at)
                if observedPhases then
                    return observedPhases[index]~=nil and (at-observedPhases[index])%120<60
                end
                if plateRoom then return index>=49 and index<=55 and (at-(index-49)*12)%120<60 end
                if index>=50 and index<=54 then return (at-(index-50)*12)%120<60 end
                if index>=80 and index<=84 then return (at-(60+(84-index)*12))%120<60 end
                return false
            end
            local function event(grid,index)
                if observedPhases then
                    if observedPhases[index]~=nil then return {kind='spike',timed=true,active=active(index,frame)} end
                    return nil
                end
                if plateRoom then
                    if index>=49 and index<=55 then return {kind='spike',timed=true,active=active(index,frame)} end
                    return nil
                end
                if (index>=50 and index<=54) or (index>=80 and index<=84) then
                    return {kind='spike',timed=true,active=active(index,frame)}
                end
            end
            local function walkable(index) return index>=0 and index<135 and not blocked[index] end
            return function(speed,phase,reverse)
                local nav=Navigator.new()
                local player={Position=Vector(observedPhases and 360 or (reverse and 80 or 550),observedPhases and 240 or 280),Velocity=Vector(0,0),MoveSpeed=speed}
                local goal=observedPhases and 71 or (plateRoom and 21 or (reverse and 73 or 61))
                local target=room:GetGridPosition(goal)
                local top,bottom=false,false
                for tick=1,(plateRoom and 1800 or 720) do
                    frame=phase+tick
                    nav:observe(room,frame,'fatal-room',event)
                    local move,waiting=nav:move(room,player,target,goal,frame,walkable)
                    if not move then return true,tick,top,bottom end
                    local velocity=player.Velocity*.7+move*(1.14*speed)
                    player.Position=player.Position+player.Velocity+velocity
                    player.Velocity=velocity
                    for index,history in pairs(nav.history) do
                        if math.abs(player.Position.X-history.position.X)<31
                            and math.abs(player.Position.Y-history.position.Y)<31 then
                            if active(index,frame) then
                                return false,'raised spike '..index..' at '..frame..' '..player.Position.X..','..player.Position.Y,top,bottom
                            end
                            if index<60 then top=true else bottom=true end
                        end
                    end
                end
                return false,nav.reason..' '..player.Position.X..','..player.Position.Y,top,bottom
            end
        ''')

    def test_measured_wave_is_crossed_without_damage_from_multiple_initial_phases(self):
        for speed in (1.,1.6):
            for phase in (0,25,70):
                with self.subTest(speed=speed,phase=phase):
                    complete,result,top,bottom=self.cross(speed,phase,False)
                    self.assertTrue(complete,result)
                    self.assertTrue(bottom)
                    self.assertFalse(top)

    def test_reverse_trip_uses_the_opposite_wave_lane(self):
        complete,result,top,bottom=self.cross(1.3,35,True)
        self.assertTrue(complete,result)
        self.assertTrue(top)
        self.assertFalse(bottom)

    def test_long_approach_and_plate_beyond_seven_spikes_are_not_outside_horizon(self):
        state=json.loads((ROOT/'tests/fixtures/stage5-no-enemy-uncleared.json').read_text(encoding='utf8'))
        self.lua.globals().blocked=self.lua.table_from({index:True for index in state['layout']['blocked']})
        self.lua.globals().plateRoom=True
        for phase in (0,70):
            complete,result,top,bottom=self.cross(1.5,phase,False)
            self.assertTrue(complete,result)
            self.assertTrue(top)

    def test_deliberate_cycle_observation_cannot_trigger_door_abandonment(self):
        with tempfile.TemporaryDirectory() as folder:
            controller=Controller(log_dir=folder)
            try:
                state=GameState(frame=250,room_clear=True,player=Entity(0,1,Vec2(),Vec2(),6),
                    enemies=(),projectiles=(),move_resolution_reason='timed_spike_wait',movement_blocked=True)
                controller._latest_action=Action('enter_door_0',Vec2(-1,0),Vec2(),mode='navigate')
                controller._movement_stall_count=100
                controller._update_movement_feedback(state)
                controller._update_navigation_stall(state)
                controller._abandon_blocked_door(state)
                self.assertEqual(controller._movement_stall_count,0)
                self.assertEqual(controller._stall_since_frame,250)
                self.assertFalse(controller._unreachable_door_edges)
            finally: controller.shutdown()

    def test_newly_observed_corner_corridor_respects_both_wave_lanes(self):
        raw=json.loads((ROOT/'tests/fixtures/stage5-timed-corridor-native73.json').read_text(encoding='utf8'))
        self.lua.globals().blocked=self.lua.table_from({i:True for i in raw['layout']['blocked']})
        self.lua.globals().observedPhases=self.lua.table_from({54:65,55:53,56:41,57:29,
            69:77,72:17,84:89,85:101,86:113,87:5})
        for speed in (1.,1.6):
            for phase in (0,25,70):
                with self.subTest(speed=speed,phase=phase):
                    complete,reason,_,_=self.cross(speed,phase,False)
                    self.assertTrue(complete,reason)


if __name__=='__main__': unittest.main()
