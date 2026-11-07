"""Both Python planning and the native input guard must allow a real Sheol route."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class NativeSheolDoorTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf-8')
        function='local function tryEnterSelectedDoor(player)'+source.split('local function tryEnterSelectedDoor(player)',1)[1].split('    -- A late JEV response',1)[0]+'return false end'
        obstacle='local function contactObstacle(entity, player)'+source.split('local function contactObstacle(entity, player)',1)[1].split('local function playerIsDead',1)[0]
        self.api=LuaRuntime(unpack_returned_tuples=True).execute('''
            local RUN_TARGET="satan"
            RoomType={ROOM_DEVIL=14,ROOM_SECRET=7,ROOM_SUPERSECRET=8,ROOM_TREASURE=4,ROOM_SHOP=2,ROOM_LIBRARY=12}
            EntityType={ENTITY_PICKUP=5,ENTITY_EFFECT=1000}
            PickupVariant={PICKUP_BIGCHEST=340,PICKUP_COLLECTIBLE=100}
            Card={CARD_JOKER=31}
            EffectVariant={MOM_FOOT_STOMP=29}
            local stage,opened,locked,kind=8,true,false,14
            local door={TargetRoomIndex=-1,IsOpen=function() return opened end,IsLocked=function() return locked end}
            local level={GetStage=function() return stage end,GetRoomByIdx=function() return nil end}
            local room={GetDoor=function(_,slot) if slot==0 then return door end end}
            local game={GetLevel=function() return level end,GetRoom=function() return room end,GetFrameCount=function() return 100 end}
            local action={mode="navigate",id="enter_door_0",sourceRoomIndex=83,targetRoomIndex=-1}
            local lastActionFrame=100
            local function hasCombatEnemy() return false end
            local function currentDimension() return 0 end
            local function canonicalRoomIndex() return 83 end
        '''+function+'\n'+obstacle+'''
            return {check=function(floor,isOpen,isLocked,targetType)
                stage,opened,locked=floor,isOpen,isLocked
                door.TargetRoomType=targetType
                return tryEnterSelectedDoor({GetNumKeys=function() return 2 end}),transitionGate
            end,chest=function(floor,isOpen,targetType)
                stage,opened=floor,isOpen;door.TargetRoomType=targetType
                return contactObstacle({Type=5,Variant=340},{Size=10})
            end}
        ''')

    def test_open_unlocked_devil_door_is_accepted_on_heart_floor(self):
        blocked,reason=self.api.check(8,True,False,14)
        self.assertFalse(blocked)
        self.assertNotEqual(reason,'door_target_missing')

    def test_unrelated_and_unverified_negative_doors_remain_blocked(self):
        for args in [(1,True,False,14),(8,False,False,14),(8,True,True,14),(8,True,False,1)]:
            self.assertTrue(self.api.check(*args)[0])

    def test_natural_early_devil_offer_can_be_entered_without_a_teleport(self):
        for stage in (2,3,6,7):
            self.assertFalse(self.api.check(stage,True,False,14)[0])

    def test_ending_chest_is_an_obstacle_only_when_a_sheol_route_exists(self):
        self.assertEqual(self.api.chest(8,True,14),(48,'ending_chest'))
        for args in [(6,True,14),(8,False,14),(8,True,1)]:
            self.assertIsNone(self.api.chest(*args))


if __name__=='__main__': unittest.main()
