"""Recover the actual Loki/Poky exit overlap through ordinary doors."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import GameState
from isaac_jev.decision import strategic_actions


class BlockedBossExitTests(unittest.TestCase):
    def setUp(self):
        state=GameState.from_message(json.loads((ROOT/'tests/fixtures/stage5-boss-exit-corner-native71.json').read_text()))
        self.state=replace(state,pickups=(),room_cleared_frame=state.frame-300,
            planned_goal='return to known boss exit')

    def test_persistent_trap_over_exit_uses_an_ordinary_door(self):
        action=strategic_actions(self.state)[0]
        self.assertEqual((action.mode,action.action_id),('navigate','enter_door_3'))

    def test_unobstructed_or_recently_cleared_exit_keeps_normal_floor_progression(self):
        for state in (replace(self.state,floor_danger_effects=()),
                      replace(self.state,room_cleared_frame=self.state.frame-90)):
            with self.subTest(clear_age=state.frame-state.room_cleared_frame):
                self.assertEqual(strategic_actions(state)[0].mode,'boss_exit')


if __name__=='__main__':unittest.main()
