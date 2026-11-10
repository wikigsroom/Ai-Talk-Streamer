"""Synthetic packets: observation must not manufacture failed input attempts."""
from pathlib import Path
import tempfile
import unittest

from isaac_jev.models import Action, GameState, Vec2
from isaac_jev.runtime import Controller


class InputAdmissionTests(unittest.TestCase):
    def controller(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        owner=Controller(autopilot_enabled=False,require_enabled_action_feedback=True,log_dir=directory.name)
        self.addCleanup(owner.shutdown)
        return owner

    @staticmethod
    def observation(frame):
        return {'type':'state','frame':frame,'room_clear':True,
                'player':{'pos':{'x':0,'y':0},'hp':6},'enemies':[],'projectiles':[],
                'hazards':[{'id':10,'kind':'fire','type':33,'hp':5,'animation':'Flickering',
                            'pos':{'x':80,'y':0}}],
                'layout':{'room_index':60,'doors':[{'slot':1,'pos':{'x':0,'y':-120},'target_room_index':47}]}}

    def test_many_unarmed_packets_do_not_mark_visible_target_unreachable(self):
        owner=self.controller()
        for frame in range(100,1000,6):
            response=owner.receive_state(self.observation(frame))
            self.assertFalse(response['enabled'])
        self.assertEqual(owner._ignored_hazard_ids,set())
        self.assertEqual(owner._unreachable_targets,[])
        self.assertEqual(owner._movement_stall_count,0)
        self.assertIsNone(owner._effective_action)
        owner.set_autopilot(True)
        self.assertIsNone(owner._effective_action)
        self.assertEqual(owner._hazard_progress_by_target,{})

    def test_real_enabled_attempt_still_expires_but_readmission_drops_old_timer(self):
        owner=self.controller();owner.set_autopilot(True)
        owner._effective_action=Action('clear_hazard_10',Vec2(),Vec2(1,0),mode='hazard')
        owner._update_hazard_progress(GameState.from_message(self.observation(100)))
        owner.set_autopilot(False)
        self.assertEqual(owner._hazard_progress_by_target,{})
        self.assertIsNone(owner._effective_action)
        owner.set_autopilot(True)
        owner._effective_action=Action('clear_hazard_10',Vec2(),Vec2(1,0),mode='hazard')
        owner._update_hazard_progress(GameState.from_message(self.observation(1000)))
        self.assertNotIn(10,owner._ignored_hazard_ids)
        owner._update_hazard_progress(GameState.from_message(self.observation(3000)))
        self.assertIn(10,owner._ignored_hazard_ids)
        self.assertIn('hazard:10',owner._unreachable_targets)


if __name__=='__main__':unittest.main()
