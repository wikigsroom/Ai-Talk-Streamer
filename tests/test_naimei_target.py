"""Meaningful branch, source-receipt and GPU isolation checks for the new runtime."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('naimei_deployment_target', ROOT / 'scripts/deployment_target.py')
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)
TEMP = ROOT / 'state/test-tmp'
TEMP.mkdir(parents=True, exist_ok=True)


class NaimeiTargetTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name in ['configs/deployment-target.json', 'configs/deployment-targets.json',
                'configs/releases/current.json', 'configs/naimei/live-runtime.json', 'configs/characters/naimei.json',
                'configs/dsh-active-policy.json', 'configs/naimei/bridge-policy.json']:
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())
        origin = {'target': 'naimei-rtx4090', 'branch': 'naimei', 'source_commit': 'a' * 40,
                  'archive_sha256': 'b' * 64, 'verified_source_manifest': True}
        (root / '.setup').mkdir()
        receipt = root / '.setup/deployment-origin.json'
        receipt.write_text(json.dumps(origin), encoding='utf-8')
        return root, receipt, origin

    def test_cannot_use_inherited_generic_launcher(self):
        root, _, _ = self.fixture()
        with self.assertRaisesRegex(RuntimeError, 'explicitly select'):
            target.validate_target(root, check_hardware=False)

    def test_cannot_reuse_female_a_device_receipt(self):
        root, receipt, origin = self.fixture()
        origin.update(target='rtx4090', branch='deploy/rtx4090')
        receipt.write_text(json.dumps(origin))
        with self.assertRaisesRegex(RuntimeError, 'another deployment target'):
            target.validate_target(root, expected_target='naimei-rtx4090', check_hardware=False)

    def test_unverified_source_archive_rejected(self):
        root, receipt, origin = self.fixture()
        del origin['archive_sha256']
        receipt.write_text(json.dumps(origin))
        with self.assertRaisesRegex(RuntimeError, 'verified source archive'):
            target.validate_target(root, expected_target='naimei-rtx4090', check_hardware=False)

    def test_24gb_card_cannot_start_this_48gb_contract(self):
        root, _, _ = self.fixture()
        with patch.object(target.subprocess, 'check_output', return_value='NVIDIA GeForce RTX 4090, 24564'):
            with self.assertRaisesRegex(RuntimeError, 'Inference GPU'):
                target.validate_target(root, expected_target='naimei-rtx4090', check_runtime=False)

    def test_own_state_and_512_configuration_required(self):
        root, _, _ = self.fixture()
        value = target.validate_target(root, expected_target='naimei-rtx4090', check_hardware=False)
        self.assertEqual(value['state_path'], 'state/naimei')
        path = root / 'configs/naimei/live-runtime.json'
        config = json.loads(path.read_text('utf-8')); config['size'] = 640
        path.write_text(json.dumps(config))
        with self.assertRaisesRegex(RuntimeError, '512x512'):
            target.validate_target(root, expected_target='naimei-rtx4090', check_hardware=False)


if __name__ == '__main__':
    unittest.main()
