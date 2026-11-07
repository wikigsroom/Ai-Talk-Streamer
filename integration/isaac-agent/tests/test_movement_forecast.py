"""Check the movement forecast against recorded native positions and inertia."""
import json
import math
import statistics
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class MovementForecastTests(unittest.TestCase):
    def wall_forecast(self,x,y,vx,vy,mx,my,horizon):
        observed=json.loads((ROOT/'tests/fixtures/stage5-rock-corner-pinned-native83.json').read_text(encoding='utf8'))['input']
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='local function movementForecast('+source.split('local function movementForecast(',1)[1].split('local function predictiveCombatMove',1)[0]
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.globals().blocked=lua.table_from({i:True for i in observed['room']['blocked']})
        api=lua.execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            local room={GetGridWidth=function() return 15 end,GetGridSize=function() return 135 end,
                GetGridIndex=function(_,p) return math.floor((p.Y-100)/40)*15+math.floor((p.X-20)/40) end,
                GetGridPath=function(_,i) return blocked[i] and 1000 or 0 end}
        '''+helper+'''
            return function(x,y,vx,vy,mx,my,t)
                return movementForecast({Position=Vector(x,y),Velocity=Vector(vx,vy),MoveSpeed=1.3,Size=10},Vector(mx,my),t,room)
            end
        ''')
        path=api(x,y,vx,vy,mx,my,horizon)
        return [(path[t]['X'],path[t]['Y']) for t in range(1,horizon+1)]

    def test_actual_rock_pocket_forecast_stops_at_wall_instead_of_inventing_escape(self):
        positions=self.wall_forecast(560,230,0,-4.9,0,-1,20)
        self.assertTrue(all(y>=189 for x,y in positions))
        self.assertGreater(positions[-1][1],100)

    def test_actual_rock_geometry_permits_sliding_along_free_axis(self):
        positions=self.wall_forecast(550,230,0,0,-.7071,-.7071,10)
        self.assertLess(positions[-1][0],550)
        blocked=set(json.loads((ROOT/'tests/fixtures/stage5-rock-corner-pinned-native83.json').read_text(encoding='utf8'))['input']['room']['blocked'])
        for x,y in positions:
            self.assertNotIn(int((y-100)//40)*15+int((x-20)//40),blocked)

    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='local function movementForecast('+source.split('local function movementForecast(',1)[1].split('local function predictiveCombatMove',1)[0]
        self.predict=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
        '''+helper+'''
            return function(x,y,vx,vy,mx,my,t)
                local path=movementForecast({Position=Vector(x,y),Velocity=Vector(vx,vy),MoveSpeed=1},Vector(mx,my),t)
                return path[t].X,path[t].Y
            end
        ''')

    def test_released_input_still_predicts_native_inertia(self):
        x,y=self.predict(200,200,4,0,0,0,1)
        self.assertGreater(x,204)
        self.assertEqual(y,200)

    def test_forecast_tracks_actual_game_samples_better_than_instant_constant_speed(self):
        rows=json.loads((ROOT/'tests/fixtures/native-movement-samples.json').read_text())['rows']
        errors,old_errors=[],[]
        for a,b in zip(rows,rows[1:]):
            if b['frame']-a['frame']!=1:
                continue
            x,y=self.predict(a['x'],a['y'],a['vx'],a['vy'],a['mx'],a['my'],1)
            errors.append(math.hypot(x-b['x'],y-b['y']))
            old_errors.append(math.hypot(a['x']+a['mx']*6-b['x'],a['y']+a['my']*6-b['y']))
        self.assertGreater(len(errors),40)
        self.assertLess(statistics.median(errors),1.5)
        self.assertLess(statistics.mean(errors),statistics.mean(old_errors))


if __name__=='__main__':
    unittest.main()
