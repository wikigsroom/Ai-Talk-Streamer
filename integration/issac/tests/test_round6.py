"""Observed R5 failures; written as part of the complete R6 development round."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from integration.issac.common import AdmissionError,file_hash,read_json,write_json
from integration.issac.saves import SaveProtection,window_position_only


class WindowPositionProtectionTests(unittest.TestCase):
    original=b'[Options]\r\nEnableDebugConsole=1\r\nWindowPosX=140\r\nWindowPosY=120\r\nMusicVolume=0.3\r\n'

    def test_real_window_writeback_preserves_original_baseline_and_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);game=root/'game';game.mkdir()
            options=game/'options.ini';options.write_bytes(self.original)
            slot=game/'rep_persistentgamedata1.dat';slot.write_bytes(b'original slot one')
            guard=SaveProtection(root);baseline=deepcopy(guard.prepare([str(game)]))
            manifest_sha=file_hash(guard.manifest)
            options.write_bytes(self.original.replace(b'WindowPosX=140',b'WindowPosX=-940').replace(b'WindowPosY=120',b'WindowPosY=500'))
            observed=guard.verify()
            self.assertTrue(observed['protected_unchanged'])
            self.assertEqual(observed['baseline_id'],baseline['id'])
            self.assertEqual(len(observed['runtime_window_position_changes']),1)
            self.assertEqual(file_hash(guard.manifest),manifest_sha)
            self.assertEqual(read_json(guard.manifest),baseline)
            self.assertEqual(Path(baseline['files'][0]['backup']).read_bytes(),self.original)
            slot.write_bytes(b'changed slot one')
            with self.assertRaisesRegex(AdmissionError,'PROTECTED_SAVE_CHANGED'):guard.verify()

    def test_other_options_whitespace_line_endings_and_invalid_coordinates_are_protected(self):
        variants=[self.original.replace(b'Console=1',b'Console=0'),
                  self.original.replace(b'Volume=0.3',b'Volume=0.5'),
                  self.original.replace(b'X=140',b'X =140'),
                  self.original.replace(b'\r\n',b'\n'),
                  self.original.replace(b'X=140',b'X=2147483648'),
                  self.original.replace(b'X=140',b'X=1.5'),
                  self.original.replace(b'WindowPosY=120\r\n',b''),
                  self.original+b'WindowPosX=42\r\n',
                  self.original+b'windowposx=bad\r\n']
        for changed in variants:
            with self.subTest(changed=changed):self.assertFalse(window_position_only(self.original,changed))

    def test_a_different_ini_or_new_configuration_is_not_exempted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);game=root/'game';game.mkdir()
            protected=game/'other.ini';protected.write_bytes(self.original)
            guard=SaveProtection(root);guard.prepare([str(game)])
            protected.write_bytes(self.original.replace(b'X=140',b'X=220'))
            with self.assertRaisesRegex(AdmissionError,'PROTECTED_SAVE_CHANGED'):guard.verify()
            protected.write_bytes(self.original)
            (game/'new.ini').write_bytes(b'new unexpected configuration')
            with self.assertRaisesRegex(AdmissionError,'UNCLASSIFIED_CONFIGURATION_FILE_CREATED'):guard.verify()


class ActualApplicationReadinessTests(unittest.TestCase):
    def fixture(self,temporary):
        from integration.issac.local_model import LocalModel
        model=LocalModel.__new__(LocalModel);model.home=Path(temporary)
        process=Mock();process.pid=100;process.children.return_value=[]
        model.app_owner=Mock(return_value=(process,{}))
        model.progress=Mock();model.audit=Mock()
        return model

    def test_a_launcher_without_published_listener_is_not_ready(self):
        from integration.issac import local_model as module
        with tempfile.TemporaryDirectory() as temporary:
            model=self.fixture(temporary)
            self.assertIsNone(model.application_api())
            write_json(model.home/'.internal/http-server.json',{'pid':100,'port':41343})
            with patch('psutil.net_connections',return_value=[]):self.assertIsNone(model.application_api())
            listener=SimpleNamespace(status='LISTEN',laddr=SimpleNamespace(port=41343,ip='127.0.0.1'),pid=100)
            with patch('psutil.net_connections',return_value=[listener]):proof=model.application_api()
            self.assertEqual(proof['listener_pids'],[100]);self.assertTrue(proof['loopback_only'])
            model.application_api=Mock(side_effect=[None,proof])
            with patch.object(module.time,'sleep') as sleep:self.assertEqual(model.wait_application_api(),proof)
            sleep.assert_called_once_with(1)

    def test_foreign_pid_and_nonloopback_listener_fail_before_cli_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            model=self.fixture(temporary)
            path=model.home/'.internal/http-server.json'
            write_json(path,{'pid':200,'port':41343})
            with patch('psutil.pid_exists',return_value=True):
                with self.assertRaisesRegex(AdmissionError,'METADATA_OWNER_CHANGED'):model.application_api()
            with patch('psutil.pid_exists',return_value=False):self.assertIsNone(model.application_api())
            write_json(path,{'pid':100,'port':41343})
            for pid,address in ((200,'127.0.0.1'),(100,'0.0.0.0')):
                listener=SimpleNamespace(status='LISTEN',laddr=SimpleNamespace(port=41343,ip=address),pid=pid)
                with patch('psutil.net_connections',return_value=[listener]):
                    with self.assertRaisesRegex(AdmissionError,'LISTENER_NOT_OWNED_OR_NOT_LOOPBACK'):model.application_api()

    def test_child_cli_selects_the_exact_isolated_metadata_file(self):
        from integration.issac.local_model import LocalModel
        with tempfile.TemporaryDirectory() as temporary:
            model=LocalModel.__new__(LocalModel);model.root=Path(temporary)
            model.home=model.root/'tools/lmstudio/home';model.profile=model.root/'state/profile'
            env=model.environment()
            self.assertEqual(env['LMS_API_SERVER_INFO_PATH'],str(model.home/'.internal/http-server.json'))

    def test_an_empty_requested_directory_cannot_pass_actual_gui_profile_isolation(self):
        from integration.issac.local_model import LocalModel
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);model=LocalModel.__new__(LocalModel)
            model.root=root;model.profile=root/'profile';model.home=root/'home'
            model.registration=root/'registration.json';model.url='http://127.0.0.1:1234/v1'
            model.last_profile_proof=None
            requested=model.profile/'electron-user-data';requested.mkdir(parents=True)
            (requested/'only-a-log.txt').write_text('requested path is not actual application state','utf8')
            process=Mock();process.pid=100;process.children.return_value=[]
            process.environ.return_value={'USERPROFILE':str(model.profile)}
            process.cmdline.return_value=['application.exe','--user-data-dir='+str(requested)]
            process.open_files.return_value=[]
            model.app_owner=Mock(return_value=(process,{}))
            listener=SimpleNamespace(status='LISTEN',laddr=SimpleNamespace(port=1234,ip='127.0.0.1'),pid=100)
            with patch('psutil.net_connections',return_value=[listener]):
                with self.assertRaisesRegex(AdmissionError,'RUNTIME_PROFILE_NOT_CONFIRMED'):model.verify_server_owner()
                actual=model.profile/'AppData/Roaming/LM Studio/Session Storage/LOCK'
                actual.parent.mkdir(parents=True);actual.write_bytes(b'')
                with self.assertRaisesRegex(AdmissionError,'RUNTIME_PROFILE_NOT_CONFIRMED'):model.verify_server_owner()
                process.open_files.return_value=[SimpleNamespace(path=str(actual))]
                proof=model.verify_server_owner()
            self.assertEqual(proof['actual_roaming_profile_open_files'],[str(actual)])
            self.assertTrue(read_json(model.registration)['runtime_profile_verified'])


class DependencyImportDiagnosticsTests(unittest.TestCase):
    def test_voice_probe_logs_each_actual_import_and_remains_model_free(self):
        path=Path(__file__).resolve().parents[3]/'scripts/diagnose_issac.py'
        spec=importlib.util.spec_from_file_location('round6_diagnostics',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        code=module.dependency_code('voice');events=[];loaded=[]
        names=('torch','transformers','omnivoice','torchaudio','numpy','soundfile','sentencepiece')
        modules={name:SimpleNamespace(__version__='2.9.1+cu128') for name in names}
        class SentencePieceFixture:
            def LoadFromFile(self,_filename):return True
        modules['sentencepiece'].SentencePieceProcessor=SentencePieceFixture
        def load(name):loaded.append(name);return modules[name]
        def observe(value,**kwargs):events.append(json.loads(value))
        with patch.dict('sys.modules',{'sentencepiece':modules['sentencepiece']}),patch('builtins.print',side_effect=observe),\
             patch('faulthandler.enable'),patch('faulthandler.dump_traceback_later'),\
             patch('faulthandler.cancel_dump_traceback_later'),patch('sys.path',[]),\
             patch('pathlib.Path.cwd',return_value=Path('.')),patch('importlib.import_module',side_effect=load):
            exec(code,{})
        self.assertEqual(loaded,list(names))
        self.assertEqual([e['module'] for e in events if e['stage']=='import_begin'],loaded)
        self.assertEqual([e['module'] for e in events if e['stage']=='import_complete'],loaded)
        self.assertIn({'stage':'native_audio_compatibility_ready','models_loaded':False},events)
        self.assertEqual(events[-1],{'stage':'dependencies_ready','kind':'voice'})


if __name__=='__main__':unittest.main()
