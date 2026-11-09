from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from integration.issac.common import AdmissionError
from integration.issac.saves import SaveProtection


class SaveScanBoundaries(unittest.TestCase):
    def test_irrelevant_assets_skip_resolution_but_new_protected_files_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); game = root/'game'; game.mkdir()
            (game/'persistentgamedata1.dat').write_bytes(b'protected')
            guard = SaveProtection(root); guard.prepare([str(game)])
            asset = game/'sprites'; asset.mkdir()
            (asset/'enemy.png').write_bytes(b'not_a_save')
            original = Path.resolve
            def resolve(path, *args, **kwargs):
                if path.suffix.lower() == '.png': raise AssertionError('Unrelated asset resolved')
                return original(path, *args, **kwargs)
            with patch.object(Path, 'resolve', resolve):
                self.assertTrue(guard.verify()['protected_unchanged'])
            for name, expected in [('persistentgamedata2.dat','UNAUTHORIZED_SAVE_SLOT_CREATED'),
                                   ('unknown.sav','UNCLASSIFIED_SAVE_FILE_CREATED'),
                                   ('unknown.ini','UNCLASSIFIED_CONFIGURATION_FILE_CREATED')]:
                file = game/name; file.write_bytes(b'new')
                with self.assertRaisesRegex(AdmissionError, expected): guard.verify()
                file.unlink()
            (game/'persistentgamedata1.dat').write_bytes(b'changed')
            with self.assertRaisesRegex(AdmissionError,'PROTECTED_SAVE_CHANGED'): guard.verify()


if __name__ == '__main__': unittest.main()
