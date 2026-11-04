"""Bounded startup resource waiting; fixtures never invoke a real GPU or model."""
from pathlib import Path
from unittest.mock import patch
import json
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import launch
import mc_application


class NativeGpuStartTests(unittest.TestCase):
    def timer(self):
        elapsed = [0.0]
        return lambda: elapsed[0], lambda delay: elapsed.__setitem__(0, elapsed[0] + delay)

    def test_transient_pressure_waits_until_the_unchanged_memory_gate_is_met(self):
        clock, sleep = self.timer()
        with patch.object(launch, 'gpu_free', side_effect=[1024, 2047, 2048]):
            result = launch.wait_for_gpu('tts', 2, timeout=5, clock=clock, sleep=sleep)
        self.assertEqual(result, {'service':'tts','free_mib':2048,'minimum_mib':2048,'waited_ms':2000,'probes':3})

    def test_deadline_returns_last_actual_capacity_and_keeps_the_threshold(self):
        clock, sleep = self.timer()
        with patch.object(launch, 'gpu_free', return_value=2047):
            with self.assertRaises(launch.ServiceStartError) as failed:
                launch.wait_for_gpu('tts', 2, timeout=2, clock=clock, sleep=sleep)
        details = failed.exception.details
        self.assertEqual(details['free_mib'], 2047); self.assertEqual(details['minimum_mib'], 2048)
        self.assertEqual(details['waited_ms'], 2000)
        safe = mc_application.startup_diagnostic(failed.exception, 'studio_spawn_tts', 2000)
        self.assertEqual(safe['exception_chain'][0]['reason_code'], 'MC_SERVICE_GPU_MEMORY_LOW')
        self.assertEqual(safe['exception_chain'][0]['resources'], details)

    def test_query_timeout_is_not_treated_as_available_memory(self):
        clock, sleep = self.timer()
        with patch.object(launch, 'gpu_free', side_effect=subprocess.TimeoutExpired(['nvidia-smi'],10)):
            with self.assertRaises(subprocess.TimeoutExpired):
                launch.wait_for_gpu('avatar', 2, clock=clock, sleep=sleep)

    def test_gpu_query_itself_has_a_ten_second_timeout(self):
        with patch.object(launch.subprocess, 'check_output', return_value='4096\n') as query:
            self.assertEqual(launch.gpu_free(), 4096)
        self.assertEqual(query.call_args.kwargs['timeout'], 10)

    def test_diagnostic_discards_non_numeric_or_unknown_resource_fields(self):
        error = launch.ServiceStartError('MC_SERVICE_GPU_MEMORY_LOW', service='tts',free_mib='SECRET_EXAMPLE',
            minimum_mib=2048,waited_ms=120000,probes=4,provider_key='SECRET_EXAMPLE')
        result = mc_application.startup_diagnostic(error, 'studio_spawn_tts', 120000)
        self.assertNotIn('SECRET_EXAMPLE',json.dumps(result))
        self.assertEqual(result['exception_chain'][0]['resources'],{'service':'tts','minimum_mib':2048,'waited_ms':120000,'probes':4})


if __name__ == '__main__': unittest.main(verbosity=2)
