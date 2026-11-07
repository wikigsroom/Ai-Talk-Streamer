"""Replay the observed approach into a one-exit Globin alcove."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import GameState
from isaac_jev.navigation import firing_position
from isaac_jev.decision import combat_actions


class MobileEnemyFiringLaneTests(unittest.TestCase):
    def test_mobile_enemy_lane_keeps_an_escape_in_the_real_rock_room(self):
        observed=json.loads((ROOT/'tests/fixtures/stage3-globin-dead-end-approach.json').read_text(encoding='utf8'))
        p=observed['player']
        enemies=[]
        for i,e in enumerate(observed['nearby_enemies']):
            x,y=p['position']['x']+e['offset']['x'],p['position']['y']+e['offset']['y']
            enemies.append({'id':i,'type':e['type'],'hp':e['hp'],'pos':{'x':x,'y':y},
                'vel':e['velocity'],'telegraph':e['telegraph'],
                'grid_index':int((y-100)//40)*15+int((x-20)//40)})
        state=GameState.from_message({'frame':observed['frame'],'layout':observed['room'],
            'player':{'pos':p['position'],'vel':p['velocity'],'hp':p['hp'],'tear_range':p['tear_range']},
            'player_grid_index':p['grid_index'],'enemies':enemies,
            'safe_move_directions':observed['navigation_feedback']['safe_move_directions']})
        target=state.enemies[0]
        original=firing_position(state,target.position,target.grid_index)
        safe=firing_position(state,target.position,target.grid_index,avoid_dead_ends=True)
        self.assertEqual(original[1],86,'the fixture must reproduce entry into the observed pocket')
        self.assertNotEqual(safe[1],86)
        blocked=state.layout.blocked|state.layout.danger_grid_indices
        def exits(index):
            row,col=divmod(index,15)
            return sum(0<=r<9 and 0<=c<15 and r*15+c not in blocked
                       for r,c in ((row-1,col),(row+1,col),(row,col-1),(row,col+1)))
        self.assertEqual(exits(86),1)
        self.assertGreaterEqual(exits(safe[1]),2)
        for action in combat_actions(state):
            if action.waypoint:
                x,y=action.waypoint.x,action.waypoint.y
                index=int((y-100)//40)*15+int((x-20)//40)
                self.assertGreaterEqual(exits(index),2)


if __name__=='__main__': unittest.main()
