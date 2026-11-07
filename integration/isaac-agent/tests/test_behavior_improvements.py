import json
import unittest

from isaac_jev.decision import build_candidate_set, candidate_actions
from isaac_jev.models import Door, Entity, GameState, GridEvent, Pickup, RoomLayout, Vec2
from isaac_jev.navigation import move_towards, path_distance
from isaac_jev.providers import JevProvider, ProviderQuestion, ProviderSettings


def clear_state(layout, *, pickups=(), player_grid_index=0, hearts=6, planned_door_slot=-1):
    return GameState(
        frame=10, room_clear=True,
        player=Entity(0, 1, Vec2(), Vec2(), hearts),
        enemies=(), projectiles=(), layout=layout, pickups=pickups,
        player_grid_index=player_grid_index, red_hearts=hearts,
        planned_door_slot=planned_door_slot,
    )


class BehaviorImprovementTests(unittest.TestCase):
    def test_unpressed_button_precedes_closed_exit(self):
        button = GridEvent("button", 4, Vec2(40, 40), active=True, entity_id=-100004)
        layout = RoomLayout(
            room_index=1, grid_width=3, grid_height=3,
            doors=(Door(0, Vec2(100, 0), target_room_index=2, open=False, open_known=True),),
            grid_events=(button,),
        )
        action = candidate_actions(clear_state(layout, planned_door_slot=0))[0]
        self.assertEqual(action.action_id, "press_button_-100004")
        self.assertEqual(action.mode, "button")

    def test_low_health_curse_door_is_replaced_by_safe_exit(self):
        layout = RoomLayout(room_index=1, doors=(
            Door(0, Vec2(100, 0), target_room_index=2, target_room_type="curse"),
            Door(1, Vec2(0, -100), target_room_index=3, target_room_type="default"),
        ))
        actions = candidate_actions(clear_state(layout, hearts=2, planned_door_slot=0))
        self.assertEqual(actions[0].action_id, "enter_door_1")
        self.assertNotIn("enter_door_0", {item.action_id for item in actions})

    def test_fully_enclosed_pickup_does_not_block_room_exit(self):
        layout = RoomLayout(
            room_index=1, grid_width=5, grid_height=5,
            blocked=frozenset({7, 11, 13, 17}),
            doors=(Door(0, Vec2(0, -100), target_room_index=2),),
        )
        pickup = Pickup(77, Vec2(80, 80), 0, 0, 3, True, "sealed item", 12)
        state = clear_state(layout, pickups=(pickup,), planned_door_slot=0)
        self.assertEqual(path_distance(state, pickup.position, pickup.grid_index), float("inf"))
        self.assertEqual(candidate_actions(state)[0].action_id, "enter_door_0")

    def test_reachable_pickup_next_to_wall_uses_detour(self):
        layout = RoomLayout(room_index=1, grid_width=5, grid_height=5, blocked=frozenset({1}))
        pickup = Pickup(77, Vec2(80, 0), 0, 0, 3, True, "item beside wall", 2)
        state = clear_state(layout, pickups=(pickup,))
        self.assertLess(path_distance(state, pickup.position, pickup.grid_index), float("inf"))
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "take_item_77")
        self.assertEqual(action.move, Vec2(0, 1))

    def test_path_and_combat_candidates_avoid_dangerous_grid(self):
        layout = RoomLayout(
            room_index=1, grid_width=3, grid_height=3,
            danger_grid_indices=frozenset({5}),
        )
        state = clear_state(layout, player_grid_index=4)
        self.assertEqual(move_towards(state, Vec2(80, -80), 2), Vec2(0, -1))
        combat = GameState(
            frame=10, room_clear=False,
            player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(1, 10, Vec2(180, 0), Vec2(), 5),),
            projectiles=(), layout=layout, player_grid_index=4,
        )
        candidates = build_candidate_set(combat).admissible_candidates
        self.assertTrue(candidates)
        self.assertTrue(all(item.move != Vec2(1, 0) for item in candidates))


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


class MultiQuestionBehaviorTests(unittest.TestCase):
    def test_reordered_partial_answers_do_not_cross_question_boundaries(self):
        questions = {
            "target": ProviderQuestion("Target?", {"enemy_1": "near", "enemy_2": "far"}),
            "tactic": ProviderQuestion("Tactic?", {"kite": "dodge", "attack": "fire"}),
            "trigger": ProviderQuestion("Fire?", {"hold": "yes", "release": "no"}),
        }
        captured = []

        def opener(request, timeout):
            captured.append(json.loads(request.data))
            return _Response({"answers": {
                "trigger": {"choice": "hold", "confidence": 0.95},
                "tactic": {"choice": "enemy_1", "confidence": 1.0},
                "target": {"choice": "enemy_2", "confidence": 0.91},
            }})

        settings = ProviderSettings("https://jev.test/v1/systemone", "", "jev-test", 0.75, 0.7)
        batch = JevProvider(settings, api_key="test-key", opener=opener).choose_questions({}, questions)
        self.assertEqual(len(captured), 1)
        self.assertEqual(set(captured[0]["questions"]), set(questions))
        self.assertEqual(batch.answers["target"].selected_choice, "enemy_2")
        self.assertEqual(batch.answers["tactic"].status, "invalid_choice")
        self.assertEqual(batch.answers["trigger"].selected_choice, "hold")


if __name__ == "__main__":
    unittest.main()
