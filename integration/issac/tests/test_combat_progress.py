"""A moving frame and a ready model must not hide an endless combat room."""
from copy import deepcopy
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock

from integration.issac.combat_progress import CombatProgress, quiet_combat_boundary
from integration.issac.live_cycle import LiveCycle


def observation():
    identity = {'controller':'c','seed':1,'restart':0,'stage':3,'dimension':0,'room':80,'visit':42,'bridge':'b'}
    return {'connected':True,'age_ms':10,'identity':identity,'frame':100,
            'data':{'identity':identity,'frame':100,'room':{'clear':False,'paused':False,'dead':False},
                    'player':{'hp':8,'pos':{'x':198.5,'y':275.6}},
                    'enemies':[{'id':3,'hp':20,'pos':{'x':480,'y':280},'vel':{'x':0,'y':0}}],
                    'projectiles':[],'danger_effects':[]}}


class CombatProgressTests(unittest.TestCase):
    def setUp(self):
        self.view = observation()
        self.guard = CombatProgress()

    def sample(self, seconds, **changes):
        self.view['data']['frame'] = 100+int(seconds*30)
        for key,value in changes.items():
            self.view['data'][key] = value
        return self.guard.update(self.view, enabled=True, now=seconds)

    def test_advancing_frames_and_player_movement_do_not_hide_no_damage(self):
        self.assertFalse(self.sample(0))
        self.assertFalse(self.sample(179))
        self.view['data']['player']['pos'] = {'x':100,'y':200}
        self.assertTrue(self.sample(181))
        self.assertTrue(self.guard.status()['stalled'])

    def test_real_damage_and_kills_restart_the_progress_timer(self):
        self.sample(0)
        self.view['data']['enemies'].append({'id':4,'hp':20})
        self.view['data']['enemies'][0]['hp'] = 10
        self.assertFalse(self.sample(179))
        self.view['data']['enemies'] = [self.view['data']['enemies'][0]]
        self.assertFalse(self.sample(350))
        self.assertFalse(self.sample(529))
        self.assertTrue(self.sample(531))

    def test_regeneration_cannot_refresh_progress_forever(self):
        self.sample(0)
        self.view['data']['enemies'][0]['hp'] = 10
        self.sample(10)
        self.view['data']['enemies'][0]['hp'] = 20
        self.sample(100)
        self.view['data']['enemies'][0]['hp'] = 10
        self.assertTrue(self.sample(191))

    def test_new_room_and_visit_reset_the_timer(self):
        self.sample(0)
        self.view['data']['identity']['visit'] += 1
        self.assertFalse(self.sample(200))
        self.assertEqual(self.guard.seconds, 0)

    def test_frozen_frame_belongs_to_simulation_watchdog(self):
        self.sample(0)
        self.assertFalse(self.guard.update(self.view, enabled=True, now=200))

    def test_unarmed_stale_paused_dead_clear_missing_hp_are_not_combat(self):
        cases = [('connected',False),('age_ms',1600)]
        for key,value in cases:
            view = observation();view[key] = value
            self.assertFalse(self.guard.update(view, enabled=True, now=500))
            self.assertIsNone(self.guard.identity)
        for key,value in [('clear',True),('paused',True),('dead',True)]:
            view = observation();view['data']['room'][key] = value
            self.assertFalse(self.guard.update(view, enabled=True, now=500))
            self.assertIsNone(self.guard.identity)
        self.assertFalse(self.guard.update(observation(), enabled=False, now=500))
        view = observation();del view['data']['enemies'][0]['hp']
        self.assertFalse(self.guard.update(view, enabled=True, now=500))

    def test_stall_requests_component_repair_without_game_pause_or_restart(self):
        now = [0]
        service = SimpleNamespace(snapshot=self.view['data'],raw={'strategy':{},'enemy_observation_valid':True},
                                  lock=threading.RLock(),fresh=Mock(return_value=True))
        host = SimpleNamespace(service=service,audit=Mock(),armed=True,uninterrupted_gameplay=True,
            runtime=SimpleNamespace(controller=SimpleNamespace(terminal_receipt=None)),
            native=Mock(),control=Mock(),core_status=Mock(return_value={'ready':True}),
            live_media_ready=Mock(return_value=True),watchdog_stop=Mock())
        cycle = LiveCycle(host,clock=lambda:now[0]);cycle.start()
        host.watchdog_stop.side_effect = cycle.attention
        cycle.tick()
        now[0] = 181;service.snapshot['frame'] += 5430
        self.assertTrue(cycle.tick())
        host.watchdog_stop.assert_called_once_with('COMBAT_NO_DAMAGE_PROGRESS')
        self.assertTrue(cycle.status()['alert']['component_repair_requested'])
        self.assertFalse(cycle.status()['alert']['game_pause_requested'])
        cycle.tick()
        self.assertEqual(host.watchdog_stop.call_count,1)
        host.control.assert_not_called();host.native.pause.assert_not_called()
        self.assertTrue(host.armed)


class QuietCombatBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.view = observation()
        self.decision = {'connected':True,'pending':False}
        self.controller = {'armed':True,'manual_override':False,'strategy':{'pending':None,'executing':None},
                           'live_cycle':{'phase':'playing'}}
        self.core = {'ready':True,'automatic':True,'busy':False}

    def allowed(self):
        return quiet_combat_boundary(self.view,self.decision,self.controller,self.core)

    def test_only_fresh_distant_stationary_unpaused_idle_combat_is_eligible(self):
        self.assertTrue(self.allowed())
        for container,key,value in [(self.decision,'pending',True),(self.controller,'manual_override',True),
                                    (self.controller,'armed',False),(self.core,'busy',True),
                                    (self.core,'automatic',False),(self.view,'connected',False)]:
            old=container[key];container[key]=value
            self.assertFalse(self.allowed(),key)
            container[key]=old

    def test_pending_execution_nearby_threats_motion_and_pause_veto_migration(self):
        self.controller['strategy']['executing'] = {'id':'existing-plan'}
        self.assertFalse(self.allowed());self.controller['strategy']['executing']=None
        self.view['data']['enemies'][0]['vel']['x'] = 1
        self.assertFalse(self.allowed());self.view['data']['enemies'][0]['vel']['x']=0
        self.view['data']['projectiles'] = [{'pos':{'x':210,'y':280}}]
        self.assertFalse(self.allowed());self.view['data']['projectiles']=[]
        self.view['data']['room']['paused'] = True
        self.assertFalse(self.allowed())

    def test_full_observation_period_is_required_after_any_veto(self):
        guard=CombatProgress(timeout_seconds=10)
        self.assertFalse(guard.update(self.view,enabled=self.allowed(),now=0))
        self.view['data']['frame'] += 150
        self.assertFalse(guard.update(self.view,enabled=False,now=5))
        self.view['data']['frame'] += 150
        self.assertFalse(guard.update(self.view,enabled=self.allowed(),now=10))
        self.view['data']['frame'] += 301
        self.assertTrue(guard.update(self.view,enabled=self.allowed(),now=20.1))


if __name__ == '__main__':
    unittest.main()
