"""Real-ending navigation keeps file protection and explicit human ownership."""
import threading
import unittest
from unittest.mock import Mock

from integration.issac.common import AdmissionError
from integration.issac.native_game import NativeGame
import test_live_cycle as fixtures


class EndingMenuCycleTests(unittest.TestCase):
    setUp=fixtures.LiveCycleTests.setUp
    proof=fixtures.LiveCycleTests.proof
    end=fixtures.LiveCycleTests.end

    def test_victory_title_file3_and_startup_use_normal_keys_then_new_seed(self):
        self.end(victory=True)
        self.host.native.progress.return_value={'slot':3,'readonly':False}
        self.host.native.observe.return_value={**self.living,'players':0,'hp':0,'seed':0}
        pages=[{'page':'title'},{'page':'file_select','selected_file':2},
               {'page':'file_select','selected_file':3},{'page':'unknown'},{'page':'unknown'}]
        self.host.native.menu_observation.side_effect=pages
        for i in range(len(pages)):
            self.now+=10 if i==0 else 3
            self.cycle.tick()
        self.assertEqual([call.args[0] for call in self.host.native.menu_key.call_args_list],
                         ['enter','right','enter','enter','enter'])
        self.host.native.observe.return_value={**self.living,'seed':456}
        self.now+=3;self.cycle.tick()
        self.assertEqual(self.cycle.phase,'binding_new_run')
        self.host.native.install_controller.assert_called_once_with()
        self.host.service.snapshot['identity']={**self.identity,'seed':456,'bridge':'new'}
        self.now+=1;self.cycle.tick()
        self.assertEqual(self.cycle.completed_runs,1)
        self.assertEqual(self.cycle.phase,'playing')

    def test_unknown_ending_page_without_file3_proof_never_receives_enter(self):
        self.end(victory=True);self.now+=10;self.cycle.tick()
        self.host.native.menu_key.assert_called_once_with('space')

    def test_file1_or_file2_can_only_move_highlight_never_confirm(self):
        self.end(victory=True)
        for selected in (1,2):
            self.host.native.menu_observation.return_value={'page':'file_select','selected_file':selected}
            self.assertEqual(self.cycle.ending_menu_key({'slot':3,'readonly':False}),'right')

    def test_stale_file3_proof_cannot_confirm_wrong_or_readonly_native_slot(self):
        self.end(victory=True)
        self.host.native.menu_observation.return_value={'page':'file_select','selected_file':3}
        self.cycle.ending_menu_key({'slot':3,'readonly':False})
        self.host.native.menu_observation.return_value={'page':'unknown'}
        for progress in ({'slot':1,'readonly':False},{'slot':3,'readonly':True}):
            with self.assertRaisesRegex(AdmissionError,'ENDING_NATIVE_WRITABLE_SLOT3_REQUIRED'):
                self.cycle.ending_menu_key(progress)

    def test_slot3_startup_is_bounded_and_return_to_title_revokes_file_proof(self):
        self.end(victory=True);progress={'slot':3,'readonly':False}
        self.host.native.menu_observation.return_value={'page':'file_select','selected_file':3}
        self.cycle.ending_menu_key(progress)
        self.host.native.menu_observation.return_value={'page':'unknown'}
        for _ in range(4):self.assertEqual(self.cycle.ending_menu_key(progress),'enter')
        with self.assertRaisesRegex(AdmissionError,'BOUNDED_ENDING_SLOT3_STARTUP_EXHAUSTED'):
            self.cycle.ending_menu_key(progress)
        self.host.native.menu_observation.return_value={'page':'title'}
        self.assertEqual(self.cycle.ending_menu_key(progress),'enter')
        self.host.native.menu_observation.return_value={'page':'unknown'}
        self.assertEqual(self.cycle.ending_menu_key(progress),'space')

    def test_actual_f8_during_ending_cancels_every_retry(self):
        self.end(victory=True);self.now+=10
        self.host.native.manual_override.return_value=True
        self.cycle.tick()
        self.assertFalse(self.cycle.enabled)
        self.assertEqual(self.cycle.phase,'operator_paused')
        self.host.native.menu_key.assert_not_called()

    def test_terminal_callback_with_real_human_override_preserves_it(self):
        self.host.native.observe.return_value={**self.living,'dead':False}
        self.host.runtime.controller.terminal_receipt=self.proof(is_game_over=False,manual_override=True)
        self.cycle.tick()
        self.assertFalse(self.cycle.enabled)
        self.assertFalse(self.host.armed)
        self.assertEqual(self.cycle.phase,'operator_paused')
        self.host.native.menu_key.assert_not_called()


class NativeManualOwnershipTests(unittest.TestCase):
    def fixture(self,value):
        native=object.__new__(NativeGame)
        native.lock=threading.RLock();native.verify_process=Mock();native.rpc=Mock(return_value=value)
        return native

    def test_native_flag_is_read_in_menus_and_requires_an_explicit_boolean(self):
        self.assertTrue(self.fixture('true').manual_override())
        self.assertFalse(self.fixture('false').manual_override())
        for value in ('nil','unknown','',None,{}):
            with self.assertRaisesRegex(AdmissionError,'CURRENT_NATIVE_MANUAL_OWNER_REQUIRED'):
                self.fixture(value).manual_override()


if __name__=='__main__':unittest.main()
