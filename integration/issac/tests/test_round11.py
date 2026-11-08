"""Exercise bounded layer plateaus without accepting simulated capacity."""
import unittest

from integration.issac.resources import MIB,assess_estimate,offload_candidates


class LayerBoundaryTests(unittest.TestCase):
    def test_intermediate_layer_fits_both_axes_when_coarse_gpu_or_host_plans_do_not(self):
        # Synthetic LMS layer plateaus, not an actual model measurement. The
        # device's new estimates and measured media receipt remain mandatory.
        observed={'gpu_free_mib':48128,'host_available_bytes':57000*MIB}
        options=offload_candidates(.45)
        def assess(ratio):
            gpu=28467 if ratio>=.36 else 27648 if ratio>=.35 else 26860
            return assess_estimate({'gpu_bytes':gpu*MIB,'total_bytes':75162*MIB},observed,
                reserve_mib=17310,host_extra_reserve_mib=2500)
        self.assertGreater(assess(.36)['gpu_shortfall_bytes'],0)
        self.assertGreater(assess(.338)['host_shortfall_bytes'],0)
        selected=next((ratio for ratio in options if assess(ratio)['fits']),None)
        self.assertIsNotNone(selected)
        self.assertTrue(.338<selected<.36)
        result=assess(selected)
        self.assertEqual(result['media_reserve_mib'],17310)
        self.assertEqual(result['gpu_margin_mib'],2048)
        self.assertEqual(result['host_margin_mib'],6144)
        self.assertEqual(result['host_extra_reserve_mib'],2500)
        self.assertEqual(result['estimate_rounding_mib'],512)
        self.assertEqual(options,sorted(set(options),reverse=True))
        self.assertLessEqual(len(options),10)
        self.assertTrue(all(0<ratio<=.45 for ratio in options))


if __name__=='__main__':unittest.main()
