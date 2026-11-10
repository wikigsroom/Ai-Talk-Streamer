"""Automatic drink pauses cannot become permanent operator takeovers."""
from copy import deepcopy
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock,patch

from integration.issac.common import AdmissionError
from integration.issac.strategy_host import StrategyHost
from integration.issac.live_supervisor import LiveSupervisor,SupervisorState


class NaturalPauseCycle(unittest.TestCase):
    def host(self):
        owner=object.__new__(StrategyHost)
        owner.action_lock=threading.RLock();owner.armed=True;owner.control_revision=8
        owner.service=SimpleNamespace(raw={'strategy':{'manual_override':False}})
        owner.lifecycle=SimpleNamespace(enabled=True,phase='playing')
        def change(phase,reason):owner.lifecycle.phase=phase
        def start():owner.lifecycle.enabled=True;owner.lifecycle.phase='playing'
        owner.lifecycle.change=Mock(side_effect=change);owner.lifecycle.start=Mock(side_effect=start)
        def control(body,*,origin):
            self.assertEqual(origin,'lifecycle');owner.armed=body['enabled'];owner.control_revision+=1
            return {'armed':owner.armed,'control_revision':owner.control_revision}
        owner.control=Mock(side_effect=control)
        return owner

    def test_completed_drink_restores_only_its_own_revision_and_lifecycle(self):
        owner=self.host()
        paused=owner.action({'action':'natural_pause','expected_revision':8})
        self.assertFalse(paused['armed']);self.assertEqual(owner.lifecycle.phase,'natural_paused')
        self.assertFalse(owner.lifecycle.enabled)
        resumed=owner.action({'action':'natural_resume','expected_revision':paused['control_revision']})
        self.assertTrue(resumed['armed']);self.assertEqual(owner.lifecycle.phase,'playing')
        owner.lifecycle.start.assert_called_once_with()

    def test_later_human_pause_or_f8_cannot_be_undone_by_drink_resume(self):
        for phase,manual,revision in [('operator_paused',False,9),('natural_paused',True,9),('natural_paused',False,10)]:
            with self.subTest(phase=phase,manual=manual,revision=revision):
                owner=self.host();owner.action({'action':'natural_pause','expected_revision':8})
                owner.lifecycle.phase=phase;owner.service.raw['strategy']['manual_override']=manual
                owner.control_revision=revision;owner.control.reset_mock()
                with self.assertRaises(AdmissionError):owner.action({'action':'natural_resume','expected_revision':9})
                owner.control.assert_not_called();owner.lifecycle.start.assert_not_called()

    def test_failed_automatic_resume_keeps_a_recoverable_nonhuman_pause(self):
        owner=self.host();owner.action({'action':'natural_pause','expected_revision':8})
        owner.control.side_effect=AdmissionError('CORE_NOT_READY')
        with self.assertRaisesRegex(AdmissionError,'CORE_NOT_READY'):
            owner.action({'action':'natural_resume','expected_revision':9})
        self.assertEqual(owner.lifecycle.phase,'natural_paused');self.assertFalse(owner.lifecycle.enabled)

    def test_natural_pause_requires_revision_and_cannot_adopt_human_pause(self):
        owner=self.host()
        with self.assertRaisesRegex(AdmissionError,'OWNERSHIP'):
            owner.action({'action':'natural_pause'})
        owner.control.assert_not_called()
        owner.armed=False;owner.lifecycle.enabled=False;owner.lifecycle.phase='operator_paused'
        with self.assertRaisesRegex(AdmissionError,'OWNERSHIP'):
            owner.action({'action':'natural_pause','expected_revision':8})

    def supervisor(self):
        from integration.issac.tests.test_readiness import DrinkReadiness
        sample=deepcopy(DrinkReadiness().sample())
        sample['game'].update(manual_override=False,live_cycle={'enabled':False,'phase':'natural_paused','phase_seconds':30})
        owner=object.__new__(LiveSupervisor)
        def api(port,path):
            return {(9541,'/status'):{'stage':'running_candidate_not_accepted'},
                (9534,'/status'):sample['game'],(8062,'/health'):sample['studio'],
                (9532,'/query?topic=state'):sample['state'],
                (3104,'/api/dsh/issac/core/status'):{'ready':True},
                (3104,'/api/dsh/platforms'):{'output_player':{'connected':True,'audio_state':'running'}}}[(port,path)]
        owner.api=Mock(side_effect=api)
        return owner,sample

    def test_verified_current_drink_is_healthy_and_expiry_requests_restart(self):
        owner,sample=self.supervisor()
        with patch('integration.issac.readiness.time.time',return_value=1001):
            self.assertEqual(owner.healthy(),(True,False,False))
        with patch('integration.issac.readiness.time.time',return_value=1061):
            healthy,manual,requested=owner.healthy()
        self.assertEqual((healthy,manual,requested),(False,False,False))
        now=[0];guard=SupervisorState(clock=lambda:now[0]);guard.assess(healthy,True,manual_pause=manual)
        now[0]=21;self.assertEqual(guard.assess(healthy,True,manual_pause=manual),'restart_owned_stack')

    def test_human_takeover_during_drink_keeps_priority_over_recovery(self):
        for field in ['phase','native_f8']:
            with self.subTest(field=field):
                owner,sample=self.supervisor()
                if field=='phase':sample['game']['live_cycle']['phase']='operator_paused'
                else:sample['game']['manual_override']=True
                self.assertEqual(owner.healthy(),(False,True,False))

    def media_host(self):
        owner=self.host();owner.pause_pending=False
        owner.lifecycle.fault=Mock()
        def attention(reason):owner.lifecycle.enabled=False;owner.lifecycle.phase='restart_required'
        owner.lifecycle.attention=Mock(side_effect=attention)
        def control(*args,**kwargs):
            owner.armed=False
            return {'armed':False,'native_receipt':{'normal_game_pause_acknowledged':True}}
        owner.control=Mock(side_effect=control)
        return owner

    def test_irreversible_media_failure_requests_normal_pause_and_full_restart(self):
        owner=self.media_host();result=owner.action({'action':'media_fault'})
        owner.control.assert_called_once_with({'enabled':False,'live':False},origin='lifecycle')
        self.assertTrue(result['native_receipt']['normal_game_pause_acknowledged']);self.assertFalse(result['armed'])
        self.assertEqual(owner.lifecycle.phase,'restart_required')

    def test_media_pause_ack_failure_still_requests_restart_and_reports_pending(self):
        owner=self.media_host();owner.control.side_effect=AdmissionError('NATIVE_REPLY_LOST')
        result=owner.action({'action':'media_fault'})
        self.assertTrue(result['pause_confirmation_pending'])
        self.assertEqual(owner.lifecycle.phase,'restart_required')

    def test_media_failure_cannot_erase_a_human_pause_or_native_takeover(self):
        for phase,manual in [('operator_paused',False),('playing',True)]:
            with self.subTest(phase=phase,manual=manual):
                owner=self.media_host();owner.lifecycle.phase=phase
                owner.service.raw['strategy']['manual_override']=manual
                self.assertTrue(owner.action({'action':'media_fault'})['operator_pause_preserved'])
                owner.control.assert_not_called();owner.lifecycle.attention.assert_not_called()
