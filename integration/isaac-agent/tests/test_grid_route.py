"""Exercise the actual Lua route follower through a blocked, turning room."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/python-libs"))
from lupa.lua53 import LuaRuntime


class GridRouteTests(unittest.TestCase):
    def setUp(self):
        source = (ROOT / "mods/IsaacJev/main.lua").read_text(encoding="utf8")
        helper = "local liveGridRoute = nil" + source.split("local liveGridRoute = nil", 1)[1].split("local function predictiveCombatMove", 1)[0]
        helper=helper.replace('include("timed_spikes")','(function()\n'+(ROOT/'mods/IsaacJev/timed_spikes.lua').read_text(encoding='utf8')+'\nend)()')
        obstacle = "local function contactObstacle(entity, player)" + source.split("local function contactObstacle(entity, player)",1)[1].split("local function playerIsDead",1)[0]
        self.api = LuaRuntime(unpack_returned_tuples=True).execute("""
            local mt = {}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local frame, closed, spikeVeto, doorVeto = 0, false, false, false
            local entities={}
            EntityType={ENTITY_SLOT=6,ENTITY_EFFECT=1000}
            PickupVariant={PICKUP_COLLECTIBLE=100}
            EffectVariant={MOM_FOOT_STOMP=29}
            Isaac={GetRoomEntities=function() return entities end}
            local room={GetGridWidth=function() return 7 end,GetGridSize=function() return 49 end,
                GetGridIndex=function(_,p) return math.floor(p.Y/40)*7+math.floor(p.X/40) end,
                GetGridPosition=function(_,i) return Vector((i%7)*40+20,math.floor(i/7)*40+20) end,
                GetGridEntity=function() return nil end}
            function room:GetGridPath(i)
                local x,y=i%7,math.floor(i/7)
                return (x==0 or x==6 or y<=0 or y>=6 or (x==3 and (closed or y<5))) and 1000 or 0
            end
            game={GetRoom=function() return room end,GetFrameCount=function() return frame end}
            local function currentRoomKey() return 'test' end
            local function gridEvent() return nil end
            local function redPoopGrid() return false end
            local function safeMoveCandidate(p,m,allowDoor,retreat,lookahead)
                if doorVeto and m.Y>0 and math.abs(p.Position.X-140)<38 and p.Position.Y+28>210 then
                    return false,'unintended_room_exit'
                end
                if spikeVeto and m.X<0 and p.Position.X>60 and p.Position.X<78 then
                    return false,'spike_or_tnt'
                end
                if room:GetGridPath(room:GetGridIndex(p.Position+m*28))>=1000 then return false,'grid_wall' end
                for _,entity in ipairs(entities) do
                    if entity.Type==5 and entity.Variant==100 then
                        local point=p.Position+m*math.max(12,math.min(28,lookahead or 28))
                        if point:Distance(entity.Position)<30 and point:Distance(entity.Position)<p.Position:Distance(entity.Position) then
                            return false,'contact_obstacle'
                        end
                    end
                end
                return true,'safe'
            end
            local gridRouteControlled=false
        """ + obstacle + helper + """
            local trail={}
            return {simulate=function(sealed,withMachine)
                frame,closed,liveGridRoute=0,sealed,nil
                entities=withMachine and {{Type=6,Size=16,Position=Vector(60,140)}} or {}
                trail={}
                local player={Position=Vector(60,60)}
                local target=Vector(220,60)
                for tick=1,500 do
                    frame=tick
                    local move=followGridRoute(player,target,8)
                    if move==nil then return false,tick,player.Position.X,player.Position.Y end
                    local nextPosition=player.Position+move*6
                    if withMachine and nextPosition:Distance(entities[1].Position)<32 then
                        return false,tick,nextPosition.X,nextPosition.Y
                    end
                    if room:GetGridPath(room:GetGridIndex(nextPosition))<1000 then player.Position=nextPosition end
                    if tick%15==0 then trail[#trail+1]={tick,player.Position.X,player.Position.Y} end
                    if player.Position:Distance(target)<=8 then return true,tick,player.Position.X,player.Position.Y end
                end
                return false,500,player.Position.X,player.Position.Y
            end,
            stableRouteReleasesTiming=function()
                frame,closed,liveGridRoute=1,false,nil
                timedSpikeNavigator.active,timedSpikeNavigator.plan=true,{}
                followGridRoute({Position=Vector(60,60)},Vector(220,60),8)
                return timedSpikeNavigator.active,timedSpikeNavigator.plan==nil
            end,
            routeAwayFromDoor=function()
                frame,closed,liveGridRoute,spikeVeto,doorVeto=0,false,nil,false,true
                entities={}
                room.GetGridPath=function(_,i)
                    local x,y=i%7,math.floor(i/7)
                    return (x==0 or x==6 or y==0 or y==6) and 1000 or 0
                end
                local p={Position=Vector(140,202.343),Velocity=Vector(0,0)}
                local target=Vector(60,180)
                for tick=1,150 do
                    frame=tick
                    local move=followGridRoute(p,target,8) or Vector(0,0)
                    local next=p.Position+move*4
                    if math.abs(next.X-140)<38 and next.Y>210 then return false,'crossed_unselected_door' end
                    p.Position=next
                    if p.Position:Distance(target)<=8 then return true,tick end
                end
                return false,'centering_deadlock'
            end,
            centerNearSpikes=function()
                frame,closed,liveGridRoute,spikeVeto=0,false,nil,true
                local move=followGridRoute({Position=Vector(74,60)},Vector(60,220),8)
                return move.X,move.Y
            end,
            simulatePedestal=function()
                frame,liveGridRoute,spikeVeto=0,nil,false
                room.GetGridPath=function(_,i)
                    local x,y=i%7,math.floor(i/7)
                    return (x==0 or x==6 or y==0 or y==6) and 1000 or 0
                end
                entities={{Type=5,Variant=100,SubType=0,Size=12,Position=Vector(140,180)}}
                local player={Position=Vector(140,229.7),Size=10}
                local target=Vector(140,60)
                for tick=1,240 do
                    frame=tick
                    local move=followGridRoute(player,target,8)
                    if not move then return false,tick end
                    local nextPosition=player.Position+move*6
                    -- Reproduce the native empty pedestal's body collision.
                    if nextPosition:Distance(entities[1].Position)>=24
                        and room:GetGridPath(room:GetGridIndex(nextPosition))<1000 then
                        player.Position=nextPosition
                    end
                    if player.Position:Distance(target)<=8 then return true,tick end
                end
                return false,240
            end,
            trail=function() return trail end,
            blockedLine=function() return clearTearLine(room,Vector(60,60),Vector(220,60)) end,
            pitLine=function()
                GridCollisionClass={COLLISION_OBJECT=2}
                room.GetGridCollision=function(_,i)
                    if i==24 then return 1 end
                    return room:GetGridPath(i)>=1000 and 2 or 0
                end
                return clearTearLine(room,Vector(60,140),Vector(220,140))
            end}
        """)

    def test_reaches_target_around_wall_and_multiple_turns(self):
        completed, ticks, x, y = self.api.simulate(False)
        self.assertTrue(completed, (ticks, x, y))
        self.assertLess(ticks, 200)

    def test_sealed_route_does_not_walk_into_wall(self):
        completed, ticks, x, y = self.api.simulate(True)
        self.assertFalse(completed)
        self.assertEqual((x, y), (60, 60))

    def test_door_centering_veto_can_move_along_the_safe_route_without_crossing(self):
        completed,detail=self.api.routeAwayFromDoor()
        self.assertTrue(completed,detail)

    def test_permanent_route_releases_the_previous_timing_owner(self):
        self.assertEqual(self.api.stableRouteReleasesTiming(),(False,True))

    def test_wall_between_aligned_targets_blocks_tear_lane(self):
        self.assertFalse(self.api.blockedLine())

    def test_pit_blocks_walking_but_not_tears(self):
        self.assertTrue(self.api.pitLine())

    def test_short_centering_checks_actual_step_beside_spikes(self):
        self.assertEqual(self.api.centerNearSpikes(), (-1, 0))

    def test_route_avoids_contact_with_blood_donation_machine(self):
        completed, ticks, x, y = self.api.simulate(False, True)
        self.assertTrue(completed, (ticks,x,y))

    def test_route_goes_around_empty_collectible_pedestal(self):
        completed,ticks=self.api.simulatePedestal()
        self.assertTrue(completed,ticks)


if __name__ == "__main__":
    unittest.main()
