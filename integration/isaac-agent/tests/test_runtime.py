import unittest
import ast
import inspect
import json
import os
import socket
import tempfile
import urllib.request
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from isaac_jev.models import Action, Door, GameState, Vec2
from isaac_jev.providers import LocalProvider, ProviderConfigStore, parse_provider_config
from isaac_jev import decision, runtime
from isaac_jev.runtime import BridgeRuntime, Controller
from isaac_jev.tuning import PolicyProfile
from isaac_jev.web_dashboard import LocalDashboard, _PAGE


class RuntimeTests(unittest.TestCase):
    def test_boss_wait_uses_first_clear_observation_with_old_mod_state(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 100, "room_clear": True,
            "player": {"pos": {"x": 0, "y": 0}}, "enemies": [], "projectiles": [],
            "boss_exit_available": True, "boss_exit_position": {"x": 100, "y": 0},
            "boss_exit_grid_index": 17,
            "layout": {"room_index": 12, "room_type": "boss", "is_boss": True},
        }
        self.assertEqual(controller.receive_state(message)["id"], "wait_for_boss_reward")
        self.assertEqual(controller.receive_state(message | {"frame": 159})["id"], "wait_for_boss_reward")
        reward = {"id": 91, "pos": {"x": 40, "y": 0}, "is_collectible": True, "name": "boss item"}
        self.assertEqual(controller.receive_state(message | {"frame": 160, "pickups": [reward]})["id"], "take_item_91")
        self.assertEqual(controller.receive_state(message | {"frame": 163})["id"], "enter_boss_exit_17")

    def test_new_room_reward_interrupts_cached_door_action(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 10, "room_clear": True,
            "player": {"pos": {"x": 0, "y": 0}}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 20, "doors": [
                {"slot": 2, "pos": {"x": 100, "y": 0}, "target_room_index": 21}]},
        }
        self.assertEqual(controller.receive_state(message)["id"], "enter_door_2")
        pickup = {"id": 77, "pos": {"x": 30, "y": 0}, "kind": "key", "name": "key"}
        self.assertEqual(controller.receive_state(message | {"frame": 13, "pickups": [pickup]})["id"], "take_pickup_77")

    def test_late_door_decision_cannot_override_new_room_reward(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 10, "room_clear": True,
            "player": {"pos": {"x": 0, "y": 0}}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 20, "doors": [
                {"slot": 2, "pos": {"x": 100, "y": 0}, "target_room_index": 21}]},
        }
        controller.receive_state(message)
        delayed = Future()
        delayed.set_result(Action("enter_door_2", Vec2(1, 0), Vec2(), mode="navigate", source="jev"))
        controller._future = delayed
        controller._future_started_frame = 10
        controller._future_provider_generation = controller._provider_generation
        pickup = {"id": 77, "pos": {"x": 30, "y": 0}, "kind": "key", "name": "key"}
        response = controller.receive_state(message | {"frame": 13, "pickups": [pickup]})
        self.assertEqual(response["id"], "take_pickup_77")
        self.assertIn("superseded exit", controller._last_stale_decision_reason)

    def test_tracking_bomb_interrupts_stale_combat_and_rejects_late_result(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": False,
            "player": {"hp": 6, "pos": {"x": 0, "y": 0}},
            "enemies": [{"id": 1, "type": 10, "hp": 5, "pos": {"x": 150, "y": 0}}],
            "projectiles": [], "layout": {"room_index": 7},
        }
        controller.receive_state(message)
        controller._latest_action = Action("hold_and_fire", Vec2(), Vec2(1, 0), mode="combat", source="jev")
        threatened = message | {
            "frame": 4,
            "danger_effects": [{"id": 4, "kind": "ghost_bomb", "type": 4,
                                "pos": {"x": 100, "y": 0}, "vel": {"x": -4, "y": 0}, "radius": 40}],
        }
        response = controller.receive_state(threatened)
        self.assertEqual(response["mode"], "evade")
        self.assertEqual(response["shoot"], {"x": 0.0, "y": 0.0})
        delayed = Future()
        delayed.set_result(Action("hold_and_fire", Vec2(), Vec2(1, 0), mode="combat", source="jev"))
        controller._future = delayed
        controller._future_started_frame = 4
        controller._future_provider_generation = controller._provider_generation
        response = controller.receive_state(threatened | {"frame": 7})
        self.assertEqual(response["mode"], "evade")
        self.assertEqual(controller.receive_state(message | {"frame": 10})["mode"], "combat")

    def test_combat_action_stops_when_only_moving_traps_remain(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        message = {"type": "state", "frame": 30, "room_clear": True,
                   "player": {"pos": {"x": 500, "y": 280}}, "enemies": [], "projectiles": [],
                   "danger_effects": [{"id": 10, "kind": "moving_spike", "pos": {"x": 320, "y": 280}, "radius": 45}],
                   "layout": {"room_index": 83, "doors": [
                       {"slot": 2, "pos": {"x": 600, "y": 280}, "target_room_index": 84}]} }
        controller.receive_state(message)
        controller._latest_action = Action("hold_and_fire", Vec2(), Vec2(-1, 0), mode="combat", source="jev")
        self.assertEqual(controller.receive_state(message | {"frame": 33})["id"], "enter_door_2")

        delayed = Future()
        delayed.set_result(Action("hold_and_fire", Vec2(), Vec2(-1, 0), mode="combat", source="jev"))
        controller._future = delayed
        controller._future_started_frame = 33
        controller._future_provider_generation = controller._provider_generation
        response = controller.receive_state(message | {"frame": 36})
        self.assertEqual(response["id"], "enter_door_2")
        self.assertEqual(response["shoot"], {"x": 0.0, "y": 0.0})

    def test_tnt_without_progress_is_ignored_so_exit_can_be_used(self):
        controller = Controller(autopilot_enabled=False, policy_profile=PolicyProfile(pickup_stuck_frames=30))
        self.addCleanup(controller.shutdown)
        message = {"type": "state", "frame": 1, "room_clear": True,
                   "player": {"pos": {"x": 500, "y": 160}, "tear_range": 260, "hp": 6},
                   "enemies": [], "projectiles": [], "pickups": [],
                   "layout": {"room_index": 82, "grid_width": 15, "grid_height": 9,
                              "grid_events": [{"kind": "tnt", "id": -100017, "grid_index": 17,
                                               "pos": {"x": 120, "y": 160}, "active": True}],
                              "doors": [{"slot": 2, "pos": {"x": 600, "y": 280}, "target_room_index": 83}]}}
        self.assertEqual(controller.receive_state(message)["id"], "shoot_tnt_-100017")
        controller.receive_state(message | {"frame": 2})
        response = controller.receive_state(message | {"frame": 32})
        self.assertEqual(response["id"], "enter_door_2")
        self.assertIn(-100017, response["ignored_hazard_ids"])

    def test_explored_room_routes_to_known_boss_instead_of_waiting(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller._current_room_index = 84
        controller._previous_room_index = 85
        controller._visited_rooms = {71, 84, 85}
        controller._room_graph = {
            84: (Door(1, Vec2(320, 120), target_room_index=71, target_room_type="boss"),
                 Door(2, Vec2(600, 280), target_room_index=85, target_room_type="treasure")),
        }
        controller._room_intel = {71: {"room_type": "boss"}}
        state = GameState.from_message({"frame": 36571, "room_clear": True, "player": {"hp": 6},
                                        "layout": {"room_index": 84}})
        self.assertEqual(controller._plan_next_door(state), (1, "return to known boss exit"))

    def test_new_treasure_priority_overrides_committed_default_door(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 1, "doors": [
                {"slot": 0, "pos": {"x": 100}, "target_room_index": 2, "target_room_type": "treasure"},
                {"slot": 1, "pos": {"y": -100}, "target_room_index": 3, "target_room_type": "default"},
            ]},
        }
        controller.receive_state(message)
        chosen = Future()
        chosen.set_result(Action("enter_door_1", Vec2(0, -1), Vec2(), source="bocha", mode="navigate"))
        controller._future = chosen
        controller._future_started_frame = 1
        controller._future_provider_generation = controller._provider_generation
        response = controller.receive_state(message | {"frame": 4})
        self.assertEqual(response["id"], "enter_door_1")
        controller.receive_state(message | {"frame": 7})
        self.assertEqual(controller.status()["latest_state"]["planned_goal"], "known treasure room")
        controller._unreachable_door_edges.add((1, 1, 3))
        self.assertEqual(controller._plan_next_door()[0], 0)

    def test_newly_bombed_secret_door_preempts_default_and_stale_navigation(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 15877, "room_clear": True, "player": {"pos": {"x": 180, "y": 280}},
            "enemies": [], "projectiles": [], "pickups": [], "hazards": [],
            "layout": {"room_index": 71, "doors": [
                {"slot": 0, "pos": {"x": 40, "y": 280}, "target_room_index": 70,
                 "target_room_type": "secret", "door_open": False, "door_open_known": True,
                 "door_locked": False, "door_lock_known": True},
                {"slot": 1, "pos": {"x": 320, "y": 120}, "target_room_index": 58,
                 "target_room_type": "default", "door_open": True, "door_open_known": True},
                {"slot": 2, "pos": {"x": 600, "y": 280}, "target_room_index": 72,
                 "target_room_type": "default", "door_open": True, "door_open_known": True},
            ]},
        }
        controller.receive_state(message)
        controller._latest_action = Action("enter_door_2", Vec2(1, 0), Vec2(), mode="navigate")
        controller._committed_door_slot, controller._committed_door_room = 2, 71
        opened = message | {"frame": 15880, "bomb_placed": True, "bomb_target_id": -200000,
                            "layout": message["layout"] | {"doors": [message["layout"]["doors"][0] | {"door_open": True},
                                                                    *message["layout"]["doors"][1:]]}}
        response = controller.receive_state(opened)
        self.assertEqual(response["id"], "enter_door_0")
        self.assertEqual(controller.status()["latest_state"]["planned_goal"], "newly bombed secret room")
        self.assertEqual([action.action_id for action in decision.build_candidate_set(controller._latest_state).admissible_candidates], ["enter_door_0"])
        self.assertEqual((controller._committed_door_slot, controller._committed_door_room), (-1, -1))

        delayed = Future()
        delayed.set_result(Action("enter_door_2", Vec2(1, 0), Vec2(), mode="navigate", source="bocha"))
        controller._future = delayed
        controller._future_started_frame = 15880
        controller._future_provider_generation = controller._provider_generation
        self.assertEqual(controller.receive_state(opened | {"frame": 15883})["id"], "enter_door_0")
        self.assertEqual(controller._last_stale_decision_reason,
                         "newly opened secret entrance superseded earlier navigation")

        # A merely suspected or still locked wall cannot receive this priority.
        closed = replace(controller._latest_state, layout=replace(controller._latest_state.layout,
                         doors=(replace(controller._latest_state.layout.doors[0], open=False),
                                *controller._latest_state.layout.doors[1:])))
        controller._room_graph[71] = closed.layout.doors
        self.assertNotEqual(controller._plan_next_door(closed)[0], 0)
        locked = replace(controller._latest_state, layout=replace(controller._latest_state.layout,
                         doors=(replace(controller._latest_state.layout.doors[0], locked=True),
                                *controller._latest_state.layout.doors[1:])))
        controller._room_graph[71] = locked.layout.doors
        self.assertNotEqual(controller._plan_next_door(locked)[0], 0)

    def test_locked_treasure_uses_key_or_backtracks_without_one(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller._current_room_index = 86
        controller._previous_room_index = 85
        controller._visited_rooms = {85, 86}
        controller._room_graph[86] = (
            Door(0, Vec2(40, 280), target_room_index=85, target_room_type="default"),
            Door(1, Vec2(320, 120), target_room_index=73, target_room_type="shop",
                 locked=True, lock_known=True, open=False, open_known=True),
            Door(2, Vec2(600, 280), target_room_index=87, target_room_type="treasure",
                 locked=True, lock_known=True, open=False, open_known=True),
        )
        state = GameState.from_message({"frame": 1, "room_clear": True,
                                        "layout": {"room_index": 86}, "player": {}, "keys": 1})
        self.assertEqual(controller._plan_next_door(state), (2, "known treasure room"))
        controller._committed_door_room, controller._committed_door_slot = 86, 0
        self.assertEqual(controller._plan_next_door(state), (2, "known treasure room"))
        self.assertEqual(controller._plan_next_door(replace(state, keys=0))[0], 0)

    def test_room_86_key_door_choice_reaches_action_response(self):
        def selected_door(keys):
            controller = Controller(autopilot_enabled=False)
            self.addCleanup(controller.shutdown)
            controller.receive_state({
                "type": "state", "frame": 1, "room_clear": True, "player": {},
                "layout": {"room_index": 85, "doors": [
                    {"slot": 2, "pos": {"x": 600, "y": 280}, "target_room_index": 86}]},
            })
            response = controller.receive_state({
                "type": "state", "frame": 4, "room_clear": True, "keys": keys,
                "player": {"pos": {"x": 150, "y": 290}},
                "layout": {"room_index": 86, "doors": [
                    {"slot": 0, "pos": {"x": 40, "y": 280}, "target_room_index": 85,
                     "target_room_type": "default", "door_open": True, "door_open_known": True},
                    {"slot": 1, "pos": {"x": 320, "y": 120}, "target_room_index": 73,
                     "target_room_type": "shop", "door_locked": True, "door_lock_known": True,
                     "door_open": False, "door_open_known": True},
                    {"slot": 2, "pos": {"x": 600, "y": 280}, "target_room_index": 87,
                     "target_room_type": "treasure", "door_locked": True, "door_lock_known": True,
                     "door_open": False, "door_open_known": True}]},
            })
            return response["id"]

        self.assertEqual(selected_door(1), "enter_door_2")
        self.assertEqual(selected_door(0), "enter_door_0")

    def test_navigation_oscillation_counts_as_stall_despite_movement(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller._effective_action = Action("enter_door_0", Vec2(-1, 0), Vec2(), mode="navigate")
        door = Door(0, Vec2(40, 280), target_room_index=85)
        base = GameState.from_message({"frame": 1, "room_clear": True,
                                       "player": {"pos": {"x": 150, "y": 280}},
                                       "layout": {"room_index": 86, "doors": [
                                           {"slot": 0, "pos": {"x": 40, "y": 280}, "target_room_index": 85}]}})
        for frame, y in ((1, 280), (16, 230), (31, 330), (61, 280)):
            state = replace(base, frame=frame, player=replace(base.player, position=Vec2(150, y)),
                            layout=replace(base.layout, doors=(door,)), last_action_id="enter_door_0")
            controller._update_navigation_stall(state)
            controller._record_action_feedback(state)
        self.assertEqual(controller._stall_since_frame, 1)
        self.assertGreaterEqual(len(controller._recent_action_feedback), 3)
        self.assertTrue(any(item["goal_progress_px"] < 0 for item in controller._recent_action_feedback
                            if item["goal_progress_px"] is not None))

    def test_recovery_can_move_toward_safe_entry_door_lane(self):
        state = GameState.from_message({
            "frame": 61, "room_clear": True, "player": {"pos": {"x": 150, "y": 280}},
            "player_grid_index": 63, "recovery_active": True, "recovery_target_door_slot": 0,
            "safe_move_directions": {"left": "safe", "up": "safe", "down": "safe"},
            "layout": {"room_index": 86, "grid_width": 15, "grid_height": 9,
                       "doors": [{"slot": 0, "pos": {"x": 40, "y": 280}, "target_room_index": 85}]},
        })
        self.assertIn("recover_left", [item.action_id for item in decision.recovery_actions(state)])

    def test_bocha_does_not_requery_each_entered_state_frame(self):
        controller = Controller(autopilot_enabled=True)
        self.addCleanup(controller.shutdown)
        config = parse_provider_config({"selected_provider": "bocha"}, environ={})
        controller._pending_provider_config = config
        message = {"type": "state", "frame": 1, "room_clear": True, "player": {}, "layout": {"room_index": 1}, "transition_phase": "entered"}
        with patch.object(controller._executor, "submit", side_effect=lambda *_args: Future()) as submit:
            controller.receive_state(message)
            self.assertEqual(submit.call_count, 1)
            controller._future = None
            controller.receive_state(message | {"frame": 4})
            self.assertEqual(submit.call_count, 1)
            controller.receive_state(message | {"frame": 31})
            self.assertEqual(submit.call_count, 2)

    def test_lua_resolved_movement_counts_stall_when_python_move_is_zero(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller._effective_action = Action("enter_door_0", Vec2(), Vec2(), mode="navigate")
        state = GameState.from_message({"frame": 10, "player": {}, "resolved_move": {"x": -1}, "movement_progress": 0, "movement_blocked": True})
        controller._update_movement_feedback(state)
        self.assertEqual(controller._movement_stall_count, 1)

    def test_floor_boundary_clears_old_room_graph_and_failures(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        for stage in (1, 2):
            controller.receive_state({"frame": stage * 10, "stage": stage, "start_seed": 42, "player": {}, "layout": {"room_index": 12}})
            if stage == 1:
                controller._visited_rooms.add(99)
                controller._unreachable_door_edges.add((12, 0, 99))
                controller._room_failures[99] = ({5}, {6})
        self.assertEqual(controller._visited_rooms, {12})
        self.assertFalse(controller._unreachable_door_edges)
        self.assertFalse(controller._room_failures)

    def test_routes_through_exhausted_transit_room_to_safe_frontier(self):
        from isaac_jev.models import Door
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller._current_room_index = 1
        controller._previous_room_index = 0
        controller._visited_rooms = {0, 1, 2, 3}
        controller._exhausted_rooms = {0, 1, 2}
        controller._room_graph = {
            0: (Door(0, Vec2(), 1),),
            1: (Door(0, Vec2(), 0), Door(1, Vec2(), 2)),
            2: (Door(0, Vec2(), 1), Door(1, Vec2(), 3)),
            3: (Door(0, Vec2(), 2), Door(1, Vec2(), 4)),
        }
        self.assertEqual(controller._plan_next_door(), (1, "route to unexplored branch"))

    def test_pickup_timeout_survives_waiting_for_remote_model(self):
        controller = Controller(autopilot_enabled=False, policy_profile=PolicyProfile(pickup_stuck_frames=30))
        self.addCleanup(controller.shutdown)
        message = {"frame": 1, "player": {}, "pickups": [{"id": 77, "pos": {"x": 200}, "is_collectible": True}]}
        action = Action("take_item_77", Vec2(1, 0), Vec2(), mode="item")
        controller._effective_action = action
        controller._update_pickup_progress(GameState.from_message(message))
        controller._effective_action = Action("await_model", Vec2(), Vec2(), mode="wait")
        controller._update_pickup_progress(GameState.from_message(message | {"frame": 20}))
        controller._effective_action = action
        controller._update_pickup_progress(GameState.from_message(message | {"frame": 32}))
        self.assertIn(77, controller._ignored_pickup_ids)

    def test_hazard_damage_counts_as_progress_without_approaching_fire(self):
        controller = Controller(autopilot_enabled=False, policy_profile=PolicyProfile(pickup_stuck_frames=30))
        self.addCleanup(controller.shutdown)
        controller._effective_action = Action("clear_hazard_9", Vec2(), Vec2(1, 0), mode="hazard")
        for frame, hp in ((1, 20), (25, 10), (45, 5)):
            controller._update_hazard_progress(GameState.from_message({"frame": frame, "player": {}, "hazards": [{"id": 9, "hp": hp, "pos": {"x": 200}}]}))
        self.assertNotIn(9, controller._ignored_hazard_ids)

    def test_room_failure_is_remembered_until_geometry_changes(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        def visit(frame, room, blocked=()):
            controller.receive_state({"frame": frame, "player": {}, "layout": {"room_index": room, "blocked": list(blocked)}})
        visit(1, 1, (5,))
        controller._ignored_pickup_ids.add(77)
        visit(2, 2)
        visit(3, 1, (5,))
        self.assertIn(77, controller._ignored_pickup_ids)
        visit(4, 1, ())
        self.assertNotIn(77, controller._ignored_pickup_ids)

    def test_manual_mode_never_enables_lua_input(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        message = controller.receive_state({"type": "state", "frame": 1, "room_clear": False, "player": {}, "enemies": [], "projectiles": []})
        self.assertFalse(message["enabled"])

    def test_disabling_autopilot_clears_action(self):
        controller = Controller(autopilot_enabled=True)
        self.addCleanup(controller.shutdown)
        controller._latest_action = Action("hold_and_fire", Vec2(), Vec2(1, 0))
        status = controller.set_autopilot(False)
        self.assertFalse(status["autopilot_enabled"])
        self.assertIsNone(status["latest_action"])

    def test_tcp_bridge_returns_a_safe_manual_action(self):
        runtime = BridgeRuntime(port=0, autopilot=False)
        runtime.start()
        self.addCleanup(runtime.stop)
        connection = socket.create_connection(runtime.address, timeout=2)
        self.addCleanup(connection.close)
        connection.sendall(b'{"type":"state","frame":1,"room_clear":false,"player":{},"enemies":[],"projectiles":[]}\n')
        response = json.loads(connection.makefile("rb").readline())
        self.assertEqual(response["type"], "action")
        self.assertFalse(response["enabled"])

    def test_local_dashboard_exposes_current_status(self):
        controller = Controller(autopilot_enabled=True)
        self.addCleanup(controller.shutdown)
        dashboard = LocalDashboard(controller, port=0)
        dashboard.start()
        self.addCleanup(dashboard.stop)
        with urllib.request.urlopen(f"{dashboard.url}api/status", timeout=2) as response:
            status = json.loads(response.read().decode("utf-8"))
        self.assertTrue(status["autopilot_enabled"])
        self.assertEqual(status["controller_version"], "2026-09-24-v19")
        self.assertEqual(status["mod_version"], "not_connected")

    def test_dashboard_javascript_keeps_newline_escapes_valid(self):
        self.assertIn("?'\\nLua", _PAGE)
        self.assertNotIn("?'\nLua", _PAGE)
        self.assertNotIn("?'\n错误", _PAGE)
        self.assertIn("决策信息", _PAGE)
        self.assertIn("Debug 日志", _PAGE)
        self.assertIn("debug_logs", _PAGE)
        self.assertIn("fallback_reason", _PAGE)
        self.assertIn("judgments", _PAGE)
        self.assertIn("x.error", _PAGE)
        self.assertIn("系统运行规则（源代码）", _PAGE)
        self.assertIn("rule-sections", _PAGE)
        self.assertIn("fire_block_reason", _PAGE)
        self.assertIn("pill_use_result", _PAGE)
        self.assertIn("trinket_swap_result", _PAGE)
        self.assertIn("controller_version", _PAGE)
        self.assertIn("mod_version", _PAGE)

    def test_provider_config_update_keeps_independent_keys_when_key_field_is_blank(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        with tempfile.TemporaryDirectory() as directory:
            store = ProviderConfigStore(Path(directory) / "decision_provider.json", environ={})
            config = parse_provider_config({
                "providers": {
                    "jev": {"api_key": "official-secret", "model": "jev-latest"},
                    "bocha": {"api_key": "bocha-secret", "model": "bocha-jev-v1"},
                },
            }, environ={})
            store.save(config)
            controller._provider_store = store
            controller._provider_config = config
            controller._pending_provider_config = config
            controller.update_provider_config({
                "selected_provider": "jev",
                "providers": {"jev": {"model": "jev-custom"}},
            })
            loaded = store.load()
            self.assertEqual(loaded.providers["jev"].model, "jev-custom")
            self.assertEqual(loaded.providers["jev"].api_key, "official-secret")
            self.assertEqual(loaded.providers["bocha"].api_key, "bocha-secret")

    def test_provider_model_switch_is_immediate_and_invalidates_inflight_generation(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        before = controller._provider_generation
        with tempfile.TemporaryDirectory() as directory:
            store = ProviderConfigStore(Path(directory) / "decision_provider.json", environ={})
            config = parse_provider_config({}, environ={})
            store.save(config)
            controller._provider_store = store
            controller._provider_config = config
            controller._pending_provider_config = config
            result = controller.update_provider_config({
                "selected_provider": "jev",
                "providers": {"jev": {"model": "jev-live-switch"}},
            })
            self.assertEqual(result["active_provider"], "jev")
            self.assertEqual(result["active_model"], "jev-live-switch")
            self.assertGreater(controller._provider_generation, before)

    def test_decision_debug_trace_contains_input_output_latency_and_role_action(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        state = GameState.from_message({
            "type": "state", "frame": 7, "room_clear": True,
            "player": {}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 3, "doors": []},
        })
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            controller._decide(state)
        trace = controller.status()["debug_logs"][0]
        self.assertEqual(trace["frame"], 7)
        self.assertEqual(trace["room_index"], 3)
        self.assertIn("input", trace)
        self.assertIn("output", trace)
        self.assertIn("latency_ms", trace)
        self.assertIn("role_action", trace)

    def test_status_exposes_source_owned_decision_rules(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        rules = controller.status()["decision_rules"]
        self.assertGreaterEqual(len(rules["sections"]), 5)
        self.assertIn("combat", {section["id"] for section in rules["sections"]})
        self.assertIn("hold_and_fire", {action["id"] for action in rules["actions"]})
        self.assertIn("candidate_actions", rules["source_revisions"])

    def test_boss_pickup_stall_window_is_at_least_240_frames(self):
        controller = Controller(autopilot_enabled=False, policy_profile=PolicyProfile(pickup_stuck_frames=90))
        self.addCleanup(controller.shutdown)
        boss = GameState.from_message({
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 12, "room_type": "boss", "is_boss": True},
        })
        normal = GameState.from_message({
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 1, "room_type": "default"},
        })
        self.assertGreaterEqual(controller._blocked_target_limit_frames(boss), 240)
        self.assertLess(controller._blocked_target_limit_frames(normal), 240)

    def test_action_catalog_covers_source_action_ids(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        catalog = {item["id"] for item in controller.status()["decision_rules"]["actions"]}
        source_ids = set()
        for module in (decision, runtime):
            for node in ast.walk(ast.parse(inspect.getsource(module))):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "Action" or not node.args:
                    continue
                value = node.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    source_ids.add(value.value)
                elif isinstance(value, ast.JoinedStr) and isinstance(value.values[0], ast.Constant):
                    source_ids.add(value.values[0].value + "<id>")
        source_ids.discard("enter_door_<id>")
        source_ids.add("enter_door_<slot>")
        source_ids.discard("bomb_<id>")
        source_ids.update({"bomb_secret_<slot>", "bomb_super_secret_<slot>"})
        self.assertFalse(source_ids - catalog, f"未在网页动作目录列出的源码动作: {source_ids - catalog}")

    def test_controller_backtracks_from_an_exhausted_dead_end(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)

        def state(room_index, slot, target_room_index):
            return {
                "type": "state", "frame": room_index, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
                "layout": {"room_index": room_index, "doors": [{"slot": slot, "pos": {}, "target_room_index": target_room_index}]},
            }

        controller.receive_state(state(1, 2, 2))
        controller.receive_state(state(2, 0, 1))
        final_action = controller.receive_state(state(1, 2, 2))
        self.assertEqual(final_action["id"], "enter_door_2")
        self.assertEqual(final_action["target_room_index"], 2)

    def test_door_response_uses_executed_slot_target_from_live_layout(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller._current_room_index = 85
        controller._planned_door_slot = 3
        controller._room_graph = {
            85: (Door(1, Vec2(), 98), Door(3, Vec2(), 98)),
        }
        response = controller.receive_state({
            "type": "state", "frame": 1, "room_clear": True,
            "player": {}, "enemies": [], "projectiles": [],
            "layout": {
                "room_index": 85,
                "doors": [
                    {"slot": 1, "pos": {}, "target_room_index": 72, "target_room_type": "treasure"},
                    {"slot": 3, "pos": {}, "target_room_index": 98, "target_room_type": "secret", "door_open": False, "door_open_known": True},
                ],
            },
        })
        self.assertEqual(response["id"], "enter_door_1")
        self.assertEqual(response["door_slot"], 1)
        self.assertEqual(response["target_room_index"], 72)

    def test_controller_routes_to_the_only_unexplored_branch(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)

        frame = 0
        def state(room_index, doors):
            nonlocal frame
            frame += 1
            return {
                "type": "state", "frame": frame, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
                "layout": {"room_index": room_index, "doors": doors},
            }

        controller.receive_state(state(1, [
            {"slot": 2, "pos": {}, "target_room_index": 2},
            {"slot": 3, "pos": {}, "target_room_index": 3},
        ]))
        controller.receive_state(state(2, [{"slot": 0, "pos": {}, "target_room_index": 1}]))
        action = controller.receive_state(state(1, [
            {"slot": 2, "pos": {}, "target_room_index": 2},
            {"slot": 3, "pos": {}, "target_room_index": 3},
        ]))
        self.assertEqual(action["id"], "enter_door_3")

    def test_blocked_door_edge_is_abandoned_and_next_exit_is_selected(self):
        controller = Controller(
            autopilot_enabled=False,
            policy_profile=PolicyProfile(movement_stall_threshold=2),
        )
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": True,
            "player": {"pos": {"x": 70, "y": 280}}, "enemies": [], "projectiles": [],
            "requested_move": {"x": -1, "y": 0}, "resolved_move": {"x": 0, "y": 0},
            "movement_progress": 0, "movement_blocked": True, "move_resolution_reason": "native_input_blocked",
            "transition_door_distance": 30,
            "layout": {"room_index": 12, "doors": [
                {"slot": 0, "pos": {"x": 40, "y": 280}, "target_room_index": 13, "target_room_type": "default"},
                {"slot": 1, "pos": {"x": 320, "y": 120}, "target_room_index": 14, "target_room_type": "default"},
            ]},
        }
        controller.receive_state(message)
        message["frame"] = 2
        controller.receive_state(message)
        message["frame"] = 3
        response = controller.receive_state(message)
        self.assertEqual(response["id"], "enter_door_1")
        self.assertIn("door:12:0->13", response["unreachable_targets"])
        self.assertTrue(controller.status()["door_retry_cooldowns"])
        clear_feedback = message | {"frame": 94, "movement_blocked": False,
                                    "movement_progress": 20, "resolved_move": {"x": 1, "y": 0},
                                    "move_resolution_reason": "requested"}
        controller.receive_state(clear_feedback)
        self.assertNotIn("door:12:0->13", controller.status()["unreachable_targets"])
        self.assertFalse(controller.status()["door_retry_cooldowns"])

    def test_room_87_alignment_rewrite_never_permanently_blacklists_only_exit(self):
        controller = Controller(autopilot_enabled=False, policy_profile=PolicyProfile(movement_stall_threshold=6))
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 4714, "room_clear": True,
            "player": {"pos": {"x": 69.9, "y": 256.5}, "hp": 5},
            "player_grid_index": 46,
            "enemies": [], "projectiles": [], "pickups": [],
            "layout": {"room_index": 87, "room_type": "treasure", "grid_width": 15, "grid_height": 9,
                       "blocked": [*range(15), 15, 29, 30, 44, 45, 59, 60, 74, 75, 89, 90,
                                   104, 105, 119, *range(120, 135)], "doors": [
                {"slot": 0, "pos": {"x": 40, "y": 280}, "grid_index": 60, "target_room_index": 86,
                 "target_room_type": "default", "door_open": True, "door_open_known": True,
                 "door_locked": False, "door_lock_known": True},
            ]},
            "safe_move_directions": {"up": "safe", "down": "grid_wall", "left": "safe", "right": "safe"},
            "requested_move": {"x": 0, "y": 1}, "resolved_move": {"x": -1, "y": 0},
            "movement_progress": 0, "movement_blocked": True,
            "move_resolution_reason": "lua_safety_rewrite", "transition_gate": "native_input_blocked",
            "transition_door_distance": 38,
        }
        controller.receive_state(message)
        for frame in range(4717, 4733, 3):
            response = controller.receive_state(message | {"frame": frame})
            self.assertNotEqual(response["id"], "wait_for_safety_filter")
        self.assertNotIn("door:87:0->86", controller.status()["unreachable_targets"])
        self.assertEqual(controller._plan_next_door(controller._latest_state)[0], 0)
        for frame in range(4735, 4790, 3):
            response = controller.receive_state(message | {"frame": frame})
        state = controller._latest_state
        self.assertTrue(state.recovery_active)
        candidates = decision.build_candidate_set(state)
        self.assertGreaterEqual(len(candidates.admissible_candidates), 2)
        self.assertTrue(all(item.mode == "recovery" for item in candidates.admissible_candidates))
        self.assertTrue(response["id"].startswith("recover_"))

    def test_recovery_jev_choice_is_rate_limited_and_preserves_real_waypoints(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller._active_provider_name = "jev"
        state = GameState.from_message({
            "frame": 100, "room_clear": True, "player": {"pos": {"x": 70, "y": 256}, "hp": 5},
            "layout": {"room_index": 87, "doors": [{"slot": 0, "pos": {"x": 40, "y": 280},
                        "target_room_index": 86, "door_open": True, "door_open_known": True}]},
            "safe_move_directions": {"up": "safe", "down": "grid_wall", "left": "grid_wall", "right": "safe"},
            "recovery_active": True, "recovery_reason": "confirmed stall",
            "recovery_target_door_slot": 0, "stall_frames": 60,
        })
        calls = []

        class Remote:
            def choose(self, game_state, candidates):
                calls.append(game_state.frame)
                local = LocalProvider().choose(game_state, candidates)
                selected = candidates.admissible_candidates[-1]
                return replace(local, provider="jev", model="test-jev", action=replace(selected, source="jev"),
                               selected_choice=selected.action_id, request_bytes=128, status="success")

        remote = Remote()
        with patch.object(runtime, "create_provider", side_effect=lambda name, *_args: LocalProvider() if name == "local" else remote):
            first = controller._decide(state)
            second = controller._decide(replace(state, frame=118))
        self.assertEqual(len(calls), 1)
        self.assertEqual(first.source, "jev")
        self.assertIsNotNone(first.waypoint)
        self.assertEqual(second.source, "local")
        logs = controller.status()["debug_logs"]
        self.assertEqual(logs[0]["fallback_reason"], "recovery_remote_cooldown")
        self.assertFalse(logs[0]["remote_call"])
        self.assertTrue(logs[1]["remote_call"])
        self.assertEqual(len({item["id"] for item in logs[1]["candidate_set"]["admissible_candidates"]}), 2)

    def test_recovery_never_opens_locked_door_or_interrupts_bomb_retreat(self):
        base = {"frame": 100, "room_clear": True, "player": {"pos": {"x": 70, "y": 256}},
                "recovery_active": True, "recovery_target_door_slot": 0,
                "safe_move_directions": {"up": "safe", "right": "safe"},
                "layout": {"room_index": 87, "doors": [{"slot": 0, "pos": {"x": 40, "y": 280},
                            "target_room_index": 86, "door_open": False, "door_open_known": True,
                            "door_locked": True, "door_lock_known": True}]}}
        locked = decision.build_candidate_set(GameState.from_message(base))
        self.assertFalse(any(item.mode == "recovery" for item in locked.admissible_candidates))
        bomb = decision.build_candidate_set(GameState.from_message(base | {"bomb_active": True}))
        self.assertEqual(bomb.admissible_candidates[0].action_id, "wait_for_bomb")

    def test_recovery_remote_timeout_keeps_safe_local_waypoint(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller._active_provider_name = "jev"
        state = GameState.from_message({
            "frame": 100, "room_clear": True, "player": {"pos": {"x": 70, "y": 256}},
            "layout": {"room_index": 87, "doors": [{"slot": 0, "pos": {"x": 40, "y": 280},
                        "target_room_index": 86, "door_open": True, "door_open_known": True}]},
            "safe_move_directions": {"up": "safe", "right": "safe"},
            "recovery_active": True, "recovery_target_door_slot": 0,
        })

        class TimedOut:
            def choose(self, game_state, candidates):
                local = LocalProvider().choose(game_state, candidates)
                return replace(local, provider="jev", model="test-jev", status="fallback",
                               fallback=True, fallback_reason="timeout", timed_out=True,
                               request_bytes=128)

        with patch.object(runtime, "create_provider", return_value=TimedOut()):
            action = controller._decide(state)
        self.assertIsNotNone(decision.conservative_action(state).waypoint)
        self.assertEqual(action.source, "local")
        self.assertEqual(action.mode, "recovery")
        self.assertIsNotNone(action.waypoint)
        self.assertEqual(controller.status()["debug_logs"][0]["fallback_reason"], "timeout")

    def test_room_with_unexplored_branch_does_not_plan_back_to_previous_room(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller.receive_state({
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 81, "room_type": "shop", "doors": [{"slot": 2, "pos": {}, "target_room_index": 82}]},
        })
        controller.receive_state({
            "type": "state", "frame": 2, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 82, "doors": [
                {"slot": 0, "pos": {}, "target_room_index": 81, "target_room_type": "shop"},
                {"slot": 2, "pos": {}, "target_room_index": 83, "target_room_type": "default"},
            ]},
        })
        action = controller.receive_state({
            "type": "state", "frame": 3, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 82, "doors": [
                {"slot": 0, "pos": {}, "target_room_index": 81, "target_room_type": "shop"},
                {"slot": 2, "pos": {}, "target_room_index": 83, "target_room_type": "default"},
            ]},
        })
        self.assertEqual(action["id"], "enter_door_2")
        self.assertEqual(action["target_room_index"], 83)

    def test_controller_prefers_treasure_over_sacrifice_room(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        response = controller.receive_state({
            "type": "state", "frame": 1, "room_clear": True, "player": {"red_hearts": 3, "max_hearts": 6}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 1, "doors": [
                {"slot": 0, "pos": {}, "target_room_index": 2, "target_room_type": "sacrifice"},
                {"slot": 1, "pos": {}, "target_room_index": 3, "target_room_type": "treasure"},
            ]},
        })
        self.assertEqual(response["id"], "enter_door_1")

    def test_controller_prefers_treasure_over_boss_room(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        response = controller.receive_state({
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 1, "doors": [
                {"slot": 0, "pos": {}, "target_room_index": 2, "target_is_boss": True, "target_room_type": "boss"},
                {"slot": 1, "pos": {}, "target_room_index": 3, "target_room_type": "treasure"},
            ]},
        })
        self.assertEqual(response["id"], "enter_door_1")
        self.assertEqual(controller.status()["latest_state"]["planned_goal"], "known treasure room")

    def test_controller_does_not_probe_unknown_hidden_door_when_treasure_is_available(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        response = controller.receive_state({
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 1, "doors": [
                {"slot": 0, "pos": {}, "target_room_index": 2, "target_room_type": "secret"},
                {"slot": 1, "pos": {}, "target_room_index": 3, "target_room_type": "treasure"},
            ]},
        })
        self.assertEqual(response["id"], "enter_door_1")

    def test_shop_item_is_marked_as_shop_action_when_affordable(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        response = controller.receive_state({
            "type": "state", "frame": 1, "room_clear": True, "coins": 10, "player": {}, "enemies": [], "projectiles": [],
            "pickups": [{"id": 7, "pos": {"x": 20, "y": 0}, "is_collectible": True, "quality": 3, "price": 5, "name": "shop item"}],
            "layout": {"room_index": 12, "room_type": "shop", "doors": [{"slot": 2, "pos": {}, "target_room_index": 13}]},
        })
        self.assertEqual(response["mode"], "shop")
        self.assertEqual(response["id"], "take_item_7")

    def test_disappeared_item_clears_old_pedestal_navigation(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        first = {
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "pickups": [{"id": 7, "pos": {"x": 20, "y": 0}, "is_collectible": True, "quality": 0, "price": 0, "name": "item"}],
            "layout": {"room_index": 97, "room_type": "treasure", "doors": [{"slot": 1, "pos": {"x": 0, "y": -100}, "target_room_index": 84}]},
            "planned_door_slot": 1,
        }
        response = controller.receive_state(first)
        self.assertEqual(response["id"], "take_item_7")
        second = first | {"frame": 4, "pickups": []}
        response = controller.receive_state(second)
        self.assertNotEqual(response["id"], "take_item_7")
        self.assertEqual(response["id"], "enter_door_1")
        self.assertEqual(controller.status()["stale_actions_discarded"], 1)

    def test_async_disappeared_item_result_falls_back_without_breaking_bridge(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller._latest_action = Action("take_item_7", Vec2(1, 0), Vec2(), mode="item")
        future = Future()
        future.set_result(Action("take_item_7", Vec2(1, 0), Vec2(), mode="item"))
        controller._future = future
        controller._future_started_frame = 1
        response = controller.receive_state({
            "type": "state", "frame": 2, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "pickups": [],
            "layout": {"room_index": 97, "doors": [{"slot": 1, "pos": {}, "target_room_index": 84}]},
        })
        self.assertEqual(response["id"], "enter_door_1")
        self.assertIsNone(controller.status()["bridge_error"])

    def test_status_exposes_observed_room_rewards_for_the_floor_plan(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller.receive_state({
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "pickups": [{"id": 7, "pos": {}, "is_collectible": False, "kind": "key", "name": "key"}],
            "layout": {"room_index": 12, "doors": [{"slot": 2, "pos": {}, "target_room_index": 13}]},
        })
        knowledge = controller.status()["floor_knowledge"]
        self.assertEqual(knowledge[0]["room_index"], 12)
        self.assertEqual(knowledge[0]["rewards"], ["key"])

    def test_status_exposes_room_hazards_and_does_not_mark_room_exhausted(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        response = controller.receive_state({
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "hazards": [{"id": 33, "type": 33, "kind": "fire", "pos": {"x": 20, "y": 0}, "vel": {}}],
            "layout": {"room_index": 12, "doors": [{"slot": 2, "pos": {}, "target_room_index": 13}]},
        })
        self.assertEqual(response["mode"], "hazard")
        self.assertEqual(response["id"], "clear_hazard_33")
        status = controller.status()
        self.assertEqual(status["latest_state"]["hazards"][0]["kind"], "fire")
        self.assertNotIn(12, status["latest_state"]["exhausted_rooms"])

    def test_disappeared_hazard_clears_old_action(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        first = {
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "hazards": [{"id": 33, "type": 33, "kind": "fire", "pos": {"x": 20, "y": 0}, "vel": {}}],
            "layout": {"room_index": 12, "doors": [{"slot": 2, "pos": {}, "target_room_index": 13}]},
        }
        response = controller.receive_state(first)
        self.assertEqual(response["id"], "clear_hazard_33")
        second = first | {"frame": 4, "hazards": []}
        response = controller.receive_state(second)
        self.assertNotEqual(response["id"], "clear_hazard_33")

    def test_extinguished_fire_animation_clears_old_action(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        first = {
            "type": "state", "frame": 1, "room_clear": True, "player": {},
            "enemies": [], "projectiles": [],
            "hazards": [{"id": 2, "type": 33, "kind": "fire", "hp": 5,
                         "animation": "Flickering", "pos": {"x": 80}}],
            "layout": {"room_index": 98, "doors": [
                {"slot": 0, "pos": {"x": -100}, "target_room_index": 97}]},
        }
        self.assertEqual(controller.receive_state(first)["id"], "clear_hazard_2")
        extinguished = first | {"frame": 4, "hazards": [
            first["hazards"][0] | {"hp": 1, "state": 3, "animation": "Dissapear3"}]}
        response = controller.receive_state(extinguished)
        self.assertNotEqual(response["id"], "clear_hazard_2")
        self.assertEqual(controller.status()["latest_state"]["hazards"], [])

    def test_negative_xrock_bomb_action_is_not_cleared_as_stale(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": True, "bombs": 1,
            "player": {}, "enemies": [], "projectiles": [],
            "hazards": [{"id": -100012, "type": 7, "kind": "xrock", "requires_bomb": True, "pos": {"x": 80, "y": 0}, "vel": {}, "grid_index": 12}],
            "layout": {"room_index": 12, "doors": [{"slot": 2, "pos": {}, "target_room_index": 13}]},
        }
        response = controller.receive_state(message)
        self.assertEqual(response["id"], "bomb_hazard_-100012")
        message["frame"] = 4
        response = controller.receive_state(message)
        self.assertEqual(response["id"], "bomb_hazard_-100012")

    def test_boss_bomb_is_executed_once_then_combat_resumes(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": False, "bombs": 2,
            "player": {"hp": 6, "pos": {"x": 200, "y": 200}},
            "enemies": [{"id": 3, "type": 19, "pos": {"x": 290, "y": 200},
                         "hp": 4, "is_boss": True}],
            "projectiles": [], "safe_move_directions": {"left": "safe"},
            "layout": {"room_index": 12, "room_type": "boss", "is_boss": True},
        }
        response = controller.receive_state(message)
        self.assertEqual(response["id"], "bomb_boss_3")
        self.assertEqual(response["bomb_site"], {"x": 200.0, "y": 200.0})
        placed = message | {"frame": 4, "bombs": 1, "bomb_placed": True,
                            "bomb_active": True, "bomb_target_id": 3}
        response = controller.receive_state(placed)
        self.assertNotEqual(response["id"], "bomb_boss_3")
        finished = placed | {"frame": 7, "bomb_active": False}
        response = controller.receive_state(finished)
        self.assertNotEqual(response["id"], "bomb_boss_3")

    def test_unreachable_hidden_wall_does_not_loop_forever(self):
        controller = Controller(autopilot_enabled=False, policy_profile=PolicyProfile(pickup_stuck_frames=24))
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": True, "bombs": 1,
            "player": {"pos": {"x": 0, "y": 0}}, "enemies": [], "projectiles": [], "hazards": [],
            "layout": {"room_index": 12, "doors": [{"slot": 2, "pos": {}, "target_room_index": 13}],
                       "bomb_walls": [{"slot": 0, "pos": {"x": -160}, "site": {"x": -80},
                                       "grid_index": -1, "room_type": "secret"}]},
        }
        self.assertEqual(controller.receive_state(message)["id"], "bomb_secret_0")
        for frame in range(4, 64, 3):
            message["frame"] = frame
            response = controller.receive_state(message)
        self.assertNotEqual(response["id"], "bomb_secret_0")

    def test_unreachable_negative_grid_hazard_is_ignored_after_no_progress(self):
        controller = Controller(
            autopilot_enabled=False,
            policy_profile=PolicyProfile(pickup_stuck_frames=30),
        )
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "hazards": [{"id": -100065, "type": 149, "kind": "poop", "pos": {"x": 200, "y": 0}, "vel": {}}],
            "layout": {"room_index": 12, "doors": [{"slot": 2, "pos": {}, "target_room_index": 13}]},
        }
        response = controller.receive_state(message)
        self.assertEqual(response["id"], "clear_hazard_-100065")
        message["frame"] = 2
        controller.receive_state(message)
        message["frame"] = 32
        response = controller.receive_state(message)
        self.assertNotEqual(response["id"], "clear_hazard_-100065")
        self.assertEqual(controller.status()["latest_state"]["ignored_hazard_ids"], [-100065])
        self.assertEqual(response["ignored_hazard_ids"], [-100065])

    def test_nearby_ignored_hazard_stays_marked_for_door_navigation(self):
        controller = Controller(
            autopilot_enabled=False,
            policy_profile=PolicyProfile(pickup_stuck_frames=30),
        )
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": True, "player": {"pos": {"x": 0, "y": 0}},
            "enemies": [], "projectiles": [],
            "hazards": [{"id": 44, "type": 149, "kind": "poop", "pos": {"x": 40, "y": 0}, "vel": {}}],
            "layout": {"room_index": 12, "doors": [{"slot": 2, "pos": {}, "target_room_index": 13}]},
        }
        controller.receive_state(message)
        message["frame"] = 2
        controller.receive_state(message)
        message["frame"] = 32
        response = controller.receive_state(message)
        self.assertEqual(response["id"], "enter_door_2")
        self.assertEqual(response["ignored_hazard_ids"], [44])
        self.assertIn("hazard:44", response.get("unreachable_targets", []))

    def test_unreachable_pickup_is_marked_and_exit_is_selected(self):
        controller = Controller(
            autopilot_enabled=False,
            policy_profile=PolicyProfile(pickup_stuck_frames=30),
        )
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": True, "player": {"pos": {"x": 0, "y": 0}},
            "enemies": [], "projectiles": [],
            "pickups": [{"id": 77, "pos": {"x": 200, "y": 0}, "is_collectible": True, "name": "blocked item"}],
            "layout": {"room_index": 12, "doors": [{"slot": 2, "pos": {}, "target_room_index": 13}]},
        }
        controller.receive_state(message)
        message["frame"] = 2
        controller.receive_state(message)
        message["frame"] = 32
        response = controller.receive_state(message)
        self.assertEqual(response["id"], "enter_door_2")
        self.assertEqual(response["ignored_pickup_ids"], [77])
        self.assertIn("pickup:77", response.get("unreachable_targets", []))

    def test_unreachable_chest_is_marked_and_exit_is_selected(self):
        controller = Controller(autopilot_enabled=False, policy_profile=PolicyProfile(pickup_stuck_frames=30))
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": True, "player": {"pos": {"x": 0, "y": 0}},
            "enemies": [], "projectiles": [],
            "pickups": [{"id": 88, "pos": {"x": 200, "y": 0}, "is_collectible": True, "kind": "red_chest", "name": "red chest"}],
            "layout": {"room_index": 12, "doors": [{"slot": 2, "pos": {}, "target_room_index": 13}]},
        }
        controller.receive_state(message)
        message["frame"] = 2
        controller.receive_state(message)
        message["frame"] = 32
        response = controller.receive_state(message)
        self.assertEqual(response["id"], "enter_door_2")
        self.assertEqual(response["ignored_pickup_ids"], [88])
        self.assertIn("pickup:88", response["unreachable_targets"])

    def test_blocked_pickup_is_abandoned_before_distance_timeout(self):
        controller = Controller(autopilot_enabled=False, policy_profile=PolicyProfile(pickup_stuck_frames=90, movement_stall_threshold=6))
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": True,
            "player": {"pos": {"x": 0, "y": 0}}, "enemies": [], "projectiles": [],
            "pickups": [{"id": 79, "pos": {"x": 200, "y": 0}, "is_collectible": True, "name": "blocked item"}],
            "requested_move": {"x": 1, "y": 0}, "resolved_move": {"x": 0, "y": 0},
            "movement_progress": 0, "movement_blocked": True, "move_resolution_reason": "no_walkable_direction",
            "layout": {"room_index": 12, "doors": [{"slot": 2, "pos": {}, "target_room_index": 13}]},
        }
        controller.receive_state(message)
        message["frame"] = 2
        controller.receive_state(message)
        message["frame"] = 20
        response = controller.receive_state(message)
        self.assertEqual(response["id"], "enter_door_2")
        self.assertEqual(response["ignored_pickup_ids"], [79])

    def test_blocked_hazard_is_abandoned_before_distance_timeout(self):
        controller = Controller(autopilot_enabled=False, policy_profile=PolicyProfile(pickup_stuck_frames=90, movement_stall_threshold=6))
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": True,
            "player": {"pos": {"x": 0, "y": 0}}, "enemies": [], "projectiles": [],
            "hazards": [{"id": 46, "type": 149, "kind": "poop", "pos": {"x": 200, "y": 0}, "vel": {}}],
            "requested_move": {"x": 1, "y": 0}, "resolved_move": {"x": 0, "y": 0},
            "movement_progress": 0, "movement_blocked": True, "move_resolution_reason": "no_walkable_direction",
            "layout": {"room_index": 12, "doors": [{"slot": 2, "pos": {}, "target_room_index": 13}]},
        }
        controller.receive_state(message)
        message["frame"] = 2
        controller.receive_state(message)
        message["frame"] = 20
        response = controller.receive_state(message)
        self.assertEqual(response["id"], "enter_door_2")
        self.assertEqual(response["ignored_hazard_ids"], [46])

    def test_actions_are_bound_to_the_current_room_observation(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        response = controller.receive_state({
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 27, "doors": [{"slot": 2, "pos": {}, "target_room_index": 28}]},
        })
        self.assertEqual(response["source_room_index"], 27)

    def test_status_contains_transition_and_action_diagnostics(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller.receive_state({
            "type": "state", "frame": 1, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 4, "doors": [{"slot": 2, "pos": {}, "target_room_index": 5}]},
        })
        status = controller.status()
        self.assertIn("transition_phase", status)
        self.assertIn("action_sequence", status)
        self.assertIn("stale_actions_discarded", status)

    def test_zero_progress_after_lua_safety_rewrite_counts_as_stall(self):
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller._effective_action = Action("enter_door_2", Vec2(1, 0), Vec2(), mode="navigate")
        state = GameState.from_message({
            "type": "state", "frame": 2, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "requested_move": {"x": 1, "y": 0}, "resolved_move": {"x": 0, "y": 0},
            "movement_progress": 0.0, "movement_blocked": False,
            "move_resolution_reason": "lua_safety_rewrite",
            "layout": {"room_index": 4, "doors": [{"slot": 2, "pos": {}, "target_room_index": 5}]},
        })
        controller._update_movement_feedback(state)
        self.assertGreaterEqual(controller.status()["movement_stall_count"], 1)

    def test_reverse_door_guard_does_not_blacklist_only_open_exit(self):
        controller = Controller(autopilot_enabled=False, policy_profile=PolicyProfile(movement_stall_threshold=3))
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "frame": 1, "room_clear": True,
            "player": {"pos": {"x": 343, "y": 287}, "hp": 7}, "enemies": [], "projectiles": [],
            "layout": {"room_index": 83, "doors": [
                {"slot": 1, "pos": {"x": 320, "y": 120}, "target_room_index": 70,
                 "target_room_type": "challenge", "door_open": False, "door_open_known": True},
                {"slot": 2, "pos": {"x": 600, "y": 280}, "target_room_index": 84,
                 "target_room_type": "default", "door_open": True, "door_open_known": True},
            ]},
        }
        self.assertEqual(controller.receive_state(message)["id"], "enter_door_2")
        for frame in range(4, 40, 3):
            message.update(frame=frame, requested_move={"x": 1, "y": 0}, resolved_move={"x": 0, "y": 0},
                           movement_progress=0.0, move_resolution_reason="reverse_door_guard",
                           transition_gate="reverse_guard")
            response = controller.receive_state(message)
            self.assertEqual(response["id"], "enter_door_2")
        self.assertEqual(controller.status()["movement_stall_count"], 0)
        self.assertEqual(controller.status()["unreachable_targets"], [])

    def test_hazard_lane_hold_is_not_misclassified_as_blocked_movement(self):
        state = GameState.from_message({
            "type": "state", "frame": 2, "room_clear": True, "player": {}, "enemies": [], "projectiles": [],
            "requested_move": {"x": 0, "y": -1}, "resolved_move": {"x": 0, "y": 0},
            "movement_progress": 0.0, "movement_blocked": False,
            "move_resolution_reason": "hazard_lane_control",
            "layout": {"room_index": 85},
        })
        self.assertFalse(Controller._target_move_blocked(state))
        controller = Controller(autopilot_enabled=False)
        self.addCleanup(controller.shutdown)
        controller._effective_action = Action("clear_hazard_2", Vec2(0, -1), Vec2(), mode="hazard")
        controller._update_movement_feedback(state)
        self.assertEqual(controller.status()["movement_stall_count"], 0)

    def test_repeated_stationary_fire_is_not_penalized_without_blocked_movement(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(
                autopilot_enabled=False,
                log_dir=directory,
                policy_profile=PolicyProfile(repeat_action_threshold=6, repeat_penalty_frames=6),
            )
            self.addCleanup(controller.shutdown)
            message = {
                "type": "state", "room_clear": False, "player": {"hp": 6},
                "enemies": [{"id": 2, "type": 10, "pos": {"x": 30, "y": 0}, "vel": {}}],
                "projectiles": [], "layout": {"room_index": 1, "doors": []},
            }
            message["frame"] = 1
            controller.receive_state(message)
            for frame in (4, 7, 10, 13, 16, 19):
                message["frame"] = frame
                controller.receive_state(message)
            message["frame"] = 22
            response = controller.receive_state(message)
            self.assertNotIn("penalty", response["id"])
            self.assertEqual(controller.status()["stall_penalty_count"], 0)

    def test_blocked_movement_triggers_penalty_even_without_repeat_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(
                autopilot_enabled=False,
                log_dir=directory,
                policy_profile=PolicyProfile(movement_stall_threshold=3, repeat_penalty_frames=3),
            )
            self.addCleanup(controller.shutdown)
            message = {
                "type": "state", "room_clear": False, "player": {"hp": 6},
                "enemies": [{"id": 2, "type": 10, "pos": {"x": 220, "y": 0}, "vel": {}}],
                "projectiles": [], "layout": {"room_index": 1, "doors": []},
                "movement_blocked": True, "resolved_move": {"x": 0, "y": 0}, "movement_progress": 0.0,
            }
            for frame in (1, 4, 7, 10, 13):
                message["frame"] = frame
                response = controller.receive_state(message.copy())
            self.assertTrue(response["id"].startswith("movement_penalty_"))
            self.assertEqual(controller.status()["stall_penalty_count"], 1)

    def test_repeated_door_navigation_is_allowed_when_not_blocked(self):
        controller = Controller(
            autopilot_enabled=False,
            policy_profile=PolicyProfile(repeat_action_threshold=2, repeat_penalty_frames=2),
        )
        self.addCleanup(controller.shutdown)
        message = {
            "type": "state", "room_clear": True, "player": {"pos": {"x": 0, "y": 0}},
            "enemies": [], "projectiles": [], "pickups": [],
            "layout": {"room_index": 97, "doors": [{"slot": 1, "pos": {"x": 100, "y": 0}, "target_room_index": 84}]},
            "planned_door_slot": 1,
        }
        responses = []
        for frame in (1, 4, 7, 10, 13):
            message["frame"] = frame
            message["movement_blocked"] = False
            message["resolved_move"] = {"x": 1, "y": 0}
            message["movement_progress"] = 5.0
            responses.append(controller.receive_state(message.copy()))
        self.assertTrue(all(response["id"] == "enter_door_1" for response in responses))
        self.assertEqual(controller.status()["stall_penalty_count"], 0)

    def test_overage_jev_result_is_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(autopilot_enabled=False, log_dir=directory, policy_profile=PolicyProfile(max_action_age_frames=15))
            self.addCleanup(controller.shutdown)
            controller.receive_state({
                "type": "state", "frame": 1, "room_clear": False, "player": {"hp": 6},
                "enemies": [], "projectiles": [], "layout": {"room_index": 1, "doors": []},
            })
            future = Future()
            future.set_result(Action("hold_and_fire", Vec2(), Vec2(1, 0), confidence=0.9, source="jev"))
            controller._future = future
            controller._future_started_frame = 1
            response = controller.receive_state({
                "type": "state", "frame": 100, "room_clear": False, "player": {"hp": 6},
                "enemies": [{"id": 2, "type": 10, "pos": {"x": 30, "y": 0}, "vel": {}}],
                "projectiles": [], "layout": {"room_index": 1, "doors": []},
            })
            self.assertEqual(controller.status()["stale_decisions_discarded"], 1)
            self.assertNotEqual(response["source"], "jev")

    def test_dead_state_clears_action_and_does_not_schedule_jev(self):
        controller = Controller(autopilot_enabled=True)
        self.addCleanup(controller.shutdown)
        response = controller.receive_state({
            "type": "state", "frame": 10, "room_clear": False, "player": {"hp": 0},
            "enemies": [{"id": 2, "type": 10, "pos": {"x": 30, "y": 0}, "vel": {}}],
            "projectiles": [], "layout": {"room_index": 1, "doors": []},
        })
        self.assertEqual(response["id"], "dead_wait")
        self.assertFalse(controller.status()["decision_pending"])
        self.assertTrue(controller.status()["latest_state"]["player_dead"])
