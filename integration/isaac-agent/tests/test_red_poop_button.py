"""Keep regenerative red poop clearable without treating rubble as lethal."""
import copy
import json
from pathlib import Path
import sys
import unittest
import tempfile
from dataclasses import replace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools/python-libs')]
from lupa.lua53 import LuaRuntime
from isaac_jev.models import GameState
from isaac_jev.decision import candidate_actions
from isaac_jev.models import Action,Vec2
from isaac_jev.runtime import Controller


class RedPoopButtonTests(unittest.TestCase):
    def test_actual_grid_damage_animation_is_progress_even_with_zero_exported_hp(self):
        raw=json.loads((ROOT/'tests/fixtures/stage7-button-trap-safety-native89.json').read_text(encoding='utf8'))
        state=GameState.from_message(raw)
        target=next(h for h in state.hazards if h.grid_index==65)
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            controller=Controller(log_dir=folder)
            controller._effective_action=Action(f'clear_hazard_{target.entity_id}',Vec2(),Vec2(1,0),mode='hazard')
            for frame,animation in ((1,'State1'),(61,'State2'),(121,'State3'),(181,'State2')):
                current=replace(state,frame=frame,hazards=(replace(target,animation=animation),))
                controller._update_hazard_progress(current)
                self.assertNotIn(target.entity_id,controller._ignored_hazard_ids)
            controller.shutdown()

    def test_required_button_obstacle_failure_is_retried_after_a_bounded_cooldown(self):
        raw=json.loads((ROOT/'tests/fixtures/stage7-button-trap-safety-native89.json').read_text(encoding='utf8'))
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            controller=Controller(log_dir=folder)
            controller.receive_state(raw)
            state=controller._latest_state
            target=next(h for h in state.hazards if h.grid_index==65)
            controller._mark_hazard_unreachable(target.entity_id,state)
            self.assertIn(target.entity_id,controller._ignored_hazard_ids)
            raw['frame']=state.frame+179
            controller.receive_state(raw)
            self.assertIn(target.entity_id,controller._ignored_hazard_ids)
            raw['frame']=state.frame+181
            controller.receive_state(raw)
            self.assertNotIn(target.entity_id,controller._ignored_hazard_ids)
            controller.shutdown()

    def test_actual_variant_is_shootable_and_rubble_releases_contact_guard(self):
        source=(ROOT/'mods/IsaacJev/main.lua').read_text(encoding='utf8')
        red='local function redPoopGrid(grid)'+source.split('local function redPoopGrid(grid)',1)[1].split('local function gridEvent',1)[0]
        hazard='local function gridHazardKind(grid)'+source.split('local function gridHazardKind(grid)',1)[1].split('local function hazardTable',1)[0]
        classify=LuaRuntime(unpack_returned_tuples=True).execute('''
            local GRID_POOP_TYPE,GRID_FIREPLACE_TYPE,GRID_TINTED_ROCK_TYPE,GRID_SUPER_TINTED_ROCK_TYPE=14,10,4,22
            local GRID_PRESSURE_PLATE_TYPE=20
            local function gridState(g) return g.State end
            local function bombOnlyFireKind() return false end
        '''+red+hazard+'''
            return function(variant,collision,state,buttonRoom)
                game={GetRoom=function() return {
                    IsClear=function() return not buttonRoom end,GetGridSize=function() return 1 end,
                    GetGridEntity=function() return buttonRoom and {State=0,GetType=function() return 20 end} or nil end}
                    end}
                local grid={CollisionClass=collision,State=state,
                    GetType=function() return 14 end,GetVariant=function() return variant end}
                return redPoopGrid(grid),liveGridHazardKind(grid)
            end
        ''')
        self.assertEqual(classify(1,3,0),(True,'red_poop'))
        self.assertEqual(classify(1,0,1000),(True,None),'ordinary routes must reserve regeneration cells')
        self.assertEqual(classify(1,0,1000,True),(False,None),'closed plate room permits its short opening')
        self.assertEqual(classify(1,3,0),(True,'red_poop'),'regrowth must restore the guard')
        self.assertEqual(classify(0,3,0),(False,'poop'))

    def test_real_closed_button_room_clears_barrier_then_operates_button(self):
        raw=json.loads((ROOT/'tests/fixtures/stage7-red-poop-button-native78.json').read_text(encoding='utf8'))
        self.assertFalse(raw['room_clear'])
        self.assertEqual(raw['enemies'],[])
        self.assertEqual(candidate_actions(GameState.from_message(raw))[0].action_id,'wait_for_room_clear')
        updated=copy.deepcopy(raw)
        updated['hazards']=[dict(id=-100000-g['grid_index'],kind='red_poop',type=14,
            variant=1,state=g['state'],pos=g['pos'],grid_index=g['grid_index'],destructible=True,
            requires_bomb=False) for g in raw['observed_grid_entities']]
        actions=candidate_actions(GameState.from_message(updated))
        self.assertTrue(actions)
        self.assertTrue(all(a.action_id.startswith('clear_hazard_') for a in actions))
        cleared={69,71,72}
        for key in ('blocked','danger_grid_indices','shot_blocked'):
            updated['layout'][key]=[i for i in updated['layout'][key] if i not in cleared]
        updated['hazards']=[h for h in updated['hazards'] if h['grid_index'] not in cleared]
        actions=candidate_actions(GameState.from_message(updated))
        self.assertEqual(actions[0].action_id,'press_button_-100073')

    def test_real_button_pocket_does_not_let_recovery_suppress_exit_clearance(self):
        raw=json.loads((ROOT/'tests/fixtures/stage7-button-pocket-recovery-native79.json').read_text(encoding='utf8'))
        self.assertTrue(raw['recovery_active'])
        self.assertTrue(raw['room_clear'])
        actions=candidate_actions(GameState.from_message(raw))
        self.assertTrue(actions)
        self.assertEqual(actions[0].mode,'hazard')
        self.assertTrue(actions[0].action_id.startswith('clear_hazard_'))

    def test_clear_regenerating_room_does_not_farm_red_poop(self):
        from dataclasses import replace
        raw=json.loads((ROOT/'tests/fixtures/stage7-red-poop-button-native78.json').read_text(encoding='utf8'))
        raw['hazards']=[dict(id=-100000-g['grid_index'],kind='red_poop',type=14,
            variant=1,pos=g['pos'],grid_index=g['grid_index'],destructible=True)
            for g in raw['observed_grid_entities']]
        state=replace(GameState.from_message(raw),room_clear=True)
        actions=candidate_actions(state)
        self.assertFalse(any(a.action_id.startswith('clear_hazard_') for a in actions))


if __name__=='__main__': unittest.main()
