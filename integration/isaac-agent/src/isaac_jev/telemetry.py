from __future__ import annotations

import json
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any

from .models import Action, GameState


class EpisodeRecorder:
    """Record bounded, local-only trajectories and classify deaths.

    The recorder deliberately stores observations rather than Jev payloads. A
    death is written as one JSONL object containing the final trajectory
    window, which keeps the input loop cheap while retaining useful evidence.
    """

    def __init__(
        self,
        path: str | Path = "logs/episodes.jsonl",
        max_samples: int = 240,
        projectile_hit_distance: float = 55.0,
        enemy_contact_distance: float = 52.0,
        latency_threshold_ms: float = 350.0,
    ) -> None:
        self.path = Path(path)
        self.max_samples = max(16, int(max_samples))
        self.projectile_hit_distance = float(projectile_hit_distance)
        self.enemy_contact_distance = float(enemy_contact_distance)
        self.latency_threshold_ms = float(latency_threshold_ms)
        self._trajectory: deque[dict[str, Any]] = deque(maxlen=self.max_samples)
        self._lock = threading.RLock()
        self._was_alive = False
        self._death_recorded = False
        self._episodes_recorded = 0
        self._death_counts: Counter[str] = Counter()
        self._last_death: dict[str, Any] | None = None
        self._load_existing()

    def _load_existing(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(event, dict) or event.get("type") != "death_episode":
                        continue
                    cause = str(event.get("cause", "unknown"))
                    self._episodes_recorded += 1
                    self._death_counts[cause] += 1
                    self._last_death = event
        except OSError:
            # A missing or locked log must never stop the game bridge.
            return

    @staticmethod
    def _nearest_distance(state: GameState, entities: tuple) -> float | None:
        if not entities:
            return None
        return min(item.position.distance_to(state.player.position) for item in entities)

    def _sample(
        self,
        state: GameState,
        action: Action | None,
        decision_latency_ms: float | None,
        state_age_seconds: float | None,
        diagnostics: dict[str, Any] | None,
    ) -> dict[str, Any]:
        diagnostics = diagnostics or {}
        return {
            "frame": state.frame,
            "room_index": state.layout.room_index,
            "player_hp": round(state.player.hit_points, 2),
            "player_position": {"x": round(state.player.position.x, 2), "y": round(state.player.position.y, 2)},
            "enemy_count": len(state.enemies),
            "projectile_count": len(state.projectiles),
            "nearest_enemy_distance": self._nearest_distance(state, state.enemies),
            "nearest_projectile_distance": self._nearest_distance(state, state.projectiles),
            "room_clear": state.room_clear,
            "action_id": action.action_id if action else None,
            "action_mode": action.mode if action else None,
            "action_source": action.source if action else None,
            "action_confidence": round(action.confidence, 3) if action else None,
            "action_sequence": diagnostics.get("action_sequence"),
            "transition_phase": state.transition_phase,
            "decision_latency_ms": round(decision_latency_ms, 2) if decision_latency_ms is not None else None,
            "state_age_seconds": round(state_age_seconds, 4) if state_age_seconds is not None else None,
            "repeated_action_count": diagnostics.get("repeated_action_count", 0),
            "movement_stall_count": diagnostics.get("movement_stall_count", 0),
            "stale_actions_discarded": diagnostics.get("stale_actions_discarded", 0),
            "pickup_target_id": diagnostics.get("pickup_target_id"),
        }

    def _classify(self) -> tuple[str, dict[str, Any]]:
        samples = list(self._trajectory)
        recent = samples[-min(30, len(samples)) :]
        projectile_hits = [item for item in recent if isinstance(item.get("nearest_projectile_distance"), (int, float)) and item["nearest_projectile_distance"] <= self.projectile_hit_distance]
        enemy_contacts = [item for item in recent if isinstance(item.get("nearest_enemy_distance"), (int, float)) and item["nearest_enemy_distance"] <= self.enemy_contact_distance]
        latency_samples = [item for item in recent if (item.get("decision_latency_ms") or 0) >= self.latency_threshold_ms or (item.get("state_age_seconds") or 0) >= 0.6]
        navigation_samples = [item for item in recent if item.get("action_mode") == "navigate" or item.get("transition_phase") in {"native_door_only", "native_input", "native_input_blocked"}]
        pickup_samples = [item for item in recent if item.get("action_mode") in {"item", "pickup"}]
        combat_samples = [item for item in recent if item.get("action_mode") == "combat" and (item.get("enemy_count", 0) or item.get("projectile_count", 0))]

        if projectile_hits:
            return "projectile_hit", {"nearest_projectile_distance": min(item["nearest_projectile_distance"] for item in projectile_hits), "samples": len(projectile_hits)}
        if enemy_contacts:
            return "enemy_contact", {"nearest_enemy_distance": min(item["nearest_enemy_distance"] for item in enemy_contacts), "samples": len(enemy_contacts)}
        if latency_samples:
            return "decision_latency", {"max_decision_latency_ms": max(item.get("decision_latency_ms") or 0 for item in latency_samples), "samples": len(latency_samples)}
        if navigation_samples and any((item.get("repeated_action_count") or 0) >= 12 for item in navigation_samples):
            return "navigation_stuck", {"samples": len(navigation_samples), "max_repeated_action_count": max(item.get("repeated_action_count") or 0 for item in navigation_samples)}
        if pickup_samples and any((item.get("repeated_action_count") or 0) >= 12 for item in pickup_samples):
            return "pickup_stall", {"samples": len(pickup_samples), "max_repeated_action_count": max(item.get("repeated_action_count") or 0 for item in pickup_samples)}
        if combat_samples:
            return "combat_exposure", {"samples": len(combat_samples), "max_enemy_count": max(item.get("enemy_count", 0) for item in combat_samples)}
        return "unknown", {"samples": len(recent)}

    def record(
        self,
        state: GameState,
        action: Action | None = None,
        decision_latency_ms: float | None = None,
        state_age_seconds: float | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Add one sample and return a newly written death event, if any."""
        with self._lock:
            # A positive HP observation starts a fresh episode and also handles
            # a restart where the game frame counter goes back to zero.
            if state.player.hit_points > 0:
                self._was_alive = True
                self._death_recorded = False
            sample = self._sample(state, action, decision_latency_ms, state_age_seconds, diagnostics)
            self._trajectory.append(sample)
            if state.player.hit_points > 0 or not self._was_alive or self._death_recorded:
                return None
            self._death_recorded = True
            cause, evidence = self._classify()
            event = {
                "type": "death_episode",
                "version": 1,
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "cause": cause,
                "evidence": evidence,
                "final_frame": state.frame,
                "final_room_index": state.layout.room_index,
                "trajectory": list(self._trajectory),
            }
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            except OSError:
                # Keep the in-memory diagnostics even if the disk is read-only.
                pass
            self._episodes_recorded += 1
            self._death_counts[cause] += 1
            self._last_death = event
            return event

    def status(self) -> dict[str, Any]:
        with self._lock:
            last_death = None
            if self._last_death:
                last_death = {key: value for key, value in self._last_death.items() if key != "trajectory"}
                last_death["trajectory_samples"] = len(self._last_death.get("trajectory", []))
            return {
                "path": str(self.path),
                "episodes_recorded": self._episodes_recorded,
                "death_counts": dict(self._death_counts),
                "last_death": last_death,
                "trajectory_samples": len(self._trajectory),
            }
