"""Replay repeated engine input queries after a charged active consumes charge."""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class ActiveInputPaymentTests(unittest.TestCase):
    def setUp(self):
        source = (ROOT / 'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper = 'function mod:onInput(' + source.split('function mod:onInput(', 1)[1].split('function mod:onEntityTakeDamage', 1)[0]
        self.api = LuaRuntime(unpack_returned_tuples=True).execute('''
            local mod={}
            local automatic,controllerEnabled=true,true
            local lastActionFrame,lastControlMessageAt=100,100
            local gridEscapeActive,bombRetreatActive,ghostBombRetreatActive=false,false,false
            local combatLiveAim=nil
            local utilityButtons={[1]=true,[2]=true,[3]=true,[4]=true}
            local charge,sharp,maxCharges,item=4,true,4,45
            ButtonAction={ACTION_ITEM=1,ACTION_PILLCARD=2,ACTION_DROP=3,ACTION_BOMB=4}
            InputHook={GET_ACTION_VALUE=0,IS_ACTION_PRESSED=1,IS_ACTION_TRIGGERED=2}
            CollectibleType={COLLECTIBLE_SHARP_PLUG=205}
            local player={HasCollectible=function(_,kind) return sharp and kind==205 end,
                GetActiveItem=function() return item end,
                GetActiveCharge=function() return charge end}
            -- MC_INPUT_ACTION provides Entity userdata; only its ToPlayer()
            -- result has player-specific methods in the real engine.
            local entity={ToPlayer=function() return player end}
            game={GetFrameCount=function() return 100 end}
            Isaac={GetTime=function() return 100 end,
                GetItemConfig=function() return {GetCollectible=function() return {MaxCharges=maxCharges} end} end}
        ''' + helper + '''
            return {query=function(hook,button) return mod:onInput(entity,hook,button or 1) end,
                spent=function(value) charge=value end,
                owned=function(value) sharp=value end,
                max=function(value) maxCharges=value end}
        ''')

    def test_same_frame_requery_cannot_pay_health_after_native_use(self):
        self.assertEqual(self.api.query(0), 1)
        self.assertTrue(self.api.query(2))
        self.api.spent(0)  # Native Yum Heart use consumed the full charge.
        self.assertEqual(self.api.query(0), 0)
        self.assertFalse(self.api.query(1))
        self.assertFalse(self.api.query(2))

    def test_recorded_self_damage_state_rejects_the_still_latched_item_pulse(self):
        recorded = json.loads((ROOT / 'tests/fixtures/sharp-plug-same-frame-native113.json').read_text(encoding='utf8'))
        state = recorded['raw_state']
        self.assertEqual(state['active_item'], 45)
        simultaneous = [event for event in state['damage_events']
                        if event['frame'] == recorded['damage_event']['frame']
                        and event['flags'] == recorded['damage_event']['flags']]
        self.assertEqual(len(simultaneous), 4)
        self.api.spent(state['active_charge'])
        for hook in (0, 1, 2):
            self.assertFalse(self.api.query(hook))

    def test_partial_charge_never_pays_and_full_charge_can_heal_normally(self):
        for charge in (0, 1, 2, 3):
            self.api.spent(charge)
            self.assertFalse(self.api.query(2))
        self.api.spent(4)
        self.assertTrue(self.api.query(2))

    def test_charge_guard_preserves_other_consumables_and_free_actives(self):
        self.api.spent(0)
        for button in (2, 3, 4):
            self.assertTrue(self.api.query(2, button))
        self.api.max(0)
        self.assertTrue(self.api.query(2))
        self.api.max(4)
        self.api.owned(False)
        self.assertTrue(self.api.query(2))


if __name__ == '__main__':
    unittest.main()
