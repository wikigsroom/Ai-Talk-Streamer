"""Keep observed knockback separate from the fixed Boil body's trajectory."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from isaac_jev.models import Entity, GameState, Vec2
from isaac_jev.decision import combat_actions, _predictive_enemy_aim, build_candidate_set, local_policy_action


class AnchoredBoilMotionTests(unittest.TestCase):
    def test_only_fixed_red_boil_uses_zero_body_motion_and_raw_velocity_is_preserved(self):
        boil=Entity(1,30,Vec2(240,200),Vec2(-20,3),20,variant=0)
        self.assertEqual(boil.motion_velocity,Vec2())
        self.assertEqual(boil.velocity,Vec2(-20,3))
        for other in (replace(boil,variant=1),replace(boil,kind=10),replace(boil,kind=9)):
            self.assertEqual(other.motion_velocity,other.velocity)

    def test_macro_aim_and_charge_dodge_use_body_motion_rather_than_knockback(self):
        player=Entity(0,1,Vec2(100,200),Vec2(),8,engagement_range=160)
        boil=Entity(1,30,Vec2(240,200),Vec2(-20,0),20,variant=0)
        state=GameState(frame=1,room_clear=False,player=player,enemies=(boil,),projectiles=())
        self.assertFalse(any(a.action_id.startswith('dodge_charge') for a in combat_actions(state)))
        mobile=replace(state,enemies=(replace(boil,variant=1),))
        self.assertTrue(any(a.action_id.startswith('dodge_charge') for a in combat_actions(mobile)))
        aiming=replace(state,player=replace(player,position=Vec2(240,60)))
        self.assertEqual(_predictive_enemy_aim(aiming,boil),Vec2(0,1))
        self.assertNotEqual(_predictive_enemy_aim(aiming,replace(boil,variant=1)),Vec2(0,1))

    def test_actual_nine_enemy_room_keeps_a_reachable_firing_waypoint(self):
        raw=json.loads((Path(__file__).parent/'fixtures/stage3-boss-boil-knockback-stall.json').read_text('utf8'))
        state=GameState.from_message(raw)
        self.assertEqual(len(state.enemies),9)
        self.assertTrue(any(abs(e.velocity.x)>10 for e in state.enemies))
        self.assertTrue(all(e.motion_velocity==Vec2() for e in state.enemies))
        action=local_policy_action(state,build_candidate_set(state))
        self.assertIsNotNone(action.waypoint)
        self.assertNotEqual(action.move,Vec2())
        self.assertLessEqual(min(action.waypoint.distance_to(e.position) for e in state.enemies),160)


if __name__=='__main__':unittest.main()
