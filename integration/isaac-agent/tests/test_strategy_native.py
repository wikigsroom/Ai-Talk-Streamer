"""Execute the native input module with engine-like state changes, not source assertions."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime

class NativeStrategyTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
          now,frame,paused=1000,100,false
          charge,item,coins,hearts,maximum,soul=6,34,3,8,8,4
          enemies={}
          ButtonAction={ACTION_ITEM=1,ACTION_PILLCARD=2,ACTION_DROP=3,ACTION_BOMB=4,ACTION_PAUSE=18}
          InputHook={GET_ACTION_VALUE=0,IS_ACTION_PRESSED=1,IS_ACTION_TRIGGERED=2}
          RoomType={ROOM_SACRIFICE=13,ROOM_DICE=20}
          Isaac={GetTime=function() return now end,GetRoomEntities=function() return enemies end,
            GetItemConfig=function() return {GetCollectible=function() return {MaxCharges=6} end} end}
          game={GetFrameCount=function() return frame end,IsPaused=function() return paused end,
            GetSeeds=function() return {GetStartSeed=function() return 123 end} end,
            GetLevel=function() return {GetStage=function() return 1 end,GetStageType=function() return 0 end,
                GetCurrentRoomIndex=function() return 97 end} end,
            GetRoom=function() return {GetType=function() return 13 end} end}
          player={GetActiveItem=function() return item end,GetActiveCharge=function() return charge end,
            GetBatteryCharge=function() return 0 end,GetNumCoins=function() return coins end,
            GetMaxHearts=function() return maximum end,GetHearts=function() return hearts end,
            GetSoulHearts=function() return soul end,GetBoneHearts=function() return 0 end,
            GetPlayerType=function() return 0 end,GetCard=function() return 22 end,GetPill=function() return 0 end}
        ''')
        module=self.lua.execute((ROOT/'mods/IsaacJev/strategy_control.lua').read_text(encoding='utf8'))
        self.control=module.new(self.lua.globals().game)
    def accept(self,op='use_active',**fields):
        data={'plan_id':'one','op':op,'slot':0,'id':int(self.lua.globals().item),**fields}
        self.control.accept(self.control,self.lua.table_from({'owned':True,'lease_ms':1500,'command':self.lua.table_from(data)}),self.lua.globals().player)
    def filter(self):
        buttons=self.lua.table_from({1:True,2:True,3:True,4:True})
        self.control.filterButtons(self.control,self.lua.globals().player,buttons)
        return buttons
    def test_same_frame_charge_consumption_stops_all_later_item_queries(self):
        self.accept();self.assertTrue(self.filter()[1]);self.lua.globals().charge=0
        self.assertFalse(self.control.utilityAllowed(self.control,self.lua.globals().player,1))
    def test_coin_item_cannot_pay_twice_in_same_frame(self):
        self.lua.globals().item=295;self.accept();self.assertTrue(self.filter()[1])
        self.lua.globals().coins=2
        self.assertFalse(self.control.utilityAllowed(self.control,self.lua.globals().player,1))
    def test_expired_lease_and_manual_input_time_are_not_replayed(self):
        self.accept();self.lua.globals().now=3000
        self.assertFalse(self.filter()[1]);self.assertFalse(self.filter()[2])
    def test_duplicate_command_cannot_rearm_next_frame(self):
        self.accept();self.lua.globals().frame=101;self.accept()
        self.assertFalse(self.filter()[1])
    def test_bible_fatal_boss_is_vetoed_at_the_game_boundary(self):
        self.lua.globals().item=33
        self.lua.execute('enemies={{Type=84,ToNPC=function() return {} end}}')
        self.accept();self.assertFalse(self.filter()[1]);self.assertEqual(self.control.ack.status,'rejected')
    def test_pause_ack_requires_observed_engine_pause(self):
        self.control.requestPause(self.control,'pause-1');self.control.render(self.control)
        self.assertIsNone(self.control.pauseAck)
        self.assertTrue(self.control.pauseInput(self.control,1,18))
        self.lua.globals().paused=True;self.control.render(self.control)
        self.assertTrue(self.control.pauseAck.paused)
        self.assertIsNone(self.control.pauseInput(self.control,1,18))

    def test_combat_pocket_is_vetoed_if_room_clears_before_the_native_query(self):
        self.lua.execute('game.GetRoom=function() return {GetType=function() return 13 end,IsClear=function() return true end} end')
        self.accept('use_pocket',kind='card',id=22,combat_required=True)
        self.assertFalse(self.filter()[2])
        self.assertFalse(self.control.utilityAllowed(self.control,self.lua.globals().player,2))
        self.assertEqual(self.control.ack.status,'rejected')
    def test_sacrifice_allows_exactly_one_observed_payment(self):
        key=self.control.key(self.control);self.control.sacrificeKnown[key]=True;self.control.sacrificeCounts[key]=2
        guard=self.lua.table_from({'count':2})
        self.accept('sacrifice_once',grid_index=97,guard=guard)
        self.assertTrue(self.control.macroAllowed(self.control,97,self.lua.globals().player))
        self.control.sacrificeCounts[key]=3
        self.assertFalse(self.control.macroAllowed(self.control,97,self.lua.globals().player))
        self.assertFalse(self.control.macroAllowed(self.control,98,self.lua.globals().player))

    def test_lost_controller_requests_normal_pause_without_unpausing(self):
        self.accept();self.lua.globals().now=3000;self.control.render(self.control)
        self.assertIsNone(self.control.pauseRequest)
        self.lua.globals().now=6501;self.control.render(self.control)
        self.assertEqual(self.control.pauseRequest.id,'controller-lease-expired')
        self.lua.globals().paused=True;self.control.render(self.control)
        self.assertTrue(self.control.pauseAck.paused);self.assertIsNone(self.control.pauseRequest)

    def test_dice_floor_is_blocked_until_matching_live_entity_is_authorized(self):
        self.lua.execute('''
          EntityType={ENTITY_EFFECT=1000};EffectVariant={DICE_FLOOR=76}
          game.GetRoom=function() return {GetType=function() return 20 end,GetGridIndex=function() return 97 end} end
          dice={Type=1000,Variant=76,SubType=3,Index=77,InitSeed=777,Position={X=320,Y=280},Size=40}
          enemies={dice}
        ''')
        dice=self.lua.globals().dice;player=self.lua.globals().player
        self.assertGreaterEqual(self.control.effectObstacle(self.control,dice,player),72)
        self.accept('trigger_dice',grid_index=97,guard=self.lua.table_from({'dice':self.lua.table_from({'entity_id':77,'spawn_seed':777,'face':4})}))
        self.assertIsNone(self.control.effectObstacle(self.control,dice,player))
        dice.InitSeed=778
        self.assertGreaterEqual(self.control.effectObstacle(self.control,dice,player),72)

    def test_unapproved_pickup_is_blocked_even_during_combat_or_after_lease_loss(self):
        self.accept()
        collider=self.lua.eval('{ToPlayer=function() return player end}')
        pickup=self.lua.table_from({'Index':7})
        self.assertTrue(self.control.pickupCollision(self.control,pickup,collider))
        self.lua.globals().now=3000
        self.assertTrue(self.control.pickupCollision(self.control,pickup,collider))
        self.control.manualOverride=True
        self.assertIsNone(self.control.pickupCollision(self.control,pickup,collider))

    def test_one_use_zero_charge_diplopia_is_pulsed_once(self):
        self.lua.globals().item=347;self.lua.globals().charge=0;self.accept()
        self.assertTrue(self.filter()[1]);self.lua.globals().item=0
        self.assertFalse(self.control.utilityAllowed(self.control,self.lua.globals().player,1))

if __name__=='__main__':unittest.main()
