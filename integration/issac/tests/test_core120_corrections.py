"""Preserve shared model bytes and select only the genuine installed client."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration.issac.common import AdmissionError,file_hash,read_json,write_json
from integration.issac import existing_backend as backend
from integration.issac.livehime import installed_executable

ROOT=Path(__file__).resolve().parents[3]


class ExistingBackendTests(unittest.TestCase):
    def test_only_the_exact_existing_file_policy_can_enable_full_gpu(self):
        original=read_json(ROOT/'configs/issac/existing-model-backend.json')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=root/'configs/issac/existing-model-backend.json'
            write_json(path,original)
            self.assertEqual(backend.selection(root)['bytes'],14252845984)
            for key,value in [('source_file','C:/different.gguf'),('bytes',1),('gpu_offload',1.0),
                              ('model_downloads_allowed',True),('cloud_fallback',True)]:
                policy=deepcopy(original);policy[key]=value;write_json(path,policy)
                with self.assertRaises(AdmissionError):backend.selection(root)

    def test_corrupted_local_file_cannot_be_registered_as_the_selected_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'existing.gguf';path.write_bytes(b'GGUFverified local fixture')
            sha=file_hash(path);size=path.stat().st_size
            backend.verify_existing_file(path,size=size,sha256=sha)
            path.write_bytes(b'GGUFcorrupted local file!')
            with self.assertRaises(AdmissionError):backend.verify_existing_file(path,size=size,sha256=sha)

    def test_registration_is_a_hardlink_and_never_replaces_a_conflicting_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'installation';source=Path(temporary)/'shared.gguf'
            source.write_bytes(b'GGUF preserved original weights')
            before=source.read_bytes()
            with patch.object(backend,'SHA256',file_hash(source)):
                linked=backend.register_link(root,source)
                self.assertTrue(linked.samefile(source));self.assertEqual(source.read_bytes(),before)
                self.assertEqual(backend.register_link(root,source),linked)
                linked.unlink();linked.write_bytes(b'preexisting unrelated model')
                with self.assertRaisesRegex(AdmissionError,'FILE_PRESERVED'):backend.register_link(root,source)
                self.assertEqual(linked.read_bytes(),b'preexisting unrelated model')
                self.assertEqual(source.read_bytes(),before)


class InstalledClientTests(unittest.TestCase):
    def test_official_installer_identical_root_copy_and_versioned_copy_are_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);policy=read_json(ROOT/'configs/issac/official-installation.json')
            policy.pop('installation_scope',None) # Exercise the retained legacy-copy admission path.
            for key in ('application','same_signed_bootstrap_copy'):
                path=root/policy[key];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'official signed fixture')
            policy['application_sha256']=file_hash(root/policy['application'])
            write_json(root/'configs/issac/official-installation.json',policy)
            self.assertEqual(installed_executable(root),root/policy['application'])
            unexpected=root/'tools/bilibili-livehime/unexpected/livehime.exe'
            unexpected.parent.mkdir();unexpected.write_bytes(b'unrelated copy preserved')
            with self.assertRaisesRegex(AdmissionError,'ONLY_PINNED'):installed_executable(root)
            self.assertEqual(unexpected.read_bytes(),b'unrelated copy preserved')

    def test_an_altered_bootstrap_or_unpinned_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);policy=read_json(ROOT/'configs/issac/official-installation.json')
            policy.pop('installation_scope',None)
            for key in ('application','same_signed_bootstrap_copy'):
                path=root/policy[key];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'official signed fixture')
            policy['application_sha256']=file_hash(root/policy['application'])
            write_json(root/'configs/issac/official-installation.json',policy)
            (root/policy['same_signed_bootstrap_copy']).write_bytes(b'changed bootstrap')
            with self.assertRaisesRegex(AdmissionError,'BYTES_CHANGED'):installed_executable(root)
            policy['application']='../../different/livehime.exe'
            write_json(root/'configs/issac/official-installation.json',policy)
            with self.assertRaisesRegex(AdmissionError,'PINNED_OFFICIAL'):installed_executable(root)

    def test_system_installation_rejects_unpinned_paths_and_changed_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);policy=read_json(ROOT/'configs/issac/official-installation.json')
            write_json(root/'configs/issac/official-installation.json',policy)
            with patch('pathlib.Path.is_file',return_value=True),patch('integration.issac.livehime.file_hash',return_value=policy['application_sha256']):
                self.assertEqual(installed_executable(root),Path(policy['installed_application']).resolve())
            with patch('pathlib.Path.is_file',return_value=True),patch('integration.issac.livehime.file_hash',return_value='0'*64):
                with self.assertRaises(AdmissionError):installed_executable(root)
            policy['installed_application']='C:/different/livehime.exe'
            write_json(root/'configs/issac/official-installation.json',policy)
            with self.assertRaises(AdmissionError):installed_executable(root)


if __name__=='__main__':unittest.main()
