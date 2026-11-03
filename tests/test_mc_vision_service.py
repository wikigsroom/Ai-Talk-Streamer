"""Vision launch boundaries; no models are loaded by these tests."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from mc_vision_service import launch_arguments


class Shared3080VisionTests(unittest.TestCase):
    def test_gpu_runtime_keeps_both_model_parts_on_cpu_for_full_cohost(self):
        with tempfile.TemporaryDirectory(prefix='mc-vision-launch-') as folder:
            root = Path(folder)
            for runtime in ('cpu', 'vulkan', 'cuda124'):
                lock = {'base_url': 'http://127.0.0.1:8019/', 'model_alias': 'mc-vision-qwen3-vl-4b',
                        'runtime_id': 'qwen3vl4b-q4km-llama-b11960-' + runtime + '-v1',
                        **{key: {'path': key + '.fixture'} for key in ('executable', 'model', 'projector')}}
                for pin in ('executable', 'model', 'projector'):
                    (root / lock[pin]['path']).touch()
                args = launch_arguments(root, lock)
                self.assertEqual(args[args.index('--n-gpu-layers') + 1], '0')
                self.assertIn('--no-mmproj-offload', args)
                self.assertEqual(args[args.index('--threads') + 1], '8')
                self.assertEqual(args[args.index('--threads-batch') + 1], '12')
                self.assertEqual(args[args.index('--parallel') + 1], '1')
                self.assertEqual(args[args.index('--ctx-size') + 1], '2048')
                self.assertEqual(args[args.index('--model') + 1], str(root / 'model.fixture'))

    def test_non_loopback_endpoint_cannot_be_launched(self):
        with self.assertRaisesRegex(RuntimeError, 'CANONICAL_ENDPOINT'):
            launch_arguments(Path.cwd(), {'base_url': 'http://192.168.196.209:8019/'})


if __name__ == '__main__':
    unittest.main()
