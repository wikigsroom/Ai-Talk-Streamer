"""Reject unmeasured budgets; reproduce delayed official profile creation."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from integration.issac.common import AdmissionError,file_hash,read_json,write_json
from integration.issac.media_capacity import budget,measured_reserves
from integration.issac.resources import MIB,assess_estimate,offload_candidates


def measurement():
    actors={role:{'role':role,'passed':True,'exit_code':0,'cuda_peak_reserved_bytes':size*MIB,
        'host_peak_bytes':1024*MIB} for role,size in [('voice',4096),('mouth',6144)]}
    actors['voice'].update(voice_id='NCM01',precision='torch.float16',steps=32,reference_preprocess_prompt=False)
    actors['mouth'].update(actual_new_frames=288,steps=4,batch=1,width=512,height=512,compile_mode='model-vae',fast_rope=True)
    return {'passed':True,'scope':'capacity_only','quality_accepted':False,'normal_cleanup':True,
        'concurrent_residency_observed':True,'foreign_jobs_observed':False,'actors':actors,
        'observed_gpu_delta_bytes':9000*MIB,'observed_host_delta_bytes':2000*MIB}


class MeasuredCapacityTests(unittest.TestCase):
    def test_separate_allocator_peaks_are_summed_and_all_existing_margins_remain(self):
        row=measurement();reserves=measured_reserves(row)
        self.assertEqual(reserves['media_reserve_mib'],12288)
        self.assertEqual(reserves['host_extra_reserve_mib'],0)
        result=assess_estimate({'gpu_bytes':30000*MIB,'total_bytes':70000*MIB},
            {'gpu_free_mib':48000,'host_available_bytes':60000*MIB},reserve_mib=reserves['media_reserve_mib'])
        self.assertEqual(result['gpu_required_bytes'],(30000+12288+2048+512)*MIB)
        self.assertEqual(result['host_required_bytes'],(40000+6144+512)*MIB)

    def test_larger_global_peaks_and_host_transients_add_reservation(self):
        row=measurement();row['observed_gpu_delta_bytes']=20000*MIB;row['observed_host_delta_bytes']=9000*MIB
        reserves=measured_reserves(row)
        self.assertEqual(reserves['media_reserve_mib'],22048)
        self.assertEqual(reserves['host_extra_reserve_mib'],4904)
        result=assess_estimate({'gpu_bytes':100*MIB,'total_bytes':200*MIB},
            {'gpu_free_mib':48000,'host_available_bytes':10000*MIB},host_extra_reserve_mib=4904)
        self.assertFalse(result['fits']);self.assertGreater(result['host_shortfall_bytes'],0)

    def test_no_static_mouth_changed_voice_foreign_job_or_unclean_worker_can_select_a_budget(self):
        changes=[('passed',False),('quality_accepted',True),('normal_cleanup',False),
            ('concurrent_residency_observed',False),('foreign_jobs_observed',True),('observed_gpu_delta_bytes',0)]
        for key,value in changes:
            with self.subTest(key=key):
                row=measurement();row[key]=value
                with self.assertRaises(AdmissionError):measured_reserves(row)
        for role,key,value in [('voice','steps',16),('voice','precision','torch.float32'),
                ('voice','voice_id','O07'),('mouth','actual_new_frames',24),('mouth','width',640),
                ('mouth','compile_mode','none'),('mouth','exit_code',1),('mouth','cuda_peak_reserved_bytes',0)]:
            row=measurement();row['actors'][role][key]=value
            with self.subTest(role=role,key=key),self.assertRaises(AdmissionError):measured_reserves(row)

    def test_no_receipt_or_a_previous_candidate_keeps_18000_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            self.assertEqual(budget(root,'new')['media_reserve_mib'],18000)
            write_json(root/'.setup/issac-media-capacity.json',{'candidate_id':'old','report':'missing'})
            self.assertEqual(budget(root,'new')['source'],'unmeasured_default')

    def test_edited_report_or_missing_actor_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);report=root/'state/report.json';write_json(report,measurement())
            write_json(root/'.setup/issac-media-capacity.json',{'candidate_id':'new','report':'state/report.json','sha256':'0'*64})
            with self.assertRaisesRegex(AdmissionError,'REPORT_CHANGED'):budget(root,'new')
            row=read_json(report);row.update(candidate_id='new',input_signature='fixture',finished_unix=100)
            write_json(report,row)
            write_json(root/'.setup/issac-media-capacity.json',{'candidate_id':'new','report':'state/report.json','sha256':file_hash(report)})
            with patch('integration.issac.media_capacity.input_signature',return_value='fixture'),patch('integration.issac.media_capacity.time.time',return_value=100):
                with self.assertRaisesRegex(AdmissionError,'BOTH_REAL_MEDIA_REPORTS'):budget(root,'new')

    def test_intermediate_offload_candidates_preserve_exact_local_model_and_context_selection(self):
        self.assertEqual(offload_candidates(.45),[.45,.405,.375,.36,.338,.225])
        for bad in (0,-1,float('nan'),.61,True):
            with self.subTest(bad=bad),self.assertRaises(AdmissionError):offload_candidates(bad)


class DelayedOfficialProfileTests(unittest.TestCase):
    def test_cef_owned_panels_are_excluded_but_two_independent_frames_remain_ambiguous(self):
        from integration.issac.official_window import primary_windows
        rows=[{'hwnd':1,'owner_hwnd':0},{'hwnd':2,'owner_hwnd':1},{'hwnd':3,'owner_hwnd':2}]
        self.assertEqual(primary_windows(rows),[rows[0]])
        rows.append({'hwnd':4,'owner_hwnd':0})
        self.assertEqual(len(primary_windows(rows)),2)

    def fixture(self,root):
        from integration.issac.livehime import Livehime
        client=Livehime.__new__(Livehime);client.registration=root/'registration.json';client.audit=Mock()
        window={'hwnd':11,'pid':22,'created_at':33}
        proofs=[{'verified':False,'foreign_profile_files':[]},{'verified':True,'foreign_profile_files':[]}]
        def native(action,**kwargs):return {'windows':[window]} if action=='windows' else proofs.pop(0)
        client.native_window=Mock(side_effect=native)
        return client,proofs

    def test_a_stable_login_window_waits_for_actual_profile_files_before_registration(self):
        from integration.issac import livehime as module
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);client,proofs=self.fixture(root);clock=SimpleNamespace(now=0)
            def sleep(seconds):clock.now+=seconds
            with patch.object(module.time,'monotonic',side_effect=lambda:clock.now),patch.object(module.time,'sleep',side_effect=sleep):
                row=client.wait_ready(SimpleNamespace(poll=lambda:None),SimpleNamespace(pid=22),{'pid':22})
            self.assertTrue(row['ready']);self.assertTrue(row['profile_isolation_verified']);self.assertFalse(proofs)
            self.assertGreater(clock.now,5);self.assertTrue(read_json(client.registration)['profile_proof']['verified'])

    def test_a_foreign_profile_is_rejected_instead_of_waited_away(self):
        from integration.issac import livehime as module
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);client,proofs=self.fixture(root);clock=SimpleNamespace(now=0)
            proofs[0]['foreign_profile_files']=['C:/foreign/livehime/settings.ini']
            def sleep(seconds):clock.now+=seconds
            with patch.object(module.time,'monotonic',side_effect=lambda:clock.now),patch.object(module.time,'sleep',side_effect=sleep):
                with self.assertRaisesRegex(AdmissionError,'PROFILE_ISOLATION'):client.wait_ready(SimpleNamespace(poll=lambda:None),SimpleNamespace(pid=22),{})
            self.assertFalse(client.registration.exists())


class CapacityPrerequisiteTests(unittest.TestCase):
    def test_a_failed_requested_media_measurement_blocks_model_load_before_inference(self):
        path=Path(__file__).resolve().parents[3]/'scripts/run_issac_round.py'
        spec=importlib.util.spec_from_file_location('round8_uniform',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        result=module.blocked_by_prerequisite('local-model-prepare',[],require_media_profile=True)
        self.assertEqual(result['requires'],'media-capacity');self.assertFalse(result['actual_inference'])
        self.assertIsNone(module.blocked_by_prerequisite('local-model-prepare',[{'check':'media-capacity','passed':True}],require_media_profile=True))


if __name__=='__main__':unittest.main()
