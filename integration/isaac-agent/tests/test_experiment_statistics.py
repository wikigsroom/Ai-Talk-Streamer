import json
import tempfile
import unittest
from pathlib import Path

from isaac_jev.experiment import (
    ExperimentEventRecorder,
    IncrementalStatistics,
    filter_comparison_records,
)
from isaac_jev.replay import DecisionTraceRecorder, evaluate_provider_statistics


def decision(**changes):
    value = {
        "schema_version": 3,
        "trace_id": "trace-1",
        "start_seed": 1234,
        "provider": "laya",
        "model": "laya-rl-agent",
        "remote_call": True,
        "model_choice": "retreat_and_fire",
        "executed_action": "retreat_and_fire",
        "raw_confidence": 0.86,
        "top_probability": 0.9,
        "margin": 0.55,
        "client_latency_ms": 20,
        "server_latency_ms": 15,
        "shadow_result": {"choice": "strafe_left", "client_latency_ms": 29},
    }
    value.update(changes)
    return value


def event(event_type, **changes):
    value = {
        "schema_version": 3,
        "type": event_type,
        "event_id": f"event-{event_type}-{len(changes)}",
        "run_id": "run-1",
        "room_visit_id": "room-1",
        "start_seed": 1234,
        "provider": "laya",
        "model": "laya-rl-agent",
    }
    value.update(changes)
    return value


class ExperimentStatisticsTests(unittest.TestCase):
    def test_recorder_recursively_removes_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "experiment_runs.jsonl"
            recorder = ExperimentEventRecorder(path)
            recorder.record("run_started", authorization="Bearer secret", nested={"TYPESAFE_API_KEY": "secret"})
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("secret", text)
            value = json.loads(text)
            self.assertEqual(value["schema_version"], 3)

    def test_group_metrics_cover_results_calibration_and_shadow(self):
        stats = IncrementalStatistics()
        stats.ingest_trace(decision())
        stats.ingest_trace({
            "schema_version": 3,
            "type": "outcome",
            "trace_id": "trace-1",
            "horizon_frames": 30,
            "outcome": {"success": True},
        })
        stats.ingest_event(event("run_started"))
        stats.ingest_event(event("room_started", event_id="room-start", combat=True, enemy_count=3))
        stats.ingest_event(event("room_completed", event_id="room-clear", combat=True, clear_frames=120))
        stats.ingest_event(event("damage", event_id="damage-1", damage_kind="projectile"))
        stats.ingest_event(event("damage", event_id="damage-1", damage_kind="projectile"))
        stats.ingest_event(event("damage", event_id="damage-2", damage_kind="enemy_contact"))
        stats.ingest_event(event("stall_started", event_id="stall-1"))
        stats.ingest_event(event("stall_recovered", event_id="recovery-1", recovery_frames=18))
        stats.ingest_event(event("death", event_id="death-1"))

        summary = stats.snapshot(seed=1234, provider="laya", model="laya-rl-agent")
        self.assertEqual(summary["group_count"], 1)
        group = summary["groups"][0]
        self.assertEqual(group["remote_calls"], 1)
        self.assertEqual(group["damage_events"], 2)
        self.assertEqual(group["projectile_hit_rate"], 0.5)
        self.assertEqual(group["contact_hit_rate"], 0.5)
        self.assertEqual(group["clear_rate"], 1.0)
        self.assertEqual(group["room_clear_frames_median"], 120.0)
        self.assertEqual(group["death_rate"], 1.0)
        self.assertEqual(group["recovery_frames_avg"], 18.0)
        self.assertEqual(group["shadow_agreement_rate"], 0.0)
        self.assertEqual(group["shadow_disagreements"], {"retreat_and_fire -> strafe_left": 1})
        self.assertEqual(group["shadow_latency_difference_ms_avg"], 9.0)
        self.assertEqual(group["calibration"]["confidence"]["0.8-0.9"]["success_rate"], 1.0)

    def test_timeout_fallback_safety_stale_and_busy_shadow(self):
        stats = IncrementalStatistics()
        stats.ingest_trace(decision(
            trace_id="trace-2",
            timeout=True,
            fallback_reason="provider_timeout",
            source="safety",
            stale_result=True,
            shadow_result={"status": "shadow_skipped_busy"},
        ))
        group = stats.snapshot()["groups"][0]
        self.assertEqual(group["timeouts"], 1)
        self.assertEqual(group["fallbacks"], 1)
        self.assertEqual(group["safety_overrides"], 1)
        self.assertEqual(group["stale_results"], 1)
        self.assertEqual(group["shadow_skipped_busy"], 1)

    def test_separate_shadow_record_is_linked_without_becoming_a_decision(self):
        stats = IncrementalStatistics()
        stats.ingest_trace(decision(schema_version="decision-v3", shadow_result={}))
        stats.ingest_trace({
            "schema_version": "decision-v3",
            "type": "shadow",
            "parent_trace_id": "trace-1",
            "provider": "jev",
            "model": "jev-latest",
            "selected_action": "retreat_and_fire",
            "executed_action": "retreat_and_fire",
            "client_latency_ms": 28,
        })
        summary = stats.snapshot()
        self.assertEqual(summary["group_count"], 1)
        group = summary["groups"][0]
        self.assertEqual(group["decisions"], 1)
        self.assertEqual(group["shadow_calls"], 1)
        self.assertEqual(group["shadow_agreement_rate"], 1.0)

    def test_old_schema_is_excluded_from_comparison(self):
        records = [
            {"schema_version": "jev-policy-v2", "provider": "jev"},
            decision(),
            decision(trace_id="trace-3", provider="jev", model="jev-latest"),
        ]
        filtered = filter_comparison_records(records, seed=1234, provider="laya")
        self.assertEqual(len(filtered), 1)
        stats = IncrementalStatistics()
        for record in records:
            stats.ingest_trace(record)
        self.assertEqual(stats.snapshot()["group_count"], 2)
        self.assertEqual(stats.snapshot()["excluded_legacy_records"], 1)

    def test_incremental_refresh_reads_only_appended_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            trace_path = Path(directory) / "decision_traces.jsonl"
            event_path = Path(directory) / "experiment_runs.jsonl"
            trace_recorder = DecisionTraceRecorder(trace_path)
            event_recorder = ExperimentEventRecorder(event_path)
            trace_recorder.record(decision())
            event_recorder.record(event("run_started"))
            stats = IncrementalStatistics(trace_path, event_path)
            self.assertEqual(stats.refresh(), 2)
            self.assertEqual(stats.refresh(), 0)
            event_recorder.record(event("damage", event_id="damage-new", damage_kind="projectile"))
            self.assertEqual(stats.refresh(), 1)
            group = stats.snapshot()["groups"][0]
            self.assertEqual(group["decisions"], 1)
            self.assertEqual(group["damage_events"], 1)

    def test_one_shot_replay_reads_both_files_and_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            trace_path = Path(directory) / "decision_traces.jsonl"
            event_path = Path(directory) / "experiment_runs.jsonl"
            DecisionTraceRecorder(trace_path).record(decision())
            ExperimentEventRecorder(event_path).record(event("run_started"))
            summary = evaluate_provider_statistics(trace_path, event_path, seed=1234, provider="laya")
            self.assertEqual(summary["group_count"], 1)
            self.assertEqual(summary["groups"][0]["runs"], 1)

if __name__ == "__main__":
    unittest.main()
