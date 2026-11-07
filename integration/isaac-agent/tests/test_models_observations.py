import unittest

from isaac_jev.models import DamageEvent, GameState, Vec2


class ObservationModelTests(unittest.TestCase):
    def test_tracking_bomb_retains_motion_and_time_to_collision(self):
        state = GameState.from_message({
            "frame": 7, "room_clear": True, "player": {"hp": 6, "pos": {"x": 0, "y": 0}},
            "danger_effects": [
                {"id": 4, "kind": "ghost_bomb", "type": 4, "variant": 78,
                 "pos": {"x": 100, "y": 0}, "vel": {"x": -5, "y": 0},
                 "radius": 50, "animation": "Ghost"},
                {"id": 5, "kind": "moving_spike", "pos": {"x": 30, "y": 0}},
            ],
        })
        self.assertEqual(len(state.danger_effects), 1)
        self.assertEqual(state.compact()["tracking_threats"][0]["variant"], 78)
        geometry = state.geometry_features()
        self.assertEqual(geometry["nearest_tracking_bomb_distance"], 100.0)
        self.assertEqual(geometry["nearest_tracking_bomb_ttc_frames"], 20.0)
        self.assertTrue(geometry["nearest_tracking_bomb_imminent"])

    def test_moving_spike_entities_are_not_combat_targets_for_old_mod_packets(self):
        state = GameState.from_message(
            {
                "frame": 1,
                "room_clear": False,
                "player": {"hp": 6},
                "enemies": [
                    {"id": 44, "type": 44, "variant": 0, "hp": 0},
                    {"id": 218, "type": 218, "variant": 0, "hp": 0},
                ],
                "layout": {"room_index": 84, "doors": [{"slot": 0, "target_room_index": 83}]},
            }
        )
        self.assertTrue(state.room_clear)
        self.assertEqual(state.enemies, ())
        self.assertEqual(state.hostile_enemy_count, 0)

    def test_stone_shooters_are_not_combat_targets_for_old_mod_packets(self):
        state = GameState.from_message({
            "frame": 19810, "room_clear": False, "player": {"hp": 6},
            "enemies": [
                {"id": 1, "type": 42, "hp": 20, "telegraph": "CloseEyes"},
                {"id": 2, "type": 201, "hp": 1},
                {"id": 3, "type": 202, "hp": 1, "telegraph": "ShootRight"},
            ],
            "layout": {"room_index": 110},
        })
        self.assertTrue(state.room_clear)
        self.assertEqual(state.enemies, ())
        self.assertEqual(state.hostile_enemy_count, 0)
        with_hostile = GameState.from_message({
            "frame": 19811, "room_clear": False, "player": {"hp": 6},
            "enemies": [{"id": 1, "type": 42, "hp": 20},
                        {"id": 4, "type": 19, "hp": 5}],
        })
        self.assertFalse(with_hostile.room_clear)
        self.assertEqual([enemy.kind for enemy in with_hostile.enemies], [19])

    def test_extinguished_fire_is_removed_even_when_hp_is_positive(self):
        state = GameState.from_message({
            "frame": 1, "room_clear": True, "player": {},
            "hazards": [
                {"id": 2, "type": 33, "kind": "fire", "hp": 1,
                 "animation": "Dissapear3", "state": 3},
                {"id": 3, "type": 33, "kind": "fire", "hp": 5,
                 "animation": "Flickering", "state": 8},
            ],
        })
        self.assertEqual([hazard.entity_id for hazard in state.hazards], [3])

    def test_old_fireplace_packet_variant_two_is_blue_fire_bomb_only(self):
        state = GameState.from_message({
            "frame": 1, "room_clear": True, "player": {}, "bombs": 4,
            "hazards": [{"id": 7, "type": 33, "variant": 2, "kind": "fire", "pos": {"x": 20}}],
        })
        self.assertEqual(state.hazards[0].kind, "blue_fire")
        self.assertTrue(state.hazards[0].requires_bomb)

    def test_old_fireplace_packet_variant_three_is_purple_fire_bomb_only(self):
        state = GameState.from_message({
            "frame": 1, "room_clear": True, "player": {}, "bombs": 4,
            "hazards": [{"id": 8, "type": 33, "variant": 3, "kind": "fire", "pos": {"x": 20}}],
        })
        self.assertEqual(state.hazards[0].kind, "purple_fire")
        self.assertTrue(state.hazards[0].requires_bomb)


    def test_experiment_observations_parse_and_compact(self):
        state = GameState.from_message(
            {
                "type": "state",
                "frame": 42,
                "start_seed": 123456,
                "room_clear": False,
                "room_visit_sequence": 3,
                "room_entered_frame": 30,
                "room_cleared_frame": -1,
                "enemy_count": 2,
                "enemy_total_hp": 17.5,
                "enemy_kill_delta": 1,
                "player": {"hp": 6},
                "enemies": [{"id": 1, "type": 10, "hp": 10}, {"id": 2, "type": 11, "hp": 7.5}],
                "projectiles": [],
                "damage_events": [
                    {"id": 9, "frame": 40, "amount": 1.0, "flags": 4, "source_type": 9, "source_variant": 2}
                ],
            }
        )

        self.assertEqual(state.start_seed, 123456)
        self.assertEqual(state.room_visit_sequence, 3)
        self.assertEqual(state.room_entered_frame, 30)
        self.assertEqual(state.enemy_count, 2)
        self.assertEqual(state.enemy_total_hp, 17.5)
        self.assertEqual(state.enemy_kill_delta, 1)
        self.assertEqual(state.damage_events, (DamageEvent(9, 40, 1.0, 4, 9, 2),))

        compact = state.compact()
        self.assertEqual(compact["start_seed"], 123456)
        self.assertEqual(compact["room_visit_sequence"], 3)
        self.assertEqual(compact["enemy_total_hp"], 17.5)
        self.assertEqual(compact["damage_events"][0]["id"], 9)

    def test_damage_event_queue_is_bounded_and_legacy_messages_work(self):
        events = [{"id": i, "frame": i, "amount": 1, "flags": 0} for i in range(40)]
        state = GameState.from_message(
            {"frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [], "damage_events": events}
        )
        self.assertEqual(len(state.damage_events), 32)
        self.assertEqual(state.damage_events[0].event_id, 8)
        self.assertEqual(state.damage_events[-1].event_id, 39)
        self.assertEqual(state.start_seed, 0)
        self.assertEqual(state.enemy_count, 0)

    def test_bomb_placement_diagnostics_are_kept_for_replay(self):
        state = GameState.from_message({
            "frame": 12, "player": {}, "bomb_placed": True,
            "bomb_position": {"x": 100, "y": 280},
            "bomb_placement_distance": 58.4,
            "bomb_escape_direction": {"x": 1, "y": 0},
        })
        self.assertEqual(state.bomb_position, Vec2(100, 280))
        self.assertEqual(state.bomb_escape_direction, Vec2(1, 0))
        self.assertEqual(state.compact()["bomb_placement_distance"], 58.4)

    def test_boss_flag_is_preserved_in_compact_enemy_observation(self):
        state = GameState.from_message({
            "frame": 1, "player": {}, "room_clear": False,
            "enemies": [{"id": 5, "type": 19, "hp": 2, "is_boss": True}],
        })
        self.assertTrue(state.enemies[0].is_boss)
        self.assertTrue(state.compact()["nearby_enemies"][0]["is_boss"])

    def test_entity_grid_index_is_preserved_for_wall_line_of_fire(self):
        state = GameState.from_message({
            "frame": 1, "room_clear": False,
            "player": {"hp": 6, "grid_index": 5}, "player_grid_index": 5,
            "enemies": [{"id": 2, "type": 10, "hp": 4,
                         "pos": {"x": 160, "y": 40}, "grid_index": 9}],
            "layout": {"room_index": 123, "grid_width": 5, "grid_height": 3,
                       "blocked": [7]},
        })
        self.assertEqual(state.player.grid_index, 5)
        self.assertEqual(state.enemies[0].grid_index, 9)
        self.assertTrue(state.geometry_features()["line_of_fire_blocked"])


if __name__ == "__main__":
    unittest.main()
