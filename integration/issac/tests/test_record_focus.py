"""Local record controls restore only the current proven game window."""
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from integration.issac.record_focus import record_controls


class RecordingFocus(unittest.TestCase):
    def test_focus_restores_on_success_and_on_record_control_error(self):
        for fails in (False,True):
            client=Mock(root='owned-root');client.owner.return_value={'pid':9}
            client.native_window.return_value={'windows':[{'hwnd':123,'pid':9}]}
            process=SimpleNamespace(pid=7,create_time=lambda:100)
            calls=[]
            with ExitStack() as stack:
                stack.enter_context(patch('integration.issac.record_focus.game_owner',return_value=process))
                stack.enter_context(patch('integration.issac.record_focus.foreground',side_effect=lambda *a:calls.append(('official',a))))
                stack.enter_context(patch('integration.issac.record_focus.game_foreground',side_effect=lambda *a:calls.append(('game',a))))
                try:
                    with record_controls(client):
                        calls.append(('normal_record_click',None))
                        if fails:raise RuntimeError('record writer unavailable')
                except RuntimeError:self.assertTrue(fails)
            self.assertEqual([r[0] for r in calls],['official','normal_record_click','game'])


if __name__=='__main__':unittest.main()
