"""Replay the observed overlapping creep death with native movement constraints."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class GroundHazardEscapeTests(unittest.TestCase):
    def setUp(self):
        source = (ROOT / 'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        safety = 'local function safeMoveCandidate(' + source.split('local function safeMoveCandidate(', 1)[1].split('local function firstSafeMove', 1)[0]
        escape = 'local function escapeStomp(player)' + source.split('local function escapeStomp(player)', 1)[1].split('local function gridDangerClearance', 1)[0]
        lifecycle = 'local function liveHazardKind(entity)' + source.split('local function liveHazardKind(entity)', 1)[1].split('local function gridHazardKind', 1)[0]
        row = json.loads((ROOT / 'tests/fixtures/stage3-overlapping-creep.json').read_text())
        self.lua = lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().blocked = lua.table_from({i: True for i in row['layout']['blocked']})
        lua.globals().start_x = row['player']['pos']['x']
        lua.globals().start_y = row['player']['pos']['y']
        self.api = lua.execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local entities={}
            Isaac={GetRoomEntities=function() return entities end}
            EntityType={ENTITY_PROJECTILE=9}
            local room={GetGridIndex=function(_,p)
                return math.floor((p.Y-100)/40)*15+math.floor((p.X-20)/40) end,
                GetGridPath=function(_,i) return (i<0 or i>=135 or blocked[i]) and 1000 or 0 end,
                GetGridEntity=function() return nil end}
            game={GetRoom=function() return room end}
            local function hazardKind(e) return e.Type==33 and 'fire' or nil end
            local function bombOnlyFireKind() return false end
            local function contactObstacle() return nil end
            local function trackingBombInfo() return nil end
            local function isMovingSpikeTrap() return false end
            local function gridEvent() return nil end
            local function redPoopGrid() return false end
            local function liveGridHazardKind() return nil end
            local function bombStillLive() return false end
            local function isCombatEnemy() return false end
            local function dangerousCreep(e) return e.Type==1000 and e.Variant==22 end
        ''' + lifecycle + safety + escape + '''
            return {fire=function(animation,hp,dead)
                local sprite={GetAnimation=function() return animation end,
                    IsPlaying=function(_,name) return name==animation end,
                    IsFinished=function() return false end}
                local e={Type=33,HitPoints=hp,GetSprite=function() return sprite end,
                    ToNPC=function() return {IsActive=function() return false end,
                        IsActiveEnemy=function() return false end,IsDead=function() return dead end} end}
                return liveHazardKind(e)
            end,replay=function()
                entities={}
                for _,v in ipairs({{597.5,398.8},{585.8,361.3},{507.1,419.4},
                    {625.3,334.4},{565.3,360.8}}) do
                    entities[#entities+1]={Type=1000,Variant=22,Size=40,
                        Position=Vector(v[1],v[2]),Velocity=Vector(0,0)}
                end
                local p={Position=Vector(start_x,start_y),Velocity=Vector(0,0),
                    Size=10,CanFly=false,MoveSpeed=1}
                local blockedCount=0
                for _,d in ipairs({Vector(1,0),Vector(-1,0),Vector(0,1),Vector(0,-1)}) do
                    if not safeMoveCandidate(p,d,false) then blockedCount=blockedCount+1 end
                end
                for tick=1,60 do
                    local move=escapeStomp(p)
                    if not move then return true,tick,blockedCount end
                    if move:Length()<.5 then return false,'zero escape',blockedCount end
                    local following=p.Velocity*.7+move*1.14
                    local nextPosition=p.Position+p.Velocity+following
                    if room:GetGridPath(room:GetGridIndex(nextPosition))>=1000 then
                        return false,'entered wall',blockedCount
                    end
                    p.Position,p.Velocity=nextPosition,following
                end
                return false,'remained inside creep',blockedCount
            end}
        ''')

    def test_inactive_predicates_do_not_hide_a_lit_fire(self):
        self.assertEqual(self.api.fire('Flickering', 4, False), 'fire')

    def test_extinguished_fire_does_not_block_navigation(self):
        for animation, hp, dead in [('Dissapear', 1, False), ('Flickering', 0, False), ('Flickering', 4, True)]:
            with self.subTest(animation=animation, hp=hp, dead=dead):
                self.assertIsNone(self.api.fire(animation, hp, dead))

    def test_combined_escape_leaves_the_actual_overlapping_pools(self):
        completed, detail, blocked_count = self.api.replay()
        self.assertEqual(blocked_count, 4, 'fixture must reproduce all-direction veto')
        self.assertTrue(completed, detail)
        self.assertLess(detail, 40)


if __name__ == '__main__':
    unittest.main()
