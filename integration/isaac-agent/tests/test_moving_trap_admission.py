"""Moving hazards must not permanently remove a real floor branch."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import DangerEffect, Door, Entity, GameState, RoomLayout, Vec2
from isaac_jev.navigation import door_path_distance, move_towards


class MovingTrapAdmissionTests(unittest.TestCase):
    def test_actual_large_room_keeps_the_unexplored_north_branch(self):
        state=GameState.from_message(json.loads((ROOT/'tests/fixtures/stage3-door4-route-stall.json').read_text()))
        north=next(door for door in state.layout.doors if door.slot==1)
        self.assertLess(door_path_distance(state,north),float('inf'))

    def test_admission_does_not_remove_a_persistent_creep_or_wall(self):
        door=Door(2,Vec2(360,120),target_room_index=2,grid_index=26,open=True,open_known=True)
        moving=DangerEffect(1,'moving_spike',Vec2(200,120),Vec2(),10)
        floor=set(range(19,26))
        state=GameState(frame=0,room_clear=True,player=Entity(0,1,Vec2(80,120),Vec2()),
            enemies=(),projectiles=(),player_grid_index=19,danger_effects=(moving,),
            layout=RoomLayout(grid_width=9,grid_height=5,doors=(door,),
                blocked=frozenset(set(range(45))-floor),danger_grid_indices=frozenset({22})))
        self.assertLess(door_path_distance(state,door),float('inf'))
        # Actual movement still refuses the currently occupied corridor.
        self.assertEqual(move_towards(state,door.position,door.grid_index),Vec2())
        creep=DangerEffect(2,'creep',Vec2(200,120),Vec2(),10)
        self.assertEqual(door_path_distance(replace(state,danger_effects=(moving,creep)),door),float('inf'))
        wall=replace(state,layout=replace(state.layout,blocked=state.layout.blocked|{22}))
        self.assertEqual(door_path_distance(wall,door),float('inf'))


if __name__=='__main__': unittest.main()
