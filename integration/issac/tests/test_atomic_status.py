from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration.issac.common import read_json, write_json


class AtomicStatus(unittest.TestCase):
    def test_transient_reader_lock_retries_without_exposing_partial_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'application.json'
            write_json(path, {'stage': 'running'})
            import os
            replace = os.replace
            calls = []
            def locked_then_release(source, target):
                calls.append(source)
                self.assertEqual(read_json(path), {'stage': 'running'})
                if len(calls) < 3:
                    error = PermissionError('reader sharing lock')
                    error.winerror = 5
                    raise error
                return replace(source, target)
            with patch('integration.issac.common.os.replace', side_effect=locked_then_release), patch('integration.issac.common.time.sleep'):
                write_json(path, {'stage': 'stopped'})
            self.assertEqual(len(calls), 3)
            self.assertEqual(read_json(path), {'stage': 'stopped'})
            self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_permanent_or_exhausted_error_preserves_old_file_and_cleans_only_own_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'application.json'
            write_json(path, {'stage': 'running'})
            sentinel = path.parent / 'another-writer.tmp'
            sentinel.write_bytes(b'preserve')
            for winerror, expected_calls in [(112, 1), (32, 8)]:
                error = OSError('bounded write failure')
                error.winerror = winerror
                with patch('integration.issac.common.os.replace', side_effect=error) as replace, patch('integration.issac.common.time.sleep'):
                    with self.assertRaises(OSError):
                        write_json(path, {'stage': 'stopped'})
                self.assertEqual(replace.call_count, expected_calls)
                self.assertEqual(read_json(path), {'stage': 'running'})
                self.assertEqual(list(path.parent.glob('*.tmp')), [sentinel])


if __name__ == '__main__':
    unittest.main()
