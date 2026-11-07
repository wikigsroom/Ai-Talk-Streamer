"""Replay the actual retreat that let three Globins seal a rock pocket."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class CombatPocketTests(unittest.TestCase):
    def replay(self, routed):
        row=json.loads((ROOT/'tests/fixtures/stage5-globin-pocket-approach.json').read_text(encoding='utf8'))
        observed=row['input']
        lua=LuaRuntime(unpack_returned_tuples=True)
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        planner='local function hostileLaser(entity)'+source.split('local function hostileLaser(entity)',1)[1].split('local function resolveSafeMove(player, navigationBlocked)',1)[0]
        lua.globals().blocked=lua.table_from({i:True for i in observed['room']['blocked']})
        p=observed['player']
        lua.globals().px=p['position']['x'];lua.globals().py=p['position']['y']
        lua.globals().vx=p['velocity']['x'];lua.globals().vy=p['velocity']['y']
        lua.globals().routed=routed
        enemies=[]
        for index,e in enumerate(observed['nearby_enemies']):
            enemies.append(dict(Type=e['type'],Index=index,HitPoints=e['hp'],Size=13,
                x=p['position']['x']+e['offset']['x'],y=p['position']['y']+e['offset']['y'],
                vx=e['velocity']['x'],vy=e['velocity']['y']))
        lua.globals().observed=lua.table_from([lua.table_from(e) for e in enemies])
        return lua.execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local entities={}
            for _,e in ipairs(observed) do
                e.Position,e.Velocity=Vector(e.x,e.y),Vector(e.vx,e.vy)
                entities[#entities+1]=e
            end
            EntityType={ENTITY_PROJECTILE=9,ENTITY_LASER=7,ENTITY_PLAYER=1,ENTITY_FAMILIAR=3}
            Isaac={GetRoomEntities=function() return entities end}
            local room={GetGridWidth=function() return 28 end,GetGridSize=function() return 448 end,
                GetGridIndex=function(_,p) return math.floor((p.Y-100)/40)*28+math.floor((p.X-20)/40) end,
                GetGridPath=function(_,i) return blocked[i] and 1000 or 0 end}
            game={GetRoom=function() return room end,GetFrameCount=function() return 35720 end}
            local action={move=Vector(0,-1),mode='combat',waypoint=routed and Vector(880,360) or nil}
            local lastResolvedMove=Vector(0,1)
            local combatAimTargetId,combatAimLockFrame=-1,-10000
            local function followGridRoute() return Vector(0,1) end
            local function isCombatEnemy(e) return e.Type==24 end
            local function isMovingSpikeTrap() return false end
            local function safeMoveCandidate(p,m)
                return room:GetGridPath(room:GetGridIndex(p.Position+m*28))<1000
            end
            local function clearTearLine() return true end
        '''+planner+'''
            local p={Position=Vector(px,py),Velocity=Vector(vx,vy),Size=10,MoveSpeed=1,TearRange=460}
            local move=predictiveCombatMove(p)
            local forecast=movementForecast(p,move,10)
            return move.X,move.Y,room:GetGridIndex(forecast[10])
        ''')

    def test_safety_rewrite_and_route_both_keep_out_of_observed_one_exit_pocket(self):
        for routed in (False,True):
            with self.subTest(routed=routed):
                x,y,index=self.replay(routed)
                self.assertNotEqual(index,220)
                self.assertFalse(x==0 and y==1,'the observed downward retreat was fatal')


if __name__=='__main__': unittest.main()
