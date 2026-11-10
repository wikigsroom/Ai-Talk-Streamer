"""The native weapon's engagement cap must survive parsing and route selection."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from isaac_jev.models import Entity, GameState, Vec2
from isaac_jev.decision import build_candidate_set, local_policy_action
from isaac_jev.navigation import firing_position, path_distance


class WeaponFiringRangeTests(unittest.TestCase):
    def test_reported_range_is_bounded_and_legacy_packets_keep_the_native_ceiling(self):
        base={'tear_range':360,'engagement_range':160}
        self.assertEqual(Entity.from_value(base).combat_range,160)
        for value in (None,True,'160',float('nan'),float('inf')):
            self.assertEqual(Entity.from_value({**base,'engagement_range':value}).combat_range,235)
        self.assertEqual(Entity.from_value({**base,'engagement_range':999}).combat_range,235)
        self.assertEqual(Entity.from_value({**base,'tear_range':100}).combat_range,75)
        self.assertEqual(Entity.from_value({**base,'engagement_range':0}).combat_range,0)

    def test_observed_boss_summons_get_a_reachable_lane_inside_weapon_spacing(self):
        raw=json.loads((Path(__file__).parent/'fixtures/stage3-boss-summons-stall.json').read_text('utf8'))
        # New native field, produced by the actual Lua weapon profile test.
        raw['player']['engagement_range']=160
        state=GameState.from_message(raw)
        enemy=state.enemies[0]
        lane=firing_position(state,enemy.position,enemy.grid_index,minimum_range=95,avoid_dead_ends=True)
        self.assertIsNotNone(lane)
        position,index,_=lane
        self.assertLessEqual(position.distance_to(enemy.position),160)
        self.assertLess(path_distance(state,position,index),float('inf'))
        action=local_policy_action(state,build_candidate_set(state))
        self.assertIsNotNone(action.waypoint)
        self.assertNotEqual(action.move,Vec2())
        self.assertLessEqual(min(action.waypoint.distance_to(target.position)
                                 for target in state.attack_targets()),160)
        self.assertEqual(state.geometry_features()['effective_firing_range'],160)

    def test_valid_long_range_tile_is_rejected_for_a_short_range_weapon(self):
        state=GameState(frame=1,room_clear=False,
            player=Entity(0,1,Vec2(135.9,159.3),Vec2(),8,tear_range=360),
            enemies=(Entity(2,30,Vec2(360,160),Vec2(),20),),projectiles=())
        ordinary=firing_position(state,state.enemies[0].position,-1)
        close=replace(state,player=replace(state.player,engagement_range=160))
        short=firing_position(close,close.enemies[0].position,-1)
        self.assertEqual(ordinary[0],state.player.position)
        self.assertNotEqual(short[0],state.player.position)
        self.assertLessEqual(short[0].distance_to(state.enemies[0].position),160)


if __name__=='__main__':unittest.main()
