import sys
from pathlib import Path
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from native_windows_display import NativeDisplayLease, ES_CONTINUOUS, ES_DISPLAY_REQUIRED, DISPLAY_REFRESH_SECONDS


class DisplayRequirementTests(unittest.TestCase):
    def test_scoped_request_and_restore_on_body_failure(self):
        calls = []
        def call(flags):
            calls.append(flags)
            return ES_CONTINUOUS
        lease = NativeDisplayLease(call)
        with self.assertRaisesRegex(ValueError, 'body'):
            with lease:
                self.assertTrue(lease.proof()['active'])
                raise ValueError('body')
        self.assertEqual(calls, [ES_CONTINUOUS | ES_DISPLAY_REQUIRED, ES_CONTINUOUS])
        self.assertFalse(lease.proof()['active'])

    def test_restore_previous_thread_requirements(self):
        calls = []
        def call(flags):
            calls.append(flags)
            return ES_CONTINUOUS | 1
        lease = NativeDisplayLease(call)
        with lease:
            self.assertEqual(lease.proof()['previous_thread_flags'], ES_CONTINUOUS | 1)
        self.assertEqual(calls[-1], ES_CONTINUOUS | 1)
        lease.release()
        self.assertEqual(len(calls), 2)

    def test_failed_acquire_never_claims_active_or_releases(self):
        calls = []
        lease = NativeDisplayLease(lambda flags: calls.append(flags) or 0)
        with self.assertRaisesRegex(RuntimeError, 'REQUEST_FAILED'):
            lease.acquire()
        lease.release()
        self.assertFalse(lease.proof()['active'])
        self.assertEqual(len(calls), 1)

    def test_double_acquire_does_not_lose_original_state(self):
        calls = []
        lease = NativeDisplayLease(lambda flags: calls.append(flags) or ES_CONTINUOUS).acquire()
        with self.assertRaisesRegex(RuntimeError, 'ALREADY_REQUIRED'):
            lease.acquire()
        self.assertEqual(len(calls), 1)
        lease.release()
        self.assertEqual(calls[-1], ES_CONTINUOUS)

    def test_other_thread_cannot_release_owners_requirement(self):
        calls = []; errors = []
        lease = NativeDisplayLease(lambda flags: calls.append(flags) or ES_CONTINUOUS).acquire()
        def other():
            try: lease.release()
            except RuntimeError as error: errors.append(str(error))
        thread = threading.Thread(target=other); thread.start(); thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ['NATIVE_DISPLAY_WRONG_THREAD'])
        self.assertTrue(lease.proof()['active']); self.assertEqual(len(calls), 1)
        lease.release()

    def test_failed_release_is_visible_and_retryable(self):
        answers = iter([ES_CONTINUOUS, 0, ES_CONTINUOUS])
        lease = NativeDisplayLease(lambda flags: next(answers)).acquire()
        with self.assertRaisesRegex(RuntimeError, 'RELEASE_FAILED'):
            lease.release()
        self.assertTrue(lease.proof()['active'])
        lease.release()
        self.assertFalse(lease.proof()['active'])

    def test_periodic_reset_is_throttled_and_preserves_original_release_state(self):
        calls = []; now = [0.0]
        def call(flags):
            calls.append(flags)
            return ES_CONTINUOUS | 1
        lease = NativeDisplayLease(call, clock=lambda: now[0]).acquire()
        now[0] = DISPLAY_REFRESH_SECONDS - .01
        self.assertFalse(lease.refresh()); self.assertEqual(len(calls), 1)
        now[0] = DISPLAY_REFRESH_SECONDS
        self.assertTrue(lease.refresh()); self.assertFalse(lease.refresh())
        self.assertEqual(calls[1], ES_DISPLAY_REQUIRED)
        self.assertEqual(lease.proof()['refresh_count'], 1)
        self.assertIsNotNone(lease.proof()['last_refresh_at'])
        lease.release(); self.assertEqual(calls[-1], ES_CONTINUOUS | 1)

    def test_failed_reset_is_visible_throttled_and_retryable_without_closing_lease(self):
        calls = []; now = [0.0]; answers = iter([ES_CONTINUOUS, 0, ES_CONTINUOUS | ES_DISPLAY_REQUIRED, ES_CONTINUOUS])
        def call(flags):
            calls.append(flags); return next(answers)
        lease = NativeDisplayLease(call, clock=lambda: now[0]).acquire()
        now[0] = DISPLAY_REFRESH_SECONDS
        self.assertTrue(lease.refresh()); self.assertTrue(lease.proof()['active'])
        self.assertEqual(lease.proof()['last_refresh_error'], 'NATIVE_DISPLAY_REFRESH_FAILED')
        self.assertEqual(lease.proof()['refresh_count'], 0)
        self.assertEqual(lease.proof()['refresh_failures'], 1)
        self.assertFalse(lease.refresh()); self.assertEqual(len(calls), 2)
        now[0] += DISPLAY_REFRESH_SECONDS
        self.assertTrue(lease.refresh()); self.assertIsNone(lease.proof()['last_refresh_error'])
        self.assertEqual(lease.proof()['refresh_count'], 1)
        lease.release(); self.assertFalse(lease.proof()['active'])

    def test_other_thread_cannot_reset_the_owners_timer(self):
        calls = []; errors = []
        lease = NativeDisplayLease(lambda flags: calls.append(flags) or ES_CONTINUOUS).acquire()
        def other():
            try: lease.refresh()
            except RuntimeError as error: errors.append(str(error))
        thread = threading.Thread(target=other); thread.start(); thread.join(timeout=5)
        self.assertFalse(thread.is_alive()); self.assertEqual(errors, ['NATIVE_DISPLAY_WRONG_THREAD'])
        self.assertEqual(len(calls), 1); lease.release()

    def test_inactive_or_released_lease_cannot_reset_display(self):
        calls = []
        lease = NativeDisplayLease(lambda flags: calls.append(flags) or ES_CONTINUOUS)
        with self.assertRaisesRegex(RuntimeError, 'NOT_ACTIVE'): lease.refresh()
        lease.acquire(); lease.release()
        with self.assertRaisesRegex(RuntimeError, 'NOT_ACTIVE'): lease.refresh()
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
