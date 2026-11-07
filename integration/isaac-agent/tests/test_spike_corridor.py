"""Replay the observed stage 5 spike corridor that pinned combat at its entrance."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from isaac_jev.decision import build_candidate_set, repeat_action_penalty_action
from isaac_jev.models import Action, GameState, Vec2


class SpikeCorridorTests(unittest.TestCase):
    def setUp(self):
        self.state = GameState.from_message(json.loads(
            (ROOT / "tests/fixtures/stage5-spike-corridor.json").read_text(encoding="utf-8")))

    def test_reachable_lane_is_not_rejected_due_to_long_centering_forecast(self):
        candidates = build_candidate_set(self.state)
        first = candidates.admissible_candidates[0]
        self.assertEqual(first.action_id, "route_to_firing_lane")
        self.assertEqual(first.move, Vec2(0, -1))
        self.assertIsNotNone(first.waypoint)
        self.assertNotIn(69, self.state.layout.danger_grid_indices)

    def test_stall_recovery_retains_the_route_around_spikes(self):
        previous = Action("advance_and_fire", Vec2(0, -1), Vec2(-1, 0), mode="combat")
        action = repeat_action_penalty_action(self.state, previous, trigger="movement")
        self.assertEqual(action.waypoint, Vec2(400, 280))


if __name__ == "__main__":
    unittest.main()
