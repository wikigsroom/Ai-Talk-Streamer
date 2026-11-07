"""Replay the cleared Womb room with an unexplored exit behind a rock wall."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.decision import build_candidate_set,local_policy_action
from isaac_jev.models import GameState,Hazard,Vec2
from isaac_jev.navigation import door_path_distance


class BlockedRoomPassageTests(unittest.TestCase):
    def setUp(self):
        raw=json.loads((ROOT/'tests/fixtures/stage7-room-85-loop-native126.json').read_text('utf8'))
        rocks=json.loads((ROOT/'tests/fixtures/stage7-room-85-rocks-native126.json').read_text('utf8'))
        raw['hazards'] += [dict(id=-100000-r['i'],kind='passage_rock',type=2,
            pos=r['pos'],grid_index=r['i'],destructible=True,requires_bomb=True) for r in rocks]
        self.state=replace(GameState.from_message(raw),visited_room_indices=frozenset({83,84,85}),
                           planned_door_slot=0,previous_room_index=84)

    def choose(self,state):
        return local_policy_action(state,build_candidate_set(state))

    def test_real_disconnected_exit_gets_one_safe_rock_bomb(self):
        state=self.state
        door=next(d for d in state.layout.doors if d.slot==2)
        self.assertEqual(door_path_distance(state,door),float('inf'))
        action=self.choose(state)
        self.assertEqual(action.mode,'bomb')
        self.assertTrue(action.action_id.startswith('bomb_hazard_'))
        rock=next(h for h in state.hazards if action.action_id.endswith('_'+str(h.entity_id)))
        self.assertEqual(rock.kind,'passage_rock')
        self.assertIsNotNone(action.bomb_site)
        opened=replace(state,layout=replace(state.layout,blocked=state.layout.blocked-{rock.grid_index}),
                       hazards=tuple(h for h in state.hazards if h!=rock))
        self.assertLess(door_path_distance(opened,door),float('inf'))
        self.assertNotEqual(self.choose(opened).mode,'bomb')

    def test_no_bombs_or_combat_cannot_spend_on_optional_rocks(self):
        self.assertFalse(any(a.action_id.startswith('bomb_hazard_')
            for a in build_candidate_set(replace(self.state,bombs=0)).raw_candidates))
        self.assertFalse(any(a.action_id.startswith('bomb_hazard_')
            for a in build_candidate_set(replace(self.state,room_clear=False)).raw_candidates))

    def test_accessible_exit_and_unrelated_rock_are_not_farmed(self):
        state=replace(self.state,layout=replace(self.state.layout,blocked=self.state.layout.blocked-{22}),
                      hazards=tuple(h for h in self.state.hazards if h.grid_index!=22))
        self.assertNotEqual(self.choose(state).mode,'bomb')


if __name__=='__main__':unittest.main()
