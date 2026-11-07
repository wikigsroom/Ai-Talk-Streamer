"""Exercise native stomp escape and resource-machine classification."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class ContactHazardTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf-8')
        obstacle='local function contactObstacle(entity, player)'+source.split('local function contactObstacle(entity, player)',1)[1].split('local function playerIsDead',1)[0]
        escape='local function escapeStomp(player)'+source.split('local function escapeStomp(player)',1)[1].split('local function escapeGridDanger',1)[0]
        self.api=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            EntityType={ENTITY_SLOT=6,ENTITY_EFFECT=1000,ENTITY_PROJECTILE=9}
            PickupVariant={PICKUP_COLLECTIBLE=100}
            EffectVariant={MOM_FOOT_STOMP=29}
            local entities={}
            Isaac={GetRoomEntities=function() return entities end}
            local function safeMoveCandidate() return true end
            local function isCombatEnemy() return false end
            local function dangerousCreep(e) return e.Type==1000 and e.Variant==23 end
            local function liveHazardKind() return nil end
            local function bombOnlyFireKind() return false end
            game={GetRoom=function() return {GetGridIndex=function() return 0 end,
                GetGridPath=function() return 0 end} end}
        '''+obstacle+escape+'''
            return {classify=function(kind,variant,subtype,price,selected,state)
                local entity={Type=kind,Variant=variant,SubType=subtype,Size=16,Index=99,State=state}
                if price then entity.ToPickup=function() return {Price=price} end end
                action={id=selected and "take_item_99" or "enter_door_0"}
                return contactObstacle(entity,{Size=10})
            end,escape=function(kind,variant,state)
                entities={{Type=kind or 1000,Variant=variant or 29,State=state,Position=Vector(200,200),Velocity=Vector(0,0)}}
                local move=escapeStomp({Position=Vector(200,200),Size=10})
                if not move then return nil,nil end
                return move.X,move.Y
            end,ending=function(stage,charge)
                RUN_TARGET='satan'
                Card={CARD_JOKER=31}
                game.GetLevel=function() return {GetStage=function() return stage end} end
                game.GetRoom=function() return {GetDoor=function() return nil end} end
                Isaac.GetItemConfig=function() return {GetCollectible=function() return {MaxCharges=6} end} end
                RoomType={ROOM_DEVIL=14}
                local p={Size=10,GetCard=function() return 0 end,
                    GetActiveItem=function() return 84 end,GetActiveCharge=function() return charge end}
                return contactObstacle({Type=5,Variant=340},p)
            end,creep=function(flying)
                entities={{Type=1000,Variant=23,Size=28,Position=Vector(200,200),Velocity=Vector(0,0)}}
                local move=escapeStomp({Position=Vector(200,200),Size=10,CanFly=flying})
                if not move then return nil,nil end
                return move.X,move.Y
            end}
        ''')

    def test_health_and_resource_machines_are_avoided(self):
        for variant in (2,5,7,8):
            radius,kind=self.api.classify(6,variant)
            self.assertGreaterEqual(radius,32)
            self.assertEqual(kind,'interactive_slot')
        self.assertIsNone(self.api.classify(5,350))

    def test_stomp_does_not_leave_player_standing_under_the_foot(self):
        self.assertEqual(self.api.classify(1000,29),(90,'stomp'))
        x,y=self.api.escape()
        self.assertGreater(abs(x)+abs(y),0.9)

    def test_satan_and_mom_npc_feet_escape_only_during_stomps(self):
        for kind,state in ((84,7),(45,6),(45,7)):
            with self.subTest(kind=kind,state=state):
                self.assertEqual(self.api.classify(kind,10,None,None,None,state),(90,'stomp'))
                x,y=self.api.escape(kind,10,state)
                self.assertGreater(abs(x)+abs(y),.9)
        for kind,variant,state in ((84,10,3),(45,10,3),(84,0,7)):
            self.assertIsNone(self.api.classify(kind,variant,None,None,None,state))
            self.assertEqual(self.api.escape(kind,variant,state),(None,None))

    def test_unsupported_remote_tear_item_is_avoided_physically(self):
        for subtype in (168,329,358,233,394,352,474,273):
            with self.subTest(subtype=subtype):
                radius,kind=self.api.classify(5,100,subtype)
                self.assertGreaterEqual(radius,30)
                self.assertEqual(kind,'unsupported_pedestal')
        self.assertIsNone(self.api.classify(5,100,3))

    def test_health_deal_is_not_bought_by_brushing_past_it(self):
        for price in (-1,-2,-3,-4,-5,-6,-7,-8,-9):
            with self.subTest(price=price):
                radius,kind=self.api.classify(5,100,3,price,False)
                self.assertGreaterEqual(radius,32)
                self.assertEqual(kind,'unselected_health_deal')
        self.assertIsNone(self.api.classify(5,100,3,-1000,False))
        self.assertIsNone(self.api.classify(5,100,3,-1,True))
        self.assertIsNone(self.api.classify(5,100,3,0,False))
        self.assertIsNone(self.api.classify(5,100,3,15,False))

    def test_charged_shovel_blocks_accidental_ending_before_its_native_use(self):
        self.assertEqual(self.api.ending(8,6),(48,'ending_chest'))
        self.assertIsNone(self.api.ending(8,5))
        self.assertIsNone(self.api.ending(6,6))

    def test_grounded_player_leaves_creep_while_flying_player_can_ignore_it(self):
        x,y=self.api.creep(False)
        self.assertGreater(abs(x)+abs(y),0.9)
        self.assertEqual(self.api.creep(True),(None,None))


if __name__=='__main__':
    unittest.main()
