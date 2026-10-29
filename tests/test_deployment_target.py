"""Reject wrong-device source/configuration before models or state are opened."""
from pathlib import Path
from unittest.mock import patch
import hashlib
import importlib.util
import json
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('deployment_target_test',ROOT/'scripts/deployment_target.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
REGISTRY=json.loads((ROOT/'configs/deployment-targets.json').read_text('utf8'))


class DeploymentTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.write('configs/deployment-targets.json',REGISTRY)
        self.select('rtx3080')

    def write(self,name,data):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data),encoding='utf8')

    def select(self,target):
        self.target=target
        self.write('configs/deployment-target.json',REGISTRY['shared'] if target is None else REGISTRY['targets'][target]['selection'])
        self.write('configs/releases/current.json',REGISTRY['shared_pointer'] if target is None else REGISTRY['targets'][target]['release_pointer'])
        if target:
            d=REGISTRY['targets'][target]
            self.write('.setup/deployment-origin.json',{'target':target,'branch':d['selection']['branch'],'source_commit':'a'*40})
            self.write('configs/livetalking.yaml',{'model':'musetalk','batch_size':d['batch_size'],'fps':25})
            self.write('configs/dsh-active-policy.json',{'policy_file':'configs/test-policy.json'})
            self.write('configs/test-policy.json',{'deployment':{'state_relative_path':d['state_path']}})

    def validate(self,hardware=None,**kwargs):
        hardware=hardware or ('NVIDIA GeForce RTX 3080, 10240\n'if self.target=='rtx3080'else'NVIDIA GeForce RTX 4090, 49140\n')
        with patch.object(guard.subprocess,'check_output',return_value=hardware):
            return guard.validate_target(self.root,**kwargs)

    def test_shared_main_cannot_start_inference(self):
        self.select(None)
        with patch.object(guard.subprocess,'check_output')as command:
            with self.assertRaisesRegex(RuntimeError,'shared source'):guard.validate_target(self.root)
            command.assert_not_called()

    def test_cross_branch_descriptor_is_rejected(self):
        d=dict(REGISTRY['targets']['rtx3080']['selection']);d['branch']='deploy/rtx4090'
        self.write('configs/deployment-target.json',d)
        with self.assertRaisesRegex(RuntimeError,'descriptor'):self.validate()

    def test_wrong_release_pointer_is_rejected(self):
        self.write('configs/releases/current.json',REGISTRY['targets']['rtx4090']['release_pointer'])
        with self.assertRaisesRegex(RuntimeError,'Release pointer'):self.validate()

    def test_wrong_git_branch_is_rejected(self):
        (self.root/'.git').mkdir()
        with patch.object(guard.subprocess,'check_output',return_value='main\n'):
            with self.assertRaisesRegex(RuntimeError,'Git branch'):guard.validate_target(self.root)

    def test_detached_checkout_is_rejected(self):
        (self.root/'.git').mkdir()
        with patch.object(guard.subprocess,'check_output',return_value='\n'):
            with self.assertRaisesRegex(RuntimeError,'Git branch'):guard.validate_target(self.root)

    def test_unidentified_copied_runtime_is_rejected(self):
        (self.root/'.setup/deployment-origin.json').unlink()
        with self.assertRaisesRegex(RuntimeError,'no deployment-origin'):self.validate()

    def test_other_target_receipt_is_rejected(self):
        self.write('.setup/deployment-origin.json',{'target':'rtx4090','branch':'deploy/rtx4090','source_commit':'b'*40})
        with self.assertRaisesRegex(RuntimeError,'another deployment'):self.validate()

    def test_unpinned_receipt_is_rejected(self):
        self.write('.setup/deployment-origin.json',{'target':'rtx3080','branch':'deploy/rtx3080','source_commit':'main'})
        with self.assertRaisesRegex(RuntimeError,'another deployment'):self.validate()

    def test_4090_source_cannot_start_on_3080(self):
        self.select('rtx4090')
        with self.assertRaisesRegex(RuntimeError,'Inference GPU'):self.validate('NVIDIA GeForce RTX 3080, 10240\n')

    def test_3080_source_cannot_start_on_4090(self):
        with self.assertRaisesRegex(RuntimeError,'Inference GPU'):self.validate('NVIDIA GeForce RTX 4090, 49140\n')

    def test_small_4090_variant_requires_an_explicit_new_profile(self):
        self.select('rtx4090')
        with self.assertRaisesRegex(RuntimeError,'Inference GPU'):self.validate('NVIDIA GeForce RTX 4090, 24576\n')

    def test_mixed_gpus_cannot_silently_use_the_wrong_default(self):
        with self.assertRaisesRegex(RuntimeError,'Inference GPU'):self.validate('NVIDIA GeForce RTX 3080, 10240\nNVIDIA GeForce RTX 4090, 49140\n')

    def test_batch_from_other_device_is_rejected(self):
        self.write('configs/livetalking.yaml',{'model':'musetalk','batch_size':8,'fps':25})
        with self.assertRaisesRegex(RuntimeError,'MuseTalk configuration'):self.validate()

    def test_other_device_memory_is_rejected(self):
        self.write('configs/test-policy.json',{'deployment':{'state_relative_path':'state/female-a-4090'}})
        with self.assertRaisesRegex(RuntimeError,'DSH state'):self.validate()

    def test_external_policy_path_is_rejected(self):
        self.write('configs/dsh-active-policy.json',{'policy_file':'../outside.json'})
        with self.assertRaisesRegex(RuntimeError,'leaves'):self.validate()

    def test_3080_configurator_cannot_run_on_the_4090_branch(self):
        self.select('rtx4090')
        with self.assertRaisesRegex(RuntimeError,'requires rtx3080'):self.validate(expected_target='rtx3080',check_runtime=False)

    def test_3080_copied_runtime_is_valid(self):
        self.assertEqual(self.validate()['batch_size'],4)

    def test_4090_copied_runtime_is_valid(self):
        self.select('rtx4090');self.assertEqual(self.validate()['batch_size'],8)

    def test_matching_git_checkout_is_valid(self):
        (self.root/'.git').mkdir()
        with patch.object(guard.subprocess,'check_output',side_effect=['deploy/rtx3080\n','NVIDIA GeForce RTX 3080, 10240\n']):
            self.assertTrue(guard.validate_target(self.root)['ok'])

    def test_check_is_read_only(self):
        def snapshot():return {p.relative_to(self.root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()for p in self.root.rglob('*')if p.is_file()}
        before=snapshot();self.validate();self.assertEqual(before,snapshot())


if __name__=='__main__':unittest.main()
