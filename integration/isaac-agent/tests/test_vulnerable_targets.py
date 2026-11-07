"""Replay Mask of Infamy's vulnerable heart beside an invulnerable mask."""
import json
import sys
import unittest
from pathlib import Path
from dataclasses import replace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import GameState, Vec2
from isaac_jev.decision import combat_actions


class VulnerableTargetTests(unittest.TestCase):
    def observed(self):
        raw=json.loads((ROOT/'tests/fixtures/stage5-mask-heart-target-native100.json').read_text(encoding='utf-8'))
        # A separate live NPC probe confirmed these phases. The original raw
        # snapshot predates vulnerability telemetry, so retain it unchanged.
        for entity in raw['enemies']:
            entity['vulnerable']=entity['type']==98
        return GameState.from_message(raw)

    def test_nearby_mask_remains_contact_threat_but_heart_is_attack_target(self):
        state=self.observed()
        self.assertEqual([e.kind for e in state.enemies],[97,98])
        self.assertEqual([e.kind for e in state.attack_targets()],[98])
        geometry=state.geometry_features()
        self.assertEqual(geometry['attack_target_id'],23)
        self.assertLess(geometry['nearest_enemy_distance'],geometry['attack_target_distance'])
        self.assertTrue(combat_actions(state))

    def test_firing_lane_uses_heart_even_when_mask_is_closer(self):
        state=self.observed()
        heart=state.attack_targets()[0]
        state=replace(state,player=replace(state.player,position=Vec2(heart.position.x,heart.position.y-160)),
            projectiles=(),hazards=(),player_grid_index=-1)
        self.assertTrue(state.geometry_features()['line_of_fire'])
        actions=combat_actions(state)
        self.assertTrue(any(action.shoot==Vec2(0,1) for action in actions))

    def test_missing_metadata_and_all_closed_windows_keep_waiting_target(self):
        state=self.observed()
        state=replace(state,enemies=tuple(replace(e,vulnerable=None) for e in state.enemies))
        self.assertEqual(state.attack_targets(),state.enemies)
        state=replace(state,enemies=tuple(replace(e,vulnerable=False) for e in state.enemies))
        self.assertEqual(state.attack_targets(),state.enemies)


if __name__=='__main__': unittest.main()
