"""Real Windows sharing, nested scope, rollback and digest freshness contracts."""
from pathlib import Path
from unittest.mock import patch
import hashlib
import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import native_artifact_pins as pins
import native_operation as native
import mc_deployment as deployment


@unittest.skipUnless(os.name == 'nt', 'Windows kernel sharing is the integrity boundary')
class NativeArtifactPinTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='MC只读校验 ')
        self.root = Path(self.folder.name); self.addCleanup(self.folder.cleanup)
        self.path = self.root / 'models/weights.pt'; self.path.parent.mkdir()
        self.data = b'original model fixture'; self.path.write_bytes(self.data)

    def test_readers_succeed_while_writes_and_replacement_are_denied_until_close(self):
        cache = pins.FileHashPins(); self.addCleanup(cache.close)
        self.assertEqual(cache.digest(self.path), hashlib.sha256(self.data).hexdigest())
        self.assertEqual(self.path.read_bytes(), self.data)
        with self.assertRaises(OSError): self.path.write_bytes(b'changed')
        with self.assertRaises(OSError): self.path.replace(self.path.with_name('moved.pt'))
        self.assertEqual(cache.digest(self.path), hashlib.sha256(self.data).hexdigest())
        self.assertEqual(cache.statistics['cache_hits'], 1)
        self.assertEqual(cache.statistics['hashed_bytes'], len(self.data))
        self.assertFalse(os.get_inheritable(next(iter(cache.pins.values()))[0].fileno()))
        cache.close(); self.path.write_bytes(b'changed')
        self.path.replace(self.path.with_name('moved.pt'))

    def test_an_existing_writer_prevents_pin_creation(self):
        cache = pins.FileHashPins(); self.addCleanup(cache.close)
        with self.path.open('r+b') as writer:
            with self.assertRaises(OSError): cache.digest(self.path)
            writer.seek(0); writer.write(self.data)
        self.assertFalse(cache.pins)
        self.assertEqual(cache.digest(self.path), hashlib.sha256(self.data).hexdigest())

    def test_minimal_package_installer_does_not_require_an_operation_module(self):
        with patch.dict(sys.modules, {'native_operation': None}):
            self.assertEqual(deployment.sha(self.path), hashlib.sha256(self.data).hexdigest())
        self.path.write_bytes(b'changed after standalone hash')

    def test_an_older_source_updater_still_hashes_fresh_bytes(self):
        with patch.dict(sys.modules, {'native_operation': SimpleNamespace()}):
            before = deployment.sha(self.path); self.path.write_bytes(b'changed under old updater')
            self.assertNotEqual(deployment.sha(self.path), before)

    def test_failed_first_hash_releases_the_native_handle(self):
        cache = pins.FileHashPins(); self.addCleanup(cache.close)
        with patch.object(pins.hashlib, 'sha256', side_effect=OSError('injected digest failure')):
            with self.assertRaises(OSError): cache.digest(self.path)
        self.assertFalse(cache.pins); self.path.write_bytes(b'changed')

    def test_nested_operation_reuses_the_pin_and_a_new_operation_reads_fresh_bytes(self):
        stamp = self.path.stat().st_mtime_ns
        with patch.object(native, 'PIN_MIN_BYTES', 1):
            with native.operation(self.root, 'fixture-first') as outer:
                first = deployment.sha(self.path)
                with native.operation(self.root, 'fixture-nested') as inner:
                    self.assertIs(outer, inner); self.assertEqual(deployment.sha(self.path), first)
                self.assertEqual(deployment.sha(self.path), first)
                with self.assertRaises(OSError): self.path.write_bytes(b'changed')
            self.assertEqual(native.status(self.root)['artifact_hashes']['cache_hits'], 2)
            self.path.write_bytes(b'changed model fixture!')
            os.utime(self.path, ns=(stamp, stamp))
            with native.operation(self.root, 'fixture-second') as current:
                second = deployment.sha(self.path)
                self.assertNotEqual(first, second)
                self.assertEqual(current.artifact_pins.statistics['hashed_files'], 1)
                self.assertEqual(current.artifact_pins.statistics['cache_hits'], 0)

    def test_rollback_also_releases_all_file_pins(self):
        with patch.object(native, 'PIN_MIN_BYTES', 1):
            with self.assertRaisesRegex(RuntimeError, 'fixture abort'):
                with native.operation(self.root, 'fixture-rollback'):
                    deployment.sha(self.path)
                    raise RuntimeError('fixture abort')
        self.assertEqual(native.status(self.root)['phase'], 'ROLLED_BACK')
        self.path.write_bytes(b'changed after rollback')

    def test_source_and_config_are_rehashed_during_the_same_operation(self):
        with patch.object(native, 'PIN_MIN_BYTES', 1):
            with native.operation(self.root, 'fixture-live-config') as current:
                for name in ['configs/current.json', 'scripts/current.py']:
                    path = self.root / name; path.parent.mkdir(exist_ok=True)
                    path.write_bytes(b'first version'); stamp = path.stat().st_mtime_ns
                    first = deployment.sha(path); path.write_bytes(b'other version')
                    os.utime(path, ns=(stamp, stamp))
                    self.assertNotEqual(deployment.sha(path), first)
                self.assertEqual(current.artifact_pins.statistics['hashed_files'], 0)

    def test_no_operation_and_other_threads_do_not_reuse_the_current_cache(self):
        self.assertIsNone(native.artifact_digest(self.path))
        with patch.object(native, 'PIN_MIN_BYTES', 1), native.operation(self.root, 'fixture-thread-isolation') as current:
            expected = deployment.sha(self.path); observed = []
            worker = threading.Thread(target=lambda: observed.append((native.artifact_digest(self.path), deployment.sha(self.path))))
            worker.start(); worker.join(timeout=10); self.assertFalse(worker.is_alive())
            self.assertEqual(observed, [(None, expected)])
            self.assertEqual(current.artifact_pins.statistics['cache_hits'], 0)
        self.path.write_bytes(b'changed after scope')
        self.assertIsNone(native.artifact_digest(self.path))

    def test_changed_file_identity_or_metadata_is_never_accepted_as_a_cache_hit(self):
        cache = pins.FileHashPins(); self.addCleanup(cache.close)
        cache.digest(self.path)
        actual = pins.identity
        def changed(stream):
            value = actual(stream)
            return value[:1] + (value[1] + 1,) + value[2:]
        with patch.object(pins, 'identity', side_effect=changed):
            with self.assertRaisesRegex(pins.ArtifactPinError, 'MC_ARTIFACT_PIN_CHANGED'):
                cache.digest(self.path)
        self.assertEqual(cache.statistics['cache_hits'], 0)

    def test_real_large_artifact_is_read_once_per_operation(self):
        size = native.PIN_MIN_BYTES
        with self.path.open('wb') as stream: stream.truncate(size)
        expected = hashlib.sha256()
        for _ in range(size // (1024 * 1024)): expected.update(b'\0' * (1024 * 1024))
        with native.operation(self.root, 'fixture-real-large-artifact') as current:
            self.assertEqual(deployment.sha(self.path), expected.hexdigest())
            self.assertEqual(deployment.sha(self.path), expected.hexdigest())
            self.assertEqual(current.artifact_pins.statistics['hashed_bytes'], size)
            self.assertEqual(current.artifact_pins.statistics['hashed_files'], 1)
            self.assertEqual(current.artifact_pins.statistics['cache_hits'], 1)


if __name__ == '__main__': unittest.main(verbosity=2)
