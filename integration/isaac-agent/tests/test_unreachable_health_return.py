"""Replay the actual half-heart behind an impassable floor-4 obstacle."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.models import Door, Entity, GameState, RoomLayout, Vec2
from isaac_jev.runtime import Controller


class UnreachableHealthReturnTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.controller=Controller(log_dir=self.folder.name)
        self.state=GameState.from_message(json.loads((ROOT/'tests/fixtures/health-loop-room-125.json').read_text(encoding='utf8')))

    def tearDown(self):
        self.controller.shutdown()
        self.folder.cleanup()

    def test_visible_half_heart_is_not_a_reachable_healing_target(self):
        self.controller._record_room_intel(self.state)
        intel=self.controller._room_intel[125]
        self.assertIn('red_half_heart',intel['rewards'])
        self.assertNotIn('red_half_heart',intel['reachable_rewards'])

    def test_other_room_does_not_return_forever_to_unreachable_half_heart(self):
        self.controller._record_room_intel(self.state)
        other=GameState.from_message(json.loads((ROOT/'tests/fixtures/health-loop-room-112.json').read_text(encoding='utf8')))
        self.controller._current_room_index=112
        self.controller._room_graph[112]=other.layout.doors
        self.controller._visited_rooms={110,112,125}
        self.assertNotEqual(self.controller._plan_next_door(other)[1],'return to observed health pickup')

    def test_reachable_health_is_still_remembered_for_a_safe_return(self):
        pickup=replace(self.state.pickups[0],position=self.state.player.position,grid_index=self.state.player_grid_index)
        self.controller._record_room_intel(replace(self.state,pickups=(pickup,)))
        self.assertIn('red_half_heart',self.controller._room_intel[125]['reachable_rewards'])

    def test_one_missing_half_heart_does_not_redirect_a_healthy_run(self):
        controller=self.controller
        controller._current_room_index=1
        controller._visited_rooms={1,2}
        doors=(Door(0,Vec2(),target_room_index=2,target_clear=True),
               Door(1,Vec2(),target_room_index=4,target_room_type='boss',target_is_boss=True))
        controller._room_graph[1]=doors
        controller._room_intel[2]={'clear':True,'room_type':'default','reachable_rewards':['red_heart']}
        state=GameState(frame=1,room_clear=True,player=Entity(0,1,Vec2(),Vec2(),7),
            enemies=(),projectiles=(),red_hearts=7,max_hearts=8,layout=RoomLayout(room_index=1,doors=doors))
        controller._committed_door_room,controller._committed_door_slot=1,0
        self.assertEqual(controller._plan_next_door(state),(1,'known boss room'))
        low=replace(state,player=replace(state.player,hit_points=3),red_hearts=3,max_hearts=4)
        self.assertEqual(controller._plan_next_door(low),(0,'return to observed health pickup'))


if __name__=='__main__': unittest.main()
