"""Exercise the real engine adapter, target windows, and primary-shot observation."""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class WeaponTargetingTests(unittest.TestCase):
    def setUp(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        helper='local function chargedShootDirection('+source.split('local function chargedShootDirection(',1)[1].split('local function escapeStomp',1)[0]
        module=(ROOT/'mods/IsaacJev/weapon_control.lua').read_text(encoding='utf8')
        self.api=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local mod={weaponControl=(function()\n'''+module+'''\nend)().new()}
            EntityType={ENTITY_PLAYER=1,ENTITY_LASER=7,ENTITY_TEAR=2,ENTITY_KNIFE=8}
            local frame,entities,cleared=0,{},false
            local room={IsClear=function() return cleared end}
            local game={GetFrameCount=function() return frame end,GetRoom=function() return room end}
            Isaac={GetRoomEntities=function() return entities end}
            local function isCombatEnemy(e) return e.Type==10 end
            local function clearTearLine() return true end
            local function vectorTable(v) return {x=v.X,y=v.Y} end
            local combatAimTargetId=-1
            local automatic,ghostBombRetreatActive,fireBlockReason=true,false,'idle'
            local action={mode='combat',id=''}
            local nativeChargeStartFrame,nativeChargePhase=-1,'idle'
            local player={Index=0,Position=Vector(0,0),MaxFireDelay=19.772859573364,ShotSpeed=1,
                HasCollectible=function() return false end}
        '''+helper+'''
            return function(tick,x,y,vx,vy,vulnerable,beam,child,clear)
                frame,cleared=tick,clear or false
                local enemy={Type=10,Index=99,Size=12,HitPoints=20,
                    Position=Vector(x,y),Velocity=Vector(vx or 0,vy or 0),
                    IsVulnerableEnemy=function() return vulnerable~=false end}
                enemy.ToNPC=function() return enemy end
                entities=cleared and {} or {enemy}
                if beam then
                    local laser={Type=7,InitSeed=123,Index=101,SpawnerEntity={Type=1,Index=0},
                        Parent={Type=child and 7 or 1}}
                    laser.ToLaser=function() return {Timeout=7} end
                    entities[#entities+1]=laser
                end
                local output=chargedShootDirection(player,Vector(1,0),'brimstone')
                return output.X,output.Y,mod.weaponControl.phase,mod.weaponControl.shots,
                    mod.weaponControl.targetReady
            end
        ''')

    def test_beam_aim_uses_short_lead_and_can_fire_at_a_crossing_target(self):
        self.api(0,200,0,0,8,True,False,False,False)
        result=self.api(23,200,0,0,8,True,False,False,False)
        self.assertEqual(result[:3],(0,0,'release'))
        self.assertTrue(result[4])

    def test_closed_host_is_charged_without_firing_into_its_invulnerable_window(self):
        self.api(0,200,0,0,0,False,False,False,False)
        self.assertEqual(self.api(40,200,0,0,0,False,False,False,False)[:3],(1,0,'hold_charge'))
        self.assertEqual(self.api(41,200,0,0,0,True,False,False,False)[:3],(0,0,'release'))

    def test_alignment_window_releases_existing_full_charge(self):
        self.api(0,200,100,0,0,True,False,False,False)
        self.assertEqual(self.api(30,200,100,0,0,True,False,False,False)[:3],(1,0,'hold_charge'))
        self.assertEqual(self.api(31,200,0,0,0,True,False,False,False)[:3],(0,0,'release'))

    def test_existing_primary_beam_is_observed_once_and_kept_running(self):
        self.assertEqual(self.api(0,200,0,0,0,True,True,False,False)[:4],(0,0,'beam',1))
        self.assertEqual(self.api(1,200,0,0,0,True,True,False,False)[:4],(0,0,'beam',1))
        self.assertEqual(self.api(8,200,0,0,0,True,False,False,False)[:3],(1,0,'charge'))

    def test_continuum_descendant_is_not_a_second_primary_beam(self):
        result=self.api(0,200,0,0,0,True,True,True,False)
        self.assertEqual(result[:4],(1,0,'charge',0))

    def test_native_room_clear_stops_an_armed_charge(self):
        self.api(0,200,0,0,0,True,False,False,False)
        self.assertEqual(self.api(15,200,0,0,0,True,False,False,True)[:3],(0,0,'idle'))


if __name__=='__main__':
    unittest.main()
