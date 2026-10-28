"""K02 pixel equivalence, frame/audio association and source-patch contracts."""
import ast
import json
from pathlib import Path
import queue
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from deployment.activate_k02 import activate, patch_sources
from integration.lipsync_k02 import K02Compositor, blend_mouth

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT/'tests/fixtures/livetalking-c7269433'


def frozen_reference():
    tree = ast.parse((ROOT/'benchmarks/k01-k05-60s-20261028/bench_common.py').read_text('utf-8'))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'mouth_blend')
    namespace = {'np':np, 'cv2':cv2}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<frozen-K02-reference>', 'exec'), namespace)
    return namespace['mouth_blend']


def audio(amplitude):
    return [SimpleNamespace(data=np.full(320, amplitude, np.float32), type=0, userdata={}) for _ in range(2)]


def method(source, class_name, method_name, namespace):
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    node = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<pinned-method>', 'exec'), namespace)
    return namespace[method_name]


class K02Tests(unittest.TestCase):
    def test_exact_pixels_match_the_frozen_experiment(self):
        reference = frozen_reference()
        rng = np.random.default_rng(20261029)
        source = rng.integers(0, 256, (260, 190, 3), np.uint8)
        for bbox in [(20, 30, 120, 180), (0, 0, 190, 260), (45, 48, 96, 111)]:
            for strength in (0, .001, .35, .65, .995, 1):
                pred = rng.integers(0, 256, (256, 256, 3), np.uint8)
                with self.subTest(box=bbox, strength=strength):
                    np.testing.assert_array_equal(blend_mouth(source, pred, bbox, strength),
                        reference(source, pred, bbox, strength, color=True))

    def test_cached_source_and_upper_face_remain_unchanged(self):
        source = np.full((180, 140, 3), 30, np.uint8)
        source.flags.writeable = False
        pred = np.full((256, 256, 3), 180, np.uint8)
        result = blend_mouth(source, pred, (20, 20, 120, 160), 1)
        np.testing.assert_array_equal(source, np.full(source.shape, 30, np.uint8))
        np.testing.assert_array_equal(result[:65], source[:65])
        np.testing.assert_array_equal(result[:, :20], source[:, :20])
        self.assertTrue(np.any(result[90:150, 40:100] != source[90:150, 40:100]))
        self.assertFalse(np.shares_memory(result, source))

    def test_gate_uses_both_matching_chunks_and_fades_during_silence(self):
        gate = K02Compositor()
        self.assertEqual(gate.advance(audio(0)), 0)
        mixed = audio(0)
        mixed[1].data[:] = .1
        self.assertAlmostEqual(gate.advance(mixed), .35)
        for _ in range(50): gate.advance(audio(.1))
        self.assertGreater(gate.strength, .999)
        for _ in range(12): gate.advance(audio(0))
        self.assertLess(gate.strength, .006)

    def test_first_frame_and_sessions_are_independent(self):
        a, b = K02Compositor(), K02Compositor()
        self.assertEqual(a.advance(audio(.1)), 1)
        self.assertEqual(b.advance(audio(0)), 0)
        self.assertEqual(a.advance(audio(0)), .65)

    def test_invalid_audio_and_missing_consumer_hook_are_rejected(self):
        gate = K02Compositor()
        with self.assertRaises(RuntimeError):gate.blend(np.zeros((40, 40, 3), np.uint8), None, (0, 0, 40, 40))
        for frames in ([], audio(0)[:1], [SimpleNamespace(data=np.zeros(319)), audio(0)[1]],
                       [SimpleNamespace(data=np.full(320, np.nan)), audio(0)[1]]):
            with self.assertRaises(ValueError):gate.advance(frames)

    def test_patch_is_idempotent_and_checks_unknown_upstream(self):
        base = (FIXTURES/'base_avatar.py').read_text('utf-8')
        muse = (FIXTURES/'musetalk_avatar.py').read_text('utf-8')
        first = patch_sources(base, muse)
        self.assertEqual(first, patch_sources(*first))
        with self.assertRaises(RuntimeError):patch_sources(base.replace('res_frame,audio_frames,idx =', 'different ='), muse)
        with self.assertRaises(RuntimeError):patch_sources(base, muse.replace('def paste_back_frame(', 'def renamed_method('))

    def test_offline_activation_keeps_private_config_and_backs_up_originals(self):
        parent = ROOT.parent/'cache/k02-test-fixtures'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            root = Path(folder)
            for name in ('base_avatar.py', 'musetalk_avatar.py'):
                target = root/'src/LiveTalking/avatars'/name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((FIXTURES/name).read_bytes())
            (root/'integration').mkdir()
            (root/'integration/lipsync_k02.py').write_bytes((ROOT/'integration/lipsync_k02.py').read_bytes())
            (root/'configs').mkdir()
            config = root/'configs/livetalking.yaml'
            original = json.dumps({'model':'musetalk', 'batch_size':8, 'fps':25,
                'tts':'resident-local', 'avatar_id':'student_dorm_motion_bank_v3'}).encode()
            config.write_bytes(original)
            with patch('deployment.activate_k02.socket.socket') as socket_mock:
                socket_mock.return_value.__enter__.return_value.connect_ex.return_value = 1
                receipt = activate(root)
            self.assertFalse(receipt['services_started'])
            self.assertFalse(receipt['private_livetalking_config_changed'])
            self.assertEqual(config.read_bytes(), original)
            for name in ('base_avatar.py', 'musetalk_avatar.py'):
                saved = root/receipt['backup']/'src/LiveTalking/avatars'/name
                self.assertEqual(saved.read_bytes(), (FIXTURES/name).read_bytes())
            installed = (root/'src/LiveTalking/server/lipsync_k02.py').read_text('utf-8')
            self.assertEqual(ast.dump(ast.parse(installed)),
                             ast.dump(ast.parse((ROOT/'integration/lipsync_k02.py').read_text('utf-8'))))
            # A generic batch4 configuration must not silently change the
            # selected baseline. Only the explicitly measured 3080 variant may.
            batch4 = json.loads(original)
            batch4['batch_size'] = 4
            config.write_text(json.dumps(batch4), encoding='utf-8')
            with patch('deployment.activate_k02.socket.socket') as socket_mock:
                socket_mock.return_value.__enter__.return_value.connect_ex.return_value = 1
                with self.assertRaises(RuntimeError):activate(root)
                (root/'configs/hardware-profile.json').write_text(
                    json.dumps({'preset':'rtx3080-k02-batch4'}), encoding='utf-8')
                receipt4 = activate(root)
            self.assertEqual(receipt4['batch_size'], 4)
            self.assertEqual(json.loads(config.read_text('utf-8')), batch4)

    def test_patched_consumer_uses_each_dequeued_audio_without_reordering(self):
        import time
        base, muse = patch_sources((FIXTURES/'base_avatar.py').read_text('utf-8'),
                                   (FIXTURES/'musetalk_avatar.py').read_text('utf-8'))
        quit_event = Event()
        frames = queue.Queue()
        source = np.zeros((160, 120, 3), np.uint8)
        prediction = np.full((256, 256, 3), 200, np.uint8)
        for amplitude in (.1, 0, .1):frames.put((prediction, audio(amplitude), 0))
        observed, pushed_audio = [], []
        namespace = {'queue':queue, 'time':time, 'cv2':cv2, 'np':np,
            'logger':SimpleNamespace(info=lambda *a:None, warning=lambda *a:None)}
        paste = method(muse, 'MuseReal', 'paste_back_frame', namespace)
        owner = SimpleNamespace(_studio_k02=K02Compositor(), frame_list_cycle=[source],
            coord_list_cycle=[(10, 20, 110, 150)], res_frame_queue=frames,
            record_video_data=lambda *a:None, record_audio_data=lambda *a:None,
            output=SimpleNamespace(start=lambda:None, stop=lambda:None))
        owner.paste_back_frame = lambda pred, idx:paste(owner, pred, idx)
        def video(frame):
            observed.append(owner._studio_k02.strength)
            if len(observed) == 3:quit_event.set()
        owner.output.push_video_frame = video
        owner.output.push_audio_frame = lambda data, info:pushed_audio.append(data.copy())
        process = method(base, 'BaseAvatar', 'process_frames', namespace)
        process(owner, quit_event)
        np.testing.assert_allclose(observed, [1, .65, .7725])
        self.assertEqual(len(pushed_audio), 6)
        np.testing.assert_array_equal(pushed_audio[2], np.zeros(320, np.int16))
        self.assertTrue(np.all(source == 0))


if __name__ == '__main__':
    unittest.main()
