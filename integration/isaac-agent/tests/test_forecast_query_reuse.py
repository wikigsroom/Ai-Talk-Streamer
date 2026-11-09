"""Optimization must retain collision paths and invalidate at every prediction."""
import json
from pathlib import Path
import random
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime

API='''
local mt={}
Vector=function(x,y)return setmetatable({X=x,Y=y},mt)end
mt.__add=function(a,b)return Vector(a.X+b.X,a.Y+b.Y)end
mt.__sub=function(a,b)return Vector(a.X-b.X,a.Y-b.Y)end
mt.__mul=function(a,b)return Vector(a.X*b,a.Y*b)end
mt.__index={Length=function(a)return math.sqrt(a.X*a.X+a.Y*a.Y)end,
    Distance=function(a,b)return (a-b):Length()end}
local blocked,queries,sizeQueries={},{},0
local room={GetGridSize=function()sizeQueries=sizeQueries+1;return 135 end,
    GetGridIndex=function(_,p)return math.floor((p.Y-100)/40)*15+math.floor((p.X-20)/40)end,
    GetGridPosition=function(_,i)return Vector(i%15*40+40,math.floor(i/15)*40+120)end,
    GetGridPath=function(_,i)queries[i]=(queries[i] or 0)+1;return blocked[i] and 1000 or 0 end}
'''
WRAPPER='''
return {set=function(cells)blocked={};for _,i in ipairs(cells)do blocked[i]=true end end,
    predict=function(x,y,vx,vy,mx,my,speed,size)
        queries={};sizeQueries=0
        local p=movementForecast({Position=Vector(x,y),Velocity=Vector(vx,vy),MoveSpeed=speed,Size=size},Vector(mx,my),10,room)
        return p,queries,sizeQueries
    end,
    candidates=function()
        queries={};sizeQueries=0;local collision={}
        for _,m in ipairs({Vector(0,0),Vector(1,0),Vector(-1,0),Vector(0,1),Vector(0,-1),Vector(.7071,.7071),Vector(-.7071,.7071),Vector(.7071,-.7071),Vector(-.7071,-.7071)})do
            movementForecast({Position=Vector(320,280),Velocity=Vector(0,0),MoveSpeed=1,Size=10},m,10,room,collision)
        end
        return queries,sizeQueries
    end}
'''


class ForecastQueryReuseTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        source=(ROOT/'mods/IsaacJev/main.lua').read_text('utf8')
        current='local function movementForecast('+source.split('local function movementForecast(',1)[1].split('local function predictiveCombatMove',1)[0]
        old=(ROOT/'tests/fixtures/movement-forecast-before-fps.lua').read_text('utf8')
        self.current=self.lua.execute(API+current+WRAPPER)
        self.before=self.lua.execute(API+old+WRAPPER)

    def set_cells(self,cells):
        for api in (self.current,self.before):api['set'](self.lua.table_from(cells))

    @staticmethod
    def coordinates(path):return [(path[i]['X'],path[i]['Y']) for i in range(11)]

    def test_same_paths_for_native_geometry_and_seeded_inertia(self):
        fixture=ROOT/'tests/fixtures'
        cells=json.loads((fixture/'stage5-rock-corner-pinned-native83.json').read_text('utf8'))['input']['room']['blocked']
        cells+=json.loads((fixture/'stage1-door-overlap-native120.json').read_text('utf8'))['layout']['blocked']
        self.set_cells(cells)
        rng=random.Random(20261109)
        for _ in range(180):
            args=[rng.uniform(20,620),rng.uniform(100,420),rng.uniform(-5,5),rng.uniform(-5,5),rng.choice([-1,0,.7071,1]),rng.choice([-1,0,.7071,1]),rng.uniform(.3,1.8),rng.uniform(6,16)]
            with self.subTest(args=args):
                old,_,_=self.before['predict'](*args)
                new,_,_=self.current['predict'](*args)
                self.assertEqual(self.coordinates(new),self.coordinates(old))

    def test_free_cells_are_reused_and_door_change_is_observed_next_call(self):
        self.set_cells([])
        args=(320,280,0,0,1,0,1,10)
        open_path,queries,sizes=self.current['predict'](*args)
        self.assertTrue(all(value==1 for _,value in queries.items()))
        self.assertLess(len(list(queries.items())),20)
        self.assertEqual(sizes,1)
        expected=self.coordinates(open_path)
        self.set_cells([68])
        blocked_path,_,_=self.current['predict'](*args)
        old_path,_,_=self.before['predict'](*args)
        self.assertEqual(self.coordinates(blocked_path),self.coordinates(old_path))
        self.assertLess(blocked_path[10]['X'],open_path[10]['X'])
        self.set_cells([])
        reopened,_,_=self.current['predict'](*args)
        self.assertEqual(self.coordinates(reopened),expected)

    def test_nine_candidates_share_only_synchronous_collision_reads(self):
        self.set_cells([])
        queries,sizes=self.current['candidates']()
        self.assertGreater(len(list(queries.items())),4)
        self.assertTrue(all(value==1 for _,value in queries.items()))
        self.assertEqual(sizes,1)
        next_queries,next_sizes=self.current['candidates']()
        self.assertEqual(dict(next_queries.items()),dict(queries.items()))
        self.assertEqual(next_sizes,1)


if __name__=='__main__':unittest.main()
