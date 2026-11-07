import unittest

from isaac_jev.decision import build_candidate_set, build_policy_observation, policy_router, should_call_jev
from dataclasses import replace

from isaac_jev.models import Entity, GameState, GridEvent, Hazard, Pickup, RoomLayout, Door, Vec2


class HarnessV2Tests(unittest.TestCase):
    def test_incoming_charge_offers_side_dodges(self):
        state = GameState(frame=1, room_clear=False, player=Entity(0, 1, Vec2(0, 0), Vec2(), 6),
                          enemies=(Entity(3, 10, Vec2(-100, 0), Vec2(10, 0), 5, telegraph="Charge"),),
                          projectiles=())
        choices = build_candidate_set(state)
        self.assertEqual({action.action_id for action in choices.admissible_candidates},
                         {"dodge_charge_left", "dodge_charge_right"})

    def test_distant_tnt_is_approached_before_firing(self):
        walls = frozenset({*range(15), *range(120, 135), 15, 29, 30, 44, 45, 59, 60, 74, 75, 89, 90, 104, 105, 119, 17})
        layout = RoomLayout(room_index=82, grid_width=15, grid_height=9, blocked=walls,
                            grid_events=(GridEvent("tnt", 17, Vec2(120, 160), True, False, -100017),))
        state = GameState(frame=4162, room_clear=True, player=Entity(0, 1, Vec2(547, 198), Vec2(), 6, tear_range=260),
                          enemies=(), projectiles=(), layout=layout, player_grid_index=43)
        action = build_candidate_set(state).admissible_candidates[0]
        self.assertEqual(action.action_id, "shoot_tnt_-100017")
        self.assertNotEqual(action.move, Vec2())
        self.assertEqual(action.shoot, Vec2())
        near = replace(state, player=Entity(0, 1, Vec2(280, 160), Vec2(), 6, tear_range=260), player_grid_index=21)
        ready = build_candidate_set(near).admissible_candidates[0]
        self.assertEqual(ready.move, Vec2())
        self.assertEqual(ready.shoot, Vec2(-1, 0))

    def test_grab_bag_and_trinket_swap_are_real_loot_choices(self):
        state = GameState(frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6),
                          enemies=(), projectiles=(), held_trinkets=(10,), trinket_slots=1,
                          pickups=(Pickup(1, Vec2(40, 0), 0, 0, 0, False, "grab bag", -1, "grab_bag"),
                                   Pickup(2, Vec2(80, 0), 20, 0, 0, False, "new trinket", -1, "trinket")))
        choices = build_candidate_set(state)
        ids = {action.action_id for action in choices.admissible_candidates}
        self.assertEqual(ids, {"take_pickup_1", "take_pickup_2", "keep_trinket_2"})
        self.assertTrue(should_call_jev(state, choices))

    def test_normal_combat_exposes_two_to_five_admissible_candidates(self):
        state = GameState(
            frame=1,
            room_clear=False,
            player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(180, 0), Vec2(), 5),),
            projectiles=(),
        )
        candidates = build_candidate_set(state)
        self.assertEqual(candidates.policy, "combat")
        self.assertGreaterEqual(len(candidates.admissible_candidates), 2)
        self.assertLessEqual(len(candidates.admissible_candidates), 5)

    def test_imminent_projectile_filters_stationary_and_approach_candidates(self):
        state = GameState(
            frame=1,
            room_clear=False,
            player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(180, 0), Vec2(), 5),),
            projectiles=(Entity(3, 9, Vec2(30, 0), Vec2(-2, 0), 0),),
        )
        candidates = build_candidate_set(state)
        ids = {item.action_id for item in candidates.admissible_candidates}
        self.assertNotIn("hold_and_fire", ids)
        self.assertNotIn("advance_and_fire", ids)
        self.assertTrue(candidates.admissible_candidates)

    def test_single_legal_candidate_has_a_reason(self):
        state = GameState(
            frame=1,
            room_clear=False,
            player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(),
            projectiles=(),
        )
        candidates = build_candidate_set(state)
        self.assertEqual(len(candidates.admissible_candidates), 1)
        self.assertTrue(candidates.single_legal_reason)

    def test_single_navigation_door_does_not_need_a_remote_choice(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(100, 0), target_room_index=2),)), planned_door_slot=0,
        )
        candidates = build_candidate_set(state)
        self.assertEqual(candidates.policy, "navigation")
        self.assertEqual(policy_router(state, candidates), "navigation")
        self.assertFalse(should_call_jev(state, candidates))

    def test_safe_unexplored_doors_are_real_remote_choices(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 2), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(
                Door(0, Vec2(100, 0), target_room_index=2, target_room_type="default"),
                Door(1, Vec2(0, -100), target_room_index=3, target_room_type="shop"),
                Door(2, Vec2(-100, 0), target_room_index=4, target_room_type="curse"),
                Door(3, Vec2(0, 100), target_room_index=5, target_room_type="default"),
            )), planned_door_slot=1, visited_room_indices=frozenset({1, 5}), previous_room_index=5,
        )
        candidates = build_candidate_set(state)
        self.assertEqual([item.action_id for item in candidates.admissible_candidates], ["enter_door_1", "enter_door_0"])
        self.assertTrue(should_call_jev(state, candidates))
        committed = build_candidate_set(replace(state, planned_door_slot=0, planned_goal="committed navigation choice"))
        self.assertEqual([item.action_id for item in committed.admissible_candidates], ["enter_door_0"])
        blocked = build_candidate_set(replace(state, unreachable_door_slots=frozenset({0})))
        self.assertEqual([item.action_id for item in blocked.admissible_candidates], ["enter_door_1"])

    def test_navigation_forecasts_compare_progress_and_key_cost(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(320, 280), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=86, doors=(
                Door(0, Vec2(40, 280), target_room_index=85, target_room_type="default"),
                Door(2, Vec2(600, 280), target_room_index=87, target_room_type="treasure",
                     locked=True, lock_known=True, open=False, open_known=True),
            )), planned_door_slot=2, keys=1, previous_room_index=85,
            visited_room_indices=frozenset({85, 86}),
            safe_move_directions={"right": "safe", "left": "safe"},
            recent_actions=({"id": "enter_door_0", "movement_px": 0},),
        )
        observation = build_policy_observation(state, build_candidate_set(state))
        self.assertEqual(observation["feedback"]["recent_actions"][0]["id"], "enter_door_0")
        treasure = next(item for item in observation["candidates"] if item["id"] == "enter_door_2")
        self.assertEqual(treasure["forecast"]["keys_consumed_on_entry"], 1)
        self.assertEqual(treasure["forecast"]["target_room_type"], "treasure")
        self.assertGreater(treasure["forecast"]["target_progress_px"], 0)
        self.assertEqual(treasure["forecast"]["horizon_frames"], 12)
        blocked = build_policy_observation(
            replace(state, safe_move_directions={"right": "grid_wall"}), build_candidate_set(state))
        blocked_treasure = next(item for item in blocked["candidates"] if item["id"] == "enter_door_2")
        self.assertEqual(blocked_treasure["forecast"]["blocked_reason"], "grid_wall")
        self.assertEqual(blocked_treasure["forecast"]["target_progress_px"], 0)

    def test_multiple_hazards_are_real_choices_until_one_is_being_cleared(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            hazards=(Hazard(1, "fire", 33, Vec2(180, 0), Vec2()), Hazard(3, "fire", 33, Vec2(220, 0), Vec2())),
        )
        candidates = build_candidate_set(state)
        self.assertEqual({item.action_id for item in candidates.admissible_candidates}, {"clear_hazard_1", "clear_hazard_3"})
        self.assertTrue(should_call_jev(state, candidates))
        observation = build_policy_observation(state, candidates)
        self.assertEqual(len(observation["candidates"]), 2)
        active = build_candidate_set(replace(state, last_action_id="clear_hazard_3", last_action_mode="hazard"))
        self.assertEqual([item.action_id for item in active.admissible_candidates], ["clear_hazard_3"])

    def test_multiple_loot_candidates_are_a_remote_conflict(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(100, 0), target_room_index=2),)),
            pickups=(
                Pickup(1, Vec2(20, 0), 0, 0, 3, True, "quality item", -1, "other"),
                Pickup(2, Vec2(30, 0), 0, 0, 1, False, "key", -1, "key"),
            ),
        )
        candidates = build_candidate_set(state)
        self.assertEqual(candidates.policy, "loot")
        self.assertGreaterEqual(len(candidates.admissible_candidates), 2)
        self.assertEqual(policy_router(state, candidates), "loot")
        self.assertTrue(should_call_jev(state, candidates))

    def test_single_loot_candidate_stays_local(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(100, 0), target_room_index=2),)),
            pickups=(Pickup(2, Vec2(30, 0), 0, 0, 1, False, "key", -1, "key"),),
        )
        candidates = build_candidate_set(state)
        self.assertEqual(len(candidates.admissible_candidates), 1)
        self.assertEqual(policy_router(state, candidates), "loot")
        self.assertFalse(should_call_jev(state, candidates))

    def test_loot_observation_excludes_room_grid_and_combat_entities(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(100, 0), Vec2(), 5),), projectiles=(),
            layout=RoomLayout(room_index=1, grid_width=13, grid_height=7, blocked=frozenset({2}), doors=()),
            pickups=(Pickup(1, Vec2(20, 0), 0, 0, 3, True, "quality item", -1, "other"), Pickup(2, Vec2(30, 0), 0, 0, 1, False, "key", -1, "key")),
        )
        candidates = build_candidate_set(state)
        observation = build_policy_observation(state, candidates)
        self.assertEqual(observation["policy"], "loot")
        self.assertNotIn("enemies", observation)
        self.assertNotIn("grid", observation)

    def test_combat_observation_has_one_geometry_block_and_no_room_graph(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(180, 0), Vec2(), 5),), projectiles=(),
            layout=RoomLayout(room_index=1, grid_width=13, grid_height=7, blocked=frozenset({2}), doors=(Door(0, Vec2(), target_room_index=2),)),
        )
        candidates = build_candidate_set(state)
        observation = build_policy_observation(state, candidates)
        self.assertEqual(observation["policy"], "combat")
        self.assertEqual(list(observation).count("geometry"), 1)
        self.assertNotIn("doors", observation)
        self.assertIn("line_of_fire", observation["geometry"])


if __name__ == "__main__":
    unittest.main()
