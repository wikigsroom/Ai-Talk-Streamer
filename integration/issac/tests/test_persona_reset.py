from pathlib import Path
import tempfile
import unittest
from integration.issac.reset_persona import clear_dsh_state
from integration.issac.common import AdmissionError


class MemoryResetScope(unittest.TestCase):
    def test_clear_old_dsh_memory_keeps_live_recorder_and_other_state_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)
            for name in ['dsh-home/sessions/old.jsonl','stream.sqlite3','stream.sqlite3-wal','stream.sqlite3-shm',
                         'livehime/profile/scene.json','platforms/settings.json','game-events.sqlite3','current-mode.json']:
                target=state/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(name.encode())
            with (state/'livehime/profile/scene.json').open('rb') as active_recorder:
                clear_dsh_state(state)
                self.assertEqual(active_recorder.read(),b'livehime/profile/scene.json')
            self.assertFalse((state/'dsh-home').exists());self.assertFalse((state/'stream.sqlite3').exists())
            for name in ['livehime/profile/scene.json','platforms/settings.json','game-events.sqlite3','current-mode.json']:
                self.assertEqual((state/name).read_bytes(),name.encode())

    def test_all_targets_are_checked_before_deleting_any_old_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder);(state/'dsh-home').mkdir();(state/'dsh-home/old').write_text('old')
            (state/'stream.sqlite3').mkdir()
            with self.assertRaises(AdmissionError):clear_dsh_state(state)
            self.assertEqual((state/'dsh-home/old').read_text(),'old')
