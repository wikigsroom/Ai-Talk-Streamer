"""Local record controls restore only the current proven game window."""
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from integration.issac.common import AdmissionError
from integration.issac.record_focus import RecordingHandoff,foreground,record_controls,caption_activate


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
        def owner(hwnd,ref):
            ref._obj.value=next(owners) if owners is not None else 9
            return 90 if hwnd==123 else 80
        user.GetWindowThreadProcessId.side_effect=owner
        user.GetForegroundWindow.side_effect=frames
        user.SetForegroundWindow.return_value=True
        user.AttachThreadInput.return_value=True;user.IsIconic.return_value=False
        kernel=Mock();kernel.GetCurrentThreadId.return_value=100
        stack.enter_context(patch('integration.issac.record_focus.ctypes.windll',SimpleNamespace(user32=user,kernel32=kernel),create=True))
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
            self.assertEqual([call.args for call in user.AttachThreadInput.call_args_list],
                [(100,80,True),(100,90,True),(100,90,False),(100,80,False)])

    def test_background_recovery_can_activate_owned_window_and_detaches_input_queues(self):
        with ExitStack() as stack:
            user=self.focus_fixture(stack,iter([8,8,123]))
            user.SetForegroundWindow.side_effect=[False,True]
            self.assertTrue(foreground(123,9)['foreground'])
            self.assertEqual([call.args for call in user.AttachThreadInput.call_args_list],
                [(100,80,True),(100,90,True),(100,90,False),(100,80,False)])
            user.ShowWindowAsync.assert_not_called()

    def test_input_queues_are_detached_even_when_activation_raises(self):
        with ExitStack() as stack:
            user=self.focus_fixture(stack,lambda:8);user.SetForegroundWindow.return_value=False
            user.BringWindowToTop.side_effect=RuntimeError('native activation failed')
            with self.assertRaisesRegex(RuntimeError,'activation failed'):foreground(123,9)
            self.assertEqual([call.args for call in user.AttachThreadInput.call_args_list][-2:],
                [(100,90,False),(100,80,False)])

    def test_only_minimized_owned_target_is_restored_before_retry(self):
        with ExitStack() as stack:
            user=self.focus_fixture(stack,iter([8,8,123]));user.IsIconic.return_value=True
            user.SetForegroundWindow.side_effect=[False,True]
            foreground(123,9)
            user.ShowWindowAsync.assert_called_once_with(123,9)


class NormalCaptionActivation(unittest.TestCase):
    def fixture(self):
        user=Mock();verify=Mock()
        def rect(hwnd,ref):
            box=ref._obj;box.left=100;box.top=100;box.right=1100;box.bottom=800
            return 1
        def hit(*args):args[-1]._obj.value=2;return 1
        def owner(hwnd,ref):ref._obj.value=9;return 90
        def cursor(ref):ref._obj.x=10;ref._obj.y=20;return 1
        user.GetWindowRect.side_effect=rect;user.GetAsyncKeyState.return_value=0
        user.SendMessageTimeoutW.side_effect=hit;user.WindowFromPoint.return_value=123
        user.GetWindowThreadProcessId.side_effect=owner;user.GetAncestor.return_value=123
        user.GetCursorPos.side_effect=cursor;user.SetCursorPos.return_value=True
        return user,verify

    def test_only_proven_visible_caption_gets_ordinary_click_and_cursor_restore(self):
        user,verify=self.fixture()
        self.assertTrue(caption_activate(user,123,9,verify))
        self.assertEqual([c.args for c in user.mouse_event.call_args_list],[(2,0,0,0,0),(4,0,0,0,0)])
        self.assertEqual([c.args for c in user.SetCursorPos.call_args_list],[(600,112),(10,20)])
        self.assertEqual(verify.call_count,2)

    def test_client_and_close_controls_are_never_clicked(self):
        for code in (1,8,9,20):
            user,verify=self.fixture()
            def hit(*args):args[-1]._obj.value=code;return 1
            user.SendMessageTimeoutW.side_effect=hit
            self.assertFalse(caption_activate(user,123,9,verify));user.mouse_event.assert_not_called()

    def test_occlusion_and_foreign_window_are_rejected_before_input(self):
        user,verify=self.fixture();user.WindowFromPoint.return_value=456
        user.GetAncestor.return_value=456
        self.assertFalse(caption_activate(user,123,9,verify));user.mouse_event.assert_not_called()
        user.SetCursorPos.assert_not_called()

    def test_pressed_modifier_or_mouse_prevents_synthetic_click(self):
        for held in (1,2,16,17,18,91,92):
            user,verify=self.fixture();user.GetAsyncKeyState.side_effect=lambda key:0x8000 if key==held else 0
            self.assertFalse(caption_activate(user,123,9,verify));user.mouse_event.assert_not_called()

    def test_failed_button_down_always_releases_mouse_and_restores_cursor(self):
        user,verify=self.fixture();user.mouse_event.side_effect=[RuntimeError('mouse rejected'),None]
        with self.assertRaisesRegex(RuntimeError,'mouse rejected'):caption_activate(user,123,9,verify)
        self.assertEqual([c.args for c in user.mouse_event.call_args_list],[(2,0,0,0,0),(4,0,0,0,0)])
        self.assertEqual(user.SetCursorPos.call_args.args,(10,20))


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


class RecordingLiveInterval(unittest.TestCase):
    def fixture(self,stack,kind='drink'):
        handoff=RecordingHandoff('owned-root');clock=[1001.0];count=[0]
        identity={'controller':'current','seed':123,'room':83,'stage':1,'bridge':'current','restart':0}
        handoff.pause_receipt={'pid':7,'created_at':100,'identity':identity,'control_revision':6};handoff.resume_confirmed=True
        studio={'ready':True,'natural_action':{'kind':kind,'control_revision':8,'identity':deepcopy(identity),
            'created_unix':1000,'expires_unix':1060,'native_receipt':{
                'normal_game_pause_acknowledged':True,'stable_frame':900,
                'native':{'frame':900,'paused':True,'dead':False,'players':1,'seed':123,'room':83,'stage':1}}}}
        def state():
            count[0]+=1
            live=kind=='drink' and count[0]>12
            return {'connected':True,'age_ms':30,'identity':deepcopy(identity),
                'data':{'frame':900+max(0,count[0]-12)*4,'room':{'paused':not live,'clear':True,'dead':False}}}
        def request(port,path,body=None):
            self.assertIsNone(body) # Waiting must never emit resume/rearm.
            if port==8062:return deepcopy(studio)
            live=kind=='drink' and count[0]>12
            return {'armed':live,'control_revision':9 if live else 8,'last_fault':None}
        handoff.state=Mock(side_effect=state);handoff.request=Mock(side_effect=request)
        stack.enter_context(patch('integration.issac.record_focus.game_owner',return_value=SimpleNamespace(pid=7,create_time=lambda:100)))
        stack.enter_context(patch('integration.issac.record_focus.time.monotonic',side_effect=lambda:clock[0]))
        stack.enter_context(patch('integration.issac.record_focus.time.time',side_effect=lambda:clock[0]))
        stack.enter_context(patch('integration.issac.record_focus.time.sleep',side_effect=lambda s:clock.__setitem__(0,clock[0]+s)))
        return handoff,studio

    def test_actual_drink_finishes_before_continuous_live_interval_without_controls(self):
        with ExitStack() as stack:
            handoff,_=self.fixture(stack);result=handoff.wait_live_interval()
        self.assertTrue(result['observed_live_progress']);self.assertEqual(len(result['verified_drinks']),1)
        self.assertGreater(result['state']['data']['frame'],905)

    def test_operator_pause_and_expired_drink_are_not_adopted(self):
        for kind in ('operator_pause','expired'):
            with ExitStack() as stack:
                handoff,studio=self.fixture(stack,kind)
                if kind=='expired':studio['natural_action'].update(kind='drink',expires_unix=1001)
                with self.assertRaisesRegex(AdmissionError,'UNVERIFIED_PAUSE'):handoff.wait_live_interval()

    def test_fault_or_changed_owner_is_rejected_without_waiting_or_controls(self):
        for defect in ('fault','owner','seed'):
            with ExitStack() as stack:
                handoff,_=self.fixture(stack)
                if defect=='fault':handoff.request=Mock(return_value={'last_fault':'GAME_BRIDGE_STALE'})
                if defect=='owner':handoff.pause_receipt['created_at']=99
                if defect=='seed':handoff.pause_receipt['identity']={**handoff.pause_receipt['identity'],'seed':999}
                with self.assertRaises(AdmissionError):handoff.wait_live_interval()
                if defect=='owner':handoff.request.assert_not_called()


if __name__=='__main__':unittest.main()
