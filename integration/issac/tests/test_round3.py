"""Regressions for real R2 failures; no model/GPU or fake acceptance receipts."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace

from integration.issac.common import AdmissionError,write_json
from integration.issac.materials import generation
from integration.issac.native_game import OBSERVE
from integration.issac.resources import MIB,available_for_initialization,estimate_fits,parse_estimate


class ResourceTests(unittest.TestCase):
    def test_low_utilization_does_not_admit_a_still_running_comfy_job(self):
        row={'gpu_free_mib':40000,'gpu_utilization_percent':0,'host_available_bytes':40*1024*MIB,'comfy_running_jobs':1}
        self.assertFalse(available_for_initialization(row,10000))
        row['comfy_running_jobs']=0
        self.assertTrue(available_for_initialization(row,10000))

    def test_estimate_accounts_for_both_cpu_and_media_gpu_reserve(self):
        estimate=parse_estimate('Estimated GPU Memory: 20 GB\nEstimated Total Memory: 40 GB\n')
        self.assertEqual(estimate,{'gpu_bytes':20*1024*MIB,'total_bytes':40*1024*MIB})
        observed={'gpu_free_mib':48000,'host_available_bytes':40*1024*MIB}
        self.assertTrue(estimate_fits(estimate,observed))
        observed['gpu_free_mib']=30000
        self.assertFalse(estimate_fits(estimate,observed))
        observed.update(gpu_free_mib=48000,host_available_bytes=22*1024*MIB)
        self.assertFalse(estimate_fits(estimate,observed))

    def test_unknown_or_low_confidence_output_is_never_an_estimated_pass(self):
        for output in ('GPU is probably enough','Estimated GPU Memory: 2 GB\nEstimated Total Memory: 3 GB\nConfidence: LOW'):
            with self.assertRaises(AdmissionError):parse_estimate(output)


class NativeMenuTests(unittest.TestCase):
    def test_observation_works_without_global_json_or_active_player(self):
        from lupa.lua53 import LuaRuntime
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('json=nil;function Game() return {GetNumPlayers=function() return 0 end,IsPaused=function() return true end,GetFrameCount=function() return 0 end} end')
        value=json.loads(lua.execute(OBSERVE))
        self.assertEqual(value,{'paused':True,'frame':0,'players':0,'dead':False,'hp':0,'stage':0,'room':0,'seed':0,'controller_installed':False})

    def test_observation_preserves_real_living_run_numbers(self):
        from lupa.lua53 import LuaRuntime
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''json=nil;Isaac={GetPlayer=function() return {IsDead=function()return false end,GetHearts=function()return 3 end,GetSoulHearts=function()return 1 end} end}
        function Game() return {GetNumPlayers=function()return 1 end,IsPaused=function()return false end,GetFrameCount=function()return 72 end,
        GetLevel=function()return {GetStage=function()return 2 end,GetCurrentRoomIndex=function()return 19 end,
        GetCurrentRoomDesc=function()return {SafeGridIndex=19} end} end,
        GetSeeds=function()return {GetStartSeed=function()return 123456 end} end} end''')
        value=json.loads(lua.execute(OBSERVE))
        self.assertEqual((value['hp'],value['frame'],value['stage'],value['room'],value['seed']),(4,72,2,19,123456))


class MaterialGenerationTests(unittest.TestCase):
    def test_new_candidate_cannot_reuse_previous_review_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            one=generation(root,{'candidate_id':'issac-123456789abc-12345678'})
            two=generation(root,{'candidate_id':'issac-123456789abc-87654321'})
            self.assertNotEqual(one,two)
            with self.assertRaises(AdmissionError):generation(root,{'candidate_id':'../../old'})


class QualificationTruthTests(unittest.TestCase):
    def test_unavailable_backend_does_not_claim_actual_inference(self):
        import importlib.util
        root=Path(__file__).resolve().parents[3]
        spec=importlib.util.spec_from_file_location('issac_qualification_r3',root/'scripts/qualify_issac_model.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class Unavailable:
            config={'model':'test-local'}
            def __init__(self,_root):pass
            def complete(self,*args,**kwargs):raise ConnectionError('offline')
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(module,'require_candidate',return_value={'candidate_id':'test'}),patch.object(module,'LocalModel',Unavailable):
                result=module.qualify(Path(temporary))
        self.assertFalse(result['actual_inference'])
        self.assertFalse(result['qualified'])
        self.assertEqual(result['inference_requests_attempted'],6)
        self.assertEqual(result['inference_responses_received'],0)


class RelocationTests(unittest.TestCase):
    def test_existing_torch_mapping_survives_repeated_relocation(self):
        from integration.issac import preparation
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);base=root/'runtime/python/cpython-3.10.22-windows-x86_64-none'
            base.mkdir(parents=True);(base/'python.exe').write_bytes(b'fixture')
            for name in ('runtime/livetalking','runtime/tts-benchmark/omnivoice'):
                folder=root/name;(folder/'Scripts').mkdir(parents=True);(folder/'Scripts/python.exe').write_bytes(b'fixture')
                (folder/'Lib/site-packages').mkdir(parents=True);(folder/'pyvenv.cfg').write_text('home = C:/old/python\n','utf8')
            media=root/'runtime/livetalking/Lib/site-packages';(media/'torch').mkdir()
            (media/'torch/version.py').write_text("__version__ = '2.9.1+cu128'\n",'utf8')
            voice=root/'runtime/tts-benchmark/omnivoice/Lib/site-packages'
            (voice/'old_shared.pth').write_text('C:/dev/legacy-unrelated/runtime/tts/Lib/site-packages\n','utf8')
            with patch.object(preparation,'native_only'):
                preparation.relocate_native_environments(root)
                initial=(voice/'zz_issac_existing_torch.pth').read_bytes()
                preparation.relocate_native_environments(root)
            self.assertEqual((voice/'zz_issac_existing_torch.pth').read_bytes(),initial)
            self.assertEqual((voice/'old_shared.pth').read_text('utf8').strip(),'')
            self.assertEqual(Path(initial.decode().strip()).resolve(),media.resolve())


class OfficialClientTests(unittest.TestCase):
    def fixture(self,root):
        from integration.issac.livehime import Livehime
        client=Livehime.__new__(Livehime);client.root=root;client.candidate={'candidate_id':'test'}
        client.registration=root/'.setup/issac-livehime-owner.json';client.executable=root/'tools/bilibili-livehime/livehime.exe'
        client.executable.parent.mkdir(parents=True);client.executable.write_bytes(b'fixture')
        write_json(root/'configs/issac/official-rendering.json',{'default_mode':'software-ui'})
        client.prepare=Mock();client.audit=Mock()
        return client

    def test_existing_official_session_is_preserved_before_any_new_launch(self):
        fake=SimpleNamespace(process_iter=lambda _fields:[SimpleNamespace(info={'name':'livehime.exe','exe':'C:/other/livehime.exe'})],
                             NoSuchProcess=ProcessLookupError,AccessDenied=PermissionError)
        with tempfile.TemporaryDirectory() as temporary:
            client=self.fixture(Path(temporary))
            with patch.dict('sys.modules',{'psutil':fake}),patch('integration.issac.livehime.subprocess.Popen') as launch:
                with self.assertRaisesRegex(AdmissionError,'EXISTING_OFFICIAL_CLIENT_PRESERVED'):client.launch()
            launch.assert_not_called();client.prepare.assert_not_called()

    def test_short_lived_launcher_is_not_a_ready_official_client(self):
        process=SimpleNamespace(pid=123,create_time=lambda:456)
        fake=SimpleNamespace(process_iter=lambda _fields:[],Process=lambda _pid:process,
                             NoSuchProcess=ProcessLookupError,AccessDenied=PermissionError)
        handle=SimpleNamespace(pid=123,poll=lambda:0,returncode=0)
        with tempfile.TemporaryDirectory() as temporary:
            client=self.fixture(Path(temporary))
            with patch.dict('sys.modules',{'psutil':fake}),patch('integration.issac.livehime.subprocess.Popen',return_value=handle),patch('integration.issac.windows_profile.verify_in_child',return_value={'verified':True}):
                with self.assertRaisesRegex(AdmissionError,'BEFORE_STABLE_WINDOW'):client.launch()
            self.assertFalse(client.registration.exists())
            pending=json.loads((client.root/'.setup/issac-livehime-launch.json').read_text('utf8'))
            self.assertIs(pending['ready'],False)


class ModelPreparationTests(unittest.TestCase):
    def test_busy_gpu_rejects_before_weight_hash_or_application_launch(self):
        from integration.issac import local_model
        model=local_model.LocalModel.__new__(local_model.LocalModel)
        model.config={'model':'test'};model.progress=Mock();model.models=Mock(side_effect=AdmissionError('unavailable'))
        model.admit_retained_files=Mock();model.start_application=Mock()
        busy={'gpu_free_mib':4000,'gpu_utilization_percent':100,'comfy_running_jobs':1}
        with patch.object(local_model,'snapshot',return_value=busy):
            with self.assertRaisesRegex(AdmissionError,'WAIT_FOR_CAPACITY'):model.prepare()
        model.admit_retained_files.assert_not_called();model.start_application.assert_not_called()


class RuntimePluginTests(unittest.TestCase):
    def test_stale_copied_plugin_is_replaced_from_the_frozen_package(self):
        import shutil
        from integration.issac.strategy_dsh import sync_plugin
        source=Path(__file__).resolve().parents[2]/'isaac-agent/dsh-host/isaac-plugin'
        fake=SimpleNamespace(process_iter=lambda _fields:[],NoSuchProcess=ProcessLookupError,AccessDenied=PermissionError)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);host=root/'integration/isaac-agent/dsh-host'
            shutil.copytree(source,host/'isaac-plugin')
            installed=host/'node_modules/dsh-isaac-strategy';installed.mkdir(parents=True)
            (installed/'index.mjs').write_text('old isaac-lan implementation','utf8')
            with patch.dict('sys.modules',{'psutil':fake}):receipt=sync_plugin(root)
            self.assertEqual((installed/'index.mjs').read_bytes(),(source/'index.mjs').read_bytes())
            self.assertTrue((installed/'stream-policy.mjs').is_file())
            self.assertFalse(receipt['runtime_load_verified'])
            self.assertEqual({row['name'] for row in receipt['files']},
                {'package.json','index.mjs','decision_binding.mjs','stream-policy.mjs','instructions.md','cordis.patch.yml','README.md'})


if __name__=='__main__':unittest.main()
