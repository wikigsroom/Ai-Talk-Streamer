from __future__ import annotations

import argparse
import json
import math
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .experiment import SCHEMA_VERSION, IncrementalStatistics, filter_comparison_records, read_experiment_events, redact_secrets


class DecisionTraceRecorder:
    """Append-only, API-key-free decision traces for offline evaluation."""

    def __init__(self, path: str | Path = "logs/decision_traces.jsonl") -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def record(self, trace: dict[str, Any]) -> str:
        trace_id = str(trace.get("trace_id") or uuid.uuid4().hex[:16])
        safe = redact_secrets(trace)
        safe["trace_id"] = trace_id
        safe.setdefault("recorded_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(safe, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            pass
        return trace_id

    def record_outcome(self, trace_id: str, horizon_frames: int, outcome: dict[str, Any], schema_version: int = SCHEMA_VERSION) -> None:
        self.record({"schema_version": schema_version, "type": "outcome", "trace_id": trace_id, "horizon_frames": int(horizon_frames), "outcome": outcome})


def read_traces(path: str | Path = "logs/decision_traces.jsonl") -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if not isinstance(value, dict) or not value.get("trace_id"):
                    continue
                if value.get("type") == "outcome":
                    base = by_id.get(str(value["trace_id"]))
                    if base is not None:
                        base.setdefault("outcomes", {})[str(value.get("horizon_frames", 0))] = value.get("outcome", {})
                    continue
                by_id[str(value["trace_id"])] = value
                traces.append(value)
    except OSError:
        pass
    return traces


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * percentile))))
    return round(values[index], 2)


def evaluate_traces(traces: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(traces)
    candidate_sets = [item.get("candidate_set", {}) for item in values if isinstance(item.get("candidate_set"), dict)]
    combat_sets = [item for item in candidate_sets if item.get("policy") == "combat"]
    raw_counts = [len(item.get("raw_candidates", [])) for item in candidate_sets]
    admissible_counts = [len(item.get("admissible_candidates", [])) for item in combat_sets]
    def number(item: dict[str, Any], key: str) -> float | None:
        value = item.get(key)
        try:
            return float(value) if isinstance(value, (int, float, str)) and str(value).strip() else None
        except (TypeError, ValueError):
            return None

    latencies = [value for item in values if (value := number(item, "latency_ms")) is not None]
    remote_latencies = [value for item in values if (value := number(item, "remote_latency_ms")) is not None]
    request_bytes = [value for item in values if (value := number(item, "request_bytes")) is not None]
    state_bytes = [value for item in values if (value := number(item, "state_bytes")) is not None]
    estimated_tokens = [value for item in values if (value := number(item, "estimated_input_tokens")) is not None]
    single_reasons = Counter(str(item.get("single_legal_reason")) for item in combat_sets if len(item.get("admissible_candidates", [])) == 1)
    rejected = sum(len(item.get("rejected_candidates", [])) for item in candidate_sets)
    selected = [item.get("output", {}) for item in values if isinstance(item.get("output"), dict)]
    fallback_count = sum(1 for item in values if str(item.get("status", "")).startswith("fallback") or item.get("fallback_reason"))
    outcomes = [item.get("outcome", {}) for item in values if isinstance(item.get("outcome"), dict)]
    for item in values:
        if isinstance(item.get("outcomes"), dict):
            outcomes.extend(value for value in item["outcomes"].values() if isinstance(value, dict))
    injured = sum(1 for item in outcomes if item.get("hp_delta", 0) < 0 or item.get("damaged"))
    remote_calls = sum(bool(item.get("remote_call")) for item in values)
    local_calls = sum(not bool(item.get("remote_call")) for item in values)
    policy_counts = Counter(str(item.get("policy", "unknown")) for item in values)
    navigation_outcomes = [item for item in values if str(item.get("policy", "")) == "navigation"]
    navigation_stuck = sum(bool(item.get("outcome", {}).get("navigation_stuck")) for item in navigation_outcomes if isinstance(item.get("outcome"), dict))
    combat_outcomes = [item for item in values if str(item.get("policy", "")) == "combat"]
    combat_exposed = sum(bool(item.get("outcome", {}).get("combat_exposed")) for item in combat_outcomes if isinstance(item.get("outcome"), dict))
    projectile_hits = sum(bool(item.get("outcome", {}).get("projectile_hit")) for item in values if isinstance(item.get("outcome"), dict))
    return {
        "traces": len(values),
        "candidate_count_compliance": round(sum(2 <= count <= 5 for count in admissible_counts) / len(admissible_counts), 4) if admissible_counts else 0.0,
        "single_legal_ratio": round(sum(count == 1 for count in admissible_counts) / len(admissible_counts), 4) if admissible_counts else 0.0,
        "single_legal_reasons": dict(single_reasons),
        "safety_filter_rejection_rate": round(rejected / max(1, sum(raw_counts)), 4),
        "fallback_rate": round(fallback_count / max(1, len(values)), 4),
        "injury_rate": round(injured / max(1, len(outcomes)), 4),
        "decision_latency_ms_avg": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "decision_latency_ms_p95": _percentile(latencies, 0.95),
        "remote_call_count": remote_calls,
        "local_decision_count": local_calls,
        "remote_call_rate": round(remote_calls / max(1, len(values)), 4),
        "policies": dict(policy_counts),
        "request_bytes_avg": round(sum(request_bytes) / len(request_bytes), 2) if request_bytes else None,
        "request_bytes_p95": _percentile(request_bytes, 0.95),
        "state_bytes_avg": round(sum(state_bytes) / len(state_bytes), 2) if state_bytes else None,
        "estimated_input_tokens_avg": round(sum(estimated_tokens) / len(estimated_tokens), 2) if estimated_tokens else None,
        "remote_latency_ms_avg": round(sum(remote_latencies) / len(remote_latencies), 2) if remote_latencies else None,
        "remote_latency_ms_p95": _percentile(remote_latencies, 0.95),
        "navigation_stuck_rate": round(navigation_stuck / max(1, len(navigation_outcomes)), 4),
        "combat_exposure_rate": round(combat_exposed / max(1, len(combat_outcomes)), 4),
        "projectile_hit_rate": round(projectile_hits / max(1, len(values)), 4),
        "selected_actions": dict(Counter(str(item.get("action", "unknown")) for item in selected)),
    }


def evaluate_provider_statistics(
    trace_path: str | Path = "logs/decision_traces.jsonl",
    experiment_path: str | Path = "logs/experiment_runs.jsonl",
    seed: str | int | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Build the v3 provider comparison summary from both local JSONL files."""
    aggregator = IncrementalStatistics(trace_path, experiment_path)
    # Direct ingestion is intentional for the CLI: the incremental API is used
    # by the dashboard, while a one-shot replay should see a complete snapshot.
    for trace in read_traces(trace_path):
        aggregator.ingest_trace(trace)
    for event in read_experiment_events(experiment_path):
        aggregator.ingest_event(event)
    return aggregator.snapshot(seed=seed, provider=provider, model=model)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Isaac Jev decision traces")
    parser.add_argument("--path", default="logs/decision_traces.jsonl")
    parser.add_argument("--experiment-path", default="logs/experiment_runs.jsonl")
    parser.add_argument("--seed", default=None, help="Only include this run seed in provider statistics")
    parser.add_argument("--provider", choices=("jev", "bocha", "systemone", "local"), default=None)
    parser.add_argument("--model", default=None, help="Only include this provider model")
    args = parser.parse_args()
    traces = read_traces(args.path)
    if args.seed is not None or args.provider is not None or args.model is not None:
        traces = filter_comparison_records(traces, seed=args.seed, provider=args.provider, model=args.model)
    summary = evaluate_traces(traces)
    summary["provider_statistics"] = evaluate_provider_statistics(
        args.path,
        args.experiment_path,
        seed=args.seed,
        provider=args.provider,
        model=args.model,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
