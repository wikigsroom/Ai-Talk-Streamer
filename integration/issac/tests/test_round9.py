"""Observed native SentencePiece gap: complete offline copy and real audio setup."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from integration.issac.common import AdmissionError,file_hash,read_json,write_json
from integration.issac import offline_dependencies as dependencies


class NativeVoiceDependencyTests(unittest.TestCase):
    def fixture(self,temporary):
        root=Path(temporary)/'isolated';source=Path(temporary)/'existing'
        contents={'pydub/__init__.py':b'original audio package',
            'pydub-0.25.1.dist-info/METADATA':b'Version: 0.25.1\n',
            'sentencepiece/__init__.py':b'original native wrapper',
            'sentencepiece/_sentencepiece.cp310-win_amd64.pyd':b'existing cp310 Windows native extension',
            'sentencepiece-0.2.2.dist-info/METADATA':b'Version: 0.2.2\n',
            'sentencepiece-0.2.2.dist-info/WHEEL':b'Tag: cp310-cp310-win_amd64\n'}
        rows=[]
        for name,content in contents.items():
            path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
            rows.append({'path':name,'bytes':len(content),'sha256':file_hash(path)})
        config={'existing_source':str(source),'packages':[{'name':'pydub','version':'0.25.1'},
            {'name':'sentencepiece','version':'0.2.2'}],'files':rows}
        write_json(root/'configs/issac/offline-voice-dependencies.json',config)
        return root,source,config

    def install(self,root,source):
        with patch.object(dependencies,'EXISTING_SHARED_SITE',source):
            return dependencies.install_voice_dependencies(root)

    def test_existing_native_binary_and_metadata_are_complete_and_repeatable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,source,config=self.fixture(temporary)
            first=self.install(root,source);again=self.install(root,source)
            self.assertEqual(first['new_files_copied'],6);self.assertEqual(again['new_files_copied'],0)
            self.assertEqual(again['packages'],config['packages']);self.assertEqual(again['new_download_bytes'],0)
            for row in config['files']:
                target=root/'runtime/tts-benchmark/omnivoice/Lib/site-packages'/row['path']
                self.assertEqual(file_hash(target),row['sha256'])
                self.assertEqual(file_hash(source/row['path']),row['sha256'])

    def test_wrong_native_abi_is_rejected_before_any_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,source,config=self.fixture(temporary)
            config['files'][3]['path']='sentencepiece/_sentencepiece.cp313-win_amd64.pyd'
            write_json(root/'configs/issac/offline-voice-dependencies.json',config)
            with self.assertRaisesRegex(AdmissionError,'CP310_WINDOWS_SENTENCEPIECE'):self.install(root,source)
            self.assertFalse((root/'runtime').exists())

    def test_corrupt_native_source_does_not_partially_install_any_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,source,config=self.fixture(temporary)
            (source/config['files'][3]['path']).write_bytes(b'corrupt binary')
            with self.assertRaisesRegex(AdmissionError,'DEPENDENCY_CHANGED'):self.install(root,source)
            self.assertFalse((root/'runtime').exists())

    def test_existing_other_version_or_unlisted_binary_survives_rejection(self):
        for member in ('sentencepiece-0.2.1.dist-info/METADATA','sentencepiece/unlisted.pyd'):
            with self.subTest(member=member),tempfile.TemporaryDirectory() as temporary:
                root,source,config=self.fixture(temporary)
                conflict=root/'runtime/tts-benchmark/omnivoice/Lib/site-packages'/member
                conflict.parent.mkdir(parents=True);conflict.write_bytes(b'preserve prior package')
                with self.assertRaises(AdmissionError):self.install(root,source)
                self.assertEqual(conflict.read_bytes(),b'preserve prior package')
                self.assertFalse((conflict.parents[1]/'pydub/__init__.py').exists())


class ActualAudioCompatibilityTests(unittest.TestCase):
    def test_unicode_sentencepiece_model_uses_the_existing_native_byte_loader(self):
        from integration import resident_tts_worker as audio
        class Processor:
            def LoadFromFile(self,_filename):raise AssertionError('Unicode path passed to native filename loader')
            def LoadFromSerializedProto(self,data):return data
        sp=SimpleNamespace(SentencePieceProcessor=Processor)
        torchaudio=SimpleNamespace()
        with tempfile.TemporaryDirectory() as temporary,patch.dict('sys.modules',{'sentencepiece':sp}):
            model=Path(temporary)/'奶妹分词模型.model';model.write_bytes(b'existing model bytes')
            audio.native_audio(SimpleNamespace(),torchaudio,SimpleNamespace(),SimpleNamespace())
            self.assertEqual(Processor().LoadFromFile(str(model)),b'existing model bytes')
            self.assertEqual(torchaudio.list_audio_backends(),['soundfile'])

    def test_missing_sentencepiece_cannot_be_reported_as_ready_or_start_media_probe(self):
        path=Path(__file__).resolve().parents[3]/'scripts/diagnose_issac.py'
        spec=importlib.util.spec_from_file_location('round9_diagnostics',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        events=[]
        def load(name):
            if name=='sentencepiece':raise ModuleNotFoundError("No module named 'sentencepiece'")
            return SimpleNamespace(__version__='2.9.1+cu128')
        with patch('builtins.print',side_effect=lambda value,**kw:events.append(json.loads(value))),\
             patch('faulthandler.enable'),patch('faulthandler.dump_traceback_later'),\
             patch('faulthandler.cancel_dump_traceback_later'),patch('sys.path',[]),\
             patch('pathlib.Path.cwd',return_value=Path('.')),patch('importlib.import_module',side_effect=load):
            with self.assertRaisesRegex(ModuleNotFoundError,'sentencepiece'):exec(module.dependency_code('voice'),{})
        self.assertEqual(events[-1],{'stage':'import_begin','module':'sentencepiece'})
        self.assertFalse(any(e['stage']=='dependencies_ready' for e in events))
        path=path.with_name('run_issac_round.py')
        spec=importlib.util.spec_from_file_location('round9_uniform',path)
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        result=runner.blocked_by_prerequisite('media-capacity',[{'check':'dependencies','passed':False}])
        self.assertEqual(result['requires'],'dependencies');self.assertFalse(result['actual_inference'])


class OfficialControlEncodingTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Native Windows PowerShell 5.1 parser required')
    def test_actual_official_button_script_parses_without_invoking_any_ui(self):
        root=Path(__file__).resolve().parents[3]
        script=root/'scripts/issac_livehime_ui.ps1'
        command=("$errors=$null;$tokens=$null;"
            "[System.Management.Automation.Language.Parser]::ParseFile($env:ISSAC_PS_PARSE_FILE,[ref]$tokens,[ref]$errors)|Out-Null;"
            "if($errors.Count -gt 0){[Console]::Error.WriteLine(($errors|Out-String));exit 1}")
        result=subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
            '-NoProfile','-NonInteractive','-Command',command],capture_output=True,timeout=20,
            env={**os.environ,'ISSAC_PS_PARSE_FILE':str(script)},creationflags=0x08000000)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf8',errors='replace'))


if __name__=='__main__':unittest.main()
