"""Behavioral checks for clip continuity and live gesture scheduling (no models/GPU)."""
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('motion_control', ROOT / 'integration/motion_control.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def controller():
    return module.MotionController({'clips': [
        {'id': 'idle', 'title': 'idle', 'category': 'idle', 'start_frame': 0, 'frames': 200},
        {'id': 'listen', 'title': 'listen', 'category': 'listen', 'start_frame': 200, 'frames': 200},
        {'id': 'posture', 'title': 'posture', 'category': 'posture', 'start_frame': 400, 'frames': 200},
        {'id': 'explain', 'title': 'explain', 'category': 'explain', 'start_frame': 600, 'frames': 200},
        {'id': 'wave', 'title': 'wave', 'category': 'welcome', 'start_frame': 800, 'frames': 200},
    ]})

class MotionContinuityTests(unittest.TestCase):
    def test_manual_request_preserves_remaining_body_frames(self):
        motion = controller()
        motion.next_indices(196)
        motion.request('wave')
        self.assertEqual(motion.status()['active'], 'idle')
        self.assertEqual(motion.next_indices(8), [196, 197, 198, 199, 800, 801, 802, 803])

    def test_latest_pending_request_replaces_earlier_one(self):
        motion = controller()
        motion.request('wave')
        motion.request('explain')
        self.assertEqual(motion.next_indices(201)[-1], 600)
        self.assertIsNone(motion.status()['pending'])

    def test_manual_clip_plays_once_then_returns_to_quiet_selection(self):
        motion = controller()
        motion.request('wave')
        frames = motion.next_indices(601, speaking=False)
        self.assertEqual(frames[200:400], list(range(800, 1000)))
        self.assertTrue(all(index < 600 for index in frames[400:]))

    def test_calm_automatic_mode_stays_quiet_during_speech(self):
        motion = controller()
        motion.request('calm')
        self.assertTrue(all(index < 600 for index in motion.next_indices(6000, speaking=True)))

    def test_auto_includes_explanation_while_speaking(self):
        motion = controller()
        frames = motion.next_indices(2400, speaking=True)
        self.assertTrue(any(600 <= i < 800 for i in frames))
        self.assertFalse(any(i >= 800 for i in frames))

    def test_auto_or_calm_cancels_pending_manual_request(self):
        for mode in ('auto', 'calm'):
            with self.subTest(mode=mode):
                motion = controller()
                motion.request('wave')
                motion.request(mode)
                self.assertIsNone(motion.status()['pending'])
                self.assertTrue(all(i < 600 for i in motion.next_indices(1000)))

    def test_unknown_id_does_not_change_pending_action(self):
        motion = controller()
        motion.request('wave')
        with self.assertRaises(ValueError):
            motion.request('unreviewed')
        self.assertEqual(motion.status()['pending'], 'wave')

    def test_batch_sizes_do_not_change_body_frame_continuity(self):
        one = controller()
        batched = controller()
        one.request('wave')
        batched.request('wave')
        expected = one.next_indices(1200, speaking=True)
        actual = []
        for size in [7, 193, 8, 192, 11, 389, 400]:
            actual.extend(batched.next_indices(size, speaking=True))
        self.assertEqual(actual, expected)

if __name__ == '__main__':
    unittest.main()
