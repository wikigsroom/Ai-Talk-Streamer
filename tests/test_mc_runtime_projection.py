"""Native file/proxy deployment fixtures; no inference, game or platform messages."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import mc_runtime_projection as projection


class RuntimeProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.name, self.target = next(iter(projection.PROJECTIONS.items()))
        self.value = b'# reviewed proxy\n'
        self.write(self.name, self.value); self.write(self.target, self.value)
        self.source = {'snapshot_sha256': 'a' * 64,
                       'files': {self.name: hashlib.sha256(self.value).hexdigest()}}
        for name,target in list(projection.PROJECTIONS.items())[1:]:
            self.write(name,self.value);self.write(target,self.value)
            self.source['files'][name]=hashlib.sha256(self.value).hexdigest()
        self.backup = self.root / '.setup/backup'

    def write(self, name, value):
        path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value)

    def install(self):
        with projection.applied(self.root, self.source, self.backup) as receipt:
            return receipt

    def test_exact_imported_copy_and_receipt_are_checked(self):
        receipt = self.install()
        self.assertEqual(receipt['files'][self.target]['sha256'], self.source['files'][self.name])
        self.assertEqual(set(projection.validate(self.root, self.source)), {*projection.PROJECTIONS.values(), projection.RECEIPT})
        self.write(self.target, b'# stale runtime copy\n')
        with self.assertRaisesRegex(RuntimeError, 'BYTES_CHANGED'):
            projection.validate(self.root, self.source)

    def test_unknown_private_copy_is_never_overwritten(self):
        original = b'# unrelated private change\n'; self.write(self.target, original)
        with self.assertRaisesRegex(RuntimeError, 'UNKNOWN_BASELINE'): self.install()
        self.assertEqual((self.root / self.target).read_bytes(), original)
        self.assertFalse((self.root / projection.RECEIPT).exists())

    def test_verified_import_baseline_is_preserved_separately(self):
        original = b'# verified imported proxy\n'; self.write(self.target, original)
        dependency = json.dumps({'installation_root': str(self.root), 'files': {
            self.target: {'sha256': hashlib.sha256(original).hexdigest(), 'bytes': len(original)}}}).encode()
        self.write('.setup/mc-offline-dependencies.json', dependency)
        self.install()
        self.assertEqual((self.root / '.setup/mc-offline-dependencies.json').read_bytes(), dependency)
        self.assertEqual((self.backup / 'runtime-projections' / self.target).read_bytes(), original)

    def test_missing_receipt_and_new_source_with_old_copy_fail_before_start(self):
        with self.assertRaisesRegex(RuntimeError, 'FILE_MISSING_OR_LARGE'):
            projection.validate(self.root, self.source)
        self.install(); old = (self.root / self.target).read_bytes()
        value = b'# next reviewed proxy\n'; self.write(self.name, value)
        source = {'snapshot_sha256': 'b' * 64, 'files': {**self.source['files'],self.name: hashlib.sha256(value).hexdigest()}}
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_CHANGED'): projection.validate(self.root, source)
        self.assertEqual((self.root / self.target).read_bytes(), old)

    def test_outer_source_transaction_failure_restores_copy_and_prior_receipt(self):
        self.install(); prior = (self.root / projection.RECEIPT).read_bytes()
        original = (self.root / self.target).read_bytes()
        value = b'# next reviewed proxy\n'; self.write(self.name, value)
        source = {'snapshot_sha256': 'b' * 64, 'files': {**self.source['files'],self.name: hashlib.sha256(value).hexdigest()}}
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_TRANSACTION_FAILED'):
            with projection.applied(self.root, source, self.root / '.setup/next-backup'):
                self.assertEqual((self.root / self.target).read_bytes(), value)
                raise RuntimeError('SOURCE_TRANSACTION_FAILED')
        self.assertEqual((self.root / self.target).read_bytes(), original)
        self.assertEqual((self.root / projection.RECEIPT).read_bytes(), prior)

    def test_first_projection_failure_removes_new_receipt(self):
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_TRANSACTION_FAILED'):
            with projection.applied(self.root, self.source, self.backup):
                raise RuntimeError('SOURCE_TRANSACTION_FAILED')
        self.assertFalse((self.root / projection.RECEIPT).exists())
        self.assertEqual((self.root / self.target).read_bytes(), self.value)

    def test_renamed_or_edited_prior_copy_is_rejected(self):
        self.install(); self.write(self.target, b'# unreviewed edit\n')
        with self.assertRaisesRegex(RuntimeError, 'PREVIOUS_CHANGED'):
            with projection.applied(self.root, self.source, self.root / '.setup/next-backup'): pass

    def test_each_of_the_six_running_owners_blocks_any_projection_write(self):
        for anchor in projection.OWNERS:
            with self.subTest(anchor=anchor), patch('psutil.process_iter', return_value=[
                    SimpleNamespace(info={'cmdline': ['python.exe', str(self.root / anchor)]})]):
                with self.assertRaisesRegex(RuntimeError, 'RUNNING_OWNER'): self.install()
        self.assertFalse(self.backup.exists())
        self.assertFalse((self.root / projection.RECEIPT).exists())


if __name__ == '__main__': unittest.main()
