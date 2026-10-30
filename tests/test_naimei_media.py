"""Validate real sample accounting, stale generations and character isolation."""
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from integration.naimei_media import NML1, parse_source, SpeechMapping, CommandFence, SILENCE, packet
from integration.character_identity import character_identity
from integration.naimei_text import spoken_text, segments

ROOT = Path(__file__).resolve().parents[1]


def source(offset=0, epoch=7, flags=1):
    jpeg = b'\xff\xd8\xff\xd9'
    return parse_source(NML1.pack(b'NML1', 1, len(jpeg), 16000, .04, epoch, flags, offset) + jpeg + SILENCE)


def command(generation=2):
    return {'request_id': 'req-naimei', 'utterance_id': 'utt-naimei', 'runtime_epoch': 1, 'generation': generation, 'text': '你好，我是奶妹。'}


class MediaTests(unittest.TestCase):
    def test_partial_final_frame_counts_only_valid_audio(self):
        mapping = SpeechMapping(command(), 7, 800)
        first = mapping.range_for(source(), 10, 'transport')
        last = mapping.range_for(source(640), 11, 'transport')
        self.assertEqual(first['ranges'][0]['sample_count'], 640)
        self.assertFalse(first['final'])
        self.assertEqual(last['ranges'][0]['sample_count'], 160)
        self.assertTrue(last['final'])
        self.assertEqual(mapping.next_offset, 800)

    def test_idle_and_other_source_cannot_advance_speech(self):
        mapping = SpeechMapping(command(), 7, 800)
        self.assertIsNone(mapping.range_for(source(0xFFFFFFFF, flags=4), 10, 'transport'))
        self.assertIsNone(mapping.range_for(source(epoch=8), 11, 'transport'))
        self.assertEqual(mapping.next_offset, 0)

    def test_missing_audio_is_rejected_instead_of_acknowledged(self):
        mapping = SpeechMapping(command(), 7, 1920)
        mapping.range_for(source(), 10, 'transport')
        with self.assertRaisesRegex(ValueError, 'NOT_CONTIGUOUS'):
            mapping.range_for(source(1280), 11, 'transport')

    def test_quiet_gated_frame_still_accounts_for_its_audio(self):
        mapping = SpeechMapping(command(), 7, 640)
        self.assertTrue(mapping.range_for(source(flags=2), 10, 'transport')['final'])

    def test_truncated_source_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_source(b'NML1')
        with self.assertRaisesRegex(ValueError, 'PAYLOAD'):
            parse_source(NML1.pack(b'NML1', 1, 4, 16000, .04, 7, 1, 0) + b'jpeg')

    def test_common_transport_preserves_pcm_and_sequence(self):
        data = packet(88, b'jpeg')
        self.assertEqual(len(data), 12 + 4 + 1280)
        self.assertEqual(data[12:16], b'jpeg')

    def test_cancel_fences_old_command_and_duplicate_start(self):
        fence = CommandFence()
        self.assertTrue(fence.speak(command()))
        self.assertFalse(fence.speak(command()))
        self.assertTrue(fence.cancel({'runtime_epoch': 1, 'new_generation': 3}))
        self.assertFalse(fence.matches(command()))
        with self.assertRaisesRegex(ValueError, 'STALE'):
            fence.speak(command())


class IdentityTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'state/test-tmp'
        path.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=path)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'configs/characters').mkdir(parents=True)
        for cid, name in [('female-a', '原角色'), ('naimei', '奶妹')]:
            (self.root / f'configs/characters/{cid}.json').write_text(json.dumps({'id': cid, 'name': name, 'persona_prompt': name}), encoding='utf-8')

    def test_active_character_is_selected_without_inheriting_legacy_identity(self):
        (self.root / 'configs/active-character.json').write_text('{"character_id":"naimei"}', encoding='utf-8')
        with patch.dict(os.environ, {'AVATAR_CHARACTER_ID': ''}):
            self.assertEqual(character_identity(root=self.root)['name'], '奶妹')
            self.assertEqual(character_identity('female-a', root=self.root)['name'], '原角色')

    def test_profile_cannot_escape_or_impersonate_another_character(self):
        with self.assertRaises(ValueError):
            character_identity('../female-a', root=self.root)
        (self.root / 'configs/characters/naimei.json').write_text('{"id":"female-a","name":"wrong","persona_prompt":"wrong"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'MISMATCH'):
            character_identity('naimei', root=self.root)


class TextTests(unittest.TestCase):
    def test_spoken_numbers_and_acronyms_keep_intended_reading(self):
        self.assertEqual(spoken_text('512×512，25fps，AI助手，0.25。'), '五百一十二乘五百一十二，二十五帧每秒，人工智能助手，零点二五。')

    def test_segmentation_never_drops_content(self):
        text = '今天先说一件小事。' * 40
        parts = segments(text, 40)
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(len(x) <= 40 for x in parts))


if __name__ == '__main__':
    unittest.main()
