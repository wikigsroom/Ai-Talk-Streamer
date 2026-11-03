"""Rebuild documentation contracts only; never start application services."""
from copy import deepcopy
from pathlib import Path
import json
import subprocess


BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[3]
SAFE = 9007199254740991


def obj(properties, required=None, additional=False):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": additional}


def string(limit=128, minimum=1):
    return {"type": "string", "minLength": minimum, "maxLength": limit}


def integer(low=0, high=SAFE):
    return {"type": "integer", "minimum": low, "maximum": high}


def enum(*values):
    return {"type": "string", "enum": list(values)}


def ref(name):
    return {"$ref": "#/$defs/" + name}


def nullable(value):
    return {"anyOf": [deepcopy(value), {"type": "null"}]}


def array(items, maximum=100, minimum=0, unique=False):
    value = {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}
    if unique:
        value["uniqueItems"] = True
    return value


ID = {**string(), "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"}
ITEM = {**string(160), "pattern": "^[a-z0-9_.-]+:[a-z0-9_./-]+$"}
TIME = {"type": "string", "format": "date-time"}
BOOL = {"type": "boolean"}
MODE = enum("AUTO", "MANUAL_COMMENTARY", "PAUSED")
SKILLS = enum("navigate", "gather", "craft", "use_item", "return_base", "cancel")
D = {}
D["Position"] = obj({"dimension": ITEM, "x": integer(-30000000, 30000000),
                     "y": integer(-2048, 2048), "z": integer(-30000000, 30000000)})
D["NavigateGoal"] = obj({"skill": {"const": "navigate"}, "target": ref("Position"),
                         "radius": {"type": "number", "minimum": 0, "maximum": 8}})
for kind in ("gather", "craft"):
    D[kind.title() + "Goal"] = obj({"skill": {"const": kind}, "item_id": ITEM, "count": integer(1, 4096)})
    D[kind.title() + "Goal"]["properties"]["count"]["description"] = (
        "相对任务开始时库存的目标新增数量；不包含已有库存。" if kind == "gather" else
        "目标新增产物单位数；按当前配方每批产量向上取整，并核验实际合成结果。")
D["UseItemGoal"] = obj({"skill": {"const": "use_item"}, "item_id": ITEM,
                        "purpose": enum("eat", "equip", "activate")})
D["UseItemGoal"]["properties"]["target"] = ref("Position")
PLANT_ITEMS = enum("minecraft:wheat_seeds", "minecraft:carrot", "minecraft:potato", "minecraft:beetroot_seeds")
D["UseItemGoal"]["allOf"] = [
    {"if": {"required": ["target"]}, "then": {"properties": {"purpose": {"const": "activate"}, "item_id": enum(*PLANT_ITEMS["enum"], "minecraft:crafting_table", "minecraft:furnace")}}},
    {"if": {"properties": {"purpose": {"const": "activate"}, "item_id": PLANT_ITEMS}, "required": ["purpose", "item_id"]},
     "then": {"required": ["target"]}}]
D["ReturnBaseGoal"] = obj({"skill": {"const": "return_base"}, "base_id": ID})
D["BaseRef"] = obj({"game_instance_id": ID, "world_id": ID, "base_id": ID,
    "base_revision": integer(1), "world_revision": integer(1)})
D["BaseTarget"] = obj({**deepcopy(D["BaseRef"]["properties"]), "position": ref("Position"),
    "radius": integer(1, 128), "source": {"const": "operator_observed"},
    "registered_world_session_id": ID, "registered_seq": integer()})


def base_binding(path, field, required=False):
    condition = {"properties": {"skill": {"const": "return_base"}}, "required": ["skill"]}
    for key in reversed(path):
        condition = {"properties": {key: condition}, "required": [key]}
    return {"if": condition, "then": {"required": [field]} if required else {},
            "else": {"not": {"required": [field]}}}


D["Goal"] = {"oneOf": [ref(x) for x in ("NavigateGoal", "GatherGoal", "CraftGoal", "UseItemGoal", "ReturnBaseGoal")]}
D["TaskCreate"] = obj({"request_id": ID, "bridge_boot_id": ID, "world_session_id": ID,
                       "expected_control_epoch": integer(), "based_on_seq": integer(),
                       "accept_within_ms": integer(250, 2000), "max_duration_ms": integer(1000, 600000),
                       "goal": ref("Goal")})
D["TaskCreate"]["properties"]["base_ref"] = ref("BaseRef")
D["TaskCreate"]["allOf"] = [base_binding(["goal"], "base_ref")]
D["ControlRequest"] = obj({"request_id": ID, "target_mode": MODE, "reason": string(240),
                           "bridge_boot_id": ID, "world_session_id": ID,
                           "expected_control_epoch": integer()}, ["request_id", "target_mode", "reason"])
D["ControlRequest"]["allOf"] = [{"if": {"properties": {"target_mode": {"const": "AUTO"}}},
    "then": {"required": ["bridge_boot_id", "world_session_id", "expected_control_epoch"]}}]
D["CancelRequest"] = obj({"request_id": ID, "reason": string(240)})
D["PanicRequest"] = obj({"request_id": ID, "reason": string(240)})
D["Player"] = obj({"health": nullable({"type": "number", "minimum": 0, "maximum": 2048}),
                   "max_health": nullable({"type": "number", "exclusiveMinimum": 0, "maximum": 2048}),
                   "food": nullable(integer(0, 20)), "oxygen": nullable(integer(0, 3000)),
                   "position": nullable(ref("Position"))})
D["InventoryEntry"] = obj({"item_id": ITEM, "count": integer(0, 2147483647)})
D["Environment"] = obj({"loaded_radius_chunks": nullable(integer(0, 64)),
                        "nearby_threats": nullable(integer(0, 4096))})
state_properties = {
    "schema_version": {"const": 1}, "game_instance_id": nullable(ID), "bridge_boot_id": nullable(ID),
    "world_id": nullable(ID), "world_session_id": nullable(ID), "connection_generation": nullable(integer(1)),
    "seq": nullable(integer()), "connected": BOOL, "freshness": enum("fresh", "stale", "unavailable"),
    "age_ms": nullable(integer()), "observed_at": nullable(TIME), "rule_fingerprint": nullable(ID),
    "mode": nullable(MODE), "control_epoch": nullable(integer()), "inputs_released": nullable(BOOL),
    "automation_ready": BOOL, "lease_remaining_ms": nullable(integer(0, 10000)),
    "player": nullable(ref("Player")), "inventory": array(ref("InventoryEntry"), 256),
    "screen": enum("gameplay", "inventory", "container", "menu", "death", "unknown"),
    "environment": nullable(ref("Environment")), "unknown_fields": array(string(100), 128, unique=True),
    "active_task_id": nullable(ID), "view_revision": integer()
}
D["GameState"] = obj(state_properties)
D["GameState"]["allOf"] = [{"if": {"properties": {"freshness": {"const": "fresh"}}}, "then": {
    "properties": {"connected": {"const": True}, "game_instance_id": ID, "bridge_boot_id": ID,
                   "world_id": ID, "world_session_id": ID, "seq": integer(), "age_ms": integer(),
                   "observed_at": TIME, "mode": MODE, "control_epoch": integer()}}},
    {"if": {"properties": {"automation_ready": {"const": True}}}, "then": {
        "properties": {"connected": {"const": True}, "freshness": {"const": "fresh"},
                       "mode": {"const": "AUTO"}, "lease_remaining_ms": integer(1, 10000)}}}]
observation = {k: deepcopy(v) for k, v in state_properties.items()
               if k not in ("connected", "freshness", "age_ms", "view_revision")}
for key in ("game_instance_id", "bridge_boot_id", "world_id", "world_session_id"):
    observation[key] = ID
for key in ("seq", "connection_generation", "control_epoch"):
    observation[key] = integer(1 if key == "connection_generation" else 0)
observation["mode"] = MODE
observation["observed_at"] = TIME
D["Observation"] = obj(observation)
D["RuntimeSlot"] = obj({"slot": integer(-1, 4095), "item_id": ITEM, "count": integer(0, 2147483647),
    "damage": nullable(integer(0, 2147483647)), "max_damage": nullable(integer(0, 2147483647))})
D["RuntimeDetails"] = obj({"source": {"const": "runtime_client"}, "selected_hotbar": integer(0, 8),
    "inventory_slots": array(ref("RuntimeSlot"), 256), "cursor": ref("RuntimeSlot"),
    "gui": obj({"kind": enum("container", "gameplay", "screen"), "title": nullable(string(240, 0)),
        "container_id": nullable(integer(0, 2147483647)), "slots": array(ref("RuntimeSlot"), 256), "truncated": BOOL}),
    "hazards": obj({"on_fire": BOOL, "in_water": BOOL, "in_lava": BOOL,
        "fall_distance": {"type": "number", "minimum": 0, "maximum": 100000}, "on_ground": BOOL}),
    "environment": obj({"biome": nullable(ITEM), "day_time": integer(), "raining": BOOL, "thundering": BOOL}),
    "received_rules": obj({"difficulty": enum("peaceful", "easy", "normal", "hard"),
        "game_mode": enum("survival", "creative", "adventure", "spectator"),
        "world_border_size": {"type": "number", "minimum": 0, "maximum": 60000000}}),
    "nearby_hostiles": array(obj({"entity_id": integer(0, 2147483647), "type": ITEM,
        "health": {"type": "number", "minimum": 0, "maximum": 1000000}, "visible": BOOL,
        "distance": {"type": "number", "minimum": 0, "maximum": 64}, "position": ref("Position")}), 32),
    "hostiles_truncated": BOOL, "unknown_fields": array(string(100), 128, unique=True)})
# Optional extension preserves old loader and saved-history compatibility.
D["GameState"]["properties"] = {**state_properties, "details": nullable(ref("RuntimeDetails"))}
D["Observation"]["properties"] = {**observation, "details": ref("RuntimeDetails")}
D["Evidence"] = obj({"world_session_id": ID, "seq": integer(),
                     "kind": enum("position", "inventory", "craft_result", "item_effect", "input_release"),
                     "summary": string(500)})
D["TaskRecovery"] = obj({"task_id": ID, "revision": integer(1),
    "status": enum("required", "querying", "waiting_terminal", "verified", "missing", "conflict", "unsupported", "operator_closed"),
    "reason": string(240), "created_at": TIME, "updated_at": TIME, "attempts": integer(),
    "checked_bridge_boot_id": nullable(ID), "confirmed_version": nullable(integer(1)), "last_error": nullable(string(120))})
D["Task"] = obj({"task_id": ID, "game_instance_id": ID, "bridge_boot_id": ID,
                 "world_id": ID, "world_session_id": ID, "request_id": ID,
                 "control_epoch": integer(), "version": integer(1), "goal": ref("Goal"),
                 "state": enum("accepted", "running", "succeeded", "failed", "cancelled"),
                 "created_at": TIME, "updated_at": TIME, "reason": nullable(string(240)),
                 "effect_status": enum("verified", "partial", "unknown"), "evidence": array(ref("Evidence"), 32)})
D["Task"]["properties"]["base_target"] = ref("BaseTarget")
D["Task"]["allOf"] = [{"if": {"properties": {"state": {"const": "succeeded"}}}, "then": {
    "properties": {"effect_status": {"const": "verified"}, "evidence": {"minItems": 1}}}}]
D["Task"]["properties"]["recovery"] = ref("TaskRecovery")
D["TaskDisposition"] = obj({"task_id": ID, "revision": integer(1), "status": enum("closed_unknown", "reopened"),
    "reason": string(240), "acknowledged_unknown": {"const": True}, "task_version": integer(1),
    "task_hash": {**string(64, 64), "pattern": "^[0-9a-f]{64}$"}, "recovery_revision": integer(),
    "created_at": TIME, "updated_at": TIME, "reopen_reason": nullable(string(120)),
    "observed_context": obj({"game_instance_id": ID, "bridge_boot_id": ID, "world_id": ID, "world_session_id": ID,
        "seq": integer(), "control_epoch": integer(), "mode": enum("PAUSED", "MANUAL_COMMENTARY"),
        "inputs_released": {"const": True}, "active_task_id": {"type": "null"}, "observed_at": TIME})})
D["Task"]["properties"]["disposition"] = ref("TaskDisposition")
D["TaskDispositionRequest"] = obj({"request_id": ID, "bridge_boot_id": ID, "world_session_id": ID,
    "expected_control_epoch": integer(), "based_on_seq": integer(), "expected_task_version": integer(1),
    "expected_recovery_revision": integer(), "acknowledge_unknown": {"const": True}, "reason": string(240)})
D["TaskPage"] = obj({"items": array(ref("Task")), "next_cursor": nullable(string(512))})
D["Operation"] = obj({"operation_id": ID, "request_id": ID,
                      "kind": enum("control", "cancel", "query", "panic", "audience"),
                      "state": enum("pending", "running", "succeeded", "failed"),
                      "created_at": TIME, "updated_at": TIME,
                      "result": nullable({"type": "object"}), "error": nullable(string(120))})
D["Capabilities"] = obj({"protocol_version": {"const": "1.0"}, "game_instance_id": ID,
                         "adapter": {"const": "minecraft.fabric"}, "game_version": string(40),
                         "mod_version": string(40), "execution_profile": enum("none", "native_core", "baritone_base", "altoclef_trial", "altoclef_survival"),
                         "skills": array(SKILLS, 6, unique=True),
                         "item_uses": array(enum("eat", "equip", "activate"), 3, unique=True),
                         "features": obj({"recipes": BOOL, "screenshots": BOOL, "local_takeover": BOOL, "cancel_all": BOOL,
                                          "basic_pve": BOOL, "survival_rules": BOOL, "resource_chains": BOOL, "task_ledger": BOOL,
                                          "targeted_planting": BOOL, "targeted_block_placement": BOOL, "autonomous_resume": BOOL},
                                         ["recipes", "screenshots", "local_takeover", "cancel_all"]),
                         "rule_fingerprint": nullable(ID)})
D["PlannerConfig"] = obj({"enabled": BOOL, "min_interval_ms": integer(1000, 60000),
                          "max_call_ms": integer(1000, 60000), "candidate_limit": integer(1, 32)})
D["PlannerConfig"]["properties"]["engine"] = enum("dsh", "mindcraft_native")
D["PlannerConfig"]["properties"]["autostart"] = BOOL
D["ControlConfig"] = obj({"state_stale_ms": integer(500, 5000), "heartbeat_ms": integer(250, 2000),
                          "lease_ttl_ms": integer(1000, 10000), "accept_within_ms": integer(250, 2000),
                          "max_task_duration_ms": integer(1000, 600000), "enabled_skills": array(SKILLS, 6, unique=True)})
D["ProgrammeConfig"] = obj({"layout_id": {"const": "mc-landscape-v1"},
                            "avatar_variant": enum("circle", "landscape"), "comment_mode": enum("feed", "fly"),
                            "scene": enum("play", "interact", "break", "recover")})
D["VisionConfig"] = obj({"enabled": BOOL, "max_concurrency": {"const": 1},
                         "min_interval_ms": integer(1000, 60000), "timeout_ms": integer(1000, 30000)})
D["GameConfig"] = obj({"schema_version": {"const": 1}, "enabled": BOOL,
                       "planner": ref("PlannerConfig"), "control": ref("ControlConfig"),
                       "programme": ref("ProgrammeConfig"), "vision": ref("VisionConfig")})
D["ConfigEnvelope"] = obj({"revision": integer(), "settings": ref("GameConfig")})
patch_properties = {"enabled": BOOL}
for name in ("Planner", "Control", "Programme", "Vision"):
    patch_properties[name.lower()] = {**deepcopy(D[name + "Config"]), "required": [], "minProperties": 1}
D["ConfigPatch"] = obj({"expected_revision": integer(),
                        "patch": {**obj(patch_properties, []), "minProperties": 1}})
D["CheckActionParams"] = obj({"goal": ref("Goal"), "base_ref": ref("BaseRef")}, ["goal"])
D["CheckActionParams"]["allOf"] = [base_binding(["goal"], "base_ref")]
D["QueryRequest"] = obj({"request_id": ID, "bridge_boot_id": ID, "world_session_id": ID,
                         "kind": enum("recipe", "check_action", "observation", "task_ledger"), "params": {"type": "object"}})
D["QueryRequest"]["allOf"] = [
    {"if": {"properties": {"kind": {"const": kind}}}, "then": {"properties": {"params": schema}}}
    for kind, schema in [
        ("recipe", obj({"item_id": ITEM, "count": integer(1, 4096)})),
        ("check_action", ref("CheckActionParams")),
        ("observation", obj({"purpose": enum("building", "screen", "text")})),
        ("task_ledger", obj({"task_ids": array(ID, 1, 1, unique=True)}))]]
D["RecipeSlot"] = obj({"index": integer(0, 8), "empty": BOOL, "alternatives": array(ITEM, 16, unique=True),
    "alternatives_total": integer(0, 8192), "truncated": BOOL})
D["RecipeChoice"] = obj({"recipe_id": ITEM, "recipe_type": ITEM, "layout": enum("shaped", "shapeless", "other"),
    "width": integer(0, 3), "height": integer(0, 3), "output_per_batch": integer(1, 4096),
    "batches": integer(1, 4096), "output_for_batches": integer(1, 8192), "ingredients_known": BOOL,
    "slots": array(ref("RecipeSlot"), 9)})
D["RecipeResult"] = obj({"kind": {"const": "recipe"}, "world_session_id": ID, "based_on_seq": integer(1),
    "source": enum("runtime_recipe_manager", "TEST_FIXTURE_ONLY"), "catalog_scope": {"const": "current_server_received"},
    "item_id": ITEM, "requested_count": integer(1, 4096), "recipe_known": BOOL, "candidate_count": integer(0, 8192),
    "ambiguous": BOOL, "recipes": array(ref("RecipeChoice"), 16), "truncated": BOOL,
    "inventory_checked": {"const": False}, "ingredient_projection": {"const": "item_ids_only"},
    "unknown_fields": array(string(160), 16, 1, unique=True)})
D["LedgerEntry"] = obj({"task_id": ID, "status": enum("found", "missing"), "task": nullable(ref("Task"))})
D["LedgerEntry"]["allOf"] = [{"if": {"properties": {"status": {"const": "found"}}},
    "then": {"properties": {"task": ref("Task")}}, "else": {"properties": {"task": {"type": "null"}}}}]
D["TaskLedgerResult"] = obj({"kind": {"const": "task_ledger"}, "game_instance_id": ID,
    "world_session_id": ID, "based_on_seq": integer(), "entries": array(ref("LedgerEntry"), 1, 1)})
D["ReconcileRequest"] = obj({"request_id": ID})
D["World"] = obj({"world_id": ID, "game_instance_id": ID, "local_label": string(80),
    "revision": integer(1), "rule_fingerprint": nullable(ID), "first_seen": TIME, "last_seen": TIME,
    "last_world_session_id": ID, "active_base_id": nullable(ID)})
D["WorldPage"] = obj({"items": array(ref("World")), "next_cursor": nullable(string(512))})
D["WorldLabelRequest"] = obj({"request_id": ID, "expected_revision": integer(1), "local_label": string(80)})
world_context = {"request_id": ID, "bridge_boot_id": ID, "world_session_id": ID}
D["BaseCreate"] = obj({**world_context, "expected_world_revision": integer(1), "label": string(80), "radius": integer(1, 128)})
D["Base"] = obj({"base_id": ID, "world_id": ID, "revision": integer(1), "label": string(80),
    "position": ref("Position"), "radius": integer(1, 128), "source": {"const": "operator_observed"},
    "world_session_id": ID, "based_on_seq": integer(), "observed_at": TIME, "created_at": TIME, "archived": BOOL})
D["BasePage"] = obj({"items": array(ref("Base")), "next_cursor": nullable(string(512))})
D["BaseArchiveRequest"] = obj({"request_id": ID, "expected_revision": integer(1), "expected_world_revision": integer(1)})
D["BaseSelectRequest"] = obj({**world_context, "expected_revision": integer(1), "expected_world_revision": integer(1)})
D["CheckpointCreate"] = obj({**world_context, "reason": string(240)})
D["Checkpoint"] = obj({"checkpoint_id": ID, "world_id": ID, "game_instance_id": ID, "world_session_id": ID,
    "bridge_boot_id": ID, "created_at": TIME, "reason": string(240), "snapshot": {"allOf": [ref("Observation"),
        {"properties": {"mode": enum("PAUSED", "MANUAL_COMMENTARY"), "inputs_released": {"const": True}, "automation_ready": {"const": False}}}]},
    "task_refs": array(ID, 100, unique=True), "base_refs": array(ID, 128, unique=True)})
D["CheckpointPage"] = obj({"items": array(ref("Checkpoint")), "next_cursor": nullable(string(512))})
D["WorldSession"] = obj({"world_session_id": ID, "world_id": ID, "game_instance_id": ID, "bridge_boot_id": nullable(ID),
    "status": enum("observed", "unobserved", "ended"), "source": enum("observed", "legacy_registry"),
    "first_observed_at": TIME, "last_observed_at": TIME, "last_seq": nullable(integer()),
    "last_connection_generation": nullable(integer(1)), "connection_count": integer(),
    "closed_at": nullable(TIME), "close_reason": nullable(string(120))})
D["WorldSessionPage"] = obj({"items": array(ref("WorldSession")), "next_cursor": nullable(string(512))})
D["GoalCondition"] = {"oneOf": [
    obj({"kind": {"const": "inventory_at_least"}, "item_id": ITEM, "count": integer(1, 4096)}),
    obj({"kind": {"const": "position_within"}, "target": ref("Position"), "radius": {"type": "number", "minimum": 0.5, "maximum": 128}}),
    obj({"kind": {"const": "food_at_least"}, "food": integer(1, 20)}),
    obj({"kind": {"const": "task_verified"}})]}
D["WorldGoalStepInput"] = obj({"step_id": ID, "label": string(100), "goal": ref("Goal"), "condition": ref("GoalCondition")})
D["WorldGoalProof"] = obj({"source": enum("observation", "task_and_observation"), "world_session_id": ID,
    "seq": integer(), "observed_at": TIME, "task_id": nullable(ID), "condition": ref("GoalCondition")})
D["WorldGoalProof"]["allOf"] = [{"if": {"properties": {"source": {"const": "observation"}}},
    "then": {"properties": {"task_id": {"type": "null"}}}, "else": {"properties": {"task_id": ID}}}]
D["WorldGoalStep"] = obj({**D["WorldGoalStepInput"]["properties"],
    "state": enum("pending", "running", "awaiting_observation", "completed", "blocked"),
    "task_ids": array(ID, 10, unique=True), "proof": nullable(ref("WorldGoalProof")), "reason": nullable(string(240))})
D["WorldGoalStep"]["allOf"] = [{"if": {"properties": {"state": {"const": "completed"}}},
    "then": {"properties": {"proof": ref("WorldGoalProof")}}, "else": {"properties": {"proof": {"type": "null"}}}}]
D["WorldGoal"] = obj({"goal_id": ID, "world_id": ID, "revision": integer(1), "title": string(100), "description": string(500, 0),
    "status": enum("draft", "active", "needs_review", "blocked", "completed", "archived"),
    "steps": array(ref("WorldGoalStep"), 16, 1), "created_at": TIME, "updated_at": TIME,
    "last_review_session_id": nullable(ID), "reason": nullable(string(240))})
D["WorldGoalPage"] = obj({"items": array(ref("WorldGoal")), "next_cursor": nullable(string(512))})
D["WorldGoalCreate"] = obj({**world_context, "expected_world_revision": integer(1), "title": string(100),
    "description": string(500, 0), "steps": array(ref("WorldGoalStepInput"), 16, 1)})
D["WorldGoalDecision"] = obj({**world_context, "expected_revision": integer(1), "action": enum("activate", "pause", "archive", "retry_step"), "reason": string(240)})
D["WorldGoalRef"] = obj({"goal_id": ID, "step_id": ID, "expected_revision": integer(1)})
D["TaskCreate"]["properties"]["world_goal_ref"] = ref("WorldGoalRef")
D["WorldGoalSummary"] = obj({"goal_id": ID, "world_id": ID, "revision": integer(1), "title": string(100),
    "status": D["WorldGoal"]["properties"]["status"], "completed_steps": integer(0, 16), "total_steps": integer(1, 16),
    "last_review_session_id": nullable(ID), "reason": nullable(string(240)), "next_step": nullable(ref("WorldGoalStep"))})
D["WorldSummary"] = obj({"world": nullable(ref("World")), "active_base": nullable(ref("Base")),
    "latest_checkpoint": nullable(obj({"checkpoint_id": ID, "created_at": TIME, "reason": string(240),
        "world_session_id": ID, "seq": integer()})), "task_recovery": array(ref("TaskRecovery"), 100),
    "current_session": nullable(ref("WorldSession")), "world_goals": array(ref("WorldGoalSummary"), 16)})
D["GameState"]["properties"]["world_ledger"] = ref("WorldSummary")
D["GameError"] = obj({"error": {**string(120), "pattern": "^[A-Z][A-Z0-9_]*$"},
                      "request_id": nullable(ID), "retryable": BOOL, "details": {"type": "object"}},
                     ["error", "request_id", "retryable"])
D["RoomSidePatch"] = obj({"expected_revision": integer(),
                          "patch": obj({"overlay": obj({"mc_chat_side": enum("left", "right")})})})
D["RoomStateSubset"] = obj({"revision": integer(), "settings": obj({
    "overlay": obj({"mc_chat_side": enum("left", "right")}, additional=True)}, additional=True)}, additional=True)
D["RoomError"] = obj({"error": string(240)}, additional=True)
D["FrameReceipt"] = obj({"frame_id": ID, "operation_id": ID, "world_session_id": ID, "source_seq": integer(),
                          "width": integer(1, 1920), "height": integer(1, 1080), "content_type": {"const": "image/jpeg"},
                          "byte_length": integer(1, 4194304), "received_at": TIME, "expires_at": TIME})
D["FrameObservation"] = obj({"kind": {"const": "observation"}, "world_session_id": ID, "frame_id": ID,
    "source_seq": integer(), "captured_at": TIME, "width": integer(1, 1920), "height": integer(1, 1080)})
D["VisionDescription"] = obj({"caption": string(2000), "visible_text": array(string(256), 16), "unknowns": array(string(240), 16)})
D["VisionResult"] = obj({**D["FrameObservation"]["properties"], **D["VisionDescription"]["properties"],
    "source": {"const": "vision_inference"}, "purpose": enum("building", "screen", "text"), "age_ms": integer(),
    "crop": obj({"x": {"const": 0}, "y": {"const": 0}, "width": integer(1, 1920), "height": integer(1, 1080)}),
    "model_id": string(120), "runtime_id": ID})
vision_pin = obj({"path": string(500), "bytes": integer(1, 100000000000), "sha256": {**string(64,64), "pattern": "^[0-9a-f]{64}$"}})
D["VisionRuntimeLock"] = obj({"schema_version": {"const": 1}, "runtime_id": ID, "base_url": string(200),
    "model_alias": string(120), "build_info": string(120), "executable": vision_pin, "model": vision_pin, "projector": vision_pin})
D["MediaInit"] = obj({"type": {"const": "media.init"}, "protocol_version": {"const": 3},
                       "stream_id": ID, "media_profile_id": ID, "width": integer(64, 4096),
                       "height": integer(64, 4096), "fps_num": integer(1, 120000), "fps_den": integer(1, 10000),
                       "codec": {**string(32), "pattern": "^avc1\\.[0-9A-Fa-f]{6}$"},
                       "avc_description_base64": {**string(65536), "contentEncoding": "base64"},
                       "audio": obj({"format": {"const": "s16le"}, "sample_rate": integer(8000, 96000), "channels": {"const": 1}}),
                       "time_base_num": {"const": 1}, "time_base_den": {"const": 1000000}, "pts_origin_us": integer()})
D["MediaReset"] = obj({"type": {"const": "media.reset"}, "protocol_version": {"const": 3},
                        "old_stream_id": ID, "new_stream_id": ID, "reason": string(120)})
D["Suggestion"] = obj({"suggestion_id": ID, "world_id": ID, "world_session_id": ID, "revision": integer(1),
                       "source_event_ids": array(string(240), 32, 1, unique=True), "goal": ref("Goal"),
                       "state": enum("proposed", "accepted", "rejected", "expired", "cancelled", "converted"),
                       "task_id": nullable(ID), "reason": nullable(string(240)), "created_at": TIME, "expires_at": TIME})
D["Suggestion"]["allOf"] = [{"if": {"properties": {"state": {"const": "converted"}}},
    "then": {"properties": {"task_id": ID}}, "else": {"properties": {"task_id": {"type": "null"}}}}]
D["SuggestionPage"] = obj({"items": array(ref("Suggestion")), "next_cursor": nullable(string(512))})
D["SuggestionOrigin"] = obj({"kind": enum("audience", "vote"), "platform": {"const": "bilibili"},
    "room_id": string(100), "vote_id": nullable(ID)})
D["SuggestionOrigin"]["allOf"] = [{"if": {"properties": {"kind": {"const": "vote"}}},
    "then": {"properties": {"vote_id": ID}}, "else": {"properties": {"vote_id": {"type": "null"}}}}]
D["Suggestion"]["properties"].update(origin=ref("SuggestionOrigin"), support_count=integer(1, 1000000))
D["Suggestion"]["dependentRequired"] = {"origin": ["support_count"], "support_count": ["origin"]}
D["SuggestionTaskRef"] = obj({"suggestion_id": ID, "expected_revision": integer(1)})
D["TaskCreate"]["properties"]["suggestion_ref"] = ref("SuggestionTaskRef")
D["SuggestionDispatch"] = obj({"request_id": ID, "bridge_boot_id": ID, "world_session_id": ID,
    "expected_control_epoch": integer(), "expected_revision": integer(1)})
D["SuggestionDecision"] = obj({"request_id": ID, "expected_revision": integer(1),
                               "action": enum("accept", "reject", "cancel"), "reason": string(240)})
D["VoteOptionInput"] = obj({"option_id": ID, "label": string(60), "goal": ref("Goal")})
D["VoteOption"] = obj({**deepcopy(D["VoteOptionInput"]["properties"]), "votes": integer(0, 1000000)})
D["VoteCreate"] = obj({"request_id": ID, "bridge_boot_id": ID, "world_session_id": ID,
                       "title": string(80), "duration_seconds": integer(30, 120),
                       "options": array(ref("VoteOptionInput"), 5, 2)})
D["Vote"] = obj({"vote_id": ID, "room_id": ID, "world_id": ID, "world_session_id": ID,
                 "revision": integer(1), "tally_version": integer(), "title": string(80),
                 "options": array(ref("VoteOption"), 5, 2), "state": enum("active", "closed", "cancelled"),
                 "created_at": TIME, "expires_at": TIME, "winning_option_id": nullable(ID), "tied": BOOL,
                 "suggestion_id": nullable(ID), "task_id": nullable(ID), "reason": nullable(string(240))})
D["Vote"]["allOf"] = [{"if": {"properties": {"state": {"enum": ["active", "cancelled"]}}}, "then": {
    "properties": {"winning_option_id": {"type": "null"}, "tied": {"const": False},
                   "suggestion_id": {"type": "null"}, "task_id": {"type": "null"}}}}]
D["VoteClose"] = obj({"request_id": ID, "expected_revision": integer(1), "action": enum("close", "cancel"),
                      "reason": string(240), "selected_option_id": ID},
                     ["request_id", "expected_revision", "action", "reason"])
D["VoteClose"]["allOf"] = [{"if": {"properties": {"action": {"const": "cancel"}}},
    "then": {"not": {"required": ["selected_option_id"]}}}]
D["VotePage"] = obj({"items": array(ref("Vote")), "next_cursor": nullable(string(512))})
D["Vote"]["allOf"].append({"if": {"properties": {"task_id": ID}}, "then": {
    "properties": {"state": {"const": "closed"}, "suggestion_id": ID, "winning_option_id": ID}}})
D["VoteSuggestionRequest"] = obj({"request_id": ID, "bridge_boot_id": ID, "world_session_id": ID,
    "expected_revision": integer(1)})
D["SuggestionFeedback"] = obj({"suggestion_id": ID, "task_id": ID, "vote_id": nullable(ID),
    "state": deepcopy(D["Task"]["properties"]["state"]), "effect_status": deepcopy(D["Task"]["properties"]["effect_status"]),
    "task_version": integer(1), "recovery_status": nullable(string(120)), "disposition_status": nullable(string(120)),
    "reason": nullable(string(240)), "evidence": array(ref("Evidence"), 8), "updated_at": TIME,
    "speech_status": {"const": "not_scheduled"}})
D["SuggestionFeedback"]["allOf"] = deepcopy(D["Task"]["allOf"])
D["Task"]["allOf"].append(base_binding(["goal"], "base_target", required=True))
D["AudienceSummary"] = obj({"platform": {"const": "bilibili"}, "room_id": nullable(string(100)),
    "server_time": TIME,
    "suggestions": array(ref("Suggestion"), 16), "votes": array(ref("Vote"), 3), "feedback": array(ref("SuggestionFeedback"), 16),
    "pending_limit": {"const": 64}, "command_hint": string(200)})
D["GameState"]["properties"]["audience"] = ref("AudienceSummary")

payloads = {
    "hello": obj({"capabilities": ref("Capabilities"), "mode": MODE, "control_epoch": integer(),
                  "world_session_id": nullable(ID)}),
    "hello_ack": obj({"controller_session_id": ID, "accepted_protocol": {"const": "1.0"},
                      "snapshot_required": {"const": True}}),
    "snapshot": ref("Observation"),
    "delta": obj({"world_session_id": ID, "base_seq": integer(), "seq": integer(), "observed_at": TIME,
                  "changes": {**obj({k: observation[k] for k in ("player", "inventory", "screen", "environment", "rule_fingerprint")}, []),
                              "minProperties": 1}}),
    "game_event": obj({"event_id": ID, "delivery_seq": integer(1), "world_session_id": ID, "seq": integer(), "occurred_at": TIME,
                       "kind": string(80), "severity": enum("normal", "important", "critical"),
                       "task_id": nullable(ID), "data": {"type": "object"}}),
    "heartbeat": obj({"heartbeat_seq": integer(1), "controller_session_id": nullable(ID), "control_epoch": nullable(integer()),
                      "last_seq": nullable(integer()), "lease_id": nullable(ID),
                      "grant_seq": nullable(integer(1)), "automation_ready": BOOL}),
    "ack": obj({"world_session_id": ID, "ack_kind": enum("events", "task_transitions"), "through_seq": integer()}),
    "snapshot_request": obj({"reason": string(120)}),
    "control_request": {**obj({**deepcopy(D["ControlRequest"]["properties"]), "operation_id": ID,
                               "controller_session_id": ID},
                              ["request_id", "target_mode", "reason", "operation_id", "controller_session_id"]),
                        "allOf": deepcopy(D["ControlRequest"]["allOf"])},
    "control_result": obj({"operation_id": ID, "request_id": ID, "world_session_id": nullable(ID),
                           "mode": MODE, "control_epoch": integer(), "inputs_released": BOOL,
                           "automation_ready": BOOL, "lease_id": nullable(ID), "heartbeat_seq": nullable(integer(1)), "error": nullable(string(120))}),
    "lease_grant": obj({"controller_session_id": ID, "lease_id": ID, "control_epoch": integer(),
                        "grant_seq": integer(1), "based_on_heartbeat_seq": integer(1), "ttl_ms": integer(1000, 10000)}),
    "task_start": obj({"controller_session_id": ID, "lease_id": ID, "control_epoch": integer(),
                       "task_id": ID, "request": ref("TaskCreate")}),
    "task_cancel": obj({"controller_session_id": ID, "operation_id": ID, "request_id": ID, "task_id": ID, "reason": string(240)}),
    "task_update": obj({"delivery_seq": integer(1), "transition_seq": integer(1), "task": ref("Task")}),
    "query": obj({"operation_id": ID, "request": ref("QueryRequest")}),
    "query_result": ref("Operation"), "protocol_error": ref("GameError")
}
for kind, path in (("task_start", ["request", "goal"]), ("query", ["request", "params", "goal"])):
    payloads[kind]["properties"]["base_target"] = ref("BaseTarget")
    payloads[kind]["allOf"] = [base_binding(path, "base_target", required=True)]
D["BridgeEnvelope"] = obj({"protocol_version": {"const": "1.0"}, "type": enum(*payloads),
                           "message_id": ID, "game_instance_id": ID, "bridge_boot_id": ID,
                           "connection_generation": integer(1), "sent_at": TIME, "payload": {"type": "object"}})
D["BridgeEnvelope"]["allOf"] = [{"if": {"properties": {"type": {"const": kind}}},
    "then": {"properties": {"payload": schema}}} for kind, schema in payloads.items()]
SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:ai-talk-streamer:mc-game:1",
          "title": "MC live v1 planned data contracts", "x-implementation-status": "planned", "$defs": D,
          "description": "Select a definition through $defs. Runtime fencing, freshness, ownership and configuration relations require business checks."}


def api_ref(name):
    return {"$ref": "#/components/schemas/" + name}


def response(name, description):
    return {"description": description, "content": {"application/json": {"schema": api_ref(name)}}}


def operation(name, summary, success, request=None, parameters=None):
    value = {"operationId": name, "summary": summary, "tags": ["MC game"],
             "x-implementation-status": "planned", "responses": {
                 str(code): response(schema, description) for code, schema, description in success}}
    for code in (400, 409, 413, 429, 503, 504):
        value["responses"][str(code)] = response("GameError", "游戏错误；按04章处理，不盲目重复副作用")
    if request:
        value["requestBody"] = {"required": True, "content": {"application/json": {"schema": api_ref(request)}}}
    if parameters:
        value["parameters"] = parameters
    return value


def path_parameter(name):
    return {"name": name, "in": "path", "required": True, "schema": ID}


paths = {}
prefix = "/api/dsh/game"
for suffix, name, summary, schema in [
    ("state", "gameState", "最新状态及新鲜度", "GameState"),
    ("capabilities", "gameCapabilities", "当前桥实际能力", "Capabilities"),
    ("config", "gameConfig", "MC配置与修订", "ConfigEnvelope")]:
    paths[prefix + "/" + suffix] = {"get": operation(name, summary, [(200, schema, "当前值")])}
paths[prefix + "/config"]["post"] = operation("patchGameConfig", "CAS更新MC配置", [(200, "ConfigEnvelope", "已保存")], "ConfigPatch")
paths[prefix + "/control"] = {"post": operation("controlGame", "异步请求模式；以B确认生效", [(202, "Operation", "已受理，尚未确认切换")], "ControlRequest")}
paths[prefix + "/tasks"] = {
    "get": operation("listGameTasks", "游标分页查询任务", [(200, "TaskPage", "任务列表")], parameters=[
        {"name": "cursor", "in": "query", "schema": string(512)},
        {"name": "limit", "in": "query", "schema": {**integer(1, 100), "default": 20}},
        {"name": "world_id", "in": "query", "schema": ID, "description": "仅返回指定已登记世界的任务；省略时保留全局列表"}]),
    "post": operation("startGameTask", "启动固定技能；不代表完成", [(202, "Task", "新任务"), (200, "Task", "幂等已有任务")], "TaskCreate")}
paths[prefix + "/tasks/{task_id}"] = {"get": operation("getGameTask", "查询任务及证据", [(200, "Task", "任务"), (404, "GameError", "不存在")], parameters=[path_parameter("task_id")])}
paths[prefix + "/tasks/{task_id}/cancel"] = {"post": operation("cancelGameTask", "请求停止后续动作", [(202, "Operation", "取消操作"), (404, "GameError", "不存在")], "CancelRequest", [path_parameter("task_id")])}
paths[prefix + "/queries"] = {"post": operation("queryGame", "配方/前置检查/按需观察", [(202, "Operation", "查询操作")], "QueryRequest")}
paths[prefix + "/operations/{operation_id}"] = {"get": operation("getGameOperation", "查询异步控制与查询结果", [(200, "Operation", "操作"), (404, "GameError", "不存在")], parameters=[path_parameter("operation_id")])}
paths[prefix + "/panic"] = {"post": operation("panicGame", "并行请求游戏停控和Room panic", [(202, "Operation", "分项确认操作")], "PanicRequest")}
frame_headers = [
    {"name": name, "in": "header", "required": True, "schema": value}
    for name, value in (("X-MC-Operation-Id", ID), ("X-MC-Bridge-Boot-Id", ID), ("X-MC-World-Session-Id", ID),
                        ("X-MC-Seq", integer()), ("X-MC-Captured-At", TIME),
                        ("X-MC-Width", integer(1, 1920)), ("X-MC-Height", integer(1, 1080))) ]
frame_post = operation("uploadGameFrame", "仅接收待处理观察操作关联的原始游戏JPEG", [(201, "FrameReceipt", "短时帧引用")],
                       parameters=[path_parameter("frame_id"), *frame_headers])
frame_post["requestBody"] = {"required": True, "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}}}
paths[prefix + "/frames/{frame_id}"] = {
    "post": frame_post,
    "get": {"operationId": "getGameFrame", "summary": "本地视觉读取短时帧；非长期截图库", "tags": ["Planned game"],
            "x-implementation-status": "planned", "parameters": [path_parameter("frame_id")],
            "responses": {"200": {"description": "JPEG；no-store，默认30秒过期", "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}}},
                          "404": response("GameError", "不存在或已过期"), "503": response("GameError", "服务未启用")}}}
paths[prefix + "/events"] = {"get": {
    "operationId": "gameEvents", "summary": "先快照后更新的只读SSE", "tags": ["Planned game"], "x-implementation-status": "planned",
    "responses": {"200": {"description": "snapshot/state/task/operation/suggestion/vote/health；非历史事件回放",
                          "content": {"text/event-stream": {"schema": {"type": "string"}}}},
                  "503": response("GameError", "服务不可用")}}}
page_parameters = [{"name": "cursor", "in": "query", "schema": string(512)},
                   {"name": "limit", "in": "query", "schema": {**integer(1, 100), "default": 20}}]
paths[prefix + "/tasks/{task_id}/reconcile"] = {"post": operation("reconcileGameTask", "从B账本核对任务；不重放动作",
    [(202, "Operation", "只读核对操作")], "ReconcileRequest", [path_parameter("task_id")])}
paths[prefix + "/tasks/{task_id}/disposition"] = {"post": operation("closeUnknownGameTask", "停控后确认未知结果；保留B任务和证据，不恢复自动控制",
    [(200, "Task", "含独立人工处置记录")], "TaskDispositionRequest", [path_parameter("task_id")])}
paths[prefix + "/worlds/{world_id}/sessions"] = {"get": operation("listGameWorldSessions", "世界会话观测历史；不推断断线期间状态",
    [(200, "WorldSessionPage", "会话分页")], parameters=[path_parameter("world_id"), *page_parameters])}
paths[prefix + "/world-sessions/{world_session_id}"] = {"get": operation("getGameWorldSession", "读取持久会话观测记录",
    [(200, "WorldSession", "会话")], parameters=[path_parameter("world_session_id")])}
paths[prefix + "/worlds/{world_id}/goals"] = {
    "get": operation("listGameWorldGoals", "世界目标及历史步骤证明", [(200, "WorldGoalPage", "目标分页")], parameters=[path_parameter("world_id"), *page_parameters]),
    "post": operation("createGameWorldGoal", "停控后登记待批准的有界目标", [(201, "WorldGoal", "目标"), (200, "WorldGoal", "幂等目标")], "WorldGoalCreate", [path_parameter("world_id")])}
paths[prefix + "/world-goals/{goal_id}"] = {"get": operation("getGameWorldGoal", "读取目标、任务引用与观测证明",
    [(200, "WorldGoal", "目标")], parameters=[path_parameter("goal_id")])}
paths[prefix + "/world-goals/{goal_id}/decision"] = {"post": operation("decideGameWorldGoal", "停控后CAS批准、暂停、归档或允许重新规划；不重放旧任务",
    [(200, "WorldGoal", "最新目标")], "WorldGoalDecision", [path_parameter("goal_id")])}
paths[prefix + "/worlds"] = {"get": operation("listGameWorlds", "已观测的持久世界登记", [(200, "WorldPage", "世界分页")], parameters=page_parameters)}
paths[prefix + "/worlds/{world_id}"] = {"get": operation("getGameWorld", "读取世界登记", [(200, "World", "世界")], parameters=[path_parameter("world_id")])}
paths[prefix + "/worlds/{world_id}/label"] = {"post": operation("labelGameWorld", "CAS修改显示名，不改变世界身份", [(200, "World", "世界")], "WorldLabelRequest", [path_parameter("world_id")])}
paths[prefix + "/worlds/{world_id}/bases"] = {
    "get": operation("listGameBases", "当前世界已登记基地", [(200, "BasePage", "基地分页")], parameters=[path_parameter("world_id"), *page_parameters]),
    "post": operation("registerGameBase", "从新鲜的实际玩家位置登记基地", [(201, "Base", "基地"), (200, "Base", "幂等基地")], "BaseCreate", [path_parameter("world_id")])}
paths[prefix + "/worlds/{world_id}/bases/{base_id}/archive"] = {"post": operation("archiveGameBase", "CAS归档基地并清空活动基地引用",
    [(200, "Base", "已归档基地")], "BaseArchiveRequest", [path_parameter("world_id"), path_parameter("base_id")])}
paths[prefix + "/worlds/{world_id}/bases/{base_id}/select"] = {"post": operation("selectGameBase", "停控后CAS选择当前世界活动基地；不执行返回基地",
    [(200, "World", "更新后的世界登记")], "BaseSelectRequest", [path_parameter("world_id"), path_parameter("base_id")])}
paths[prefix + "/worlds/{world_id}/checkpoints"] = {
    "get": operation("listGameCheckpoints", "读取历史检查点，不恢复自动输入", [(200, "CheckpointPage", "检查点分页")], parameters=[path_parameter("world_id"), *page_parameters]),
    "post": operation("createGameCheckpoint", "停控确认后保存观测与任务/基地引用", [(201, "Checkpoint", "检查点"), (200, "Checkpoint", "幂等检查点")], "CheckpointCreate", [path_parameter("world_id")])}
paths[prefix + "/checkpoints/{checkpoint_id}"] = {"get": operation("getGameCheckpoint", "读取不可变检查点", [(200, "Checkpoint", "检查点")], parameters=[path_parameter("checkpoint_id")])}
paths[prefix + "/suggestions"] = {"get": operation("listGameSuggestions", "当前世界受审建议分页",
    [(200, "SuggestionPage", "建议列表")], parameters=page_parameters)}
paths[prefix + "/suggestions/{suggestion_id}/decision"] = {"post": operation("decideGameSuggestion", "CAS采纳、拒绝或取消候选；不直接宣称任务已完成",
    [(200, "Suggestion", "建议最新状态"), (404, "GameError", "不存在")], "SuggestionDecision", [path_parameter("suggestion_id")])}
paths[prefix + "/suggestions/{suggestion_id}/dispatch"] = {"post": operation("dispatchGameSuggestion", "重新核验前置条件后关联并受理一个任务；不改变控制模式",
    [(202, "Operation", "异步核验及本地任务受理操作")], "SuggestionDispatch", [path_parameter("suggestion_id")])}
paths[prefix + "/audience"] = {"get": operation("getGameAudience", "当前B站房间的有界候选、投票及真实任务反馈；不会发声",
    [(200, "AudienceSummary", "互动摘要")])}
paths[prefix + "/votes"] = {
    "get": operation("listGameVotes", "当前房间投票摘要分页，不暴露选民身份", [(200, "VotePage", "投票列表")], parameters=page_parameters),
    "post": operation("createGameVote", "创建有界固定选项投票，同房间最多一个活动投票",
                      [(201, "Vote", "新投票"), (200, "Vote", "幂等已有投票")], "VoteCreate")}
paths[prefix + "/votes/{vote_id}"] = {"get": operation("getGameVote", "查询计数、状态与截止结果",
    [(200, "Vote", "投票状态"), (404, "GameError", "不存在")], parameters=[path_parameter("vote_id")])}
paths[prefix + "/votes/{vote_id}/close"] = {"post": operation("closeGameVote", "CAS关闭或取消；平票由后台明确决定",
    [(200, "Vote", "投票最新状态"), (404, "GameError", "不存在")], "VoteClose", [path_parameter("vote_id")])}
paths[prefix + "/votes/{vote_id}/suggestion"] = {"post": operation("promoteGameVote", "将已确定的胜出选项生成待审核建议；不会直接执行",
    [(201, "Suggestion", "待审核建议"), (200, "Suggestion", "已有建议")], "VoteSuggestionRequest", [path_parameter("vote_id")])}
paths["/api/dsh/room/config"] = {"post": {
    "operationId": "patchMcChatSide", "summary": "已有Room接口：MC留言换边子集", "tags": ["Existing room subset"],
    "x-implementation-status": "implemented_local_validation_only",
    "requestBody": {"required": True, "content": {"application/json": {"schema": api_ref("RoomSidePatch")}}},
    "responses": {"200": response("RoomStateSubset", "完整RoomState；此处仅定义换边相关字段"),
                  "400": response("RoomError", "值非法"), "409": response("RoomError", "修订冲突")}}}
for route, methods in paths.items():
    if route.startswith(prefix + "/"):
        for value in methods.values():
            value["x-implementation-status"] = "implemented_protocol_tests_only"
            value["x-game-runtime-acceptance"] = "not_run"
OPENAPI = {"openapi": "3.1.0", "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
           "info": {"title": "林知夏MC直播接口技术设计", "version": "1.5.0",
                    "description": "服务端核心、短时帧上传/读取及原生视觉适配器已有源码与隔离协议检查；真实MC、CUDA推理及完整系统未验收。已有Room仅描述留言换边子集。202/accepted不代表游戏完成。"},
           "servers": [{"url": "/", "description": "现有8010/8020同源代理入口"}], "security": [],
           "tags": [{"name": "MC game"}, {"name": "Planned game"}, {"name": "Existing room subset"}], "paths": paths,
           "components": {"schemas": {name: {"$ref": "./game.schema.json#/$defs/" + name} for name in D}}}

NOW = "2026-10-30T04:00:00Z"
GOAL = {"skill": "gather", "item_id": "minecraft:oak_log", "count": 4}
CONFIG = {"schema_version": 1, "enabled": False,
          "planner": {"enabled": False, "min_interval_ms": 3000, "max_call_ms": 30000, "candidate_limit": 16},
          "control": {"state_stale_ms": 2000, "heartbeat_ms": 1000, "lease_ttl_ms": 3000,
                      "accept_within_ms": 1500, "max_task_duration_ms": 120000, "enabled_skills": []},
          "programme": {"layout_id": "mc-landscape-v1", "avatar_variant": "circle", "comment_mode": "feed", "scene": "play"},
          "vision": {"enabled": False, "max_concurrency": 1, "min_interval_ms": 1000, "timeout_ms": 8000}}
TASK_REQUEST = {"request_id": "req-gather-001", "bridge_boot_id": "boot-example-001",
                "world_session_id": "world-session-example-001", "expected_control_epoch": 7,
                "based_on_seq": 1042, "accept_within_ms": 1500, "max_duration_ms": 120000, "goal": GOAL}
STATE = {"schema_version": 1, "game_instance_id": "mc-instance-example", "bridge_boot_id": "boot-example-001",
         "world_id": "world-example-001", "world_session_id": "world-session-example-001",
         "connection_generation": 1, "seq": 1042, "connected": True, "freshness": "fresh", "age_ms": 80,
         "observed_at": NOW, "rule_fingerprint": "rules-example-001", "mode": "MANUAL_COMMENTARY",
         "control_epoch": 7, "inputs_released": True, "automation_ready": False, "lease_remaining_ms": None,
         "player": {"health": 18, "max_health": 20, "food": 16, "oxygen": 300,
                    "position": {"dimension": "minecraft:overworld", "x": 32, "y": 64, "z": 48}},
         "inventory": [{"item_id": "minecraft:oak_log", "count": 3}], "screen": "gameplay",
         "environment": {"loaded_radius_chunks": 8, "nearby_threats": 0},
         "unknown_fields": ["unloaded_region", "unopened_container_contents"], "active_task_id": None, "view_revision": 12}
TASK = {"task_id": "task-example-001", "game_instance_id": "mc-instance-example", "bridge_boot_id": "boot-example-001",
        "world_id": "world-example-001", "world_session_id": "world-session-example-001", "request_id": "req-gather-001",
        "control_epoch": 7, "version": 3, "goal": GOAL, "state": "succeeded", "created_at": NOW, "updated_at": NOW,
        "reason": None, "effect_status": "verified", "evidence": [{"world_session_id": "world-session-example-001",
            "seq": 1088, "kind": "inventory", "summary": "虚构样例：关联拾取核验原木增量4；不是实测"}]}
CAPABILITIES = {"protocol_version": "1.0", "game_instance_id": "mc-instance-example", "adapter": "minecraft.fabric",
                "game_version": "1.21.1", "mod_version": "planned-1.0", "execution_profile": "baritone_base",
                "skills": ["navigate", "gather", "craft", "use_item", "return_base", "cancel"], "item_uses": ["eat"],
                "features": {"recipes": True, "screenshots": False, "local_takeover": True, "cancel_all": True},
                "rule_fingerprint": "rules-example-001"}
OP = {"operation_id": "op-manual-example", "request_id": "req-manual-001", "kind": "control", "state": "succeeded",
      "created_at": NOW, "updated_at": NOW, "result": {"mode": "MANUAL_COMMENTARY", "control_epoch": 8,
      "inputs_released": True, "automation_ready": False}, "error": None}
BRIDGE = {"protocol_version": "1.0", "type": "hello", "message_id": "message-example-001",
          "game_instance_id": "mc-instance-example", "bridge_boot_id": "boot-example-001",
          "connection_generation": 1, "sent_at": NOW,
          "payload": {"capabilities": CAPABILITIES, "mode": "PAUSED", "control_epoch": 7, "world_session_id": "world-session-example-001"}}
RECIPE_RESULT = {"kind": "recipe", "world_session_id": "world-session-example-001", "based_on_seq": 1043,
    "source": "TEST_FIXTURE_ONLY", "catalog_scope": "current_server_received", "item_id": "minecraft:iron_pickaxe",
    "requested_count": 1, "recipe_known": True, "candidate_count": 1, "ambiguous": False, "truncated": False,
    "inventory_checked": False, "ingredient_projection": "item_ids_only",
    "unknown_fields": ["ingredient_components", "remaining_items", "recipe_unlock_requirements",
        "server_side_crafting_restrictions", "inventory_allocation", "unreceived_server_recipes", "dynamic_recipe_outputs"],
    "recipes": [{"recipe_id": "minecraft:iron_pickaxe", "recipe_type": "minecraft:crafting", "layout": "shaped",
        "width": 3, "height": 3, "output_per_batch": 1, "batches": 1, "output_for_batches": 1, "ingredients_known": True,
        "slots": [{"index": i, "empty": item is None, "alternatives": [] if item is None else [item],
                   "alternatives_total": 0 if item is None else 1, "truncated": False}
                  for i, item in enumerate(["minecraft:iron_ingot"]*3 + [None, "minecraft:stick", None]*2)]}]}
EXAMPLES = {"classification": "FICTIONAL_CONTRACT_EXAMPLES_NOT_RUNTIME_EVIDENCE", "cases": [
    {"name": "state-manual", "definition": "GameState", "value": STATE},
    {"name": "task-start", "definition": "TaskCreate", "value": TASK_REQUEST},
    {"name": "task-complete", "definition": "Task", "value": TASK},
    {"name": "control-manual", "definition": "ControlRequest", "value": {"request_id": "req-manual-001", "target_mode": "MANUAL_COMMENTARY", "reason": "operator_takeover"}},
    {"name": "control-auto", "definition": "ControlRequest", "value": {"request_id": "req-auto-001", "target_mode": "AUTO", "reason": "operator_resume", "bridge_boot_id": "boot-example-001", "world_session_id": "world-session-example-001", "expected_control_epoch": 7}},
    {"name": "default-config", "definition": "GameConfig", "value": CONFIG},
    {"name": "config-envelope", "definition": "ConfigEnvelope", "value": {"revision": 0, "settings": CONFIG}},
    {"name": "config-patch", "definition": "ConfigPatch", "value": {"expected_revision": 0, "patch": {"programme": {"avatar_variant": "landscape"}}}},
    {"name": "recipe-query", "definition": "QueryRequest", "value": {"request_id": "query-recipe-001", "bridge_boot_id": "boot-example-001", "world_session_id": "world-session-example-001", "kind": "recipe", "params": {"item_id": "minecraft:iron_pickaxe", "count": 1}}},
    {"name": "capabilities", "definition": "Capabilities", "value": CAPABILITIES},
    {"name": "control-result", "definition": "Operation", "value": OP},
    {"name": "bridge-hello", "definition": "BridgeEnvelope", "value": BRIDGE},
    {"name": "room-side", "definition": "RoomSidePatch", "value": {"expected_revision": 12, "patch": {"overlay": {"mc_chat_side": "left"}}}},
    {"name": "error", "definition": "GameError", "value": {"error": "GAME_STATE_STALE", "request_id": None, "retryable": True}}]}
offline = deepcopy(STATE)
offline.update(connected=False, freshness="stale", age_ms=3100, automation_ready=False)
EXAMPLES["cases"].append({"name": "state-disconnected", "definition": "GameState", "value": offline})
sample_query = deepcopy(EXAMPLES["cases"][8]["value"])
wire_control = {**EXAMPLES["cases"][3]["value"], "operation_id": "op-manual-example", "controller_session_id": "controller-example"}
wire_samples = {
    "hello_ack": {"controller_session_id": "controller-example", "accepted_protocol": "1.0", "snapshot_required": True},
    "snapshot": {k: STATE[k] for k in observation},
    "delta": {"world_session_id": "world-session-example-001", "base_seq": 1042, "seq": 1043,
              "observed_at": NOW, "changes": {"player": STATE["player"]}},
    "game_event": {"event_id": "event-example", "delivery_seq": 1, "world_session_id": "world-session-example-001",
                   "seq": 1043, "occurred_at": NOW, "kind": "inventory_changed", "severity": "important", "task_id": None, "data": {}},
    "heartbeat": {"heartbeat_seq": 1, "controller_session_id": "controller-example", "control_epoch": 7, "last_seq": 1043,
                  "lease_id": None, "grant_seq": None, "automation_ready": False},
    "ack": {"world_session_id": "world-session-example-001", "ack_kind": "events", "through_seq": 1},
    "snapshot_request": {"reason": "sequence_gap"}, "control_request": wire_control,
    "control_result": {"operation_id": "op-manual-example", "request_id": "req-manual-001",
                       "world_session_id": "world-session-example-001", "mode": "MANUAL_COMMENTARY",
                       "control_epoch": 8, "inputs_released": True, "automation_ready": False, "lease_id": None, "heartbeat_seq": None, "error": None},
    "lease_grant": {"controller_session_id": "controller-example", "lease_id": "lease-example", "control_epoch": 7, "grant_seq": 1, "based_on_heartbeat_seq": 1, "ttl_ms": 3000},
    "task_start": {"controller_session_id": "controller-example", "lease_id": "lease-example", "control_epoch": 7, "task_id": "task-example-001", "request": TASK_REQUEST},
    "task_cancel": {"controller_session_id": "controller-example", "operation_id": "op-cancel-example", "request_id": "req-cancel-001", "task_id": "task-example-001", "reason": "operator_cancel"},
    "task_update": {"delivery_seq": 1, "transition_seq": 3, "task": TASK},
    "query": {"operation_id": "op-query-example", "request": sample_query},
    "query_result": {**OP, "operation_id": "op-query-example", "request_id": sample_query["request_id"], "kind": "query",
                     "result": deepcopy(RECIPE_RESULT)},
    "protocol_error": {"error": "GAME_REQUEST_INVALID", "request_id": None, "retryable": False}
}
EXAMPLES["cases"].append({"name": "recipe-result", "definition": "RecipeResult", "value": deepcopy(RECIPE_RESULT)})
for index, (kind, payload) in enumerate(wire_samples.items(), 2):
    sample = {**deepcopy(BRIDGE), "type": kind, "message_id": "message-example-" + str(index), "payload": payload}
    EXAMPLES["cases"].append({"name": "bridge-" + kind, "definition": "BridgeEnvelope", "value": sample})
EXAMPLES["cases"].append({"name": "media-init-fixture", "definition": "MediaInit", "value": {
    "type": "media.init", "protocol_version": 3, "stream_id": "stream-example", "media_profile_id": "portrait-fixture",
    "width": 720, "height": 1280, "fps_num": 25, "fps_den": 1, "codec": "avc1.42c01f",
    "avc_description_base64": "AA==", "audio": {"format": "s16le", "sample_rate": 24000, "channels": 1},
    "time_base_num": 1, "time_base_den": 1000000, "pts_origin_us": 0}})
SUGGESTION = {"suggestion_id": "suggestion-example-001", "world_id": "world-example-001",
              "world_session_id": "world-session-example-001", "revision": 2,
              "source_event_ids": ["platform-event-example-001"], "goal": GOAL, "state": "accepted",
              "task_id": None, "reason": "虚构样例：已采纳候选，仍待AUTO及前置检查", "created_at": NOW,
              "expires_at": "2026-10-30T04:02:00Z"}
VOTE_OPTIONS = [{"option_id": "logs", "label": "补充原木", "goal": GOAL},
                {"option_id": "planks", "label": "合成木板", "goal": {"skill": "craft", "item_id": "minecraft:oak_planks", "count": 4}}]
VOTE = {"vote_id": "vote-example-001", "room_id": "room-example-001", "world_id": "world-example-001",
        "world_session_id": "world-session-example-001", "revision": 1, "tally_version": 0,
        "title": "虚构样例：接下来做什么", "options": [{**item, "votes": 0} for item in VOTE_OPTIONS],
        "state": "active", "created_at": NOW, "expires_at": "2026-10-30T04:01:00Z",
        "winning_option_id": None, "tied": False, "suggestion_id": None, "task_id": None, "reason": None}
EXAMPLES["cases"].extend([
    {"name": "suggestion-accepted", "definition": "Suggestion", "value": SUGGESTION},
    {"name": "suggestion-decision", "definition": "SuggestionDecision", "value": {
        "request_id": "req-suggestion-001", "expected_revision": 1, "action": "accept", "reason": "operator_accept"}},
    {"name": "vote-create", "definition": "VoteCreate", "value": {"request_id": "req-vote-001",
        "bridge_boot_id": "boot-example-001", "world_session_id": "world-session-example-001",
        "title": VOTE["title"], "duration_seconds": 60, "options": VOTE_OPTIONS}},
    {"name": "vote-active", "definition": "Vote", "value": VOTE},
    {"name": "vote-close", "definition": "VoteClose", "value": {"request_id": "req-vote-close-001",
        "expected_revision": 1, "action": "close", "reason": "operator_close"}},
    {"name": "capabilities-survival-fixture", "definition": "Capabilities", "value": {**CAPABILITIES,
        "execution_profile": "altoclef_survival", "features": {**CAPABILITIES["features"], "screenshots": True,
            "basic_pve": True, "survival_rules": True, "resource_chains": True}}},
    {"name": "suggestion-converted-fixture", "definition": "Suggestion", "value": {**SUGGESTION,
        "state": "converted", "revision": 3, "task_id": "task-example-001", "reason": "虚构样例：前置核验后关联任务"}},
    {"name": "vote-tied-fixture", "definition": "Vote", "value": {**VOTE, "state": "closed",
        "revision": 2, "tally_version": 2, "tied": True, "options": [{**item, "votes": 1} for item in VOTE_OPTIONS],
        "reason": "虚构样例：截止平票，等待后台明确选择"}}
])

WORLD = {"world_id": "world-example-001", "game_instance_id": "mc-instance-example", "local_label": "虚构样例世界",
    "revision": 1, "rule_fingerprint": None, "first_seen": NOW, "last_seen": NOW,
    "last_world_session_id": "world-session-example-001", "active_base_id": None}
BASE_EXAMPLE = {"base_id": "base-example-001", "world_id": WORLD["world_id"], "revision": 1, "label": "虚构基地",
    "position": {"dimension": "minecraft:overworld", "x": 0, "y": 64, "z": 0}, "radius": 8,
    "source": "operator_observed", "world_session_id": WORLD["last_world_session_id"], "based_on_seq": 1,
    "observed_at": NOW, "created_at": NOW, "archived": False}
RECOVERY = {"task_id": TASK["task_id"], "revision": 1, "status": "required", "reason": "INTERRUPTED_HOST_RESTART",
    "created_at": NOW, "updated_at": NOW, "attempts": 0, "checked_bridge_boot_id": None, "confirmed_version": None, "last_error": None}
checkpoint_observation = deepcopy(wire_samples["snapshot"])
checkpoint_observation.update(mode="PAUSED", automation_ready=False, inputs_released=True, lease_remaining_ms=None)
WORLD_CONTEXT = {"request_id": "request-world-example", "bridge_boot_id": "boot-example-001", "world_session_id": "world-session-example-001"}
EXAMPLES["cases"].extend([
    {"name": "world-record", "definition": "World", "value": WORLD},
    {"name": "world-label", "definition": "WorldLabelRequest", "value": {"request_id": "label-example", "expected_revision": 1, "local_label": "虚构新名称"}},
    {"name": "base-record", "definition": "Base", "value": BASE_EXAMPLE},
    {"name": "base-create", "definition": "BaseCreate", "value": {**WORLD_CONTEXT, "expected_world_revision": 1, "label": "虚构基地", "radius": 8}},
    {"name": "base-archive", "definition": "BaseArchiveRequest", "value": {"request_id": "archive-example", "expected_revision": 1, "expected_world_revision": 2}},
    {"name": "checkpoint-record", "definition": "Checkpoint", "value": {"checkpoint_id": "checkpoint-example", "world_id": WORLD["world_id"],
        "game_instance_id": WORLD["game_instance_id"], "world_session_id": WORLD["last_world_session_id"], "bridge_boot_id": "boot-example-001",
        "created_at": NOW, "reason": "虚构检查点", "snapshot": checkpoint_observation, "task_refs": [TASK["task_id"]], "base_refs": [BASE_EXAMPLE["base_id"]]}},
    {"name": "checkpoint-create", "definition": "CheckpointCreate", "value": {**WORLD_CONTEXT, "reason": "operator_stop"}},
    {"name": "task-recovery", "definition": "TaskRecovery", "value": RECOVERY},
    {"name": "ledger-query", "definition": "QueryRequest", "value": {**WORLD_CONTEXT, "kind": "task_ledger", "params": {"task_ids": [TASK["task_id"]]}}},
    {"name": "ledger-result", "definition": "TaskLedgerResult", "value": {"kind": "task_ledger", "game_instance_id": WORLD["game_instance_id"],
        "world_session_id": WORLD["last_world_session_id"], "based_on_seq": 1, "entries": [{"task_id": TASK["task_id"], "status": "found", "task": TASK}]}}
])


SESSION_EXAMPLE = {"world_session_id": WORLD["last_world_session_id"], "world_id": WORLD["world_id"],
    "game_instance_id": WORLD["game_instance_id"], "bridge_boot_id": "boot-example-001", "status": "observed", "source": "observed",
    "first_observed_at": NOW, "last_observed_at": NOW, "last_seq": 1, "last_connection_generation": 1,
    "connection_count": 1, "closed_at": None, "close_reason": None}
STEP_EXAMPLE = {"step_id": "step-logs", "label": "虚构木材目标", "goal": GOAL,
    "condition": {"kind": "inventory_at_least", "item_id": "minecraft:oak_log", "count": 4}}
GOAL_EXAMPLE = {"goal_id": "world-goal-example", "world_id": WORLD["world_id"], "revision": 1, "title": "虚构生存目标",
    "description": "仅为契约样例", "status": "draft", "steps": [{**STEP_EXAMPLE, "state": "pending", "task_ids": [], "proof": None, "reason": None}],
    "created_at": NOW, "updated_at": NOW, "last_review_session_id": None, "reason": None}
DISPOSITION_REQUEST = {**WORLD_CONTEXT, "expected_control_epoch": 7, "based_on_seq": 1, "expected_task_version": 1,
    "expected_recovery_revision": 2, "acknowledge_unknown": True, "reason": "虚构人工记录：确认按未知结果处理"}
DISPOSITION_EXAMPLE = {"task_id": TASK["task_id"], "revision": 1, "status": "closed_unknown", "reason": DISPOSITION_REQUEST["reason"],
    "acknowledged_unknown": True, "task_version": 1, "task_hash": "0" * 64, "recovery_revision": 2, "created_at": NOW,
    "updated_at": NOW, "reopen_reason": None, "observed_context": {key: checkpoint_observation[key] for key in
        ("game_instance_id", "bridge_boot_id", "world_id", "world_session_id", "seq", "control_epoch", "mode", "inputs_released", "active_task_id", "observed_at")}}
EXAMPLES["cases"].extend([
    {"name": "world-session", "definition": "WorldSession", "value": SESSION_EXAMPLE},
    {"name": "world-goal", "definition": "WorldGoal", "value": GOAL_EXAMPLE},
    {"name": "world-goal-create", "definition": "WorldGoalCreate", "value": {**WORLD_CONTEXT, "expected_world_revision": 1,
        "title": GOAL_EXAMPLE["title"], "description": GOAL_EXAMPLE["description"], "steps": [STEP_EXAMPLE]}},
    {"name": "world-goal-decision", "definition": "WorldGoalDecision", "value": {**WORLD_CONTEXT, "expected_revision": 1, "action": "activate", "reason": "虚构本会话批准"}},
    {"name": "world-goal-proof", "definition": "WorldGoalProof", "value": {"source": "observation", "world_session_id": SESSION_EXAMPLE["world_session_id"],
        "seq": 2, "observed_at": NOW, "task_id": None, "condition": STEP_EXAMPLE["condition"]}},
    {"name": "task-disposition-request", "definition": "TaskDispositionRequest", "value": DISPOSITION_REQUEST},
    {"name": "task-disposition", "definition": "TaskDisposition", "value": DISPOSITION_EXAMPLE}
])


FRAME_EXAMPLE = {"kind": "observation", "world_session_id": "world-session-example-001", "frame_id": "frame-example-001",
    "source_seq": 9, "captured_at": "2026-10-30T04:00:00.123456789Z", "width": 1920, "height": 1080}
EXAMPLES["cases"].extend([
    {"name": "observation-query", "definition": "QueryRequest", "value": {"request_id": "observation-example-001",
        "bridge_boot_id": "boot-example-001", "world_session_id": "world-session-example-001", "kind": "observation", "params": {"purpose": "screen"}}},
    {"name": "frame-observation", "definition": "FrameObservation", "value": FRAME_EXAMPLE},
    {"name": "frame-receipt", "definition": "FrameReceipt", "value": {key: FRAME_EXAMPLE[key] for key in ("frame_id", "world_session_id", "source_seq", "width", "height")} |
        {"operation_id": "operation-example-001", "content_type": "image/jpeg", "byte_length": 131072, "received_at": NOW, "expires_at": "2026-10-30T04:00:30Z"}},
    {"name": "vision-result", "definition": "VisionResult", "value": {**FRAME_EXAMPLE, "source": "vision_inference", "purpose": "screen", "age_ms": 500,
        "crop": {"x": 0, "y": 0, "width": 1920, "height": 1080}, "caption": "虚构示例，不代表模型已安装或推理通过", "visible_text": [],
        "unknowns": ["无法从此示例判断真实游戏状态"], "model_id": "fixture-model", "runtime_id": "fixture-runtime"}},
    {"name": "vision-runtime-lock", "definition": "VisionRuntimeLock", "value": {"schema_version": 1, "runtime_id": "fixture-runtime", "base_url": "http://127.0.0.1:8019/",
        "model_alias": "fixture-model", "build_info": "TEST_FIXTURE_ONLY", **{key: {"path": "fixtures/" + key, "bytes": 1, "sha256": "0" * 64} for key in ("executable", "model", "projector")}}}
])


AUDIENCE_SUGGESTION = {**SUGGESTION, "origin": {"kind": "audience", "platform": "bilibili", "room_id": "100", "vote_id": None}, "support_count": 1}
AUDIENCE_FEEDBACK = {"suggestion_id": SUGGESTION["suggestion_id"], "task_id": TASK["task_id"], "vote_id": None,
    "state": "succeeded", "effect_status": "verified", "task_version": 3, "recovery_status": None, "disposition_status": None,
    "reason": None, "evidence": TASK["evidence"][:8], "updated_at": NOW, "speech_status": "not_scheduled"}
EXAMPLES["cases"].extend([
    {"name": "audience-suggestion", "definition": "Suggestion", "value": AUDIENCE_SUGGESTION},
    {"name": "suggestion-task-ref", "definition": "SuggestionTaskRef", "value": {"suggestion_id": SUGGESTION["suggestion_id"], "expected_revision": 2}},
    {"name": "suggestion-dispatch", "definition": "SuggestionDispatch", "value": {"request_id": "dispatch-example", "bridge_boot_id": "boot-example-001", "world_session_id": SUGGESTION["world_session_id"], "expected_control_epoch": 7, "expected_revision": 2}},
    {"name": "vote-suggestion-request", "definition": "VoteSuggestionRequest", "value": {"request_id": "promote-example", "bridge_boot_id": "boot-example-001", "world_session_id": VOTE["world_session_id"], "expected_revision": 2}},
    {"name": "audience-feedback", "definition": "SuggestionFeedback", "value": AUDIENCE_FEEDBACK},
    {"name": "audience-summary", "definition": "AudienceSummary", "value": {"platform": "bilibili", "room_id": "100", "server_time": NOW,
        "suggestions": [AUDIENCE_SUGGESTION], "votes": [], "feedback": [AUDIENCE_FEEDBACK], "pending_limit": 64, "command_hint": "建议 采集 minecraft:oak_log 4"}}
])


EXAMPLES["cases"].append({"name": "base-select", "definition": "BaseSelectRequest", "value": {
    "request_id": "select-base-example", "bridge_boot_id": "boot-example-001", "world_session_id": "world-session-example-001",
    "expected_revision": 1, "expected_world_revision": 2}})


BASE_TARGET_EXAMPLE = {"game_instance_id": TASK["game_instance_id"], "world_id": TASK["world_id"],
    "base_id": BASE_EXAMPLE["base_id"], "base_revision": BASE_EXAMPLE["revision"], "world_revision": 2,
    "position": BASE_EXAMPLE["position"], "radius": BASE_EXAMPLE["radius"], "source": "operator_observed",
    "registered_world_session_id": BASE_EXAMPLE["world_session_id"], "registered_seq": BASE_EXAMPLE["based_on_seq"]}
BASE_REF_EXAMPLE = {k: BASE_TARGET_EXAMPLE[k] for k in D["BaseRef"]["required"]}
HOME_REQUEST = {**TASK_REQUEST, "goal": {"skill": "return_base", "base_id": BASE_TARGET_EXAMPLE["base_id"]}, "base_ref": BASE_REF_EXAMPLE}
HOME_QUERY = {**WORLD_CONTEXT, "kind": "check_action", "params": {"goal": HOME_REQUEST["goal"], "base_ref": BASE_REF_EXAMPLE}}
EXAMPLES["cases"].extend([
    {"name": "base-ref", "definition": "BaseRef", "value": BASE_REF_EXAMPLE},
    {"name": "base-target", "definition": "BaseTarget", "value": BASE_TARGET_EXAMPLE},
    {"name": "return-base-request", "definition": "TaskCreate", "value": HOME_REQUEST},
    {"name": "return-base-task", "definition": "Task", "value": {**TASK, "goal": HOME_REQUEST["goal"], "base_target": BASE_TARGET_EXAMPLE}},
    {"name": "return-base-query", "definition": "QueryRequest", "value": HOME_QUERY},
    {"name": "return-base-wire-start", "definition": "BridgeEnvelope", "value": {**BRIDGE,
        "type": "task_start", "payload": {**wire_samples["task_start"], "request": HOME_REQUEST, "base_target": BASE_TARGET_EXAMPLE}}},
    {"name": "return-base-wire-query", "definition": "BridgeEnvelope", "value": {**BRIDGE,
        "type": "query", "payload": {"operation_id": "query-home-example", "request": HOME_QUERY, "base_target": BASE_TARGET_EXAMPLE}}}
])


def build():
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    if branch != "mc":
        raise SystemExit("MC documentation contracts must be rebuilt on mc")
    # This historical template must not erase later reviewed runtime contracts.
    current_schema = json.loads((BASE / 'game.schema.json').read_text(encoding='utf-8'))
    current_api = json.loads((BASE / 'openapi.json').read_text(encoding='utf-8'))
    current_examples = json.loads((BASE / 'examples.json').read_text(encoding='utf-8'))
    missing_definitions = set(current_schema['$defs']) - set(SCHEMA['$defs'])
    missing_paths = {(path, method) for path, methods in current_api['paths'].items() for method in methods} - {(path, method) for path, methods in OPENAPI['paths'].items() for method in methods}
    missing_examples = {case['name'] for case in current_examples['cases']} - {case['name'] for case in EXAMPLES['cases']}
    if missing_definitions or missing_paths or missing_examples:
        raise SystemExit('Historical contract template is incomplete; current reviewed JSON files were not changed. Align the complete template before rebuilding.')
    for name, value in (("game.schema.json", SCHEMA), ("openapi.json", OPENAPI), ("examples.json", EXAMPLES)):
        (BASE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"branch": branch, "definitions": len(D), "http_operations": sum(len(v) for v in paths.values()),
                      "ws_types": len(payloads), "examples": len(EXAMPLES["cases"]), "runtime_started": False}, ensure_ascii=False))


if __name__ == "__main__":
    build()
