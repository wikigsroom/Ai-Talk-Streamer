"""Replay the cleared room whose harmless Poky danger padding sealed its exit."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools/python-libs')]
from lupa.lua53 import LuaRuntime
from isaac_jev.models import GameState
from isaac_jev.navigation import door_path_distance


class RetractedSpikeTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        traps='local function isRetractedSpikeTrap(entity)'+source.split('local function isRetractedSpikeTrap(entity)',1)[1].split('local function liveHazardKind',1)[0]
        combat='local function isCombatEnemy(entity)'+source.split('local function isCombatEnemy(entity)',1)[1].split('local function hasCombatEnemy',1)[0]
        contact='local function contactObstacle(entity, player)'+source.split('local function contactObstacle(entity, player)',1)[1].split('local function playerIsDead',1)[0]
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.api=self.lua.execute('''
            local clear=true
            EntityType={ENTITY_POKY=44,ENTITY_EFFECT=1000}
            EntityFlag={FLAG_FRIENDLY=1}
            Isaac={GetPlayer=function() return {} end}
            game={GetRoom=function() return {IsClear=function() return clear end} end}
            local function hazardKind() return nil end
            local function trackingBombInfo() return nil end
        '''+traps+combat+contact+'''
            return function(state,damage,animation,cleared,speed)
                clear=cleared
                local entity={Type=44,Variant=0,Size=16,State=state,CollisionDamage=damage,
                    Velocity={Length=function() return speed end},
                    GetSprite=function() return {GetAnimation=function() return animation end} end,
                    ToNPC=function(e) return e end,IsActiveEnemy=function() return true end,
                    HasEntityFlags=function() return false end,HitPoints=100}
                local radius,kind=contactObstacle(entity,{Size=10})
                return isMovingSpikeTrap(entity),isCombatEnemy(entity),radius,kind
            end
        ''')

    def test_actual_retracted_traps_keep_only_their_physical_body(self):
        fixture=json.loads((ROOT/'tests/fixtures/stage5-retracted-spike-entities-native117.json').read_text(encoding='utf8'))
        self.assertTrue(fixture['clear'])
        self.assertEqual(len(fixture['traps']),6)
        for trap in fixture['traps']:
            speed=(trap['vx']**2+trap['vy']**2)**.5
            self.assertEqual(self.api(trap['state'],trap['collision'],trap['animation'],True,speed),
                             (False,False,29,'retracted_spike'))

    def test_partial_or_unknown_retraction_retains_danger_and_never_becomes_a_target(self):
        for args in ((16,1,'No-Spikes',True,0),(16,0,'No-Spikes',False,0),
                     (7,0,'No-Spikes',True,0),(16,0,'Spikes',True,0),
                     (16,0,'No-Spikes',True,2)):
            with self.subTest(args=args):
                self.assertEqual(self.api(*args),(True,False,None,None))

    def test_actual_room_projection_releases_safe_cells_without_erasing_trap_bodies(self):
        raw=json.loads((ROOT/'tests/fixtures/stage5-retracted-spikes-native117.json').read_text(encoding='utf8'))
        traps=json.loads((ROOT/'tests/fixtures/stage5-retracted-spike-entities-native117.json').read_text(encoding='utf8'))['traps']
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        project='local dangerousIndices = {}'+source.split('local dangerousIndices = {}',1)[1].split('    -- Layout is cached',1)[0]
        emit=self.lua.execute('''
            Vector=function(x,y) return {X=x,Y=y,Distance=function(a,b) return math.sqrt((a.X-b.X)^2+(a.Y-b.Y)^2) end} end
            return function(effects)
                local lastLayout={danger_grid_indices={}}
                local dangerEffects=effects
                local room={GetGridSize=function() return 135 end,
                    GetGridPosition=function(_,i) return Vector(40+(i%15)*40,120+math.floor(i/15)*40) end}
        '''+project+'''
                return lastLayout.danger_grid_indices
            end
        ''')
        effects=self.lua.table_from([self.lua.table_from({'kind':'retracted_spike',
                    'pos':self.lua.table_from({'x':t['x'],'y':t['y']}),'radius':29}) for t in traps])
        cells=frozenset(emit(effects).values())
        state=GameState.from_message(raw)
        before=[door_path_distance(state,d) for d in state.layout.doors]
        safe=replace(state,layout=replace(state.layout,danger_grid_indices=cells))
        after=[door_path_distance(safe,d) for d in safe.layout.doors]
        self.assertTrue(cells)
        self.assertIn(raw['player_grid_index'],state.layout.danger_grid_indices)
        self.assertNotIn(raw['player_grid_index'],cells)
        self.assertTrue(any(distance<float('inf') for distance in after))
        self.assertTrue(all(a<=b for b,a in zip(before,after)),(before,after))


if __name__=='__main__':unittest.main()
