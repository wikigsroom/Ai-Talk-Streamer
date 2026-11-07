"""Actual R6 CLI lookup/output failures and unchanged resource admission."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch

from integration.issac.common import AdmissionError
from integration.issac.local_model import LocalModel
from integration.issac.resources import MIB,assess_estimate,estimate_fits,parse_estimate


class NativeCliOutputTests(unittest.TestCase):
    observed_estimate=('Model: swift-1.5-qwen3.8-flash-next-gsq-rco-abliterated\n'
        'Context Length: 16,384\nGPU Offload: 45%\n'
        'Estimated GPU Memory:   33.84 GiB\nEstimated Total Memory: 73.40 GiB\n'
        'Estimate: This model may be loaded based on your resource guardrails settings.\n')

    def test_successful_stderr_estimate_is_read_without_turning_empty_stdout_into_a_pass(self):
        from integration.issac import local_model as module
        with tempfile.TemporaryDirectory() as temporary:
            model=LocalModel.__new__(LocalModel);model.root=Path(temporary)
            model.cli=model.root/'lms.exe';model.cli.write_bytes(b'fixture only')
            model.audit=Mock();model.environment=Mock(return_value={})
            result=subprocess.CompletedProcess([],0,b'',self.observed_estimate.encode())
            with patch.object(module.subprocess,'run',return_value=result):
                with self.assertRaisesRegex(AdmissionError,'ACTUAL_LMS_MEMORY_ESTIMATE_REQUIRED'):
                    parse_estimate(model.command('load','fixture','--estimate-only'))
                actual=parse_estimate(model.command('load','fixture','--estimate-only',include_stderr=True))
            self.assertGreater(actual['gpu_bytes'],33*1024**3)
            self.assertGreater(actual['total_bytes'],73*1024**3)

    def test_json_stdout_remains_valid_and_a_failed_command_cannot_be_parsed_as_success(self):
        from integration.issac import local_model as module
        with tempfile.TemporaryDirectory() as temporary:
            model=LocalModel.__new__(LocalModel);model.root=Path(temporary)
            model.cli=model.root/'lms.exe';model.cli.write_bytes(b'fixture only')
            model.audit=Mock();model.environment=Mock(return_value={})
            with patch.object(module.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'[]\n',b'notice')):
                self.assertEqual(model.command('ls','--json'),'[]\n')
            with patch.object(module.subprocess,'run',return_value=subprocess.CompletedProcess([],1,b'',self.observed_estimate.encode())):
                with self.assertRaisesRegex(AdmissionError,'NATIVE_LMS_COMMAND_FAILED'):
                    model.command('load','fixture',include_stderr=True)


class RetainedVariantAndCapacityTests(unittest.TestCase):
    def fixture(self):
        model=LocalModel.__new__(LocalModel)
        model.config={'retained_model_key':'SC117/locked/voice-free-IQ3_XXS-00001-of-00002.gguf',
            'retained_model_files':[{'path':'C:/dev/lmstudio/models/SC117/locked/voice-free-IQ3_XXS-00001-of-00002.gguf'}]}
        return model

    def test_exact_local_path_keeps_the_verified_quantization_instead_of_fuzzy_model_name(self):
        model=self.fixture();args=model.load_arguments(.45,16384)
        self.assertEqual(args[1],model.config['retained_model_key'])
        self.assertIn('--exact',args);self.assertIn('--local',args)
        for wrong in ('swift-1.5','SC117/locked/other-quantization.gguf',
                      'SC117/locked/voice-free-IQ3_XXS-00002-of-00002.gguf'):
            model.config['retained_model_key']=wrong
            with self.assertRaisesRegex(AdmissionError,'VERIFIED_FIRST_SHARD'):model.load_arguments(.45,16384)

    def test_a_file_outside_the_retained_model_root_is_rejected(self):
        model=self.fixture();model.config['retained_model_files'][0]['path']='C:/other/model.gguf'
        with self.assertRaisesRegex(AdmissionError,'VERIFIED_RETAINED_FIRST_SHARD'):model.load_arguments(.45,16384)

    def test_observed_three_estimates_report_real_shortfalls_without_lowering_reserves(self):
        observed={'gpu_free_mib':34780,'host_available_bytes':40672096256}
        for gpu_gib in (33.84,26.23,17.10):
            text=f'Estimated GPU Memory: {gpu_gib} GiB\nEstimated Total Memory: 73.40 GiB'
            estimate=parse_estimate(text);result=assess_estimate(estimate,observed)
            self.assertFalse(result['fits']);self.assertFalse(estimate_fits(estimate,observed))
            self.assertEqual(result['media_reserve_mib'],18000)
            self.assertEqual(result['gpu_margin_mib'],2048)
            self.assertEqual(result['host_margin_mib'],6144)
            self.assertGreater(result['host_shortfall_bytes'],0)
            self.assertEqual(result['gpu_required_bytes'],estimate['gpu_bytes']+20560*MIB)
            self.assertEqual(result['host_required_bytes'],estimate['total_bytes']-estimate['gpu_bytes']+6656*MIB)


if __name__=='__main__':unittest.main()
