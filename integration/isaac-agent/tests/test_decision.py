import unittest
from dataclasses import replace

from isaac_jev.decision import build_candidate_set, candidate_actions, conservative_action, hard_rule_filter, hazard_actions, repeat_action_penalty_action, should_call_jev
from isaac_jev.models import Action, BombWall, DangerEffect, Door, Entity, GameState, Hazard, Pickup, RoomLayout, Vec2
from isaac_jev.navigation import bombing_position, door_path_distance, move_towards, path_distance
from isaac_jev.tuning import PolicyProfile


def make_state(projectiles=()):
    return GameState(
        frame=1,
        room_clear=False,
        player=Entity(0, 1, Vec2(0, 0), Vec2(), 6),
        enemies=(Entity(1, 10, Vec2(10, 0), Vec2(), 5),),
        projectiles=projectiles,
    )


class DecisionTests(unittest.TestCase):
    def test_tracking_bomb_preempts_combat_loot_and_navigation_with_real_escapes(self):
        for room_clear in (False, True):
            state = GameState(
                frame=1, room_clear=room_clear,
                player=Entity(0, 1, Vec2(), Vec2(), 6),
                enemies=(Entity(1, 10, Vec2(100, 0), Vec2(), 5),) if not room_clear else (),
                projectiles=(),
                pickups=(Pickup(9, Vec2(20, 0), 1, 0, 0, False, pickup_kind="key"),),
                danger_effects=(DangerEffect(4, "ghost_bomb", Vec2(100, 0), Vec2(-4, 0), 42, 4),),
            )
            candidates = build_candidate_set(state)
            self.assertEqual(candidates.policy, "emergency")
            self.assertGreaterEqual(len(candidates.admissible_candidates), 2)
            self.assertTrue(should_call_jev(state, candidates))
            self.assertTrue(all(action.mode == "evade" and action.shoot == Vec2()
                                for action in candidates.admissible_candidates))
            self.assertEqual(conservative_action(state).action_id, "evade_ghost_bomb")

    def test_nonclosing_or_distant_bomb_does_not_preempt_normal_action(self):
        base = dict(frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
                    enemies=(Entity(1, 10, Vec2(100, 0), Vec2(), 5),), projectiles=())
        for position, velocity in ((Vec2(100, 0), Vec2(4, 0)), (Vec2(400, 0), Vec2(-4, 0))):
            state = GameState(**base, danger_effects=(DangerEffect(4, "ghost_bomb", position, velocity),))
            self.assertEqual(build_candidate_set(state).policy, "combat")

    def test_pickup_path_avoids_active_spike_grid(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(100, 40), Vec2(), 6),
            player_grid_index=7, enemies=(), projectiles=(),
            layout=RoomLayout(room_index=85, grid_width=5, grid_height=3,
                              danger_grid_indices=frozenset({8})),
        )
        step = move_towards(state, Vec2(180, 40), target_grid_index=9)
        self.assertNotEqual(step, Vec2(1, 0))

    def test_blue_fire_never_becomes_tear_target_and_only_bombs_above_four(self):
        base = dict(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(), projectiles=(), hazards=(Hazard(33, "blue_fire", 33, Vec2(80, 0), Vec2(), variant=2, requires_bomb=True),),
        )
        low = candidate_actions(GameState(**base, bombs=4))
        self.assertNotIn("clear_hazard_33", [item.action_id for item in low])
        self.assertNotIn("bomb_hazard_33", [item.action_id for item in low])
        high = candidate_actions(GameState(**base, bombs=5))
        self.assertIn("bomb_hazard_33", [item.action_id for item in high])

    def test_purple_fire_never_becomes_tear_target_and_only_bombs_above_four(self):
        base = dict(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(), projectiles=(), hazards=(Hazard(34, "purple_fire", 33, Vec2(80, 0), Vec2(), variant=3, requires_bomb=True),),
        )
        low = candidate_actions(GameState(**base, bombs=4))
        self.assertNotIn("clear_hazard_34", [item.action_id for item in low])
        self.assertNotIn("bomb_hazard_34", [item.action_id for item in low])
        high = candidate_actions(GameState(**base, bombs=5))
        self.assertIn("bomb_hazard_34", [item.action_id for item in high])

    def test_candidate_action_ids_are_unique(self):
        actions = candidate_actions(make_state())
        self.assertEqual(len({action.action_id for action in actions}), len(actions))
        self.assertTrue(all(action.shoot.x == 1 for action in actions))

    def test_fallback_strafes_when_projectiles_are_present(self):
        action = conservative_action(make_state((Entity(3, 9, Vec2(4, 0), Vec2(), 0),)))
        self.assertEqual(action.action_id, "strafe_left")
        self.assertEqual(action.move, Vec2(0, -1))

    def test_projectile_threat_never_offers_stationary_fire(self):
        actions = candidate_actions(make_state((Entity(3, 9, Vec2(4, 0), Vec2(), 0),)))
        self.assertNotIn("hold_and_fire", [action.action_id for action in actions])
        self.assertTrue(all(action.move != Vec2() for action in actions))

    def test_visible_projectile_moving_toward_player_triggers_evasion_before_close(self):
        state = make_state((Entity(3, 9, Vec2(200, 0), Vec2(-1, 0), 0),))
        actions = candidate_actions(state)
        self.assertNotIn("hold_and_fire", [action.action_id for action in actions])
        self.assertTrue(all(action.move != Vec2() for action in actions))

    def test_distant_projectile_allows_approach_to_reach_enemy_tear_range(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(220, 0), Vec2(1, 0), 5),),
            projectiles=(Entity(3, 9, Vec2(240, 0), Vec2(-1, 0), 0),),
        )
        actions = candidate_actions(state)
        self.assertEqual(actions[0].action_id, "advance_and_evade_fire")
        self.assertEqual(actions[0].move, Vec2(1, 0))
        self.assertNotIn("hold_and_fire", [action.action_id for action in actions])

    def test_imminent_projectile_blocks_approach_even_when_enemy_is_out_of_range(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(220, 0), Vec2(1, 0), 5),),
            projectiles=(Entity(3, 9, Vec2(150, 0), Vec2(-1, 0), 0),),
        )
        actions = candidate_actions(state)
        self.assertNotIn("advance_and_evade_fire", [action.action_id for action in actions])
        self.assertTrue(all(action.move != Vec2() for action in actions))

    def test_fallback_approaches_when_projectile_is_distant_but_enemy_is_out_of_range(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(220, 0), Vec2(1, 0), 5),),
            projectiles=(Entity(3, 9, Vec2(240, 0), Vec2(-1, 0), 0),),
        )
        action = conservative_action(state)
        self.assertEqual(action.action_id, "advance_and_evade_fire")

    def test_diagonal_enemy_uses_one_fire_direction(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(10, 10), Vec2(), 5),), projectiles=(),
        )
        action = candidate_actions(state)[0]
        self.assertIn(action.shoot, (Vec2(1, 0), Vec2(0, 1)))

    def test_fire_direction_leads_a_laterally_moving_enemy(self):
        # Without a lead, (39, 40) selects vertical fire. During the tear's
        # flight the enemy crosses the axis, so horizontal fire is the hit path.
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6, 260, 1.0),
            enemies=(Entity(1, 10, Vec2(39, 40), Vec2(3, 0), 5),), projectiles=(),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.shoot, Vec2(1, 0))

    def test_movement_and_predicted_fire_directions_are_independent(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(0, 220), Vec2(2, 0), 5),), projectiles=(),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "advance_and_fire")
        self.assertEqual(action.move, Vec2(0, 1))
        self.assertEqual(action.shoot, Vec2(0, 1))

    def test_stationary_enemy_inside_range_prefers_hold_and_fire(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(180, 0), Vec2(), 5),), projectiles=(),
        )
        actions = candidate_actions(state)
        self.assertEqual(actions[0].action_id, "hold_and_fire")
        self.assertEqual(actions[0].move, Vec2())

    def test_stationary_enemy_outside_range_still_approaches(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(240, 0), Vec2(), 5),), projectiles=(),
        )
        self.assertEqual(candidate_actions(state)[0].action_id, "advance_and_fire")

    def test_wall_between_player_and_enemy_removes_shooting_candidates(self):
        state = GameState(
            frame=1, room_clear=False,
            player=Entity(0, 1, Vec2(0, 40), Vec2(), 6, grid_index=5),
            player_grid_index=5,
            enemies=(Entity(1, 10, Vec2(160, 40), Vec2(), 5, grid_index=9),),
            projectiles=(),
            layout=RoomLayout(room_index=123, grid_width=5, grid_height=3,
                              blocked=frozenset({7})),
        )
        candidate_set = build_candidate_set(state)
        self.assertTrue(candidate_set.rejected_candidates)
        self.assertTrue(all(item.shoot == Vec2() for item in candidate_set.admissible_candidates))
        self.assertTrue(any(item.action_id.startswith("reposition_to_fire_lane")
                            for item in candidate_set.admissible_candidates))
        self.assertTrue(any(item["rule"] == "line_of_fire_blocked"
                            for item in candidate_set.rejected_candidates))

    def test_door_path_uses_walkable_approach_tile_when_door_cell_is_blocked(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(80, 80), Vec2(), 6),
            player_grid_index=6, enemies=(), projectiles=(), layout=RoomLayout(
                room_index=10, grid_width=5, grid_height=3,
                blocked=frozenset({1}),
                doors=(Door(1, Vec2(40, 0), target_room_index=11, grid_index=1),),
            ),
        )
        self.assertLess(door_path_distance(state, state.layout.doors[0]), float("inf"))

    def test_low_tear_range_requires_closer_approach(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6, 100),
            enemies=(Entity(1, 10, Vec2(150, 0), Vec2(1, 0), 5),), projectiles=(),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "advance_and_fire")

    def test_poop_between_player_and_enemy_is_cleared_before_combat(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(180, 0), Vec2(), 5),), projectiles=(),
            hazards=(Hazard(33, "poop", 149, Vec2(90, 0), Vec2()),),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "clear_hazard_33")
        self.assertEqual(action.mode, "hazard")

    def test_unrelated_live_poop_does_not_override_enemy_combat(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(180, 80), Vec2(), 5),), projectiles=(),
            hazards=(Hazard(34, "poop", 149, Vec2(-80, -80), Vec2()),),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.mode, "combat")
        self.assertEqual(action.action_id, "advance_and_fire")

    def test_ignored_unreachable_hazard_is_skipped_for_the_exit(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(), projectiles=(),
            hazards=(Hazard(-100065, "poop", 149, Vec2(-80, -80), Vec2()),),
            ignored_hazard_ids=frozenset({-100065}),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(100, 0), target_room_index=2),)),
            planned_door_slot=0,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "enter_door_0")
        self.assertEqual(action.mode, "navigate")

    def test_uncleared_room_with_only_ignored_hazard_can_leave(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(), projectiles=(),
            hazards=(Hazard(44, "poop", 149, Vec2(40, 0), Vec2()),),
            ignored_hazard_ids=frozenset({44}),
            layout=RoomLayout(room_index=1, doors=(Door(2, Vec2(100, 0), target_room_index=2),)),
            planned_door_slot=2,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "enter_door_2")
        self.assertEqual(action.mode, "navigate")

    def test_chest_is_a_first_class_strategic_target(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(), projectiles=(),
            pickups=(Pickup(91, Vec2(80, 0), 0, 0, 1, True, "red chest", -1, "red_chest"),),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(100, 0), target_room_index=2),)),
            planned_door_slot=0,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "open_chest_91")
        self.assertEqual(action.mode, "chest")

    def test_locked_hidden_door_is_never_selected(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(
                Door(0, Vec2(), target_room_index=2, target_room_type="secret", locked=True, lock_known=True),
                Door(1, Vec2(), target_room_index=3, target_room_type="default"),
            )), planned_door_slot=1,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "enter_door_1")

    def test_unknown_hidden_door_is_never_selected(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(
                Door(0, Vec2(), target_room_index=2, target_room_type="super_secret"),
                Door(1, Vec2(), target_room_index=3, target_room_type="default"),
            )), planned_door_slot=1,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "enter_door_1")

    def test_explicitly_unlocked_hidden_door_can_be_selected(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(
                Door(0, Vec2(), target_room_index=2, target_room_type="secret", locked=False, lock_known=True),
            )), planned_door_slot=0,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "enter_door_0")

    def test_bomb_opened_hidden_door_is_usable_when_lock_status_is_unknown(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(
                Door(0, Vec2(), target_room_index=2, target_room_type="secret", open=True, open_known=True),
            )), planned_door_slot=0,
        )
        self.assertEqual(candidate_actions(state)[0].action_id, "enter_door_0")

    def test_stationary_enemy_inside_effective_range_is_not_approached(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(90, 0), Vec2(), 5),), projectiles=(),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "hold_and_fire")

    def test_blocked_combat_move_repositions_before_firing(self):
        state = GameState(
            frame=10, room_clear=False, player=Entity(0, 1, Vec2(40, 40), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(120, 40), Vec2(), 5),), projectiles=(),
            player_grid_index=4,
            layout=RoomLayout(room_index=1, grid_width=3, grid_height=3, blocked=frozenset({5})),
            movement_blocked=True, movement_progress=0.0,
            last_action_id="advance_and_fire", last_action_mode="combat",
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "reposition_and_fire")
        self.assertNotEqual(action.move, Vec2())
        self.assertEqual(action.shoot, Vec2(1, 0))

    def test_combat_prefers_roomier_direction_over_corner(self):
        state = GameState(
            frame=10, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(180, 0), Vec2(), 5),), projectiles=(),
            player_grid_index=1,
            layout=RoomLayout(room_index=1, grid_width=3, grid_height=3, blocked=frozenset({0, 2})),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "hold_and_fire")
        self.assertEqual(action.move, Vec2())

    def test_fallback_turns_when_strafe_hits_a_blocked_corner(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(10, 0), Vec2(), 5),),
            projectiles=(Entity(3, 9, Vec2(-4, 0), Vec2(), 0),), player_grid_index=8,
            layout=RoomLayout(room_index=1, grid_width=3, grid_height=3, blocked=frozenset({5})),
        )
        action = conservative_action(state)
        self.assertEqual(action.move, Vec2(-1, 0))

    def test_clear_room_prioritizes_an_affordable_collectible(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(), coins=10,
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(0, -100), target_is_boss=True),)),
            pickups=(Pickup(8, Vec2(30, 0), 100, 5, 3, True, "#ITEM", 1),),
        )
        actions = candidate_actions(state)
        self.assertEqual(actions[0].mode, "item")
        self.assertEqual(actions[0].target, "#ITEM")

    def test_pickup_action_preserves_grid_route_around_blocker(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            player_grid_index=0,
            layout=RoomLayout(room_index=1, grid_width=3, grid_height=3, blocked=frozenset({1}), doors=(Door(0, Vec2(0, -100), target_room_index=2),)),
            pickups=(Pickup(8, Vec2(80, 0), 100, 0, 3, True, "#ITEM", 2),),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "take_item_8")
        self.assertEqual(action.move, Vec2(0, 1))

    def test_clear_room_collects_a_dropped_key_before_leaving(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(0, -100)),)),
            pickups=(Pickup(4, Vec2(25, 0), 0, 0, 0, False, "key", 1, "key"),),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "take_pickup_4")
        self.assertEqual(action.mode, "pickup")

    def test_clear_room_destroys_hazard_before_rewards_or_exit(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(0, -100), target_room_index=2),)),
            hazards=(Hazard(33, "fire", 33, Vec2(30, 0), Vec2()),),
            pickups=(Pickup(4, Vec2(25, 0), 0, 0, 0, False, "key", 1, "key"),),
            planned_door_slot=0,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "clear_hazard_33")
        self.assertEqual(action.mode, "hazard")
        self.assertEqual(action.shoot, Vec2())  # first retreat beyond fire contact range
        self.assertEqual(action.move, Vec2(-1, 0))

    def test_cleared_boss_room_collects_reward_before_residual_hazard(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=12, room_type="boss", is_boss=True, doors=(Door(0, Vec2(0, -100), target_room_index=13),)),
            hazards=(Hazard(33, "poop", 149, Vec2(80, 0), Vec2()),),
            pickups=(Pickup(91, Vec2(40, 0), 0, 0, 2, True, "boss item", -1, "other"),),
            planned_door_slot=0,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "take_item_91")
        self.assertEqual(action.mode, "item")

    def test_boss_room_keeps_collectible_priority_when_trapdoor_is_available(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=12, room_type="boss", is_boss=True),
            pickups=(Pickup(91, Vec2(40, 0), 0, 0, 2, True, "boss item", -1, "other"),),
            boss_exit_available=True, boss_exit_position=Vec2(100, 0), boss_exit_grid_index=17,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "take_item_91")
        self.assertEqual(action.mode, "item")

    def test_boss_room_enters_trapdoor_after_ignored_reward(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=12, room_type="boss", is_boss=True),
            pickups=(Pickup(91, Vec2(40, 0), 0, 0, 2, True, "boss item", -1, "other"),),
            ignored_pickup_ids=frozenset({91}),
            boss_exit_available=True, boss_exit_position=Vec2(100, 0), boss_exit_grid_index=17,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "enter_boss_exit_17")
        self.assertEqual(action.mode, "boss_exit")
        self.assertNotIn("enter_door_", action.action_id)

    def test_boss_waits_two_seconds_for_reward_spawn_before_exiting(self):
        state = GameState(
            frame=159, room_clear=True, room_cleared_frame=100,
            player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(), projectiles=(),
            layout=RoomLayout(room_index=12, room_type="boss", is_boss=True),
            boss_exit_available=True, boss_exit_position=Vec2(100, 0), boss_exit_grid_index=17,
        )
        self.assertEqual(candidate_actions(state)[0].action_id, "wait_for_boss_reward")
        reward = Pickup(91, Vec2(40, 0), 0, 0, 2, True, "boss item", -1, "other")
        self.assertEqual(candidate_actions(replace(state, pickups=(reward,)))[0].action_id, "take_item_91")
        self.assertEqual(candidate_actions(replace(state, frame=160))[0].action_id, "enter_boss_exit_17")
        self.assertEqual(candidate_actions(replace(state, frame=170, pickups=(reward,)))[0].action_id, "take_item_91")

    def test_full_health_boss_heart_does_not_block_exit(self):
        state = GameState(
            frame=161, room_clear=True, room_cleared_frame=100,
            player=Entity(0, 1, Vec2(), Vec2(), 6), red_hearts=6, max_hearts=6,
            enemies=(), projectiles=(),
            layout=RoomLayout(room_index=12, room_type="boss", is_boss=True),
            pickups=(Pickup(92, Vec2(40, 0), 0, 0, 0, False, "red heart", -1, "red_heart"),),
            boss_exit_available=True, boss_exit_position=Vec2(100, 0), boss_exit_grid_index=17,
        )
        self.assertEqual(candidate_actions(state)[0].action_id, "enter_boss_exit_17")

    def test_full_health_boss_hearts_do_not_hide_collectible_from_old_packet(self):
        state = GameState.from_message({
            "frame": 18697, "room_clear": True, "room_cleared_frame": 17200,
            "player": {"hp": 6, "red_hearts": 6, "max_hearts": 6},
            "layout": {"room_index": 62, "room_type": "boss", "is_boss": True},
            "pickups": [
                {"id": 1317, "kind": "red_heart", "pos": {"x": 200}},
                {"id": 1318, "kind": "red_half_heart", "pos": {"x": 120}},
                {"id": 1350, "kind": "collectible", "subtype": 195,
                 "name": "Mom's Coin Purse", "pos": {"x": 300}},
            ],
            "boss_exit_available": True, "boss_exit_position": {"x": 320, "y": 200},
            "boss_exit_grid_index": 37,
        })
        candidates = build_candidate_set(state)
        self.assertEqual([action.action_id for action in candidates.admissible_candidates], ["take_item_1350"])
        self.assertEqual(candidate_actions(state)[0].action_id, "take_item_1350")

    def test_boss_room_does_not_skip_visible_reward_with_no_path_estimate(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=12, room_type="boss", is_boss=True, blocked=frozenset({17})),
            pickups=(Pickup(92, Vec2(120, 0), 0, 0, 2, True, "boss item", 17, "other"),),
            boss_exit_available=True, boss_exit_position=Vec2(100, 0), boss_exit_grid_index=17,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "take_item_92")
        self.assertNotEqual(action.mode, "boss_exit")

    def test_blocked_combat_lane_offers_movement_only_reposition(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(180, 0), Vec2(), 10),), projectiles=(),
            hazards=(Hazard(33, "poop", 14, Vec2(90, 0), Vec2()),),
            ignored_hazard_ids=frozenset({33}),
        )
        candidates = build_candidate_set(state)
        self.assertIn("reposition_to_fire_lane", [item.action_id for item in candidates.admissible_candidates])
        reposition = next(item for item in candidates.admissible_candidates if item.action_id == "reposition_to_fire_lane")
        self.assertEqual(reposition.shoot, Vec2())
        self.assertNotEqual(reposition.move, Vec2())

    def test_clear_room_uses_one_bomb_for_tinted_xrock_when_available(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(), bombs=1,
            hazards=(Hazard(-100012, "xrock", 7, Vec2(80, 0), Vec2(), grid_index=12, requires_bomb=True),),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(0, -100), target_room_index=2),)), planned_door_slot=0,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "bomb_hazard_-100012")
        self.assertEqual(action.mode, "bomb")
        self.assertEqual(action.shoot, Vec2())

    def test_boss_bomb_targets_real_boss_even_at_low_health(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(2, 10, Vec2(80, 0), Vec2(), 40),
                     Entity(3, 19, Vec2(90, 0), Vec2(), 3, is_boss=True)),
            projectiles=(), bombs=1, layout=RoomLayout(room_index=5, room_type="boss", is_boss=True),
            safe_move_directions={"left": "safe"},
        )
        candidates = build_candidate_set(state)
        bomb = next(item for item in candidates.admissible_candidates if item.action_id == "bomb_boss_3")
        self.assertEqual(bomb.bomb_site, state.player.position)
        self.assertNotIn("bomb_boss_2", [item.action_id for item in candidates.raw_candidates])

    def test_boss_bomb_requires_resources_clear_retreat_and_no_projectile(self):
        base = {"frame": 1, "room_clear": False, "player": {"hp": 6},
                "enemies": [{"id": 3, "type": 19, "pos": {"x": 90}, "hp": 3, "is_boss": True}],
                "layout": {"room_index": 5, "room_type": "boss", "is_boss": True},
                "bombs": 1, "safe_move_directions": {"left": "safe"}}
        for change in ({"bombs": 0}, {"bomb_active": True}, {"bomb_placed": True},
                       {"bomb_error": "no clear bomb escape corridor"},
                       {"safe_move_directions": {}},
                       {"enemies": [{"id": 3, "type": 19, "pos": {"x": 30}, "hp": 3, "is_boss": True}]},
                       {"projectiles": [{"id": 4, "type": 9, "pos": {"x": 70}, "vel": {"x": -1}}]}):
            state = GameState.from_message(base | change)
            self.assertFalse(any(item.action_id.startswith("bomb_boss_")
                                 for item in build_candidate_set(state).admissible_candidates), change)

    def test_boss_bomb_filter_does_not_reject_x_rock_bomb(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            bombs=1, layout=RoomLayout(room_index=1),
        )
        rock = Action("bomb_hazard_-100012", Vec2(), Vec2(), mode="bomb", target="xrock")
        admissible, rejected = hard_rule_filter(state, [rock])
        self.assertEqual(admissible, [rock])
        self.assertEqual(rejected, [])

    def test_clear_room_skips_tinted_xrock_when_no_bombs(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(), bombs=0,
            hazards=(Hazard(-100012, "xrock", 7, Vec2(80, 0), Vec2(), grid_index=12, requires_bomb=True),),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(0, -100), target_room_index=2),)), planned_door_slot=0,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "enter_door_0")
        self.assertEqual(action.mode, "navigate")

    def test_bomb_targets_use_reachable_site_and_prioritize_rock_then_hidden_rooms(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(0, 0), Vec2(), 6), enemies=(), projectiles=(), bombs=3,
            hazards=(Hazard(-100012, "xrock", 4, Vec2(160, 0), Vec2(), grid_index=12, requires_bomb=True),),
            layout=RoomLayout(room_index=1, bomb_walls=(
                BombWall(2, Vec2(300, 0), Vec2(220, 0), -1, "super_secret"),
                BombWall(0, Vec2(-300, 0), Vec2(-220, 0), -1, "secret"),
            )),
        )
        rock = candidate_actions(state)[0]
        self.assertEqual(rock.action_id, "bomb_hazard_-100012")
        self.assertIsNotNone(rock.bomb_site)
        self.assertLessEqual(rock.bomb_site.distance_to(state.hazards[0].position), 60)
        without_rock = GameState.from_message({
            "frame": 1, "room_clear": True, "player": {}, "bombs": 2,
            "layout": {"room_index": 1, "bomb_walls": [
                {"slot": 2, "pos": {"x": 300}, "site": {"x": 220}, "grid_index": -1, "room_type": "super_secret"},
                {"slot": 0, "pos": {"x": -300}, "site": {"x": -220}, "grid_index": -1, "room_type": "secret"},
            ]},
        })
        self.assertEqual(candidate_actions(without_rock)[0].action_id, "bomb_secret_0")
        self.assertEqual(candidate_actions(GameState.from_message({
            "frame": 2, "room_clear": True, "player": {}, "bombs": 1,
            "layout": {"room_index": 1, "bomb_walls": [
                {"slot": 0, "pos": {}, "site": {}, "room_type": "secret", "bombed": True},
                {"slot": 2, "pos": {}, "site": {}, "room_type": "super_secret"},
            ]},
        }))[0].action_id, "bomb_super_secret_2")

    def test_xrock_site_is_adjacent_even_when_a_distant_site_would_be_reachable(self):
        # Room 97's first bomb was released roughly 100px from the rock and
        # left it intact. The planner must walk to an adjacent grid tile.
        blocked = frozenset({*range(15), 15, 29, 30, 44, 45, 52, 59, 60,
                             66, 67, 68, 74, 75, 82, 89, 90, 104, 105,
                             119, *range(120, 135)})
        state = GameState(
            frame=13201, room_clear=True,
            player=Entity(0, 1, Vec2(320, 160), Vec2(), 4),
            player_grid_index=22,
            layout=RoomLayout(room_index=97, grid_width=15,
                              grid_height=9, blocked=blocked),
            enemies=(), projectiles=(), bombs=1,
        )
        site = bombing_position(state, Vec2(360, 280), 68)
        self.assertIsNotNone(site)
        self.assertLessEqual(site[0].distance_to(Vec2(360, 280)), 60)

    def test_placed_bomb_waits_for_blast_and_does_not_retry_surviving_rock(self):
        base = {"frame": 10, "room_clear": True, "player": {}, "bombs": 2,
                "bomb_placed": True, "bomb_target_id": -100012,
                "hazards": [{"id": -100012, "kind": "xrock", "type": 4,
                             "requires_bomb": True, "pos": {"x": 80}, "grid_index": 12}],
                "layout": {"room_index": 1, "doors": [{"slot": 0, "target_room_index": 2}]}}
        self.assertEqual(candidate_actions(GameState.from_message(base | {"bomb_active": True}))[0].action_id, "wait_for_bomb")
        self.assertEqual(candidate_actions(GameState.from_message(base | {"bomb_active": False}))[0].action_id, "enter_door_0")

    def test_combat_has_priority_over_unrelated_hazard(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(80, 0), Vec2(), 5),), projectiles=(),
            hazards=(Hazard(33, "fire", 33, Vec2(-80, -80), Vec2()),),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.mode, "combat")
        self.assertNotEqual(action.action_id, "clear_hazard_33")

    def test_stuck_combat_allows_hazard_clear_without_walking_into_fire(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(180, 0), Vec2(), 5),), projectiles=(),
            hazards=(Hazard(33, "fire", 33, Vec2(90, 0), Vec2()),), combat_stuck=True,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "clear_hazard_33")
        self.assertEqual(action.move, Vec2())
        self.assertEqual(action.shoot, Vec2(1, 0))

    def test_failed_bomb_does_not_leave_combat_waiting_forever(self):
        # Room 97, frame 8929: the old Mod's missing DropBomb method caused
        # the X rock to be ignored. The remaining poop has no reachable
        # firing lane, but four hostile enemies are still present.
        blocked = frozenset({*range(15), 15, 29, 30, 44, 45, 52, 59, 60,
                             66, 67, 68, 74, 75, 82, 89, 90, 104, 105,
                             119, *range(120, 135)})
        state = GameState(
            frame=8929, room_clear=False,
            player=Entity(0, 1, Vec2(384.6, 155.3), Vec2(), 4),
            player_grid_index=24,
            enemies=(Entity(1, 77, Vec2(277.1, 169.5), Vec2(), 12),),
            projectiles=(),
            layout=RoomLayout(room_index=97, grid_width=15, grid_height=9,
                              blocked=blocked),
            hazards=(
                Hazard(-100068, "xrock", 4, Vec2(360, 280), Vec2(),
                       grid_index=68, requires_bomb=True),
                Hazard(-100067, "poop", 14, Vec2(320, 280), Vec2(),
                       grid_index=67),
            ),
            ignored_hazard_ids=frozenset({-100068}), combat_stuck=True,
        )
        self.assertEqual(hazard_actions(state), [])
        actions = candidate_actions(state)
        self.assertTrue(actions)
        self.assertTrue(all(action.mode == "combat" for action in actions))
        self.assertNotEqual(actions[0].action_id, "wait_for_safety_filter")

    def test_fire_lane_uses_reachable_side_instead_of_retreating_forever(self):
        # Reproduces the room-85 corner: the old 110px minimum picked a lane
        # beyond the fire and Lua's 90px retreat vetoed every approach step.
        blocked = frozenset({0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
                             15, 16, 28, 29, 30, 44, 45, 59, 60, 74, 75, 89,
                             90, 104, 105, 106, 118, 119, *range(120, 135)})
        state = GameState(
            frame=343, room_clear=True,
            player=Entity(0, 1, Vec2(116, 405), Vec2(), 6, 260), player_grid_index=107,
            enemies=(), projectiles=(),
            layout=RoomLayout(room_index=85, grid_width=15, grid_height=9, blocked=blocked),
            hazards=(Hazard(8, "fire", 33, Vec2(160, 360), Vec2(), grid_index=93),),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "clear_hazard_8")
        self.assertEqual(action.move, Vec2(0, -1))
        self.assertEqual(action.shoot, Vec2())
        corner_cleared = GameState(
            frame=353, room_clear=True,
            player=Entity(0, 1, Vec2(116, 377), Vec2(), 6, 260), player_grid_index=92,
            enemies=(), projectiles=(), layout=state.layout, hazards=state.hazards,
        )
        self.assertEqual(candidate_actions(corner_cleared)[0].move, Vec2(-1, 0))
        aligned = GameState(
            frame=365, room_clear=True,
            player=Entity(0, 1, Vec2(80, 360), Vec2(), 6, 260), player_grid_index=91,
            enemies=(), projectiles=(),
            layout=state.layout, hazards=state.hazards,
        )
        shot = candidate_actions(aligned)[0]
        self.assertEqual(shot.move, Vec2())
        self.assertEqual(shot.shoot, Vec2(1, 0))
        too_close = GameState(
            frame=360, room_clear=True,
            player=Entity(0, 1, Vec2(96, 360), Vec2(), 6, 260), player_grid_index=91,
            enemies=(), projectiles=(), layout=state.layout, hazards=state.hazards,
        )
        correction = candidate_actions(too_close)[0]
        self.assertEqual(correction.move, Vec2(-1, 0))
        self.assertEqual(correction.shoot, Vec2())

    def test_entity_fire_blocks_grid_route(self):
        state = GameState(
            frame=1, room_clear=True,
            player=Entity(0, 1, Vec2(40, 120), Vec2(), 6), player_grid_index=0,
            enemies=(), projectiles=(), layout=RoomLayout(room_index=1, grid_width=3, grid_height=1),
            hazards=(Hazard(8, "fire", 33, Vec2(80, 120), Vec2(), grid_index=1),),
        )
        self.assertEqual(path_distance(state, Vec2(120, 120), 2), float("inf"))

    def test_hazard_observation_must_be_valid_before_exit(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(0, -100), target_room_index=2),)),
            hazards_observation_valid=False, planned_door_slot=0,
        )
        self.assertEqual(candidate_actions(state)[0].action_id, "wait_for_hazard_observation")

    def test_non_destructible_hazard_does_not_create_a_shoot_loop(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            hazards=(Hazard(33, "poop", 149, Vec2(30, 0), Vec2(), destructible=False),),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(0, -100), target_room_index=2),)),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "wait_for_hazard_clear")
        self.assertEqual(action.shoot, Vec2())

    def test_native_room_clear_overrides_stale_mechanical_enemy_observation(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(900, 1000, Vec2(80, 0), Vec2(), 0),), projectiles=(),
            layout=RoomLayout(room_index=110, doors=(Door(0, Vec2(0, -100), target_room_index=123),)),
            planned_door_slot=0,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.mode, "navigate")
        self.assertEqual(action.action_id, "enter_door_0")
        self.assertEqual(action.shoot, Vec2())

    def test_native_room_clear_overrides_stale_projectile_observation(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(900, 1000, Vec2(80, 0), Vec2(), 0),),
            projectiles=(Entity(901, 9, Vec2(4, 0), Vec2(-1, 0), 0),),
            layout=RoomLayout(room_index=110, doors=(Door(0, Vec2(0, -100), target_room_index=123),)),
            planned_door_slot=0,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.mode, "navigate")
        self.assertEqual(action.action_id, "enter_door_0")
        self.assertEqual(action.shoot, Vec2())

    def test_resource_shortage_prioritizes_key_over_coin(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            keys=0, coins=0,
            layout=RoomLayout(room_index=1, room_type="default", doors=(Door(0, Vec2(0, -100), target_room_index=2),)),
            pickups=(Pickup(1, Vec2(20, 0), 0, 0, 0, False, "coin", -1, "coin"), Pickup(2, Vec2(30, 0), 0, 0, 0, False, "key", -1, "key")),
        )
        self.assertEqual(candidate_actions(state)[0].action_id, "take_pickup_2")

    def test_red_heart_is_skipped_at_full_red_health_but_soul_heart_is_kept(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            red_hearts=6, max_hearts=6, soul_hearts=0,
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(0, -100), target_room_index=2),)),
            pickups=(Pickup(1, Vec2(20, 0), 0, 0, 0, False, "red heart", -1, "red_heart"), Pickup(2, Vec2(30, 0), 0, 0, 0, False, "soul heart", -1, "soul_heart")),
        )
        self.assertEqual(candidate_actions(state)[0].action_id, "take_pickup_2")

    def test_room_planner_prefers_treasure_over_sacrifice_branch(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(), target_room_index=2, target_room_type="sacrifice"), Door(1, Vec2(), target_room_index=3, target_room_type="treasure"))),
            planned_door_slot=1,
        )
        self.assertEqual(candidate_actions(state)[0].action_id, "enter_door_1")

    def test_clear_room_skips_a_red_heart_when_red_health_is_full(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(0, -100), target_room_index=2),)), red_hearts=6, max_hearts=6,
            planned_door_slot=0,
            pickups=(Pickup(10, Vec2(25, 0), 0, 0, 0, False, "heart", 1, "heart"),),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "enter_door_0")

    def test_uncleared_room_without_enemy_observation_does_not_walk_into_a_locked_door(self):
        state = GameState(
            frame=1, room_clear=False, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(0, -100)),)),
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.mode, "wait")
        self.assertEqual(action.action_id, "wait_for_room_clear")

    def test_clear_room_exposes_only_one_pickup_target(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(0, -100), target_room_index=2),)),
            pickups=(Pickup(1, Vec2(20, 0), 0, 0, 1, False, "key", -1, "key"), Pickup(2, Vec2(30, 0), 0, 0, 1, False, "coin", -1, "coin")),
        )
        self.assertEqual(len(candidate_actions(state)), 1)

    def test_ignored_pickup_is_not_reselected(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(0, Vec2(0, -100), target_room_index=2),)),
            ignored_pickup_ids=frozenset({1}),
            pickups=(Pickup(1, Vec2(20, 0), 0, 0, 1, False, "key", -1, "key"),),
            planned_door_slot=0,
        )
        self.assertEqual(candidate_actions(state)[0].action_id, "enter_door_0")

    def test_grid_navigation_uses_a_first_path_step(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(), player_grid_index=0,
            layout=RoomLayout(room_index=1, grid_width=3, grid_height=3, blocked=frozenset({1})),
        )
        step = move_towards(state, Vec2(80, 0), target_grid_index=2)
        self.assertEqual(step, Vec2(0, 1))

    def test_navigation_approaches_a_blocked_door_tile_instead_of_walking_into_it(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(), player_grid_index=12,
            layout=RoomLayout(room_index=1, grid_width=5, grid_height=5, blocked=frozenset({4})),
        )
        step = move_towards(state, Vec2(100, 0), target_grid_index=4)
        self.assertIn(step, (Vec2(1, 0), Vec2(0, -1)))

    def test_door_navigation_action_keeps_the_slot_in_its_id(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(2, Vec2(300, 0), target_room_index=2),)), planned_door_slot=2,
        )
        self.assertEqual(candidate_actions(state)[0].action_id, "enter_door_2")

    def test_exploration_prefers_an_unvisited_door_over_the_room_just_left(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=2, doors=(Door(0, Vec2(-100, 0), target_room_index=1), Door(2, Vec2(100, 0), target_room_index=3))),
            visited_room_indices=frozenset({1, 2}), previous_room_index=1, planned_door_slot=2,
        )
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "enter_door_2")

    def test_floor_planner_exposes_only_its_selected_door(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=2, doors=(Door(0, Vec2(-100, 0), target_room_index=1), Door(2, Vec2(100, 0), target_room_index=3))),
            visited_room_indices=frozenset({1, 2}), previous_room_index=1, planned_door_slot=2,
            planned_goal="unexplored room",
        )
        actions = candidate_actions(state)
        self.assertEqual([action.action_id for action in actions], ["enter_door_2"])

    def test_exploration_backtracks_when_only_exhausted_entry_door_exists(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=1, doors=(Door(2, Vec2(100, 0), target_room_index=2),)),
            visited_room_indices=frozenset({1, 2}), exhausted_room_indices=frozenset({2}), previous_room_index=2,
        )
        self.assertEqual(candidate_actions(state)[0].action_id, "enter_door_2")

    def test_clear_room_uses_known_door_when_planner_slot_is_missing(self):
        state = GameState(
            frame=1, room_clear=True, player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            layout=RoomLayout(room_index=97, doors=(Door(1, Vec2(100, 0), target_room_index=84),)),
            planned_door_slot=-1, planned_goal="no unexplored room is known",
        )
        self.assertEqual(candidate_actions(state)[0].action_id, "enter_door_1")

    def test_repeat_action_penalty_breaks_stationary_combat(self):
        state = make_state()
        previous = Action("hold_and_fire", Vec2(), Vec2(1, 0), mode="combat")
        action = repeat_action_penalty_action(state, previous, PolicyProfile(repeat_action_threshold=2))
        self.assertTrue(action.action_id.startswith("repeat_penalty_"))
        self.assertNotEqual(action.move, Vec2())
        self.assertEqual(action.mode, "combat")

    def test_jev_observation_contains_collision_feedback_and_room_geometry(self):
        state = GameState(
            frame=10, room_clear=False, player=Entity(0, 1, Vec2(40, 40), Vec2(), 6),
            enemies=(), projectiles=(), player_grid_index=4,
            layout=RoomLayout(room_index=2, grid_width=3, grid_height=3, blocked=frozenset({1})),
            requested_move=Vec2(1, 0), resolved_move=Vec2(1, 0), movement_progress=0.0,
            movement_blocked=True, move_resolution_reason="lua_safety_rewrite", last_action_id="enter_door_2",
        )
        observation = state.compact()
        self.assertTrue(observation["navigation_feedback"]["movement_blocked"])
        self.assertEqual(observation["room"]["blocked"], [1])
        self.assertEqual(observation["player"]["grid_index"], 4)
