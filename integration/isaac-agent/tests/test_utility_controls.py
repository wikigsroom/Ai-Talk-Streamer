"""Verify consumables use native input and respect health/charge/knowledge."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/python-libs"))
from lupa.lua53 import LuaRuntime


class UtilityControlTests(unittest.TestCase):
    def setUp(self):
        source = (ROOT / "mods/IsaacJev/main.lua").read_text(encoding="utf8")
        helper = "function mod:planHeldActive(player)" + source.split("function mod:planHeldActive(player)",1)[1].split("function mod:onUpdate()",1)[0]
        self.api = LuaRuntime(unpack_returned_tuples=True).execute("""
            local utilityButtons,lastUtilityFrame,utilityResult,pillUseResult={},-10000,'idle','idle'
            local mod={}
            local lastPyroHealFrame=-10000
            local pyroHealPending=false
            local frame=100
            local identified,effect=true,5
            local combatCount,bossFight,roomClear=0,false,true
            local vulnerable=true
            local enemyType=10
            EntityType={ENTITY_MOM=45,ENTITY_MOMS_HEART=78}
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end}
            local recoilSafe=true
            local enemyY=280
            local enemyX=300
            local fireDirection={X=1,Y=0,Length=function(v) return math.sqrt(v.X*v.X+v.Y*v.Y) end}
            local function safeMoveCandidate() return recoilSafe end
            local floor,roomType=1,1
            RoomType={ROOM_BOSS=5}
            ButtonAction={ACTION_ITEM=1,ACTION_PILLCARD=2,ACTION_DROP=3,ACTION_BOMB=4}
            TrinketType={TRINKET_MOMS_TOENAIL=16}
            CollectibleType={COLLECTIBLE_YUM_HEART=45,COLLECTIBLE_BOOK_OF_REVELATIONS=78,COLLECTIBLE_BOOK_OF_SHADOWS=58,
                COLLECTIBLE_MONSTER_MANUAL=123,COLLECTIBLE_PYROMANIAC=223,COLLECTIBLE_HOURGLASS=66,
                COLLECTIBLE_CRYSTAL_BALL=158,COLLECTIBLE_BOOK_OF_SIN=97,COLLECTIBLE_WE_NEED_TO_GO_DEEPER=84}
            PillEffect={PILLEFFECT_FULL_HEALTH=5,PILLEFFECT_BALLS_OF_STEEL=2}
            Card={CARD_JOKER=31,CARD_WORLD=22,CARD_ERA_WALK=54,CARD_SUN=20,CARD_HIEROPHANT=6,CARD_LOVERS=7,CARD_JUSTICE=9,CARD_MAGICIAN=2,CARD_CHARIOT=8,
                CARD_DIAMONDS_2=24,CARD_CLUBS_2=23,CARD_SPADES_2=25,CARD_HEARTS_2=26}
            local pool={IsPillIdentified=function() return identified end,GetPillEffect=function() return effect end}
            game={GetLevel=function() return {GetStage=function() return floor end} end,
                GetFrameCount=function() return frame end,GetRoom=function() return {IsClear=function() return roomClear end,GetType=function() return roomType end} end,
                GetItemPool=function() return pool end}
            Isaac={GetRoomEntities=function()
                    local entities={}
                    for i=1,combatCount do entities[i]={Type=enemyType,IsBoss=function() return bossFight end,Position=Vector(enemyX,enemyY),
                        ToNPC=function(e) return e end,IsVulnerableEnemy=function() return vulnerable end} end
                    return entities
                end,
                GetItemConfig=function() return {GetCollectible=function(_,item)
                    return {MaxCharges=item==352 and 110 or item==507 and 300 or item==295 and 0 or (item==58 and 3 or ((item==123 or item==84) and 6 or (item==66 and 2 or 4)))}
                end} end}
            local function bombStillLive() return false end
            local function healingRoomSafe() return true end
            local function isCombatEnemy() return true end
            local function bossExitInfo() return false end
        """ + helper + """
            return {route=function(stage,kind) RUN_TARGET='satan';floor,roomType=stage,kind end,
                npc=function(kind) enemyType=kind end,
                enemyPosition=function(x,y) enemyX,enemyY=x,y end,
                vulnerable=function(value) vulnerable=value end,
                cannon=function(aimX,aimY,targetY,safe) fireDirection.X,fireDirection.Y=aimX,aimY;enemyY,recoilSafe=targetY,safe end,
                choose=function(item,charge,red,pill,known,pillEffect,card,enemies,isBoss,trinket,clear,pyro,bombs,atFrame,coins,keys,speed)
                identified,effect,lastUtilityFrame=known,pillEffect,-10000
                combatCount,bossFight=enemies or 0,isBoss or false
                roomClear=clear~=false
                frame=atFrame or 100
                local p={Position=Vector(100,280),GetMaxHearts=function() return 6 end,GetHearts=function() return red end,
                    Velocity={Length=function() return speed or 0 end},
                    GetActiveItem=function() return item end,GetActiveCharge=function() return charge end,
                    GetSoulHearts=function() return 0 end,GetEternalHearts=function() return 0 end,
                    GetPill=function() return pill end,GetCard=function() return card end,
                    HasCollectible=function(_,kind) return pyro==true and kind==223 end,
                    GetNumBombs=function() return bombs or 0 end,
                    GetNumCoins=function() return coins or 0 end,GetNumKeys=function() return keys or 0 end,
                    GetMaxTrinkets=function() return 1 end,GetTrinket=function() return trinket or 0 end}
                planUtilityButtons(p)
                return utilityButtons[1]==true,utilityButtons[2]==true
            end,drop=function() return utilityButtons[3]==true end,
            heal=function() return utilityButtons[4]==true end,
            pending=function() return pyroHealPending end}
        """)

    def test_healing_active_requires_charge_and_missing_health(self):
        self.assertEqual(self.api.choose(45,4,2,0,True,5,0),(True,False))
        self.assertEqual(self.api.choose(45,3,2,0,True,5,0),(False,False))
        self.assertEqual(self.api.choose(45,4,6,0,True,5,0),(False,False))

    def test_owned_bible_uses_its_mom_and_heart_effect_but_never_targets_satan(self):
        for stage,kind in ((6,45),(8,78)):
            self.api.route(stage,5);self.api.npc(kind)
            self.assertEqual(self.api.choose(33,4,6,0,True,5,0,1,True),(True,False))
            self.assertEqual(self.api.choose(33,3,6,0,True,5,0,1,True),(False,False))
            self.assertEqual(self.api.choose(33,4,6,0,True,5,0,0,False),(False,False))
        self.api.route(10,5)
        for kind in (84,45,78):
            self.api.npc(kind)
            self.assertEqual(self.api.choose(33,4,2,0,True,5,0,1,True),(False,False))

    def test_owned_sharp_straw_uses_timed_charge_only_against_vulnerable_enemies(self):
        self.assertEqual(self.api.choose(507,300,6,0,True,5,0,1),(True,False))
        self.assertEqual(self.api.choose(507,299,6,0,True,5,0,1),(False,False))
        self.assertEqual(self.api.choose(507,300,6,0,True,5,0,0),(False,False))
        self.api.vulnerable(False)
        self.assertEqual(self.api.choose(507,300,6,0,True,5,0,3,True),(False,False))

    def test_existing_cannon_requires_charge_live_aim_target_and_safe_recoil(self):
        self.assertEqual(self.api.choose(352,110,6,0,True,5,0,1,True),(True,False))
        self.assertEqual(self.api.choose(352,109,6,0,True,5,0,1,True),(False,False))
        self.assertEqual(self.api.choose(352,110,6,0,True,5,0,0),(False,False))
        self.api.cannon(0,0,280,True)
        self.assertEqual(self.api.choose(352,110,6,0,True,5,0,1,True),(False,False))
        self.api.cannon(1,0,350,True)
        self.assertEqual(self.api.choose(352,110,6,0,True,5,0,1,True),(False,False))
        self.api.cannon(1,0,280,False)
        self.assertEqual(self.api.choose(352,110,6,0,True,5,0,1,True),(False,False))
        self.api.cannon(1,0,280,True)
        self.api.vulnerable(False)
        self.assertEqual(self.api.choose(352,110,6,0,True,5,0,1,True),(False,False))

    def test_held_defense_does_not_suppress_emergency_healing_cards(self):
        self.api.enemyPosition(200,280)
        self.assertEqual(self.api.choose(655,90,2,0,True,5,20,1,True),(True,True))

    def test_charged_defense_is_not_reserved_while_a_small_fight_can_kill_player(self):
        self.assertEqual(self.api.choose(58,3,2,0,True,5,0,1,False,0,False),(True,False))
        self.assertEqual(self.api.choose(58,3,4,0,True,5,0,2,False,0,False),(True,False))
        self.assertEqual(self.api.choose(58,2,2,0,True,5,0,1,False,0,False),(False,False))
        self.assertEqual(self.api.choose(58,3,2,0,True,5,0,0,False,0,True),(False,False))
        self.assertEqual(self.api.choose(58,3,6,0,True,5,0,1,False,0,False),(False,False))

    def test_doubling_heal_can_prevent_death_in_combat_but_waits_with_small_injury(self):
        self.assertEqual(self.api.choose(0,0,2,0,True,5,26,3,False,0,False),(False,True))
        self.assertEqual(self.api.choose(0,0,4,0,True,5,26,3,False,0,False),(False,False))
        self.assertEqual(self.api.choose(0,0,6,0,True,5,26,3,True,0,False),(False,False))

    def test_coin_active_requires_real_coins_and_vulnerable_targets_without_charge(self):
        self.assertEqual(self.api.choose(295,0,6,0,True,5,0,3,False,0,False,False,0,100,2),(True,False))
        self.assertEqual(self.api.choose(295,0,6,0,True,5,0,3,False,0,False,False,0,100,0),(False,False))
        self.assertEqual(self.api.choose(295,0,6,0,True,5,0,0,False,0,True,False,0,100,2),(False,False))
        self.api.vulnerable(False)
        self.assertEqual(self.api.choose(295,0,6,0,True,5,0,1,True,0,False,False,0,100,2),(False,False))
        self.api.vulnerable(True)
        self.assertEqual(self.api.choose(295,0,2,0,True,5,26,3,True,0,False,False,0,100,2),(False,True))

    def test_owned_joker_is_reserved_for_after_heart_and_precedes_healing_utility(self):
        self.api.route(7,5)
        self.assertEqual(self.api.choose(0,0,6,0,True,5,31,0),(False,False))
        self.api.route(8,5)
        self.assertEqual(self.api.choose(45,4,2,0,True,5,31,0),(False,True))
        self.assertEqual(self.api.choose(0,0,6,0,True,5,31,1,True),(False,False))

    def test_owned_shovel_is_used_only_after_heart_when_charged(self):
        self.api.route(7,5)
        self.assertEqual(self.api.choose(84,6,6,0,True,5,0,0),(False,False))
        self.api.route(8,5)
        self.assertEqual(self.api.choose(84,6,6,0,True,5,0,0),(True,False))
        self.assertEqual(self.api.choose(84,5,6,0,True,5,0,0),(False,False))
        self.assertEqual(self.api.choose(84,0,6,0,True,5,0,0),(False,False))

    def test_homing_and_invulnerability_cards_are_used_for_dangerous_fights(self):
        for card in (2,8,54,50):
            self.assertEqual(self.api.choose(0,0,6,0,True,5,card,1,True),(False,True))
            self.assertEqual(self.api.choose(0,0,2,0,True,5,card,1,False),(False,True))
            self.assertEqual(self.api.choose(0,0,6,0,True,5,card,0,False),(False,False))

    def test_resource_card_waits_for_clear_room_and_owned_resource_actives_use_charge(self):
        for card in (9,22):
            self.assertEqual(self.api.choose(0,0,6,0,True,5,card,0,False),(False,True))
        self.assertEqual(self.api.choose(0,0,6,0,True,5,9,2,False),(False,False))
        for active in (97,158):
            self.assertEqual(self.api.choose(active,4,6,0,True,5,0),(True,False))
            self.assertEqual(self.api.choose(active,0,6,0,True,5,0),(False,False))

    def test_unknown_pill_is_not_used_even_when_effect_would_be_good(self):
        self.assertEqual(self.api.choose(0,0,2,1,False,5,0),(False,False))
        self.assertEqual(self.api.choose(0,0,2,1,True,5,0),(False,True))

    def test_known_bad_pill_is_kept(self):
        self.assertEqual(self.api.choose(0,0,2,1,True,1,0),(False,False))

    def test_monster_manual_uses_charge_in_hard_fights(self):
        self.assertEqual(self.api.choose(123,6,6,0,True,5,0,3,False),(True,False))
        self.assertEqual(self.api.choose(123,5,6,0,True,5,0,3,False),(False,False))
        self.assertEqual(self.api.choose(123,6,6,0,True,5,0,2,False),(False,False))
        self.assertEqual(self.api.choose(123,6,6,0,True,5,0,1,True),(True,False))

    def test_charged_hourglass_is_used_in_hard_fights(self):
        self.assertEqual(self.api.choose(66,2,6,0,True,5,0,3,False),(True,False))
        self.assertEqual(self.api.choose(66,1,6,0,True,5,0,3,False),(False,False))
        self.assertEqual(self.api.choose(66,2,6,0,True,5,0,1,True),(True,False))

    def test_dangerous_trinket_is_dropped_only_in_a_safe_clear_room(self):
        self.api.choose(0,0,6,0,True,5,0,0,False,16,True)
        self.assertTrue(self.api.drop())
        self.api.choose(0,0,6,0,True,5,0,1,False,16,False)
        self.assertFalse(self.api.drop())
        self.api.choose(0,0,6,0,True,5,0,0,False,16+32768,True)
        self.assertTrue(self.api.drop())

    def test_dangerous_trinket_and_cannon_are_not_offered_as_new_upgrades(self):
        source = (ROOT / "mods/IsaacJev/main.lua").read_text(encoding="utf-8")
        # This replay needs only pickupTable, not the next mod-scoped method.
        helper = "local function pickupTable(entity)" + source.split("local function pickupTable(entity)",1)[1].split("\nend\n",1)[0] + "\nend\n"
        choose = LuaRuntime().execute("""
            PickupVariant={PICKUP_TRINKET=350,PICKUP_COLLECTIBLE=100}
            TrinketType={TRINKET_MOMS_TOENAIL=16}
            Isaac={GetItemConfig=function() return {GetTrinket=function() return {Name='safe trinket'} end} end}
            game={GetRoom=function() return {GetGridIndex=function() return 1 end} end}
            local function vectorTable() return {x=1,y=1} end
        """ + helper + """
            return function(subtype,variant)
                return pickupTable({Variant=variant or 350,SubType=subtype,Index=1,Position={},
                    ToPickup=function() return {Price=0} end})
            end
        """)
        self.assertIsNone(choose(16))
        self.assertIsNone(choose(16+32768))
        self.assertEqual(choose(2)['kind'], 'trinket')
        self.assertIsNone(choose(352,100))
        self.assertIsNone(choose(474,100))
        self.assertIsNone(choose(273,100))

    def test_pyromaniac_healing_requires_owned_item_clear_room_and_bomb_reserve(self):
        self.api.choose(0,0,2,0,True,5,0,0,False,0,True,False,3,100)
        self.assertFalse(self.api.heal())

        self.api.choose(0,0,2,0,True,5,0,0,False,0,True,True,1,100)
        self.assertFalse(self.api.heal())
        self.api.choose(0,0,2,0,True,5,0,1,False,0,False,True,3,100)
        self.assertFalse(self.api.heal())
        self.api.choose(0,0,2,0,True,5,0,0,False,0,True,True,3,100)
        self.assertTrue(self.api.heal())
        self.api.choose(0,0,2,0,True,5,0,0,False,0,True,True,3,150)
        self.assertFalse(self.api.heal())

    def test_resource_cards_are_used_with_meaningful_resources_in_clear_rooms(self):
        for card,coins,keys,bombs in ((24,13,0,0),(23,0,0,3),(25,0,3,0),(26,0,0,0)):
            self.assertEqual(self.api.choose(0,0,4,0,True,5,card,0,False,0,True,False,bombs,100,coins,keys),(False,True))
            self.assertEqual(self.api.choose(0,0,4,0,True,5,card,1,False,0,False,False,bombs,100,coins,keys),(False,False))
        self.assertEqual(self.api.choose(0,0,6,0,True,5,24,0,False,0,True,False,0,100,0,0),(False,False))

    def test_healing_bomb_waits_until_native_movement_stops(self):
        self.api.choose(0,0,2,0,True,5,0,0,False,0,True,True,3,100,0,0,4)
        self.assertTrue(self.api.pending())
        self.assertFalse(self.api.heal())
        self.api.choose(0,0,2,0,True,5,0,0,False,0,True,True,3,101,0,0,0.1)
        self.assertTrue(self.api.heal())

    def test_owned_pyromaniac_can_restore_the_final_missing_half_heart(self):
        self.api.choose(0,0,5,0,True,5,0,0,False,0,True,True,3,100)
        self.assertTrue(self.api.heal())
        self.api.choose(0,0,6,0,True,5,0,0,False,0,True,True,3,250)
        self.assertFalse(self.api.heal())


if __name__ == "__main__":
    unittest.main()
