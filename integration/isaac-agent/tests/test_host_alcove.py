"""Replay the observed Host alcove with no distant firing lane."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import GameState,Pickup,Vec2
from isaac_jev.decision import build_candidate_set,local_policy_action,_safe_consumable_pickup,repeat_action_penalty_action
from isaac_jev.navigation import firing_position,path_distance
import test_inertial_navigation as inertial


class HostAlcoveTests(unittest.TestCase):
    def setUp(self):
        self.state=GameState.from_message(json.loads((ROOT/'tests/fixtures/stage4-movable-turret-stall.json').read_text(encoding='utf8')))

    def test_host_gets_a_reachable_short_lane_when_rocks_block_all_distant_lanes(self):
        state=self.state
        enemy=state.enemies[0]
        self.assertIsNone(firing_position(state,enemy.position,enemy.grid_index))
        action=local_policy_action(state,build_candidate_set(state))
        self.assertEqual(action.action_id,'reposition_to_fire_lane')
        self.assertIsNotNone(action.waypoint)
        self.assertGreaterEqual(action.waypoint.distance_to(enemy.position),70)
        self.assertLess(action.waypoint.distance_to(enemy.position),105)
        index=int((action.waypoint.y-100)//40)*15+int((action.waypoint.x-20)//40)
        self.assertLess(path_distance(state,action.waypoint,index),float('inf'))
        reached=replace(state,player=replace(state.player,position=action.waypoint),
                        player_grid_index=index,last_action_id='',movement_progress=1)
        hold=local_policy_action(reached,build_candidate_set(reached))
        self.assertEqual(hold.action_id,'hold_and_fire')
        self.assertIsNotNone(hold.waypoint)

    def test_actual_lua_route_reaches_the_host_lane_without_body_contact(self):
        helper=inertial.InertialNavigationTests()
        helper.load_fixture('stage4-movable-turret-stall.json')
        completed,ticks,clearance,x,y=helper.api.simulate(107,281.8,0,0,315.6,387.5,315.6,307.5)
        self.assertTrue(completed,(ticks,clearance,x,y))
        self.assertGreater(clearance,0)

    def test_repeated_firing_lane_action_keeps_its_route_in_safety_override(self):
        action=local_policy_action(self.state,build_candidate_set(self.state))
        for trigger in ('repeat','movement'):
            override=repeat_action_penalty_action(self.state,action,trigger=trigger)
            self.assertEqual(override.waypoint,action.waypoint)
            self.assertEqual(override.mode,'combat')

    def test_joker_can_replace_a_held_card_but_is_not_swapped_back(self):
        joker_id=json.loads((ROOT/'game-card-enum.json').read_text(encoding='utf8'))['CARD_JOKER']
        joker=Pickup(1,Vec2(),joker_id,0,0,False,pickup_kind='card')
        other=replace(joker,subtype=2)
        state=replace(self.state,held_cards=((0,2),))
        self.assertTrue(_safe_consumable_pickup(state,joker))
        self.assertFalse(_safe_consumable_pickup(state,replace(joker,subtype=54)))
        holding=replace(state,held_cards=((0,joker_id),))
        self.assertFalse(_safe_consumable_pickup(holding,joker))
        self.assertFalse(_safe_consumable_pickup(holding,other))
        self.assertFalse(_safe_consumable_pickup(replace(state,progression_target=''),joker))


if __name__=='__main__': unittest.main()
