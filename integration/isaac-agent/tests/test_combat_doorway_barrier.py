"""Actual rock enclosure: the doorway poop is off the nearest enemy's ray."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import GameState,Vec2
from isaac_jev.decision import build_candidate_set,candidate_actions
from isaac_jev.navigation import firing_position,path_distance


class CombatDoorwayBarrierTests(unittest.TestCase):
    def setUp(self):
        self.state=GameState.from_message(json.loads((ROOT/'tests/fixtures/stage1-room71-safety-stall-native120.json').read_text(encoding='utf8')))

    def test_actual_disconnected_room_clears_the_shootable_doorway_without_bombs(self):
        state=self.state
        self.assertTrue(all(firing_position(state,e.position,e.grid_index) is None for e in state.enemies))
        candidates=build_candidate_set(state)
        self.assertEqual(len(candidates.admissible_candidates),1)
        action=candidates.admissible_candidates[0]
        self.assertEqual(action.action_id,'clear_hazard_-100068')
        self.assertEqual(action.mode,'hazard')
        self.assertEqual(action.shoot,Vec2())
        self.assertIsNotNone(action.waypoint)
        self.assertLess(path_distance(state,action.waypoint,66),float('inf'))

    def test_cleared_barrier_opens_a_normal_combat_lane(self):
        state=self.state
        cell=frozenset({68})
        state=replace(state,hazards=tuple(h for h in state.hazards if h.grid_index!=68),
            layout=replace(state.layout,blocked=state.layout.blocked-cell,shot_blocked=state.layout.shot_blocked-cell))
        actions=candidate_actions(state)
        self.assertTrue(any(a.mode=='combat' and a.waypoint is not None for a in actions))
        self.assertFalse(any(a.mode in {'hazard','bomb'} for a in actions))

    def test_unrelated_poop_does_not_interrupt_a_reachable_enemy_lane(self):
        state=self.state
        enemy=replace(state.enemies[0],position=Vec2(160,360),grid_index=93)
        state=replace(state,enemies=(enemy,))
        self.assertIsNotNone(firing_position(state,enemy.position,enemy.grid_index))
        self.assertFalse(any(a.mode=='hazard' for a in candidate_actions(state)))

    def test_nearby_hostile_keeps_combat_priority(self):
        state=self.state
        enemy=replace(state.enemies[0],position=Vec2(280,360),grid_index=96)
        state=replace(state,enemies=(enemy,)+state.enemies[1:])
        self.assertFalse(any(a.mode=='hazard' for a in candidate_actions(state)))


if __name__=='__main__':unittest.main()
