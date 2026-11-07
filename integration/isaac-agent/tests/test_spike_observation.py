"""An interrupted phase observation must not invent longer safe windows."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class SpikeObservationTests(unittest.TestCase):
    def test_pressed_plate_invalidates_a_cycle_that_no_longer_occurs(self):
        module=(ROOT/'mods/IsaacJev/timed_spikes.lua').read_text(encoding='utf8')
        replay=LuaRuntime(unpack_returned_tuples=True).execute('''
            Vector=function(x,y) return {X=x,Y=y} end
            local Navigator=(function()
        '''+module+'''
            end)()
            return function()
                local nav=Navigator.new()
                local room={GetGridSize=function() return 1 end,
                    GetGridEntity=function() return {} end,
                    GetGridPosition=function() return Vector(0,0) end}
                local function observe(at)
                    nav:observe(room,at,'plate-latches-off',function()
                        return {kind='spike',timed=true,active=at<240 and at%120<60}
                    end)
                end
                for at=1,239 do observe(at) end
                nav.plan={old=true}
                for at=240,301 do observe(at) end
                return nav.plan==nil,nav:ready(301),nav:safe(0,340),nav:safe(0,400)
            end
        ''')
        invalidated,ready,near,later=replay()
        self.assertTrue(invalidated,'a lowered plate must discard the old cyclic path')
        self.assertTrue(ready)
        self.assertTrue(near)
        self.assertTrue(later)

    def test_blind_interval_cannot_extend_a_real_sixty_frame_off_window(self):
        module=(ROOT/'mods/IsaacJev/timed_spikes.lua').read_text(encoding='utf8')
        replay=LuaRuntime(unpack_returned_tuples=True).execute('''
            Vector=function(x,y) return {X=x,Y=y} end
            local Navigator=(function()
        '''+module+'''
            end)()
            return function()
                local nav=Navigator.new()
                local room={GetGridSize=function() return 1 end,
                    GetGridEntity=function() return {} end,
                    GetGridPosition=function() return Vector(0,0) end}
                local function observe(at)
                    nav:observe(room,at,'measured-sixty-frame-wave',function()
                        return {kind='spike',timed=true,active=at%120<60}
                    end)
                end
                for at=1,180 do observe(at) end
                local learned=nav:ready(180)
                nav.plan={old=true}
                observe(250)
                local unsafeForecast=nav:safe(0,365)
                local waiting=not nav:ready(250) and nav.plan==nil
                for at=251,425 do observe(at) end
                return learned,unsafeForecast,waiting,nav:ready(425),nav:safe(0,365)
            end
        ''')
        learned,unsafe,waiting,relearned,unsafe_after_relearning=replay()
        self.assertTrue(learned)
        self.assertFalse(unsafe,'frame 365 is a raised phase of the observed 120-frame cycle')
        self.assertTrue(waiting)
        self.assertTrue(relearned)
        self.assertFalse(unsafe_after_relearning)


if __name__=='__main__': unittest.main()
