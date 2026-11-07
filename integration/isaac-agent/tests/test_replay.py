import json
import tempfile
import unittest
from pathlib import Path

from isaac_jev.models import Entity, GameState, Vec2
from isaac_jev.replay import DecisionTraceRecorder, evaluate_traces, read_traces


class ReplayTests(unittest.TestCase):
    def test_trace_round_trip_is_key_free_and_evaluable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision_traces.jsonl"
            recorder = DecisionTraceRecorder(path)
            trace_id = recorder.record({
                "frame": 8,
                "api_key": "must-not-be-written",
                "candidate_set": {"policy": "combat", "raw_candidates": [{"id": "a"}, {"id": "b"}], "admissible_candidates": [{"id": "a"}, {"id": "b"}], "rejected_candidates": []},
                "output": {"action": "a"}, "latency_ms": 12.5, "remote_latency_ms": 11.0,
                "remote_call": True, "request_bytes": 800, "state_bytes": 600, "estimated_input_tokens": 200,
            })
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("must-not-be-written", text)
            traces = read_traces(path)
            self.assertEqual(traces[0]["trace_id"], trace_id)
            summary = evaluate_traces(traces)
            self.assertEqual(summary["traces"], 1)
            self.assertEqual(summary["candidate_count_compliance"], 1.0)
            self.assertEqual(summary["remote_call_count"], 1)
            self.assertEqual(summary["request_bytes_avg"], 800.0)
            self.assertEqual(summary["estimated_input_tokens_avg"], 200.0)

    def test_malformed_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision_traces.jsonl"
            path.write_text("bad\n{}\n", encoding="utf-8")
            self.assertEqual(read_traces(path), [])

    def test_geometry_contains_ttc_and_entity_metadata(self):
        state = GameState(
            frame=1,
            room_clear=False,
            player=Entity(0, 1, Vec2(), Vec2(), 6),
            enemies=(Entity(2, 10, Vec2(100, 0), Vec2(), 5, variant=3, subtype=4, state=7, telegraph="windup"),),
            projectiles=(Entity(3, 9, Vec2(60, 0), Vec2(-2, 0), 0),),
        )
        compact = state.compact()
        self.assertEqual(compact["nearby_enemies"][0]["variant"], 3)
        self.assertEqual(compact["nearby_enemies"][0]["telegraph"], "windup")
        self.assertIsNotNone(compact["geometry"]["nearest_projectile_ttc_frames"])


if __name__ == "__main__":
    unittest.main()
