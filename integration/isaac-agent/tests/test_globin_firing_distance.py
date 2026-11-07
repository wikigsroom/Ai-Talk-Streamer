"""Strategic lanes leave reaction space without abandoning a downed Globin."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import GameState,Vec2
from isaac_jev.decision import combat_actions


class GlobinFiringDistanceTests(unittest.TestCase):
    def state(self,kind=24,animation='WalkHori',hp=33):
        rows=json.loads((ROOT/'tests/fixtures/stage4-explosive-chargers-native122.json').read_text(encoding='utf8'))
        state=GameState.from_message(next(s for s in rows if s['frame']==54523))
        target=replace(state.enemies[0],kind=kind,variant=0,position=Vec2(520,280),velocity=Vec2(),
            grid_index=72,telegraph=animation,hit_points=hp)
        return replace(state,enemies=(target,),player=replace(state.player,position=Vec2(360,280)),
            player_grid_index=68,layout=replace(state.layout,blocked=frozenset(),shot_blocked=frozenset()))

    def lane(self,state):
        routes=[a.waypoint for a in combat_actions(state) if a.waypoint is not None]
        self.assertTrue(routes)
        return routes[0].distance_to(state.enemies[0].position)

    def test_living_globin_and_fallen_have_reaction_space_in_strategic_lanes(self):
        for kind in (24,81):
            self.assertGreaterEqual(self.lane(self.state(kind)),185)

    def test_regenerating_or_low_health_globin_keeps_the_finishing_lane(self):
        for animation,hp in (('ReGen',10),('WalkHori',3)):
            actions=combat_actions(self.state(animation=animation,hp=hp))
            self.assertEqual(actions[0].action_id,'hold_and_fire')
            self.assertEqual(actions[0].move,Vec2())
            self.assertFalse(any(a.action_id=='route_to_firing_lane' for a in actions))


if __name__=='__main__':unittest.main()
