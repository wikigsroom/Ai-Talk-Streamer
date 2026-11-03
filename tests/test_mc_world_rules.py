"""NBT file fixtures, not real Minecraft rule or death acceptance."""
from pathlib import Path
import gzip
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from mc_world_rules import enable_keep_inventory, rule_span


def text(value):
    return struct.pack('>H', len(value)) + value


def fixture(value=b'false'):
    return (b'\x0a\x00\x00\x0a' + text(b'Data') + b'\x0a' + text(b'GameRules')
            + b'\x08' + text(b'keepInventory') + text(value) + b'\x00'
            + b'\x07' + text(b'unchanged') + struct.pack('>i', 5) + b'\x00\x01\xff\x03\x04'
            + b'\x00\x00')


class WorldRules(unittest.TestCase):
    def test_only_rule_bytes_change_and_original_backup_is_exact(self):
        with tempfile.TemporaryDirectory() as folder:
            path, backup = Path(folder) / 'level.dat', Path(folder) / 'backup'
            original = gzip.compress(fixture()); path.write_bytes(original)
            result = enable_keep_inventory(path, backup)
            self.assertTrue(result['changed'])
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(gzip.decompress(path.read_bytes()), fixture(b'true'))
            again = enable_keep_inventory(path, backup)
            self.assertFalse(again['changed'])

    def test_existing_backup_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path, backup = Path(folder) / 'level.dat', Path(folder) / 'backup'
            original = gzip.compress(fixture()); path.write_bytes(original); backup.write_bytes(b'preserve')
            with self.assertRaisesRegex(ValueError, 'BACKUP_ALREADY_EXISTS'):
                enable_keep_inventory(path, backup)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(backup.read_bytes(), b'preserve')

    def test_truncated_unknown_and_trailing_payloads_are_rejected(self):
        for raw in (fixture()[:-1], fixture() + b'\x00', b'\x08\x00\x00', fixture(b'unknown')):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError): rule_span(raw)


if __name__ == '__main__':
    unittest.main()
