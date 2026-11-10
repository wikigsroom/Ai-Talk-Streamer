"""Use the existing post-hit grace to leave the actual lethal Globin pocket."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class DamageGraceEscapeTests(unittest.TestCase):
    def replay(self, grace):
        observed=json.loads((ROOT/'tests/fixtures/stage3-globin-loss-28749-native85.json').read_text(encoding='utf8'))['input']
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.globals().blocked=lua.table_from({i:True for i in observed['room']['blocked']})
        lua.globals().grace=grace
        p=observed['player']
        lua.globals().px=p['position']['x'];lua.globals().py=p['position']['y']
        enemies=[]
        for i,e in enumerate(observed['nearby_enemies']):
            enemies.append(lua.table_from({'Type':e['type'],'Index':i,'Size':13,'HitPoints':e['hp'],
                'x':p['position']['x']+e['offset']['x'],'y':p['position']['y']+e['offset']['y'],
                'vx':e['velocity']['x'],'vy':e['velocity']['y'],'animation':e['telegraph']}))
        lua.globals().observed=lua.table_from(enemies)
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
            local entities={}
            for _,e in ipairs(observed) do
                e.Position,e.Velocity=Vector(e.x,e.y),Vector(e.vx,e.vy)
                e.GetSprite=function() return {GetAnimation=function() return e.animation end} end
                entities[#entities+1]=e
            end
            EntityType={ENTITY_PROJECTILE=9,ENTITY_LASER=7,ENTITY_PLAYER=1,ENTITY_FAMILIAR=3}
            Isaac={GetRoomEntities=function() return entities end}
            local room={GetGridWidth=function() return 28 end,GetGridSize=function() return 448 end,
                GetGridIndex=function(_,p) return math.floor((p.Y-100)/40)*28+math.floor((p.X-20)/40) end,
                GetGridPath=function(_,i) return (i<0 or i>=448 or blocked[i]) and 1000 or 0 end}
            game={GetRoom=function() return room end,GetFrameCount=function() return 28750 end}
            local action={move=Vector(-1,0),mode='combat',waypoint=Vector(600,680)}
            local lastResolvedMove=Vector(0,0)
            local combatAimTargetId,combatAimLockFrame=-1,-10000
            local function followGridRoute() return nil end
            local function isCombatEnemy(e) return e.Type==24 end
            local function isMovingSpikeTrap() return false end
            local function safeMoveCandidate(p,m)
                return room:GetGridPath(room:GetGridIndex(p.Position+m*28))<1000
            end
            local function clearTearLine() return true end
        '''+planner+'''
            local p={Position=Vector(px,py),Velocity=Vector(0,0),Size=10,MoveSpeed=1,TearRange=260,
                GetDamageCooldown=function() return grace end}
            local move=predictiveCombatMove(p)
            local forecast=movementForecast(p,move,10,room)
            return move.X,move.Y,forecast[10].X,forecast[10].Y,room:GetGridIndex(forecast[10])
        ''')

    def test_available_native_grace_leaves_the_pocket_through_its_only_exit(self):
        x,y,fx,fy,index=self.replay(58)
        self.assertLess(x,0)
        self.assertLess(fx,700)
        self.assertNotEqual(index,409)
        observed=json.loads((ROOT/'tests/fixtures/stage3-globin-loss-28749-native85.json').read_text(encoding='utf8'))['input']
        self.assertNotIn(index,observed['room']['blocked'])

    def test_short_or_absent_grace_keeps_normal_contact_avoidance(self):
        self.assertEqual(self.replay(0),self.replay(23))
        self.assertEqual(self.replay(0),self.replay(47))


if __name__=='__main__': unittest.main()
