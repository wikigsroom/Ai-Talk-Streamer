"""Replay the Monstro II laser lane trapped below the real boss-room rocks."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import GameState, Vec2
from isaac_jev.navigation import firing_position, path_distance
from isaac_jev.decision import combat_actions
from isaac_jev.tuning import PolicyProfile


class BeamFiringLaneTests(unittest.TestCase):
    def observed_state(self, name='stage5-monstro2-laser-43781.json'):
        observed=json.loads((ROOT/'tests/fixtures'/name).read_text(encoding='utf8'))['input']
        p=observed['player']
        enemies=[]
        for i,e in enumerate(observed['nearby_enemies']):
            x,y=p['position']['x']+e['offset']['x'],p['position']['y']+e['offset']['y']
            enemies.append({'id':i,'type':e['type'],'variant':e['variant'],'hp':e['hp'],
                'pos':{'x':x,'y':y},'vel':e['velocity'],'telegraph':e['telegraph'],
                'is_boss':e['is_boss'],
                'grid_index':int((y-100)//40)*15+int((x-20)//40)})
        return GameState.from_message({'frame':observed['frame'],'layout':observed['room'],
            'player':{'pos':p['position'],'vel':p['velocity'],'hp':p['hp'],'tear_range':p['tear_range']},
            'player_grid_index':p['grid_index'],'enemies':enemies,
            'safe_move_directions':observed['navigation_feedback']['safe_move_directions']})

    def test_observed_rock_corridor_has_a_reachable_vertical_lane(self):
        for name in ('stage5-monstro2-laser-43781.json','stage5-monstro2-laser-43812.json'):
            with self.subTest(name=name):
                state=self.observed_state(name)
                enemy=state.enemies[0]
                lane=firing_position(state,enemy.position,enemy.grid_index,130,
                    avoid_dead_ends=True,firing_axis='vertical')
                self.assertIsNotNone(lane)
                point,index,shoot=lane
                self.assertAlmostEqual(point.x,enemy.position.x)
                self.assertGreaterEqual(abs(point.y-enemy.position.y),130)
                self.assertNotEqual(shoot.y,0)
                self.assertLess(path_distance(state,point,index),float('inf'))
                waypoints=[a.waypoint for a in combat_actions(state) if a.waypoint]
                self.assertTrue(waypoints)
                self.assertTrue(all(abs(p.x-enemy.position.x)<1 for p in waypoints))
                self.assertTrue(all(abs(p.y-enemy.position.y)>=PolicyProfile().enemy_safe_distance for p in waypoints))

    def test_current_horizontal_lane_is_not_retained_during_horizontal_beam(self):
        state=self.observed_state()
        enemy=state.enemies[0]
        state=replace(state,player=replace(state.player,position=Vec2(120,enemy.position.y)),
                      player_grid_index=107)
        lane=firing_position(state,enemy.position,enemy.grid_index,130,firing_axis='vertical')
        self.assertIsNotNone(lane)
        self.assertAlmostEqual(lane[0].x,enemy.position.x)

    def test_axis_is_respected_without_grid_geometry(self):
        state=GameState.from_message({'player':{'pos':{'x':100,'y':200},'tear_range':260}})
        lane=firing_position(state,Vec2(300,200),-1,firing_axis='vertical')
        self.assertEqual(lane[0].x,300)
        self.assertNotEqual(lane[0].y,200)
        self.assertEqual(lane[2].x,0)

    def test_actual_gurdy_jr_approaches_keep_a_reachable_reaction_gap(self):
        for frame in (20103,20115,20310,20322):
            with self.subTest(frame=frame):
                state=self.observed_state(f'stage3-gurdy-jr-approach-{frame}-native91.json')
                waypoints=[a.waypoint for a in combat_actions(state) if a.waypoint]
                self.assertTrue(waypoints)
                for point in waypoints:
                    self.assertGreaterEqual(point.distance_to(state.enemies[0].position),185)


if __name__=='__main__': unittest.main()
