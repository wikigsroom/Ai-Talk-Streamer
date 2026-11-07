import tempfile
import unittest
from pathlib import Path

from isaac_jev.tuning import PolicyProfile, analyze_episodes, applied_death_counts, load_profile, pending_events, suggest_profile, write_profile


class TuningTests(unittest.TestCase):
    def test_insufficient_evidence_keeps_profile(self):
        profile = PolicyProfile()
        self.assertEqual(suggest_profile([{"cause": "projectile_hit"}], profile), profile)

    def test_repeated_causes_change_bounded_profile(self):
        profile = PolicyProfile(jev_timeout_seconds=0.30, confidence_threshold=0.94)
        events = [{"cause": "projectile_hit"}, {"cause": "projectile_hit"}, {"cause": "decision_latency"}, {"cause": "decision_latency"}]
        tuned = suggest_profile(events, profile)
        self.assertGreater(tuned.projectile_evade_radius, profile.projectile_evade_radius)
        self.assertEqual(tuned.confidence_threshold, 0.95)
        self.assertGreaterEqual(tuned.jev_timeout_seconds, 0.25)

    def test_profile_round_trip_and_bad_values_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            output = write_profile(Path(directory), PolicyProfile(enemy_safe_distance=999), {"cause": "test"})
            self.assertEqual(output.name, "policy_profile.json")
            self.assertEqual(load_profile(directory).enemy_safe_distance, 180.0)
            output.write_text("{bad", encoding="utf-8")
            self.assertEqual(load_profile(directory), PolicyProfile())

    def test_analyze_skips_malformed_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.jsonl"
            path.write_text("bad\n{\"type\":\"death_episode\",\"cause\":\"enemy_contact\"}\n", encoding="utf-8")
            self.assertEqual(len(analyze_episodes(path)), 1)

    def test_pending_events_prevent_reapplying_old_deaths(self):
        events = [{"cause": "projectile_hit"}, {"cause": "projectile_hit"}, {"cause": "enemy_contact"}]
        self.assertEqual(len(pending_events(events, {"projectile_hit": 2, "enemy_contact": 1})), 0)
        self.assertEqual(len(pending_events(events, {"projectile_hit": 1})), 2)

    def test_written_evidence_marks_death_counts_as_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            write_profile(Path(directory), PolicyProfile(), {"death_counts": {"projectile_hit": 2}})
            self.assertEqual(applied_death_counts(directory), {"projectile_hit": 2})
