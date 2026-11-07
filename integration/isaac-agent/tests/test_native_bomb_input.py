"""Plant through ordinary input and observe the engine's actual bomb/inventory."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class NativeBombInputTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        planting='function mod:observeBombInput(player)'+source.split('function mod:observeBombInput(player)',1)[1].split('local function tryEnterSelectedDoor',1)[0]
        inputs='function mod:onInput('+source.split('function mod:onInput(',1)[1].split('function mod:onEntityTakeDamage',1)[0]
        self.api=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local mod={}
            local frame,inventory,golden,roomKey=100,2,false,'room71'
            local entities={}
            local automatic,controllerEnabled,manualOverride=true,true,false
            local lastActionFrame,lastControlMessageAt=100,100
            local utilityButtons={}
            local resolvedMove=Vector(1,0)
            local bombPlaced,bombPlacedFrame,bombPosition,bombEntity=false,-1,nil,nil
            local bombTargetId,bombPlacementDistance,bombRoomKey=-1,-1,''
            local bombRetreatDirection=Vector(1,0)
            local bombedWallKeys={}
            local bombError=nil
            local action={id='bomb_secret_2',mode='bomb_wall',sourceRoomIndex=71,bombSite=Vector(520,280)}
            EntityType={ENTITY_BOMB=4,ENTITY_PLAYER=1}
            ButtonAction={ACTION_ITEM=1,ACTION_PILLCARD=2,ACTION_DROP=3,ACTION_BOMB=4}
            InputHook={GET_ACTION_VALUE=0,IS_ACTION_PRESSED=1,IS_ACTION_TRIGGERED=2}
            CollectibleType={COLLECTIBLE_SHARP_PLUG=205}
            local player={Index=0,Type=1,Position=Vector(520,280),Velocity=Vector(0,0),
                GetNumBombs=function() return inventory end,HasGoldenBomb=function() return golden end,
                FireBomb=function() error('Direct creation must never be called') end,
                AddBombs=function() error('Inventory must belong to the engine') end}
            local entity={ToPlayer=function() return player end}
            local function currentRoomKey() return roomKey end
            local function canonicalRoomIndex() return 71 end
            local combat=false
            local function hasCombatEnemy() return combat end
            local function liveGridHazardKind() return 'passage_rock' end
            local function bombOnlyFireKind() return false end
            local function bombEscapeDirection() return Vector(-1,0) end
            local function actualDoorPosition() return Vector(580,280) end
            local room={IsDoorSlotAllowed=function() return true end,
                GetDoor=function() return nil end,GetCenterPos=function() return Vector(320,280) end}
            game={GetFrameCount=function() return frame end,GetLevel=function() return {} end,
                GetRoom=function() return room end}
            Isaac={GetRoomEntities=function() return entities end,GetTime=function() return 100 end}
        '''+planting+inputs+'''
            return {request=function(speed)
                player.Velocity=Vector(speed or 0,0)
                tryDropBomb(player)
                return utilityButtons[4]==true,mod.pendingBombInput~=nil,bombPlaced,resolvedMove.X,resolvedMove.Y
            end,input=function(hook) return mod:onInput(entity,hook,4) end,
            spawn=function(owner,id,remaining)
                inventory=remaining
                entities[#entities+1]={Type=4,Index=id,SpawnerType=owner,
                    SpawnerEntity={Type=owner,Index=owner==1 and 0 or 20},Position=Vector(515,285)}
            end,observe=function()
                mod:observeBombInput(player)
                return bombPlaced,mod.pendingBombInput~=nil,utilityButtons[4]==true,
                    bombPosition and bombPosition.X,bombPosition and bombPosition.Y
            end,golden=function() golden=true;inventory=0 end,
            inventory=function() return inventory end,
            tick=function(n) frame=frame+n end,
            room=function(value) roomKey=value end,
            passage=function(clear,enemies)
                combat=enemies
                action={id='bomb_hazard_-100052',mode='bomb',sourceRoomIndex=71,bombSite=Vector(260,240)}
                player.Position=Vector(260,240)
                room.GetGridSize=function() return 53 end
                room.GetGridEntity=function() return {Position=Vector(320,240)} end
                room.IsClear=function() return clear end
            end}
        ''')

    def test_recorded_moving_plant_brakes_without_generating_or_spending(self):
        rows=json.loads((ROOT/'tests/fixtures/stage6-bomb-contact-native118.json').read_text(encoding='utf8'))
        before=rows[0]['player']['vel']
        speed=(before['x']**2+before['y']**2)**.5
        self.assertGreater(speed,.25)
        self.assertEqual(self.api.request(speed),(False,False,False,0,0))
        self.assertEqual(self.api.inventory(),2)

    def test_native_spawn_confirms_placement_and_requery_does_not_spend_a_second_bomb(self):
        self.assertEqual(self.api.request(0),(True,True,False,0,0))
        self.assertEqual(self.api.input(0),1)
        self.assertTrue(self.api.input(2))
        self.api.spawn(1,90,1)  # Simulate the engine's own resource use.
        self.assertFalse(self.api.input(2))
        self.assertEqual(self.api.input(0),0)
        self.assertEqual(self.api.observe(),(True,False,False,515,285))
        self.assertEqual(self.api.inventory(),1)

    def test_golden_bomb_pulse_stops_after_actual_spawn_without_inventory_change(self):
        self.api.golden()
        self.assertTrue(self.api.request(0)[0])
        self.api.spawn(1,90,0)
        self.assertFalse(self.api.input(2))
        self.assertTrue(self.api.observe()[0])

    def test_enemy_or_preexisting_bomb_does_not_confirm_the_players_plant(self):
        self.api.spawn(1,50,2)
        self.api.request(0)
        self.assertFalse(self.api.observe()[0])
        self.api.spawn(9,51,2)
        self.assertFalse(self.api.observe()[0])
        self.api.spawn(1,52,1)
        self.assertTrue(self.api.observe()[0])

    def test_missing_spawn_and_changed_room_cancel_without_fake_placement(self):
        self.api.request(0)
        self.api.tick(13)
        self.assertEqual(self.api.observe()[:3],(False,False,False))
        self.assertEqual(self.api.inventory(),2)
        self.api.request(0)
        self.api.room('other_room')
        self.assertEqual(self.api.observe()[:3],(False,False,False))

    def test_clear_room_passage_rock_uses_the_same_normal_bomb_input(self):
        self.api.passage(True,False)
        self.assertTrue(self.api.request(0)[0])
        self.assertEqual(self.api.input(0),1)
        self.assertEqual(self.api.inventory(),2)

    def test_stale_passage_bomb_cannot_plant_during_live_combat(self):
        self.api.passage(True,True)
        self.assertFalse(self.api.request(0)[0])


if __name__=='__main__':unittest.main()
