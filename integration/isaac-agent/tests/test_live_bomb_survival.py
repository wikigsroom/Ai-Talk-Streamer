"""Live room observation must retain bomb danger after a controller reload."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools/python-libs')]
from lupa.lua53 import LuaRuntime
from isaac_jev.models import GameState, Vec2
from isaac_jev.decision import build_candidate_set


class LiveBombSurvivalTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf-8')
        function='local function trackingBombInfo(entity, player)'+source.split('local function trackingBombInfo(entity, player)',1)[1].split('local function nearestTrackingBomb',1)[0]
        self.classify=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            EntityType={ENTITY_BOMB=4,ENTITY_EFFECT=1000}
            local function vectorTable(v) return {x=v.X,y=v.Y} end
        '''+function+'''
            return function(distance, immune, multiplier)
                local player={Index=0,Size=10,Position=Vector(0,0),HasCollectible=function() return immune end}
                local entity={Index=7,Type=4,Variant=0,Position=Vector(distance,0),Velocity=Vector(0,0),
                    SpawnerEntity=player,Parent=player,ToBomb=function() return {RadiusMultiplier=multiplier} end}
                return trackingBombInfo(entity,player)
            end
        ''')

    def test_stationary_player_bomb_survives_missing_placement_history(self):
        threat=self.classify(35,False,1)
        self.assertEqual(threat.kind,'armed_bomb')
        self.assertGreaterEqual(threat.radius,120)

    def test_own_explosion_immunity_preserves_natural_pyromaniac_healing(self):
        self.assertIsNone(self.classify(35,True,1))

    def test_large_bomb_radius_is_observed_and_distant_bombs_do_not_interrupt(self):
        self.assertIsNone(self.classify(250,False,1))
        self.assertGreater(self.classify(250,False,2).radius,200)

    def test_stationary_bomb_preempts_loot_and_selects_real_escape(self):
        state=GameState.from_message({'frame':10,'room_clear':True,
            'player':{'hp':6,'pos':{'x':0,'y':0}},
            'pickups':[{'id':3,'pos':{'x':90,'y':0},'pickup_kind':'coin'}],
            'danger_effects':[{'id':7,'kind':'armed_bomb','type':4,
                'pos':{'x':50,'y':0},'vel':{'x':0,'y':0},'radius':125}]})
        candidates=build_candidate_set(state)
        self.assertEqual(candidates.policy,'emergency')
        self.assertTrue(candidates.admissible_candidates)
        for action in candidates.admissible_candidates:
            self.assertEqual(action.mode,'evade')
            self.assertEqual(action.shoot,Vec2())
            future=Vec2(state.player.position.x+action.move.x*40,state.player.position.y+action.move.y*40)
            self.assertGreater(future.distance_to(Vec2(50,0)),50)

    def test_native_escape_scores_simultaneous_bombs_and_inertia(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf-8')
        forecast='local function movementForecast('+source.split('local function movementForecast(',1)[1].split('local function predictiveCombatMove',1)[0]
        escape='local function escapeObservedBombs(player)'+source.split('local function escapeObservedBombs(player)',1)[1].split('local function resolveSafeMove',1)[0]
        choose=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local bombs={}
            Isaac={GetRoomEntities=function() return bombs end}
            local function trackingBombInfo(e) return e end
            local function safeMoveCandidate() return true end
        '''+forecast+escape+'''
            return function(two)
                bombs={{pos={x=150,y=200},vel={x=0,y=0},radius=125}}
                if two then bombs[2]={pos={x=250,y=200},vel={x=0,y=0},radius=125} end
                local move=escapeObservedBombs({Position=Vector(200,200),Velocity=Vector(two and 0 or -4,0),MoveSpeed=1})
                return move.X,move.Y
            end
        ''')
        self.assertGreater(choose(False)[0],.7)
        self.assertGreater(abs(choose(True)[1]),.7)

    def test_overlapping_chasing_bomb_does_not_reverse_escape_for_small_pushes(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        forecast='local function movementForecast('+source.split('local function movementForecast(',1)[1].split('local function predictiveCombatMove',1)[0]
        escape='local observedBombEscape=nil'+source.split('local observedBombEscape=nil',1)[1].split('local function resolveSafeMove',1)[0]
        choose=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local bombs,frame,blocked={},0,false
            game={GetFrameCount=function() return frame end}
            Isaac={GetRoomEntities=function() return bombs end}
            local function trackingBombInfo(e) return e end
            local function safeMoveCandidate(_,move) return not blocked or move.X>=0 end
        '''+forecast+escape+'''
            return function(offset,wall)
                frame,blocked=frame+1,wall
                bombs={{id=48,pos={x=200+offset,y=200},vel={x=0,y=0},radius=125}}
                local move=escapeObservedBombs({Position=Vector(200,200),Velocity=Vector(0,0),MoveSpeed=1})
                return move.X,move.Y
            end
        ''')
        initial=choose(2,False)
        self.assertLess(initial[0],-.5)
        for offset in (-2,1,-1,2,-2,1):
            move=choose(offset,False)
            self.assertGreater(move[0]*initial[0]+move[1]*initial[1],.5)
        self.assertGreaterEqual(choose(2,True)[0],0,'a blocked direction must release commitment')


if __name__=='__main__': unittest.main()
