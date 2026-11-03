import { canonical } from '../dsh-bridge/channel.mjs';
import { nativeHands } from './native-hands.mjs';

/** Bounded model context; the complete native observation stays available to the UI and executor. */
export function modelState(value, { inventory = false, worldLedger = true } = {}) {
  const state = structuredClone(value), omitted = [];
  if (!inventory) {
    state.inventory_summary = { item_types: state.inventory?.length ?? 0, query_tool: 'game_query_inventory' };
    delete state.inventory; omitted.push('inventory');
  }
  if (state.details) {
    const details = state.details;
    const hands=nativeHands(state);if(hands)details.held_items=hands;
    delete details.inventory_slots; omitted.push('details.inventory_slots');
    if (details.gui) {
      details.gui.slot_count = details.gui.slots?.length ?? 0;
      delete details.gui.slots; omitted.push('details.gui.slots');
    }
    if (details.nearby_hostiles?.length > 8) {
      details.nearby_hostiles = details.nearby_hostiles.slice(0, 8);
      details.hostiles_truncated = true; omitted.push('details.nearby_hostiles_tail');
    }
    // The exact tick advances while a line is generated. Give the model an
    // explicitly approximate range; narration can still reject a changed range.
    if (Number.isSafeInteger(details.environment?.day_time)) {
      const start = Math.floor(details.environment.day_time / 6000) * 6000;
      details.environment.day_time_range = { from: start, through: start + 5999, precision_ticks: 6000 };
      delete details.environment.day_time; omitted.push('details.environment.day_time');
    }
  }
  if (state.world_ledger && !worldLedger) {
    const ledger = state.world_ledger;
    state.world_ledger_summary = { active_base_id: ledger.active_base?.base_id ?? null,
      active_goal_ids: ledger.world_goals?.filter(row => row.status === 'active').slice(0, 3).map(row => row.goal_id) ?? [],
      world_goal_count: ledger.world_goals?.length ?? 0, task_recovery_count: ledger.task_recovery?.length ?? 0,
      query_tool: 'game_get_state' };
    delete state.world_ledger; omitted.push('world_ledger');
  }
  if (state.world_ledger) {
    const ledger = state.world_ledger;
    // These identifiers and live-observation fields already exist at the root.
    // Retain the ledger's decisions and history, without resending its full
    // database row after every read tool.
    for (const [key, fields] of [
      ['world', ['game_instance_id', 'world_id', 'first_seen', 'last_seen', 'last_world_session_id']],
      ['current_session', ['game_instance_id', 'world_id', 'world_session_id', 'bridge_boot_id', 'last_connection_generation']],
    ]) {
      if (!ledger[key]) continue;
      for (const field of fields) if (Object.hasOwn(ledger[key], field)) {
        delete ledger[key][field]; omitted.push('world_ledger.' + key + '.' + field);
      }
    }
    for (const key of ['task_recovery', 'world_goals']) {
      if (!Array.isArray(ledger[key]) || ledger[key].length <= 3) continue;
      ledger[key + '_total'] = ledger[key].length;
      const rows = key === 'world_goals'
        ? [...ledger[key].filter(row => row.status === 'active'), ...ledger[key].filter(row => row.status !== 'active')]
        : ledger[key];
      ledger[key] = rows.slice(0, 3); omitted.push('world_ledger.' + key + '_tail');
    }
  }
  if (state.audience) {
    state.audience_summary = { platform: state.audience.platform, room_id: state.audience.room_id,
      suggestions: state.audience.suggestions?.length ?? 0, votes: state.audience.votes?.length ?? 0,
      feedback: state.audience.feedback?.length ?? 0, query_tool: 'game_get_audience' };
    delete state.audience; omitted.push('audience');
  }
  state.model_projection = { kind: 'bounded_native_summary', omitted_fields: omitted,
    rule: '省略的槽位不是空槽或未知物品；完整原生状态仍由执行器核验。' +
      (inventory ? 'inventory已提供本次观测的聚合库存总量。' : '库存总量请调用game_query_inventory。') };
  return state;
}

// Planning needs the usable base/next step from its first call, not a second
// copy of ledger transport metadata after every state read. Keep historical
// scope and unresolved recovery facts; this projection never changes the DB.
export function planningState(value) {
  const state = modelState(value, { inventory: true });
  const pick = (row, keys) => row && Object.fromEntries(keys.filter(key => Object.hasOwn(row, key))
    .map(key => [key, row[key]]));
  if (state.world_ledger) {
    const ledger = state.world_ledger;
    for (const [key, fields] of [
      ['world', ['revision', 'rule_fingerprint']], ['current_session', ['status', 'source', 'close_reason']],
      ['active_base', ['base_id', 'revision', 'label', 'position', 'radius', 'archived', 'source', 'world_session_id', 'observed_at']],
      ['latest_checkpoint', ['checkpoint_id', 'created_at', 'world_session_id', 'seq']],
    ]) if (Object.hasOwn(ledger, key)) ledger[key] = pick(ledger[key], fields);
    if (Array.isArray(ledger.world_goals)) ledger.world_goals = ledger.world_goals.map(row => pick(row,
      ['goal_id', 'revision', 'title', 'status', 'completed_steps', 'total_steps', 'last_review_session_id', 'reason', 'next_step']));
    state.model_projection.omitted_fields.push('world_ledger.transport_metadata');
  }
  state.model_projection.kind = 'bounded_planning_summary';
  state.model_projection.rule += '基地与检查点保留历史会话来源；省略账本传输元数据，不能据历史完成推断当前效果。';
  return state;
}

// Compare the complete projected gameplay and ledger facts before shortening
// a repeated read. Never memoize a precondition, stale or changed observation.
export function planningStateRead(initial, current) {
  const projected = planningState(current);
  const signature = value => canonical(Object.fromEntries(Object.entries(value)
    .filter(([key]) => !['seq', 'observed_at', 'age_ms', 'view_revision', 'lease_remaining_ms'].includes(key))));
  if (projected.freshness !== 'fresh' || signature(initial) !== signature(projected)) return projected;
  const result = Object.fromEntries(['world_id', 'world_session_id', 'bridge_boot_id', 'connection_generation',
    'control_epoch', 'seq', 'observed_at', 'age_ms', 'freshness', 'mode', 'inputs_released',
    'automation_ready', 'active_task_id', 'player', 'unknown_fields'].filter(key => Object.hasOwn(current, key))
    .map(key => [key, structuredClone(current[key])]));
  result.model_projection = { kind: 'unchanged_planning_facts', unchanged_from: 'initial_game_context',
    omitted_fields: ['inventory', 'details', 'environment', 'world_ledger'],
    rule: '已核对新鲜原生观测，省略事实及账本与本轮初始game上下文一致，不表示空库存、无危险或无目标。动作仍须原生前置与后置核验。' };
  return result;
}

/** Speech describes observations; route meshes and task histories are read elsewhere. */
export function speechState(value) {
  const keep=['world_id','world_session_id','seq','observed_at','freshness','mode','screen','active_task_id','player','unknown_fields'];
  const state=Object.fromEntries(keep.filter(k=>Object.hasOwn(value,k)).map(k=>[k,structuredClone(value[k])]));
  const details=value.details||{};
  state.details={environment:structuredClone(details.environment||{}),
    nearby_hostiles:structuredClone((details.nearby_hostiles||[]).slice(0,3))};
  if(Number.isSafeInteger(state.details.environment.day_time)) {
    const start=Math.floor(state.details.environment.day_time/6000)*6000;
    state.details.environment.day_time_range={from:start,through:start+5999,precision_ticks:6000};
    delete state.details.environment.day_time;
  }
  state.inventory_summary={item_types:value.inventory?.length||0,query_tool:'game_query_inventory'};
  if(value.world_ledger) {
    const pick=(row,keys)=>row&&Object.fromEntries(keys.filter(k=>Object.hasOwn(row,k)).map(k=>[k,structuredClone(row[k])]));
    const ledger=value.world_ledger;
    state.world_ledger={
      active_base:pick(ledger.active_base,['base_id','label','position','radius','world_session_id','observed_at','archived']),
      latest_checkpoint:pick(ledger.latest_checkpoint,['checkpoint_id','world_session_id','created_at','seq']),
      task_recovery:(ledger.task_recovery||[]).slice(0,3).map(row=>pick(row,['task_id','status','world_session_id','world_id','reason','effect_status'])),
      task_recovery_total:ledger.task_recovery?.length||0,
    };
  }
  state.model_projection={kind:'speech_native_facts',omitted_fields:['inventory','route_geometry','workstations','world_ledger_transport_and_history','inventory_slots'],
    rule:'仅供口播的当前原生事实。省略不表示没有；库存另查，历史任务结果不能冒充当前库存。'};
  return state;
}
