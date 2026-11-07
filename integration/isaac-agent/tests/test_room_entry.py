"""A previous-room action must not suppress live combat on entering a room."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class RoomEntryTests(unittest.TestCase):
    def test_live_combat_precedes_previous_room_action_guard(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='local function resolveSafeMove(player, navigationBlocked)'+source.split('local function resolveSafeMove(player, navigationBlocked)',1)[1].split('local function actionHazardStillPresent',1)[0]
        choose=LuaRuntime(unpack_returned_tuples=True).execute('''
            Vector=function(x,y) return {X=x,Y=y} end
            local action={sourceRoomIndex=1,move=Vector(0,1),waypoint=Vector(500,500)}
            local utilityButtons={}
            local lastPyroHealFrame=-10000
            local lastActionFrame=100
            ButtonAction={ACTION_DROP=3}
            game={GetRoom=function() return {} end,GetLevel=function() return {} end,GetFrameCount=function() return 100 end}
            local enemies=false
            local function canonicalRoomIndex() return 2 end
            local timedSpikeNavigator={active=false}
            local function escapeGridDanger() return nil end
            local function escapeStomp() return nil end
            local function bombStillLive() return false end
            local function nearestTrackingBomb() return nil end
            local function hasCombatEnemy() return enemies end
            Isaac={GetRoomEntities=function() return {} end}
            local function predictiveCombatMove(_,ignoreWaypoint)
                assert(ignoreWaypoint,'old room waypoint must be ignored')
                return Vector(1,0),Vector(0,-1)
            end
        '''+helper+'''
            return function(present,stale)
                enemies=present
                lastActionFrame=stale and 0 or 100
                action.sourceRoomIndex=stale and 2 or 1
                local move=resolveSafeMove({})
                return move.X,move.Y
            end
        ''')
        self.assertEqual(choose(False),(0,0))
        self.assertEqual(choose(True),(1,0))
        self.assertEqual(choose(True,True),(1,0),'expired route must not override live combat')
        self.assertEqual(choose(False,True),(0,0),'expired navigation cannot move through a clear room')

    def test_reverse_door_guard_preserves_dodge_in_a_cleared_trap_room(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='local function resolveSafeMove(player, navigationBlocked)'+source.split('local function resolveSafeMove(player, navigationBlocked)',1)[1].split('local function actionHazardStillPresent',1)[0]
        choose=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            EntityType={ENTITY_PROJECTILE=9}
            local action={sourceRoomIndex=47,move=Vector(0,1),mode='navigate'}
            local utilityButtons={}
            local lastPyroHealFrame=-10000
            local lastActionFrame=100
            ButtonAction={ACTION_DROP=3}
            game={GetRoom=function() return {} end,GetLevel=function() return {} end,
                GetFrameCount=function() return 100 end}
            local entities={}
            Isaac={GetRoomEntities=function() return entities end}
            local function canonicalRoomIndex() return 47 end
            local timedSpikeNavigator={active=false}
            local function escapeGridDanger() return nil end
            local function escapeStomp() return nil end
            local function bombStillLive() return false end
            local function nearestTrackingBomb() return nil end
            local function hasCombatEnemy() return false end
            local function hostileLaser() return nil end
            local function isMovingSpikeTrap(e) return e.Type==218 end
            local function predictiveCombatMove(_,ignoreWaypoint)
                assert(ignoreWaypoint,'blocked navigation target must not steer escape')
                return Vector(-1,0),Vector(0,0)
            end
        '''+helper+'''
            return function(kind)
                entities=kind and {{Type=kind,Position=Vector(852.9,640.3)}} or {}
                local move=resolveSafeMove({Position=Vector(840,662.3)},true)
                return move.X,move.Y
            end
        ''')
        self.assertEqual(choose(None),(0,0))
        self.assertEqual(choose(218),(-1,0))
        self.assertEqual(choose(9),(-1,0))

    def test_lingering_projectiles_precede_all_clear_room_targets(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='local function resolveSafeMove(player, navigationBlocked)'+source.split('local function resolveSafeMove(player, navigationBlocked)',1)[1].split('local function actionHazardStillPresent',1)[0]
        choose=LuaRuntime(unpack_returned_tuples=True).execute('''
            Vector=function(x,y) return {X=x,Y=y} end
            EntityType={ENTITY_PROJECTILE=9}
            local action={sourceRoomIndex=110,move=Vector(-1,0)}
            local utilityButtons={}
            local lastPyroHealFrame=-10000
            local lastActionFrame=100
            ButtonAction={ACTION_DROP=3}
            game={GetRoom=function() return {} end,GetLevel=function() return {} end,
                GetFrameCount=function() return 100 end}
            local entities={{Type=9}}
            Isaac={GetRoomEntities=function() return entities end}
            local function canonicalRoomIndex() return 110 end
            local timedSpikeNavigator={active=false}
            local emergency=false
            local function escapeGridDanger() return emergency and Vector(-1,0) or nil end
            local function escapeStomp() return nil end
            local function bombStillLive() return false end
            local function nearestTrackingBomb() return nil end
            local function hasCombatEnemy() return false end
            local function isCombatEnemy() return false end
            local function hostileLaser() return nil end
            local function isMovingSpikeTrap() return false end
            local function predictiveCombatMove()
                return Vector(0,1),Vector(0,0)
            end
            local function followGridRoute() error('timed route bypassed live bullet') end
        '''+helper+'''
            return function(mode,temporal,escape,inspectAim)
                action.mode=mode
                emergency=escape==true
                timedSpikeNavigator.active=temporal==true
                timedSpikeNavigator.key='same'
                currentRoomKey=function() return 'same' end
                local move=resolveSafeMove({})
                if inspectAim then return move.X,move.Y,combatLiveAim==nil end
                return move.X,move.Y
            end
        ''')
        for mode in ('pickup','item','navigate','button','boss_exit','hazard','wait'):
            with self.subTest(mode=mode):
                self.assertEqual(choose(mode,False),(0,1))
        self.assertEqual(choose('button',True),(0,1))
        self.assertEqual(choose('button',True,True),(-1,0))
        self.assertEqual(choose('hazard',False,False,True),(0,1,True))
        self.assertEqual(choose('tnt',False,False,True),(0,1,True))
        self.assertEqual(choose('combat',False,False,True),(0,1,False))


if __name__=='__main__':
    unittest.main()
