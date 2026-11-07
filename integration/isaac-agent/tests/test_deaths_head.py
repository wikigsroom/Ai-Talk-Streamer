"""Keep the observed invulnerable floating heads out of clear/aim decisions."""
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools/python-libs')]
from isaac_jev.models import GameState
from lupa.lua53 import LuaRuntime


class DeathsHeadTests(unittest.TestCase):
    def test_actual_mixed_room_keeps_vis_as_the_combat_target(self):
        trace=json.loads((ROOT/'tests/fixtures/stage5-deaths-head-vis-trace.json').read_text(encoding='utf8'))
        enemies=trace['input']['nearby_enemies']
        self.assertTrue(any(e['type']==212 for e in enemies))
        state=GameState.from_message({'player':{'hp':5},'enemies':enemies,'room_clear':False})
        self.assertTrue(state.enemies)
        self.assertEqual({e.kind for e in state.enemies},{39})
        self.assertFalse(state.room_clear)

    def test_native_classification_retains_host_windows_but_excludes_floating_heads(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        traps='local function isRetractedSpikeTrap(entity)'+source.split('local function isRetractedSpikeTrap(entity)',1)[1].split('local function liveHazardKind',1)[0]
        combat='local function isCombatEnemy(entity)'+source.split('local function isCombatEnemy(entity)',1)[1].split('local function hasCombatEnemy',1)[0]
        classify=LuaRuntime(unpack_returned_tuples=True).execute('''
            EntityType={ENTITY_SPIDER=85}
            EntityFlag={FLAG_FRIENDLY=1}
            Isaac={GetPlayer=function() return {} end}
            local function hazardKind() return nil end
            local function trackingBombInfo() return nil end
        '''+traps+combat+'''
            return function(kind,variant)
                local entity={Type=kind,Variant=variant or 0,HitPoints=20,ToNPC=function(e) return e end,
                    IsActiveEnemy=function() return true end,HasEntityFlags=function() return false end}
                return isCombatEnemy(entity),isMovingSpikeTrap(entity)
            end
        ''')
        self.assertEqual(classify(212),(False,True))
        self.assertEqual(classify(212,1),(True,False))
        self.assertEqual(classify(39),(True,False))
        self.assertEqual(classify(27),(True,False))
        self.assertEqual(classify(68,0),(True,False))
        self.assertEqual(classify(68,10),(False,True))
        self.assertEqual(classify(68,20),(True,False))
        self.assertEqual(classify(79,20),(False,False))
        self.assertEqual(classify(79,0),(True,False))
        self.assertEqual(classify(79,10),(True,False))
        self.assertEqual(classify(216,10),(False,False))
        self.assertEqual(classify(216,0),(True,False))
        self.assertEqual(classify(216,1),(True,False))

    def test_observed_peep_fight_aims_at_main_body_with_two_eyes_present(self):
        observed=json.loads((ROOT/'tests/fixtures/stage4-peep-eyes-native75.json').read_text(encoding='utf8'))
        enemies=observed['nearby_enemies']
        self.assertEqual([(e['type'],e['variant']) for e in enemies],[(68,0),(68,10),(68,10)])
        state=GameState.from_message({'player':{'hp':15},'enemies':enemies,'room_clear':False})
        self.assertEqual([(e.kind,e.variant) for e in state.enemies],[(68,0)])
        self.assertFalse(state.room_clear)

    def test_actual_gemini_cord_pieces_cannot_outvote_the_living_boss(self):
        row=json.loads((ROOT/'tests/fixtures/stage2-gemini-cords-native81.json').read_text(encoding='utf8'))
        observed=row['input']['nearby_enemies']
        self.assertGreater(sum(e['variant']==20 for e in observed),4)
        state=GameState.from_message({'player':{'hp':5},'enemies':observed,'room_clear':False})
        self.assertEqual([(e.kind,e.variant) for e in state.enemies],[(79,0)])
        self.assertFalse(state.room_clear)

    def test_vulnerable_variant_keeps_the_room_in_combat(self):
        state=GameState.from_message({'player':{'hp':7},'room_clear':False,'enemies':[
            {'id':1,'type':212,'variant':0,'hp':20},
            {'id':2,'type':212,'variant':1,'hp':20},
            {'id':3,'type':212,'variant':0,'hp':20}]})
        self.assertEqual([(e.kind,e.variant) for e in state.enemies],[(212,1)])
        self.assertFalse(state.room_clear)

    def test_actual_heart_swinger_cords_do_not_outvote_its_living_body(self):
        rows=json.loads((ROOT/'tests/fixtures/stage8-heart-swinger-cords-native96.json').read_text(encoding='utf8'))
        observed=rows['enemies']
        self.assertGreater(sum(e['variant']==10 for e in observed),4)
        state=GameState.from_message({'player':{'hp':5},'enemies':observed,'room_clear':False})
        self.assertEqual([(e.kind,e.variant) for e in state.enemies],[(216,0)])
        self.assertFalse(state.room_clear)


if __name__=='__main__': unittest.main()
