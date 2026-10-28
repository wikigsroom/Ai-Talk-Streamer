"""Destructive cleanup boundaries and preservation, using project-local fixtures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.cleanup_lipsync_candidates import TARGETS, cleanup, inventory, safe_target


class CleanupTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[2]/'cache/k02-test-fixtures'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, data=b'model'):
        target = self.root/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def test_inventory_does_not_delete_and_rejects_unlisted_paths(self):
        weight = self.write(TARGETS[0]+'/identity.pth')
        result = cleanup(self.root)
        self.assertTrue(weight.exists())
        self.assertEqual(result['logical_bytes'], 5)
        for path in ('../elsewhere', 'models', 'src/LiveTalking/models', 'runtime/livetalking'):
            with self.assertRaises(ValueError):safe_target(self.root, path)

    def test_reparse_point_is_rejected_before_traversal(self):
        target = self.write(TARGETS[0]+'/identity.pth')
        original = Path.lstat
        def metadata(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path == target:
                from types import SimpleNamespace
                return SimpleNamespace(st_file_attributes=0x400, st_mode=value.st_mode)
            return value
        with patch.object(Path, 'lstat', metadata):
            with self.assertRaises(ValueError):inventory(self.root, TARGETS[0])

    def test_apply_requires_k02_and_no_active_candidate_job(self):
        target = self.write(TARGETS[0]+'/identity.pth')
        with self.assertRaises(FileNotFoundError):cleanup(self.root, True)
        self.write('.setup/k02/activation.json', json.dumps({'profile':{'id':'K02'}}).encode())
        with patch('scripts.cleanup_lipsync_candidates.assert_inactive', side_effect=RuntimeError('busy')):
            with self.assertRaises(RuntimeError):cleanup(self.root, True)
        self.assertTrue(target.exists())

    def test_apply_removes_only_candidates_and_is_repeatable(self):
        self.write('.setup/k02/activation.json', json.dumps({'profile':{'id':'K02'}}).encode())
        removed = self.write(TARGETS[0]+'/identity.pth')
        kept = [self.write(path, b'keep') for path in (
            'src/LiveTalking/models/sd-vae/diffusion_pytorch_model.bin',
            'models/tts-benchmark/omnivoice/model.safetensors',
            'models/tts-benchmark/f5/model.safetensors',
            'models/tts-benchmark/kokoro/kokoro.pth',
            'models/tts-benchmark/melo/model.pth',
            'runtime/livetalking/Lib/site-packages/shared.pth',
            'outputs/lipsync-k01-k05-60s-20261028/K02/K02-60s.mp4',
            'Ai-Talk-Streamer/docs/analysis/lipsync-k01-k05-20261028/results.json')]
        with patch('scripts.cleanup_lipsync_candidates.assert_inactive'):
            result = cleanup(self.root, True)
            second = cleanup(self.root, True)
        self.assertFalse(removed.exists())
        self.assertTrue(result['ok'] and result['history_unchanged'] and second['ok'])
        self.assertEqual(second['deleted'], [])
        for path in kept:self.assertEqual(path.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
