"""The real narrow treasure room remains passable below its empty pedestal."""
import json
from dataclasses import replace
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools/python-libs')]
from lupa.lua53 import LuaRuntime
from isaac_jev.models import GameState,Vec2
from isaac_jev.navigation import door_path_distance
from isaac_jev.decision import recovery_actions


class PedestalCorridorTests(unittest.TestCase):
    def project(self,kind):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        block='local dangerousIndices = {}'+source.split('local dangerousIndices = {}',1)[1].split('    -- Layout is cached',1)[0]
        result=LuaRuntime(unpack_returned_tuples=True).execute('''
            local mt={}
            Vector=function(x,y) return setmetatable({X=x,Y=y},mt) end
            mt.__index={Distance=function(a,b) return math.sqrt((a.X-b.X)^2+(a.Y-b.Y)^2) end}
            local room={GetGridSize=function() return 135 end,
                GetGridPosition=function(_,i) return Vector(40+(i%15)*40,120+math.floor(i/15)*40) end}
            return function(kind)
                local lastLayout={danger_grid_indices={}}
                local dangerEffects={{kind=kind,pos={x=320,y=200},radius=30}}
        '''+block+'''
                return lastLayout.danger_grid_indices
            end
        ''')(kind)
        return frozenset(result.values())

    def state(self):
        raw=json.loads((ROOT/'tests/fixtures/stage5-empty-pedestal-stall-native91.json').read_text(encoding='utf8'))
        return GameState.from_message(raw)

    def test_actual_exit_opens_in_planning_without_removing_the_pedestal(self):
        state=self.state();door=state.layout.doors[0]
        self.assertEqual(door_path_distance(state,door),float('inf'))
        safe=replace(state,layout=replace(state.layout,danger_grid_indices=self.project('empty_pedestal')))
        self.assertIn(37,safe.layout.danger_grid_indices)
        self.assertNotIn(52,safe.layout.danger_grid_indices)
        self.assertLess(door_path_distance(safe,door),float('inf'))
        self.assertEqual(self.project('unsupported_pedestal'),frozenset({37}))
        self.assertEqual(self.project('unselected_health_deal'),frozenset({37}))

    def test_damaging_effects_keep_the_extra_grid_margin(self):
        for kind in ('fire','creep','moving_spike','stomp'):
            with self.subTest(kind=kind):
                self.assertIn(52,self.project(kind))

    def test_live_safe_one_cell_step_can_precede_a_turn(self):
        state=self.state()
        state=replace(state,recovery_active=True,recovery_target_door_slot=3,
            layout=replace(state.layout,danger_grid_indices=self.project('empty_pedestal'),
                blocked=state.layout.blocked|{51}))
        actions=recovery_actions(state,allow_short=True)
        left=next(a for a in actions if a.action_id=='recover_left')
        self.assertEqual(left.waypoint,Vec2(320,240))
        unsafe=replace(state,safe_move_directions={'left':'contact_obstacle'})
        self.assertFalse(recovery_actions(unsafe,allow_short=True))


if __name__=='__main__': unittest.main()
