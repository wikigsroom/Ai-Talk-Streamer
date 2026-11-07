"""The actual rock/pit Host has no reachable 70px cardinal firing point."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import GameState
from isaac_jev.navigation import firing_position,path_distance
from isaac_jev.decision import candidate_actions


class CloseHostLaneTests(unittest.TestCase):
    def test_real_narrow_alcove_routes_to_adjacent_firing_cell(self):
        raw=json.loads((ROOT/'tests/fixtures/stage3-host-close-alcove-native87.json').read_text(encoding='utf8'))
        state=GameState.from_message(raw)
        host=state.enemies[0]
        self.assertIsNone(firing_position(state,host.position,host.grid_index,70))
        lane=firing_position(state,host.position,host.grid_index,35)
        self.assertIsNotNone(lane)
        self.assertGreaterEqual(lane[0].distance_to(host.position),35)
        self.assertLess(path_distance(state,lane[0],lane[1]),float('inf'))
        actions=candidate_actions(state)
        self.assertTrue(any(a.waypoint==lane[0] and a.move.x+a.move.y!=0 for a in actions))


if __name__=='__main__': unittest.main()
