"""Windows filesystem fixtures; not a real game startup or continuous log budget test."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import os
import tempfile
import unittest
from native_log_archive import CONSOLE_LIMIT_BYTES, prepare_console_log
from native_operation import OperationError


@unittest.skipUnless(os.name == 'nt', 'Native Windows sharing and rename semantics required')
class NativeLogArchiveTests(unittest.TestCase):
    def setUp(self):
        self.fixture_parent = Path(os.environ.get('MC_NATIVE_LOG_FIXTURE_ROOT',
                Path(__file__).resolve().parents[1] / 'outputs/native-log-fixtures')).resolve()
        self.fixture_parent.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix='console-', dir=self.fixture_parent)
        self.root = Path(self.directory.name).resolve()
        self.assertTrue(self.root.is_relative_to(self.fixture_parent))
        self.path = self.root / 'runtime/minecraft/fixture/work/logs/application-console.log'
        self.path.parent.mkdir(parents=True)

    def tearDown(self):
        # Verify the resolved target before TemporaryDirectory's recursive cleanup.
        self.assertTrue(self.root.is_relative_to(self.fixture_parent))
        self.directory.cleanup()

    def test_small_or_absent_log_is_preserved_for_append(self):
        absent = prepare_console_log(self.root, self.path)
        self.assertFalse(absent['rotated']); self.assertFalse(self.path.exists())
        self.assertEqual(absent['maximum_bytes'], CONSOLE_LIMIT_BYTES)
        self.path.write_bytes(b'original\n')
        before = self.path.stat()
        report = prepare_console_log(self.root, self.path, maximum_bytes=16)
        self.assertFalse(report['rotated']); self.assertEqual(self.path.read_bytes(), b'original\n')
        self.assertEqual(self.path.stat().st_ino, before.st_ino)

    def test_archive_keeps_the_original_file_and_opens_a_new_current_log(self):
        original = b'old-console\x00\xff\n' * 4
        self.path.write_bytes(original); before = self.path.stat()
        report = prepare_console_log(self.root, self.path, maximum_bytes=16)
        archive = self.root / report['archive_path']
        self.assertTrue(report['rotated']); self.assertFalse(self.path.exists())
        self.assertEqual(archive.read_bytes(), original); self.assertEqual(archive.stat().st_ino, before.st_ino)
        self.assertEqual(archive.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertFalse(report['existing_bytes_deleted_or_truncated'])
        self.assertFalse(report['full_file_digest_computed'])
        with self.path.open('ab') as stream:
            stream.write(b'new-session\n')
        self.assertEqual(self.path.read_bytes(), b'new-session\n')
        self.assertEqual(archive.read_bytes(), original)

    def test_repeated_archives_do_not_replace_or_delete_earlier_sessions(self):
        reports = []
        for text in [b'first-log', b'second-log']:
            self.path.write_bytes(text); reports.append(prepare_console_log(self.root, self.path, maximum_bytes=8))
        self.assertNotEqual(reports[0]['archive_path'], reports[1]['archive_path'])
        self.assertEqual((self.root / reports[0]['archive_path']).read_bytes(), b'first-log')
        self.assertEqual((self.root / reports[1]['archive_path']).read_bytes(), b'second-log')

    def test_wrong_scope_and_nonregular_file_are_rejected(self):
        for path in [self.root / 'application-console.log', self.path.with_name('other.log'), self.root.parent / 'outside.log']:
            with self.assertRaises(OperationError):
                prepare_console_log(self.root, path)
        self.path.mkdir()
        with self.assertRaises(OperationError):
            prepare_console_log(self.root, self.path)
        for limit in [0, -1, True, CONSOLE_LIMIT_BYTES + 1]:
            with self.assertRaises(OperationError):
                prepare_console_log(self.root, self.path, maximum_bytes=limit)

    def test_a_windows_reader_without_delete_sharing_blocks_rotation_without_losing_bytes(self):
        self.path.write_bytes(b'locked-console')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(self.path), 0x80000000, 1 | 2, None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            with self.assertRaises(PermissionError):
                prepare_console_log(self.root, self.path, maximum_bytes=8)
            self.assertEqual(self.path.read_bytes(), b'locked-console')
        finally:
            kernel.CloseHandle(handle)


if __name__ == '__main__':
    unittest.main()
