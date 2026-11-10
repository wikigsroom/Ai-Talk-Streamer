"""Replay real menu frames and test that unconfirmed slots never start a run."""
from pathlib import Path
import io
import json
import unittest
from unittest.mock import Mock, patch

from integration.issac.common import AdmissionError
from integration.issac.live_supervisor import LiveSupervisor
from integration.issac.menu_observation import recognize_menu

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent/'fixtures'


class MenuRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.signature = json.loads((ROOT/'configs/issac/menu-signatures.json').read_text('utf8'))

    def test_separate_real_native_file_frames_identify_all_three_highlights(self):
        for slot in range(1, 4):
            with self.subTest(slot=slot):
                result = recognize_menu((FIXTURES/f'menu-file{slot}.jpg').read_bytes(), self.signature)
                self.assertEqual((result['page'], result['selected_file']), ('file_select', slot))

    def test_actual_title_is_not_mistaken_for_a_file(self):
        result = recognize_menu((FIXTURES/'menu-title.jpg').read_bytes(), self.signature)
        self.assertEqual(result['page'], 'title')
        self.assertIsNone(result['selected_file'])

    def test_film_like_paper_and_black_transition_authorize_nothing(self):
        from PIL import Image
        for color in ('black', '#99918c', 'white'):
            image = Image.new('RGB', (960, 540), color)
            output = io.BytesIO(); image.save(output, format='JPEG')
            result = recognize_menu(output.getvalue(), self.signature)
            self.assertEqual(result['page'], 'unknown')
            self.assertIsNone(result['selected_file'])

    def test_header_without_unambiguous_highlight_cannot_select_a_slot(self):
        from PIL import Image
        image = Image.open(FIXTURES/'menu-file1.jpg').convert('RGB')
        for rect in self.signature['file_paper_regions']:
            image.paste((145, 145, 145), tuple(rect))
        output = io.BytesIO(); image.save(output, format='JPEG')
        self.assertEqual(recognize_menu(output.getvalue(), self.signature)['page'], 'unknown')


class NativeMenuRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now, self.slot, self.players = 0., 0, 0
        self.keys, self.confirmed_slot, self.selected = [], 3, 1
        self.owner = object.__new__(LiveSupervisor)
        self.owner.root = ROOT
        self.owner.audit = Mock(); self.owner.report = Mock()
        self.owner.game_menu = Mock(side_effect=self.menu)
        self.pages = ['unknown', 'unknown', 'title']
        self.owner.api = Mock(side_effect=self.api)

    def menu(self):
        page = self.pages.pop(0) if self.pages else 'file_select'
        return {'page': page, 'selected_file': self.selected if page == 'file_select' else None,
                'native_frame_sha256': 'real-frame'}

    def observe(self):
        return {'progress': {'slot': self.slot, 'readonly': False},
                'observation': {'players': self.players, 'dead': False}}

    def api(self, port, path, body=None, **kwargs):
        if port == 9541:return {}
        action = body['action']
        if action == 'observe':return self.observe()
        if action == 'menu':
            key = body['key']; self.keys.append(key)
            if key == 'right': self.selected = self.selected % 3+1
            if key == 'enter':
                if self.slot == 0:self.slot = self.confirmed_slot
                else:self.players = 1
        return {}

    def sleep(self, seconds):self.now += seconds

    def restore(self):
        with patch('integration.issac.live_supervisor.time.monotonic', side_effect=lambda: self.now), \
             patch('integration.issac.live_supervisor.time.sleep', side_effect=self.sleep), \
             patch('integration.issac.live_supervisor.read_json', return_value={'processes': [{'name': 'isaac-game', 'pid': 42}]}), \
             patch('integration.issac.record_focus.game_foreground'), \
             patch('integration.issac.saves.SaveProtection'):
            self.owner.restore_game()

    def test_film_waits_then_actual_title_and_highlight_restore_slot3(self):
        self.restore()
        self.assertEqual(self.keys, ['space', 'right', 'right', 'enter', 'enter'])
        self.assertGreaterEqual(self.now, 6)
        self.owner.api.assert_any_call(9534, '/control', {'action': 'install'}, timeout=20)

    def test_already_highlighted_file3_is_not_rotated_to_file1(self):
        self.selected = 3; self.pages = []
        self.restore()
        self.assertEqual(self.keys, ['enter', 'enter'])

    def test_unrecognized_frames_never_receive_a_confirm_key(self):
        self.owner.game_menu.side_effect = None
        self.owner.game_menu.return_value = {'page': 'unknown', 'selected_file': None}
        with self.assertRaisesRegex(AdmissionError, 'MENU_NOT_RECOGNIZED'):self.restore()
        self.assertEqual(self.keys, [])

    def test_wrong_native_slot_rejects_continue_even_after_visual_confirmation(self):
        self.confirmed_slot = 1
        with self.assertRaisesRegex(AdmissionError, 'SLOT3_NOT_CONFIRMED'):self.restore()
        self.assertEqual(self.keys.count('enter'), 1)
        self.assertEqual(self.players, 0)
        self.assertFalse(any(c.args[2] == {'action': 'install'} for c in self.owner.api.call_args_list if len(c.args) > 2))

    def test_nonfresh_slot_cannot_be_automatically_navigated(self):
        self.slot = 2
        with self.assertRaisesRegex(AdmissionError, 'FRESH_GAME_TITLE'):self.restore()
        self.assertEqual(self.keys, [])


if __name__ == '__main__':unittest.main()
