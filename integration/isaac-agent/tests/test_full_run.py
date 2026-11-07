"""Regressions for real play: cardinal tears, ending navigation and native results."""
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from isaac_jev.models import Action, Door, Entity, GameState, GridEvent, Hazard, Pickup, RoomLayout, Vec2
from isaac_jev.decision import candidate_actions, hard_rule_filter
from isaac_jev.runtime import Controller
from isaac_jev.navigation import firing_position, door_is_usable


class FullRunTests(unittest.TestCase):
    def test_shop_without_buying_power_does_not_spend_a_key(self):
        state=GameState(frame=1,room_clear=True,player=Entity(0,1,Vec2(),Vec2(),6),enemies=(),projectiles=(),keys=1,coins=0)
        self.assertFalse(door_is_usable(Door(0,Vec2(),target_room_index=2,target_room_type="shop",locked=True),state))

    def test_healthy_run_explores_for_missing_treasure_before_early_boss(self):
        with tempfile.TemporaryDirectory() as folder:
            controller=Controller(log_dir=folder)
            controller._current_room_index=1
            controller._visited_rooms={1}
            doors=(Door(0,Vec2(),target_room_index=2,target_room_type="default"),
                Door(1,Vec2(),target_room_index=3,target_room_type="boss",target_is_boss=True))
            controller._room_graph[1]=doors
            state=GameState(frame=1,stage=2,room_clear=True,player=Entity(0,1,Vec2(),Vec2(),6),
                enemies=(),projectiles=(),keys=1,red_hearts=6,max_hearts=6,layout=RoomLayout(room_index=1,doors=doors))
            self.assertEqual(controller._plan_next_door(state),(0,"search treasure upgrade before boss"))
            controller._room_intel[4]={"room_type":"treasure","clear":True}
            self.assertEqual(controller._plan_next_door(state),(1,"known boss room"))
            controller.shutdown()

    def test_full_pockets_do_not_cycle_ground_consumables_or_block_boss_exit(self):
        state = GameState(frame=100,room_clear=True,player=Entity(0,1,Vec2(),Vec2(),5),
            enemies=(),projectiles=(),held_cards=((0,1),),
            boss_exit_available=True,boss_exit_grid_index=50,boss_exit_position=Vec2(300,300),
            layout=RoomLayout(room_index=1,is_boss=True,room_type="boss"),
            pickups=(Pickup(1,Vec2(100,100),0,0,0,False,"pill",pickup_kind="pill"),
                Pickup(2,Vec2(200,100),0,0,0,False,"card",pickup_kind="card")))
        self.assertEqual(candidate_actions(state)[0].mode,"boss_exit")

    def test_unknown_pill_can_upgrade_to_card_without_replacing_pills_forever(self):
        state = GameState(frame=1,room_clear=True,player=Entity(0,1,Vec2(),Vec2(),5),
            enemies=(),projectiles=(),held_pills=((0,11),),
            pickups=(Pickup(1,Vec2(100,100),0,0,0,False,"pill",pickup_kind="pill"),
                Pickup(2,Vec2(200,100),0,0,0,False,"card",pickup_kind="card")))
        self.assertEqual(candidate_actions(state)[0].action_id,"take_pickup_2")

    def test_negative_health_price_is_not_free_but_price_free_is(self):
        state = GameState(frame=1,room_clear=True,player=Entity(0,1,Vec2(),Vec2(),5),
            enemies=(),projectiles=(),coins=99,
            pickups=(Pickup(1,Vec2(100,100),0,-2,4,True,"health deal"),
                Pickup(2,Vec2(200,100),0,-1000,1,True,"free item")))
        self.assertEqual(candidate_actions(state)[0].action_id,"take_item_2")

    def test_alternating_tnt_targets_do_not_reset_stall_timers(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = Controller(log_dir=folder)
            state = GameState(frame=1, room_clear=True,
                player=Entity(0,1,Vec2(300,160),Vec2(),6), enemies=(), projectiles=(),
                layout=RoomLayout(room_index=1, grid_events=(
                    GridEvent("tnt",66,Vec2(280,280),active=True,entity_id=-100066),
                    GridEvent("tnt",68,Vec2(360,280),active=True,entity_id=-100068))))
            for frame in range(1, 202):
                target = -100066 if frame % 2 else -100068
                controller._effective_action = Action(f"shoot_tnt_{target}",Vec2(),Vec2(),mode="tnt")
                controller._update_hazard_progress(replace(state,frame=frame))
            self.assertTrue({-100066,-100068}.issubset(controller._ignored_hazard_ids))
            controller.shutdown()

    def test_shoots_across_pit_without_standing_in_it(self):
        enemy=Entity(1,27,Vec2(120,120),Vec2(),3.5,grid_index=30)
        state=GameState(frame=1,room_clear=False,player=Entity(0,1,Vec2(280,120),Vec2(),7),
            player_grid_index=34,enemies=(enemy,),projectiles=(),
            layout=RoomLayout(room_index=1,grid_width=9,grid_height=7,
                blocked=frozenset({31}),shot_blocked=frozenset()))
        self.assertTrue(state.geometry_features()["line_of_fire"])
        lane=firing_position(state,enemy.position,enemy.grid_index,95)
        self.assertIsNotNone(lane)
        self.assertEqual(lane[0].y,enemy.position.y)
        self.assertGreater(lane[0].x,enemy.position.x)
        self.assertNotIn(lane[1],state.layout.blocked)

    def test_productive_combat_does_not_switch_to_unrelated_xrock(self):
        state = GameState(frame=100,room_clear=False,player=Entity(0,1,Vec2(200,200),Vec2(),6),
            enemies=(Entity(1,12,Vec2(400,200),Vec2(),10),Entity(2,12,Vec2(200,400),Vec2(),10)),
            projectiles=(),combat_stuck=True,bombs=5,
            hazards=(Hazard(-100040,"xrock",4,Vec2(100,100),Vec2(),grid_index=40,requires_bomb=True),))
        self.assertTrue(all(action.mode == "combat" for action in candidate_actions(state)))

    def test_low_health_takes_heart_before_key(self):
        state = GameState(frame=1,room_clear=True,player=Entity(0,1,Vec2(),Vec2(),1),enemies=(),projectiles=(),
            red_hearts=1,max_hearts=6,pickups=(
                Pickup(1,Vec2(80,0),1,0,0,False,"key",pickup_kind="key"),
                Pickup(2,Vec2(0,80),1,0,0,False,"heart",pickup_kind="red_heart")))
        self.assertEqual(candidate_actions(state)[0].action_id,"take_pickup_2")

    def test_damage_chests_do_not_prevent_leaving_room(self):
        doors=(Door(0,Vec2(100,0),target_room_index=2),)
        state = GameState(frame=1,room_clear=True,player=Entity(0,1,Vec2(),Vec2(),1),enemies=(),projectiles=(),
            pickups=(Pickup(1,Vec2(80,0),1,0,0,False,"spiked",pickup_kind="spiked_chest"),),
            layout=RoomLayout(room_index=1,doors=doors),planned_door_slot=0)
        self.assertEqual(candidate_actions(state)[0].action_id,"enter_door_0")

    def test_last_key_is_reserved_for_visible_unopened_treasure(self):
        doors=(Door(0,Vec2(100,0),target_room_index=2,target_room_type="treasure",locked=True),)
        state = GameState(frame=1,room_clear=True,player=Entity(0,1,Vec2(),Vec2(),6),enemies=(),projectiles=(),keys=1,
            pickups=(Pickup(1,Vec2(80,0),1,0,0,False,"locked",pickup_kind="locked_chest"),),
            layout=RoomLayout(room_index=1,doors=doors),planned_door_slot=0)
        self.assertEqual(candidate_actions(state)[0].action_id,"enter_door_0")

    def test_new_key_routes_back_to_observed_treasure_before_boss(self):
        with tempfile.TemporaryDirectory() as folder:
            controller=Controller(log_dir=folder)
            controller._current_room_index=1
            controller._visited_rooms={1,2}
            doors=(Door(0,Vec2(),target_room_index=2,target_clear=True),
                Door(1,Vec2(),target_room_index=4,target_room_type="boss",target_is_boss=True))
            controller._room_graph[1]=doors
            controller._room_graph[2]=(Door(3,Vec2(),target_room_index=3,target_room_type="treasure",locked=True),)
            state=GameState(frame=1,room_clear=True,player=Entity(0,1,Vec2(),Vec2(),6),
                enemies=(),projectiles=(),keys=1,layout=RoomLayout(room_index=1,doors=doors))
            self.assertEqual(controller._plan_next_door(state)[0],0)
            controller.shutdown()

    def test_low_health_returns_to_observed_heart_through_clear_rooms(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = Controller(log_dir=folder)
            controller._current_room_index = 1
            doors = (Door(0,Vec2(),target_room_index=2,target_clear=True),
                     Door(2,Vec2(),target_room_index=4,target_clear=False))
            controller._room_graph[1] = doors
            controller._room_graph[2] = (Door(1,Vec2(),target_room_index=3,target_clear=True),)
            controller._room_intel[3] = {"clear":True,"room_type":"default","rewards":["red_heart"]}
            state = GameState(frame=1,room_clear=True,player=Entity(0,1,Vec2(),Vec2(),1),
                enemies=(),projectiles=(),red_hearts=1,max_hearts=6,layout=RoomLayout(room_index=1,doors=doors))
            self.assertEqual(controller._plan_next_door(state),(0,"return to observed health pickup"))
            controller.shutdown()

    def test_coin_12_is_not_rejected_as_full_health_heart_2(self):
        state = GameState(frame=1, room_clear=True,
            player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(),
            red_hearts=6, max_hearts=6, pickups=(
                Pickup(2, Vec2(100, 100), 1, 0, 0, False, "heart", pickup_kind="red_heart"),
                Pickup(12, Vec2(200, 100), 1, 0, 0, False, "coin", pickup_kind="coin")))
        actions, rejected = hard_rule_filter(state, [Action("take_pickup_12", Vec2(1,0), Vec2(), mode="pickup")])
        self.assertFalse(rejected)
        self.assertEqual(len(actions),1)

    def test_free_item_12_does_not_inherit_item_2_price(self):
        state = GameState(frame=1, room_clear=True,
            player=Entity(0, 1, Vec2(), Vec2(), 6), enemies=(), projectiles=(), coins=0,
            pickups=(Pickup(2,Vec2(),1,15,3,True,"expensive"),
                     Pickup(12,Vec2(100,0),2,0,3,True,"free")))
        actions, rejected = hard_rule_filter(state, [Action("take_item_12", Vec2(1,0), Vec2(), mode="item")])
        self.assertFalse(rejected)
        self.assertEqual(len(actions),1)

    def test_unblocked_diagonal_enemy_requires_firing_lane(self):
        state = GameState(frame=1, room_clear=False,
            player=Entity(0, 1, Vec2(218, 363), Vec2(), 6),
            enemies=(Entity(1, 12, Vec2(322, 277), Vec2(), 3),), projectiles=())
        self.assertFalse(state.geometry_features()["line_of_fire"])
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "reposition_to_fire_lane")
        self.assertNotEqual(action.move, Vec2())

    def test_ending_chest_is_reached_by_normal_pickup_navigation(self):
        state = GameState(frame=1, room_clear=True,
            player=Entity(0, 1, Vec2(100, 100), Vec2(), 6), enemies=(), projectiles=(),
            pickups=(Pickup(entity_id=9, position=Vec2(200, 100), subtype=0, price=0,
                pickup_kind="ending_chest", name="ending chest", quality=0, is_collectible=False),))
        action = candidate_actions(state)[0]
        self.assertEqual(action.action_id, "take_pickup_9")
        self.assertNotEqual(action.move, Vec2())

    def test_native_death_does_not_count_as_victory(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = Controller(log_dir=folder, autopilot_enabled=True)
            controller._latest_state = GameState(frame=10, room_clear=False,
                player=Entity(0, 1, Vec2(), Vec2()), enemies=(), projectiles=())
            controller._run_seed = 12
            event = {"type": "game_event", "callback": "MC_POST_GAME_END",
                "start_seed": 12, "stage": 6, "is_game_over": True}
            controller.receive_game_event(event)
            self.assertFalse((Path(folder) / "victory.json").exists())
            self.assertTrue(controller.autopilot_enabled)
            controller.receive_game_event(dict(event, is_game_over=False))
            self.assertEqual(json.loads((Path(folder) / "victory.json").read_text())["result"], "victory")
            self.assertFalse(controller.autopilot_enabled)
            controller.shutdown()


if __name__ == "__main__":
    unittest.main()
