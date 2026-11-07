"""Charge/release behavior with target windows and actual attack feedback."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class ChargedShootingTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.module = self.lua.execute((ROOT / 'mods/IsaacJev/weapon_control.lua').read_text(encoding='utf8'))
        self.control = self.module.new()
        self.owned = set()
        self.player = self.lua.table_from({'MaxFireDelay': 19.772859573364,
            'HasCollectible': lambda _, item: item in self.owned})

    def profile(self, weapon='brimstone'):
        return self.control.profile(self.control, self.player, weapon)

    def step(self, tick, ready=True, wanted=(1, 0), weapon='brimstone', **context):
        c = {'engaged': True, 'ready': ready, **context}
        result = self.control.step(self.control, tick, self.profile(weapon),
            self.lua.table_from(dict(zip(('x', 'y'), wanted))), self.lua.table_from(c))
        return result['x'], result['y'], self.control.phase

    def test_actual_brimstone_stats_do_not_receive_a_second_charge_multiplier(self):
        self.assertEqual(self.profile().charge, 23)
        for tick in range(23):
            self.assertEqual(self.step(tick), (1, 0, 'charge'))
        self.assertEqual(self.step(23), (0, 0, 'release'))

    def test_charged_attack_waits_for_vulnerable_aligned_target(self):
        for tick in range(80):
            row = self.step(tick, ready=False)
            self.assertEqual(row[:2], (1, 0))
        self.assertEqual(self.control.phase, 'hold_charge')
        self.assertEqual(self.step(80), (0, 0, 'release'))

    def test_evasion_or_occlusion_does_not_clear_a_held_charge(self):
        self.step(0)
        self.assertEqual(self.step(30, ready=False, wanted=(0, 0)), (1, 0, 'hold_charge'))
        self.assertEqual(self.control.start, 0)
        self.assertEqual(self.step(31), (0, 0, 'release'))

    def test_new_direction_is_committed_before_releasing(self):
        self.step(0)
        self.assertEqual(self.step(23, wanted=(0, -1)), (0, -1, 'aim_commit'))
        self.assertEqual(self.step(24, wanted=(0, -1)), (0, 0, 'release'))

    def test_brimstone_is_not_recharged_while_its_beam_is_active(self):
        self.step(0)
        self.step(23)
        for tick in range(24, 32):
            row = self.step(tick, shot=tick == 24, active_beam=True)
            self.assertEqual(row, (0, 0, 'beam'))
        self.assertEqual(self.control.shots, 1)
        self.assertEqual(self.step(32), (1, 0, 'charge'))
        self.assertEqual(self.control.failures, 0)

    def test_failed_release_extends_next_charge_instead_of_silently_looping(self):
        self.step(0)
        self.step(23)
        for tick in range(24, 28):
            self.assertEqual(self.step(tick)[:2], (0, 0))
        self.assertEqual(self.step(28), (1, 0, 'charge'))
        self.assertGreater(self.control.extra, 0)
        self.assertEqual(self.control.failures, 1)
        self.assertEqual(self.step(51)[:2], (1, 0))

    def test_room_clear_and_explicit_safety_stop_release_control(self):
        self.step(0)
        self.assertEqual(self.step(10, engaged=False), (0, 0, 'idle'))
        self.assertEqual(self.control.start, -1)
        self.step(11)
        self.assertEqual(self.step(15, hard_stop=True), (0, 0, 'idle'))

    def test_tech_x_fires_full_charge_and_can_charge_while_ring_is_in_flight(self):
        self.step(0, weapon='tech_x')
        self.assertEqual(self.step(23, weapon='tech_x'), (0, 0, 'release'))
        self.step(24, weapon='tech_x', shot=True)
        self.assertEqual(self.step(25, weapon='tech_x'), (1, 0, 'charge'))

    def test_knife_waits_for_native_full_charge_and_return(self):
        self.step(0, weapon='knife', knife_charge=0)
        self.assertEqual(self.step(23, weapon='knife', knife_charge=.4)[:2], (1, 0))
        self.assertEqual(self.step(40, weapon='knife', knife_charge=1), (0, 0, 'release'))
        self.assertEqual(self.step(41, weapon='knife', shot=True, knife_flying=True), (0, 0, 'beam'))
        self.assertEqual(self.step(60, weapon='knife', knife_flying=True), (0, 0, 'beam'))
        self.assertEqual(self.step(61, weapon='knife', knife_flying=False)[:2], (1, 0))

    def test_chocolate_milk_overrides_technology_continuous_profile(self):
        self.owned.add(69)
        self.assertEqual(self.profile('laser').kind, 'chocolate_milk')
        self.assertEqual(self.profile('laser').mode, 'release')

    def test_soy_milk_and_ordinary_tears_have_no_release_pulses(self):
        for weapon in ['tear', 'laser', 'bombs']:
            for tick in range(40):
                self.assertEqual(self.step(tick, weapon=weapon), (1, 0, 'continuous'))
        self.owned.add(330)
        for tick in range(40):
            self.assertEqual(self.step(tick), (1, 0, 'continuous'))

    def test_melee_taps_and_ranged_charges_are_separate(self):
        self.assertEqual(self.step(0, weapon='spirit_sword', distance=40), (1, 0, 'melee_tap'))
        self.assertEqual(self.step(1, weapon='spirit_sword', distance=40)[:2], (0, 0))
        self.assertEqual(self.step(3, weapon='spirit_sword', distance=40)[:2], (1, 0))
        self.assertEqual(self.step(4, weapon='spirit_sword', distance=180), (1, 0, 'charge'))

    def test_soy_milk_knife_still_requires_release(self):
        self.owned.add(330)
        self.assertEqual(self.profile('knife').mode,'release')
        self.step(0,weapon='knife',knife_charge=0)
        self.assertEqual(self.step(23,weapon='knife',knife_charge=1),(0,0,'release'))

    def test_sword_aim_is_locked_until_its_real_release(self):
        self.step(0,weapon='spirit_sword',distance=180)
        self.assertEqual(self.step(30,weapon='spirit_sword',wanted=(0,1),ready=False,distance=180)[:2],(1,0))
        self.assertEqual(self.step(116,weapon='spirit_sword',wanted=(0,1),ready=False,distance=180),(0,0,'release'))

    def test_sword_can_turn_after_switching_from_charge_to_close_taps(self):
        self.step(0,weapon='spirit_sword',distance=180)
        self.assertEqual(self.step(10,weapon='spirit_sword',distance=40,wanted=(0,1)),(0,1,'melee_tap'))
        self.assertEqual(self.step(13,weapon='spirit_sword',distance=40,wanted=(-1,0)),(-1,0,'melee_tap'))
        self.assertEqual(self.step(14,weapon='spirit_sword',distance=180,wanted=(-1,0)),(-1,0,'charge'))

    def test_existing_beam_is_not_cut_when_new_target_or_controller_appears(self):
        self.assertEqual(self.step(0,active_beam=True,shot=True),(0,0,'beam'))
        self.assertEqual(self.step(5,active_beam=True),(0,0,'beam'))
        self.assertEqual(self.step(8,active_beam=False),(1,0,'charge'))

    def test_fetus_auto_charge_is_not_mistaken_for_a_release_weapon(self):
        for tick in range(50):
            self.assertEqual(self.step(tick,weapon='fetus'),(1,0,'continuous'))

    def test_knife_can_use_timing_when_native_charge_property_is_unavailable(self):
        self.step(0,weapon='knife',knife_charge=0)
        self.assertEqual(self.step(23,weapon='knife',knife_charge=0),(0,0,'release'))


if __name__ == '__main__':
    unittest.main()
