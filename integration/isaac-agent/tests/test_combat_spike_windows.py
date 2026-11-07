"""Combat inputs must respect the same closing windows as timed navigation."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class CombatSpikeWindowTests(unittest.TestCase):
    def setUp(self):
        rows=json.loads((ROOT/'tests/fixtures/stage8-spikes-native119.json').read_text(encoding='utf8'))
        self.raw=next(s for s in rows if s['frame']==57109)
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.globals().events=lua.table_from([lua.table_from(dict(index=e['grid_index'],x=e['pos']['x'],y=e['pos']['y'])) for e in self.raw['layout']['grid_events']])
        module=(ROOT/'mods/IsaacJev/timed_spikes.lua').read_text(encoding='utf8')
        self.api=lua.execute('''
            local mt={}
            Vector=function(x,y)return setmetatable({X=x,Y=y},mt)end
            mt.__add=function(a,b)return Vector(a.X+b.X,a.Y+b.Y)end
            mt.__sub=function(a,b)return Vector(a.X-b.X,a.Y-b.Y)end
            mt.__mul=function(a,b)return Vector(a.X*b,a.Y*b)end
            mt.__index={Length=function(a)return math.sqrt(a.X*a.X+a.Y*a.Y)end,
                Distance=function(a,b)return (a-b):Length()end}
            local Navigator=(function()
        '''+module+'''
            end)()
            return function(px,py,vx,vy,speed,frame,mx,my,fly,unknown)
                local nav=Navigator.new()
                for _,e in ipairs(events)do
                    nav.history[e.index]={position=Vector(e.x,e.y),active=false,since=57053,
                        durations=unknown and {} or {[0]=60,[1]=60}}
                end
                local p={Position=Vector(px,py),Velocity=Vector(vx,vy),MoveSpeed=speed,CanFly=fly}
                return nav:motionSafe(p,Vector(mx,my),frame),nav:exposure(p.Position,frame+4)
            end
        ''')

    def test_actual_near_spike_geometry_rejects_approach_and_allows_escape(self):
        # This 60/60 cycle is consistent with the recorded last OFF at 57109
        # and first ON at 57124; the sparse trace does not prove its exact phase.
        p=self.raw['player']
        args=(p['pos']['x'],p['pos']['y'],p['vel']['x'],p['vel']['y'],p['move_speed'],self.raw['frame'])
        self.assertFalse(self.api(*args,-1,0,False,False)[0])
        self.assertTrue(self.api(*args,1,0,False,False)[0])

    def test_staying_in_the_closing_spike_has_a_cost_even_with_zero_input(self):
        p=self.raw['player']
        safe,cost=self.api(p['pos']['x'],p['pos']['y'],0,0,1.5,57109,0,0,False,False)
        self.assertFalse(safe)
        self.assertGreater(cost,0)
        self.assertEqual(self.api(580,280,0,0,1.5,57109,0,0,False,False)[1],0)

    def test_a_genuine_open_window_and_flight_keep_movement_available(self):
        p=self.raw['player']
        args=(p['pos']['x'],p['pos']['y'],0,0,p['move_speed'])
        self.assertTrue(self.api(*args,57070,-1,0,False,False)[0])
        self.assertTrue(self.api(*args,57109,-1,0,True,False)[0])

    def test_unknown_cycle_does_not_admit_a_new_spike_entry(self):
        self.assertFalse(self.api(580,280,0,0,1.5,57109,-1,0,False,True)[0])
        self.assertFalse(self.api(580,280,0,0,1.5,57109,1,0,False,True)[0])
        self.assertTrue(self.api(580,280,0,0,1.5,57109,0,-1,False,True)[0])


if __name__=='__main__':unittest.main()
