"""An enemy-free pressure-plate room is not clear until its plate is used."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from isaac_jev.decision import build_candidate_set, local_policy_action
from isaac_jev.models import Door, Entity, GameState, GridEvent, RoomLayout, Vec2
from isaac_jev.navigation import path_distance


class ButtonRoomTests(unittest.TestCase):
    def setUp(self):
        self.state = GameState(
            frame=300,room_clear=False,player=Entity(0,1,Vec2(320,320),Vec2(),hit_points=6),
            enemies=(),projectiles=(),player_grid_index=82,movement_progress=3,
            layout=RoomLayout(grid_width=15,grid_height=9,
                              grid_events=(GridEvent("button",22,Vec2(320,160),True,False,-100022),),
                              doors=(Door(0,Vec2(40,280),target_room_index=95,grid_index=60,
                                          open=False,open_known=True),)))

    def test_button_is_pressed_before_native_clear_flag(self):
        action=local_policy_action(self.state,build_candidate_set(self.state))
        self.assertEqual(action.mode,"button")
        self.assertNotEqual(action.move,Vec2())

    def test_live_enemy_keeps_combat_priority(self):
        enemy=Entity(10,10,Vec2(320,240),Vec2(),hit_points=10,grid_index=52)
        state=replace(self.state,enemies=(enemy,))
        action=local_policy_action(state,build_candidate_set(state))
        self.assertEqual(action.mode,"combat")

    def test_actual_plate_beyond_rolling_spikes_is_admitted_before_native_clear(self):
        root=Path(__file__).resolve().parents[1]
        state=GameState.from_message(json.loads((root/'tests/fixtures/stage5-no-enemy-uncleared.json').read_text(encoding='utf8')))
        plate=next(event for event in state.layout.grid_events if event.kind=='button')
        self.assertEqual(path_distance(state,plate.position,plate.grid_index),float('inf'))
        self.assertLess(path_distance(state,plate.position,plate.grid_index,allow_timed=True),float('inf'))
        action=local_policy_action(state,build_candidate_set(state))
        self.assertEqual(action.mode,'button')
        self.assertEqual(action.action_id,'press_button_-100021')

    def test_a_permanently_isolated_plate_is_not_admitted_as_a_timed_route(self):
        state=replace(self.state,layout=replace(self.state.layout,
            blocked=frozenset({21,23,7,37})))
        self.assertNotEqual(local_policy_action(state,build_candidate_set(state)).mode,'button')

    def test_projectile_without_hostile_target_keeps_a_legal_escape(self):
        projectile=Entity(90,9,Vec2(260,320),Vec2(4,0),hit_points=1)
        state=replace(self.state,projectiles=(projectile,))
        candidates=build_candidate_set(state)
        self.assertTrue(candidates.admissible_candidates,candidates.rejected_candidates)
        action=local_policy_action(state,candidates)
        self.assertEqual(action.action_id,'evade_projectile')
        self.assertNotEqual(action.move,Vec2())
        self.assertEqual(action.shoot,Vec2())

    def test_distant_trap_fire_does_not_permanently_suppress_plate_progress(self):
        projectile=Entity(90,9,Vec2(90,320),Vec2(3,0),hit_points=1)
        state=replace(self.state,projectiles=(projectile,))
        action=local_policy_action(state,build_candidate_set(state))
        self.assertEqual(action.mode,'button')

    def test_actual_brimstone_trap_room_has_clearance_or_escape_action(self):
        root=Path(__file__).resolve().parents[1]
        raw=json.loads((root/'tests/fixtures/stage8-brimstone-button-trap-native95.json').read_text(encoding='utf8'))
        state=GameState.from_message(raw)
        self.assertEqual(state.enemies,())
        player=state.player.position
        state=replace(state,projectiles=(Entity(90,9,Vec2(player.x-60,player.y),Vec2(4,0),hit_points=1),))
        candidates=build_candidate_set(state)
        self.assertTrue(candidates.admissible_candidates,candidates.rejected_candidates)
        self.assertEqual(local_policy_action(state,candidates).action_id,'evade_projectile')

    def test_actual_receding_trap_fire_preserves_the_button_goal(self):
        root=Path(__file__).resolve().parents[1]
        raw=json.loads((root/'tests/fixtures/stage4-parallel-projectiles-native105.json').read_text(encoding='utf8'))
        state=GameState.from_message(raw)
        self.assertFalse(state.room_clear)
        self.assertEqual(state.enemies,())
        self.assertTrue(state.projectiles)
        geometry=state.geometry_features()
        self.assertFalse(any(t['imminent'] for t in geometry['projectile_threats']))
        self.assertLess(geometry['projectile_threats'][0]['distance'],80)
        self.assertEqual(local_policy_action(state,build_candidate_set(state)).mode,'button')

    def test_parallel_nearby_fire_is_distinct_from_a_collision_course(self):
        parallel=Entity(90,9,Vec2(260,320),Vec2(0,7.5),hit_points=1)
        state=replace(self.state,projectiles=(parallel,))
        self.assertEqual(local_policy_action(state,build_candidate_set(state)).mode,'button')
        approaching=replace(parallel,velocity=Vec2(7.5,0))
        state=replace(state,projectiles=(approaching,))
        self.assertEqual(local_policy_action(state,build_candidate_set(state)).action_id,'evade_projectile')

    def test_actual_trap_emergency_preserves_the_reachable_plate_route(self):
        root=Path(__file__).resolve().parents[1]
        raw=json.loads((root/'tests/fixtures/stage6-trap-stall-native108.json').read_text(encoding='utf8'))
        state=GameState.from_message(raw)
        self.assertFalse(state.enemies)
        plate=next(event for event in state.layout.grid_events if event.kind=='button')
        action=local_policy_action(state,build_candidate_set(state))
        self.assertEqual(action.waypoint,plate.position)
        self.assertEqual(action.shoot,Vec2())
        # Braking changes the same recorded stream into a collision course.
        # Emergency ownership must preserve the identical plate goal.
        braking=replace(state,player=replace(state.player,velocity=Vec2()))
        action=local_policy_action(braking,build_candidate_set(braking))
        self.assertEqual(action.action_id,'evade_projectile')
        self.assertEqual(action.waypoint,plate.position)
        self.assertEqual(action.shoot,Vec2())

    def test_projectile_escape_without_a_plate_does_not_invent_a_goal(self):
        state=replace(self.state,layout=replace(self.state.layout,grid_events=()),
            projectiles=(Entity(90,9,Vec2(260,320),Vec2(7.5,0),hit_points=1),))
        action=local_policy_action(state,build_candidate_set(state))
        self.assertEqual(action.action_id,'evade_projectile')
        self.assertIsNone(action.waypoint)


if __name__ == "__main__":
    unittest.main()
