"""Special room -1 is an actual visited room, not an absent observation."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from isaac_jev.runtime import Controller


class SpecialRoomTrackingTests(unittest.TestCase):
    def test_devil_entry_and_return_reset_actions_and_preserve_visitation(self):
        with tempfile.TemporaryDirectory() as folder:
            controller=Controller(log_dir=folder)
            def observe(frame,index,kind,target):
                controller.receive_state({'frame':frame,'start_seed':444,'stage':2,
                    'floor_id':'444:2:0','room_index':index,'room_clear':True,
                    'player':{'id':0,'type':1,'pos':{'x':320,'y':280},'hp':8},
                    'enemies':[],'projectiles':[],
                    'layout':{'room_index':index,'room_type':kind,'doors':[
                        {'slot':0,'pos':{'x':40,'y':280},'target_room_index':target,
                         'target_room_type':'devil' if target<0 else 'boss',
                         'door_open':True,'door_open_known':True}]}})
            observe(100,33,'boss',-1)
            controller._ignored_pickup_ids.add(101)
            observe(110,-1,'devil',33)
            self.assertEqual(controller._current_room_index,-1)
            self.assertEqual(controller._previous_room_index,33)
            self.assertEqual(controller._ignored_pickup_ids,set())
            self.assertIn(-1,controller._visited_rooms)
            self.assertEqual(controller._room_graph[-1][0].target_room_index,33)
            observe(120,33,'boss',-1)
            self.assertEqual(controller._previous_room_index,-1)
            self.assertIn((33,-1),controller._traversed_edges)
            self.assertIn((-1,33),controller._traversed_edges)
            self.assertEqual(controller._ignored_pickup_ids,{101})


if __name__=='__main__': unittest.main()
