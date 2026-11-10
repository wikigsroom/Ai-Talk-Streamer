"""Replay the real large-room stalemate where Python's lane exceeded Lua's."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from isaac_jev.decision import build_candidate_set, local_policy_action, repeat_action_penalty_action
from isaac_jev.models import GameState, Vec2
from isaac_jev.navigation import firing_position, path_distance


class PitFiringRangeTests(unittest.TestCase):
    def setUp(self):
        self.state = GameState.from_message(json.loads((Path(__file__).parent/'fixtures/stage3-pit-range-stall.json').read_text('utf8')))

    def test_long_nominal_range_cannot_reuse_the_unproductive_far_tile(self):
        state = self.state
        enemy = state.enemies[0]
        self.assertGreater(enemy.position.distance_to(state.player.position), 235)
        self.assertGreater(state.player.tear_range-25, enemy.position.distance_to(state.player.position))
        lane = firing_position(state, enemy.position, enemy.grid_index, avoid_dead_ends=True)
        self.assertIsNotNone(lane)
        position, index, _ = lane
        self.assertNotEqual(position, state.player.position)
        self.assertLessEqual(position.distance_to(enemy.position), 235)
        self.assertLess(path_distance(state, position, index), float('inf'))

    def test_real_policy_supplies_a_pit_detour_to_the_native_planner(self):
        action = local_policy_action(self.state, build_candidate_set(self.state))
        self.assertEqual(action.mode, 'combat')
        self.assertIsNotNone(action.waypoint)
        self.assertNotEqual(action.move, Vec2())
        self.assertLessEqual(action.waypoint.distance_to(self.state.enemies[0].position), 235)
        self.assertGreater(action.waypoint.distance_to(self.state.player.position), 22)
        # The shot crosses pits; the player cannot. It needs a different row.
        self.assertGreater(abs(action.waypoint.y-self.state.player.position.y), 30)

    def test_movement_penalty_keeps_the_long_route_around_the_pits(self):
        action = local_policy_action(self.state, build_candidate_set(self.state))
        for trigger in ('repeat', 'movement'):
            recovered = repeat_action_penalty_action(self.state, action, trigger=trigger)
            self.assertEqual(recovered.waypoint, action.waypoint)

    def test_short_range_is_not_increased_to_the_native_upper_ceiling(self):
        state = replace(self.state, player=replace(self.state.player, tear_range=90))
        self.assertIsNone(firing_position(state, state.enemies[0].position, state.enemies[0].grid_index))


if __name__ == '__main__':
    unittest.main()
