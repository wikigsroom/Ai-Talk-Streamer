"""Replay pre-charge observations with native inertia and the actual walls."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class GurdyReactionSpaceTests(unittest.TestCase):
    def replay(self,frame):
        s=json.loads((ROOT/f'tests/fixtures/stage3-gurdy-jr-approach-{frame}-native91.json').read_text(encoding='utf8'))['input']
        p=s['player'];e=s['nearby_enemies'][0];r=s['room']
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.globals().blocked=lua.table_from({i:True for i in r['blocked']})
        lua.globals().p=lua.table_from({'x':p['position']['x'],'y':p['position']['y'],
            'vx':p['velocity']['x'],'vy':p['velocity']['y']})
        lua.globals().e=lua.table_from({'x':p['position']['x']+e['offset']['x'],
            'y':p['position']['y']+e['offset']['y'],'vx':e['velocity']['x'],'vy':e['velocity']['y']})
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        planner='local function hostileLaser(entity)'+source.split('local function hostileLaser(entity)',1)[1].split('local function resolveSafeMove(player, navigationBlocked)',1)[0]
        planner='local function combatVelocity(entity)'+source.split('local function combatVelocity(entity)',1)[1].split('local function hasCombatEnemy()',1)[0]+planner
        return lua.execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            EntityType={ENTITY_PROJECTILE=9,ENTITY_LASER=7,ENTITY_PLAYER=1,ENTITY_FAMILIAR=3}
            local enemy={Type=99,Index=2,Size=32,Position=Vector(e.x,e.y),Velocity=Vector(e.vx,e.vy)}
            Isaac={GetRoomEntities=function() return {enemy} end}
            local room={GetGridWidth=function() return 15 end,GetGridSize=function() return 135 end,
                GetGridIndex=function(_,p) return math.floor((p.Y-100)/40)*15+math.floor((p.X-20)/40) end,
                GetGridPath=function(_,i) return (i<0 or i>=135 or blocked[i]) and 1000 or 0 end}
            game={GetRoom=function() return room end,GetFrameCount=function() return 100 end}
            local player={Position=Vector(p.x,p.y),Velocity=Vector(p.vx,p.vy),Size=10,MoveSpeed=1.3,TearRange=360}
            local toward=enemy.Position-player.Position
            local direction=math.abs(toward.X)>math.abs(toward.Y) and Vector(toward.X>0 and 1 or -1,0)
                or Vector(0,toward.Y>0 and 1 or -1)
            local action={move=direction,mode='combat',waypoint=enemy.Position}
            local lastResolvedMove=Vector(0,0)
            local combatAimTargetId,combatAimLockFrame=-1,-10000
            local function followGridRoute() return direction end
            local function isCombatEnemy() return true end
            local function isMovingSpikeTrap() return false end
            local function safeMoveCandidate(p,m)
                return room:GetGridPath(room:GetGridIndex(p.Position+m*28))<1000
            end
            local function clearTearLine() return true end
        '''+planner+'''
            local move=predictiveCombatMove(player)
            local forecast=movementForecast(player,move,10,room)
            return move.X,move.Y,player.Position:Distance(enemy.Position),forecast[5]:Distance(enemy.Position),
                room:GetGridPath(room:GetGridIndex(forecast[5]))
        ''')

    def test_close_observed_charge_positions_reject_the_approach_and_gain_space(self):
        for frame in (20103,20115,20310,20322):
            with self.subTest(frame=frame):
                x,y,before,after,path=self.replay(frame)
                self.assertGreater(abs(x)+abs(y),0)
                self.assertGreater(after,before)
                self.assertLess(path,1000)


if __name__=='__main__': unittest.main()
