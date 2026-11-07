"""A head travelling toward a wall can return into Isaac's route."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class BouncingContactTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='local bouncePaths={}'+source.split('local bouncePaths={}',1)[1].split('local tntThreat=',1)[0]
        self.api=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            return function(kind,variant,px,vx,object)
                local entity={Type=kind,Variant=variant,Position=Vector(80,200),Velocity=Vector(vx,0),Size=12}
                local contacts={entity}
                local player={Position=Vector(px,200)}
                local room={GetGridIndex=function(_,point) return math.floor(point.Y/10)*1000+math.floor(point.X/10) end,
                    GetGridSize=function() return 100000 end,
                    GetGridCollision=function(_,index)
                        local x,y=(index%1000)*10,math.floor(index/1000)*10
                        if x<60 or x>560 or y<60 or y>440 then return 4 end
                        if object and x==120 then return 2 end
                        return 0
                    end}
            '''+helper+'''
                local forecast={}
                for tick=0,10 do forecast[tick]=player.Position end
                local path=bouncePaths[entity]
                return contactClearance(entity,forecast,10),path and path[10].X or nil,
                    path and path[1].X or nil
            end
        ''')

    def test_rebound_toward_player_is_seen_before_the_head_reaches_the_wall(self):
        clearance,x,_=self.api(212,0,150,-4,False)
        self.assertLess(clearance,15)
        self.assertGreater(x,130)

    def test_flying_head_does_not_reflect_from_an_ordinary_rock(self):
        _,x,_=self.api(212,0,300,4,True)
        self.assertEqual(x,160)

    def test_straight_path_is_retained_when_collision_size_is_uncertain(self):
        clearance,_,_=self.api(212,0,60,-4,False)
        self.assertAlmostEqual(clearance,0)

    def test_peep_eye_reflects_but_ordinary_chasing_body_keeps_its_model(self):
        self.assertLess(self.api(68,10,150,-4,False)[0],15)
        self.assertEqual(self.api(68,0,150,-4,False),(70,None,None))
        self.assertEqual(self.api(10,0,150,-4,False),(70,None,None))


if __name__=='__main__': unittest.main()
