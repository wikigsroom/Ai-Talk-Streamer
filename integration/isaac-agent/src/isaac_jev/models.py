from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MECHANICAL_TRAP_ENTITY_TYPES = frozenset({42, 44, 201, 202, 203, 212, 218, 235, 236})


@dataclass(frozen=True)
class Vec2:
    x: float = 0.0
    y: float = 0.0

    @classmethod
    def from_value(cls, value: Any) -> "Vec2":
        if not isinstance(value, dict):
            return cls()
        return cls(float(value.get("x", 0.0)), float(value.get("y", 0.0)))

    def distance_to(self, other: "Vec2") -> float:
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5


@dataclass(frozen=True)
class Entity:
    entity_id: int
    kind: int
    position: Vec2
    velocity: Vec2
    hit_points: float = 0.0
    tear_range: float = 260.0
    tear_speed: float = 1.0
    variant: int = -1
    subtype: int = -1
    state: int = -1
    telegraph: str = ""
    is_boss: bool = False
    # Lua reports the room grid cell for entities. Keep this at the end so
    # existing positional Entity(...) construction remains compatible.
    grid_index: int = -1
    vulnerable: bool | None = None
    @classmethod
    def from_value(cls, value: Any) -> "Entity":
        if not isinstance(value, dict):
            return cls(0, 0, Vec2(), Vec2())
        return cls(
            int(value.get("id", 0)),
            int(value.get("type", 0)),
            Vec2.from_value(value.get("pos")),
            Vec2.from_value(value.get("vel")),
            float(value.get("hp", 0.0)),
            float(value.get("tear_range", 260.0) or 260.0),
            float(value.get("tear_speed", 1.0) or 1.0),
            int(value.get("variant", -1)) if value.get("variant") is not None else -1,
            int(value.get("subtype", value.get("sub_type", -1))) if value.get("subtype", value.get("sub_type", -1)) is not None else -1,
            int(value.get("state", -1)) if value.get("state") is not None else -1,
            str(value.get("telegraph", "") or ""),
            bool(value.get("is_boss", False)),
            int(value.get("grid_index", -1) or -1),
            value.get("vulnerable") if isinstance(value.get("vulnerable"), bool) else None,
        )


def projectile_closest_approach(player: Entity, projectile: Entity, horizon: float = 24.0) -> tuple[float, float]:
    """Minimum relative separation over a bounded straight-line forecast.

    Native per-frame avoidance still checks the actual movement path and bodies.
    This macro-level test prevents receding/parallel trap fire from permanently
    interrupting a pressure-plate route merely because it is nearby.
    """
    dx,dy=projectile.position.x-player.position.x,projectile.position.y-player.position.y
    vx,vy=projectile.velocity.x-player.velocity.x,projectile.velocity.y-player.velocity.y
    speed_sq=vx*vx+vy*vy
    tick=max(0.0,min(horizon,-(dx*vx+dy*vy)/speed_sq)) if speed_sq>.001 else 0.0
    return ((dx+vx*tick)**2+(dy+vy*tick)**2)**.5,tick


def projectile_is_imminent(player: Entity, projectile: Entity) -> bool:
    closest,tick=projectile_closest_approach(player,projectile,float('inf'))
    # Closing on a nearby bullet also shortens the collision time when the
    # planner starts moving. Reserve that forward lane before approaching.
    return closest<=40.0 and (player.position.distance_to(projectile.position)<=200.0 or tick<=24.0)


def is_mechanical_trap_entity(entity: Entity) -> bool:
    """Exclude room machinery and noncombat boss attachments from targets."""
    return ((entity.kind in MECHANICAL_TRAP_ENTITY_TYPES
             and (entity.kind != 212 or entity.variant <= 0))
            or (entity.kind == 68 and entity.variant == 10)
            or (entity.kind == 79 and entity.variant == 20)
            or (entity.kind == 216 and entity.variant == 10))


@dataclass(frozen=True)
class Door:
    slot: int
    position: Vec2
    target_room_index: int = -1
    target_is_boss: bool = False
    target_clear: bool = False
    grid_index: int = -1
    target_room_type: str = "unknown"
    locked: bool = False
    lock_known: bool = False
    open: bool = True
    open_known: bool = False

    @classmethod
    def from_value(cls, value: Any) -> "Door":
        return cls(
            int(value.get("slot", -1)), Vec2.from_value(value.get("pos")),
            int(value.get("target_room_index", -1)), bool(value.get("target_is_boss", False)),
            bool(value.get("target_clear", False)), int(value.get("grid_index", -1)),
            str(value.get("target_room_type", "unknown")), bool(value.get("door_locked", value.get("locked", False))),
            bool(value.get("door_lock_known", value.get("lock_known", False))),
            bool(value.get("door_open", value.get("open", True))),
            bool(value.get("door_open_known", value.get("open_known", False))),
        )


@dataclass(frozen=True)
class Pickup:
    entity_id: int
    position: Vec2
    subtype: int
    price: int
    quality: int
    is_collectible: bool
    name: str = "unknown"
    grid_index: int = -1
    pickup_kind: str = "other"

    @classmethod
    def from_value(cls, value: Any) -> "Pickup":
        kind = str(value.get("kind", "other"))
        return cls(
            int(value.get("id", 0)), Vec2.from_value(value.get("pos")), int(value.get("subtype", 0)),
            int(value.get("price", 0)), int(value.get("quality", 0)),
            bool(value.get("is_collectible", False)) or kind == "collectible",
            str(value.get("name", "unknown")), int(value.get("grid_index", -1)), kind,
        )


@dataclass(frozen=True)
class Hazard:
    """A non-hostile room obstacle that must be destroyed before exiting."""

    entity_id: int
    kind: str
    entity_type: int
    position: Vec2
    velocity: Vec2
    hit_points: float = 0.0
    destructible: bool = True
    grid_index: int = -1
    animation: str = ""
    variant: int = -1
    state: int = -1
    requires_bomb: bool = False

    @classmethod
    def from_value(cls, value: Any) -> "Hazard":
        if not isinstance(value, dict):
            return cls(0, "unknown", 0, Vec2(), Vec2())
        entity_type = int(value.get("type", value.get("entity_type", 0)))
        variant = int(value.get("variant", -1)) if value.get("variant") is not None else -1
        raw_kind = str(value.get("kind", "unknown"))
        # Older Mod packets called every fireplace "fire". Recover the
        # special blue/purple variants locally so a controller restart cannot
        # turn an invulnerable fireplace into a tear target.
        if entity_type == 33 and variant in {2, 12}:
            kind = "blue_fire"
        elif entity_type == 33 and variant in {3, 13}:
            kind = "purple_fire"
        else:
            kind = raw_kind
        return cls(
            int(value.get("id", 0)), kind,
            entity_type,
            Vec2.from_value(value.get("pos")), Vec2.from_value(value.get("vel")),
            float(value.get("hp", 0.0) or 0.0), bool(value.get("destructible", True)), int(value.get("grid_index", -1)),
            str(value.get("animation", "") or ""), variant, int(value.get("state", -1)),
            bool(value.get("requires_bomb", False)) or raw_kind == "xrock" or kind in {"blue_fire", "purple_fire"},
        )


@dataclass(frozen=True)
class DangerEffect:
    """A moving non-shootable threat such as a homing ghost bomb."""

    entity_id: int
    kind: str
    position: Vec2
    velocity: Vec2
    radius: float = 40.0
    entity_type: int = 0
    variant: int = -1
    subtype: int = -1
    state: int = -1
    animation: str = ""

    @classmethod
    def from_value(cls, value: Any) -> "DangerEffect":
        if not isinstance(value, dict):
            return cls(0, "unknown", Vec2(), Vec2())
        return cls(
            int(value.get("id", 0)), str(value.get("kind", "unknown")),
            Vec2.from_value(value.get("pos")), Vec2.from_value(value.get("vel")),
            float(value.get("radius", 40.0) or 40.0),
            int(value.get("type", value.get("entity_type", 0)) or 0),
            int(value.get("variant", -1) if value.get("variant") is not None else -1),
            int(value.get("subtype", -1) if value.get("subtype") is not None else -1),
            int(value.get("state", -1) if value.get("state") is not None else -1),
            str(value.get("animation", value.get("telegraph", "")) or ""),
        )


def is_extinguished_fire(hazard: Hazard) -> bool:
    return hazard.kind in {"fire", "blue_fire", "purple_fire"} and any(
        marker in hazard.animation.lower()
        for marker in ("dissapear", "disappear", "extingu", "nofire", "no_fire", "unlit", "off", "death", "destroy", "poof")
    )


@dataclass(frozen=True)
class GridEvent:
    kind: str
    grid_index: int
    position: Vec2
    active: bool = False
    triggered: bool = False
    entity_id: int = -1
    timed: bool = False

    @classmethod
    def from_value(cls, value: Any) -> "GridEvent":
        return cls(
            str(value.get("kind", "unknown")),
            int(value.get("grid_index", -1)),
            Vec2.from_value(value.get("pos")),
            bool(value.get("active", False)),
            bool(value.get("triggered", False)),
            int(value.get("id", -1)),
            bool(value.get("timed", False)),
        )


@dataclass(frozen=True)
class BombWall:
    slot: int
    position: Vec2
    site: Vec2
    grid_index: int
    room_type: str
    bombed: bool = False

    @classmethod
    def from_value(cls, value: Any) -> "BombWall":
        return cls(int(value.get("slot", -1)), Vec2.from_value(value.get("pos")), Vec2.from_value(value.get("site")),
                   int(value.get("grid_index", -1)), str(value.get("room_type", "unknown")),
                   bool(value.get("bombed", False)))


@dataclass(frozen=True)
class RoomLayout:
    room_index: int = -1
    room_type: str = "unknown"
    is_boss: bool = False
    grid_width: int = 0
    grid_height: int = 0
    blocked: frozenset[int] = frozenset()
    doors: tuple[Door, ...] = ()
    danger_grid_indices: frozenset[int] = frozenset()
    grid_events: tuple[GridEvent, ...] = ()
    bomb_walls: tuple[BombWall, ...] = ()
    shot_blocked: frozenset[int] | None = None

    @classmethod
    def from_value(cls, value: Any) -> "RoomLayout":
        if not isinstance(value, dict):
            return cls()
        return cls(
            int(value.get("room_index", -1)), str(value.get("room_type", value.get("type", "unknown"))), bool(value.get("is_boss", False)),
            int(value.get("grid_width", 0)), int(value.get("grid_height", 0)),
            frozenset(int(item) for item in value.get("blocked", []) if isinstance(item, int)),
            tuple(Door.from_value(item) for item in value.get("doors", []) if isinstance(item, dict)),
            frozenset(int(item) for item in value.get("danger_grid_indices", []) if isinstance(item, int)),
            tuple(GridEvent.from_value(item) for item in value.get("grid_events", []) if isinstance(item, dict)),
            tuple(BombWall.from_value(item) for item in value.get("bomb_walls", []) if isinstance(item, dict)),
            frozenset(int(item) for item in value["shot_blocked"]) if isinstance(value.get("shot_blocked"), list) else None,
        )


@dataclass(frozen=True)
class DamageEvent:
    event_id: int
    frame: int
    amount: float
    flags: int
    source_type: int = -1
    source_variant: int = -1

    @classmethod
    def from_value(cls, value: Any) -> "DamageEvent":
        if not isinstance(value, dict):
            return cls(0, 0, 0.0, 0)
        return cls(
            event_id=int(value.get("id", value.get("event_id", 0)) or 0),
            frame=int(value.get("frame", 0) or 0),
            amount=float(value.get("amount", 0.0) or 0.0),
            flags=int(value.get("flags", 0) or 0),
            source_type=int(value.get("source_type", -1) if value.get("source_type") is not None else -1),
            source_variant=int(value.get("source_variant", -1) if value.get("source_variant") is not None else -1),
        )


@dataclass(frozen=True)
class GameState:
    frame: int
    room_clear: bool
    player: Entity
    enemies: tuple[Entity, ...]
    projectiles: tuple[Entity, ...]
    layout: RoomLayout = field(default_factory=RoomLayout)
    pickups: tuple[Pickup, ...] = ()
    hazards: tuple[Hazard, ...] = ()
    danger_effects: tuple[DangerEffect, ...] = ()
    floor_danger_effects: tuple[DangerEffect, ...] = ()
    hazards_observation_valid: bool = True
    coins: int = 0
    keys: int = 0
    bombs: int = 0
    player_grid_index: int = -1
    red_hearts: int = 0
    max_hearts: int = 0
    soul_hearts: int = 0
    black_hearts: int = 0
    bone_hearts: int = 0
    eternal_hearts: int = 0
    visited_room_indices: frozenset[int] = frozenset()
    exhausted_room_indices: frozenset[int] = frozenset()
    previous_room_index: int = -1
    planned_door_slot: int = -1
    planned_goal: str = ""
    room_index: int = -1
    hostile_enemy_count: int = 0
    enemy_observation_valid: bool = True
    ignored_pickup_ids: frozenset[int] = frozenset()
    ignored_hazard_ids: frozenset[int] = frozenset()
    unreachable_door_slots: frozenset[int] = frozenset()
    combat_stuck: bool = False
    transition_phase: str = "idle"
    transition_attempt: int = 0
    transition_error: str = ""
    transition_gate: str = "idle"
    transition_door_distance: float = -1.0
    requested_move: Vec2 = Vec2()
    resolved_move: Vec2 = Vec2()
    movement_progress: float = 0.0
    movement_blocked: bool = False
    move_resolution_reason: str = ""
    last_action_id: str = ""
    last_action_mode: str = ""
    last_action_sequence: int = 0
    action_age_frames: int = 0
    player_dead: bool = False
    restart_phase: str = "alive"
    restart_count: int = 0
    restart_error: str = ""
    boss_exit_available: bool = False
    boss_exit_position: Vec2 = Vec2()
    boss_exit_grid_index: int = -1
    start_seed: int = 0
    progression_target: str = ""
    room_visit_sequence: int = 0
    room_entered_frame: int = -1
    room_cleared_frame: int = -1
    damage_events: tuple[DamageEvent, ...] = ()
    enemy_total_hp: float = 0.0
    enemy_count: int = 0
    enemy_kill_delta: int = 0
    stage: int = 0
    stage_type: int = 0
    dimension: int = 0
    weapon_type: str = "unknown"
    weapon_type_known: bool = False
    held_trinkets: tuple[int, ...] = ()
    trinket_slots: int = 1
    held_pills: tuple[tuple[int, int], ...] = ()
    held_cards: tuple[tuple[int, int], ...] = ()
    pill_use_result: str = "idle"
    trinket_swap_result: str = "idle"
    mod_version: str = "unknown"
    fire_block_reason: str = "idle"
    bomb_active: bool = False
    bomb_placed: bool = False
    bomb_target_id: int = -1
    bomb_error: str = ""
    bomb_position: Vec2 = Vec2()
    bomb_placement_distance: float = -1.0
    bomb_escape_direction: Vec2 = Vec2()
    safe_move_directions: dict[str, str] = field(default_factory=dict)
    recovery_active: bool = False
    recovery_reason: str = ""
    recovery_target_door_slot: int = -1
    stall_frames: int = 0
    recent_actions: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_message(cls, message: dict[str, Any]) -> "GameState":
        raw_player = message.get("player") if isinstance(message.get("player"), dict) else {}
        raw_enemies = message.get("enemies") if isinstance(message.get("enemies"), (list, tuple)) else []
        raw_damage_events = message.get("damage_events") if isinstance(message.get("damage_events"), (list, tuple)) else []
        reported_dead = bool(message.get("player_dead", False)) or ("hp" in raw_player and float(raw_player.get("hp", 0.0) or 0.0) <= 0)
        parsed_enemies = tuple(Entity.from_value(item) for item in raw_enemies if isinstance(item, dict))
        enemies = tuple(item for item in parsed_enemies if not is_mechanical_trap_entity(item))
        only_mechanical_traps = bool(parsed_enemies) and not enemies
        parsed_hazards = tuple(Hazard.from_value(item) for item in message.get("hazards", []) if isinstance(item, dict))
        hazards = tuple(item for item in parsed_hazards if not is_extinguished_fire(item))
        return cls(
            frame=int(message.get("frame", 0)),
            room_clear=bool(message.get("room_clear", False)) or only_mechanical_traps,
            player=Entity.from_value(message.get("player")),
            enemies=enemies,
            projectiles=tuple(Entity.from_value(item) for item in (message.get("projectiles") if isinstance(message.get("projectiles"), (list, tuple)) else []) if isinstance(item, dict)),
            layout=RoomLayout.from_value(message.get("layout")),
            pickups=tuple(Pickup.from_value(item) for item in message.get("pickups", []) if isinstance(item, dict)),
            hazards=hazards,
            danger_effects=tuple(
                DangerEffect.from_value(item)
                for item in message.get("danger_effects", [])
                if isinstance(item, dict) and str(item.get("kind", "")) in {"ghost_bomb", "armed_bomb"}
            ),
            floor_danger_effects=tuple(
                DangerEffect.from_value(item)
                for item in message.get("danger_effects", [])
                if isinstance(item, dict) and str(item.get("kind", "")) not in {"ghost_bomb", "armed_bomb"}
            ),
            hazards_observation_valid=bool(message.get("hazards_observation_valid", True)),
            coins=int(message.get("coins", 0)),
            keys=int(message.get("keys", 0)),
            bombs=int(message.get("bombs", 0)),
            held_trinkets=tuple(int(item) for item in message.get("held_trinkets", []) if isinstance(item, int)),
            trinket_slots=int(message.get("trinket_slots", 1) or 1),
            held_pills=tuple((int(item.get("slot", 0)), int(item.get("color", 0))) for item in message.get("held_pills", []) if isinstance(item, dict)),
            held_cards=tuple((int(item.get("slot", 0)), int(item.get("card", 0))) for item in message.get("held_cards", []) if isinstance(item, dict)),
            pill_use_result=str(message.get("pill_use_result", "idle")),
            trinket_swap_result=str(message.get("trinket_swap_result", "idle")),
            mod_version=str(message.get("mod_version", "unknown")),
            fire_block_reason=str(message.get("fire_block_reason", "idle")),
            bomb_active=bool(message.get("bomb_active", False)),
            bomb_placed=bool(message.get("bomb_placed", False)),
            bomb_target_id=int(message.get("bomb_target_id", -1)),
            bomb_error=str(message.get("bomb_error", "")),
            bomb_position=Vec2.from_value(message.get("bomb_position")),
            bomb_placement_distance=float(message.get("bomb_placement_distance", -1.0)),
            bomb_escape_direction=Vec2.from_value(message.get("bomb_escape_direction")),
            safe_move_directions={str(key): str(value) for key, value in message.get("safe_move_directions", {}).items()}
            if isinstance(message.get("safe_move_directions"), dict) else {},
            recovery_active=bool(message.get("recovery_active", False)),
            recovery_reason=str(message.get("recovery_reason", "")),
            recovery_target_door_slot=int(message.get("recovery_target_door_slot", -1)),
            stall_frames=int(message.get("stall_frames", 0)),
            recent_actions=tuple(item for item in message.get("recent_actions", [])[-5:]
                                 if isinstance(item, dict)) if isinstance(message.get("recent_actions"), list) else (),
            player_grid_index=int(message.get("player_grid_index", -1)),
            red_hearts=int(message.get("player", {}).get("red_hearts", 0)) if isinstance(message.get("player"), dict) else 0,
            max_hearts=int(message.get("player", {}).get("max_hearts", 0)) if isinstance(message.get("player"), dict) else 0,
            soul_hearts=int(message.get("player", {}).get("soul_hearts", 0)) if isinstance(message.get("player"), dict) else 0,
            black_hearts=int(message.get("player", {}).get("black_hearts", 0)) if isinstance(message.get("player"), dict) else 0,
            bone_hearts=int(message.get("player", {}).get("bone_hearts", 0)) if isinstance(message.get("player"), dict) else 0,
            eternal_hearts=int(message.get("player", {}).get("eternal_hearts", 0)) if isinstance(message.get("player"), dict) else 0,
            visited_room_indices=frozenset(int(item) for item in message.get("visited_room_indices", []) if isinstance(item, int)),
            exhausted_room_indices=frozenset(int(item) for item in message.get("exhausted_room_indices", []) if isinstance(item, int)),
            previous_room_index=int(message.get("previous_room_index", -1)),
            planned_door_slot=int(message.get("planned_door_slot", -1)),
            planned_goal=str(message.get("planned_goal", "")),
            room_index=int(message.get("room_index", message.get("layout", {}).get("room_index", -1))) if isinstance(message.get("layout", {}), dict) else -1,
            hostile_enemy_count=len(enemies),
            enemy_observation_valid=bool(message.get("enemy_observation_valid", True)),
            ignored_pickup_ids=frozenset(int(item) for item in message.get("ignored_pickup_ids", []) if isinstance(item, int)),
            ignored_hazard_ids=frozenset(int(item) for item in message.get("ignored_hazard_ids", []) if isinstance(item, int)),
            unreachable_door_slots=frozenset(int(item) for item in message.get("unreachable_door_slots", []) if isinstance(item, int)),
            combat_stuck=bool(message.get("combat_stuck", False)),
            transition_phase=str(message.get("transition_phase", "idle")),
            transition_attempt=int(message.get("transition_attempt", 0)),
            transition_error=str(message.get("transition_error", "") or ""),
            transition_gate=str(message.get("transition_gate", "idle") or "idle"),
            transition_door_distance=float(message.get("transition_door_distance", -1.0) or -1.0),
            requested_move=Vec2.from_value(message.get("requested_move")),
            resolved_move=Vec2.from_value(message.get("resolved_move")),
            movement_progress=float(message.get("movement_progress", 0.0) or 0.0),
            movement_blocked=bool(message.get("movement_blocked", False)),
            move_resolution_reason=str(message.get("move_resolution_reason", "") or ""),
            last_action_id=str(message.get("last_action_id", "") or ""),
            last_action_mode=str(message.get("last_action_mode", "") or ""),
            last_action_sequence=int(message.get("last_action_sequence", 0) or 0),
            action_age_frames=int(message.get("action_age_frames", 0) or 0),
            player_dead=reported_dead,
            restart_phase=str(message.get("restart_phase", "alive") or "alive"),
            restart_count=int(message.get("restart_count", 0) or 0),
            restart_error=str(message.get("restart_error", "") or ""),
            boss_exit_available=bool(message.get("boss_exit_available", False)),
            boss_exit_position=Vec2.from_value(message.get("boss_exit_position")),
            boss_exit_grid_index=int(message.get("boss_exit_grid_index", -1) or -1),
            start_seed=int(message.get("start_seed", 0) or 0),
            progression_target=str(message.get("progression_target", "") or ""),
            room_visit_sequence=int(message.get("room_visit_sequence", 0) or 0),
            room_entered_frame=int(message.get("room_entered_frame", -1) if message.get("room_entered_frame") is not None else -1),
            room_cleared_frame=int(message.get("room_cleared_frame", -1) if message.get("room_cleared_frame") is not None else -1),
            damage_events=tuple(
                DamageEvent.from_value(item)
                for item in raw_damage_events[-32:]
                if isinstance(item, dict)
            ),
            enemy_total_hp=float(message.get("enemy_total_hp", sum(float(item.get("hp", 0.0) or 0.0) for item in raw_enemies if isinstance(item, dict))) or 0.0),
            enemy_count=int(message.get("enemy_count", len(raw_enemies)) or 0),
            enemy_kill_delta=int(message.get("enemy_kill_delta", 0) or 0),
            stage=int(message.get("stage", 0) or 0),
            stage_type=int(message.get("stage_type", 0) or 0),
            dimension=int(message.get("dimension", 0) or 0),
            weapon_type=str(raw_player.get("weapon_type", message.get("weapon_type", "unknown")) or "unknown"),
            weapon_type_known=bool(raw_player.get("weapon_type_known", message.get("weapon_type_known", False))),
        )

    def compact(self) -> dict[str, Any]:
        geometry = self.geometry_features()

        def describe(entity: Entity) -> dict[str, Any]:
            offset = Vec2(entity.position.x - self.player.position.x, entity.position.y - self.player.position.y)
            return {
                "type": entity.kind,
                "variant": entity.variant,
                "subtype": entity.subtype,
                "state": entity.state,
                "telegraph": entity.telegraph,
                "is_stationary": abs(entity.velocity.x) + abs(entity.velocity.y) < 0.1,
                "offset": {"x": round(offset.x, 1), "y": round(offset.y, 1)},
                "velocity": {"x": round(entity.velocity.x, 1), "y": round(entity.velocity.y, 1)},
                "hp": round(entity.hit_points, 1),
                "is_boss": entity.is_boss,
                "vulnerable": entity.vulnerable,
            }

        close_enemies = sorted(self.enemies, key=lambda item: item.position.distance_to(self.player.position))[:8]
        close_shots = sorted(self.projectiles, key=lambda item: item.position.distance_to(self.player.position))[:12]
        close_effects = sorted(self.danger_effects, key=lambda item: item.position.distance_to(self.player.position))[:4]
        return {
            "frame": self.frame,
            "mod_version": self.mod_version,
            "fire_block_reason": self.fire_block_reason,
            "bomb_active": self.bomb_active,
            "bomb_placed": self.bomb_placed,
            "bomb_target_id": self.bomb_target_id,
            "bomb_error": self.bomb_error,
            "bomb_position": self.bomb_position.__dict__,
            "bomb_placement_distance": round(self.bomb_placement_distance, 1),
            "bomb_escape_direction": self.bomb_escape_direction.__dict__,
            "start_seed": self.start_seed,
            "room_clear": self.room_clear,
            "room_visit_sequence": self.room_visit_sequence,
            "room_entered_frame": self.room_entered_frame,
            "room_cleared_frame": self.room_cleared_frame,
            "hostile_enemy_count": self.hostile_enemy_count,
            "enemy_count": self.enemy_count,
            "enemy_total_hp": round(self.enemy_total_hp, 1),
            "enemy_kill_delta": self.enemy_kill_delta,
            "enemy_observation_valid": self.enemy_observation_valid,
            "player": {"hp": round(self.player.hit_points, 1), "position": self.player.position.__dict__, "grid_index": self.player_grid_index, "red_hearts": self.red_hearts, "max_hearts": self.max_hearts, "soul_hearts": self.soul_hearts, "black_hearts": self.black_hearts, "bone_hearts": self.bone_hearts, "eternal_hearts": self.eternal_hearts, "tear_range": round(self.player.tear_range, 1), "tear_speed": round(self.player.tear_speed, 2), "velocity": self.player.velocity.__dict__, "weapon_type": self.weapon_type, "weapon_type_known": self.weapon_type_known},
            "room": {"index": self.layout.room_index, "stage": self.stage, "stage_type": self.stage_type, "dimension": self.dimension, "type": self.layout.room_type, "is_boss": self.layout.is_boss, "grid_width": self.layout.grid_width, "grid_height": self.layout.grid_height, "blocked": sorted(self.layout.blocked), "danger_grid_indices": sorted(self.layout.danger_grid_indices), "grid_events": [item.__dict__ | {"position": item.position.__dict__} for item in self.layout.grid_events], "bomb_walls": [item.__dict__ | {"position": item.position.__dict__} for item in self.layout.bomb_walls], "planned_door_slot": self.planned_door_slot, "planned_goal": self.planned_goal, "doors": [door.__dict__ | {"position": door.position.__dict__} for door in self.layout.doors]},
            "resources": {"coins": self.coins, "keys": self.keys, "bombs": self.bombs,
                          "held_trinkets": list(self.held_trinkets), "trinket_slots": self.trinket_slots,
                          "held_pills": [{"slot": slot, "color": color} for slot, color in self.held_pills],
                          "held_cards": [{"slot": slot, "card": card} for slot, card in self.held_cards],
                          "pill_use_result": self.pill_use_result,
                          "trinket_swap_result": self.trinket_swap_result},
            "pickups": [{"id": item.entity_id, "name": item.name, "kind": item.pickup_kind, "quality": item.quality, "price": item.price} for item in self.pickups],
            "hazards": [{"id": item.entity_id, "kind": item.kind, "type": item.entity_type, "grid_index": item.grid_index, "offset": {"x": round(item.position.x - self.player.position.x, 1), "y": round(item.position.y - self.player.position.y, 1)}, "hp": round(item.hit_points, 1), "destructible": item.destructible, "requires_bomb": item.requires_bomb, "animation": item.animation, "variant": item.variant, "state": item.state} for item in sorted(self.hazards, key=lambda item: item.position.distance_to(self.player.position))[:8]],
            "ignored_hazard_ids": sorted(self.ignored_hazard_ids),
            "combat_stuck": self.combat_stuck,
            "hazards_observation_valid": self.hazards_observation_valid,
            "nearby_enemies": [describe(item) for item in close_enemies],
            "nearby_projectiles": [describe(item) for item in close_shots],
            "tracking_threats": [
                {"id": item.entity_id, "kind": item.kind, "type": item.entity_type,
                 "variant": item.variant, "animation": item.animation,
                 "offset": {"x": round(item.position.x - self.player.position.x, 1),
                            "y": round(item.position.y - self.player.position.y, 1)},
                 "velocity": {"x": round(item.velocity.x, 1), "y": round(item.velocity.y, 1)},
                 "radius": round(item.radius, 1)}
                for item in close_effects
            ],
            "damage_events": [
                {
                    "id": event.event_id,
                    "frame": event.frame,
                    "amount": round(event.amount, 2),
                    "flags": event.flags,
                    "source_type": event.source_type,
                    "source_variant": event.source_variant,
                }
                for event in self.damage_events
            ],
            "geometry": geometry,
            "navigation_feedback": {"requested_move": self.requested_move.__dict__, "resolved_move": self.resolved_move.__dict__, "movement_progress": round(self.movement_progress, 2), "movement_blocked": self.movement_blocked, "move_resolution_reason": self.move_resolution_reason, "safe_move_directions": self.safe_move_directions, "recovery_active": self.recovery_active, "recovery_reason": self.recovery_reason, "recovery_target_door_slot": self.recovery_target_door_slot, "stall_frames": self.stall_frames, "last_action_id": self.last_action_id, "last_action_mode": self.last_action_mode, "last_action_sequence": self.last_action_sequence, "action_age_frames": self.action_age_frames, "recent_actions": list(self.recent_actions), "transition_phase": self.transition_phase},
            "boss_exit": {"available": self.boss_exit_available, "position": self.boss_exit_position.__dict__, "grid_index": self.boss_exit_grid_index},
            "death": {"player_dead": self.player_dead, "restart_phase": self.restart_phase, "restart_count": self.restart_count, "restart_error": self.restart_error},
        }

    def attack_targets(self) -> tuple[Entity, ...]:
        vulnerable = tuple(item for item in self.enemies if item.vulnerable is not False)
        return vulnerable or self.enemies

    def geometry_features(self) -> dict[str, Any]:
        """Return deterministic safety features computed locally, never by Jev."""
        nearest_enemy = min(self.enemies, key=lambda item: item.position.distance_to(self.player.position), default=None)
        enemy_distance = nearest_enemy.position.distance_to(self.player.position) if nearest_enemy else None
        attack_target = min(self.attack_targets(), key=lambda item: item.position.distance_to(self.player.position), default=None)
        threatening: list[dict[str, Any]] = []
        for projectile in self.projectiles:
            closest,closest_tick=projectile_closest_approach(self.player,projectile)
            rel = Vec2(self.player.position.x - projectile.position.x, self.player.position.y - projectile.position.y)
            distance = projectile.position.distance_to(self.player.position)
            speed_sq = projectile.velocity.x * projectile.velocity.x + projectile.velocity.y * projectile.velocity.y
            closing_speed = (rel.x * projectile.velocity.x + rel.y * projectile.velocity.y) / max(distance, 1.0)
            ttc = distance / closing_speed if closing_speed > 0.01 else None
            if ttc is not None:
                ttc = round(max(0.0, ttc), 2)
            threatening.append({
                "id": projectile.entity_id,
                "distance": round(distance, 1),
                "offset": {"x": round(projectile.position.x - self.player.position.x, 1), "y": round(projectile.position.y - self.player.position.y, 1)},
                "velocity": projectile.velocity.__dict__,
                "closing_speed": round(max(0.0, closing_speed), 2),
                "ttc_frames": ttc,
                "closest_approach_distance": round(closest,1),
                "closest_approach_frames": round(closest_tick,2),
                "imminent": projectile_is_imminent(self.player,projectile),
            })
        open_neighbors = 0
        if self.layout.grid_width and self.layout.grid_height and self.player_grid_index >= 0:
            row, col = divmod(self.player_grid_index, self.layout.grid_width)
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = row + dr, col + dc
                if 0 <= nr < self.layout.grid_height and 0 <= nc < self.layout.grid_width:
                    if nr * self.layout.grid_width + nc not in self.layout.blocked:
                        open_neighbors += 1
        else:
            open_neighbors = 4
        threatening.sort(key=lambda item: item["distance"])
        nearest = threatening[0] if threatening else None
        tracking: list[dict[str, Any]] = []
        for effect in self.danger_effects:
            if effect.kind not in {"ghost_bomb", "armed_bomb"}:
                continue
            rel = Vec2(self.player.position.x - effect.position.x, self.player.position.y - effect.position.y)
            distance = effect.position.distance_to(self.player.position)
            closing_speed = (rel.x * effect.velocity.x + rel.y * effect.velocity.y) / max(distance, 1.0)
            ttc = distance / closing_speed if closing_speed > 0.01 else None
            if ttc is not None:
                ttc = round(max(0.0, ttc), 2)
            tracking.append({
                "id": effect.entity_id,
                "kind": effect.kind,
                "distance": round(distance, 1),
                "offset": {"x": round(effect.position.x - self.player.position.x, 1),
                           "y": round(effect.position.y - self.player.position.y, 1)},
                "velocity": effect.velocity.__dict__,
                "closing_speed": round(max(0.0, closing_speed), 2),
                "ttc_frames": ttc,
                "imminent": bool((ttc is not None and ttc <= 24.0) or distance <= 150.0),
            })
        tracking.sort(key=lambda item: item["distance"])
        nearest_tracking = tracking[0] if tracking else None
        line_of_fire_blocked = False
        if attack_target:
            dx = attack_target.position.x - self.player.position.x
            dy = attack_target.position.y - self.player.position.y
            length_sq = dx * dx + dy * dy
            for hazard in self.hazards:
                if not hazard.destructible:
                    continue
                projection = ((hazard.position.x - self.player.position.x) * dx + (hazard.position.y - self.player.position.y) * dy) / max(length_sq, 1.0)
                if 0.05 < projection < 0.95:
                    closest_x = self.player.position.x + projection * dx
                    closest_y = self.player.position.y + projection * dy
                    if ((hazard.position.x - closest_x) ** 2 + (hazard.position.y - closest_y) ** 2) ** 0.5 <= 42.0:
                        line_of_fire_blocked = True
                        break
            # A wall/rock grid cell can block the shot even when no
            # destructible hazard entity is present. Isaac's Lua bridge sends
            # grid_index for both player and enemies, so sample the discrete
            # grid segment and inspect only the cells between the endpoints.
            player_grid = self.player_grid_index if self.player_grid_index >= 0 else self.player.grid_index
            enemy_grid = attack_target.grid_index
            width, height = self.layout.grid_width, self.layout.grid_height
            if (not line_of_fire_blocked and width and height
                    and player_grid >= 0 and enemy_grid >= 0
                    and player_grid != enemy_grid):
                prow, pcol = divmod(player_grid, width)
                erow, ecol = divmod(enemy_grid, width)
                dx_grid = abs(ecol - pcol)
                dy_grid = abs(erow - prow)
                step_col = 1 if pcol < ecol else -1
                step_row = 1 if prow < erow else -1
                error = dx_grid - dy_grid
                col, row = pcol, prow
                while (col, row) != (ecol, erow):
                    doubled = 2 * error
                    if doubled > -dy_grid:
                        error -= dy_grid
                        col += step_col
                    if doubled < dx_grid:
                        error += dx_grid
                        row += step_row
                    if (col, row) == (ecol, erow):
                        break
                    index = row * width + col
                    if index in (self.layout.shot_blocked if self.layout.shot_blocked is not None else self.layout.blocked):
                        line_of_fire_blocked = True
                        break
        return {
            "nearest_enemy_distance": round(enemy_distance, 1) if enemy_distance is not None else None,
            "enemy_range_margin": round(self.player.tear_range - enemy_distance, 1) if enemy_distance is not None else None,
            "wall_clearance_neighbors": open_neighbors,
            # An unobstructed diagonal is not a cardinal tear firing lane.
            "attack_target_id": attack_target.entity_id if attack_target else None,
            "attack_target_distance": round(attack_target.position.distance_to(self.player.position),1) if attack_target else None,
            "line_of_fire": bool(attack_target) and not line_of_fire_blocked and min(
                abs(attack_target.position.x - self.player.position.x),
                abs(attack_target.position.y - self.player.position.y),
            ) <= 22.0,
            "line_of_fire_blocked": line_of_fire_blocked,
            "projectile_threats": threatening,
            "nearest_projectile_ttc_frames": nearest["ttc_frames"] if nearest else None,
            "nearest_projectile_imminent": bool(nearest and nearest["imminent"]),
            "tracking_threats": tracking,
            "nearest_tracking_bomb_distance": nearest_tracking["distance"] if nearest_tracking else None,
            "nearest_tracking_bomb_ttc_frames": nearest_tracking["ttc_frames"] if nearest_tracking else None,
            "nearest_tracking_bomb_imminent": bool(nearest_tracking and nearest_tracking["imminent"]),
        }


@dataclass(frozen=True)
class Action:
    action_id: str
    move: Vec2
    shoot: Vec2
    confidence: float = 0.0
    source: str = "fallback"
    mode: str = "combat"
    target: str = ""
    reason: str = ""
    issued_frame: int = -1
    expires_frame: int = -1
    macro_horizon_frames: int = 8
    bomb_site: Vec2 | None = None
    waypoint: Vec2 | None = None

    def as_message(self, enabled: bool) -> dict[str, Any]:
        return {
            "type": "action",
            "enabled": enabled,
            "id": self.action_id,
            "move": self.move.__dict__,
            "shoot": self.shoot.__dict__,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "mode": self.mode,
            "target": self.target,
            "reason": self.reason,
            "issued_frame": self.issued_frame,
            "expires_frame": self.expires_frame,
            "macro_horizon_frames": self.macro_horizon_frames,
            "bomb_site": self.bomb_site.__dict__ if self.bomb_site else None,
            "waypoint": self.waypoint.__dict__ if self.waypoint else None,
        }
