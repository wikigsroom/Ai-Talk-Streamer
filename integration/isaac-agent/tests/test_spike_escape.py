"""Replay the real two-sided spike trap and verify safe healing conditions."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/python-libs'))
from lupa.lua53 import LuaRuntime


class SpikeEscapeTests(unittest.TestCase):
    def setUp(self):
        source = (ROOT / 'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        safety = 'local function safeMoveCandidate(' + source.split('local function safeMoveCandidate(', 1)[1].split('local function firstSafeMove', 1)[0]
        escape = 'local function gridDangerClearance(' + source.split('local function gridDangerClearance(', 1)[1].split('local function hostileLaser', 1)[0]
        healing = 'local function healingRoomSafe(' + source.split('local function healingRoomSafe(', 1)[1].split('function mod:planHeldActive', 1)[0]
        state = json.loads((ROOT / 'tests/fixtures/stage5-trap-healing-death.json').read_text(encoding='utf8'))['input']
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().blocked = lua.table_from({i: True for i in state['room']['blocked']})
        lua.globals().spikes = lua.table_from({e['grid_index']: True for e in state['room']['grid_events'] if e['kind'] == 'spike'})
        self.api = lua.execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__add=function(a,b) return Vector(a.X+b.X,a.Y+b.Y) end
            mt.__sub=function(a,b) return Vector(a.X-b.X,a.Y-b.Y) end
            mt.__mul=function(a,b) return Vector(a.X*b,a.Y*b) end
            mt.__index={Length=function(a) return math.sqrt(a.X*a.X+a.Y*a.Y) end,
                Distance=function(a,b) return (a-b):Length() end}
            local active=true
            local entities={}
            local room={GetGridSize=function() return 135 end,
                GetGridIndex=function(_,p) return math.floor((p.Y-100)/40)*15+math.floor((p.X-20)/40) end,
                GetGridPosition=function(_,i) return Vector(40+(i%15)*40,120+math.floor(i/15)*40) end,
                GetGridPath=function(_,i) return blocked[i] and 1000 or 0 end}
            function room:GetGridEntity(i)
                return spikes[i] and {Position=self:GetGridPosition(i)} or nil
            end
            local function gridEvent(g) return g and {kind='spike',active=active,pos={x=g.Position.X,y=g.Position.Y}} or nil end
            local function redPoopGrid() return false end
            local function liveGridHazardKind() return nil end
            local function liveHazardKind() return nil end
            local function bombOnlyFireKind() return false end
            local function bombStillLive() return false end
            local function hostileLaser() return nil end
            local function dangerousCreep() return false end
            local function isMovingSpikeTrap() return false end
            EntityType={ENTITY_PROJECTILE=9}
            Isaac={GetRoomEntities=function() return entities end}
            game={GetRoom=function() return room end}
        ''' + safety + escape + healing + '''
            return {escape=function()
                local player={Position=Vector(332.2,253.5),Velocity=Vector(-0.5,1),Size=10}
                local move=escapeGridDanger(player)
                return move.X,move.Y
            end,heal=function(hazard,entityType)
                active=hazard
                entities=entityType and {{Type=entityType}} or {}
                return healingRoomSafe(room,{Size=10})
            end,simulate=function()
                active=true
                local p={Position=Vector(332.2,253.5),Velocity=Vector(-0.5,1),Size=10}
                for tick=1,30 do
                    local move=escapeGridDanger(p)
                    if not move then return true,tick end
                    p.Velocity=p.Velocity*0.7+move*1.32
                    p.Position=p.Position+p.Velocity*2
                end
                return false,30
            end}
        ''')

    def test_escape_increases_clearance_from_both_adjacent_spikes(self):
        x,y = self.api.escape()
        self.assertLess(x, 0)
        self.assertLess(y, 0)

    def test_actual_corner_escape_settles_outside_all_spikes_with_inertia(self):
        complete,ticks = self.api.simulate()
        self.assertTrue(complete, ticks)

    def test_room_clear_is_insufficient_for_standing_still_to_heal(self):
        self.assertFalse(self.api.heal(True, None))
        self.assertFalse(self.api.heal(False, 9))
        self.assertFalse(self.api.heal(False, 201))
        self.assertTrue(self.api.heal(False, None))


if __name__ == '__main__':
    unittest.main()
