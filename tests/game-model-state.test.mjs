import test from 'node:test';
import assert from 'node:assert/strict';
import { modelState, planningState, planningStateRead, planningEvents } from '../backend/game/model-state.mjs';
import { gameFixture } from './game-fixture.mjs';

test('recent events start with the latest world page and explicit cursors retain incremental order',async t=>{
 const f=await gameFixture();t.after(()=>f.close());const game=await f.connect();
 for(let i=0;i<30;i++){
  const value={event_id:'event-'+i,world_session_id:game.observation.world_session_id,seq:i,kind:'inventory_changed',data:{count:i}};
  f.manager.store.run('INSERT INTO game_events VALUES(?,?,?,?)',value.event_id,value.world_session_id,new Date().toISOString(),JSON.stringify(value));
 }
 f.manager.store.run('INSERT INTO game_events VALUES(?,?,?,?)','foreign-event','different-session',new Date().toISOString(),JSON.stringify({event_id:'foreign-event'}));
 const latest=await f.manager.tools.invoke('game_get_recent_events',{limit:3});
 assert.deepEqual(latest.items.map(x=>x.event_id),['event-27','event-28','event-29']);
 const first=await f.manager.tools.invoke('game_get_recent_events',{limit:3,cursor:'0'});
 assert.deepEqual(first.items.map(x=>x.event_id),['event-0','event-1','event-2']);
 const next=await f.manager.tools.invoke('game_get_recent_events',{limit:2,cursor:first.next_cursor});
 assert.deepEqual(next.items.map(x=>x.event_id),['event-3','event-4']);
 assert.deepEqual(latest.items.at(-1).data,{count:29});
});

test('large historical event bodies cannot consume planning context or hide an older critical event',()=>{
 const page={items:Array.from({length:50},(_,i)=>({event_id:'e-'+i,delivery_seq:i,world_session_id:'current',seq:i,
  occurred_at:'2026-11-03T07:28:00Z',kind:i===3?'player_damaged':'inventory_changed',severity:i===3?'critical':'normal',task_id:null,
  data:{inventory:Array.from({length:41},()=>({item_id:'minecraft:cobblestone',count:64,components:'opaque'.repeat(1000)}))}})),next_cursor:'50'};
 const before=structuredClone(page),result=planningEvents(page);
 assert.equal(result.items.length,8);assert.equal(result.items[0].event_id,'e-3');assert.equal(result.items.at(-1).event_id,'e-49');
 assert.equal(result.items[0].severity,'critical');assert.equal(result.items[0].kind,'player_damaged');
 assert.equal(result.model_projection.omitted_events,42);assert.deepEqual(result.model_projection.omitted_fields,['items.data']);
 assert.equal(result.model_projection.historical_not_current,true);assert.equal(result.next_cursor,'50');
 assert(JSON.stringify(result).length<3000);assert.deepEqual(page,before);
 const empty=planningEvents({items:[],next_cursor:null});assert.equal(empty.items.length,0);assert.equal(empty.next_cursor,null);
});

test('a full container cannot consume the speech context or erase native facts', () => {
  const source = { bridge_boot_id: 'current-boot', world_session_id: 'current-world', seq: 91,
    observed_at: '2026-11-01T08:00:00Z', freshness: 'fresh', mode: 'PAUSED', inputs_released: true,
    inventory: [{ item_id: 'minecraft:stone', count: 32 }], unknown_fields: ['unreceived_server_rules'],
    details: { inventory_slots: Array.from({ length: 41 }, (_, slot) => ({ slot, item_id: 'minecraft:air', count: 0 })),
      cursor: { slot: -1, item_id: 'minecraft:diamond', count: 1 },
      gui: { kind: 'container', title: 'Actual container', container_id: 14, truncated: true,
        slots: Array.from({ length: 256 }, (_, slot) => ({ slot, item_id: 'minecraft:stone', count: 64 })) },
      hazards: { in_lava: false, on_fire: true }, unknown_fields: ['unopened_container_contents'] } };
  const original = structuredClone(source), summary = modelState(source);
  assert(JSON.stringify(source).length > 12000);
  assert(JSON.stringify(summary).length < 2200);
  for (const key of ['bridge_boot_id', 'world_session_id', 'seq', 'observed_at', 'freshness', 'mode', 'inputs_released', 'unknown_fields'])
    assert.deepEqual(summary[key], source[key]);
  assert.deepEqual(summary.details.cursor, source.details.cursor);
  assert.deepEqual(summary.details.hazards, source.details.hazards);
  assert.equal(summary.details.gui.slot_count, 256);
  assert.equal(summary.details.gui.truncated, true);
  assert.equal(summary.details.gui.slots, undefined);
  assert.equal(summary.inventory, undefined);
  assert(summary.model_projection.omitted_fields.includes('details.gui.slots'));
  assert.deepEqual(source, original, 'context projection cannot mutate the authoritative observation');
  assert.deepEqual(modelState(source, { inventory: true }).inventory, source.inventory);
});

test('bounded context retains active goals and marks omitted threats and recovery rows', () => {
  const source = { inventory: [], details: { nearby_hostiles: Array.from({ length: 32 }, (_, entity_id) => ({ entity_id })), hostiles_truncated: false },
    world_ledger: { task_recovery: Array.from({ length: 100 }, (_, task_id) => ({ task_id, status: 'required' })),
      world_goals: Array.from({ length: 12 }, (_, goal_id) => ({ goal_id, status: goal_id === 11 ? 'active' : 'paused' })) } };
  const result = modelState(source);
  assert.equal(result.details.nearby_hostiles.length, 8);
  assert.equal(result.details.hostiles_truncated, true);
  assert.equal(result.world_ledger.task_recovery_total, 100);
  assert.equal(result.world_ledger.task_recovery.length, 3);
  assert.equal(result.world_ledger.world_goals_total, 12);
  assert.equal(result.world_ledger.world_goals[0].goal_id, 11);
  assert(result.model_projection.omitted_fields.includes('world_ledger.world_goals_tail'));
  assert.equal(source.details.nearby_hostiles.length, 32);
});

test('the actual game tools use bounded facts while inventory reads and action permissions stay authoritative', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect();
  const state = await f.manager.tools.invoke('game_get_state', {});
  assert.equal(state.world_session_id, game.observation.world_session_id);
  assert.equal(state.freshness, 'fresh');
  assert.equal(state.inventory, undefined);
  assert.equal(state.inventory_summary.query_tool, 'game_query_inventory');
  assert.deepEqual((await f.manager.tools.invoke('game_query_inventory', {})).inventory, f.manager.stateView().inventory);
  assert.equal(state.model_projection.kind, 'bounded_native_summary');
  assert.equal(f.manager.stateView().model_projection, undefined);
  await assert.rejects(f.manager.tools.invoke('game_start_task', { goal: game.request().goal }, { purpose: 'speech' }), e => e.code === 'GAME_TOOL_PERMISSION');
});

test('repeated state and inventory reads omit duplicated ledger rows and audience configuration', () => {
  const source = { world_id: 'world-current', world_session_id: 'session-current', bridge_boot_id: 'boot-current',
    game_instance_id: 'game-current', seq: 90, freshness: 'fresh',
    inventory: Array.from({ length: 32 }, (_, index) => ({ item_id: 'minecraft:item_' + index, count: index + 1 })),
    world_ledger: { world: { world_id: 'world-current', game_instance_id: 'game-current', revision: 4,
      active_base_id: 'base-current', local_label: '观众共建基地', first_seen: 'old', last_seen: 'now', last_world_session_id: 'old-session' },
      current_session: { world_id: 'world-current', game_instance_id: 'game-current', world_session_id: 'session-current',
        bridge_boot_id: 'boot-current', last_connection_generation: 3, status: 'observed', close_reason: null, connection_count: 3 },
      world_goals: [], task_recovery: [] },
    audience: { platform: 'bilibili', room_id: '595139', suggestions: [], votes: [], feedback: [],
      command_hint: '只通过专用工具读取的提示'.repeat(600), support_budget: { tracked_events: 0 } } };
  const original = structuredClone(source), state = modelState(source);
  assert.equal(state.world_id, source.world_id);
  assert.deepEqual(state.world_ledger.world, { revision: 4, active_base_id: 'base-current', local_label: '观众共建基地' });
  assert.deepEqual(state.world_ledger.current_session, { status: 'observed', close_reason: null, connection_count: 3 });
  assert.equal(state.audience, undefined);
  assert.deepEqual(state.audience_summary, { platform: 'bilibili', room_id: '595139', suggestions: 0, votes: 0, feedback: 0,
    query_tool: 'game_get_audience' });
  assert(state.model_projection.omitted_fields.includes('audience'));
  assert(state.model_projection.omitted_fields.includes('world_ledger.current_session.bridge_boot_id'));
  assert(JSON.stringify([state, state, { inventory: source.inventory }]).length < 6000,
    'a second state read plus the complete aggregate inventory must leave space for persona and memory');
  assert.deepEqual(source, original);
});

test('enabling vision starts pin verification before the first frame without running inference', async t => {
  let preparations = 0, inferences = 0;
  const f = await gameFixture({ visionProvider: { available() { preparations++; return false; }, analyze() { inferences++; } } });
  t.after(() => f.close());
  f.manager.configure({ expected_revision: 0, patch: { vision: { enabled: true } } });
  assert.equal(preparations, 1); assert.equal(inferences, 0);
  assert.equal(f.manager.pending.size, 0); assert.equal(f.manager.tasks.active(), null);
  f.manager.start(); assert.equal(preparations, 2); assert.equal(inferences, 0);
});

test('initial speech context points to the full ledger tool and marks approximate native time', () => {
  const value = { details: { environment: { day_time: 4681414, raining: true } },
    world_ledger: { world: { revision: 2 }, active_base: { base_id: 'base-actual' },
      world_goals: [{ goal_id: 'goal-old', status: 'completed' }, { goal_id: 'goal-current', status: 'active' }], task_recovery: [{ task_id: 'task-review' }] } };
  const initial = modelState(value, { worldLedger: false }), queried = modelState(value);
  assert.equal(initial.world_ledger, undefined);
  assert.deepEqual(initial.world_ledger_summary, { active_base_id: 'base-actual', active_goal_ids: ['goal-current'],
    world_goal_count: 2, task_recovery_count: 1, query_tool: 'game_get_state' });
  assert(initial.model_projection.omitted_fields.includes('world_ledger'));
  assert.deepEqual(queried.world_ledger.world, { revision: 2 });
  assert.equal(queried.details.environment.raining, true);
  assert.equal(queried.details.environment.day_time, undefined);
  assert.deepEqual(queried.details.environment.day_time_range, { from: 4680000, through: 4685999, precision_ticks: 6000 });
  assert(queried.model_projection.omitted_fields.includes('details.environment.day_time'));
  assert.equal(value.details.environment.day_time, 4681414);
});

test('planning provides base provenance initially and shortens only an unchanged current ledger', () => {
  const original = { world_id: 'world-actual', world_session_id: 'session-actual', bridge_boot_id: 'boot-actual',
    control_epoch: 3, mode: 'AUTO', freshness: 'fresh', seq: 10, observed_at: 'old', age_ms: 100,
    view_revision: 4, lease_remaining_ms: 2500, inputs_released: true, player: { health: 20, food: 20 },
    inventory: [{ item_id: 'minecraft:coal', count: 2 }],
    details: { hazards: { in_lava: false }, environment: { day_time: 12010 } },
    world_ledger: { active_base: { base_id: 'base-actual', position: { x: 1, y: 70, z: 3 } },
      world_goals: [], task_recovery: [], current_session: { last_seq: 10 } } };
  const initial = planningState(original);
  assert.match(initial.model_projection.rule, /inventory已提供/);
  assert.deepEqual(initial.world_ledger.active_base, original.world_ledger.active_base);
  const current = structuredClone(original);
  Object.assign(current, { seq: 11, observed_at: 'now', age_ms: 40, view_revision: 5, lease_remaining_ms: 2300 });
  current.details.environment.day_time = 12020;
  current.world_ledger.current_session.last_seq = 11;
  const before = structuredClone(current), result = planningStateRead(initial, current);
  assert.equal(result.model_projection.kind, 'unchanged_planning_facts');
  assert.equal(result.model_projection.unchanged_from, 'initial_game_context');
  assert.equal(result.seq, 11); assert.equal(result.observed_at, 'now');
  assert.equal(result.world_ledger, undefined);
  assert(result.model_projection.omitted_fields.includes('world_ledger'));
  assert.equal(result.inventory, undefined); assert.equal(result.details, undefined);
  assert.deepEqual(current, before); assert.equal(original.seq, 10);
});

test('planning reads never shorten changed inventory, hazards, health, scope, time range or freshness', () => {
  const source = { freshness: 'fresh', world_session_id: 'session-a', control_epoch: 1,
    player: { health: 20, position: { x: 1 } }, inventory: [{ item_id: 'minecraft:coal', count: 2 }],
    unknown_fields: [], details: { hazards: { in_lava: false }, environment: { day_time: 12010 } } };
  const initial = planningState(source);
  for (const change of [s => s.inventory[0].count++, s => s.player.health--, s => s.player.position.x++,
    s => s.details.hazards.in_lava = true, s => s.world_session_id = 'session-b', s => s.control_epoch++,
    s => s.details.environment.day_time = 18000, s => s.freshness = 'stale', s => s.unknown_fields.push('new_unknown')]) {
    const current = structuredClone(source); change(current);
    assert.equal(planningStateRead(initial, current).model_projection.kind, 'bounded_planning_summary');
  }
});

test('changed bases, approved next steps and unresolved recovery cannot hide behind an unchanged gameplay read', () => {
  const source = { freshness: 'fresh', world_session_id: 'session-a', inventory: [],
    world_ledger: { active_base: { base_id: 'base-a', revision: 1, source: 'operator_observed', world_session_id: 'old-session',
      observed_at: '2026-10-31T00:00:00Z', position: { dimension: 'minecraft:overworld', x: 1, y: 70, z: 2 } },
      latest_checkpoint: { checkpoint_id: 'checkpoint-a', world_session_id: 'old-session', seq: 20 },
      world_goals: [{ goal_id: 'goal-a', revision: 1, status: 'active', next_step: { step_id: 'step-a', state: 'pending',
        goal: { skill: 'gather', item_id: 'minecraft:cobblestone', count: 1 } } }], task_recovery: [] } };
  const initial = planningState(source);
  assert.equal(initial.world_ledger.active_base.world_session_id, 'old-session');
  for (const change of [s => s.world_ledger.active_base.revision++, s => s.world_ledger.active_base.position.x++,
    s => s.world_ledger.world_goals[0].next_step.state = 'awaiting_observation',
    s => s.world_ledger.world_goals[0].status = 'needs_review',
    s => s.world_ledger.task_recovery.push({ task_id: 'task-a', status: 'required', reason: 'INTERRUPTED_HOST_RESTART' })]) {
    const current = structuredClone(source); change(current);
    const result = planningStateRead(initial, current);
    assert.equal(result.model_projection.kind, 'bounded_planning_summary');
    assert.deepEqual(result.world_ledger, planningState(current).world_ledger);
  }
  assert.equal(source.world_ledger.task_recovery.length, 0);
});
