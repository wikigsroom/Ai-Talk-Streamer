"""Held active items need continuous input, reserve and release handling."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class HeldActiveTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='function mod:planHeldActive(player)'+source.split('function mod:planHeldActive(player)',1)[1].split('    if frame - lastUtilityFrame < 45 then return end',1)[0]+'end'
        self.api=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end}
            local mod={}
            local utilityButtons,utilityResult={},'idle'
            local frame,lastUtilityFrame=100,100
            local entities={}
            EntityType={ENTITY_PROJECTILE=9}
            CollectibleType={COLLECTIBLE_SPIN_TO_WIN=655}
            ButtonAction={ACTION_ITEM=1}
            TrinketType={TRINKET_MOMS_TOENAIL=16}
            local game={GetFrameCount=function() return frame end,GetRoom=function() return {} end}
            Isaac={GetRoomEntities=function() return entities end}
            local function isCombatEnemy(e) return e.Type==10 end
            local function bombStillLive() return false end
            local player={Position=Vector(0,0),GetMaxTrinkets=function() return 1 end,
                GetTrinket=function() return 0 end}
        '''+helper+'''
            return function(tick,charge,distance,projectile,receding)
                frame=tick
                player.GetActiveItem=function() return 655 end
                player.GetActiveCharge=function() return charge end
                entities=distance and {{Type=projectile and 9 or 10,Position=Vector(distance,0),
                    Velocity=Vector(receding and 5 or -5,0),IsBoss=function() return false end}} or {}
                planUtilityButtons(player)
                return utilityButtons[1]==true
            end
        ''')

    def test_holds_through_one_shot_cooldown_and_can_use_partial_charge(self):
        self.assertTrue(self.api(100,90,150,False,False))
        self.assertTrue(self.api(101,89,150,False,False))
        self.assertTrue(self.api(102,5,150,False,False))
        self.assertFalse(self.api(103,0,150,False,False))
        self.assertFalse(self.api(104,1,150,False,False))
        self.assertTrue(self.api(124,20,150,False,False))

    def test_releases_when_danger_passes_without_spending_charge_on_distant_targets(self):
        self.assertFalse(self.api(100,90,400,False,False))
        self.assertTrue(self.api(101,90,120,False,False))
        self.assertFalse(self.api(102,80,None,False,False))

    def test_incoming_projectiles_can_trigger_defense_but_receding_ones_do_not(self):
        self.assertFalse(self.api(100,90,100,True,True))
        self.assertTrue(self.api(101,90,100,True,False))


if __name__=='__main__': unittest.main()
