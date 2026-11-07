"""Predict in-flight tear ignition instead of walking into the delayed blast."""
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class PendingTntTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/tnt_safety.lua').read_text(encoding='utf8')
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.api=self.lua.execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            EntityType={ENTITY_TEAR=2}
            local Guard=(function()
        '''+source+'''
            end)()
            _Guard=Guard
            return function(px,py,dx,dy,chain,away,blocked,destroyed,expired)
                local guard=Guard.new()
                local room={GetGridSize=function() return chain and 2 or 1 end,
                    GetGridEntity=function(_,i) return i end,
                    GetGridPosition=function(_,i) return Vector(560+i*120,160) end}
                local event=function() return {kind='tnt',active=true} end
                guard:observe(room,{{Type=2,Position=Vector(400,160),Velocity=Vector(away and -8 or 8,0)}},
                    630,'observed-room',event,function() return not blocked end)
                if destroyed then
                    guard:observe(room,{},631,'observed-room',function() return nil end,function() return true end)
                end
                if expired then
                    guard:observe(room,{},730,'observed-room',function() return nil end,function() return true end)
                end
                local p={Position=Vector(px,py)}
                return guard:danger(p),guard:safe(p,p.Position+Vector(dx,dy)),guard:clearance(p,p.Position)
            end
        ''')

    def test_recorded_damage_position_cannot_keep_walking_toward_an_ignited_barrel(self):
        event=json.loads((ROOT/'tests/fixtures/stage1-tnt-damage-native.json').read_text(encoding='utf8'))
        danger,safe,margin=self.api(event['x'],event['y'],28,0,False,False,False,False)
        self.assertTrue(danger)
        self.assertFalse(safe)
        self.assertLess(margin,0)
        self.assertTrue(self.api(event['x'],event['y'],-28,0,False,False,False,False)[1])

    def test_connected_barrel_is_guarded_before_the_first_one_explodes(self):
        self.assertFalse(self.api(680,320,0,-28,True,False,False,False)[1])

    def test_away_or_blocked_tear_does_not_create_phantom_danger(self):
        for away,blocked in ((True,False),(False,True)):
            self.assertFalse(self.api(436,158,28,0,False,away,blocked,False)[0])

    def test_inactive_grid_is_still_guarded_during_the_actual_delayed_blast(self):
        event=json.loads((ROOT/'tests/fixtures/stage3-tnt-damage-native61.json').read_text())
        # Translate the observed barrel at (440,280) to the fixture's (560,160).
        x,y=event['x']+120,event['y']-120
        self.assertTrue(self.api(x,y,-28,0,False,False,False,True)[0])
        self.assertFalse(self.api(x,y,-28,0,False,False,False,True)[1])
        self.assertFalse(self.api(x,y,-28,0,False,False,False,True,True)[0])

    def test_enemy_ignition_without_a_friendly_tear_is_also_guarded(self):
        self.assertTrue(self.api(436,158,28,0,False,True,False,True)[0])

    def test_actual_inactive_movable_tnt_is_guarded_before_its_blast(self):
        event=json.loads((ROOT/'tests/fixtures/stage4-movable-tnt-blast-native91.json').read_text(encoding='utf8'))
        tnt=next(e for e in event['enemies'] if e['type']==292)
        self.assertFalse(tnt['active'])
        self.lua.globals().blast=self.lua.table_from({'x':tnt['x'],'y':tnt['y'],
            'px':event['x'],'py':event['y'],'animation':tnt['animation']})
        result=self.lua.execute('''
            local guard=_Guard.new()
            local room={GetGridSize=function() return 0 end}
            local mobile={Type=292,Index=3,Position=Vector(blast.x,blast.y),
                GetSprite=function() return {GetAnimation=function() return blast.animation end} end}
            guard:observe(room,{mobile},26080,'actual',function() end,function() return true end)
            local player={Position=Vector(blast.px,blast.py)}
            return guard:danger(player),guard:safe(player,player.Position+Vector(28,0)),
                guard:safe(player,player.Position+Vector(-28,0))
        ''')
        self.assertEqual(result,(True,False,True))

    def test_movable_tnt_ignition_and_position_are_tracked_from_a_friendly_tear(self):
        self.assertEqual(self.lua.execute('''
            local guard=_Guard.new()
            local room={GetGridSize=function() return 0 end}
            local mobile={Type=292,Index=3,Position=Vector(240,200),
                GetSprite=function() return {GetAnimation=function() return 'Idle' end} end}
            local player={Position=Vector(400,200)}
            guard:observe(room,{mobile},1,'mobile',function() end,function() return true end)
            local idle=guard:danger(player)
            guard:observe(room,{mobile,{Type=2,Position=Vector(200,200),Velocity=Vector(8,0)}},
                2,'mobile',function() end,function() return true end)
            mobile.Position=Vector(320,200)
            guard:observe(room,{mobile},3,'mobile',function() end,function() return true end)
            return idle,guard:clearance(player,player.Position)
        '''),(False,-70))

    def test_movable_explosion_propagates_to_grid_tnt_and_then_expires(self):
        self.assertEqual(self.lua.execute('''
            local guard=_Guard.new()
            local room={GetGridSize=function() return 4 end,GetGridEntity=function(_,i) return i end,
                GetGridPosition=function(_,i) return Vector(280+i*40,240+i*40) end}
            local mobile={Type=292,Index=3,Position=Vector(239.8,199.8),
                GetSprite=function() return {GetAnimation=function() return 'ReadyToExplode' end} end}
            local player={Position=Vector(430,360)}
            guard:observe(room,{mobile},1,'chain',function() return {kind='tnt',active=true} end,function() return true end)
            local chained=guard:danger(player)
            guard:observe(room,{},2,'chain',function() end,function() return true end)
            local delayed=guard:danger(player)
            guard:observe(room,{},100,'chain',function() end,function() return true end)
            return chained,delayed,guard:danger(player)
        '''),(True,True,False))


if __name__=='__main__': unittest.main()
