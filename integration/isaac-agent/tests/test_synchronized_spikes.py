"""Replay the actual two-plate room with synchronized 60-frame safe windows."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class SynchronizedSpikeTests(unittest.TestCase):
    def test_both_plates_and_return_without_raised_spike_contact(self):
        raw=json.loads((ROOT/'tests/fixtures/stage3-timed-plate-977822611.json').read_text())
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.globals().blocked=lua.table_from({i:True for i in raw['layout']['blocked']})
        lua.globals().spikes=lua.table_from({e['grid_index']:True for e in raw['layout']['grid_events'] if e['kind']=='spike'})
        module=(ROOT/'mods/IsaacJev/timed_spikes.lua').read_text(encoding='utf8')
        replay=lua.execute('''
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
            local function walkable(i) return i>=0 and i<135 and not blocked[i] end
            return function(phase)
                local nav=Navigator.new()
                local p={Position=Vector(541.2,280),Velocity=Vector(0,0),MoveSpeed=1.2}
                local goals={42,92,72}
                local current=1
                for tick=1,2400 do
                    local frame=phase+tick
                    nav:observe(room,frame,'actual-synchronized-room',function(_,i)
                        if spikes[i] then return {kind='spike',timed=true,active=frame%120<60} end
                    end)
                    local goal=goals[current]
                    local move=nav:move(room,p,room:GetGridPosition(goal),goal,frame,walkable)
                    if not move then
                        current=current+1
                        if current>#goals then return true,tick end
                        move=Vector(0,0)
                    end
                    local following=p.Velocity*.7+move*(1.14*p.MoveSpeed)
                    p.Position=p.Position+p.Velocity+following
                    p.Velocity=following
                    if not walkable(room:GetGridIndex(p.Position)) then return false,'pit/wall at '..frame end
                    for i in pairs(spikes) do
                        local position=room:GetGridPosition(i)
                        if math.abs(p.Position.X-position.X)<31 and math.abs(p.Position.Y-position.Y)<31
                            and frame%120<60 then return false,'raised spike '..i..' at '..frame end
                    end
                end
                return false,'goal '..goals[current]..': '..nav.reason..' '..p.Position.X..','..p.Position.Y
            end
        ''')
        for phase in (0,25,70):
            with self.subTest(phase=phase):
                complete,reason=replay(phase)
                self.assertTrue(complete,reason)


if __name__=='__main__': unittest.main()
