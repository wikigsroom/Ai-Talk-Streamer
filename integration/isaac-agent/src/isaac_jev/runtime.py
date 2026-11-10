from __future__ import annotations

import json
import hashlib
import inspect
import re
import socketserver
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .decision import action_label, build_candidate_set, conservative_action, decision_rules, local_policy_action, loot_policy, policy_router, repeat_action_penalty_action
from .models import Action, GameState, RoomLayout, Vec2
from .navigation import door_is_usable, door_path_distance, newly_opened_secret_door, path_distance
from .telemetry import EpisodeRecorder
from .replay import DecisionTraceRecorder
from .tuning import PolicyProfile, load_profile
from .snapshots import publish_json
from .providers import DecisionProviderConfig, JevProvider, ProviderConfigStore, ProviderDecision, create_provider
from .experiment import ExperimentEventRecorder, IncrementalStatistics

DOOR_RETRY_FRAMES = 90
RECOVERY_TRIGGER_FRAMES = 60
RECOVERY_ACTION_FRAMES = 18
RECOVERY_REMOTE_INTERVAL_FRAMES = 60


@dataclass
class Controller:
    autopilot_enabled: bool = False
    decision_hz: float = 6.0
    macro_horizon_frames: int = 8
    log_dir: str = "logs"
    policy_profile: PolicyProfile | None = None
    provider_config_path: str | None = None
    require_enabled_action_feedback: bool = False
    _latest_state: GameState | None = field(default=None, init=False)
    _latest_action: Action | None = field(default=None, init=False)
    _last_decision_at: float = field(default=0.0, init=False)
    _future: Future[Action] | None = field(default=None, init=False)
    _future_started_at: float = field(default=0.0, init=False)
    _future_started_frame: int = field(default=-1, init=False)
    _future_provider_generation: int = field(default=0, init=False)
    _last_decision_frame: int = field(default=-10_000, init=False)
    _last_layout: RoomLayout = field(default_factory=RoomLayout, init=False)
    _history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=8), init=False)
    _debug_history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=60), init=False)
    _connections: int = field(default=0, init=False)
    _received_bytes: int = field(default=0, init=False)
    _received_states: int = field(default=0, init=False)
    _bridge_error: str | None = field(default=None, init=False)
    _latest_lua_fired_tears: int = field(default=0, init=False)
    _latest_lua_fire_error: str | None = field(default=None, init=False)
    _visited_rooms: set[int] = field(default_factory=set, init=False)
    _floor_key: tuple[Any, ...] | None = field(default=None, init=False)
    _room_failures: dict[int, tuple[set[int], set[int]]] = field(default_factory=dict, init=False)
    _room_failure_geometry: dict[int, frozenset[int]] = field(default_factory=dict, init=False)
    _backtrack_edges: set[tuple[int, int]] = field(default_factory=set, init=False)
    _hazard_last_hp: float | None = field(default=None, init=False)
    _exhausted_rooms: set[int] = field(default_factory=set, init=False)
    _current_room_index: int = field(default=-1, init=False)
    _previous_room_index: int = field(default=-1, init=False)
    _room_graph: dict[int, tuple] = field(default_factory=dict, init=False)
    _unreachable_door_edges: set[tuple[int, int, int]] = field(default_factory=set, init=False)
    _door_retry_until: dict[tuple[int, int, int], int] = field(default_factory=dict, init=False)
    _door_retry_reasons: dict[tuple[int, int, int], str] = field(default_factory=dict, init=False)
    _traversed_edges: set[tuple[int, int]] = field(default_factory=set, init=False)
    _edge_visit_counts: dict[tuple[int, int], int] = field(default_factory=dict, init=False)
    _room_intel: dict[int, dict[str, Any]] = field(default_factory=dict, init=False)
    _planned_door_slot: int = field(default=-1, init=False)
    _planned_goal: str = field(default="", init=False)
    _committed_door_slot: int = field(default=-1, init=False)
    _committed_door_room: int = field(default=-1, init=False)
    _ignored_pickup_ids: set[int] = field(default_factory=set, init=False)
    _ignored_hazard_ids: set[int] = field(default_factory=set, init=False)
    _last_held_trinkets: tuple[int, ...] = field(default=(), init=False)
    _dropped_trinket_subtypes: set[int] = field(default_factory=set, init=False)
    _combat_stuck: bool = field(default=False, init=False)
    _pickup_target_id: int = field(default=-1, init=False)
    _pickup_last_distance: float | None = field(default=None, init=False)
    _pickup_last_progress_frame: int = field(default=0, init=False)
    _hazard_target_id: int = field(default=-1, init=False)
    _hazard_last_distance: float | None = field(default=None, init=False)
    _hazard_last_progress_frame: int = field(default=0, init=False)
    _hazard_progress_by_target: dict[int, tuple[float, float, int]] = field(default_factory=dict, init=False)
    _hazard_animation_by_target: dict[int, str] = field(default_factory=dict, init=False)
    _hazard_retry_after: dict[int, int] = field(default_factory=dict, init=False)
    _unreachable_targets: list[str] = field(default_factory=list, init=False)
    _effective_action: Action | None = field(default=None, init=False)
    _last_response_signature: tuple[Any, ...] | None = field(default=None, init=False)
    _action_sequence: int = field(default=0, init=False)
    _stale_actions_discarded: int = field(default=0, init=False)
    _repeated_action_count: int = field(default=0, init=False)
    _stall_override: Action | None = field(default=None, init=False)
    _stall_override_until_frame: int = field(default=-1, init=False)
    _last_stall_penalty_frame: int = field(default=-10_000, init=False)
    _stall_penalty_count: int = field(default=0, init=False)
    _last_stall_penalty_reason: str | None = field(default=None, init=False)
    _movement_stall_count: int = field(default=0, init=False)
    _stall_anchor: Vec2 | None = field(default=None, init=False)
    _stall_since_frame: int = field(default=0, init=False)
    _stall_target_slot: int = field(default=-1, init=False)
    _stall_best_distance: float | None = field(default=None, init=False)
    _recent_action_feedback: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=5), init=False)
    _last_action_sample: dict[str, Any] | None = field(default=None, init=False)
    _local_recovery_failures: int = field(default=0, init=False)
    _recovery_last_remote_frame: int = field(default=-10_000, init=False)
    _recovery_reason: str = field(default="", init=False)
    _stale_decisions_discarded: int = field(default=0, init=False)
    _last_stale_decision_reason: str | None = field(default=None, init=False)
    _transition_phase: str = field(default="idle", init=False)
    _transition_attempt: int = field(default=0, init=False)
    _transition_error: str = field(default="", init=False)
    _lua_transition_source_room: int = field(default=-1, init=False)
    _lua_transition_target_room: int = field(default=-1, init=False)
    _lua_room_entry_age_frames: int = field(default=0, init=False)
    _lua_backtrack_guard_active: bool = field(default=False, init=False)
    _last_state_at: float = field(default=0.0, init=False)
    _last_decision_latency_ms: float | None = field(default=None, init=False)
    _latency_samples: deque[float] = field(default_factory=lambda: deque(maxlen=120), init=False)
    _profile: PolicyProfile = field(default_factory=PolicyProfile, init=False)
    _recorder: EpisodeRecorder = field(init=False)
    _trace_recorder: DecisionTraceRecorder = field(init=False)
    _experiment_recorder: ExperimentEventRecorder = field(init=False)
    _statistics_store: IncrementalStatistics = field(init=False)
    _last_trace: dict[str, Any] | None = field(default=None, init=False)
    _last_trace_id: str | None = field(default=None, init=False)
    _pending_trace_outcomes: list[dict[str, Any]] = field(default_factory=list, init=False)
    _remote_call_count: int = field(default=0, init=False)
    _local_decision_count: int = field(default=0, init=False)
    _last_policy: str = field(default="local", init=False)
    _last_request_bytes: int = field(default=0, init=False)
    _last_state_bytes: int = field(default=0, init=False)
    _last_estimated_input_tokens: int = field(default=0, init=False)
    _last_remote_latency_ms: float | None = field(default=None, init=False)
    _last_fallback_reason: str | None = field(default=None, init=False)
    _remote_latency_samples: deque[float] = field(default_factory=lambda: deque(maxlen=120), init=False)
    _executor: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(max_workers=1), init=False)
    _shadow_executor: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(max_workers=1), init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _state_lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _provider_store: ProviderConfigStore = field(init=False)
    _provider_config: DecisionProviderConfig = field(init=False)
    _pending_provider_config: DecisionProviderConfig = field(init=False)
    _active_provider_name: str = field(default="local", init=False)
    _active_provider_model: str = field(default="local-policy", init=False)
    _provider_generation: int = field(default=0, init=False)
    _run_id: str = field(default="", init=False)
    _run_seed: int | None = field(default=None, init=False)
    _last_restart_count: int = field(default=0, init=False)
    _last_state_frame: int = field(default=-1, init=False)
    _shadow_future: Future[ProviderDecision] | None = field(default=None, init=False)
    _shadow_provider_name: str | None = field(default=None, init=False)
    _shadow_skipped_busy: int = field(default=0, init=False)
    _provider_health: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    _damage_attribution: dict[int, str] = field(default_factory=dict, init=False)
    _seen_damage_event_ids: set[int] = field(default_factory=set, init=False)
    _last_room_clear: bool = field(default=False, init=False)
    _boss_clear_observed_frame: int = field(default=-1, init=False)
    _last_player_dead: bool = field(default=False, init=False)
    _run_end_recorded: bool = field(default=False, init=False)
    _game_result: dict[str, Any] | None = field(default=None, init=False)
    _progress_key: tuple[Any, ...] | None = field(default=None, init=False)
    _raw_state_at: float = field(default=0.0, init=False)
    _delivered_signature: tuple[Any, ...] | None = field(default=None, init=False)
    _delivered_sequence: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._profile = (self.policy_profile or load_profile(self.log_dir)).bounded()
        self._recorder = EpisodeRecorder(
            path=f"{self.log_dir}/episodes.jsonl",
            projectile_hit_distance=self._profile.projectile_evade_radius,
        )
        self._trace_recorder = DecisionTraceRecorder(f"{self.log_dir}/decision_traces.jsonl")
        self._experiment_recorder = ExperimentEventRecorder(f"{self.log_dir}/experiment_runs.jsonl")
        self._statistics_store = IncrementalStatistics(
            f"{self.log_dir}/decision_traces.jsonl", f"{self.log_dir}/experiment_runs.jsonl"
        )
        self.macro_horizon_frames = min(12, max(6, int(self.macro_horizon_frames)))
        self._provider_store = (ProviderConfigStore(self.provider_config_path, environ={})
                                if self.provider_config_path else ProviderConfigStore())
        try:
            self._provider_config = self._provider_store.load()
        except Exception:
            self._provider_config = DecisionProviderConfig()
        self._pending_provider_config = self._provider_config
        self._active_provider_name = self._provider_config.selected_provider
        self._active_provider_model = self._provider_config.providers[self._active_provider_name].model
        self._provider_generation = 1

    def provider_config(self) -> dict[str, Any]:
        config = self._pending_provider_config
        active = self._provider_config
        return {
            **config.public_dict(),
            "active_provider": self._active_provider_name,
            "active_model": self._active_provider_model,
            "next_provider": config.selected_provider,
            "next_model": config.providers[config.selected_provider].model,
            "run_id": self._run_id,
            "run_seed": self._run_seed,
            "active_config": active.public_dict(),
            "health": dict(self._provider_health),
        }

    def update_provider_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        from .providers import parse_provider_config
        # Start from the private in-memory config so saving a selector from
        # the web page does not accidentally erase the existing API key.
        merged = self._pending_provider_config.persisted_dict()
        merged.update({key: value for key, value in raw.items() if key in {"version", "selected_provider", "shadow_enabled", "shadow_provider"}})
        if isinstance(raw.get("providers"), dict):
            current_providers = merged.get("providers", {})
            merged_providers = dict(current_providers) if isinstance(current_providers, dict) else {}
            for name, value in raw["providers"].items():
                if not isinstance(value, dict):
                    merged_providers[name] = value
                    continue
                current = merged_providers.get(name)
                merged_providers[name] = {**current, **value} if isinstance(current, dict) else dict(value)
            merged["providers"] = merged_providers
        config = parse_provider_config(merged, self._provider_store.environ)
        self._provider_store.save(config)
        with self._lock:
            self._pending_provider_config = config
            # Provider/model changes are live for the current run. Invalidate
            # the in-flight result so a response from the previous model can
            # never become the next action.
            self._provider_config = config
            self._active_provider_name = config.selected_provider
            self._active_provider_model = config.providers[config.selected_provider].model
            self._provider_generation += 1
            self._last_decision_frame = -10_000
            self._last_decision_at = 0.0
            if self._future:
                self._future.cancel()
                self._future = None
                self._future_started_at = 0.0
                self._future_started_frame = -1
            if self._shadow_future:
                self._shadow_future.cancel()
                self._shadow_future = None
        return self.provider_config()

    def check_provider(self, name: str) -> dict[str, Any]:
        from .providers import _provider_name
        provider_name = _provider_name(name, "provider")
        provider = create_provider(provider_name, self._pending_provider_config, self._profile, self._provider_store.environ)
        result = provider.health_check().__dict__
        with self._lock:
            self._provider_health[provider_name] = result
        return result

    def statistics(self, filters: dict[str, str] | None = None) -> dict[str, Any]:
        filters = filters or {}
        self._statistics_store.refresh()
        return self._statistics_store.snapshot(filters.get("seed"), filters.get("provider"), filters.get("model"))

    def _maybe_start_run(self, state: GameState) -> None:
        seed_value = getattr(state, "start_seed", None)
        boundary = (
            not self._run_id
            or (seed_value is not None and self._run_seed is not None and seed_value != self._run_seed)
            or state.frame < self._last_state_frame
            or state.restart_count > self._last_restart_count
        )
        if not boundary:
            self._last_state_frame = state.frame
            self._last_restart_count = state.restart_count
            return
        import uuid
        self._run_id = uuid.uuid4().hex[:16]
        self._run_end_recorded = False
        self._game_result = None
        self._run_seed = seed_value
        self._last_state_frame = state.frame
        self._last_restart_count = state.restart_count
        self._provider_config = self._pending_provider_config
        self._active_provider_name = self._provider_config.selected_provider
        self._active_provider_model = self._provider_config.providers[self._active_provider_name].model
        self._provider_generation += 1
        self._pending_trace_outcomes.clear()
        self._damage_attribution.clear()
        self._experiment_recorder.record(
            "run_started", run_id=self._run_id, start_seed=self._run_seed,
            provider=self._active_provider_name,
            model=self._active_provider_model,
        )
        if self._future:
            self._future.cancel()
            self._future = None
        if self._shadow_future:
            self._shadow_future.cancel()
            self._shadow_future = None

    def receive_state(self, message: dict[str, Any]) -> dict[str, Any]:
        # The Lua bridge uses a threaded server. Serialize state transitions so
        # one request cannot clear an action while another request reads it.
        with self._state_lock:
            response = self._receive_state_unlocked(message)
            strategy = getattr(self, 'strategy_service', None)
            if strategy is not None:
                strategy.update(message, self._latest_state)
                response = strategy.decorate_response(response, self._latest_state)
                self._track_delivered_strategy_action(response)
            now = time.monotonic()
            key = tuple(message.get(k) for k in ("start_seed", "stage", "stage_type", "room_index", "room_clear", "restart_count"))
            root = Path(self.log_dir)
            root.mkdir(parents=True, exist_ok=True)
            if now - self._raw_state_at >= 1.0 or key != self._progress_key:
                publish_json(root / "latest-raw-state.json",message)
                self._raw_state_at = now
            if key != self._progress_key:
                self._experiment_recorder.record("game_progress", run_id=self._run_id,
                    start_seed=message.get("start_seed"), stage=message.get("stage"),
                    stage_type=message.get("stage_type"), room_index=message.get("room_index"),
                    room_clear=message.get("room_clear"), frame=message.get("frame"),
                    restart_count=message.get("restart_count"), player=message.get("player"))
                self._progress_key = key
            return response

    def _track_delivered_strategy_action(self, response: dict[str, Any]) -> None:
        # Progress feedback must describe the action delivered to Lua, including
        # a strategic hold. A baseline proposal withheld while the model thinks
        # is not an attempted path and must not become an unreachable pickup.
        if not response.get('strategy', {}).get('owned'):
            return
        self._effective_action = Action(
            action_id=response.get('id', ''), move=Vec2.from_value(response.get('move')),
            shoot=Vec2.from_value(response.get('shoot')), mode=response.get('mode', ''),
            source=response.get('source', ''), target=response.get('target', ''),
            reason=response.get('reason', ''), issued_frame=response.get('issued_frame', -1),
            expires_frame=response.get('expires_frame', -1),
            waypoint=Vec2.from_value(response['waypoint']) if response.get('waypoint') else None,
        )
        signature = (response.get('source_room_index'), response.get('id'), response.get('mode'),
                     response.get('target'), (response['strategy'].get('command') or {}).get('plan_id'))
        if signature != self._delivered_signature:
            self._delivered_signature = signature
            self._delivered_sequence += 1
        response['action_sequence'] = self._delivered_sequence
        if response.get('mode') == 'strategy_hold':
            self._pickup_target_id = -1
            self._pickup_last_distance = None
            self._movement_stall_count = 0

    def receive_game_event(self, message: dict[str, Any]) -> None:
        """Record the native MC_POST_GAME_END result; false means an ending."""
        if message.get("callback") != "MC_POST_GAME_END" or type(message.get("is_game_over")) is not bool:
            return
        with self._state_lock, self._lock:
            if self._latest_state is None or message.get("start_seed") != self._run_seed:
                return
            won = message["is_game_over"] is False
            result = dict(message, result="victory" if won else "death", run_id=self._run_id)
            self._game_result = result
            self._experiment_recorder.record("native_game_end", **{k: v for k, v in result.items() if k != "type"})
            root = Path(self.log_dir)
            root.mkdir(parents=True, exist_ok=True)
            with (root / "native-game-events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            if won:
                (root / "victory.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                self.autopilot_enabled = False
                self._latest_action = None
                self._stall_override = None
                self._run_end_recorded = True

    def _receive_state_unlocked(self, message: dict[str, Any]) -> dict[str, Any]:
        # Lua's retry counter resets on a Mod reload. Seed/stage/dimension and
        # frame regression already identify real run and floor boundaries.
        floor_key = (message.get("start_seed"), message.get("stage"), message.get("stage_type"), message.get("dimension"), message.get("floor_id"))
        frame = int(message.get("frame", 0))
        boundary = self._floor_key is not None and (floor_key != self._floor_key or frame < self._last_state_frame)
        if boundary:
            self._provider_generation += 1
            if self._future:
                self._future.cancel()
                self._future = None
            self._future_started_at = 0.0
            self._future_started_frame = -1
            self._latest_action = None
            self._effective_action = None
            self._last_response_signature = None
            self._stall_override = None
            self._stall_override_until_frame = -1
            self._visited_rooms.clear()
            self._exhausted_rooms.clear()
            self._room_graph.clear()
            self._room_intel.clear()
            self._unreachable_door_edges.clear()
            self._door_retry_until.clear()
            self._door_retry_reasons.clear()
            self._traversed_edges.clear()
            self._edge_visit_counts.clear()
            self._backtrack_edges.clear()
            self._room_failures.clear()
            self._room_failure_geometry.clear()
            self._current_room_index = -1
            self._previous_room_index = -1
            self._committed_door_slot = -1
            self._committed_door_room = -1
            self._last_layout = RoomLayout()
            self._movement_stall_count = 0
            self._stall_anchor = None
            self._stall_since_frame = frame
            self._stall_target_slot = -1
            self._stall_best_distance = None
            self._recent_action_feedback.clear()
            self._last_action_sample = None
            self._local_recovery_failures = 0
            self._recovery_last_remote_frame = -10_000
            self._recovery_reason = ""
            self._last_decision_frame = -10_000
            self._boss_clear_observed_frame = -1
        self._floor_key = floor_key
        if isinstance(message.get("layout"), dict):
            self._last_layout = RoomLayout.from_value(message["layout"])
        elif (self._last_layout.room_index >= 0
              or self._last_layout.room_type in {"devil", "angel"}):
            message = message | {"layout": {
                "room_index": self._last_layout.room_index,
                "room_type": self._last_layout.room_type,
                "is_boss": self._last_layout.is_boss,
                "grid_width": self._last_layout.grid_width,
                "grid_height": self._last_layout.grid_height,
                "blocked": list(self._last_layout.blocked),
                "shot_blocked": list(self._last_layout.shot_blocked) if self._last_layout.shot_blocked is not None else None,
                "danger_grid_indices": list(self._last_layout.danger_grid_indices),
                "grid_events": [{"kind": event.kind, "id": event.entity_id, "pos": event.position.__dict__, "grid_index": event.grid_index, "active": event.active, "triggered": event.triggered, "timed": event.timed} for event in self._last_layout.grid_events],
                "bomb_walls": [{"slot": wall.slot, "pos": wall.position.__dict__, "site": wall.site.__dict__, "grid_index": wall.grid_index, "room_type": wall.room_type, "bombed": wall.bombed} for wall in self._last_layout.bomb_walls],
                "doors": [{"slot": door.slot, "pos": door.position.__dict__, "target_room_index": door.target_room_index, "target_is_boss": door.target_is_boss, "target_clear": door.target_clear, "target_room_type": door.target_room_type, "grid_index": door.grid_index, "door_locked": door.locked, "door_lock_known": door.lock_known, "door_open": door.open, "door_open_known": door.open_known} for door in self._last_layout.doors],
            }}
        room_index = self._last_layout.room_index
        known_room = room_index >= 0 or self._last_layout.room_type in {"devil", "angel"}
        room_changed = known_room and room_index != self._current_room_index
        if room_changed:
            self._boss_clear_observed_frame = -1
            if self._current_room_index in self._visited_rooms:
                self._room_failures[self._current_room_index] = (set(self._ignored_pickup_ids), set(self._ignored_hazard_ids))
                if self._planned_goal == "backtrack to entry room":
                    self._backtrack_edges.add((self._current_room_index, room_index))
                self._traversed_edges.add((self._current_room_index, room_index))
                edge_pair = (self._current_room_index, room_index)
                self._edge_visit_counts[edge_pair] = self._edge_visit_counts.get(edge_pair, 0) + 1
            self._previous_room_index = self._current_room_index
            self._current_room_index = room_index
            self._committed_door_slot = -1
            self._committed_door_room = -1
            self._last_decision_frame = -10_000
            self._visited_rooms.add(room_index)
            failed_pickups, failed_hazards = self._room_failures.get(room_index, (set(), set()))
            self._ignored_pickup_ids = set(failed_pickups)
            self._ignored_hazard_ids = set(failed_hazards)
            self._dropped_trinket_subtypes.clear()
            self._combat_stuck = False
            self._pickup_target_id = -1
            self._pickup_last_distance = None
            self._pickup_last_progress_frame = 0
            self._hazard_target_id = -1
            self._hazard_last_distance = None
            self._hazard_last_progress_frame = 0
            self._hazard_progress_by_target.clear()
            self._hazard_animation_by_target.clear()
            self._hazard_retry_after.clear()
            self._unreachable_targets.clear()
            self._effective_action = None
            self._last_response_signature = None
            self._stall_override = None
            self._stall_override_until_frame = -1
            self._stall_anchor = None
            self._stall_since_frame = frame
            self._stall_target_slot = -1
            self._stall_best_distance = None
            self._recent_action_feedback.clear()
            self._last_action_sample = None
            self._local_recovery_failures = 0
            self._recovery_reason = ""
            self._recovery_last_remote_frame = -10_000
            self._transition_phase = "entered"
        old_geometry = self._room_failure_geometry.get(room_index)
        if old_geometry is not None and old_geometry != self._last_layout.blocked:
            self._ignored_pickup_ids.clear()
            self._ignored_hazard_ids.clear()
            self._room_failures.pop(room_index, None)
            self._unreachable_door_edges = {edge for edge in self._unreachable_door_edges if edge[0] != room_index}
            self._door_retry_until = {edge: until for edge, until in self._door_retry_until.items() if edge[0] != room_index}
            self._door_retry_reasons = {edge: reason for edge, reason in self._door_retry_reasons.items() if edge[0] != room_index}
        self._room_failure_geometry[room_index] = self._last_layout.blocked
        self._expire_door_retries(frame)
        if known_room:
            self._room_graph[room_index] = self._last_layout.doors
        if message.get("room_clear") and (self._last_layout.is_boss or self._last_layout.room_type == "boss"):
            reported_clear = message.get("room_cleared_frame")
            if reported_clear is None or int(reported_clear) < 0:
                if self._boss_clear_observed_frame < 0:
                    self._boss_clear_observed_frame = frame
                message = message | {"room_cleared_frame": self._boss_clear_observed_frame}
        base_message = message | {
            "visited_room_indices": sorted(self._visited_rooms),
            "exhausted_room_indices": sorted(self._exhausted_rooms),
            "previous_room_index": self._previous_room_index,
            "ignored_pickup_ids": sorted(self._ignored_pickup_ids),
            "ignored_hazard_ids": sorted(self._ignored_hazard_ids),
            "combat_stuck": self._combat_stuck,
        }
        observed_state = GameState.from_message(base_message)
        self._maybe_start_run(observed_state)
        if room_changed:
            self._experiment_recorder.record(
                "room_started", run_id=self._run_id,
                room_visit_id=f"{self._run_id}:{observed_state.room_visit_sequence or room_index}",
                start_seed=self._run_seed, provider=self._active_provider_name, model=self._active_provider_model,
                room_index=room_index, entered_frame=observed_state.room_entered_frame,
                combat=bool(observed_state.enemies), enemy_count=len(observed_state.enemies),
            )
        if observed_state.room_clear and not self._last_room_clear:
            self._experiment_recorder.record(
                "room_completed", run_id=self._run_id,
                room_visit_id=f"{self._run_id}:{observed_state.room_visit_sequence or room_index}",
                start_seed=self._run_seed, provider=self._active_provider_name, model=self._active_provider_model,
                room_index=room_index, entered_frame=observed_state.room_entered_frame,
                cleared_frame=observed_state.room_cleared_frame or observed_state.frame,
                clear_frames=max(0, (observed_state.room_cleared_frame or observed_state.frame) - observed_state.room_entered_frame),
                combat=bool(observed_state.enemies) or observed_state.enemy_count > 0,
            )
        for damage in observed_state.damage_events:
            if damage.event_id not in self._seen_damage_event_ids:
                self._seen_damage_event_ids.add(damage.event_id)
                self._experiment_recorder.record(
                    "damage", run_id=self._run_id,
                    room_visit_id=f"{self._run_id}:{observed_state.room_visit_sequence or room_index}",
                    start_seed=self._run_seed, provider=self._active_provider_name, model=self._active_provider_model,
                    damage_event_id=damage.event_id, frame=damage.frame, amount=damage.amount,
                    flags=damage.flags, source_type=damage.source_type, source_variant=damage.source_variant,
                    damage_kind="projectile" if damage.source_type == 9 else "contact",
                )
        if observed_state.player_dead and not self._last_player_dead:
            self._experiment_recorder.record(
                "death", run_id=self._run_id, start_seed=self._run_seed,
                provider=self._active_provider_name, model=self._active_provider_model,
                frame=observed_state.frame, event_id=f"death:{self._run_id}:{observed_state.frame}",
            )
        self._last_room_clear = observed_state.room_clear
        self._last_player_dead = observed_state.player_dead
        if room_changed or observed_state.player_dead:
            self._pending_trace_outcomes.clear()
        else:
            self._update_trace_outcomes(observed_state)
        feedback_enabled = self.autopilot_enabled or not self.require_enabled_action_feedback
        if feedback_enabled:
            self._update_pickup_progress(observed_state)
        if not room_changed and self._last_held_trinkets != observed_state.held_trinkets:
            dropped = set(self._last_held_trinkets) - set(observed_state.held_trinkets)
            self._dropped_trinket_subtypes.update(dropped)
            for pickup in observed_state.pickups:
                if pickup.pickup_kind == "trinket" and pickup.subtype in dropped:
                    self._ignored_pickup_ids.add(pickup.entity_id)
        for pickup in observed_state.pickups:
            if pickup.pickup_kind == "trinket" and pickup.subtype in self._dropped_trinket_subtypes:
                self._ignored_pickup_ids.add(pickup.entity_id)
        self._last_held_trinkets = observed_state.held_trinkets
        if feedback_enabled:
            self._update_hazard_progress(observed_state)
        for target_id, retry_frame in tuple(self._hazard_retry_after.items()):
            if observed_state.frame >= retry_frame:
                self._hazard_retry_after.pop(target_id, None)
                self._ignored_hazard_ids.discard(target_id)
                self._hazard_progress_by_target.pop(target_id, None)
                self._hazard_animation_by_target.pop(target_id, None)
                self._last_decision_frame = -10_000
        self._clear_disappeared_pickup_action(observed_state)
        if feedback_enabled:
            self._update_movement_feedback(observed_state)
            self._update_navigation_stall(observed_state)
            self._record_action_feedback(observed_state)
            self._abandon_blocked_door(observed_state)
        if self._latest_action and self._latest_action.mode in {"hazard", "bomb"}:
            match = re.search(r"_(-?\d+)$", self._latest_action.action_id)
            target_id = int(match.group(1)) if match else -1
            negative_grid_target = (
                self._latest_action.action_id.startswith("clear_hazard_-")
                or self._latest_action.action_id.startswith("bomb_hazard_-")
            )
            boss_bomb = self._latest_action.action_id.startswith("bomb_boss_")
            target_exists = any(item.entity_id == target_id for item in observed_state.enemies if boss_bomb) or any(
                item.entity_id == target_id for item in observed_state.hazards if not boss_bomb
            )
            if (target_id < 0 and not negative_grid_target) or target_id in self._ignored_hazard_ids or not target_exists:
                # The target disappeared between decision ticks. Do not keep
                # replaying its old aim while the next state is evaluated.
                self._latest_action = None
        unresolved_pickups = tuple(item for item in observed_state.pickups if item.entity_id not in self._ignored_pickup_ids)
        unresolved_hazards = tuple(
            item for item in observed_state.hazards
            if item.entity_id not in self._ignored_hazard_ids
            and (not item.requires_bomb or observed_state.bombs > 0)
            and (item.kind != "blue_fire" or observed_state.bombs > 4)
        )
        if observed_state.room_clear and not unresolved_pickups and not unresolved_hazards and self._last_layout.doors:
            known_targets = [door.target_room_index for door in self._last_layout.doors if door.target_room_index >= 0]
            if known_targets and not any(target not in self._visited_rooms for target in known_targets):
                self._exhausted_rooms.add(room_index)
        previous_door_plan = (self._planned_door_slot, self._planned_goal)
        self._planned_door_slot, self._planned_goal = self._plan_next_door(observed_state)
        if self._planned_goal == "newly bombed secret room":
            # An old macro action or an in-flight decision for a default door
            # must not send Isaac away after the bomb opens the entrance.
            if self._latest_action and (
                (not observed_state.bomb_active and self._latest_action.action_id == "wait_for_bomb")
                or (self._latest_action.mode == "navigate" and self._latest_action.action_id != f"enter_door_{self._planned_door_slot}")
            ):
                self._latest_action = None
                self._effective_action = None
                self._last_decision_frame = -10_000
            if previous_door_plan != (self._planned_door_slot, self._planned_goal) and self._future and not self._future.done():
                self._future.cancel()
                self._future = None
                self._future_started_at = 0.0
                self._future_started_frame = -1
        recovery_door = next((door for door in observed_state.layout.doors
                              if door.slot == self._planned_door_slot and door_is_usable(door, observed_state)), None)
        if recovery_door is None:
            recovery_door = next((door for door in observed_state.layout.doors
                                  if door_is_usable(door, observed_state)), None)
        previous_action = self._effective_action or self._latest_action
        recoverable_action = previous_action is not None and (
            previous_action.mode in {"navigate", "recovery"}
            or previous_action.action_id in {"wait_for_exit", "wait_for_safety_filter", "wait_for_recovery_route"}
        )
        stall_frames = max(0, observed_state.frame - self._stall_since_frame)
        recovery_active = bool(
            recovery_door and recoverable_action and observed_state.room_clear
            and not observed_state.player_dead and not observed_state.bomb_active
            and not observed_state.enemies
            and not loot_policy(observed_state)
            and not ((observed_state.layout.is_boss or observed_state.layout.room_type == "boss")
                     and observed_state.room_cleared_frame >= 0
                     and observed_state.frame - observed_state.room_cleared_frame < 60)
            and (stall_frames >= RECOVERY_TRIGGER_FRAMES or self._local_recovery_failures >= 2)
        )
        if recovery_active:
            self._recovery_reason = (f"no navigation progress for {stall_frames} frames"
                                     if stall_frames >= RECOVERY_TRIGGER_FRAMES
                                     else f"{self._local_recovery_failures} local reposition attempts did not leave the room")
        else:
            self._recovery_reason = ""
        message = base_message | {
            "planned_door_slot": self._planned_door_slot,
            "planned_goal": self._planned_goal,
            "ignored_pickup_ids": sorted(self._ignored_pickup_ids),
            "ignored_hazard_ids": sorted(self._ignored_hazard_ids),
            "unreachable_door_slots": sorted(slot for room, slot, _ in self._unreachable_door_edges if room == room_index),
            "unreachable_targets": list(self._unreachable_targets),
            "combat_stuck": self._combat_stuck,
            "recovery_active": recovery_active,
            "recovery_reason": self._recovery_reason,
            "recovery_target_door_slot": recovery_door.slot if recovery_active and recovery_door else -1,
            "stall_frames": stall_frames,
            "recent_actions": list(self._recent_action_feedback),
            "transition_phase": self._transition_phase,
            "transition_attempt": self._transition_attempt,
            "transition_error": self._transition_error,
            "hostile_enemy_count": len(message.get("enemies", [])),
            "enemy_observation_valid": bool(message.get("enemy_observation_valid", True)),
        }
        state = GameState.from_message(message)
        current_candidates = build_candidate_set(state, self._profile).admissible_candidates if state.room_clear else ()
        exit_priority = current_candidates[0] if current_candidates and current_candidates[0].mode not in {"navigate", "boss_exit"} else None
        if exit_priority and self._latest_action and self._latest_action.mode in {"navigate", "boss_exit"}:
            self._latest_action = None
            self._effective_action = None
            self._last_decision_frame = -10_000
        if exit_priority and self._stall_override and self._stall_override.mode in {"navigate", "boss_exit"}:
            self._stall_override = None
            self._stall_override_until_frame = -1
        self._record_room_intel(state)
        now = time.monotonic()
        with self._lock:
            self._latest_lua_fired_tears = int(message.get("fired_tears", 0) or 0)
            raw_fire_error = message.get("fire_error")
            self._latest_lua_fire_error = str(raw_fire_error) if raw_fire_error else None
            self._received_states += 1
            self._latest_state = state
            self._last_state_at = now
            self._transition_phase = str(message.get("transition_phase", self._transition_phase) or self._transition_phase)
            self._transition_attempt = int(message.get("transition_attempt", self._transition_attempt) or 0)
            self._transition_error = str(message.get("transition_error", self._transition_error) or "")
            self._lua_transition_source_room = int(message.get("last_transition_source_room_index", -1) if message.get("last_transition_source_room_index") is not None else -1)
            self._lua_transition_target_room = int(message.get("last_transition_target_room_index", -1) if message.get("last_transition_target_room_index") is not None else -1)
            self._lua_room_entry_age_frames = int(message.get("room_entry_age_frames", 0) if message.get("room_entry_age_frames") is not None else 0)
            self._lua_backtrack_guard_active = bool(message.get("backtrack_guard_active", False))
            if state.player_dead:
                # Never let a combat/navigation result keep driving a dead
                # player while the Lua side waits for the restart transition.
                self._latest_action = None
                if self._future:
                    self._future.cancel()
                    self._future = None
                self._future_started_at = 0.0
                self._future_started_frame = -1
                self._stall_override = None
                self._stall_override_until_frame = -1
            if room_changed:
                # A background request describes the room that was just left.
                # Never let its result drive the player back through the same
                # door after the native room transition has completed.
                self._latest_action = None
                if self._future:
                    self._future.cancel()
                    self._future = None
                self._future_started_at = 0.0
                self._future_started_frame = -1
                self._transition_phase = "entered"
            if state.room_clear and not state.enemies and self._latest_action and self._latest_action.mode == "combat":
                # A mechanical trap can previously have been mistaken for an
                # enemy. Do not keep a stale combat macro after the corrected
                # observation confirms there is nothing to shoot.
                self._latest_action = None
                self._effective_action = None
                self._last_decision_frame = -10_000
            if self._latest_action and self._latest_action.action_id.startswith("bomb_boss_") and (
                state.bomb_placed or state.bomb_active or not any(
                    item.action_id == self._latest_action.action_id
                    for item in build_candidate_set(state, self._profile).admissible_candidates
                )
            ):
                self._latest_action = None
                self._effective_action = None
                self._last_decision_frame = -10_000
            if self._future and self._future.done():
                decision_age_frames = state.frame - self._future_started_frame if self._future_started_frame >= 0 else 0
                try:
                    result = self._future.result()
                    if self._future_provider_generation != self._provider_generation:
                        self._latest_action = replace(conservative_action(state, self._profile), issued_frame=state.frame, expires_frame=state.frame + self.macro_horizon_frames)
                        self._stale_decisions_discarded += 1
                        self._last_stale_decision_reason = "provider generation changed"
                    elif decision_age_frames > self._profile.max_action_age_frames:
                        self._latest_action = replace(conservative_action(state, self._profile), issued_frame=state.frame, expires_frame=state.frame + self.macro_horizon_frames)
                        self._stale_decisions_discarded += 1
                        self._last_stale_decision_reason = f"decision age {decision_age_frames} frames exceeded {self._profile.max_action_age_frames}"
                    elif state.geometry_features().get("nearest_tracking_bomb_imminent") and result.mode != "evade":
                        self._latest_action = replace(conservative_action(state, self._profile), issued_frame=state.frame,
                                                      expires_frame=state.frame + self.macro_horizon_frames)
                        self._stale_decisions_discarded += 1
                        self._last_stale_decision_reason = "tracking bomb superseded earlier decision"
                    elif result.mode == "evade" and not any(
                        item.action_id == result.action_id
                        for item in build_candidate_set(state, self._profile).admissible_candidates
                    ):
                        self._latest_action = replace(conservative_action(state, self._profile), issued_frame=state.frame,
                                                      expires_frame=state.frame + self.macro_horizon_frames)
                        self._stale_decisions_discarded += 1
                        self._last_stale_decision_reason = "tracking bomb escape is no longer legal"
                    elif result.mode == "combat" and state.room_clear and not state.enemies:
                        self._latest_action = replace(conservative_action(state, self._profile), issued_frame=state.frame,
                                                      expires_frame=state.frame + self.macro_horizon_frames)
                        self._stale_decisions_discarded += 1
                        self._last_stale_decision_reason = "combat target disappeared before decision arrived"
                    elif result.mode in {"navigate", "boss_exit"} and exit_priority:
                        self._latest_action = replace(conservative_action(state, self._profile), issued_frame=state.frame,
                                                      expires_frame=state.frame + self.macro_horizon_frames)
                        self._stale_decisions_discarded += 1
                        self._last_stale_decision_reason = "room reward or Boss spawn wait superseded exit"
                    elif result.action_id.startswith("bomb_boss_") and not any(
                        item.action_id == result.action_id
                        for item in build_candidate_set(state, self._profile).admissible_candidates
                    ):
                        self._latest_action = replace(conservative_action(state, self._profile), issued_frame=state.frame,
                                                      expires_frame=state.frame + self.macro_horizon_frames)
                        self._stale_decisions_discarded += 1
                        self._last_stale_decision_reason = "Boss bomb is no longer safe or available"
                    elif state.planned_goal == "newly bombed secret room" and result.mode == "navigate" and result.action_id != f"enter_door_{state.planned_door_slot}":
                        self._latest_action = replace(conservative_action(state, self._profile), issued_frame=state.frame,
                                                      expires_frame=state.frame + self.macro_horizon_frames)
                        self._stale_decisions_discarded += 1
                        self._last_stale_decision_reason = "newly opened secret entrance superseded earlier navigation"
                    elif result.mode == "recovery" and (
                        not state.recovery_active or not any(
                            item.action_id == result.action_id
                            for item in build_candidate_set(state, self._profile).admissible_candidates
                        )
                    ):
                        self._latest_action = replace(conservative_action(state, self._profile), issued_frame=state.frame,
                                                      expires_frame=state.frame + self.macro_horizon_frames)
                        self._stale_decisions_discarded += 1
                        self._last_stale_decision_reason = "recovery waypoint is no longer legal"
                    else:
                        horizon = RECOVERY_ACTION_FRAMES if result.mode == "recovery" else self.macro_horizon_frames
                        self._latest_action = replace(result, issued_frame=state.frame,
                                                      expires_frame=state.frame + horizon, macro_horizon_frames=horizon)
                        if result.action_id.startswith("keep_trinket_"):
                            kept_id = int(result.action_id.removeprefix("keep_trinket_"))
                            self._ignored_pickup_ids.add(kept_id)
                        elif result.action_id.startswith("take_pickup_"):
                            selected_pickup = next((item for item in state.pickups if result.action_id == f"take_pickup_{item.entity_id}"), None)
                            if selected_pickup and selected_pickup.pickup_kind == "trinket" and len(state.held_trinkets) >= state.trinket_slots:
                                self._dropped_trinket_subtypes.update(state.held_trinkets)
                        selected_door = re.fullmatch(r"enter_door_(\d+)", result.action_id) if result.mode == "navigate" else None
                        if selected_door:
                            self._committed_door_slot = int(selected_door.group(1))
                            self._committed_door_room = state.layout.room_index
                    # The Jev request may have been started on the previous
                    # state tick. Never resurrect a pickup target that has
                    # already disappeared from the current observation.
                    self._clear_disappeared_pickup_action(state)
                    if self._latest_action is None:
                        # The stale target was cleared above. Keep the bridge
                        # alive and publish a valid action for this state
                        # instead of dereferencing a cleared result below.
                        self._latest_action = replace(conservative_action(state, self._profile), issued_frame=state.frame, expires_frame=state.frame + self.macro_horizon_frames)
                except Exception:
                    self._latest_action = replace(conservative_action(state, self._profile), issued_frame=state.frame, expires_frame=state.frame + self.macro_horizon_frames)
                self._future = None
                if self._future_started_at:
                    self._last_decision_latency_ms = max(0.0, (time.monotonic() - self._future_started_at) * 1000.0)
                    self._latency_samples.append(self._last_decision_latency_ms)
                    self._future_started_at = 0.0
                self._future_started_frame = -1
                self._future_provider_generation = 0
                latest_action = self._latest_action
                if latest_action is None:
                    latest_action = conservative_action(state, self._profile)
                self._history.appendleft({
                    "frame": state.frame,
                    "mode": latest_action.mode,
                    "action": latest_action.action_id,
                    "action_label": action_label(latest_action.action_id),
                    "target": latest_action.target,
                    "confidence": latest_action.confidence,
                    "source": latest_action.source,
                    "requested_provider": self._last_trace.get("requested_provider", self._active_provider_name) if self._last_trace else self._active_provider_name,
                    "model": self._last_trace.get("model", self._active_provider_model) if self._last_trace else self._active_provider_model,
                    "reason": latest_action.reason,
                })
            tracking_bomb_imminent = bool(state.geometry_features().get("nearest_tracking_bomb_imminent"))
            if tracking_bomb_imminent and (not self._latest_action or self._latest_action.mode != "evade"):
                self._latest_action = replace(conservative_action(state, self._profile), issued_frame=state.frame,
                                              expires_frame=state.frame + self.macro_horizon_frames)
                self._last_decision_frame = -10_000
            elif not state.danger_effects and self._latest_action and self._latest_action.mode == "evade":
                self._latest_action = None
                self._last_decision_frame = -10_000
            action_expired = bool(self._latest_action and self._latest_action.expires_frame >= 0 and state.frame > self._latest_action.expires_frame)
            if action_expired and not state.player_dead:
                self._latest_action = replace(
                    conservative_action(state, self._profile), issued_frame=state.frame,
                    expires_frame=state.frame + self.macro_horizon_frames,
                    macro_horizon_frames=self.macro_horizon_frames,
                )
                self._last_stale_decision_reason = "macro action expired"
            urgent_break = (
                bool(state.geometry_features().get("nearest_projectile_imminent"))
                or bool(state.geometry_features().get("nearest_tracking_bomb_imminent"))
                or state.movement_blocked
                or state.transition_phase == "entered"
            )
            # Bocha is rate-limited more aggressively than the official Jev
            # endpoint. Keep the local macro action for at least half a second
            # between Bocha requests instead of turning every game tick into a
            # remote call and receiving HTTP 429 responses.
            recovering = state.recovery_active or bool(self._latest_action and self._latest_action.mode == "recovery")
            decision_horizon = (max(self.macro_horizon_frames, 30) if self._active_provider_name in {"bocha", "systemone"}
                                else RECOVERY_ACTION_FRAMES if recovering else self.macro_horizon_frames)
            frame_due = state.frame - self._last_decision_frame >= decision_horizon
            decision_due = frame_due if recovering or self._active_provider_name in {"bocha", "systemone"} else (frame_due or urgent_break)
            if self.autopilot_enabled and not state.player_dead and self._future is None and decision_due:
                self._last_decision_at = now
                self._last_decision_frame = state.frame
                self._future_started_at = now
                self._future_started_frame = state.frame
                self._future_provider_generation = self._provider_generation
                self._future = self._executor.submit(self._decide, state, self._profile, self._provider_generation)
            action = Action("dead_wait", Vec2(), Vec2(), 0.0, "safety", "wait", "", "player is dead; waiting for automatic restart") if state.player_dead else (self._latest_action or conservative_action(state, self._profile))
            # Emergency observations trigger an immediate model request above;
            # do not replace the current model action with a local emergency
            # policy while the request is in flight.
            if state.recovery_active and self._stall_override:
                self._stall_override = None
                self._stall_override_until_frame = -1
            if self._stall_override and state.frame <= self._stall_override_until_frame:
                action = self._stall_override
            elif self._stall_override:
                if self._stall_override.mode == "navigate":
                    self._local_recovery_failures += 1
                self._stall_override = None
                self._stall_override_until_frame = -1
            movement_is_actionable = (
                self._movement_stall_count >= self._profile.movement_stall_threshold
                and action.mode in {"combat", "evade", "item", "shop", "pickup", "chest", "hazard", "bomb", "navigate", "boss_exit"}
            )
            if (
                not state.player_dead
                and
                self._stall_override is None
                and movement_is_actionable
                and state.frame - self._last_stall_penalty_frame >= self._profile.repeat_penalty_frames
            ):
                self._stall_override = repeat_action_penalty_action(state, action, self._profile, "movement")
                self._stall_override_until_frame = state.frame + self._profile.repeat_penalty_frames
                self._last_stall_penalty_frame = state.frame
                self._stall_penalty_count += 1
                self._last_stall_penalty_reason = self._stall_override.reason
                self._movement_stall_count = 0
                action = self._stall_override
            # A cleared room is where navigation and item selection happen;
            # disabling input here left the controller unable to leave spawn.
            self._effective_action = action if feedback_enabled else None
            if self._last_trace and self._last_trace.get("room_index") == state.layout.room_index:
                self._last_trace["applied"] = {"frame": state.frame, "action_id": action.action_id,
                                               "source": action.source, "move": action.move.__dict__,
                                               "waypoint": action.waypoint.__dict__ if action.waypoint else None}
            signature = (state.layout.room_index, action.action_id, action.mode, action.target)
            if feedback_enabled and signature == self._last_response_signature:
                self._repeated_action_count += 1
            else:
                self._last_response_signature = signature
                self._action_sequence += 1
                self._repeated_action_count = 0
            if action.mode == "combat" and (
                self._repeated_action_count >= self._profile.repeat_action_threshold
                or self._movement_stall_count >= self._profile.movement_stall_threshold
            ):
                self._combat_stuck = True
            elif not state.enemies:
                self._combat_stuck = False
            response = action.as_message(self.autopilot_enabled)
            response["source_room_index"] = state.layout.room_index
            response["action_sequence"] = self._action_sequence
            executed_door = re.fullmatch(r"enter_door_(\d+)", action.action_id) if action.mode == "navigate" else None
            executed_slot = int(executed_door.group(1)) if executed_door else -1
            response["door_slot"] = executed_slot
            # The live Lua layout is authoritative. The cached floor graph can
            # contain an older target for the same slot after a room descriptor
            # refresh; sending that stale target makes Lua reject every frame
            # with `target_mismatch` and leaves Isaac repeating the same move.
            response["target_room_index"] = self._target_room_for_slot(executed_slot, state) if executed_slot >= 0 else -1
            # Lua must know which unreachable hazards the local controller
            # has already exhausted; otherwise it will keep blocking every
            # door forever even after Python has moved on to navigation.
            response["ignored_hazard_ids"] = sorted(self._ignored_hazard_ids)
            response["ignored_pickup_ids"] = sorted(self._ignored_pickup_ids)
            response["unreachable_targets"] = list(self._unreachable_targets)
            response["transition_phase"] = self._transition_phase
            self._recorder.record(
                state,
                action,
                self._last_decision_latency_ms,
                max(0.0, time.monotonic() - self._last_state_at),
                {
                    "action_sequence": self._action_sequence,
                    "repeated_action_count": self._repeated_action_count,
                    "stale_actions_discarded": self._stale_actions_discarded,
                    "pickup_target_id": self._pickup_target_id,
                    "movement_stall_count": self._movement_stall_count,
                },
            )
            return response

    def _target_room_for_slot(self, slot: int, state: GameState | None = None) -> int:
        if state is not None:
            for door in state.layout.doors:
                if door.slot == slot:
                    return door.target_room_index
        for door in self._room_graph.get(self._current_room_index, ()):
            if door.slot == slot:
                return door.target_room_index
        return -1

    def _expire_door_retries(self, frame: int) -> None:
        for edge, until in list(self._door_retry_until.items()):
            live_door = next((door for door in self._last_layout.doors if edge[0] == self._last_layout.room_index
                              and door.slot == edge[1]), None)
            door_changed = live_door is not None and (
                live_door.target_room_index != edge[2]
                or (live_door.open_known and not live_door.open and not live_door.locked)
            )
            if frame < until and not door_changed:
                continue
            self._door_retry_until.pop(edge, None)
            self._door_retry_reasons.pop(edge, None)
            self._unreachable_door_edges.discard(edge)
            marker = f"door:{edge[0]}:{edge[1]}->{edge[2]}"
            self._unreachable_targets = [target for target in self._unreachable_targets if target != marker]

    def _update_navigation_stall(self, state: GameState) -> None:
        if state.move_resolution_reason in {"recovery_waypoint_reached", "timed_spike_wait"}:
            self._local_recovery_failures = 0
            self._stall_anchor = state.player.position
            self._stall_since_frame = state.frame
            self._stall_best_distance = None
            return
        action = self._effective_action or self._latest_action
        relevant = bool(action and (action.mode in {"navigate", "recovery"}
                                     or action.action_id in {"wait_for_exit", "wait_for_safety_filter", "wait_for_recovery_route"}))
        if (not relevant or not state.room_clear or state.player_dead or state.bomb_active
                or state.move_resolution_reason == "hazard_lane_control"):
            self._stall_anchor = state.player.position
            self._stall_since_frame = state.frame
            self._stall_target_slot = -1
            self._stall_best_distance = None
            return
        selected = re.fullmatch(r"enter_door_(\d+)", action.action_id) if action else None
        slot = int(selected.group(1)) if selected else -1
        door = next((item for item in state.layout.doors if item.slot == slot), None)
        if door is not None:
            distance = door_path_distance(state, door)
            if slot != self._stall_target_slot or self._stall_best_distance is None:
                self._stall_target_slot = slot
                self._stall_best_distance = distance
                self._stall_since_frame = state.frame
            elif distance < self._stall_best_distance - 8:
                self._stall_best_distance = distance
                self._stall_since_frame = state.frame
            return
        self._stall_target_slot = -1
        self._stall_best_distance = None
        if self._stall_anchor is None or self._stall_anchor.distance_to(state.player.position) >= 10:
            self._stall_anchor = state.player.position
            self._stall_since_frame = state.frame

    def _record_action_feedback(self, state: GameState) -> None:
        """Keep sparse engine results so the next Jev call can see a loop."""
        action_id = state.last_action_id
        if not action_id:
            return
        prior = self._last_action_sample
        if prior and prior["action_id"] == action_id and state.frame - prior["frame"] < 12:
            return
        goal = next((door.position for door in state.layout.doors
                     if action_id == f"enter_door_{door.slot}"), None)
        movement = (prior["position"].distance_to(state.player.position)
                    if prior and prior["room_index"] == state.layout.room_index else 0.0)
        progress = (prior["position"].distance_to(goal) - state.player.position.distance_to(goal)
                    if goal is not None and prior and prior["room_index"] == state.layout.room_index else None)
        self._recent_action_feedback.append({
            "id": action_id, "frame": state.frame,
            "elapsed_frames": state.frame - prior["frame"] if prior else 0,
            "movement_px": round(movement, 1),
            "goal_progress_px": round(progress, 1) if progress is not None else None,
            "blocked": state.movement_blocked,
            "resolution": state.move_resolution_reason,
        })
        self._last_action_sample = {"action_id": action_id, "frame": state.frame,
                                    "position": state.player.position, "room_index": state.layout.room_index}

    def _update_movement_feedback(self, state: GameState) -> None:
        """Count commands that request movement but produce no engine progress."""
        if state.move_resolution_reason in {"reverse_door_guard", "timed_spike_wait"} or state.transition_gate == "reverse_guard":
            # The Mod intentionally pauses a just-used reverse door. This is
            # not evidence that the open door is physically unreachable.
            self._movement_stall_count = 0
            return
        action = self._effective_action or self._latest_action
        if not action or action.mode not in {"combat", "evade", "item", "shop", "pickup", "chest", "hazard", "bomb", "navigate", "boss_exit", "button"}:
            self._movement_stall_count = 0
            return
        blocked = state.movement_blocked or (
            (state.resolved_move.x or state.resolved_move.y)
            and state.movement_progress < 0.5
        ) or (
            state.move_resolution_reason in {"door_input_guard", "native_input_blocked", "no_walkable_direction", "lua_safety_rewrite"}
            and state.movement_progress < 0.5
        ) or (
            state.transition_gate == "target_mismatch"
        )
        if blocked:
            self._movement_stall_count += 1
        else:
            self._movement_stall_count = 0

    def _update_pickup_progress(self, state: GameState) -> None:
        action = self._effective_action or self._latest_action
        if not action or action.mode not in {"item", "shop", "pickup", "chest"}:
            return
        match = re.search(r"_(-?\d+)$", action.action_id)
        target_id = int(match.group(1)) if match else self._pickup_target_id
        pickup = next((item for item in state.pickups if item.entity_id == target_id), None)
        if pickup is None:
            self._pickup_target_id = -1
            self._pickup_last_distance = None
            return
        distance = path_distance(state, pickup.position, pickup.grid_index)
        if target_id != self._pickup_target_id:
            self._pickup_target_id = target_id
            self._pickup_last_distance = distance
            self._pickup_last_progress_frame = state.frame
            return
        if self._pickup_last_distance is None or distance < self._pickup_last_distance - 4:
            self._pickup_last_distance = distance
            self._pickup_last_progress_frame = state.frame
        elif self._target_move_blocked(state) and state.frame - self._pickup_last_progress_frame >= self._blocked_target_limit_frames(state):
            self._mark_pickup_unreachable(target_id)
        elif state.frame - self._pickup_last_progress_frame >= self._pickup_stuck_limit_frames(state):
            self._mark_pickup_unreachable(target_id)

    def _blocked_target_limit_frames(self, state: GameState | None = None) -> int:
        """Use movement feedback to abandon a wall-bound target promptly."""
        limit = min(self._profile.pickup_stuck_frames, max(18, self._profile.movement_stall_threshold * 3))
        if state and (state.layout.is_boss or state.layout.room_type == "boss"):
            return max(240, limit)
        return limit

    def _pickup_stuck_limit_frames(self, state: GameState) -> int:
        """Boss rewards need time for repositioning before being abandoned."""
        if state.layout.is_boss or state.layout.room_type == "boss":
            return max(240, self._profile.pickup_stuck_frames)
        return self._profile.pickup_stuck_frames

    @staticmethod
    def _target_move_blocked(state: GameState) -> bool:
        return state.movement_blocked or (
            state.move_resolution_reason != "hazard_lane_control"
            and (state.requested_move.x or state.requested_move.y)
            and state.movement_progress < 0.5
        ) or (
            state.move_resolution_reason in {"door_input_guard", "native_input_blocked", "no_walkable_direction", "lua_safety_rewrite"}
            and state.movement_progress < 0.5
        )

    def _mark_pickup_unreachable(self, target_id: int) -> None:
        if target_id in self._ignored_pickup_ids:
            return
        self._ignored_pickup_ids.add(target_id)
        self._unreachable_targets.append(f"pickup:{target_id}")
        self._stale_actions_discarded += 1
        self._pickup_target_id = -1
        self._pickup_last_distance = None
        self._clear_unreachable_action({"item", "shop", "pickup", "chest"})

    def _clear_disappeared_pickup_action(self, state: GameState) -> None:
        """Drop stale item navigation as soon as its entity is gone."""
        actions = [self._latest_action, self._effective_action, self._stall_override]
        action = next((item for item in actions if item and item.mode in {"item", "shop", "pickup", "chest"}), None)
        if action is None:
            return
        match = re.search(r"_(\-?\d+)$", action.action_id)
        target_id = int(match.group(1)) if match else -1
        if target_id < 0 or any(item.entity_id == target_id for item in state.pickups):
            return
        self._latest_action = None
        self._effective_action = None
        self._stall_override = None
        self._stall_override_until_frame = -1
        self._pickup_target_id = -1
        self._pickup_last_distance = None
        self._last_response_signature = None
        self._repeated_action_count = 0
        self._stale_actions_discarded += 1

    def _update_hazard_progress(self, state: GameState) -> None:
        action = self._effective_action or self._latest_action
        if not action or action.mode not in {"hazard", "bomb", "bomb_wall", "tnt"}:
            return
        match = re.search(r"_(-?\d+)$", action.action_id)
        target_id = int(match.group(1)) if match else -1
        wall = next((item for item in state.layout.bomb_walls if item.slot == target_id), None) if action.mode == "bomb_wall" else None
        if action.mode == "bomb_wall":
            target_id = -200000 - target_id
        hazard = next((item for item in state.hazards if item.entity_id == target_id), None)
        tnt = next((item for item in state.layout.grid_events if item.entity_id == target_id and item.kind == "tnt" and item.active), None)
        if hazard is None and tnt is None and wall is None:
            self._hazard_target_id = -1
            self._hazard_last_distance = None
            return
        distance = (hazard.position if hazard else tnt.position if tnt else wall.site).distance_to(state.player.position)
        hit_points = hazard.hit_points if hazard else 0.0
        animation = hazard.animation if hazard else ""
        previous_animation = self._hazard_animation_by_target.get(target_id)
        self._hazard_animation_by_target[target_id] = animation
        # Switching between adjacent targets is not progress. Keep each
        # target's best distance and timer across those decision changes.
        previous = self._hazard_progress_by_target.get(target_id)
        self._hazard_target_id = target_id
        if previous is None:
            previous = (distance, hit_points, state.frame)
        self._hazard_last_distance, self._hazard_last_hp, self._hazard_last_progress_frame = previous
        if ((hazard is not None and hit_points < self._hazard_last_hp)
                or distance < self._hazard_last_distance - 4
                or (previous_animation is not None and animation != previous_animation)):
            self._hazard_last_distance = distance
            self._hazard_last_hp = hit_points
            self._hazard_last_progress_frame = state.frame
        self._hazard_progress_by_target[target_id] = (
            self._hazard_last_distance, self._hazard_last_hp, self._hazard_last_progress_frame)
        if self._target_move_blocked(state) and state.frame - self._hazard_last_progress_frame >= self._blocked_target_limit_frames():
            self._mark_hazard_unreachable(target_id, state)
        elif state.frame - self._hazard_last_progress_frame >= self._profile.pickup_stuck_frames:
            self._mark_hazard_unreachable(target_id, state)

    def _mark_hazard_unreachable(self, target_id: int, state: GameState | None = None) -> None:
        if target_id in self._ignored_hazard_ids:
            return
        # A destructible obstacle that makes no progress is unreachable from
        # the current firing lane; mark it and choose an exit.
        self._ignored_hazard_ids.add(target_id)
        if (state is not None and not state.room_clear
                and any(e.kind == "button" and e.active and not e.triggered for e in state.layout.grid_events)
                and any(h.entity_id == target_id and h.kind in {"poop", "red_poop", "fire"} for h in state.hazards)):
            # A moving trap can temporarily block a mandatory obstacle's lane.
            # Try another target, then retry after the trap's phase changes.
            self._hazard_retry_after[target_id] = state.frame + 180
        self._unreachable_targets.append(f"hazard:{target_id}")
        self._stale_actions_discarded += 1
        self._hazard_target_id = -1
        self._hazard_last_distance = None
        self._clear_unreachable_action({"hazard", "bomb", "bomb_wall", "tnt"})

    def _clear_unreachable_action(self, modes: set[str]) -> None:
        """Drop target actions and safety overrides after marking them unreachable."""
        if self._latest_action and self._latest_action.mode in modes:
            self._latest_action = None
        if self._effective_action and self._effective_action.mode in modes:
            self._effective_action = None
        if self._stall_override and self._stall_override.mode in modes:
            self._stall_override = None
            self._stall_override_until_frame = -1
        self._movement_stall_count = 0
        self._last_response_signature = None
        self._repeated_action_count = 0

    def _abandon_blocked_door(self, state: GameState) -> None:
        """Temporarily avoid a genuinely blocked threshold when another exit exists."""
        if state.move_resolution_reason in {"reverse_door_guard", "timed_spike_wait"} or state.transition_gate == "reverse_guard":
            return
        action = self._effective_action or self._latest_action
        if not action or action.mode != "navigate" or (
            self._movement_stall_count < self._profile.movement_stall_threshold
            and state.transition_gate != "target_mismatch"
        ):
            return
        match = re.search(r"^enter_door_(\d+)$", action.action_id)
        if not match:
            return
        slot = int(match.group(1))
        door = next((item for item in state.layout.doors if item.slot == slot), None)
        if door is None or door.target_room_index < 0:
            return
        feedback = list(self._recent_action_feedback)
        progress_values = [item.get("goal_progress_px") for item in feedback
                           if isinstance(item.get("goal_progress_px"), (int, float))]
        recent_ids = [str(item.get("id", "")) for item in feedback[-5:]]
        oscillating = (
            len(progress_values) >= 3
            and sum(value < -4.0 for value in progress_values) >= 2
            and any(value > 4.0 for value in progress_values)
            and len(set(recent_ids[-4:])) <= 2
        )
        # Aligning with a door is not an attempt to cross its threshold.
        # In the observed room-87 failure Lua rewrote a downward alignment
        # request into a blocked leftward step; that is route feedback, not
        # evidence that the only open door is permanently inaccessible.
        if state.move_resolution_reason in {"lua_safety_rewrite", "no_walkable_direction"}:
            return
        perpendicular = (abs(state.player.position.y - door.position.y) if slot in {0, 2, 4, 6}
                         else abs(state.player.position.x - door.position.x))
        # A path that alternates between positive and negative progress is a
        # navigation oscillation. Treat it as a failed edge even when the
        # latest sample is still a few pixels from the threshold.
        if not oscillating and (perpendicular > 12 or state.transition_door_distance > 55):
            return
        alternatives = [item for item in state.layout.doors
                        if item.slot != slot and door_is_usable(item, state)]
        if not alternatives:
            return
        edge = (state.layout.room_index, slot, door.target_room_index)
        if edge in self._unreachable_door_edges:
            return
        self._unreachable_door_edges.add(edge)
        self._door_retry_until[edge] = state.frame + DOOR_RETRY_FRAMES
        self._door_retry_reasons[edge] = f"{state.move_resolution_reason or 'blocked'} at aligned door threshold"
        if self._committed_door_room == state.layout.room_index and self._committed_door_slot == slot:
            self._committed_door_slot = -1
            self._committed_door_room = -1
        self._unreachable_targets.append(f"door:{state.layout.room_index}:{slot}->{door.target_room_index}")
        self._stale_actions_discarded += 1
        self._clear_unreachable_action({"navigate"})

    def _plan_next_door(self, state: GameState | None = None) -> tuple[int, str]:
        """Choose one deliberate floor-graph step; never ask Jev to backtrack blindly."""
        doors = self._room_graph.get(self._current_room_index, ())
        def is_usable(door: Any) -> bool:
            if not door_is_usable(door, state):
                return False
            if (state is not None and self._current_room_index == state.layout.room_index
                    and door_path_distance(state, door) == float("inf")
                    and state.player.position.distance_to(door.position) > 70):
                return False
            if (self._current_room_index, door.slot, door.target_room_index) in self._unreachable_door_edges:
                return False
            return True

        usable = [door for door in doors if is_usable(door)]
        # A key acquired on another branch can unlock a previously observed
        # treasure room. Visit that upgrade before taking the boss shortcut.
        if state is not None and state.keys > 0 and not (0 < state.player.hit_points <= 3) and state.red_hearts >= state.max_hearts:
            queue = [(self._current_room_index, -1)]
            seen = {self._current_room_index}
            while queue:
                room, first = queue.pop(0)
                edges = usable if room == self._current_room_index else self._room_graph.get(room, ())
                for edge in edges:
                    target = edge.target_room_index
                    if not door_is_usable(edge, state) or (room, edge.slot, target) in self._unreachable_door_edges:
                        continue
                    slot = edge.slot if first < 0 else first
                    if edge.target_room_type == "treasure" and target not in self._visited_rooms:
                        return slot, ("known treasure room" if room == self._current_room_index
                                      else "collect observed treasure upgrade before boss")
                    if target not in seen and self._room_intel.get(target, {}).get("clear", edge.target_clear):
                        seen.add(target)
                        queue.append((target, slot))
        # Return through cleared rooms to health actually seen on this floor.
        if state is not None and (0 < state.player.hit_points <= 3 or state.max_hearts - state.red_hearts >= 2):
            healing_kinds = {"soul_heart", "half_soul_heart", "black_heart"}
            if state.red_hearts < state.max_hearts:
                healing_kinds |= {"heart", "red_heart", "red_half_heart", "red_double_heart", "scared_heart", "blended_heart"}
            targets = {room for room, intel in self._room_intel.items()
                if room != self._current_room_index and intel.get("clear")
                and intel.get("room_type") != "shop"
                and healing_kinds.intersection(intel.get("reachable_rewards", intel.get("rewards", [])))}
            queue = [(self._current_room_index, -1)]
            seen = {self._current_room_index}
            while queue and targets:
                room, first = queue.pop(0)
                edges = usable if room == self._current_room_index else self._room_graph.get(room, ())
                for edge in edges:
                    target = edge.target_room_index
                    if target in seen or not door_is_usable(edge, state):
                        continue
                    if (room, edge.slot, target) in self._unreachable_door_edges:
                        continue
                    if not edge.target_clear and not self._room_intel.get(target, {}).get("clear"):
                        continue
                    slot = edge.slot if first < 0 else first
                    if target in targets:
                        return slot, "return to observed health pickup"
                    seen.add(target)
                    queue.append((target, slot))
        # A boss discovered early must not silently skip the floor's upgrade.
        # Search only ordinary branches while healthy and holding a key.
        if (state is not None and 1 <= state.stage <= 6 and state.player.hit_points >= 6
                and state.keys > 0 and not any(intel.get("room_type") == "treasure"
                    for intel in self._room_intel.values())):
            queue = [(self._current_room_index, -1)]
            seen = {self._current_room_index}
            while queue:
                room, first = queue.pop(0)
                edges = usable if room == self._current_room_index else self._room_graph.get(room, ())
                for edge in edges:
                    target = edge.target_room_index
                    if (not door_is_usable(edge, state) or edge.target_is_boss
                            or (room, edge.slot, target) in self._unreachable_door_edges):
                        continue
                    slot = edge.slot if first < 0 else first
                    if target not in self._visited_rooms and edge.target_room_type in {"default", "unknown", "treasure"}:
                        return slot, "search treasure upgrade before boss"
                    if target not in seen and self._room_intel.get(target, {}).get("clear", edge.target_clear):
                        seen.add(target)
                        queue.append((target, slot))
        unexplored = [door for door in usable if door.target_room_index not in self._visited_rooms]
        opened_secret = newly_opened_secret_door(state) if state is not None else None
        if opened_secret and any(door.slot == opened_secret.slot for door in unexplored):
            self._committed_door_slot = -1
            self._committed_door_room = -1
            return opened_secret.slot, "newly bombed secret room"
        treasure = [door for door in unexplored if door.target_room_type == "treasure"]
        # A newly affordable treasure room outranks an earlier commitment to
        # the entry door or a lower-value unexplored branch.
        if treasure and self._committed_door_slot not in {door.slot for door in treasure}:
            self._committed_door_slot = -1
            self._committed_door_room = -1
            return min(treasure, key=lambda door: door.slot).slot, "known treasure room"
        if self._committed_door_room == self._current_room_index:
            committed = next((door for door in doors if door.slot == self._committed_door_slot and is_usable(door)), None)
            if committed is not None and committed.target_room_index not in self._visited_rooms:
                return committed.slot, "committed navigation choice"
            self._committed_door_slot = -1
            self._committed_door_room = -1

        # Treasure rooms are the highest-value optional branch. Keep this
        # before the boss shortcut: the generic score already ranks treasure
        # highly, but the old unconditional boss return made that score
        # unreachable whenever both doors were present.
        if treasure:
            return min(treasure, key=lambda door: door.slot).slot, "known treasure room"

        boss = [door for door in unexplored if door.target_is_boss]
        if boss:
            return min(boss, key=lambda door: door.slot).slot, "known boss room"
        if unexplored:
            risky = {"curse", "sacrifice", "challenge"}
            safe = [door for door in unexplored if door.target_room_type not in risky]
            candidates = safe or unexplored
            def door_score(door: Any) -> tuple[int, int, int]:
                priority = {
                    "boss": 100, "treasure": 90, "library": 65, "shop": 60,
                    "secret": 55, "super_secret": 52, "default": 50,
                    "challenge": 20, "sacrifice": 15, "curse": 10,
                }.get(door.target_room_type, 35)
                if door.target_room_type == "shop" and state is not None and state.coins < 5:
                    priority -= 20
                return (-priority, 0 if door.target_clear else 1, door.slot)
            selected = min(candidates, key=door_score)
            reason = f"unexplored {selected.target_room_type} room"
            if selected.target_room_type in risky and safe:
                reason = "safe unexplored room before risk room"
            return selected.slot, reason

        # No local unexplored door: route through known graph to the nearest
        # room that still has one, rather than oscillating over one edge.
        frontier_rooms = {
            room for room, edges in self._room_graph.items()
            if any(door_is_usable(edge, state) and edge.target_room_index not in self._visited_rooms and (room, edge.slot, edge.target_room_index) not in self._unreachable_door_edges for edge in edges)
        }
        queue = [self._current_room_index]
        first_slot: dict[int, int] = {self._current_room_index: -1}
        while queue:
            room = queue.pop(0)
            if room != self._current_room_index and room in frontier_rooms:
                return first_slot[room], "route to unexplored branch"
            for door in self._room_graph.get(room, ()):
                target = door.target_room_index
                hidden = door.target_room_type in {"secret", "super_secret"}
                edge = (room, door.slot, target)
                if not door_is_usable(door, state) or edge in self._unreachable_door_edges or target in first_slot:
                    continue
                first_slot[target] = door.slot if room == self._current_room_index else first_slot[room]
                queue.append(target)

        # All doors being visited does not mean the floor is complete. Route
        # back to a known boss room so its trapdoor can advance the run.
        known_bosses = {room for room, intel in self._room_intel.items() if intel.get("room_type") == "boss"}
        if known_bosses and self._current_room_index not in known_bosses:
            queue = [self._current_room_index]
            first_slot = {self._current_room_index: -1}
            while queue:
                room = queue.pop(0)
                if room in known_bosses and room != self._current_room_index:
                    return first_slot[room], "return to known boss exit"
                for door in self._room_graph.get(room, ()):
                    target = door.target_room_index
                    if target in first_slot or not door_is_usable(door, state):
                        continue
                    if (room, door.slot, target) in self._unreachable_door_edges:
                        continue
                    first_slot[target] = door.slot if room == self._current_room_index else first_slot[room]
                    queue.append(target)

        # A dead-end can have no known frontier yet still be recoverable by
        # returning through the entry door. Do this only after frontier search
        # and never retry an edge already classified as unreachable.
        if self._previous_room_index >= 0:
            backtrack = next(
                (
                    door for door in doors
                    if door.target_room_index == self._previous_room_index
                    and door_is_usable(door, state)
                    and (self._current_room_index, door.target_room_index) not in self._backtrack_edges
                    and (self._current_room_index, door.slot, door.target_room_index) not in self._unreachable_door_edges
                ),
                None,
            )
            if backtrack is not None:
                # Consume only after an actual transition, not on every state tick.
                if (backtrack.target_room_index, self._current_room_index) in self._backtrack_edges:
                    alternatives = [door for door in usable if door.slot != backtrack.slot]
                    if alternatives:
                        selected = min(alternatives, key=lambda door: (door.target_room_type in {"curse", "sacrifice", "challenge"}, self._edge_visit_counts.get((self._current_room_index, door.target_room_index), 0), door.slot))
                        return selected.slot, "search known rooms for progression"
                return backtrack.slot, "backtrack to entry room"
        if usable:
            selected = min(usable, key=lambda door: (door.target_room_type in {"curse", "sacrifice", "challenge"}, self._edge_visit_counts.get((self._current_room_index, door.target_room_index), 0), door.slot))
            return selected.slot, "search known rooms for progression"
        return -1, "no usable exit is currently known"

    def _record_room_intel(self, state: GameState) -> None:
        """Keep only observations the Lua API has actually revealed this floor."""
        room_index = state.layout.room_index
        if room_index < 0:
            return
        rewards = []
        reachable_rewards = []
        for pickup in state.pickups:
            if pickup.entity_id in state.ignored_pickup_ids:
                continue
            reward = None
            if pickup.is_collectible:
                reward = f"item: {pickup.name} (quality {pickup.quality}, price {pickup.price})"
            elif pickup.pickup_kind in {"key", "coin", "bomb", "heart", "red_heart", "red_half_heart", "red_double_heart", "soul_heart", "half_soul_heart", "black_heart", "eternal_heart", "golden_heart", "bone_heart", "scared_heart", "blended_heart", "rotten_heart", "card", "pill", "trinket", "grab_bag"}:
                reward = pickup.pickup_kind
            if reward is not None:
                rewards.append(reward)
                if path_distance(state,pickup.position,pickup.grid_index) < float("inf"):
                    reachable_rewards.append(reward)
        self._room_intel[room_index] = {
            "room_index": room_index,
            "clear": state.room_clear,
            "room_type": state.layout.room_type,
            "hazards": [{"id": hazard.entity_id, "kind": hazard.kind, "requires_bomb": hazard.requires_bomb} for hazard in state.hazards],
            "rewards": rewards,
            "reachable_rewards": reachable_rewards,
            "doors": [
                {"slot": door.slot, "target_room_index": door.target_room_index, "room_type": door.target_room_type, "boss": door.target_is_boss}
                for door in state.layout.doors
            ],
        }

    def note_connection(self) -> None:
        with self._lock:
            self._connections += 1

    def note_received_bytes(self, count: int) -> None:
        with self._lock:
            self._received_bytes += count

    def note_bridge_error(self, error: Exception) -> None:
        with self._lock:
            self._bridge_error = f"{type(error).__name__}: {error}"[:160]

    def _decide(self, state: GameState, profile: PolicyProfile | None = None, provider_generation: int | None = None) -> Action:
        candidate_set = build_candidate_set(state, profile)
        route = policy_router(state, candidate_set)
        config = self._provider_config
        provider = create_provider(self._active_provider_name, config, profile, self._provider_store.environ)
        recovery_remote_cooldown = bool(
            state.recovery_active and len(candidate_set.admissible_candidates) >= 2
            and state.frame - self._recovery_last_remote_frame < RECOVERY_REMOTE_INTERVAL_FRAMES
            and self._active_provider_name != "local"
        )
        if recovery_remote_cooldown:
            local = create_provider("local", config, profile, self._provider_store.environ)
            decision = replace(local.choose(state, candidate_set), status="local",
                               fallback_reason="recovery_remote_cooldown")
        else:
            decision: ProviderDecision = (
                provider.choose_composed(state, candidate_set)
                if isinstance(provider, JevProvider) else provider.choose(state, candidate_set)
            )
        action = decision.action
        stale_result = provider_generation is not None and provider_generation != self._provider_generation
        trace = {
            "schema_version": "decision-v3",
            "run_id": self._run_id,
            "seed": getattr(state, "start_seed", None),
            "frame": state.frame,
            "room_index": state.layout.room_index,
            "provider": decision.provider,
            "requested_provider": self._active_provider_name,
            "model": decision.model,
            "status": decision.status,
            "policy": decision.policy or route,
            "input": state.compact(),
            "output": {"action": decision.selected_choice or action.action_id, "action_label": action_label(action.action_id)},
            "probabilities": decision.probabilities,
            "judgments": decision.judgments,
            "composition_schema": decision.schema_version,
            "confidence": decision.confidence,
            "top1": decision.top1_probability,
            "top2": decision.top2_probability,
            "margin": decision.margin,
            "entropy": decision.entropy,
            "latency_ms": decision.client_latency_ms,
            "client_latency_ms": decision.client_latency_ms,
            "server_latency_ms": decision.server_latency_ms,
            "remote_latency_ms": decision.client_latency_ms if decision.provider in {"jev", "bocha", "systemone"} else None,
            "request_bytes": decision.request_bytes,
            "estimated_input_tokens": decision.estimated_input_tokens,
            "candidate_set": candidate_set.as_dict(),
            "fallback": decision.fallback,
            "fallback_reason": decision.fallback_reason,
            "timeout": decision.timed_out,
            "error": decision.error,
            "stale_result": stale_result,
            "policy_fingerprint": hashlib.sha1(inspect.getsource(local_policy_action).encode("utf-8")).hexdigest()[:12],
            "recovery": {"active": state.recovery_active, "reason": state.recovery_reason,
                         "stall_frames": state.stall_frames, "target_door_slot": state.recovery_target_door_slot,
                         "remote_cooldown": recovery_remote_cooldown},
        }
        shadow_future: Future[ProviderDecision] | None = None
        if config.shadow_enabled and not state.recovery_active and config.shadow_provider != decision.provider and route in {"combat", "loot", "navigation"}:
            if self._shadow_future and not self._shadow_future.done():
                self._shadow_skipped_busy += 1
                trace["shadow_skipped_busy"] = True
            else:
                shadow_provider_name = config.shadow_provider
                shadow_provider = create_provider(shadow_provider_name, config, profile, self._provider_store.environ)
                self._shadow_provider_name = shadow_provider_name
                self._shadow_future = self._shadow_executor.submit(shadow_provider.choose, state, candidate_set)
                shadow_future = self._shadow_future
                trace["shadow_provider"] = shadow_provider_name
        trace["role_action"] = action_label(action.action_id)
        trace["action"] = action.action_id
        trace["source"] = action.source
        trace["execution"] = {
            "action_id": action.action_id,
            "mode": action.mode,
            "source": action.source,
            "execution_source": action.source,
            "provider_fallback": decision.fallback,
            "move": action.move.__dict__,
            "shoot": action.shoot.__dict__,
            "confidence": action.confidence,
        }
        trace["policy"] = route
        trace["policy_route"] = route
        remote_called = decision.provider in {"jev", "bocha", "systemone"} and decision.status not in {"local", "fallback_not_remote"} and decision.request_bytes > 0
        trace["remote_call"] = remote_called
        trace["phase"] = trace.get("candidate_set", {}).get("phase", "unknown")
        trace["state_age_seconds"] = max(0.0, time.monotonic() - self._last_state_at)
        trace["action_age_frames"] = state.action_age_frames
        trace["outcome"] = {
            "hp_before": state.player.hit_points,
            "hp_delta": 0.0,
            "room_clear": state.room_clear,
            "movement_progress": state.movement_progress,
        }
        trace["recorded_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        with self._lock:
            if remote_called:
                self._remote_call_count += 1
                if state.recovery_active:
                    self._recovery_last_remote_frame = state.frame
            if action.source not in {"jev"}:
                self._local_decision_count += 1
            self._last_policy = decision.policy or route
            self._last_request_bytes = int(trace.get("request_bytes", 0) or 0)
            self._last_state_bytes = int(trace.get("state_bytes", 0) or 0)
            self._last_estimated_input_tokens = int(trace.get("estimated_input_tokens", 0) or 0)
            self._last_remote_latency_ms = float(trace["remote_latency_ms"]) if isinstance(trace.get("remote_latency_ms"), (int, float)) else None
            if self._last_remote_latency_ms is not None:
                self._remote_latency_samples.append(self._last_remote_latency_ms)
            self._last_fallback_reason = str(trace.get("fallback_reason")) if trace.get("fallback_reason") else None
        trace_id = self._trace_recorder.record(trace)
        trace["trace_id"] = trace_id
        if shadow_future is not None:
            executed_action = action.action_id
            run_id = self._run_id
            generation = self._provider_generation

            def record_shadow(future: Future[ProviderDecision]) -> None:
                try:
                    shadow = future.result()
                    stale = generation != self._provider_generation or run_id != self._run_id
                    self._trace_recorder.record({
                        "type": "shadow",
                        "schema_version": "decision-v3",
                        "parent_trace_id": trace_id,
                        "run_id": run_id,
                        "seed": getattr(state, "start_seed", None),
                        "provider": shadow.provider,
                        "model": shadow.model,
                        "selected_action": shadow.selected_choice,
                        "executed_action": executed_action,
                        "agreement": shadow.selected_choice == executed_action,
                        "outcome_eligible": shadow.selected_choice == executed_action and not stale,
                        "stale_result": stale,
                        "probabilities": shadow.probabilities,
                        "confidence": shadow.confidence,
                        "top1": shadow.top1_probability,
                        "top2": shadow.top2_probability,
                        "margin": shadow.margin,
                        "entropy": shadow.entropy,
                        "client_latency_ms": shadow.client_latency_ms,
                        "server_latency_ms": shadow.server_latency_ms,
                        "fallback": shadow.fallback,
                        "fallback_reason": shadow.fallback_reason,
                        "timeout": shadow.timed_out,
                    })
                except Exception as error:
                    self._trace_recorder.record({
                        "type": "shadow", "schema_version": "decision-v3", "parent_trace_id": trace_id,
                        "run_id": run_id, "provider": self._shadow_provider_name,
                        "status": "error", "error": f"{type(error).__name__}: {error}"[:300],
                    })

            shadow_future.add_done_callback(record_shadow)
        with self._lock:
            self._last_trace = trace
            self._last_trace_id = trace_id
            self._pending_trace_outcomes.append({
                "trace_id": trace_id,
                "issued_frame": state.frame,
                "hp": state.player.hit_points,
                "room_index": state.layout.room_index,
                "position": state.player.position,
                "action_id": action.action_id,
                "action_mode": action.mode,
            })
            self._debug_history.appendleft(trace)
        return action

    def _update_trace_outcomes(self, state: GameState) -> None:
        """Write 6/12/30-frame outcome snapshots without blocking input."""
        with self._lock:
            for damage in state.damage_events:
                if damage.event_id in self._damage_attribution:
                    continue
                eligible = [
                    item for item in self._pending_trace_outcomes
                    if int(item["issued_frame"]) <= damage.frame
                    and int(item["room_index"]) == state.layout.room_index
                ]
                if eligible:
                    owner = max(eligible, key=lambda item: int(item["issued_frame"]))
                    self._damage_attribution[damage.event_id] = str(owner["trace_id"])
            remaining: list[dict[str, Any]] = []
            for pending in self._pending_trace_outcomes:
                age = state.frame - int(pending["issued_frame"])
                for horizon in (6, 12, 30):
                    if age < horizon or pending.get(f"done_{horizon}"):
                        continue
                    start = pending["position"]
                    assigned_damage = [
                        item for item in state.damage_events
                        if self._damage_attribution.get(item.event_id) == str(pending["trace_id"])
                    ]
                    damaged = bool(assigned_damage) or (not state.damage_events and state.player.hit_points < pending["hp"])
                    outcome = {
                        "action_id": pending["action_id"],
                        "hp_before": pending["hp"],
                        "hp_after": state.player.hit_points,
                        "hp_delta": round(-sum(item.amount for item in assigned_damage), 2) if assigned_damage else round(state.player.hit_points - pending["hp"], 2),
                        "damaged": damaged,
                        "damage_event_ids": [item.event_id for item in assigned_damage],
                        "room_changed": state.layout.room_index != pending["room_index"],
                        "movement_distance": round(state.player.position.distance_to(start), 2),
                        "movement_progress": round(state.movement_progress, 2),
                        "room_clear": state.room_clear,
                        "navigation_stuck": pending["action_mode"] in {"navigate", "boss_exit"} and state.movement_blocked,
                        "combat_exposed": pending["action_mode"] == "combat" and damaged,
                        "projectile_hit": any(item.source_type == 9 for item in assigned_damage) or (not state.damage_events and damaged and bool(state.projectiles)),
                        "contact_hit": any(item.source_type != 9 for item in assigned_damage),
                    }
                    target_id = str(pending["action_id"]).rsplit("_", 1)[-1]
                    if pending["action_mode"] in {"item", "shop", "pickup", "chest", "hazard", "boss_exit"} and target_id.lstrip("-").isdigit():
                        visible_ids = {str(item.entity_id) for item in state.pickups} | {str(item.entity_id) for item in state.hazards}
                        outcome["target_disappeared"] = target_id not in visible_ids
                    self._trace_recorder.record_outcome(str(pending["trace_id"]), horizon, outcome)
                    for trace in self._debug_history:
                        if trace.get("trace_id") == pending["trace_id"]:
                            trace.setdefault("follow_up_outcomes", {})[str(horizon)] = {
                                "movement_distance": outcome["movement_distance"],
                                "room_changed": outcome["room_changed"],
                                "damaged": outcome["damaged"],
                            }
                            break
                    pending[f"done_{horizon}"] = True
                if age < 30:
                    remaining.append(pending)
            self._pending_trace_outcomes = remaining

    @staticmethod
    def _percentile(values: deque[float], percentile: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
        return ordered[index]

    def status(self, compact: bool = False) -> dict[str, Any]:
        with self._lock:
            if compact:
                state = self._latest_state
                action = self._latest_action
                return {
                    "mod_version": state.mod_version if state else "not_connected",
                    "autopilot_enabled": self.autopilot_enabled,
                    "game_result": self._game_result,
                    "run_seed": self._run_seed,
                    "latest_frame": state.frame if state else None,
                    "latest_action": action.action_id if action else None,
                    "latest_reason": action.reason if action else None,
                    "latest_source": action.source if action else None,
                    "latest_move": action.move.__dict__ if action else None,
                    "bridge_error": self._bridge_error,
                    "remote_call_count": self._remote_call_count,
                    "state_age_seconds": max(0.0, time.monotonic() - self._last_state_at) if self._last_state_at else None,
                    "latest_state": {
                        "room_clear": state.room_clear,
                        "player_dead": state.player_dead,
                        "restart_phase": state.restart_phase,
                        "restart_count": state.restart_count,
                        "restart_error": state.restart_error,
                        "room_index": state.layout.room_index,
                        "room_type": state.layout.room_type,
                        "player_hp": state.player.hit_points,
                        "player_position": state.player.position.__dict__,
                        "combat_stuck": self._combat_stuck,
                        "movement_blocked": state.movement_blocked,
                        "move_resolution_reason": state.move_resolution_reason,
                        "safe_move_directions": state.safe_move_directions,
                        "planned_goal": self._planned_goal,
                        "visited_rooms": sorted(self._visited_rooms),
                    } if state else None,
                }
            rules = decision_rules()
            rules["source_revisions"].update({
                "Controller.receive_state": hashlib.sha1(inspect.getsource(Controller.receive_state).encode("utf-8")).hexdigest()[:12],
                "Controller._plan_next_door": hashlib.sha1(inspect.getsource(Controller._plan_next_door).encode("utf-8")).hexdigest()[:12],
            })
            return {
                "controller_version": "2026-09-24-v19",
                "mod_version": self._latest_state.mod_version if self._latest_state else "not_connected",
                "autopilot_enabled": self.autopilot_enabled,
                "game_result": self._game_result,
                "decision_hz": self.decision_hz,
                "macro_horizon_frames": self.macro_horizon_frames,
                "macro_remaining_frames": max(0, self._latest_action.expires_frame - self._latest_state.frame) if self._latest_action and self._latest_state and self._latest_action.expires_frame >= 0 else 0,
                "latest_frame": self._latest_state.frame if self._latest_state else None,
                "latest_action": self._latest_action.action_id if self._latest_action else None,
                "latest_mode": self._latest_action.mode if self._latest_action else None,
                "latest_target": self._latest_action.target if self._latest_action else None,
                "latest_reason": self._latest_action.reason if self._latest_action else None,
                "latest_confidence": self._latest_action.confidence if self._latest_action else None,
                "latest_source": self._latest_action.source if self._latest_action else None,
                "latest_move": self._latest_action.move.__dict__ if self._latest_action else None,
                "latest_shoot": self._latest_action.shoot.__dict__ if self._latest_action else None,
                "latest_issued_frame": self._latest_action.issued_frame if self._latest_action else None,
                "latest_expires_frame": self._latest_action.expires_frame if self._latest_action else None,
                "decision_pending": bool(self._future and not self._future.done()),
                "recent_decisions": list(self._history),
                "debug_logs": list(self._debug_history),
                "latest_debug_recorded_at": self._debug_history[0].get("recorded_at") if self._debug_history else None,
                "latest_debug_frame": self._debug_history[0].get("frame") if self._debug_history else None,
                "latest_trace_id": self._last_trace_id,
                "latest_candidate_set": self._last_trace.get("candidate_set") if self._last_trace else None,
                "latest_probabilities": self._last_trace.get("probabilities", {}) if self._last_trace else {},
                "decision_rules": rules,
                "bridge_connections": self._connections,
                "bridge_received_bytes": self._received_bytes,
                "bridge_received_states": self._received_states,
                "bridge_error": self._bridge_error,
                "lua_fired_tears": self._latest_lua_fired_tears,
                "lua_fire_error": self._latest_lua_fire_error,
                "effective_action": self._effective_action.action_id if self._effective_action else None,
                "effective_mode": self._effective_action.mode if self._effective_action else None,
                "effective_source": self._effective_action.source if self._effective_action else None,
                "effective_reason": self._effective_action.reason if self._effective_action else None,
                "action_sequence": self._action_sequence,
                "stale_actions_discarded": self._stale_actions_discarded,
                "stale_decisions_discarded": self._stale_decisions_discarded,
                "last_stale_decision_reason": self._last_stale_decision_reason,
                "repeated_action_count": self._repeated_action_count,
                "movement_stall_count": self._movement_stall_count,
                "stall_frames": max(0, self._latest_state.frame - self._stall_since_frame) if self._latest_state else 0,
                "local_recovery_failures": self._local_recovery_failures,
                "recovery_active": self._latest_state.recovery_active if self._latest_state else False,
                "recovery_reason": self._recovery_reason,
                "door_retry_cooldowns": [
                    {"room_index": edge[0], "slot": edge[1], "target_room_index": edge[2],
                     "frames_remaining": max(0, until - self._latest_state.frame) if self._latest_state else 0,
                     "reason": self._door_retry_reasons.get(edge, "")}
                    for edge, until in sorted(self._door_retry_until.items())
                ],
                "stall_penalty_count": self._stall_penalty_count,
                "stall_penalty_active": bool(self._stall_override),
                "last_stall_penalty_reason": self._last_stall_penalty_reason,
                "transition_phase": self._transition_phase,
                "transition_attempt": self._transition_attempt,
                "transition_error": self._transition_error,
                "unreachable_targets": list(self._unreachable_targets),
                "lua_transition_source_room": self._lua_transition_source_room,
                "lua_transition_target_room": self._lua_transition_target_room,
                "lua_room_entry_age_frames": self._lua_room_entry_age_frames,
                "lua_backtrack_guard_active": self._lua_backtrack_guard_active,
                "state_age_seconds": max(0.0, time.monotonic() - self._last_state_at) if self._last_state_at else None,
                "last_decision_latency_ms": round(self._last_decision_latency_ms, 2) if self._last_decision_latency_ms is not None else None,
                "average_decision_latency_ms": round(sum(self._latency_samples) / len(self._latency_samples), 2) if self._latency_samples else None,
                "p95_decision_latency_ms": round(self._percentile(self._latency_samples, 0.95), 2) if self._percentile(self._latency_samples, 0.95) is not None else None,
                "remote_call_count": self._remote_call_count,
                "local_decision_count": self._local_decision_count,
                "policy": self._last_policy,
                "request_bytes": self._last_request_bytes,
                "state_bytes": self._last_state_bytes,
                "estimated_input_tokens": self._last_estimated_input_tokens,
                "remote_latency_ms": round(self._last_remote_latency_ms, 2) if self._last_remote_latency_ms is not None else None,
                "remote_latency_p95_ms": round(self._percentile(self._remote_latency_samples, 0.95), 2) if self._percentile(self._remote_latency_samples, 0.95) is not None else None,
                "fallback_reason": self._last_fallback_reason,
                "provider": self.provider_config(),
                "active_provider_name": self._active_provider_name,
                "active_provider_model": self._active_provider_model,
                "run_id": self._run_id,
                "run_seed": self._run_seed,
                "provider_generation": self._provider_generation,
                "shadow_pending": bool(self._shadow_future and not self._shadow_future.done()),
                "shadow_skipped_busy": self._shadow_skipped_busy,
                "policy_profile": self._profile.to_dict(),
                "telemetry": self._recorder.status(),
                "traversed_edges": sorted(self._traversed_edges),
                "floor_knowledge": [self._room_intel[index] for index in sorted(self._room_intel)],
                "latest_state": {
                    "room_clear": self._latest_state.room_clear,
                    "player_dead": self._latest_state.player_dead,
                    "restart_phase": self._latest_state.restart_phase,
                    "restart_count": self._latest_state.restart_count,
                    "restart_error": self._latest_state.restart_error,
                    "room_index": self._latest_state.layout.room_index,
                    "room_type": self._latest_state.layout.room_type,
                    "player_hp": self._latest_state.player.hit_points,
                    "player_position": self._latest_state.player.position.__dict__,
                    "player_grid_index": self._latest_state.player_grid_index,
                    "layout": {
                        "grid_width": self._latest_state.layout.grid_width,
                        "grid_height": self._latest_state.layout.grid_height,
                        "blocked": sorted(self._latest_state.layout.blocked),
                        "danger_grid_indices": sorted(self._latest_state.layout.danger_grid_indices),
                        "doors": [{"slot": door.slot, "grid_index": door.grid_index,
                                   "position": door.position.__dict__}
                                  for door in self._latest_state.layout.doors],
                    },
                    "enemies": len(self._latest_state.enemies),
                    "projectiles": len(self._latest_state.projectiles),
                    "tracking_threats": [
                        {"id": effect.entity_id, "kind": effect.kind,
                         "distance": round(effect.position.distance_to(self._latest_state.player.position), 1),
                         "radius": round(effect.radius, 1)}
                        for effect in self._latest_state.danger_effects
                    ],
                    "pickups": len(self._latest_state.pickups),
                    "resources": {"coins": self._latest_state.coins, "keys": self._latest_state.keys, "bombs": self._latest_state.bombs, "red_hearts": self._latest_state.red_hearts, "max_hearts": self._latest_state.max_hearts, "soul_hearts": self._latest_state.soul_hearts, "black_hearts": self._latest_state.black_hearts, "eternal_hearts": self._latest_state.eternal_hearts},
                    "visited_rooms": sorted(self._visited_rooms),
                    "exhausted_rooms": sorted(self._exhausted_rooms),
                    "planned_door_slot": self._planned_door_slot,
                    "planned_goal": self._planned_goal,
                    "hostile_enemy_count": self._latest_state.hostile_enemy_count,
                    "enemy_observation_valid": self._latest_state.enemy_observation_valid,
            "hazards": [{"id": hazard.entity_id, "kind": hazard.kind, "requires_bomb": hazard.requires_bomb, "distance": round(hazard.position.distance_to(self._latest_state.player.position), 1), "hp": round(hazard.hit_points, 1), "animation": hazard.animation, "variant": hazard.variant, "state": hazard.state} for hazard in self._latest_state.hazards],
                    "hazards_observation_valid": self._latest_state.hazards_observation_valid,
                    "transition_phase": self._latest_state.transition_phase,
                    "transition_gate": self._latest_state.transition_gate,
                    "transition_door_distance": round(self._latest_state.transition_door_distance, 1),
                    "ignored_pickup_ids": sorted(self._ignored_pickup_ids),
                    "ignored_hazard_ids": sorted(self._ignored_hazard_ids),
                    "unreachable_targets": list(self._unreachable_targets),
                    "combat_stuck": self._combat_stuck,
                    "bomb_active": self._latest_state.bomb_active,
                    "bomb_placed": self._latest_state.bomb_placed,
                    "bomb_target_id": self._latest_state.bomb_target_id,
                    "bomb_position": self._latest_state.bomb_position.__dict__,
                    "bomb_placement_distance": self._latest_state.bomb_placement_distance,
                    "bomb_escape_direction": self._latest_state.bomb_escape_direction.__dict__,
                    "bomb_error": self._latest_state.bomb_error,
                    "requested_move": self._latest_state.requested_move.__dict__,
                    "resolved_move": self._latest_state.resolved_move.__dict__,
                    "movement_progress": self._latest_state.movement_progress,
                    "movement_blocked": self._latest_state.movement_blocked,
                    "move_resolution_reason": self._latest_state.move_resolution_reason,
                    "safe_move_directions": self._latest_state.safe_move_directions,
                    "recovery_active": self._latest_state.recovery_active,
                    "recovery_reason": self._latest_state.recovery_reason,
                    "recovery_target_door_slot": self._latest_state.recovery_target_door_slot,
                    "stall_frames": self._latest_state.stall_frames,
                    "last_action_id": self._latest_state.last_action_id,
                    "action_age_frames": self._latest_state.action_age_frames,
                    "hazard_target_id": self._hazard_target_id,
                } if self._latest_state else None,
            }

    def set_autopilot(self, enabled: bool, compact: bool = False) -> dict[str, Any]:
        with self._lock:
            if self.require_enabled_action_feedback and enabled != self.autopilot_enabled:
                # Admission/observation time is not time spent attempting input.
                # Keep genuine prior failures, but restart in-flight timers.
                self._effective_action = None
                self._last_action_sample = None
                self._last_response_signature = None
                self._repeated_action_count = 0
                self._movement_stall_count = 0
                self._hazard_progress_by_target.clear()
                self._hazard_animation_by_target.clear()
                self._hazard_target_id = -1
                self._pickup_target_id = -1
                self._pickup_last_distance = None
                self._stall_anchor = None
                self._stall_best_distance = None
            self.autopilot_enabled = enabled
            if not enabled:
                self._latest_action = None
                self._stall_override = None
                self._stall_override_until_frame = -1
            return self.status(compact=compact)

    def shutdown(self) -> None:
        if self._run_id and not self._run_end_recorded:
            self._experiment_recorder.record(
                "run_ended", run_id=self._run_id, start_seed=self._run_seed,
                provider=self._active_provider_name, model=self._active_provider_model,
            )
            self._run_end_recorded = True
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._shadow_executor.shutdown(wait=False, cancel_futures=True)


class _BridgeHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        runtime: BridgeRuntime = self.server.runtime  # type: ignore[attr-defined]
        runtime.controller.note_connection()
        buffered = b""
        while True:
            try:
                chunk = self.request.recv(65536)
                if not chunk:
                    return
                runtime.controller.note_received_bytes(len(chunk))
                buffered += chunk
                while b"\n" in buffered:
                    raw_line, buffered = buffered.split(b"\n", 1)
                    if not raw_line:
                        continue
                    message = json.loads(raw_line.decode("utf-8"))
                    if message.get("type") == "game_event":
                        runtime.controller.receive_game_event(message)
                        continue
                    if message.get("type") != "state":
                        continue
                    response = runtime.controller.receive_state(message)
                    self.wfile.write((json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8"))
                    self.wfile.flush()
            except (UnicodeDecodeError, json.JSONDecodeError, BrokenPipeError, ConnectionError, OSError) as error:
                runtime.controller.note_bridge_error(error)
                return


class _ThreadedTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class BridgeRuntime:
    def __init__(self, host: str = "127.0.0.1", port: int = 9528, autopilot: bool = False, log_dir: str = "logs", policy_profile: PolicyProfile | None = None, macro_horizon_frames: int = 8, controller_class=Controller) -> None:
        self.controller = controller_class(autopilot_enabled=autopilot, log_dir=log_dir, policy_profile=policy_profile, macro_horizon_frames=macro_horizon_frames)
        self._server = _ThreadedTcpServer((host, port), _BridgeHandler)
        self._server.runtime = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address
        return str(host), int(port)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.controller.shutdown()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
