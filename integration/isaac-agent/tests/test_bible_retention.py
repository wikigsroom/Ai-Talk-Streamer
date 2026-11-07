"""An owned Mom/Heart utility should survive unrelated active pedestal offers."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class BibleRetentionTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='function mod:keepProgressionActive('+source.split('function mod:keepProgressionActive(',1)[1].split('local function pickupTable',1)[0]
        self.api=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mod={}
            local RUN_TARGET='satan'
            RoomType={ROOM_BOSS=5};ItemType={ITEM_ACTIVE=3}
            local stage,clear,boss,held,itemType=1,false,false,33,3
            game={GetLevel=function() return {GetStage=function() return stage end} end,
                GetRoom=function() return {GetType=function() return boss and 5 or 1 end,IsClear=function() return clear end} end}
            Isaac={GetItemConfig=function() return {GetCollectible=function() return {Type=itemType} end} end}
        '''+helper+'''
            return function(floor,cleared,isBoss,current,incomingType,subtype)
                stage,clear,boss,held,itemType=floor,cleared,isBoss,current,incomingType
                return mod:keepProgressionActive({GetActiveItem=function() return held end},subtype or 295)
            end
        ''')

    def test_unrelated_active_cannot_discard_bible_before_heart(self):
        for stage in range(1,9):
            self.assertTrue(self.api(stage,False,False,33,3))

    def test_passive_upgrades_and_other_held_actives_are_not_blocked(self):
        self.assertFalse(self.api(6,False,False,33,1,1))
        self.assertFalse(self.api(6,False,False,295,3,33))
        self.assertFalse(self.api(6,False,False,33,3,33))

    def test_bible_can_be_replaced_after_heart_or_in_sheol(self):
        self.assertFalse(self.api(8,True,True,33,3))
        self.assertFalse(self.api(10,False,True,33,3))

    def test_shovel_route_is_preserved_until_sheol(self):
        for stage in (2,6,8):
            self.assertTrue(self.api(stage,False,False,84,3,33))
            self.assertTrue(self.api(stage,True,True,84,3,295))
            self.assertFalse(self.api(stage,True,True,84,1,1))
        self.assertFalse(self.api(10,True,True,84,3,295))

    def test_shovel_can_replace_bible_without_blocking_passives(self):
        self.assertFalse(self.api(6,False,False,33,3,84))
        self.assertFalse(self.api(6,False,False,84,1,1))


if __name__=='__main__': unittest.main()
