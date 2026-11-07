"""Trade only deliberate supported upgrades with a survivable health budget."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import Entity,GameState,Pickup,RoomLayout,Vec2
from isaac_jev.decision import build_candidate_set,local_policy_action


class HealthDealBudgetTests(unittest.TestCase):
    def setUp(self):
        self.offer=Pickup(12,Vec2(200,280),118,-2,4,True,'Brimstone')
        self.state=GameState(frame=300,stage=4,room_clear=True,progression_target='satan',
            player=Entity(0,1,Vec2(320,280),Vec2(),12),enemies=(),projectiles=(),
            max_hearts=8,red_hearts=8,soul_hearts=4,
            pickups=(self.offer,),layout=RoomLayout(room_index=-1,room_type='devil'))

    def selected(self,state):
        return local_policy_action(state,build_candidate_set(state)).action_id

    def test_supported_two_heart_upgrade_can_be_deliberately_bought(self):
        self.assertEqual(self.selected(self.state),'take_item_12')

    def test_quality_threshold_depends_on_red_container_cost(self):
        for price,quality,allowed in ((-1,3,True),(-1,2,False),(-2,3,False)):
            with self.subTest(price=price,quality=quality):
                state=replace(self.state,pickups=(replace(self.offer,price=price,quality=quality),))
                self.assertEqual(self.selected(state)=='take_item_12',allowed)

    def test_owned_route_item_offer_uses_health_budget_instead_of_quality(self):
        offer=replace(self.offer,subtype=84,quality=2,price=-1,name='We Need To Go Deeper!')
        state=replace(self.state,pickups=(offer,))
        self.assertEqual(self.selected(state),'take_item_12')
        poor=replace(state,max_hearts=4,red_hearts=4,soul_hearts=0,
                     player=replace(state.player,hit_points=4))
        self.assertNotEqual(self.selected(poor),'take_item_12')

    def test_safe_route_offer_precedes_generic_item_quality(self):
        shovel=replace(self.offer,entity_id=13,subtype=84,quality=2,price=-1)
        self.assertEqual(self.selected(replace(self.state,pickups=(self.offer,shovel))),'take_item_13')

    def test_repeated_purchases_recheck_remaining_containers(self):
        state=replace(self.state,max_hearts=6,red_hearts=6,soul_hearts=8,
            player=replace(self.state.player,hit_points=14))
        self.assertNotEqual(self.selected(state),'take_item_12')

    def test_filled_red_health_is_capped_after_container_removal(self):
        # Four filled red containers plus half a soul heart leave only five
        # half-heart units, below the six-unit survival budget.
        state=replace(self.state,red_hearts=8,soul_hearts=1,
            player=replace(self.state.player,hit_points=9))
        self.assertNotEqual(self.selected(state),'take_item_12')
        # Empty containers may be spent without inventing lost filled hearts.
        state=replace(self.state,red_hearts=2,soul_hearts=4,
            player=replace(self.state.player,hit_points=6))
        self.assertEqual(self.selected(state),'take_item_12')

    def test_low_health_and_inconsistent_observations_never_pass_the_budget(self):
        state=replace(self.state,player=replace(self.state.player,hit_points=5),coins=99)
        self.assertNotEqual(self.selected(state),'take_item_12')

    def test_unknown_and_non_red_prices_do_not_use_the_container_formula(self):
        for price in (-3,-4,-5,-6,-7,-8,-9,-10,-11):
            with self.subTest(price=price):
                state=replace(self.state,pickups=(replace(self.offer,price=price),))
                self.assertNotEqual(self.selected(state),'take_item_12')

    def test_bone_containers_and_unsupported_controls_are_not_traded(self):
        self.assertNotEqual(self.selected(replace(self.state,bone_hearts=1)),'take_item_12')
        for subtype in (0,168,329,358,233,394,352,474,316):
            with self.subTest(subtype=subtype):
                state=replace(self.state,pickups=(replace(self.offer,subtype=subtype),))
                self.assertNotEqual(self.selected(state),'take_item_12')

    def test_trade_admission_requires_a_clear_early_devil_room_and_satan_goal(self):
        for change in ({'progression_target':''},{'stage':1},{'stage':8},{'room_clear':False},
                       {'layout':RoomLayout(room_index=1,room_type='default')}):
            with self.subTest(change=change):
                self.assertNotEqual(self.selected(replace(self.state,**change)),'take_item_12')

    def test_container_transformations_cannot_bypass_the_retained_health_budget(self):
        for subtype in (81, 230, 549):
            with self.subTest(subtype=subtype):
                offer=replace(self.offer,subtype=subtype,price=-1,quality=4)
                self.assertNotEqual(self.selected(replace(self.state,pickups=(offer,))),'take_item_12')

    def test_sheol_trapdoor_precedes_any_health_trade(self):
        state=replace(self.state,stage=8,boss_exit_available=True,
            boss_exit_position=Vec2(320,320),boss_exit_grid_index=67)
        self.assertEqual(self.selected(state),'enter_boss_exit_67')


if __name__=='__main__':unittest.main()
