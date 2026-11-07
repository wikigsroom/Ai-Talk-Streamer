from __future__ import annotations

import json
import hashlib
import inspect
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import Any

from .models import Action, GameState, Vec2, projectile_is_imminent
from .navigation import bombing_position, door_is_usable, door_path_distance, firing_position, grid_cell_center, move_towards, newly_opened_secret_door, path_distance
from .tuning import PolicyProfile

SCHEMA_VERSION = "jev-policy-v2"
_LOOT_MODES = frozenset({"item", "shop", "pickup", "chest", "hazard", "bomb", "bomb_wall", "tnt"})
BOSS_REWARD_SPAWN_FRAMES = 60
JOKER_CARD_ID = 31  # Read from Card.CARD_JOKER in the running 1.7.9b game.


def _boss_reward_wait_action(state: GameState) -> Action | None:
    if not (state.room_clear and (state.layout.is_boss or state.layout.room_type == "boss")):
        return None
    if state.room_cleared_frame < 0 or state.frame - state.room_cleared_frame >= BOSS_REWARD_SPAWN_FRAMES:
        return None
    return Action("wait_for_boss_reward", Vec2(), Vec2(), mode="wait",
                  reason=f"wait {BOSS_REWARD_SPAWN_FRAMES - (state.frame - state.room_cleared_frame)} frames for Boss reward to spawn")


@dataclass(frozen=True)
class CandidateSet:
    """The auditable candidate contract passed to Jev."""

    policy: str
    phase: str
    raw_candidates: tuple[Action, ...]
    admissible_candidates: tuple[Action, ...]
    rejected_candidates: tuple[dict[str, Any], ...] = ()
    single_legal_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        def encode(action: Action) -> dict[str, Any]:
            return {
                "id": action.action_id,
                "mode": action.mode,
                "target": action.target,
                "move": action.move.__dict__,
                "shoot": action.shoot.__dict__,
                "reason": action.reason,
            }
        return {
            "policy": self.policy,
            "phase": self.phase,
            "raw_candidates": [encode(item) for item in self.raw_candidates],
            "admissible_candidates": [encode(item) for item in self.admissible_candidates],
            "rejected_candidates": list(self.rejected_candidates),
            "single_legal_reason": self.single_legal_reason,
        }


def policy_router(state: GameState, candidate_set: CandidateSet | None = None) -> str:
    """Select the owner of the next decision before any remote call."""
    candidate_set = candidate_set or build_candidate_set(state)
    if state.player_dead:
        return "dead"
    # The selected decision provider owns every actionable policy. The local
    # layer still validates the returned id and applies a failure fallback,
    # but it must not silently take over navigation or emergency choices.
    return candidate_set.policy


def should_call_jev(state: GameState, candidate_set: CandidateSet | None = None) -> bool:
    """A Choice request is useful only when there are real alternatives."""
    route = policy_router(state, candidate_set)
    candidates = candidate_set or build_candidate_set(state)
    return route in {"combat", "loot", "navigation", "emergency"} and len(candidates.admissible_candidates) >= 2


def local_policy_action(state: GameState, candidate_set: CandidateSet | None = None, profile: PolicyProfile | None = None) -> Action:
    """Resolve decisions that must not wait on the network."""
    candidate_set = candidate_set or build_candidate_set(state, profile)
    route = policy_router(state, candidate_set)
    if candidate_set.admissible_candidates:
        selected = candidate_set.admissible_candidates[0]
    else:
        selected = conservative_action(state, profile)
    return replace(selected, source="local", confidence=max(1.0, selected.confidence))


def build_policy_observation(state: GameState, candidate_set: CandidateSet) -> dict[str, Any]:
    """Build the smallest state needed by the selected remote policy."""
    geometry = state.geometry_features()

    def action_forecast(item: Action) -> dict[str, Any]:
        """Conservative 12-frame comparison, not a simulated game outcome."""
        door = next((entry for entry in state.layout.doors
                     if item.action_id == f"enter_door_{entry.slot}"), None)
        forecast_move = item.move
        if door and door.slot % 4 in {0, 2}:
            side = Vec2(-1, 0) if door.slot % 4 == 0 else Vec2(1, 0)
            side_name = "left" if side.x < 0 else "right"
            if (abs(door.position.x - state.player.position.x) > 70
                    and abs(door.position.y - state.player.position.y) <= 42
                    and state.safe_move_directions.get(side_name) == "safe"):
                forecast_move = side
        direction = ({(0, -1): "up", (0, 1): "down", (-1, 0): "left", (1, 0): "right"}
                     .get((forecast_move.x, forecast_move.y)))
        lua_safety = state.safe_move_directions.get(direction) if direction else None
        next_grid = None
        if direction and state.layout.grid_width and state.layout.grid_height and state.player_grid_index >= 0:
            row, col = divmod(state.player_grid_index, state.layout.grid_width)
            next_row, next_col = row + int(forecast_move.y), col + int(forecast_move.x)
            if 0 <= next_row < state.layout.grid_height and 0 <= next_col < state.layout.grid_width:
                next_grid = next_row * state.layout.grid_width + next_col
        blocked_reason = (lua_safety if lua_safety not in {None, "safe"} else None)
        crossing_door = bool(door and state.player.position.distance_to(door.position) <= 70
                             and ((door.slot % 4 == 0 and direction == "left")
                                  or (door.slot % 4 == 1 and direction == "up")
                                  or (door.slot % 4 == 2 and direction == "right")
                                  or (door.slot % 4 == 3 and direction == "down")))
        if crossing_door and blocked_reason == "grid_wall":
            blocked_reason = None
        if (direction and next_grid is None and state.layout.grid_width
                and state.layout.grid_height and state.player_grid_index >= 0):
            blocked_reason = blocked_reason or "outside_grid"
        elif (next_grid is not None
              and (next_grid in state.layout.danger_grid_indices
                   or (not crossing_door and next_grid in state.layout.blocked))):
            blocked_reason = blocked_reason or "blocked_or_danger_grid"
        estimated_step = 0 if blocked_reason else (24 if direction else 0)
        predicted = Vec2(state.player.position.x + forecast_move.x * estimated_step,
                         state.player.position.y + forecast_move.y * estimated_step)
        target = door.position if door else item.waypoint
        if target is None and item.mode == "boss_exit":
            target = state.boss_exit_position
        if target is None and item.mode in {"item", "shop", "pickup", "chest"}:
            pickup = next((entry for entry in state.pickups
                           if item.action_id.endswith(f"_{entry.entity_id}")), None)
            target = pickup.position if pickup else None
        if target is None and item.mode in {"hazard", "bomb", "tnt"}:
            hazard = next((entry for entry in state.hazards
                           if item.action_id.endswith(f"_{entry.entity_id}")), None)
            target = hazard.position if hazard else None
            if target is None and item.action_id.startswith("bomb_boss_"):
                boss = next((entry for entry in state.enemies
                             if item.action_id == f"bomb_boss_{entry.entity_id}"), None)
                target = boss.position if boss else None
        progress = (round(state.player.position.distance_to(target) - predicted.distance_to(target), 1)
                    if target is not None else None)
        result: dict[str, Any] = {
            "horizon_frames": 12,
            "expected_move": forecast_move.__dict__,
            "estimated_move_px": estimated_step,
            "target_progress_px": progress,
            "blocked_reason": blocked_reason,
            "basis": "current grid and Lua direction safety; dynamic motion uncertain",
        }
        if door:
            result.update({
                "target_room_type": door.target_room_type,
                "target_room_index": door.target_room_index,
                "unvisited": door.target_room_index not in state.visited_room_indices,
                "returns_to_previous_room": door.target_room_index == state.previous_room_index,
                "keys_consumed_on_entry": 1 if door.locked else 0,
                "continuation": "unlock_and_enter" if door.locked else "enter_room",
            })
        elif item.mode == "recovery":
            result["continuation"] = "retry_selected_door_after_reposition"
        return result

    def entity_record(entity: Any) -> dict[str, Any]:
        offset = {
            "x": round(entity.position.x - state.player.position.x, 1),
            "y": round(entity.position.y - state.player.position.y, 1),
        }
        return {
            "type": entity.kind,
            "variant": entity.variant,
            "subtype": entity.subtype,
            "state": entity.state,
            "telegraph": entity.telegraph,
            "offset": offset,
            "velocity": {"x": round(entity.velocity.x, 1), "y": round(entity.velocity.y, 1)},
            "hp": round(entity.hit_points, 1),
        }

    def candidate_record(item: Action) -> dict[str, Any]:
        mobility = _mobility_after_move(state, item.move)
        return {
            "id": item.action_id,
            "mode": item.mode,
            "target": item.target,
            "move": item.move.__dict__,
            "shoot": item.shoot.__dict__,
            "waypoint": item.waypoint.__dict__ if item.waypoint else None,
            "macro_horizon_frames": item.macro_horizon_frames,
            "wall_clearance": mobility if mobility is not None else geometry.get("wall_clearance_neighbors", 4),
            "line_of_fire": geometry.get("line_of_fire", False) if item.shoot != Vec2() else None,
            "projectile_ttc_frames": geometry.get("nearest_projectile_ttc_frames"),
            "risk": "high" if geometry.get("nearest_projectile_imminent") else ("medium" if item.mode == "combat" else "low"),
            "forecast": action_forecast(item),
        }

    candidates = list(candidate_set.admissible_candidates)
    if candidate_set.policy == "combat":
        threats = geometry.get("projectile_threats", [])[:4]
        relevant_enemies = sorted(state.enemies, key=lambda item: item.position.distance_to(state.player.position))[:4]
        return {
            "schema_version": SCHEMA_VERSION,
            "policy": "combat",
            "phase": candidate_set.phase,
            "player": {
                "hp": round(state.player.hit_points, 1),
                "position": state.player.position.__dict__,
                "velocity": state.player.velocity.__dict__,
                "tear_range": round(state.player.tear_range, 1),
                "tear_speed": round(state.player.tear_speed, 2),
            },
            "boss_bomb": {"available": any(item.action_id.startswith("bomb_boss_") for item in candidates),
                          "bombs": state.bombs, "already_placed": state.bomb_placed},
            "enemies": [entity_record(item) for item in relevant_enemies],
            "projectile_threats": threats,
            "geometry": {
                "nearest_enemy_distance": geometry.get("nearest_enemy_distance"),
                "enemy_range_margin": geometry.get("enemy_range_margin"),
                "wall_clearance_neighbors": geometry.get("wall_clearance_neighbors"),
                "line_of_fire": geometry.get("line_of_fire"),
                "line_of_fire_blocked": geometry.get("line_of_fire_blocked"),
                "nearest_projectile_ttc_frames": geometry.get("nearest_projectile_ttc_frames"),
                "nearest_projectile_imminent": geometry.get("nearest_projectile_imminent"),
                "tracking_threats": geometry.get("tracking_threats", []),
                "nearest_tracking_bomb_distance": geometry.get("nearest_tracking_bomb_distance"),
                "nearest_tracking_bomb_ttc_frames": geometry.get("nearest_tracking_bomb_ttc_frames"),
                "nearest_tracking_bomb_imminent": geometry.get("nearest_tracking_bomb_imminent", False),
            },
            "feedback": {
                "movement_blocked": state.movement_blocked,
                "movement_progress": round(state.movement_progress, 2),
                "last_action_id": state.last_action_id,
                "action_age_frames": state.action_age_frames,
                "combat_stuck": state.combat_stuck,
                "recent_actions": list(state.recent_actions),
            },
            "candidates": [candidate_record(item) for item in candidates],
        }
    loot_candidates = [item for item in candidates if item.mode in _LOOT_MODES]
    if candidate_set.policy == "loot":
        return {
        "schema_version": SCHEMA_VERSION,
        "policy": "loot",
        "phase": candidate_set.phase,
        "player": {
            "hp": round(state.player.hit_points, 1),
            "red_hearts": state.red_hearts,
            "max_hearts": state.max_hearts,
            "soul_hearts": state.soul_hearts,
            "black_hearts": state.black_hearts,
            "bone_hearts": state.bone_hearts,
            "eternal_hearts": state.eternal_hearts,
        },
        "resources": {"coins": state.coins, "keys": state.keys, "bombs": state.bombs},
        "recent_actions": list(state.recent_actions),
        "candidates": [
            candidate_record(item) | {
                "quality": next((pickup.quality for pickup in state.pickups if item.action_id.endswith(f"_{pickup.entity_id}")), 0),
                "price": next((pickup.price for pickup in state.pickups if item.action_id.endswith(f"_{pickup.entity_id}")), 0),
                "requires_bomb": next((hazard.requires_bomb for hazard in state.hazards if item.action_id.endswith(f"_{hazard.entity_id}")), False),
                "distance": round(next((hazard.position.distance_to(state.player.position) for hazard in state.hazards if item.action_id.endswith(f"_{hazard.entity_id}")), 0.0), 1),
            }
            for item in loot_candidates
        ],
        }
    # Navigation and emergency are intentionally compact too. They contain
    # only the facts needed to choose among already validated action ids.
    return {
        "schema_version": SCHEMA_VERSION,
        "policy": candidate_set.policy,
        "phase": candidate_set.phase,
        "player": {
            "hp": round(state.player.hit_points, 1),
            "position": state.player.position.__dict__,
            "velocity": state.player.velocity.__dict__,
        },
        "geometry": {
            "wall_clearance_neighbors": geometry.get("wall_clearance_neighbors"),
            "nearest_projectile_ttc_frames": geometry.get("nearest_projectile_ttc_frames"),
            "nearest_projectile_imminent": geometry.get("nearest_projectile_imminent"),
            "line_of_fire": geometry.get("line_of_fire"),
            "line_of_fire_blocked": geometry.get("line_of_fire_blocked"),
            "tracking_threats": geometry.get("tracking_threats", []),
            "nearest_tracking_bomb_distance": geometry.get("nearest_tracking_bomb_distance"),
            "nearest_tracking_bomb_ttc_frames": geometry.get("nearest_tracking_bomb_ttc_frames"),
            "nearest_tracking_bomb_imminent": geometry.get("nearest_tracking_bomb_imminent", False),
        },
        "transition": {
            "phase": state.transition_phase,
            "planned_goal": state.planned_goal,
            "room_index": state.layout.room_index,
        },
        "feedback": {
            "movement_blocked": state.movement_blocked,
            "movement_progress": round(state.movement_progress, 2),
            "action_age_frames": state.action_age_frames,
            "last_action_id": state.last_action_id,
            "move_resolution_reason": state.move_resolution_reason,
            "safe_move_directions": state.safe_move_directions,
            "recovery_reason": state.recovery_reason,
            "stall_frames": state.stall_frames,
            "recent_actions": list(state.recent_actions),
        },
        "candidates": [candidate_record(item) for item in candidates],
    }


def action_label(action_id: str) -> str:
    """Return the player-facing Chinese description for a controller action."""
    labels = {
        "hold_and_fire": "原地射击",
        "advance_and_fire": "接近敌人并射击",
        "advance_and_evade_fire": "接近并躲避弹幕射击",
        "retreat_and_fire": "后退并射击",
        "strafe_left": "向左侧移并射击",
        "strafe_right": "向右侧移并射击",
        "reposition_and_fire": "脱离卡点并射击",
        "reposition_to_fire_lane": "移动到无遮挡射击线",
        "evade_projectile": "躲避弹幕",
        "retreat_from_enemy": "远离近身敌人并射击",
        "evade_ghost_bomb": "远离追踪鬼炸弹",
        "evade_ghost_bomb_left": "向左躲开追踪鬼炸弹",
        "evade_ghost_bomb_right": "向右躲开追踪鬼炸弹",
        "mandatory_evade_and_fire": "强制躲避并射击",
        "dodge_charge_left": "向左躲开冲刺",
        "dodge_charge_right": "向右躲开冲刺",
        "wait_for_hazard_observation": "等待障碍观测",
        "wait_for_hazard_clear": "等待障碍清除",
        "wait_for_room_clear": "等待确认清房",
        "wait_for_boss_reward": "等待 Boss 奖励生成",
        "wait_for_exit": "等待出口规划",
        "wait_for_recovery_route": "等待安全脱困方向",
        "dead_wait": "死亡等待重开",
    }
    if action_id in labels:
        return labels[action_id]
    if action_id.startswith("enter_door_"):
        return f"进入 {action_id.removeprefix('enter_door_')} 号门"
    if action_id.startswith("recover_"):
        return f"脱困：前往{action_id.removeprefix('recover_')}侧安全站位"
    if action_id.startswith("enter_boss_exit_"):
        return "进入 Boss 房陷阱门"
    if action_id.startswith("take_item_"):
        return f"拾取道具 {action_id.removeprefix('take_item_')}"
    if action_id.startswith("take_pickup_"):
        return f"拾取资源 {action_id.removeprefix('take_pickup_')}"
    if action_id.startswith("keep_trinket_"):
        return "保留当前饰品"
    if action_id.startswith("open_chest_"):
        return f"打开宝箱 {action_id.removeprefix('open_chest_')}"
    if action_id.startswith("clear_hazard_"):
        return f"清理障碍 {action_id.removeprefix('clear_hazard_')}"
    if action_id.startswith("bomb_hazard_"):
        return f"炸毁障碍 {action_id.removeprefix('bomb_hazard_')}"
    if action_id.startswith("bomb_boss_"):
        return "用炸弹攻击 Boss"
    if action_id.startswith("bomb_secret_"):
        return "炸开隐藏房入口"
    if action_id.startswith("bomb_super_secret_"):
        return "炸开超级隐藏房入口"
    if action_id.startswith("press_button_"):
        return "踩下房间按钮"
    if action_id.startswith("shoot_tnt_"):
        return "远距离引爆炸药桶"
    if action_id.startswith("movement_penalty_"):
        return "脱困重定位"
    if action_id.startswith("repeat_penalty_"):
        return "重复动作脱困"
    return action_id or "等待"


_DECISION_RULE_SECTIONS = (
    {
        "id": "pipeline",
        "title": "总决策流水线",
        "summary": "候选动作严格按以下顺序收敛，Jev 只能在当前阶段暴露的候选中选择一个动作。",
        "rules": (
            "1. 障碍观测无效：等待有效障碍观测，不打开出口。",
            "2. 房间已清空：附近火焰会妨碍拾取时先清火；其他奖励先于普通障碍和 TNT；Boss 清房至少等待 60 游戏帧并拾取奖励后再离开。",
            "3. 房间未清空且有弹幕威胁：优先躲避；弹幕尚未迫近且敌人超出射程时允许安全接近。",
            "4. 房间未清空且有敌人：优先战斗；障碍挡住敌人或 combat_stuck 时才清理障碍。",
            "5. 房间未清空但没有可确认敌人：等待 room_clear，不凭空开火或走门。",
        ),
        "source": "candidate_actions",
    },
    {
        "id": "combat",
        "title": "战斗与弹幕规则",
        "summary": "战斗动作保持移动与射击分离，并按射程、敌人距离、弹幕紧迫程度决定候选。",
        "rules": (
            "弹幕尚未迫近且敌人超出射程：允许 advance_and_evade_fire，同时保留左右侧移。",
            "有近迫弹幕：只提供 retreat_and_fire 或 strafe_left/strafe_right。",
            "检测到向角色闭合的鬼炸弹：立即停止射击并远离；躲避方向由 Lua 逐帧安全检查。",
            "高速敌人朝角色冲刺且预计经过角色位置：提供离开冲刺轨迹的左右侧移。",
            "没有敌人但有弹幕：不编造射击目标；躲避动作不携带射击方向。",
            "Poky/Slide 与 Wall Hugger 刺块由 Lua 作为移动危险物上报，不计入可射杀敌人；没有真实战斗目标时停止旧射击动作。",
            "上一动作被阻挡或位移接近零：优先 reposition_and_fire，脱离墙角后继续射击。",
            "射线被墙或障碍挡住：提供无射击的 reposition_to_fire_lane，先移动到无遮挡位置再开火。",
            "wait 或 movement-only 战斗恢复动作不会被 Lua 自动补成瞄准射击。",
            "敌人超出有效射程：只提供 advance_and_fire；敌人过近：优先 retreat_and_fire。",
            "安全距离内且没有紧迫弹幕：hold_and_fire；瞄准使用有限提前量。",
        ),
        "source": "combat_actions, _predictive_enemy_aim, _safety_filter",
    },
    {
        "id": "hazard",
        "title": "障碍与 X 石头规则",
        "summary": "火堆、大便等障碍从实体实际位置处理，角色不能直接走向危险障碍。",
        "rules": (
            "障碍挡住敌人火线或战斗卡住：先寻找可达且在射程内的射击位置，到位后才开火。",
            "X 石头和超级 X 石头：有炸弹时选择相邻可达落弹格，实际距离不超过 70 像素；先确认撤离通道再放弹。",
            "普通隐藏房墙位优先于超级隐藏房；只尝试已确认的 1×1 相邻房间，每面墙最多放一枚炸弹。",
            "红色大便会复活且伤害角色，只作为持续危险格绕开，不当作普通大便反复清理。",
            "无炸弹时跳过 X 石头，不生成不可执行的开石动作。",
            "关闭出口优先踩可达按钮；活动 TNT 寻找爆炸半径外、当前泪弹射程内的射击位置，无进展后暂时忽略。",
            "障碍无距离进展时加入当前房间忽略集合；目标消失则清除旧动作并重新规划。",
        ),
        "source": "mechanism_actions, hazard_actions, bomb_wall_actions, _active_hazards, _bomb_hazards",
    },
    {
        "id": "rewards",
        "title": "奖励、道具与宝箱规则",
        "summary": "清房后将多个真实可执行奖励目标交给当前 Provider 选择。",
        "rules": (
            "宝箱优先级：红箱、永恒箱、锁箱、拟态/尖刺/鬼箱，再到普通木箱。",
            "可购买道具必须价格可观测且不超过硬币数量；不可负债购买。",
            "资源掉落按钥匙、炸弹、魂/黑/永恒/骨心等价值排序。",
            "福袋作为可拾取资源；饰品槽已满时同时提供保留当前和更换地面饰品两种选择。",
            "持有胶囊由 Lua 一次性使用，并回传使用结果。",
            "红心已满、魂心达到保守上限或已有永恒心时跳过对应掉落。",
            "奖励目标无进展或消失：放弃旧目标，继续剩余奖励或出口规划。",
            "Boss 房的可见奖励必须先拾取；只有奖励消失或被运行时明确标记不可达后才允许进入陷阱门。",
            "普通房离门前逐次复查可达奖励，新奖励抢占缓存门动作和迟到的远程选门结果。",
        ),
        "source": "strategic_actions, _pickup_score",
    },
    {
        "id": "route",
        "title": "楼层路线规则",
        "summary": "本地楼层图先提出目标；多个安全未探索出口可由 Jev 选择，选定后持续执行。",
        "rules": (
            "优先未访问 Treasure 房，再选择未访问 Boss 房。",
            "普通安全分支优先于 curse、sacrifice、challenge 等风险分支。",
            "商店会结合硬币数量降权；secret/super_secret 只有明确解锁或已炸开且门已打开才可进入。",
            "本房刚炸开的隐藏门若确认开启且未锁，会覆盖先前普通门承诺；完成当前战斗与奖励后优先进入。",
            "没有本地前沿时沿已知楼层图路由；死路才允许返回入口房。",
            "已访问所有可见门不代表楼层完成；优先返回已知 Boss 房，否则从安全且较少走过的门继续寻找进度。",
            "只有在已对齐门槛且另有开放出口时才短暂冷却受阻门；冷却结束或门状态改变后重新评估。",
        ),
        "source": "Controller._plan_next_door",
    },
    {
        "id": "safety",
        "title": "安全与运行时兜底",
        "summary": "本地反射层可以覆盖 Jev，优先保证输入不会把角色推向危险状态。",
        "rules": (
            "网格碰撞、墙角和不可行走方向会改写移动向量，保留独立射击方向。",
            "活动地刺和敌方伤害地面进入危险格；冲刺轨迹在 Lua 本地即时侧移避让。",
            "追踪鬼炸弹单独作为高优先级危险效果上报，不能当作普通炸弹或可攻击敌人。",
            "连续无位移达到阈值时触发 movement penalty，短暂执行脱困重定位。",
            "确认导航停滞后把 Lua 验证过的短距离安全站位交给 Jev 选择；单一候选本地执行，远程请求限频。",
            "超过 max_action_age_frames 的异步 Jev 结果丢弃，改用保守动作。",
            "死亡时清空旧动作、停止新 Jev 请求，等待 Lua 自动重开。",
            "Jev 超时、网络错误、低置信度或没有 API key 时使用 deterministic fallback。",
        ),
        "source": "Controller.receive_state, conservative_action, _safety_filter",
    },
)


def decision_rules() -> dict[str, Any]:
    """Expose the source-owned rule catalog used by the web dashboard."""
    functions = (candidate_actions, build_candidate_set, hard_rule_filter, combat_policy, loot_policy, navigation_policy, recovery_actions, mechanism_actions, hazard_actions, combat_actions, strategic_actions, conservative_action, _safety_filter)
    revisions = {
        function.__name__: hashlib.sha1(inspect.getsource(function).encode("utf-8")).hexdigest()[:12]
        for function in functions
    }
    action_ids = (
        "advance_and_fire", "advance_and_evade_fire", "hold_and_fire", "retreat_and_fire",
        "strafe_left", "strafe_right", "reposition_and_fire", "reposition_to_fire_lane", "route_to_firing_lane", "evade_projectile",
        "retreat_from_enemy", "mandatory_evade_and_fire", "dodge_charge_left", "dodge_charge_right",
        "evade_ghost_bomb", "evade_ghost_bomb_left", "evade_ghost_bomb_right",
        "clear_hazard_<id>", "bomb_hazard_<id>", "bomb_boss_<id>", "bomb_secret_<slot>", "bomb_super_secret_<slot>", "open_chest_<id>", "take_item_<id>",
        "take_pickup_<id>", "keep_trinket_<id>", "press_button_<id>", "shoot_tnt_<id>", "enter_door_<slot>", "enter_boss_exit_<id>", "wait_for_hazard_observation",
        "wait_for_hazard_clear", "wait_for_room_clear", "wait_for_boss_reward", "wait_for_exit", "wait_for_bomb", "dead_wait",
        "wait_for_safety_filter", "wait_for_recovery_route",
        "await_model",
        "recover_up", "recover_down", "recover_left", "recover_right",
        "movement_penalty_reposition", "repeat_penalty_reposition",
    )
    return {
        "sections": [section | {"rules": list(section["rules"])} for section in _DECISION_RULE_SECTIONS],
        "actions": [{"id": action_id, "label": action_label(action_id)} for action_id in action_ids],
        "source_files": ["src/isaac_jev/decision.py", "src/isaac_jev/runtime.py"],
        "source_revisions": revisions,
    }


def _unit(vector: Vec2) -> Vec2:
    magnitude = (vector.x * vector.x + vector.y * vector.y) ** 0.5
    return Vec2() if magnitude == 0 else Vec2(round(vector.x / magnitude), round(vector.y / magnitude))


def _cardinal(vector: Vec2) -> Vec2:
    """Isaac accepts one cardinal fire direction, not a diagonal chord."""
    if abs(vector.x) >= abs(vector.y) and vector.x:
        return Vec2(1 if vector.x > 0 else -1, 0)
    if vector.y:
        return Vec2(0, 1 if vector.y > 0 else -1)
    return Vec2()


def _is_open(state: GameState, move: Vec2) -> bool:
    layout = state.layout
    if not layout.grid_width or not layout.grid_height or state.player_grid_index < 0:
        return True
    row, col = divmod(state.player_grid_index, layout.grid_width)
    dx, dy = int(move.x), int(move.y)
    # A short step back toward the current tile's center need not enter the
    # neighboring blocked tile. Require the live Lua collision check too.
    if bool(dx) != bool(dy):
        name = {(1, 0): "right", (-1, 0): "left", (0, 1): "down", (0, -1): "up"}.get((dx, dy))
        center = grid_cell_center(state, state.player_grid_index)
        if center is not None and state.safe_move_directions.get(name) == "safe":
            offset = (center.x-state.player.position.x)*dx + (center.y-state.player.position.y)*dy
            if 6 < offset <= 21 and state.player_grid_index not in layout.blocked | layout.danger_grid_indices:
                return True
    candidates = [(row + dy, col + dx)]
    if dx and dy:  # Do not cut diagonally through an obstacle corner.
        candidates.extend(((row, col + dx), (row + dy, col)))
    for next_row, next_col in candidates:
        if not (0 <= next_row < layout.grid_height and 0 <= next_col < layout.grid_width):
            return False
        if next_row * layout.grid_width + next_col in layout.blocked or next_row * layout.grid_width + next_col in layout.danger_grid_indices:
            return False
    return True


def _mobility_after_move(state: GameState, move: Vec2) -> int | None:
    """Return the number of cardinal exits after a move when grid data exists."""
    layout = state.layout
    if not layout.grid_width or not layout.grid_height or state.player_grid_index < 0:
        return None
    row, col = divmod(state.player_grid_index, layout.grid_width)
    next_row, next_col = row + int(move.y), col + int(move.x)
    if not (0 <= next_row < layout.grid_height and 0 <= next_col < layout.grid_width):
        return 0
    next_index = next_row * layout.grid_width + next_col
    if next_index in layout.blocked or next_index in layout.danger_grid_indices:
        return 0
    exits = 0
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        candidate_row, candidate_col = next_row + dy, next_col + dx
        if 0 <= candidate_row < layout.grid_height and 0 <= candidate_col < layout.grid_width:
            candidate_index = candidate_row * layout.grid_width + candidate_col
            if candidate_index not in layout.blocked and candidate_index not in layout.danger_grid_indices:
                exits += 1
    return exits


def _safe_move(state: GameState, preferred: Vec2, avoid_corner: bool | None = None) -> Vec2:
    lateral = Vec2(-preferred.y, preferred.x)
    candidates = (preferred, lateral, Vec2(-lateral.x, -lateral.y), Vec2(-preferred.x, -preferred.y), Vec2())
    valid = []
    for rank, candidate in enumerate(candidates):
        if not _is_open(state, candidate) or candidate in [item[1] for item in valid]:
            continue
        valid.append((rank, candidate))
    if not valid:
        return Vec2()
    if avoid_corner is None:
        avoid_corner = bool(state.enemies)
    if not avoid_corner or _mobility_after_move(state, Vec2()) is None:
        return valid[0][1]
    # A one-exit destination is a likely corner/dead-end. Prefer a lateral
    # escape with more room, while retaining the requested direction when the
    # choices have comparable mobility.
    scored = []
    for rank, candidate in valid:
        mobility = _mobility_after_move(state, candidate)
        score = (10 - rank) + (mobility or 0) * 4
        if candidate != Vec2() and mobility is not None and mobility <= 1:
            score -= 12
        # Do not replace an escape with a walk into a second nearby enemy.
        next_position = Vec2(state.player.position.x + candidate.x * 40, state.player.position.y + candidate.y * 40)
        for enemy in state.enemies:
            separation = next_position.distance_to(Vec2(enemy.position.x + enemy.velocity.x * 6, enemy.position.y + enemy.velocity.y * 6))
            if separation < 85:
                score -= (85 - separation) * 0.4
        for projectile in state.projectiles:
            future = Vec2(projectile.position.x + projectile.velocity.x * 6, projectile.position.y + projectile.velocity.y * 6)
            separation = next_position.distance_to(future)
            if separation < 48:
                score -= (48 - separation) * 0.8
        scored.append((score, -rank, candidate))
    return max(scored, key=lambda item: (item[0], item[1]))[2]


def _nearest(state: GameState, entities: tuple) -> Any | None:
    return min(entities, key=lambda entity: entity.position.distance_to(state.player.position), default=None)


def _is_stationary(entity: Any) -> bool:
    return abs(entity.velocity.x) + abs(entity.velocity.y) < 0.20


def _attack_distance(state: GameState, profile: PolicyProfile) -> float:
    # TearRange is reported by Lua in Isaac's pixel-like room units. Keep a
    # conservative margin so shots are not fired at the edge of the range.
    tear_range = float(getattr(state.player, "tear_range", 260.0) or 260.0)
    return max(140.0, min(320.0, tear_range * 0.72))


def _predictive_enemy_aim(state: GameState, enemy: Any) -> Vec2:
    """Aim at a bounded lead point instead of the enemy's stale position."""
    delta = Vec2(enemy.position.x - state.player.position.x, enemy.position.y - state.player.position.y)
    distance = delta.distance_to(Vec2())
    # Lua emits tears at ShotSpeed * 10 room units per frame. Limit the lead
    # so a reversing enemy cannot make the aim oscillate wildly.
    tear_speed = max(1.0, float(getattr(state.player, "tear_speed", 1.0) or 1.0) * 10.0)
    flight_frames = min(12.0, max(1.5, distance / tear_speed))
    velocity = getattr(enemy, "velocity", Vec2())
    predicted = Vec2(
        enemy.position.x + velocity.x * flight_frames,
        enemy.position.y + velocity.y * flight_frames,
    )
    return _cardinal(Vec2(predicted.x - state.player.position.x, predicted.y - state.player.position.y))


def _hazard_blocks_enemy(state: GameState, enemy: Any) -> bool:
    """Detect a destructible obstacle sitting between Isaac and an enemy.

    Isaac's entity list can contain enemies trapped behind poop or fire. In
    that situation repeatedly aiming at the enemy does not create progress;
    the local controller must expose obstacle removal as the only safe phase.
    """
    target = Vec2(enemy.position.x - state.player.position.x, enemy.position.y - state.player.position.y)
    length_sq = target.x * target.x + target.y * target.y
    if length_sq < 1.0:
        return False
    for hazard in state.hazards:
        if not hazard.destructible or hazard.entity_id in state.ignored_hazard_ids:
            continue
        offset = Vec2(hazard.position.x - state.player.position.x, hazard.position.y - state.player.position.y)
        projection = (offset.x * target.x + offset.y * target.y) / length_sq
        if projection <= 0.08 or projection >= 0.92:
            continue
        closest = Vec2(target.x * projection, target.y * projection)
        distance = Vec2(offset.x - closest.x, offset.y - closest.y).distance_to(Vec2())
        if distance <= 42.0:
            return True
    return False


def _opens_needed_door(state: GameState, barrier: Any) -> bool:
    """Spend an ordinary bomb only on a rock which repairs a necessary route."""
    if (not state.room_clear or state.enemies or barrier.grid_index<0
            or not state.layout.grid_width or state.bombs<=0):
        return False
    doors=[door for door in state.layout.doors if door_is_usable(door,state)
           and (door.target_room_index not in state.visited_room_indices
                or door.slot==state.planned_door_slot or door.target_is_boss)
           and door_path_distance(state,door)==float('inf')]
    if not doors:
        return False
    cell=frozenset({barrier.grid_index})
    future=replace(state,hazards=tuple(h for h in state.hazards if h!=barrier),
        layout=replace(state.layout,blocked=state.layout.blocked-cell,
            danger_grid_indices=state.layout.danger_grid_indices-cell))
    return any(door_path_distance(future,door)<float('inf') for door in doors)


def _active_hazards(state: GameState) -> tuple:
    return tuple(
        item for item in state.hazards
        if item.destructible
        and not (state.room_clear and item.kind=="red_poop")
        and (item.kind!="passage_rock" or _opens_needed_door(state,item))
        and item.entity_id not in state.ignored_hazard_ids
        and not (item.requires_bomb and state.bomb_placed and item.entity_id == state.bomb_target_id)
        and (not item.requires_bomb or state.bombs > 0)
        # Blue and purple fire cannot be damaged by tears. Preserve them as
        # route hazards, but reserve bomb actions until more than four bombs.
        and (item.kind not in {"blue_fire", "purple_fire"} or state.bombs > 4)
    )


def _bomb_hazards(state: GameState) -> tuple:
    return tuple(
        item for item in _active_hazards(state)
        if item.requires_bomb
    )


def _threatening_projectiles(state: GameState, profile: PolicyProfile) -> tuple:
    """Keep visible bullets that are close or moving toward the player."""
    threats = []
    for projectile in state.projectiles:
        offset = Vec2(state.player.position.x - projectile.position.x, state.player.position.y - projectile.position.y)
        distance = projectile.position.distance_to(state.player.position)
        closing = offset.x * projectile.velocity.x + offset.y * projectile.velocity.y > 0.25
        if distance <= profile.projectile_evade_radius or (closing and distance <= 260):
            threats.append(projectile)
    return tuple(threats)


def _tracking_bomb_threats(state: GameState, imminent_only: bool = False) -> tuple:
    """Return ghost bombs that are closing on Isaac, ordered by urgency."""
    threats = []
    for effect in state.danger_effects:
        if effect.kind not in {"ghost_bomb", "armed_bomb"}:
            continue
        offset = Vec2(state.player.position.x - effect.position.x,
                      state.player.position.y - effect.position.y)
        distance = effect.position.distance_to(state.player.position)
        closing_speed = (offset.x * effect.velocity.x + offset.y * effect.velocity.y) / max(distance, 1.0)
        ttc = distance / closing_speed if closing_speed > 0.01 else None
        if effect.kind == "armed_bomb":
            if distance <= effect.radius + 65:
                threats.append((0.0, distance, effect))
            continue
        imminent = bool((ttc is not None and ttc <= 24.0) or distance <= 150.0)
        if closing_speed > 0.01 and distance <= 260.0 and (not imminent_only or imminent):
            threats.append((ttc if ttc is not None else 999.0, distance, effect))
    threats.sort(key=lambda item: (item[0], item[1], item[2].entity_id))
    return tuple(item[2] for item in threats)


def tracking_bomb_actions(state: GameState) -> list[Action]:
    """Generate real escape directions; never stand still or fire at the bomb."""
    threat = _tracking_bomb_threats(state, imminent_only=False)
    if not threat:
        return []
    effect = threat[0]
    predicted = Vec2(effect.position.x + effect.velocity.x * 8,
                      effect.position.y + effect.velocity.y * 8)
    away = _unit(Vec2(state.player.position.x - predicted.x,
                      state.player.position.y - predicted.y))
    if not away.x and not away.y:
        away = Vec2(1, 0)
    directions = (
        ("evade_ghost_bomb", away, "move directly away from the closing ghost bomb"),
        ("evade_ghost_bomb_left", Vec2(-away.y, away.x), "sidestep left of the ghost bomb trajectory"),
        ("evade_ghost_bomb_right", Vec2(away.y, -away.x), "sidestep right of the ghost bomb trajectory"),
    )
    actions: list[Action] = []
    current_distance = state.player.position.distance_to(predicted)
    for action_id, desired, reason in directions:
        move = _safe_move(state, desired, avoid_corner=True)
        if not move.x and not move.y:
            continue
        direction = {(0, -1): "up", (0, 1): "down", (-1, 0): "left", (1, 0): "right"}.get((move.x, move.y))
        if direction and state.safe_move_directions.get(direction, "safe") != "safe":
            continue
        next_position = Vec2(state.player.position.x + move.x * 40,
                             state.player.position.y + move.y * 40)
        if next_position.distance_to(predicted) <= current_distance:
            continue
        if any(item.move == move for item in actions):
            continue
        actions.append(Action(action_id, move, Vec2(), mode="evade",
                              target="ghost bomb", reason=reason))
    return actions


def _projectile_imminent(state: GameState, projectile: Any, profile: PolicyProfile) -> bool:
    return projectile_is_imminent(state.player,projectile)


def _combat_firing_distance(target: Any, profile: PolicyProfile) -> float:
    finisher=target.kind==24 and (target.hit_points<=3.5 or 'regen' in target.telegraph.lower())
    reactive=(target.kind==99 or (target.kind==81 and target.variant==0)
              or (target.kind==24 and not finisher))
    return max(profile.enemy_safe_distance,185 if reactive else 0)


def _raw_candidate_actions(state: GameState, profile: PolicyProfile | None = None) -> list[Action]:
    profile = profile or PolicyProfile()
    if state.bomb_active:
        return [Action("wait_for_bomb", Vec2(), Vec2(), mode="wait", reason="wait for the bomb to open the rock or wall while retreating")]
    ghost_escape = tracking_bomb_actions(state)
    if ghost_escape:
        return ghost_escape
    if not state.hazards_observation_valid:
        return [Action("wait_for_hazard_observation", Vec2(), Vec2(), mode="wait", reason="wait for a valid obstacle observation before opening an exit")]
    if state.recovery_active and state.room_clear and not state.enemies:
        recovery = recovery_actions(state)
        if recovery:
            return recovery
        # A short walkable tile may end at a destructible barrier, so no
        # two-tile recovery waypoint exists. Clear a reachable firing target
        # instead of letting recovery permanently suppress obstacle removal.
        clearable=[item for item in hazard_actions(state) if item.mode=="hazard"]
        if clearable:
            return clearable
        short_recovery = recovery_actions(state, allow_short=True)
        if short_recovery:
            return short_recovery
        return [Action("wait_for_recovery_route", Vec2(), Vec2(), mode="wait",
                       reason="no Lua-confirmed safe recovery direction; recheck on next state")]
    # Room:IsClear() is authoritative for trap rooms. Some mechanical room
    # entities are exposed by the Lua API as NPCs even though they are not
    # enemies; never let those stale observations pin Isaac in combat.
    active_hazards = _active_hazards(state)
    unresolved_hazards = active_hazards or tuple(item for item in state.hazards if not item.destructible)

    # A native clear flag wins over stale enemy and projectile observations.
    # This is important for challenge/机关 rooms where Lua can still report
    # mechanical NPCs or lingering tears for a few frames after the room is
    # actually cleared. Resolve hazards first, then rewards and the planner's
    # single exit; never keep firing in a room that the game says is clear.
    if state.room_clear:
        nearby_fire = [hazard for hazard in active_hazards if hazard.kind == "fire" and (
            hazard.position.distance_to(state.player.position) < 100
            or any(hazard.position.distance_to(pickup.position) < 60 for pickup in state.pickups)
        )]
        if nearby_fire:
            clearable = hazard_actions(state)
            if clearable:
                return clearable
        rewards = loot_policy(state)
        if rewards:
            return rewards
        boss_wait = _boss_reward_wait_action(state)
        if boss_wait:
            return [boss_wait]
        mechanisms = mechanism_actions(state)
        if mechanisms and mechanisms[0].mode == "button":
            return mechanisms
        rock_actions = [action for action in hazard_actions(state) if action.action_id.startswith("bomb_hazard_")]
        if rock_actions:
            return rock_actions
        wall_actions = bomb_wall_actions(state)
        if wall_actions:
            return wall_actions
        boss_room = state.layout.is_boss or state.layout.room_type == "boss"
        if unresolved_hazards and not boss_room:
            clearable = hazard_actions(state)
            if clearable:
                return clearable
        if boss_room and state.boss_exit_available:
            return strategic_actions(state)
        if mechanisms:
            return mechanisms
        return strategic_actions(state)

    # Once every observed obstacle has been marked unreachable and no hostile
    # enemy remains, do not wait forever for a stale room-clear flag. The
    # planner may leave through the selected native door and record the failed
    # target in ignored_hazard_ids/ignored_pickup_ids.
    if not state.enemies and not unresolved_hazards and (state.ignored_hazard_ids or state.ignored_pickup_ids):
        return strategic_actions(state)

    threats = _threatening_projectiles(state, profile)
    if threats and (state.enemies or any(_projectile_imminent(state, item, profile) for item in threats)):
        return combat_actions(state, profile)

    # A repeated combat action can be a productive firing lane. Never turn
    # that alone, or one occluded enemy among several, into resource farming.
    if state.enemies:
        shootable = tuple(hazard for hazard in active_hazards if not hazard.requires_bomb)
        obstacle_state = replace(state, hazards=shootable)
        if (shootable and all(enemy.position.distance_to(state.player.position) > 130
                and _hazard_blocks_enemy(obstacle_state, enemy) for enemy in state.enemies)):
            clearable = hazard_actions(obstacle_state)
            if clearable:
                return clearable
            # A failed bomb or inaccessible firing lane may leave hazards in
            # the observation but no executable clear action. Keep fighting
            # instead of turning an empty list into permanent idle time.
        # A doorway barrier can disconnect the whole enemy enclosure without
        # lying on the direct ray to each enemy. Only clear it when no normal
        # firing lane exists and removing this exact barrier opens one. This
        # is route repair, not optional resource farming during combat.
        if (shootable and state.layout.grid_width
                and all(enemy.position.distance_to(state.player.position) > 130 for enemy in state.enemies)):
            def has_lane(observation):
                return any(firing_position(observation, enemy.position, enemy.grid_index,
                    minimum_range=_combat_firing_distance(enemy,profile),
                    avoid_dead_ends=enemy.kind not in {27,204}) is not None
                    for enemy in observation.attack_targets())
            if not has_lane(state):
                for barrier in shootable:
                    if barrier.grid_index<0:
                        continue
                    cell=frozenset({barrier.grid_index})
                    future=replace(state,hazards=tuple(h for h in state.hazards if h!=barrier),
                        layout=replace(state.layout,blocked=state.layout.blocked-cell,
                            shot_blocked=(state.layout.shot_blocked-cell if state.layout.shot_blocked is not None else None),
                            danger_grid_indices=state.layout.danger_grid_indices-cell))
                    if has_lane(future):
                        clearable=[a for a in hazard_actions(replace(state,hazards=(barrier,))) if a.mode=='hazard']
                        if clearable:
                            return clearable
        return combat_actions(state, profile)
    # An exit plate may be what makes the room clear in the first place.
    # Operate it after live enemies/projectiles, without waiting for IsClear.
    mechanisms = mechanism_actions(state)
    if mechanisms and mechanisms[0].mode == "button":
        return mechanisms
    # A live fire/poop obstacle can hide an enemy or block the only useful
    # firing lane. Clear it before combat; relying only on a 2-D line test is
    # unsafe because grid hazards and enemy hitboxes do not share coordinates.
    if unresolved_hazards:
        return hazard_actions(state)
    # Do not invent a target or fire at empty space when the room is not yet
    # confirmed clear and no hostile NPC was observed.
    return [Action("wait_for_room_clear", Vec2(), Vec2(), mode="wait", reason="wait for a confirmed room-clear state")]


def recovery_actions(state: GameState, *, allow_short: bool = False) -> list[Action]:
    """Offer distinct, locally walkable short waypoints during a confirmed stall."""
    directions = (("up", Vec2(0, -1)), ("down", Vec2(0, 1)),
                  ("left", Vec2(-1, 0)), ("right", Vec2(1, 0)))
    door = next((item for item in state.layout.doors if item.slot == state.recovery_target_door_slot), None)
    if (door is None or not door_is_usable(door, state)
            or not state.safe_move_directions):
        return []
    options: list[Action] = []
    for name, move in directions:
        if state.safe_move_directions.get(name) != "safe":
            continue
        if not _is_open(state, move):
            continue
        waypoint = Vec2(state.player.position.x + move.x * 64,
                        state.player.position.y + move.y * 64)
        if state.layout.grid_width and state.layout.grid_height and state.player_grid_index >= 0:
            row, col = divmod(state.player_grid_index, state.layout.grid_width)
            target_row, target_col = row + int(move.y) * 2, col + int(move.x) * 2
            blocked = state.layout.blocked | state.layout.danger_grid_indices
            if (not (0 <= target_row < state.layout.grid_height and 0 <= target_col < state.layout.grid_width)
                    or target_row * state.layout.grid_width + target_col in blocked):
                if not allow_short:
                    continue
                # A one-cell neck can require one step before a turn. Retain
                # the live Lua admission and prefer a real adjacent centre;
                # _is_open can also admit recentering within the current cell.
                next_row, next_col = row + int(move.y), col + int(move.x)
                if (0 <= next_row < state.layout.grid_height and 0 <= next_col < state.layout.grid_width
                        and next_row * state.layout.grid_width + next_col not in blocked):
                    target_index = next_row * state.layout.grid_width + next_col
                else:
                    target_index = state.player_grid_index
                waypoint = grid_cell_center(state, target_index)
                if waypoint is None or waypoint.distance_to(state.player.position) <= 6:
                    continue
        action_id = f"recover_{name}"
        if state.movement_blocked and state.last_action_id == action_id:
            continue
        if door and waypoint.distance_to(door.position) < 32:
            continue
        options.append(Action(
            action_id, move, Vec2(), mode="recovery", waypoint=waypoint,
            target=f"short safe waypoint {name}",
            reason=f"{state.recovery_reason}; reposition before retrying door {state.recovery_target_door_slot}",
        ))
    if door:
        options.sort(key=lambda item: item.waypoint.distance_to(door.position) if item.waypoint else float("inf"))
    return options[:3]


def mechanism_actions(state: GameState) -> list[Action]:
    """Operate an exit button, then clear a nearby TNT obstacle from range."""
    closed_exit = any(door.open_known and not door.open for door in state.layout.doors)
    if closed_exit:
        buttons = [event for event in state.layout.grid_events
                   if event.kind == "button" and event.active and not event.triggered
                   and path_distance(state, event.position, event.grid_index,allow_timed=True) < float("inf")]
        if buttons:
            button = min(buttons, key=lambda event: path_distance(state, event.position, event.grid_index,allow_timed=True))
            return [Action(
                f"press_button_{button.entity_id}", move_towards(state, button.position, button.grid_index), Vec2(),
                mode="button", target="exit button", reason="press the reachable plate to unlock closed exits",
                waypoint=button.position,
            )]
    tnts = [event for event in state.layout.grid_events if event.kind == "tnt" and event.active
            and event.entity_id not in state.ignored_hazard_ids]
    if tnts:
        actions = []
        for tnt in sorted(tnts, key=lambda event: event.position.distance_to(state.player.position))[:4]:
            lane = firing_position(state, tnt.position, tnt.grid_index, minimum_range=160)
            if lane is None:
                continue
            position, index, direction = lane
            approaching = position.distance_to(state.player.position) > 22
            actions.append(Action(
                f"shoot_tnt_{tnt.entity_id}", move_towards(state, position, index) if approaching else Vec2(),
                Vec2() if approaching else direction,
                mode="tnt", target="TNT barrel",
                reason="approach a reachable firing lane inside tear range and outside the blast radius",
                waypoint=position if approaching else None,
            ))
        return actions
    return []


def hazard_actions(state: GameState) -> list[Action]:
    """Offer distinct real obstacles while keeping the local first choice stable."""
    targets = sorted(
        _active_hazards(state),
        key=lambda item: (not item.requires_bomb, item.position.distance_to(state.player.position), item.entity_id),
    )
    if state.last_action_mode in {"hazard", "bomb"}:
        active_target = next(
            (item for item in targets if state.last_action_id in {f"clear_hazard_{item.entity_id}", f"bomb_hazard_{item.entity_id}"}),
            None,
        )
        if active_target is not None:
            targets = [active_target]
    if not targets:
        return [Action("wait_for_hazard_clear", Vec2(), Vec2(), mode="wait", reason="observed obstacles are not marked destructible")]
    actions: list[Action] = []
    for target in targets:
        if len(actions)>=3:
            break
        delta = Vec2(target.position.x - state.player.position.x, target.position.y - state.player.position.y)
        distance = target.position.distance_to(state.player.position)
        if target.kind in {"blue_fire", "purple_fire"} and state.bombs <= 4:
            # It is an invulnerable route obstacle until the resource reserve
            # is available; never turn it into a tear or bomb command.
            continue
        if target.requires_bomb:
            site = bombing_position(state, target.position, target.grid_index)
            if site is None:
                continue
            position, index = site
            actions.append(Action(
                f"bomb_hazard_{target.entity_id}", move_towards(state, position, index), Vec2(),
                mode="bomb", target=target.kind,
                reason=(f"bomb {target.kind} at {distance:.0f} pixels only with more than four bombs, then retreat"
                        if target.kind in {"blue_fire", "purple_fire"}
                        else f"break {target.kind} at {distance:.0f} pixels with one bomb, then retreat"),
                bomb_site=position,
            ))
            continue
        lane = firing_position(state, target.position, target.grid_index, minimum_range=70 if target.kind == "fire" else 75)
        if lane is None:
            continue
        position, index, direction = lane
        lane_delta = Vec2(target.position.x - state.player.position.x, target.position.y - state.player.position.y)
        approaching = (position.distance_to(state.player.position) > 18
                       or min(abs(lane_delta.x), abs(lane_delta.y)) > 14
                       or distance < (70 if target.kind == "fire" else 75))
        actions.append(Action(
            f"clear_hazard_{target.entity_id}", move_towards(state, position, index) if approaching else Vec2(),
            Vec2() if approaching else direction,
            mode="hazard", target=target.kind,
            reason=f"approach a clear firing lane, then destroy {target.kind} from {distance:.0f} pixels",
            waypoint=position,
        ))
    return actions


def bomb_wall_actions(state: GameState) -> list[Action]:
    """Try known, unbombed hidden-room walls after X rocks."""
    if state.bombs <= 0:
        return []
    for wall in sorted(state.layout.bomb_walls, key=lambda item: (item.room_type != "secret", item.slot)):
        if wall.bombed or -200000 - wall.slot in state.ignored_hazard_ids or wall.room_type not in {"secret", "super_secret"}:
            continue
        if path_distance(state, wall.site, wall.grid_index) == float("inf"):
            continue
        return [Action(
            f"bomb_{wall.room_type}_{wall.slot}", move_towards(state, wall.site, wall.grid_index), Vec2(),
            mode="bomb_wall", target=wall.room_type,
            reason="place one bomb near the confirmed hidden-room wall and retreat before the blast",
            bomb_site=wall.site,
        )]
    return []


def combat_actions(state: GameState, profile: PolicyProfile | None = None) -> list[Action]:
    profile = profile or PolicyProfile()
    enemy = _nearest(state, state.attack_targets())
    projectile_candidates = _threatening_projectiles(state, profile)
    projectile = _nearest(state, projectile_candidates)
    aim = _predictive_enemy_aim(state, enemy) if enemy else Vec2()
    def safe_firing_distance(target):
        return _combat_firing_distance(target,profile)
    def safe_firing_axis(target):
        # Monstro II fires horizontally. A rock can block the native local
        # dodge, so the long route must also lead to a vertical firing lane.
        if target.kind == 43 and target.variant == 0:
            return "vertical"
        if target.kind in {39, 49}:
            animation = target.telegraph.lower()
            if "horiz" in animation:
                return "vertical"
            if any(part in animation for part in ("vert", "up", "down")):
                return "horizontal"
        return None
    def with_boss_bomb(actions: list[Action]) -> list[Action]:
        # Give the frame-level controller a route around walls, rather than
        # letting a locally aligned but obstructed target pin it in place.
        if state.layout.grid_width and state.enemies:
            lanes = []
            def finisher_priority(item):
                return int(not (item.kind == 24 and "regen" in item.telegraph.lower()))
            for target in sorted(state.attack_targets(), key=lambda item: (finisher_priority(item), item.position.distance_to(state.player.position)))[:4]:
                lane = firing_position(state, target.position, target.grid_index,
                                       minimum_range=safe_firing_distance(target),
                                       avoid_dead_ends=target.kind not in {27,204},
                                       firing_axis=safe_firing_axis(target))
                if lane is not None:
                    position, index, _ = lane
                    lanes.append((finisher_priority(target),path_distance(state, position, index), position, index))
            if lanes:
                _, _, position, index = min(lanes, key=lambda item: item[:2])
                route_move = move_towards(state, position, index)
                if position.distance_to(state.player.position) > 22 and route_move != Vec2():
                    route = Action("route_to_firing_lane", route_move, Vec2(), mode="combat",
                        waypoint=position, reason="follow a reachable firing lane around obstacles; evade live threats each frame")
                    actions = [route] + [replace(item, waypoint=position) for item in actions]
        boss_room = state.layout.is_boss or state.layout.room_type == "boss"
        boss_target = min(
            (item for item in state.attack_targets() if item.is_boss
             and 55.0 <= item.position.distance_to(state.player.position) <= 110.0),
            key=lambda item: item.position.distance_to(state.player.position), default=None,
        )
        if (boss_room and boss_target is not None and state.bombs > 0
                and not state.bomb_active and not state.bomb_placed and not state.bomb_error
                and not _threatening_projectiles(state, profile)
                and any(value == "safe" for value in state.safe_move_directions.values())):
            actions.insert(0, Action(
                f"bomb_boss_{boss_target.entity_id}", Vec2(), Vec2(), mode="bomb",
                target="boss", reason="Boss is within bomb blast range; place one bomb then retreat through a clear corridor",
                bomb_site=state.player.position,
            ))
        return actions
    for charger in state.enemies:
        speed = (charger.velocity.x ** 2 + charger.velocity.y ** 2) ** 0.5
        offset = Vec2(state.player.position.x - charger.position.x, state.player.position.y - charger.position.y)
        closing = offset.x * charger.velocity.x + offset.y * charger.velocity.y > 0
        predicted = Vec2(charger.position.x + charger.velocity.x * 10,
                         charger.position.y + charger.velocity.y * 10)
        if speed >= 3.5 and closing and offset.distance_to(Vec2()) < 190 and predicted.distance_to(state.player.position) < 80:
            side = _cardinal(Vec2(-charger.velocity.y, charger.velocity.x))
            opposite = Vec2(-side.x, -side.y)
            choices = [Action("dodge_charge_left", side, aim, mode="combat", reason="leave the charging enemy's projected lane"),
                       Action("dodge_charge_right", opposite, aim, mode="combat", reason="leave the charging enemy's projected lane")]
            return with_boss_bomb([choice for choice in choices if _is_open(state, choice.move)] or [
                Action("retreat_and_fire", _safe_move(state, _unit(offset), avoid_corner=True), aim,
                       mode="combat", reason="charging lane has no safe side route")])
    threat = _unit(Vec2(state.player.position.x - projectile.position.x, state.player.position.y - projectile.position.y)) if projectile else Vec2()
    if not threat.x and not threat.y:
        threat = Vec2(-aim.x, -aim.y)
    lateral = _safe_move(state, Vec2(-threat.y, threat.x), avoid_corner=True)
    opposite_lateral = _safe_move(state, Vec2(threat.y, -threat.x), avoid_corner=True)
    if projectile and not enemy:
        retreat = _safe_move(state, threat, avoid_corner=True)
        movement = lateral if lateral != Vec2() else retreat
        # Trap fire may be perpetual until its plate is pressed. Keep the
        # reachable plate as a route goal while Lua chooses a safe step from
        # the current projectiles; an emergency must not erase that goal.
        mechanism = next((item for item in mechanism_actions(state) if item.mode == "button"), None)
        return [Action("evade_projectile", movement, Vec2(), mode="combat",
                       waypoint=mechanism.waypoint if mechanism else None,
                       reason="dodge live trap fire without inventing a hostile shooting target")]
    # When the Lua observation contains an imminent projectile, standing still
    # or closing distance is never an admissible choice.
    if projectile:
        distance = enemy.position.distance_to(state.player.position) if enemy else 0.0
        attack_distance = max(_attack_distance(state, profile), profile.enemy_safe_distance * 1.25)
        if enemy and distance > attack_distance and not _projectile_imminent(state, projectile, profile):
            approach = _safe_move(state, move_towards(state, enemy.position))
            if approach.x or approach.y:
                return with_boss_bomb([
                    Action("advance_and_evade_fire", approach, aim, mode="combat", reason="close to tear range while the projectile is not imminent"),
                    Action("strafe_left", lateral, aim, mode="combat", reason="sidestep the distant projectile while firing"),
                    Action("strafe_right", opposite_lateral, aim, mode="combat", reason="sidestep opposite the distant projectile while firing"),
                ])
        return with_boss_bomb([
            Action("retreat_and_fire", _safe_move(state, threat, avoid_corner=True), aim, mode="combat", reason="move away from the nearest projectile while firing"),
            Action("strafe_left", lateral, aim, mode="combat", reason="sidestep the nearest projectile while firing"),
            Action("strafe_right", opposite_lateral, aim, mode="combat", reason="sidestep opposite the nearest projectile while firing"),
        ])
    if not enemy:
        return [Action("evade_projectile", threat, Vec2(), mode="combat", reason="avoid a projectile without inventing a firing target")]
    # A blocked/zero-progress combat move means Isaac is likely pressing into
    # a wall or enemy near a corner. Reposition laterally before resuming the
    # normal approach/hold policy, while keeping the firing direction fixed.
    if state.movement_blocked or (
        state.last_action_mode == "combat"
        and state.last_action_id in {"advance_and_fire", "advance_and_evade_fire", "retreat_and_fire", "strafe_left", "strafe_right", "reposition_and_fire"}
        and state.movement_progress < 0.05
    ):
        away = _unit(Vec2(state.player.position.x - enemy.position.x, state.player.position.y - enemy.position.y))
        lateral = Vec2(-away.y, away.x)
        reposition = _safe_move(state, lateral, avoid_corner=True)
        if not reposition.x and not reposition.y:
            reposition = _safe_move(state, Vec2(-lateral.x, -lateral.y), avoid_corner=True)
        if reposition.x or reposition.y:
            return with_boss_bomb([Action(
                "reposition_and_fire", reposition, aim, mode="combat",
                reason="leave the blocked wall/corner while maintaining a safe firing position",
            )])
    distance = enemy.position.distance_to(state.player.position)
    geometry = state.geometry_features()
    attack_distance = max(_attack_distance(state, profile), profile.enemy_safe_distance * 1.25)
    if _is_stationary(enemy) and (geometry.get("line_of_fire_blocked") or
            (distance <= attack_distance and not geometry.get("line_of_fire")) or enemy.kind in {27,204}):
        lane = firing_position(state, enemy.position, enemy.grid_index,
                               minimum_range=safe_firing_distance(enemy),
                               avoid_dead_ends=enemy.kind not in {27,204},
                               firing_axis=safe_firing_axis(enemy))
        # Closed Hosts in a narrow alcove can have no reachable lane at the
        # preferred distance. An 80px lane still clears their body; the native
        # planner continues to veto actual contact, bombs, beams and bullets.
        if lane is None and enemy.kind in {27, 204}:
            lane = firing_position(state, enemy.position, enemy.grid_index, minimum_range=70)
        if lane is None and enemy.kind in {27, 204} and enemy.variant == 0:
            # The observed rock corridor exposes only the adjacent 40px cell.
            # This enemy is fixed in place; native body/bullet guards still
            # apply and it waits for an actual vulnerable firing window.
            lane = firing_position(state, enemy.position, enemy.grid_index, minimum_range=35)
        if lane is not None:
            position, index, _shoot = lane
            move = move_towards(state, position, index)
            if move != Vec2() and _is_open(state, move):
                return with_boss_bomb([Action(
                    "reposition_to_fire_lane", move, Vec2(), mode="combat", waypoint=position,
                    reason="align a walkable cardinal firing lane before shooting at a stationary enemy",
                )])
            if enemy.kind in {27,204} and move == Vec2() and state.player.position.distance_to(position) <= 14:
                return with_boss_bomb([Action(
                    "hold_and_fire", Vec2(), _shoot, mode="combat", waypoint=position,
                    reason="retain the reachable firing lane while native control waits for vulnerability",
                )])
    approach = _safe_move(state, move_towards(state, enemy.position))
    # Stationary enemies and enemies at range need deliberate closing movement;
    # otherwise the model tends to choose hold_and_fire and hug a wall forever.
    attack_distance = max(_attack_distance(state, profile), profile.enemy_safe_distance * 1.25)
    # A stationary enemy inside the effective tear range is a valid firing
    # lane. Moving closer in that case makes Isaac hug walls and can turn a
    # clear shot into a repeated wall impact. Approach only when genuinely
    # outside the conservative range; blocked lines use movement-only
    # reposition candidates below.
    should_approach = distance > attack_distance
    actions: list[Action] = []
    if should_approach and (approach.x or approach.y):
        # Do not expose hold_and_fire in this phase. Keeping it as a candidate
        # lets a remote selector reintroduce the exact wall-stalling behavior
        # this local rule is meant to prevent.
        actions = [Action(
            "advance_and_fire", approach, aim, mode="combat",
            reason="close the distance to the nearest enemy while firing",
        )]
        lateral_move = _safe_move(state, Vec2(-approach.y, approach.x), avoid_corner=True)
        opposite_move = _safe_move(state, Vec2(approach.y, -approach.x), avoid_corner=True)
        if lateral_move.x or lateral_move.y:
            actions.append(Action("strafe_left", lateral_move, aim, mode="combat", reason="use a lateral firing lane while closing distance"))
        if opposite_move.x or opposite_move.y:
            actions.append(Action("strafe_right", opposite_move, aim, mode="combat", reason="use the opposite lateral firing lane while closing distance"))
        # A blocked firing line is a navigation problem, not a reason to
        # stand still and keep firing at the wall. Keep the movement part as
        # a real candidate with no shot so the safety filter can admit it and
        # Jev can choose between distinct ways to reach a clear lane.
        if state.geometry_features().get("line_of_fire_blocked"):
            reposition_moves: list[Vec2] = []
            for move in (approach, lateral_move, opposite_move):
                if (move.x or move.y) and move not in reposition_moves:
                    reposition_moves.append(move)
            actions.extend(
                Action(
                    "reposition_to_fire_lane" if index == 0 else f"reposition_to_fire_lane_{index + 1}",
                    move, Vec2(), mode="combat",
                    reason="move to a clear firing lane without shooting through the wall",
                )
                for index, move in enumerate(reposition_moves[:2])
            )
        return with_boss_bomb(actions)
    if distance < profile.enemy_safe_distance * 0.65:
        retreat = _safe_move(state, _unit(Vec2(state.player.position.x - enemy.position.x, state.player.position.y - enemy.position.y)))
        if retreat.x or retreat.y:
            actions.append(Action(
                "retreat_and_fire", retreat, aim, mode="combat",
                reason="back away from a nearby enemy while firing",
            ))
    actions.append(Action("hold_and_fire", Vec2(), aim, mode="combat", reason="keep firing at the nearest enemy"))
    # Keep a lateral alternative in the normal safe combat phase. The hard
    # filter removes it when geometry says there is no executable direction.
    lateral = _safe_move(state, Vec2(1, 0), avoid_corner=True)
    if not lateral.x and not lateral.y:
        lateral = _safe_move(state, Vec2(0, 1), avoid_corner=True)
    if lateral.x or lateral.y:
        actions.append(Action("strafe_left", lateral, aim, mode="combat", reason="reposition laterally while maintaining fire"))
    if state.geometry_features().get("line_of_fire_blocked"):
        # Preserve a movement-only escape when every firing action is blocked
        # by a wall or destructible obstacle. This prevents an empty safety
        # set from degrading into an idle loop while Lua keeps aiming.
        actions.append(Action(
            "reposition_to_fire_lane", lateral if lateral.x or lateral.y else Vec2(), Vec2(),
            mode="combat", reason="move to a clear firing lane without shooting through the wall",
        ))
    return with_boss_bomb(actions)


def _safe_pickup_price(state: GameState, price: int, pickup: Any = None) -> bool:
    if price in {0, -1000} or 0 < price <= state.coins:
        return True
    # A deliberate early Devil purchase can improve the build and future
    # Sheol access. Only known red-container prices are budgeted; mixed/soul
    # prices and uncertain bone-container interactions remain inadmissible.
    if (price not in {-1, -2} or pickup is None or not pickup.is_collectible
            or state.progression_target != "satan" or state.layout.room_type != "devil"
            or not state.room_clear or state.enemies or not 2 <= state.stage < 8
            or state.bone_hearts > 0):
        return False
    if pickup.subtype <= 0 or pickup.subtype in {168,329,358,233,394,352,474,316}:
        return False
    # These pickups replace or remove red containers themselves. The price
    # formula alone cannot promise our retained-container survival budget.
    if pickup.subtype in {81, 230, 549}:  # Dead Cat, Abaddon, Brittle Bones
        return False
    if pickup.subtype != 84 and pickup.quality < (3 if price == -1 else 4):
        return False
    remaining_max = state.max_hearts - (-price * 2)
    remaining_health = min(state.player.hit_points,
        min(state.red_hearts, max(0, remaining_max)) + state.soul_hearts)
    return remaining_max >= 4 and remaining_health >= 6


def _safe_consumable_pickup(state: GameState, pickup: Any) -> bool:
    if pickup.pickup_kind not in {"pill", "card"}:
        return True
    if (state.progression_target == "satan" and pickup.pickup_kind == "card"
            and pickup.subtype == JOKER_CARD_ID and not any(card == JOKER_CARD_ID for _,card in state.held_cards)):
        return True
    # Never cycle full pockets. A card may replace a retained unknown pill;
    # once a card is held, keep it until its normal use condition is met.
    if state.held_cards:
        return False
    return pickup.pickup_kind == "card" or not state.held_pills


def _pickup_score(state: GameState, price: int, quality: int, pickup: Any = None) -> int:
    affordable = _safe_pickup_price(state, price, pickup)
    route_bonus=(1000 if affordable and state.progression_target=='satan' and state.stage<=8
                 and pickup is not None and pickup.is_collectible and pickup.subtype==84 else 0)
    return route_bonus + quality * 100 + (20 if affordable else -200) - max(price, 0)


def strategic_actions(state: GameState) -> list[Action]:
    boss_room = state.layout.is_boss or state.layout.room_type == "boss"
    if state.progression_target == "satan" and state.stage == 8:
        # A naturally opened Devil Room can lead to Sheol before It Lives is
        # unlocked. Its special room index is negative, which is valid here.
        if boss_room and state.room_clear:
            exits = [door for door in state.layout.doors
                     if door.target_room_type == "devil" and door_is_usable(door, state)
                     and door_path_distance(state, door) < float("inf")]
            if exits:
                door = min(exits, key=lambda item: door_path_distance(state, item))
                return [Action(f"enter_door_{door.slot}",
                    move_towards(state, door.position, door.grid_index), Vec2(),
                    mode="navigate", target="Devil Room route to Sheol",
                    reason="continue toward Satan before touching the ending chest")]
        if state.room_clear and (boss_room or state.layout.room_type == "devil") and state.boss_exit_available:
            return [Action(f"enter_boss_exit_{state.boss_exit_grid_index}",
                move_towards(state, state.boss_exit_position, state.boss_exit_grid_index), Vec2(),
                mode="boss_exit", target="Sheol",
                reason="use the observed native trapdoor to continue toward Satan")]
    if (boss_room and state.room_clear and state.boss_exit_available
            and state.room_cleared_frame >= 0 and state.frame-state.room_cleared_frame >= 240
            and any(effect.kind == 'moving_spike'
                    and effect.position.distance_to(state.boss_exit_position) < effect.radius+18
                    for effect in state.floor_danger_effects)):
        # Loki can leave a Poky over the newly opened trapdoor. An ordinary
        # exit/re-entry refreshes an already cleared room without fighting or
        # touching the trap; never teleport or remove the blocking entity.
        exits=[door for door in state.layout.doors if door_is_usable(door,state)
               and door_path_distance(state,door)<float('inf')]
        if exits:
            door=min(exits,key=lambda item:door_path_distance(state,item))
            return [Action(f'enter_door_{door.slot}',
                move_towards(state,door.position,door.grid_index),Vec2(),mode='navigate',
                target='clear boss room re-entry',
                reason='leave normally so the cleared room can refresh its obstructed floor exit')]
    for pickup in state.pickups:
        if pickup.pickup_kind in {"ending_chest", "ending_trophy"}:
            return [Action(f"take_pickup_{pickup.entity_id}",
                move_towards(state, pickup.position, pickup.grid_index), Vec2(),
                mode="pickup", target=pickup.name, reason="walk into the native ending reward",
                waypoint=pickup.position)]
    # Boss rewards are the primary objective once the native clear flag is
    # true. Residual poop/fire can be handled afterward; letting it win here
    # leaves the controller circling an obstacle while the item is untouched.
    if not boss_room and (_active_hazards(state) or any(not item.destructible for item in state.hazards)):
        clearable = hazard_actions(state)
        if clearable:
            return clearable
    actions: list[Action] = []
    chest_priority = {
        "red_chest": 100, "eternal_chest": 95, "locked_chest": 90,
        "mimic_chest": 85, "spiked_chest": 80, "haunted_chest": 75,
        "bomb_chest": 70, "wooden_chest": 65, "old_chest": 60, "chest": 55,
    }
    chests = sorted(
        (item for item in state.pickups if item.pickup_kind in chest_priority and _safe_optional_chest(state, item) and item.entity_id not in state.ignored_pickup_ids
         and path_distance(state, item.position, item.grid_index) < float("inf")),
        key=lambda item: chest_priority[item.pickup_kind], reverse=True,
    )
    if chests:
        chest = chests[0]
        return [Action(
            f"open_chest_{chest.entity_id}", move_towards(state, chest.position, chest.grid_index), Vec2(), mode="chest",
            target=chest.name, reason=f"open reachable {chest.pickup_kind}; abandon it if no progress",
        )]
    collectibles = sorted(
        (item for item in state.pickups if item.is_collectible and item.entity_id not in state.ignored_pickup_ids
         and path_distance(state, item.position, item.grid_index) < float("inf")),
        key=lambda item: _pickup_score(state, item.price, item.quality, item), reverse=True,
    )
    for pickup in collectibles:
        affordable = _safe_pickup_price(state, pickup.price, pickup)
        if not affordable:
            continue
        item_mode = "shop" if state.layout.room_type == "shop" and pickup.price > 0 else "item"
        actions.append(Action(
            f"take_item_{pickup.entity_id}", move_towards(state, pickup.position, pickup.grid_index), Vec2(), mode=item_mode,
            target=pickup.name, reason=f"collect quality {pickup.quality} item for price {pickup.price}",
        ))
        break
    loot_priority = {
        "key": 80 if state.keys < 2 else 35,
        "coin": 50 if state.coins < 15 else 25,
        "bomb": 65 if state.bombs < 2 else 25,
        "red_heart": 45, "red_half_heart": 35, "red_double_heart": 55,
        "soul_heart": 70, "half_soul_heart": 65, "black_heart": 75, "eternal_heart": 90,
        "golden_heart": 60, "bone_heart": 80, "scared_heart": 50, "blended_heart": 70, "rotten_heart": 60, "heart": 35,
        "card": 45, "pill": 35, "trinket": 55, "grab_bag": 65,
    }
    loose_pickups = sorted(
        (item for item in state.pickups if not item.is_collectible and item.pickup_kind in loot_priority and item.entity_id not in state.ignored_pickup_ids
         and path_distance(state, item.position, item.grid_index) < float("inf")),
        key=lambda item: loot_priority[item.pickup_kind], reverse=True,
    )
    for pickup in loose_pickups:
        if not _safe_consumable_pickup(state, pickup):
            continue
        if pickup.pickup_kind == "trinket" and pickup.subtype in state.held_trinkets:
            continue
        if pickup.pickup_kind in {"red_heart", "red_half_heart", "red_double_heart", "heart"} and state.max_hearts > 0 and state.red_hearts >= state.max_hearts:
            continue
        if pickup.pickup_kind == "soul_heart" and state.soul_hearts >= 24:
            continue
        if pickup.pickup_kind == "eternal_heart" and state.eternal_hearts > 0:
            continue
        if not _safe_pickup_price(state, pickup.price, pickup):
            continue
        actions.append(Action(
            f"take_pickup_{pickup.entity_id}", move_towards(state, pickup.position, pickup.grid_index), Vec2(), mode="pickup",
            target=pickup.name, reason=f"collect {pickup.pickup_kind} (resources: {state.coins} coins, {state.keys} keys, {state.bombs} bombs)",
        ))
        break
    # Finish known rewards first. Strategic navigation is one planner-selected
    # edge, so Jev cannot pick a different (often backwards) door.
    if actions:
        return actions
    if boss_room:
        # A Boss trapdoor is never a substitute for a visible reward. Keep an
        # unresolved pickup actionable even when the current path estimate is
        # temporarily infinite; the runtime's normal pickup progress timeout
        # will mark a genuinely inaccessible reward as ignored before this
        # gate can be passed.
        boss_rewards = [
            item for item in state.pickups
            if item.entity_id not in state.ignored_pickup_ids
            and _safe_optional_chest(state, item)
            and _safe_pickup_price(state, item.price, item)
            and _safe_consumable_pickup(state, item)
            and not (item.pickup_kind in {"red_heart", "red_half_heart", "red_double_heart", "heart"}
                     and state.max_hearts > 0 and state.red_hearts >= state.max_hearts)
            and not (item.pickup_kind == "soul_heart" and state.soul_hearts >= 24)
            and not (item.pickup_kind == "eternal_heart" and state.eternal_hearts > 0)
            and not (item.pickup_kind == "trinket" and item.subtype in state.held_trinkets)
        ]
        if boss_rewards:
            reward = min(boss_rewards, key=lambda item: item.position.distance_to(state.player.position))
            mode = "item" if reward.is_collectible else "pickup"
            action_id = f"take_item_{reward.entity_id}" if reward.is_collectible else f"take_pickup_{reward.entity_id}"
            return [Action(
                action_id, move_towards(state, reward.position, reward.grid_index), Vec2(),
                mode=mode, target=reward.name,
                reason="Boss reward remains visible; retry pickup before entering the next floor",
            )]
    boss_wait = _boss_reward_wait_action(state)
    if boss_wait:
        return [boss_wait]
    if (state.progression_target == "satan" and 2 <= state.stage < 8
            and boss_room and state.room_clear):
        # Skipping the first Devil Room guarantees an Angel offer next time.
        # Inspect a naturally opened Devil Room once before leaving the floor;
        # paid health offers remain subject to the existing pickup rules.
        offers = [door for door in state.layout.doors
                  if door.target_room_type == "devil"
                  and door.target_room_index not in state.visited_room_indices
                  and door_is_usable(door, state)
                  and door_path_distance(state, door) < float("inf")]
        if offers:
            door = min(offers, key=lambda item: door_path_distance(state, item))
            return [Action(f"enter_door_{door.slot}",
                move_towards(state, door.position, door.grid_index), Vec2(),
                mode="navigate", target="inspect Devil Room for Satan route",
                reason="visit the natural offer before the floor exit to avoid guaranteeing the next Angel offer")]
    if (boss_room and state.boss_exit_available and state.boss_exit_grid_index >= 0
            and state.planned_goal not in {"return to observed health pickup", "collect observed treasure upgrade before boss", "search treasure upgrade before boss"}):
        return [Action(
            f"enter_boss_exit_{state.boss_exit_grid_index}",
            move_towards(state, state.boss_exit_position, state.boss_exit_grid_index),
            Vec2(), mode="boss_exit", target="next floor",
            reason="Boss reward processed; enter the detected trapdoor to the next floor",
        )]
    if _active_hazards(state) or any(not item.destructible for item in state.hazards):
        clearable = hazard_actions(state)
        if clearable:
            return clearable
    doors = [door for door in state.layout.doors
             if door.slot == state.planned_door_slot
             and door_is_usable(door, state)
             and door_path_distance(state, door) < float("inf")]
    if not doors and state.previous_room_index >= 0:
        # A fully explored dead-end still needs an exit. The floor planner
        # normally supplies a selected frontier door, but when no frontier is
        # known the only useful local action is to return through the door we
        # entered. Lua's reverse-door guard prevents stale immediate bounces
        # when another exit is available.
        doors = [
            door for door in state.layout.doors
            if door.target_room_index == state.previous_room_index and door_is_usable(door, state)
            and door_path_distance(state, door) < float("inf")
        ]
        if doors:
            backtrack = doors[0]
            room_label = backtrack.target_room_type if backtrack.target_room_type != "unknown" else "previous"
            return [Action(
                f"enter_door_{backtrack.slot}",
                move_towards(state, backtrack.position, backtrack.grid_index),
                Vec2(), mode="navigate", target=f"backtrack {room_label} room",
                reason="return through the entry door because no unexplored branch is known",
            )]
    if not doors:
        # Planner metadata can briefly lag behind the Lua layout after a room
        # transition. A known ordinary door is still actionable; returning a
        # zero-movement wait here makes Jev repeat `wait_for_exit` forever.
        fallback_doors = [
            door for door in state.layout.doors
            if door_is_usable(door, state)
            and door_path_distance(state, door) < float("inf")
        ]
        if fallback_doors:
            fallback = min(fallback_doors, key=lambda door: (door.target_room_index in state.exhausted_room_indices, door.slot))
            room_label = fallback.target_room_type if fallback.target_room_type != "unknown" else "room"
            return [Action(
                f"enter_door_{fallback.slot}",
                move_towards(state, fallback.position, fallback.grid_index),
                Vec2(), mode="navigate", target=f"fallback {room_label} door",
                reason="use a known ordinary door while the floor plan is being refreshed",
            )]
    for door in doors:
        room_label = door.target_room_type if door.target_room_type != "unknown" else "room"
        label = f"boss door ({room_label})" if door.target_is_boss else f"{room_label} door slot {door.slot}"
        actions.append(Action(
            f"enter_door_{door.slot}", move_towards(state, door.position, door.grid_index), Vec2(), mode="navigate", target=label,
            reason=state.planned_goal or "advance according to the floor plan",
        ))
    return actions or [Action("wait_for_exit", Vec2(), Vec2(), mode="navigate", reason="no usable collectible or exit is currently known")]


def _safe_optional_chest(state: GameState, pickup: Any) -> bool:
    if pickup.pickup_kind in {"spiked_chest", "mimic_chest"}:
        return False
    if pickup.pickup_kind in {"locked_chest", "eternal_chest"}:
        # Preserve a last key while any observed treasure room is unopened.
        reserve = int(any(door.target_room_type == "treasure"
            and door.target_room_index not in state.visited_room_indices for door in state.layout.doors))
        return state.keys > reserve
    return True


def _loot_candidates(state: GameState) -> list[Action]:
    """Return meaningful reward choices without adding navigation or hazards."""
    chest_priority = {
        "red_chest": 100, "eternal_chest": 95, "locked_chest": 90,
        "mimic_chest": 85, "spiked_chest": 80, "haunted_chest": 75,
        "bomb_chest": 70, "wooden_chest": 65, "old_chest": 60, "chest": 55,
    }
    candidates: list[Action] = []
    chests = sorted(
        (item for item in state.pickups if item.pickup_kind in chest_priority and _safe_optional_chest(state, item) and item.entity_id not in state.ignored_pickup_ids
         and path_distance(state, item.position, item.grid_index) < float("inf")),
        key=lambda item: chest_priority[item.pickup_kind], reverse=True,
    )
    for chest in chests:
        candidates.append(Action(
            f"open_chest_{chest.entity_id}", move_towards(state, chest.position, chest.grid_index), Vec2(),
            mode="chest", target=chest.name, reason=f"open reachable {chest.pickup_kind}; abandon it if no progress",
        ))

    collectibles = sorted(
        (item for item in state.pickups if item.is_collectible and item.entity_id not in state.ignored_pickup_ids
         and _safe_pickup_price(state, item.price, item)
         and path_distance(state, item.position, item.grid_index) < float("inf")),
        key=lambda item: _pickup_score(state, item.price, item.quality, item), reverse=True,
    )
    for pickup in collectibles:
        item_mode = "shop" if state.layout.room_type == "shop" and pickup.price > 0 else "item"
        candidates.append(Action(
            f"take_item_{pickup.entity_id}", move_towards(state, pickup.position, pickup.grid_index), Vec2(),
            mode=item_mode, target=pickup.name, reason=f"collect quality {pickup.quality} item for price {pickup.price}",
        ))

    loot_priority = {
        "key": 80 if state.keys < 2 else 35, "coin": 50 if state.coins < 15 else 25,
        "bomb": 65 if state.bombs < 2 else 25, "red_heart": 45, "red_half_heart": 35,
        "red_double_heart": 55, "soul_heart": 70, "half_soul_heart": 65,
        "black_heart": 75, "eternal_heart": 90, "golden_heart": 60, "bone_heart": 80,
        "scared_heart": 50, "blended_heart": 70, "rotten_heart": 60, "heart": 35,
        "card": 45, "pill": 35, "trinket": 55, "grab_bag": 65,
    }
    if state.red_hearts < state.max_hearts:
        for kind in ("heart", "red_heart", "red_half_heart", "red_double_heart", "scared_heart", "blended_heart"):
            loot_priority[kind] = 120 if state.player.hit_points <= 3 else 85
    loose_pickups = sorted(
        (item for item in state.pickups if not item.is_collectible and item.pickup_kind in loot_priority
         and item.entity_id not in state.ignored_pickup_ids
         and path_distance(state, item.position, item.grid_index) < float("inf")),
        key=lambda item: loot_priority[item.pickup_kind], reverse=True,
    )
    for pickup in loose_pickups:
        if not _safe_consumable_pickup(state, pickup):
            continue
        if pickup.pickup_kind in {"red_heart", "red_half_heart", "red_double_heart", "heart"} and state.max_hearts > 0 and state.red_hearts >= state.max_hearts:
            continue
        if pickup.pickup_kind == "soul_heart" and state.soul_hearts >= 24:
            continue
        if pickup.pickup_kind == "eternal_heart" and state.eternal_hearts > 0:
            continue
        if not _safe_pickup_price(state, pickup.price, pickup):
            continue
        if pickup.pickup_kind == "trinket" and pickup.subtype in state.held_trinkets:
            continue
        if pickup.pickup_kind == "trinket" and len(state.held_trinkets) >= state.trinket_slots:
            candidates.append(Action(
                f"keep_trinket_{pickup.entity_id}", Vec2(), Vec2(), mode="pickup",
                target=pickup.name,
                reason=f"keep held trinket {list(state.held_trinkets)} rather than swap for {pickup.name} ({pickup.subtype})",
            ))
        candidates.append(Action(
            f"take_pickup_{pickup.entity_id}", move_towards(state, pickup.position, pickup.grid_index), Vec2(),
            mode="pickup", target=pickup.name,
            reason=f"collect {pickup.pickup_kind} subtype {pickup.subtype} (held trinkets: {list(state.held_trinkets)}; resources: {state.coins} coins, {state.keys} keys, {state.bombs} bombs)",
        ))
    return candidates[:5]


def combat_policy(state: GameState, profile: PolicyProfile | None = None) -> list[Action]:
    """Generate combat candidates without applying the safety contract."""
    return combat_actions(state, profile) if state.enemies or state.projectiles else []


def loot_policy(state: GameState) -> list[Action]:
    """Generate clear-room reward candidates without selecting an exit."""
    return _loot_candidates(state)


def navigation_policy(state: GameState) -> list[Action]:
    """Offer real safe unexplored exits, with the floor plan first for fallback."""
    actions = [item for item in strategic_actions(state) if item.mode in {"navigate", "boss_exit"}]
    # The bomb was spent to reveal this room. Keep the confirmed entrance as
    # the only navigation candidate until it is visited or becomes unusable.
    opened_secret = newly_opened_secret_door(state)
    if opened_secret and state.planned_door_slot == opened_secret.slot:
        return actions
    if len(actions) != 1 or not actions[0].action_id.startswith("enter_door_") or state.planned_goal == "committed navigation choice":
        return actions
    available = [
        door for door in state.layout.doors
        if door_is_usable(door, state)
        and door_path_distance(state, door) < float("inf")
        and door.slot not in state.unreachable_door_slots
        and door.target_room_index not in state.visited_room_indices
        and door.target_room_index not in state.exhausted_room_indices
        and door.target_room_index != state.previous_room_index
    ]
    treasure = [door for door in available if door.target_room_type == "treasure"]
    safe = [door for door in available if door.target_room_type not in {"curse", "sacrifice", "challenge"}]
    choices = treasure or safe or available
    if not any(f"enter_door_{door.slot}" == actions[0].action_id for door in choices):
        return actions
    result = actions[:]
    for door in sorted(choices, key=lambda item: item.slot):
        if f"enter_door_{door.slot}" == actions[0].action_id:
            continue
        move = move_towards(state, door.position, door.grid_index)
        if move == Vec2() and door.position.distance_to(state.player.position) > 70:
            continue
        result.append(Action(
            f"enter_door_{door.slot}", move, Vec2(),
            mode="navigate", target=f"{door.target_room_type} door slot {door.slot}",
            reason=f"safe unexplored {door.target_room_type} room {door.target_room_index}; compare with planned goal {state.planned_goal}",
        ))
    return result


def _candidate_policy(state: GameState, raw: list[Action]) -> str:
    if not raw:
        return "wait"
    if any(item.mode == "combat" for item in raw):
        return "combat"
    if any(item.mode == "evade" for item in raw):
        return "emergency"
    if any(item.mode in _LOOT_MODES for item in raw):
        return "loot"
    return "navigation"


def hard_rule_filter(state: GameState, candidates: list[Action], profile: PolicyProfile | None = None) -> tuple[list[Action], list[dict[str, Any]]]:
    """Apply deterministic admissibility rules before a remote Jev call."""
    profile = (profile or PolicyProfile()).bounded()
    geometry = state.geometry_features()
    imminent = bool(geometry.get("nearest_projectile_imminent"))
    enemy_distance = geometry.get("nearest_enemy_distance")
    attack_distance = _attack_distance(state, profile)
    admissible: list[Action] = []
    rejected: list[dict[str, Any]] = []

    def reject(action: Action, rule: str) -> None:
        rejected.append({"id": action.action_id, "rule": rule})

    for action in candidates:
        rule = ""
        if action.mode == "combat":
            if state.room_clear:
                rule = "room_clear_stale_combat"
            elif not state.enemies and action.action_id != "evade_projectile":
                rule = "no_hostile_target"
            elif imminent and action.action_id in {"advance_and_fire", "advance_and_evade_fire", "hold_and_fire"}:
                rule = "projectile_imminent_vetoes_approach_or_hold"
            elif enemy_distance is not None and enemy_distance > attack_distance and action.action_id == "hold_and_fire":
                rule = "enemy_out_of_range_vetoes_stationary_fire"
            elif geometry.get("line_of_fire_blocked") and action.shoot != Vec2() and not action.action_id.startswith("dodge_charge_"):
                rule = "line_of_fire_blocked"
            elif action.move != Vec2() and not _is_open(state, action.move):
                rule = "non_walkable_direction"
            elif (state.movement_blocked or state.movement_progress < 0.05) and action.action_id == state.last_action_id and action.move != Vec2():
                rule = "repeated_blocked_direction"
        if action.mode == "evade":
            if not _tracking_bomb_threats(state, imminent_only=False):
                rule = "ghost_bomb_no_longer_present"
            elif not action.move.x and not action.move.y:
                rule = "ghost_bomb_escape_has_no_movement"
            elif not _is_open(state, action.move):
                rule = "ghost_bomb_route_blocked"
            elif state.safe_move_directions.get(
                {(0, -1): "up", (0, 1): "down", (-1, 0): "left", (1, 0): "right"}.get(
                    (action.move.x, action.move.y), ""), "safe"
            ) != "safe":
                rule = "lua_ghost_bomb_escape_direction_unsafe"
            else:
                threat = _tracking_bomb_threats(state, imminent_only=False)[0]
                predicted = Vec2(threat.position.x + threat.velocity.x * 8,
                                 threat.position.y + threat.velocity.y * 8)
                current_distance = state.player.position.distance_to(predicted)
                next_position = Vec2(state.player.position.x + action.move.x * 40,
                                     state.player.position.y + action.move.y * 40)
                if next_position.distance_to(predicted) <= current_distance:
                    rule = "ghost_bomb_move_not_increasing_distance"
        if action.action_id.startswith("bomb_boss_"):
            suffix = action.action_id.removeprefix("bomb_boss_")
            target_id = int(suffix) if suffix.isdigit() else -1
            target = next((item for item in state.enemies if item.entity_id == target_id and item.is_boss), None)
            distance = target.position.distance_to(state.player.position) if target else float("inf")
            if not (state.layout.is_boss or state.layout.room_type == "boss"):
                rule = "boss_bomb_outside_boss_room"
            elif state.bombs <= 0 or state.bomb_active or state.bomb_placed:
                rule = "bomb_unavailable_or_on_cooldown"
            elif state.bomb_error:
                rule = "bomb_placement_failed_in_room"
            elif target is None:
                rule = "boss_target_missing"
            elif distance < 55.0 or distance > 110.0:
                rule = "boss_outside_safe_blast_range"
            elif _threatening_projectiles(state, profile):
                rule = "projectile_threat_vetoes_bomb_placement"
            elif not any(value == "safe" for value in state.safe_move_directions.values()):
                rule = "no_known_bomb_retreat_direction"
        if action.action_id.startswith("bomb_hazard_"):
            suffix = action.action_id.removeprefix("bomb_hazard_")
            target_id = int(suffix) if suffix.lstrip("-").isdigit() else -1
            target = next((item for item in state.hazards if item.entity_id == target_id), None)
            if target is not None and target.kind in {"blue_fire", "purple_fire"} and state.bombs <= 4:
                rule = "special_fire_requires_more_than_four_bombs"
        if action.mode in {"item", "shop"}:
            pickup = next((item for item in state.pickups if str(item.entity_id) == action.action_id.rsplit("_", 1)[-1]), None)
            if pickup is not None and not _safe_pickup_price(state, pickup.price, pickup):
                rule = "unaffordable_pickup"
        if action.mode == "pickup":
            pickup = next((item for item in state.pickups if str(item.entity_id) == action.action_id.rsplit("_", 1)[-1]), None)
            if pickup is not None and not _safe_consumable_pickup(state, pickup):
                rule = "keep_held_consumable"
            elif pickup is not None and not _safe_pickup_price(state, pickup.price, pickup):
                rule = "unaffordable_pickup"
            if pickup is not None and pickup.pickup_kind in {"red_heart", "red_half_heart", "red_double_heart", "heart"} and state.max_hearts > 0 and state.red_hearts >= state.max_hearts:
                rule = "full_health_red_heart"
        if action.mode == "navigate":
            door = next((item for item in state.layout.doors if f"enter_door_{item.slot}" == action.action_id), None)
            if door and door.slot in state.unreachable_door_slots:
                rule = "door_previously_unreachable"
            elif door and not door_is_usable(door, state):
                rule = "door_resource_or_lock_constraint"
            elif door and door.open_known and not door.open and not door.locked:
                rule = "door_not_open"
        if action.mode == "recovery":
            direction = action.action_id.removeprefix("recover_")
            if not state.recovery_active or state.bomb_active or state.player_dead:
                rule = "recovery_not_active"
            elif state.safe_move_directions.get(direction) != "safe":
                rule = "lua_recovery_direction_unsafe"
            elif not _is_open(state, action.move):
                rule = "recovery_route_blocked"
        if action.mode in {"button", "tnt"} and action.move != Vec2() and not _is_open(state, action.move):
            rule = "mechanism_route_blocked"
        if rule:
            reject(action, rule)
        else:
            admissible.append(action)
    return admissible, rejected


def build_candidate_set(state: GameState, profile: PolicyProfile | None = None) -> CandidateSet:
    raw = _raw_candidate_actions(state, profile)
    # Keep candidate_actions() compatible with its historical single-target
    # behavior, while exposing genuine reward conflicts to the remote policy.
    if state.room_clear and not state.recovery_active and not any(item.mode in {"combat", "evade", "hazard", "bomb", "bomb_wall", "button", "tnt", "wait"} for item in raw):
        reward_candidates = loot_policy(state)
        if reward_candidates:
            raw = reward_candidates
        elif any(item.mode == "navigate" for item in raw):
            raw = navigation_policy(state)
    admissible, rejected = hard_rule_filter(state, raw, profile)
    policy = _candidate_policy(state, raw)
    phase = "combat" if policy == "combat" else ("clear" if state.room_clear else "awaiting_clear")
    reason = ""
    if len(admissible) == 1:
        reason = "only one candidate survived deterministic safety/resource rules"
    elif len(admissible) == 0 and raw:
        reason = "all generated candidates were rejected by deterministic safety/resource rules"
    return CandidateSet(policy, phase, tuple(raw), tuple(admissible), tuple(rejected), reason)


def candidate_actions(state: GameState, profile: PolicyProfile | None = None) -> list[Action]:
    """Compatibility API returning only admissible actions."""
    candidate_set = build_candidate_set(state, profile)
    if candidate_set.admissible_candidates:
        # Legacy callers execute the first deterministic local reward target;
        # Jev-facing callers use CandidateSet and can see genuine conflicts.
        if candidate_set.policy == "loot":
            return [candidate_set.admissible_candidates[0]]
        return list(candidate_set.admissible_candidates)
    return [Action("wait_for_safety_filter", Vec2(), Vec2(), mode="wait", reason=candidate_set.single_legal_reason or "no admissible candidate")]


def conservative_action(state: GameState, profile: PolicyProfile | None = None) -> Action:
    profile = profile or PolicyProfile()
    actions = candidate_actions(state, profile)
    if not actions:
        return Action("await_model", Vec2(), Vec2(), 0.0, "safety", "wait", "", "no admissible action is available")
    if state.room_clear or (state.enemies and not state.projectiles):
        selected = actions[0]
    else:
        enemy = _nearest(state, state.enemies)
        projectile = _nearest(state, _threatening_projectiles(state, profile))
        if projectile:
            approach = next((action for action in actions if action.action_id == "advance_and_evade_fire"), None)
            if approach is not None and not _projectile_imminent(state, projectile, profile):
                selected = approach
            else:
                selected = next(
                    (action for action in actions if action.action_id in {"strafe_left", "strafe_right"}),
                    actions[0],
                )
        elif enemy and enemy.position.distance_to(state.player.position) < profile.enemy_safe_distance:
            away = _unit(Vec2(state.player.position.x - enemy.position.x, state.player.position.y - enemy.position.y))
            selected = Action("retreat_from_enemy", _safe_move(state, away), _predictive_enemy_aim(state, enemy), mode="combat", reason="keep a safe distance from the nearest enemy while leading its movement")
        elif actions:
            selected = actions[0]
    if selected.mode == "evade":
        return replace(selected, confidence=0.0, source="fallback")
    return replace(selected, move=_safe_move(state, selected.move), confidence=0.0, source="fallback")


def _safety_filter(state: GameState, action: Action, profile: PolicyProfile | None = None) -> Action:
    profile = profile or PolicyProfile()
    ghost_escape = tracking_bomb_actions(state)
    if ghost_escape:
        selected = next((item for item in ghost_escape if item.action_id == action.action_id), ghost_escape[0])
        return replace(selected, source="safety", confidence=action.confidence)
    if state.room_clear:
        return action
    enemy = _nearest(state, state.enemies)
    projectile = _nearest(state, _threatening_projectiles(state, profile))
    move = _safe_move(state, action.move)
    if projectile and _projectile_imminent(state, projectile, profile):
        threat = _unit(Vec2(state.player.position.x - projectile.position.x, state.player.position.y - projectile.position.y))
        lateral = Vec2(-threat.y, threat.x)
        evade = _safe_move(state, lateral)
        if not evade.x and not evade.y:
            evade = _safe_move(state, threat)
        return Action(
            "mandatory_evade_and_fire", evade, action.shoot, action.confidence,
            "safety", "combat", action.target,
            "imminent projectile overrides approach; evade while firing",
        )
    # Even if a remote response selected a static combat action, enforce
    # movement under live bullet pressure.
    if not move.x and not move.y and projectile:
        if projectile:
            away = _unit(Vec2(state.player.position.x - projectile.position.x, state.player.position.y - projectile.position.y))
            move = _safe_move(state, Vec2(-away.y, away.x))
        return Action("mandatory_evade_and_fire", move, action.shoot, action.confidence, "safety", "combat", action.target, "move while firing under active threat")
    if enemy and enemy.position.distance_to(state.player.position) < profile.enemy_safe_distance:
        toward = Vec2(enemy.position.x - state.player.position.x, enemy.position.y - state.player.position.y)
        if move.x * toward.x + move.y * toward.y > 0:
            move = _safe_move(state, _unit(Vec2(-toward.x, -toward.y)))
    return Action(action.action_id, move, action.shoot, action.confidence, action.source, action.mode, action.target, action.reason,
                  action.issued_frame, action.expires_frame, action.macro_horizon_frames, action.bomb_site, action.waypoint)


def repeat_action_penalty_action(state: GameState, previous: Action, profile: PolicyProfile | None = None, trigger: str = "repeat") -> Action:
    """Break a repeated or blocked action locally so Jev cannot pin Isaac."""
    profile = profile or PolicyProfile()
    prefix = "movement_penalty_" if trigger == "movement" else "repeat_penalty_"
    reason = (
        f"movement penalty after {profile.movement_stall_threshold} blocked movement observations"
        if trigger == "movement"
        else f"repeat penalty after {profile.repeat_action_threshold} identical decisions"
    )
    if state.enemies:
        alternatives = [item for item in combat_actions(state, profile)
                        if (item.action_id != previous.action_id or item.waypoint is not None)
                        and item.move != Vec2()]
        if alternatives:
            selected = alternatives[0]
            return _safety_filter(
                state,
                Action(
                    prefix + selected.action_id,
                    selected.move,
                    selected.shoot,
                    0.0,
                    "safety",
                    "combat",
                    previous.target,
                    reason,
                    waypoint=selected.waypoint,
                ),
                profile,
            )

    base = previous.move
    if not base.x and not base.y:
        pickup = _nearest(state, state.pickups)
        if pickup:
            base = _unit(Vec2(pickup.position.x - state.player.position.x, pickup.position.y - state.player.position.y))
    lateral = Vec2(-base.y, base.x) if base.x or base.y else Vec2(1, 0)
    move = _safe_move(state, lateral)
    if not move.x and not move.y:
        move = _safe_move(state, Vec2(-lateral.x, -lateral.y))
    return Action(
        prefix + "reposition",
        move,
        Vec2(),
        0.0,
        "safety",
        previous.mode,
        previous.target,
        reason,
    )


@dataclass
class JevClient:
    api_key: str
    url: str = os.getenv("JEV_API_URL", "https://api.typesafe.ai/v1/systemone")
    model: str = os.getenv("JEV_MODEL", "jev-latest")
    timeout_seconds: float = 0.75
    confidence_threshold: float = 0.70
    profile: PolicyProfile = PolicyProfile()
    last_trace: dict[str, Any] | None = None

    @classmethod
    def from_environment(cls, profile: PolicyProfile | None = None) -> "JevClient":
        key = os.getenv("TYPESAFE_API_KEY")
        if not key:
            raise RuntimeError("TYPESAFE_API_KEY is not configured for the current process.")
        profile = (profile or PolicyProfile()).bounded()
        return cls(api_key=key, timeout_seconds=profile.jev_timeout_seconds, confidence_threshold=profile.confidence_threshold, profile=profile)

    def choose(self, state: GameState, candidate_set: CandidateSet | None = None) -> Action:
        candidate_set = candidate_set or build_candidate_set(state, self.profile)
        candidates = list(candidate_set.admissible_candidates)
        fallback = conservative_action(state, self.profile)
        if not candidates:
            self.last_trace = {
                "frame": state.frame,
                "room_index": state.layout.room_index,
                "status": "fallback",
                "candidate_set": candidate_set.as_dict(),
                "fallback_reason": candidate_set.single_legal_reason,
                "output": {"action": fallback.action_id},
                "latency_ms": 0.0,
            }
            return fallback
        route = policy_router(state, candidate_set)
        observation = build_policy_observation(state, candidate_set)
        candidate_set_record = candidate_set.as_dict()
        candidate_set_record["policy_route"] = route
        candidate_set_record["schema_version"] = SCHEMA_VERSION
        criteria = {item.action_id: item.reason for item in candidates}
        instructions = {
            "combat": "Choose one admissible combat action that best balances survival and damage.",
            "loot": "Choose one admissible reward action; prefer the best value for the current resources.",
            "navigation": "Choose one admissible navigation action and follow the planner's intended exit.",
            "emergency": "Choose one admissible emergency action that best handles the immediate threat.",
        }.get(route, "Choose exactly one admissible action for the current phase.")
        payload = {
            "model": self.model,
            "state": observation,
            "questions": {
                "next_action": {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": criteria,
                }
            },
        }
        state_bytes = len(json.dumps(payload["state"], ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        request_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        estimated_tokens = max(1, (request_bytes + 3) // 4)
        started_at = time.monotonic()
        trace = {
            "frame": state.frame,
            "room_index": state.layout.room_index,
            "policy": route,
            "schema_version": SCHEMA_VERSION,
            "input": payload["state"],
            "jev_request": {
                "model": self.model,
                "state": payload["state"],
                "questions": payload["questions"],
            },
            "request_summary": {
                "policy": route,
                "question_ids": ["next_action"],
                "candidate_ids": [item.action_id for item in candidates],
            },
            "status": "started",
            "candidate_set": candidate_set_record,
            "state_bytes": state_bytes,
            "request_bytes": request_bytes,
            "estimated_input_tokens": estimated_tokens,
        }
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        trace["request_summary"]["request_bytes"] = len(data)
        request = urllib.request.Request(
            self.url,
            data=data,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as error:
            trace.update({
                "status": "fallback",
                "output": {"action": fallback.action_id, "action_label": action_label(fallback.action_id)},
                "error": f"{type(error).__name__}: {error}",
                "latency_ms": round((time.monotonic() - started_at) * 1000, 2),
                "remote_latency_ms": round((time.monotonic() - started_at) * 1000, 2),
                "fallback_reason": "network_error",
            })
            self.last_trace = trace
            return fallback
        if not isinstance(body, dict):
            trace.update({
                "status": "fallback",
                "output": {"action": fallback.action_id, "action_label": action_label(fallback.action_id)},
                "fallback_reason": "response_not_an_object",
                "latency_ms": round((time.monotonic() - started_at) * 1000, 2),
                "remote_latency_ms": round((time.monotonic() - started_at) * 1000, 2),
            })
            self.last_trace = trace
            return fallback
        answer = body.get("answers", {}).get("next_action", {})
        if not isinstance(answer, dict):
            answer = {}
        selected_id = answer.get("choice") or answer.get("value") or answer.get("answer")
        try:
            confidence = float(answer.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        probabilities = answer.get("probabilities", answer.get("distribution", {}))
        if not isinstance(probabilities, dict):
            probabilities = {}
        safe_probabilities: dict[str, float] = {}
        for key, value in probabilities.items():
            try:
                safe_probabilities[str(key)] = round(float(value), 4)
            except (TypeError, ValueError):
                continue
        selected = next((item for item in candidates if item.action_id == selected_id), fallback)
        if selected is fallback or confidence < self.confidence_threshold:
            trace.update({
                "status": "fallback",
                "output": {"action": fallback.action_id, "action_label": action_label(fallback.action_id), "selected_id": selected_id, "confidence": confidence, "probabilities": safe_probabilities},
                "fallback_reason": "invalid_choice_or_low_confidence",
                "latency_ms": round((time.monotonic() - started_at) * 1000, 2),
                "remote_latency_ms": round((time.monotonic() - started_at) * 1000, 2),
            })
            self.last_trace = trace
            return fallback
        selected = Action(selected.action_id, selected.move, selected.shoot, confidence, "jev", selected.mode, selected.target, selected.reason,
                          selected.issued_frame, selected.expires_frame, selected.macro_horizon_frames, selected.bomb_site, selected.waypoint)
        filtered = _safety_filter(state, selected, self.profile)
        trace.update({
            "status": "success" if filtered.action_id == selected.action_id else "safety_filtered",
            "output": {"selected_action": selected.action_id, "action": filtered.action_id, "action_label": action_label(filtered.action_id), "confidence": confidence, "probabilities": safe_probabilities},
            "probabilities": safe_probabilities,
            "latency_ms": round((time.monotonic() - started_at) * 1000, 2),
            "remote_latency_ms": round((time.monotonic() - started_at) * 1000, 2),
        })
        self.last_trace = trace
        return filtered
