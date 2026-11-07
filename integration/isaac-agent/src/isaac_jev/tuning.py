from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class PolicyProfile:
    """Bounded local policy knobs; this does not modify the Jev model."""

    confidence_threshold: float = 0.70
    jev_timeout_seconds: float = 0.75
    pickup_stuck_frames: int = 90
    enemy_safe_distance: float = 95.0
    projectile_evade_radius: float = 120.0
    repeat_action_threshold: int = 18
    repeat_penalty_frames: int = 18
    movement_stall_threshold: int = 6
    max_action_age_frames: int = 45

    def bounded(self) -> "PolicyProfile":
        return replace(
            self,
            confidence_threshold=min(0.95, max(0.50, float(self.confidence_threshold))),
            jev_timeout_seconds=min(1.50, max(0.25, float(self.jev_timeout_seconds))),
            pickup_stuck_frames=min(240, max(30, int(self.pickup_stuck_frames))),
            enemy_safe_distance=min(180.0, max(55.0, float(self.enemy_safe_distance))),
            projectile_evade_radius=min(220.0, max(80.0, float(self.projectile_evade_radius))),
            repeat_action_threshold=min(90, max(6, int(self.repeat_action_threshold))),
            repeat_penalty_frames=min(60, max(6, int(self.repeat_penalty_frames))),
            movement_stall_threshold=min(30, max(2, int(self.movement_stall_threshold))),
            max_action_age_frames=min(120, max(15, int(self.max_action_age_frames))),
        )

    def to_dict(self) -> dict[str, Any]:
        value = self.bounded()
        return {
            "confidence_threshold": round(value.confidence_threshold, 3),
            "jev_timeout_seconds": round(value.jev_timeout_seconds, 3),
            "pickup_stuck_frames": value.pickup_stuck_frames,
            "enemy_safe_distance": round(value.enemy_safe_distance, 1),
            "projectile_evade_radius": round(value.projectile_evade_radius, 1),
            "repeat_action_threshold": value.repeat_action_threshold,
            "repeat_penalty_frames": value.repeat_penalty_frames,
            "movement_stall_threshold": value.movement_stall_threshold,
            "max_action_age_frames": value.max_action_age_frames,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "PolicyProfile":
        if not isinstance(value, dict):
            return cls()
        defaults = cls()
        try:
            return cls(
                confidence_threshold=float(value.get("confidence_threshold", defaults.confidence_threshold)),
                jev_timeout_seconds=float(value.get("jev_timeout_seconds", defaults.jev_timeout_seconds)),
                pickup_stuck_frames=int(value.get("pickup_stuck_frames", defaults.pickup_stuck_frames)),
                enemy_safe_distance=float(value.get("enemy_safe_distance", defaults.enemy_safe_distance)),
                projectile_evade_radius=float(value.get("projectile_evade_radius", defaults.projectile_evade_radius)),
                repeat_action_threshold=int(value.get("repeat_action_threshold", defaults.repeat_action_threshold)),
                repeat_penalty_frames=int(value.get("repeat_penalty_frames", defaults.repeat_penalty_frames)),
                movement_stall_threshold=int(value.get("movement_stall_threshold", defaults.movement_stall_threshold)),
                max_action_age_frames=int(value.get("max_action_age_frames", defaults.max_action_age_frames)),
            ).bounded()
        except (TypeError, ValueError, OverflowError):
            return defaults


def profile_path(log_dir: str | Path = "logs") -> Path:
    path = Path(log_dir)
    return path if path.suffix.lower() == ".json" else path / "policy_profile.json"


def load_profile(log_dir: str | Path = "logs") -> PolicyProfile:
    path = profile_path(log_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return PolicyProfile()
    return PolicyProfile.from_dict(data.get("profile", data) if isinstance(data, dict) else data)


def analyze_episodes(log_path: str | Path = "logs/episodes.jsonl") -> list[dict[str, Any]]:
    path = Path(log_path)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(event, dict) and event.get("type") == "death_episode":
                    events.append(event)
    except OSError:
        return events
    return events


def _counts(events: Iterable[dict[str, Any]]) -> Counter[str]:
    return Counter(str(event.get("cause", "unknown")) for event in events)


def pending_events(events: Iterable[dict[str, Any]], applied_counts: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return only events not represented by the last written profile."""
    applied = Counter()
    for cause, value in (applied_counts or {}).items():
        try:
            applied[str(cause)] = max(0, int(value))
        except (TypeError, ValueError):
            continue
    seen: Counter[str] = Counter()
    pending: list[dict[str, Any]] = []
    for event in events:
        cause = str(event.get("cause", "unknown"))
        if seen[cause] >= applied[cause]:
            pending.append(event)
        seen[cause] += 1
    return pending


def applied_death_counts(log_dir: str | Path = "logs") -> dict[str, int]:
    try:
        document = json.loads(profile_path(log_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    evidence = document.get("evidence", {}) if isinstance(document, dict) else {}
    counts = evidence.get("death_counts", {}) if isinstance(evidence, dict) else {}
    return {str(key): int(value) for key, value in counts.items() if isinstance(value, (int, float)) and value >= 0}


def suggest_profile(events: Iterable[dict[str, Any]], current_profile: PolicyProfile | None = None) -> PolicyProfile:
    """Apply conservative changes only when a cause has at least two examples."""
    current = (current_profile or PolicyProfile()).bounded()
    counts = _counts(events)
    updates: dict[str, Any] = {}
    if counts["projectile_hit"] >= 2:
        updates["projectile_evade_radius"] = current.projectile_evade_radius + 10
        updates["confidence_threshold"] = current.confidence_threshold + 0.03
    if counts["enemy_contact"] + counts["combat_exposure"] >= 2:
        updates["enemy_safe_distance"] = current.enemy_safe_distance + 10
        updates["confidence_threshold"] = max(updates.get("confidence_threshold", current.confidence_threshold), current.confidence_threshold + 0.02)
    if counts["navigation_stuck"] >= 2:
        updates["movement_stall_threshold"] = current.movement_stall_threshold - 1
    if counts["pickup_stall"] >= 2:
        updates["pickup_stuck_frames"] = current.pickup_stuck_frames - 15
    if counts["decision_latency"] >= 2:
        updates["jev_timeout_seconds"] = current.jev_timeout_seconds - 0.10
    return replace(current, **updates).bounded() if updates else current


def write_profile(path: str | Path, profile: PolicyProfile, evidence: dict[str, Any] | None = None) -> Path:
    output = profile_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "version": 1,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "profile": profile.bounded().to_dict(),
        "evidence": evidence or {},
    }
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Isaac death episodes and tune the local policy profile")
    parser.add_argument("--log-dir", default="logs", help="Directory containing episodes.jsonl and policy_profile.json")
    parser.add_argument("--write", action="store_true", help="Write the suggested profile to policy_profile.json")
    args = parser.parse_args()
    log_dir = Path(args.log_dir)
    events = analyze_episodes(log_dir / "episodes.jsonl")
    pending = pending_events(events, applied_death_counts(log_dir))
    before = load_profile(log_dir)
    after = suggest_profile(pending, before)
    counts = dict(_counts(events))
    changed = {key: [before.to_dict()[key], after.to_dict()[key]] for key in before.to_dict() if before.to_dict()[key] != after.to_dict()[key]}
    print(json.dumps({"episodes": len(events), "pending_episodes": len(pending), "death_counts": counts, "before": before.to_dict(), "after": after.to_dict(), "changed": changed}, ensure_ascii=False, indent=2))
    if args.write:
        output = write_profile(log_dir, after, {"episodes": len(events), "death_counts": counts, "changed": changed})
        print(f"wrote {output}")


if __name__ == "__main__":
    main()
