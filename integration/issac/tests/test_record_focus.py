"""Local record controls restore only the current proven game window."""
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from integration.issac.common import AdmissionError
from integration.issac.record_focus import RecordingHandoff,foreground,record_controls


class RecordingFocus(unittest.TestCase):
    def test_focus_restores_on_success_and_on_record_control_error(self):
        for fails in (False,True):
            client=Mock(root='owned-root');client.owner.return_value={'pid':9,'created_at':101}
            client.native_window.return_value={'windows':[{'hwnd':123,'pid':9}]}
            process=SimpleNamespace(pid=7,create_time=lambda:100)
            calls=[]
            with ExitStack() as stack:
                stack.enter_context(patch('integration.issac.record_focus.game_owner',return_value=process))
                stack.enter_context(patch('integration.issac.record_focus.foreground',side_effect=lambda *a,**k:calls.append(('official',a))))
                stack.enter_context(patch('integration.issac.record_focus.game_foreground',side_effect=lambda *a:calls.append(('game',a))))
                try:
                    with record_controls(client):
                        calls.append(('normal_record_click',None))
                        if fails:raise RuntimeError('record writer unavailable')
                except RuntimeError:self.assertTrue(fails)
            self.assertEqual([r[0] for r in calls],['official','normal_record_click','game'])

    def focus_fixture(self,stack,frames,owners=None):
        user=Mock();clock=[0.0]
        def owner(hwnd,ref):ref._obj.value=next(owners) if owners is not None else 9
        user.GetWindowThreadProcessId.side_effect=owner
        user.GetForegroundWindow.side_effect=frames
        user.SetForegroundWindow.return_value=True
        stack.enter_context(patch('integration.issac.record_focus.ctypes.windll',SimpleNamespace(user32=user),create=True))
        stack.enter_context(patch('integration.issac.record_focus.time.monotonic',side_effect=lambda:clock[0]))
        stack.enter_context(patch('integration.issac.record_focus.time.sleep',side_effect=lambda s:clock.__setitem__(0,clock[0]+s)))
        return user

    def test_accepted_foreground_is_confirmed_after_input_queue_applies_it(self):
        with ExitStack() as stack:
            user=self.focus_fixture(stack,iter([8,8,8,123]))
            result=foreground(123,9)
            self.assertTrue(result['foreground']);self.assertGreaterEqual(result['confirmation_seconds'],.04)
            user.SetForegroundWindow.assert_called_once_with(123)

    def test_focus_that_never_arrives_is_bounded_and_rejected(self):
        with ExitStack() as stack:
            self.focus_fixture(stack,lambda:8)
            with self.assertRaisesRegex(AdmissionError,'FOREGROUND_NOT_CONFIRMED'):foreground(123,9,timeout=.08)

    def test_window_owner_change_during_focus_wait_is_rejected(self):
        with ExitStack() as stack:
            self.focus_fixture(stack,lambda:8,iter([9,9,10]))
            with self.assertRaisesRegex(AdmissionError,'OWNED_FOCUS_WINDOW_CHANGED'):foreground(123,9)

    def test_reused_process_lifetime_and_denied_activation_are_rejected(self):
        with ExitStack() as stack:
            self.focus_fixture(stack,lambda:8)
            process=Mock();process.create_time.side_effect=[100,101]
            stack.enter_context(patch('psutil.Process',return_value=process))
            with self.assertRaisesRegex(AdmissionError,'OWNED_FOCUS_PROCESS_CHANGED'):foreground(123,9,created_at=100)
        with ExitStack() as stack:
            user=self.focus_fixture(stack,lambda:8);user.SetForegroundWindow.return_value=False
            with self.assertRaisesRegex(AdmissionError,'FOREGROUND_NOT_CONFIRMED'):foreground(123,9)


class ExplicitRecordingHandoff(unittest.TestCase):
    def fixture(self):
        handoff=RecordingHandoff('owned-root');self.actions=[]
        identity={'seed':123,'room':84,'bridge':'native'}
        self.status={'armed':True,'save_slot':3,'control_revision':8,'pause_confirmation_pending':False}
        pause={'normal_game_pause_acknowledged':True,'pause_hold':True,'stable_frame':50,
               'pause_input_ack':{'id':'recording-pause'}}
        def request(port,path,body=None):
            if path=='/status':return deepcopy(self.status)
            self.assertEqual(path,'/control');self.assertEqual(body['expected_revision'],self.status['control_revision'])
            self.actions.append(body['action']);self.status['control_revision']+=1
            self.status['armed']=body['action']=='resume'
            return {**self.status,'native_receipt':deepcopy(pause)}
        handoff.request=Mock(side_effect=request)
        self.active={'identity':identity,'data':{'frame':50,'room':{'paused':False,'dead':False}}}
        self.paused={'identity':identity,'data':{'frame':50,'room':{'paused':True,'dead':False,'pause_ack':{'id':'recording-pause'}}}}
        advanced=deepcopy(self.active);advanced['data']['frame']=57
        handoff.state=Mock(side_effect=[deepcopy(self.active),deepcopy(self.paused),deepcopy(self.paused),advanced])
        return handoff

    def owners(self,stack):
        stack.enter_context(patch('integration.issac.record_focus.game_owner',return_value=SimpleNamespace(pid=7,create_time=lambda:100)))
        return stack.enter_context(patch('integration.issac.record_focus.game_foreground'))

    def test_explicit_start_resumes_its_own_confirmed_pause_and_observes_progress(self):
        handoff=self.fixture()
        with ExitStack() as stack:
            focused=self.owners(stack);handoff.pause();result=handoff.resume()
        self.assertTrue(result['game_advanced']);self.assertEqual(self.actions,['pause','resume']);focused.assert_called_once()
        with self.assertRaisesRegex(AdmissionError,'UNUSED_RECORDING_OWNED_PAUSE_REQUIRED'):handoff.resume()

    def test_preexisting_pause_is_not_resumed_or_adopted(self):
        handoff=self.fixture();self.status['armed']=False
        with ExitStack() as stack:
            self.owners(stack)
            with self.assertRaisesRegex(AdmissionError,'ACTIVE_AUTOMATIC_RUN_REQUIRED'):handoff.pause()
        self.assertEqual(self.actions,[])

    def test_operator_change_or_different_pause_ack_prevents_resume(self):
        for changed in ('revision','ack'):
            handoff=self.fixture()
            with ExitStack() as stack:
                self.owners(stack);handoff.pause()
                if changed=='revision':self.status['control_revision']+=1
                else:
                    state=deepcopy(self.paused);state['data']['room']['pause_ack']['id']='operator-pause'
                    handoff.state=Mock(return_value=state)
                with self.assertRaisesRegex(AdmissionError,'PAUSE_NO_LONGER_CURRENT'):handoff.resume()
            self.assertEqual(self.actions,['pause'])

    def test_ui_error_leaves_owned_pause_and_expired_handoff_never_resumes(self):
        handoff=self.fixture()
        with ExitStack() as stack:
            self.owners(stack);handoff.pause()
            handoff.pause_receipt['created_monotonic']-=21
            with self.assertRaisesRegex(AdmissionError,'OWNER_OR_DEADLINE_CHANGED'):handoff.resume()
        self.assertEqual(self.actions,['pause'])


if __name__=='__main__':unittest.main()
