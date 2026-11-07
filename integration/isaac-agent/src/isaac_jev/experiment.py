from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 3
PROVIDERS = {"jev", "bocha", "systemone", "local"}
_SECRET_KEYS = {"apikey", "authorization", "typesafeapikey", "token", "accesstoken"}


def redact_secrets(value: Any) -> Any:
    """Return a JSON-safe copy without credential-shaped fields."""
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized in _SECRET_KEYS or normalized.endswith("apikey"):
                continue
            safe[str(key)] = redact_secrets(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    return value


class ExperimentEventRecorder:
    """Append structured run/room/damage events without retaining secrets."""

    def __init__(self, path: str | Path = "logs/experiment_runs.jsonl") -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def record(self, event: str | dict[str, Any], **fields: Any) -> dict[str, Any]:
        if isinstance(event, str):
            record: dict[str, Any] = {"type": event, **fields}
        else:
            record = {**event, **fields}
        record.setdefault("schema_version", SCHEMA_VERSION)
        record.setdefault("event_id", uuid.uuid4().hex[:16])
        record.setdefault("recorded_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        safe = redact_secrets(record)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(safe, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            pass
        return safe


def read_experiment_events(path: str | Path = "logs/experiment_runs.jsonl") -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    records.append(value)
    except OSError:
        pass
    return records


def is_comparison_record(record: dict[str, Any]) -> bool:
    """Only numeric schema v3+ records are valid for provider comparisons."""
    value = record.get("schema_version")
    if isinstance(value, bool):
        return False
    try:
        return float(str(value).strip()) >= SCHEMA_VERSION
    except (TypeError, ValueError):
        match = re.search(r"(?:^|[-_])v?(\d+)$", str(value).strip().lower())
        return bool(match and int(match.group(1)) >= SCHEMA_VERSION)


def comparison_identity(record: dict[str, Any]) -> tuple[str, str, str]:
    provider_result = record.get("provider_result") if isinstance(record.get("provider_result"), dict) else {}
    context = record.get("context") if isinstance(record.get("context"), dict) else {}
    seed = _first(record, "start_seed", "seed", "run_seed")
    if seed is None:
        seed = _first(context, "start_seed", "seed")
    provider = _first(record, "provider", "active_provider", "decision_provider")
    if provider is None:
        provider = _first(provider_result, "provider")
    if provider is None and str(record.get("source", "")).lower() in PROVIDERS:
        provider = record.get("source")
    model = _first(record, "model", "provider_model")
    if model is None:
        model = _first(provider_result, "model")
    return (_label(seed), _label(provider), _label(model))


def filter_comparison_records(
    records: Iterable[dict[str, Any]],
    seed: str | int | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    expected_seed = None if seed is None else str(seed)
    expected_provider = None if provider is None else provider.lower()
    return [
        record
        for record in records
        if is_comparison_record(record)
        and (expected_seed is None or comparison_identity(record)[0] == expected_seed)
        and (expected_provider is None or comparison_identity(record)[1].lower() == expected_provider)
        and (model is None or comparison_identity(record)[2] == model)
    ]


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


def _label(value: Any) -> str:
    return "unknown" if value is None or value == "" else str(value)


def _number(record: dict[str, Any], *keys: str) -> float | None:
    value = _first(record, *keys)
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _truthy(record: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = record.get(key)
        if value is True or (isinstance(value, (int, float)) and value != 0):
            return True
        if isinstance(value, str) and value.strip().lower() in {"true", "yes", "1", "timeout", "stale", "expired"}:
            return True
    return False


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return round(ordered[index], 2)


def _bucket(value: float | None) -> str | None:
    if value is None:
        return None
    bounded = min(1.0, max(0.0, value))
    low = min(0.9, math.floor(bounded * 10.0) / 10.0)
    high = 1.0 if low >= 0.9 else low + 0.1
    return f"{low:.1f}-{high:.1f}"


def _new_group(seed: str, provider: str, model: str) -> dict[str, Any]:
    return {
        "seed": seed,
        "provider": provider,
        "model": model,
        "decision_count": 0,
        "remote_calls": 0,
        "timeouts": 0,
        "fallbacks": 0,
        "safety_overrides": 0,
        "stale_results": 0,
        "selected_actions": Counter(),
        "executed_actions": Counter(),
        "client_latencies": [],
        "server_latencies": [],
        "run_ids": set(),
        "death_run_ids": set(),
        "death_events": set(),
        "combat_room_ids": set(),
        "cleared_room_ids": set(),
        "room_clear_frames": [],
        "damage_ids": set(),
        "damage_events": 0,
        "projectile_hits": 0,
        "contact_hits": 0,
        "stall_ids": set(),
        "recovery_ids": set(),
        "recovery_frames": [],
        "calibration": {"confidence": {}, "top_probability": {}, "margin": {}},
        "shadow_calls": 0,
        "shadow_agreements": 0,
        "shadow_skipped_busy": 0,
        "shadow_disagreements": Counter(),
        "shadow_latency_differences": [],
    }


class IncrementalStatistics:
    """Thread-safe in-memory provider statistics with incremental JSONL tailing."""

    def __init__(
        self,
        trace_path: str | Path = "logs/decision_traces.jsonl",
        experiment_path: str | Path = "logs/experiment_runs.jsonl",
    ) -> None:
        self.trace_path = Path(trace_path)
        self.experiment_path = Path(experiment_path)
        self._lock = threading.RLock()
        self._groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._trace_context: dict[str, dict[str, Any]] = {}
        self._pending_outcomes: dict[str, list[dict[str, Any]]] = {}
        self._pending_shadows: dict[str, list[dict[str, Any]]] = {}
        self._offsets: dict[Path, int] = {self.trace_path: 0, self.experiment_path: 0}
        self._remainders: dict[Path, bytes] = {self.trace_path: b"", self.experiment_path: b""}
        self.excluded_legacy_records = 0
        self.invalid_records = 0

    def reset(self) -> None:
        with self._lock:
            self._groups.clear()
            self._trace_context.clear()
            self._pending_outcomes.clear()
            self._pending_shadows.clear()
            self._offsets = {self.trace_path: 0, self.experiment_path: 0}
            self._remainders = {self.trace_path: b"", self.experiment_path: b""}
            self.excluded_legacy_records = 0
            self.invalid_records = 0

    def refresh(self) -> int:
        """Ingest only bytes appended since the prior call."""
        with self._lock:
            for path in (self.trace_path, self.experiment_path):
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size < self._offsets[path]:
                    self.reset()
                    break
            ingested = self._ingest_appended(self.trace_path, True)
            ingested += self._ingest_appended(self.experiment_path, False)
            return ingested

    def _ingest_appended(self, path: Path, trace_source: bool) -> int:
        try:
            with path.open("rb") as handle:
                handle.seek(self._offsets[path])
                chunk = handle.read()
                self._offsets[path] = handle.tell()
        except OSError:
            return 0
        if not chunk:
            return 0
        data = self._remainders[path] + chunk
        lines = data.split(b"\n")
        self._remainders[path] = lines.pop()
        count = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, TypeError, ValueError):
                self.invalid_records += 1
                continue
            if not isinstance(record, dict):
                self.invalid_records += 1
                continue
            if trace_source:
                self.ingest_trace(record)
            else:
                self.ingest_event(record)
            count += 1
        return count

    def _group(self, key: tuple[str, str, str]) -> dict[str, Any]:
        group = self._groups.get(key)
        if group is None:
            group = _new_group(*key)
            self._groups[key] = group
        return group

    def ingest_trace(self, record: dict[str, Any]) -> bool:
        with self._lock:
            if not is_comparison_record(record):
                self.excluded_legacy_records += 1
                return False
            if record.get("type") == "outcome":
                trace_id = str(record.get("trace_id", ""))
                if not trace_id:
                    return False
                context = self._trace_context.get(trace_id)
                if context is None:
                    self._pending_outcomes.setdefault(trace_id, []).append(record)
                else:
                    self._apply_outcome(context, record)
                return True
            if record.get("type") == "shadow":
                parent_trace_id = str(record.get("parent_trace_id", ""))
                context = self._trace_context.get(parent_trace_id)
                if context is None:
                    self._pending_shadows.setdefault(parent_trace_id, []).append(record)
                else:
                    self._apply_shadow_record(context, record)
                return True

            key = comparison_identity(record)
            group = self._group(key)
            group["decision_count"] += 1
            provider = key[1].lower()
            if _truthy(record, "remote_call") or provider in {"jev", "bocha", "systemone"}:
                group["remote_calls"] += 1
            status = str(record.get("status", "")).lower()
            error = str(record.get("error", "")).lower()
            if _truthy(record, "timeout", "timed_out") or "timeout" in status or "timeout" in error:
                group["timeouts"] += 1
            if _truthy(record, "fallback", "used_fallback") or record.get("fallback_reason"):
                group["fallbacks"] += 1
            execution = record.get("execution") if isinstance(record.get("execution"), dict) else {}
            source = str(_first(execution, "source") or record.get("source", "")).lower()
            if source == "safety" or _truthy(record, "safety_override") or record.get("override_reason"):
                group["safety_overrides"] += 1
            if _truthy(record, "stale", "expired", "stale_result", "expired_result") or "stale" in status or "expired" in status:
                group["stale_results"] += 1

            provider_result = record.get("provider_result") if isinstance(record.get("provider_result"), dict) else {}
            output = record.get("output") if isinstance(record.get("output"), dict) else {}
            selected = _first(record, "model_choice", "selected_action", "choice")
            selected = selected or _first(provider_result, "choice", "action") or _first(output, "choice", "action")
            executed = _first(record, "executed_action", "final_action")
            executed = executed or _first(execution, "action", "action_id") or record.get("action") or selected
            if selected:
                group["selected_actions"][str(selected)] += 1
            if executed:
                group["executed_actions"][str(executed)] += 1

            client_latency = _number(record, "client_latency_ms", "latency_ms", "remote_latency_ms")
            if client_latency is not None:
                group["client_latencies"].append(client_latency)
            server_latency = _number(record, "server_latency_ms")
            if server_latency is None:
                server_latency = _number(provider_result, "server_latency_ms", "latency_ms")
            if server_latency is not None:
                group["server_latencies"].append(server_latency)

            confidence = _number(record, "raw_confidence", "confidence")
            if confidence is None:
                confidence = _number(provider_result, "raw_confidence", "confidence")
            top_probability = _number(record, "top_probability", "top1", "top1_probability")
            if top_probability is None:
                top_probability = _number(provider_result, "top_probability", "top1", "top1_probability")
            margin = _number(record, "margin")
            if margin is None:
                margin = _number(provider_result, "margin")
            trace_id = str(record.get("trace_id", ""))
            context = {
                "key": key,
                "trace_id": trace_id,
                "executed_action": str(executed) if executed else None,
                "calibration_values": {
                    "confidence": confidence,
                    "top_probability": top_probability,
                    "margin": margin,
                },
                "calibration_outcome": None,
                "calibration_horizon": -1,
                "client_latency": client_latency,
            }
            if trace_id:
                self._trace_context[trace_id] = context
            self._apply_shadow(group, record, context, client_latency)

            if isinstance(record.get("outcome"), dict):
                self._apply_outcome(context, {"outcome": record["outcome"], "horizon_frames": 0})
            outcomes = record.get("outcomes")
            if isinstance(outcomes, dict):
                for horizon, outcome in outcomes.items():
                    if isinstance(outcome, dict):
                        self._apply_outcome(context, {"outcome": outcome, "horizon_frames": horizon})
            for pending in self._pending_outcomes.pop(trace_id, []):
                self._apply_outcome(context, pending)
            for pending in self._pending_shadows.pop(trace_id, []):
                self._apply_shadow_record(context, pending)
            return True

    def _apply_shadow_record(self, context: dict[str, Any], record: dict[str, Any]) -> None:
        group = self._group(context["key"])
        shadow = {
            "choice": _first(record, "selected_action", "choice", "action"),
            "client_latency_ms": _first(record, "client_latency_ms", "latency_ms"),
            "status": record.get("status"),
        }
        self._apply_shadow(group, {"shadow_result": shadow}, context, context.get("client_latency"))

    def _apply_shadow(
        self,
        group: dict[str, Any],
        record: dict[str, Any],
        context: dict[str, Any],
        active_latency: float | None,
    ) -> None:
        shadow = record.get("shadow_result")
        if not isinstance(shadow, dict):
            shadow = record.get("shadow") if isinstance(record.get("shadow"), dict) else {}
        status = str(shadow.get("status", record.get("shadow_status", ""))).lower()
        if _truthy(record, "shadow_skipped_busy") or _truthy(shadow, "skipped_busy") or status == "shadow_skipped_busy":
            group["shadow_skipped_busy"] += 1
            return
        choice = _first(shadow, "choice", "action", "selected_action")
        if choice is None:
            choice = record.get("shadow_choice")
        if choice is None:
            return
        group["shadow_calls"] += 1
        executed = context.get("executed_action")
        if executed == str(choice):
            group["shadow_agreements"] += 1
        else:
            group["shadow_disagreements"][f"{executed or 'unknown'} -> {choice}"] += 1
        shadow_latency = _number(shadow, "client_latency_ms", "latency_ms")
        if shadow_latency is None:
            shadow_latency = _number(record, "shadow_latency_ms")
        if shadow_latency is not None and active_latency is not None:
            group["shadow_latency_differences"].append(shadow_latency - active_latency)

    def _apply_outcome(self, context: dict[str, Any], record: dict[str, Any]) -> None:
        outcome = record.get("outcome") if isinstance(record.get("outcome"), dict) else record
        success = _outcome_success(outcome)
        if success is None:
            return
        try:
            horizon = int(record.get("horizon_frames", 0))
        except (TypeError, ValueError):
            horizon = 0
        if horizon < int(context.get("calibration_horizon", -1)):
            return
        group = self._group(context["key"])
        previous = context.get("calibration_outcome")
        if previous is not None:
            for metric, value in context["calibration_values"].items():
                bucket = _bucket(value)
                if bucket:
                    counts = group["calibration"][metric][bucket]
                    counts["samples"] -= 1
                    counts["successes"] -= int(previous)
        for metric, value in context["calibration_values"].items():
            bucket = _bucket(value)
            if bucket:
                counts = group["calibration"][metric].setdefault(bucket, {"samples": 0, "successes": 0})
                counts["samples"] += 1
                counts["successes"] += int(success)
        context["calibration_outcome"] = success
        context["calibration_horizon"] = horizon

    def ingest_event(self, record: dict[str, Any]) -> bool:
        with self._lock:
            if not is_comparison_record(record):
                self.excluded_legacy_records += 1
                return False
            key = comparison_identity(record)
            group = self._group(key)
            event_type = str(record.get("type", record.get("event", ""))).lower()
            run_id = _label(record.get("run_id"))
            room_id = _label(_first(record, "room_visit_id", "room_id"))
            event_id = _label(_first(record, "event_id", "damage_event_id"))
            qualified_room = f"{run_id}:{room_id}"

            if event_type in {"run_started", "run_start", "run_ended", "run_end", "death", "player_death"} and run_id != "unknown":
                group["run_ids"].add(run_id)
            if event_type in {"death", "player_death"}:
                if run_id != "unknown":
                    group["death_run_ids"].add(run_id)
                group["death_events"].add(event_id)

            combat = _truthy(record, "combat", "is_combat") or (_number(record, "enemy_count", "hostile_enemy_count") or 0) > 0
            if event_type in {"room_started", "room_entered", "room_visit_started"} and combat:
                group["combat_room_ids"].add(qualified_room)
            if event_type in {"room_completed", "room_cleared", "room_clear"}:
                if combat or record.get("combat") is not False:
                    group["combat_room_ids"].add(qualified_room)
                    group["cleared_room_ids"].add(qualified_room)
                clear_frames = _number(record, "clear_frames", "room_clear_frames", "duration_frames")
                if clear_frames is None:
                    entered = _number(record, "entered_frame", "room_entered_frame")
                    cleared = _number(record, "cleared_frame", "room_cleared_frame", "frame")
                    if entered is not None and cleared is not None:
                        clear_frames = max(0.0, cleared - entered)
                if clear_frames is not None:
                    group["room_clear_frames"].append(clear_frames)

            if event_type in {"damage", "damage_taken", "player_damage"} and (event_id == "unknown" or event_id not in group["damage_ids"]):
                if event_id == "unknown":
                    event_id = f"anonymous:{group['damage_events']}"
                group["damage_ids"].add(event_id)
                group["damage_events"] += 1
                category = str(_first(record, "damage_kind", "cause", "source_kind", "source_type") or "").lower()
                if _truthy(record, "projectile_hit") or any(word in category for word in ("projectile", "tear", "bullet")):
                    group["projectile_hits"] += 1
                elif _truthy(record, "contact_hit") or any(word in category for word in ("contact", "enemy", "npc")):
                    group["contact_hits"] += 1

            if event_type in {"stall", "stall_started", "stuck"}:
                group["stall_ids"].add(event_id)
            if event_type in {"stall_recovered", "recovery", "recovered"}:
                group["recovery_ids"].add(event_id)
                duration = _number(record, "recovery_frames", "duration_frames", "stall_frames")
                if duration is not None:
                    group["recovery_frames"].append(duration)
            if event_type in {"run_ended", "run_end"} and run_id != "unknown":
                group["run_ids"].add(run_id)
            return True

    def snapshot(
        self,
        seed: str | int | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            expected_seed = None if seed is None else str(seed)
            expected_provider = None if provider is None else provider.lower()
            groups = []
            for key in sorted(self._groups):
                if expected_seed is not None and key[0] != expected_seed:
                    continue
                if expected_provider is not None and key[1].lower() != expected_provider:
                    continue
                if model is not None and key[2] != model:
                    continue
                groups.append(_summarize_group(self._groups[key]))
            return {
                "schema_version": SCHEMA_VERSION,
                "filters": {"seed": expected_seed, "provider": provider, "model": model},
                "group_count": len(groups),
                "groups": groups,
                "excluded_legacy_records": self.excluded_legacy_records,
                "invalid_records": self.invalid_records,
            }


def _outcome_success(outcome: dict[str, Any]) -> bool | None:
    for key in ("success", "actual_success", "successful"):
        if isinstance(outcome.get(key), bool):
            return bool(outcome[key])
    if _truthy(outcome, "room_clear", "target_disappeared", "room_changed"):
        return True
    if _truthy(outcome, "damaged", "navigation_stuck", "combat_exposed", "projectile_hit"):
        return False
    return None


def _calibration_summary(metrics: dict[str, dict[str, dict[str, int]]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for metric, buckets in metrics.items():
        result[metric] = {
            bucket: {
                "samples": counts["samples"],
                "successes": counts["successes"],
                "success_rate": round(counts["successes"] / max(1, counts["samples"]), 4),
            }
            for bucket, counts in sorted(buckets.items())
            if counts["samples"] > 0
        }
    return result


def _summarize_group(group: dict[str, Any]) -> dict[str, Any]:
    decisions = group["decision_count"]
    combat_rooms = len(group["combat_room_ids"])
    runs = len(group["run_ids"])
    deaths = len(group["death_run_ids"]) if group["death_run_ids"] else len(group["death_events"])
    damage = group["damage_events"]
    stalls = len(group["stall_ids"])
    recovered = len(group["recovery_ids"])
    shadow_calls = group["shadow_calls"]
    return {
        "seed": group["seed"],
        "provider": group["provider"],
        "model": group["model"],
        "decisions": decisions,
        "remote_calls": group["remote_calls"],
        "timeouts": group["timeouts"],
        "timeout_rate": round(group["timeouts"] / max(1, group["remote_calls"]), 4),
        "fallbacks": group["fallbacks"],
        "fallback_rate": round(group["fallbacks"] / max(1, decisions), 4),
        "safety_overrides": group["safety_overrides"],
        "safety_override_rate": round(group["safety_overrides"] / max(1, decisions), 4),
        "stale_results": group["stale_results"],
        "selected_actions": dict(group["selected_actions"]),
        "executed_actions": dict(group["executed_actions"]),
        "combat_rooms": combat_rooms,
        "cleared_rooms": len(group["cleared_room_ids"]),
        "clear_rate": round(len(group["cleared_room_ids"]) / max(1, combat_rooms), 4),
        "room_clear_frames_median": _percentile(group["room_clear_frames"], 0.5),
        "room_clear_frames_p95": _percentile(group["room_clear_frames"], 0.95),
        "runs": runs,
        "deaths": deaths,
        "death_rate": round(deaths / max(1, runs), 4),
        "damage_events": damage,
        "projectile_hits": group["projectile_hits"],
        "projectile_hit_rate": round(group["projectile_hits"] / max(1, damage), 4),
        "contact_hits": group["contact_hits"],
        "contact_hit_rate": round(group["contact_hits"] / max(1, damage), 4),
        "stalls": stalls,
        "stall_rate": round(stalls / max(1, combat_rooms), 4),
        "recoveries": recovered,
        "recovery_rate": round(recovered / max(1, stalls), 4),
        "recovery_frames_avg": round(sum(group["recovery_frames"]) / len(group["recovery_frames"]), 2) if group["recovery_frames"] else None,
        "recovery_frames_p95": _percentile(group["recovery_frames"], 0.95),
        "client_latency_ms_avg": round(sum(group["client_latencies"]) / len(group["client_latencies"]), 2) if group["client_latencies"] else None,
        "client_latency_ms_p95": _percentile(group["client_latencies"], 0.95),
        "server_latency_ms_avg": round(sum(group["server_latencies"]) / len(group["server_latencies"]), 2) if group["server_latencies"] else None,
        "server_latency_ms_p95": _percentile(group["server_latencies"], 0.95),
        "calibration": _calibration_summary(group["calibration"]),
        "shadow_calls": shadow_calls,
        "shadow_agreements": group["shadow_agreements"],
        "shadow_agreement_rate": round(group["shadow_agreements"] / max(1, shadow_calls), 4),
        "shadow_skipped_busy": group["shadow_skipped_busy"],
        "shadow_disagreements": dict(group["shadow_disagreements"]),
        "shadow_latency_difference_ms_avg": round(sum(group["shadow_latency_differences"]) / len(group["shadow_latency_differences"]), 2) if group["shadow_latency_differences"] else None,
        "shadow_latency_difference_ms_p95": _percentile(group["shadow_latency_differences"], 0.95),
    }
