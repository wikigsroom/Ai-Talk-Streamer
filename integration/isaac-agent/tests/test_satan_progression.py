"""Do not end a viable Sheol route at Mom's Heart's ending chest."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import Door,Entity,GameState,Pickup,RoomLayout,Vec2
from isaac_jev.decision import strategic_actions
from isaac_jev.navigation import door_is_usable

class SatanProgressionTests(unittest.TestCase):
    def state(self):
        return GameState(frame=100,room_clear=True,stage=8,progression_target='satan',
            player=Entity(0,1,Vec2(320,280),Vec2(),8),enemies=(),projectiles=(),
            layout=RoomLayout(room_index=1,room_type='boss',is_boss=True),
            pickups=(Pickup(12,Vec2(320,280),0,0,0,False,'ending chest',pickup_kind='ending_chest'),))

    def test_open_negative_devil_index_precedes_ending_chest(self):
        state=self.state()
        door=Door(0,Vec2(40,280),-1,target_room_type='devil',open=True,open_known=True)
        state=replace(state,layout=replace(state.layout,doors=(door,)))
        action=strategic_actions(state)[0]
        self.assertTrue(door_is_usable(door,state))
        self.assertEqual((action.mode,action.action_id),('navigate','enter_door_0'))

    def test_closed_devil_door_cannot_replace_valid_ending(self):
        state=self.state()
        door=Door(0,Vec2(40,280),-1,target_room_type='devil',open=False,open_known=True)
        state=replace(state,layout=replace(state.layout,doors=(door,)))
        self.assertFalse(door_is_usable(door,state))
        self.assertEqual(strategic_actions(state)[0].action_id,'take_pickup_12')

    def test_unknown_negative_indices_and_unrelated_floors_stay_blocked(self):
        door=Door(0,Vec2(),-1,target_room_type='unknown',open=True,open_known=True)
        self.assertFalse(door_is_usable(door,self.state()))
        self.assertFalse(door_is_usable(replace(door,target_room_type='devil'),replace(self.state(),stage=1)))

    def test_early_devil_offer_is_inspected_once_before_floor_exit(self):
        door=Door(0,Vec2(40,280),-1,target_room_type='devil',open=True,open_known=True)
        state=replace(self.state(),stage=2,pickups=(),boss_exit_available=True,
            boss_exit_grid_index=67,boss_exit_position=Vec2(320,280),room_cleared_frame=0,
            layout=replace(self.state().layout,doors=(door,)))
        self.assertEqual(strategic_actions(state)[0].action_id,'enter_door_0')
        seen=replace(state,visited_room_indices=frozenset({1,-1}))
        self.assertEqual(strategic_actions(seen)[0].mode,'boss_exit')

    def test_early_devil_visit_keeps_health_deals_unaffordable(self):
        state=replace(self.state(),stage=2,pickups=(
            Pickup(13,Vec2(200,280),1,-2,4,True,'devil deal'),),
            layout=RoomLayout(room_index=-1,room_type='devil',doors=(
                Door(2,Vec2(600,280),1,open=True,open_known=True),)),
            previous_room_index=1,planned_door_slot=2)
        self.assertEqual(strategic_actions(state)[0].action_id,'enter_door_2')

    def test_native_devil_trapdoor_precedes_paid_deals(self):
        state=replace(self.state(),layout=RoomLayout(room_index=-1,room_type='devil'),
            boss_exit_available=True,boss_exit_grid_index=67,boss_exit_position=Vec2(320,320),
            pickups=(Pickup(13,Vec2(200,280),1,-2,4,True,'devil deal'),))
        action=strategic_actions(state)[0]
        self.assertEqual((action.mode,action.target),('boss_exit','Sheol'))

    def test_native_trapdoor_in_heart_room_precedes_ending_chest(self):
        state=replace(self.state(),boss_exit_available=True,boss_exit_grid_index=67,
                      boss_exit_position=Vec2(320,320))
        self.assertEqual(strategic_actions(state)[0].action_id,'enter_boss_exit_67')

    def test_other_objectives_keep_native_ending(self):
        state=replace(self.state(),progression_target='')
        door=Door(0,Vec2(40,280),-1,target_room_type='devil',open=True,open_known=True)
        state=replace(state,layout=replace(state.layout,doors=(door,)))
        self.assertEqual(strategic_actions(state)[0].action_id,'take_pickup_12')

if __name__=='__main__': unittest.main()
