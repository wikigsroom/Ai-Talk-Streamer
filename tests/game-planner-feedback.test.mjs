// WebSocket peers and the model here are protocol fixtures, not Minecraft or inference.
import test from 'node:test';
import assert from 'node:assert/strict';
import { gameFixture, until } from './game-fixture.mjs';

const goal = { skill: 'gather', item_id: 'minecraft:oak_log', count: 2 };
const swimmingDetails = () => ({source:'runtime_client',selected_hotbar:0,inventory_slots:[],
  cursor:{slot:-1,item_id:'minecraft:air',count:0,damage:null,max_damage:null},
  gui:{kind:'gameplay',title:null,container_id:null,slots:[],truncated:false},
  hazards:{on_fire:false,in_water:true,in_lava:false,fall_distance:0,on_ground:false},
  environment:{biome:'minecraft:plains',day_time:1,raining:false,thundering:false},
  received_rules:{difficulty:'normal',game_mode:'survival',world_border_size:1000},
  nearby_hostiles:[],hostiles_truncated:false,unknown_fields:[]});
async function setup(t) {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close());
  const game = await f.connect(); await game.auto();
  const contexts = []; let action = null, delivery = 0;
  f.bridge.health = () => ({ persona_injection_ready: true }); f.bridge.channel = { snapshot: () => ({}) };
  f.bridge.host = { generate: async value => {
    contexts.push(JSON.parse(value.context)); if (action) await action(value);
    return { session_id: 'PLANNER_PROTOCOL_FIXTURE' };
  } };
  f.manager.config.planner.enabled = true;
  async function observe(patch = {}, elapsed = 3000) {
    f.advance(elapsed); game.snapshot({ seq: game.observation.seq + 1,
      observed_at: new Date(f.manager.wall()).toISOString(), ...patch });
    await until(() => f.manager.state.value.seq === game.observation.seq);
  }
  async function check(checked = goal, allowed = false) {
    const previous = new Set(game.messages.filter(row => row.type === 'query').map(row => row.payload.operation_id));
    action = value => value.tools('game_check_action', { goal: checked });
    const pending = f.manager.planner.tick(); t.after(async () => { f.manager.planner.cancel(); await pending; });
    const query = await game.next('query', row => !previous.has(row.payload.operation_id));
    game.send('query_result', { ...f.manager.operation(query.payload.operation_id), state: 'succeeded',
      result: { world_session_id: game.observation.world_session_id, kind: 'check_action', allowed,
        reason: allowed ? null : 'GAME_NAVIGATION_NO_ROUTE' } });
    await pending; action = null; return query.payload.operation_id;
  }
  async function complete(nextGoal, state = 'failed', effect = 'unknown') {
    const task = (await f.api('/tasks', game.request(nextGoal, 'feedback-' + (++delivery)))).value;
    assert.ok(task.task_id);
    await game.next('task_start', message => message.payload.task_id === task.task_id);
    game.send('task_update', { delivery_seq: delivery, transition_seq: 2, task: { ...task, version: 2, state,
      effect_status: effect, reason: state === 'failed' ? 'GAME_NAVIGATION_NO_ROUTE' : null,
      evidence: effect === 'verified' ? [{world_session_id:task.world_session_id,seq:game.observation.seq,
        kind:nextGoal.skill==='navigate'?'position':'inventory',summary:'Protocol fixture only: confirmed native effect'}] : [],
      updated_at: new Date(f.manager.wall()).toISOString() } });
    await until(() => f.manager.tasks.get(task.task_id).state === state);
    await observe(); return task.task_id;
  }
  return { f, game, contexts, observe, check, complete };
}

test('independent planning receives bounded native results and retains a failure among successful short moves', async t => {
  const { f, game, contexts, complete } = await setup(t);
  const route = { skill:'navigate', target:{...game.observation.player.position,x:10}, radius:0 };
  const failed = await complete(route);
  const productive = await complete(goal, 'succeeded', 'verified');
  await complete(route, 'succeeded', 'verified');
  const latest = await complete({...route,target:{...route.target,x:12}}, 'succeeded', 'verified');
  await f.manager.planner.tick();
  const facts = contexts.at(-1).recent_task_results;
  assert.equal(facts.length,3);
  assert.deepEqual(new Set(facts.map(row=>row.task_id)),new Set([failed,productive,latest]));
  assert.equal(facts.find(row=>row.task_id===failed).effect_status,'unknown');
  assert.equal(facts.find(row=>row.task_id===failed).reason,'GAME_NAVIGATION_NO_ROUTE');
  assert.equal(facts.find(row=>row.task_id===productive).effect_status,'verified');
  assert.ok(facts.every(row=>row.source==='native_task_transition'&&row.history_only&&row.age_ms>=0));
  assert.equal(game.messages.filter(row=>row.type==='task_start').length,4,'feedback adds no action or replay');
});

test('planning results exclude unconfirmed host projections, conflicting recovery and expired results', async t => {
  const { f, game, contexts, complete, observe } = await setup(t);
  const accepted = (await f.api('/tasks',game.request(goal,'unconfirmed-projection'))).value;
  const projection={...accepted,state:'succeeded',effect_status:'verified',version:2};
  f.manager.store.put('task',projection);
  await f.manager.planner.tick();
  assert.equal(contexts.at(-1).recent_task_results,undefined);
  f.manager.store.put('task',accepted);
  // Restore this fixture's unexecuted task before sending the native result.
  game.send('task_update',{delivery_seq:1,transition_seq:2,task:{...accepted,state:'failed',version:2,reason:'GAME_NAVIGATION_NO_ROUTE'}});
  await until(()=>f.manager.tasks.get(accepted.task_id).state==='failed');
  f.manager.tasks.setRecovery(accepted.task_id,'conflict','GAME_LEDGER_CONFLICT');
  await observe();await f.manager.planner.tick();
  assert.equal(contexts.at(-1).recent_task_results,undefined);
  await observe({},300000);await f.manager.planner.tick();
  assert.deepEqual(f.manager.tasks.planningOutcomes(f.manager.stateView()),[]);
  assert.equal(contexts.at(-1).recent_task_results,undefined);
});

test('executed task history never crosses a world, bridge or control boundary and expires after five minutes', async t => {
  const { f, contexts, complete, observe } = await setup(t);
  await complete(goal,'cancelled','partial');
  const state=f.manager.stateView();
  assert.equal(f.manager.tasks.planningOutcomes(state)[0].effect_status,'partial');
  for(const patch of [{freshness:'stale'},{world_id:'another-world'},{world_session_id:'another-session'},
    {bridge_boot_id:'another-boot'},{game_instance_id:'another-instance'},{control_epoch:state.control_epoch+1}]) {
    assert.deepEqual(f.manager.tasks.planningOutcomes({...state,...patch}),[]);
  }
  await observe({},300000);await f.manager.planner.tick();
  assert.equal(contexts.at(-1).recent_task_results,undefined);
});

test('a later independent planning session sees an actual denied check, without inventing an action or permanent ban', async t => {
  const { f, contexts, observe, check } = await setup(t);
  const id = await check(); assert.equal(contexts[0].recent_action_checks, undefined);
  await observe(); await f.manager.planner.tick();
  const facts = contexts.at(-1).recent_action_checks;
  assert.equal(facts.length, 1); assert.deepEqual(facts[0].goal, goal);
  assert.equal(facts[0].operation_id, id); assert.equal(facts[0].reason, 'GAME_NAVIGATION_NO_ROUTE');
  assert.equal(facts[0].allowed, false); assert.equal(facts[0].age_ms, 3000);
  assert.equal(f.manager.tasks.active(), null); assert.equal(f.manager.state.value.mode, 'AUTO');
  await observe(); await check({ ...goal, count: 1 });
  await observe(); await f.manager.planner.tick();
  assert.equal(contexts.at(-1).recent_action_checks.length, 1, 'changing gather quantity cannot masquerade as a new route');
  assert.equal(contexts.at(-1).recent_action_checks[0].goal.count, 1);
});

test('position, inventory, control scope and age invalidate previous planning denials; allowed checks are not failures', async t => {
  const { f, game, contexts, observe, check } = await setup(t);
  await check();
  await observe({ player: { ...game.observation.player, position: { ...game.observation.player.position, x: 10 } } });
  await f.manager.planner.tick(); assert.equal(contexts.at(-1).recent_action_checks, undefined);
  await observe(); await check();
  await observe({ inventory: [{ item_id: 'minecraft:coal', count: 1 }] });
  await f.manager.planner.tick(); assert.equal(contexts.at(-1).recent_action_checks, undefined);
  await observe(); await check();
  await observe({ control_epoch: game.observation.control_epoch + 1 });
  await f.manager.planner.tick(); assert.equal(contexts.at(-1).recent_action_checks, undefined);
  await observe(); await check(); await observe({}, 120000);
  await f.manager.planner.tick(); assert.equal(contexts.at(-1).recent_action_checks, undefined);
  await observe(); await check(goal, true); await observe(); await f.manager.planner.tick();
  assert.equal(contexts.at(-1).recent_action_checks, undefined);
});

test('fresh idle threats bypass ordinary model cooldown and use checked Mindcraft retreat with bounded retries', async t => {
  const { f, game, contexts, observe } = await setup(t);
  f.manager.config.planner.engine = 'mindcraft_native';
  const planner = f.manager.planner;
  let retreats = 0;
  planner.mindcraft.retreat = async () => { retreats++; return false; };
  await observe({ details: { source:'runtime_client', selected_hotbar:0, inventory_slots:[],
    cursor:{slot:-1,item_id:'minecraft:air',count:0,damage:null,max_damage:null},
    gui:{kind:'gameplay',title:null,container_id:null,slots:[],truncated:false},
    hazards:{on_fire:false,in_water:false,in_lava:false,fall_distance:0,on_ground:true},
    environment:{biome:'minecraft:plains',day_time:1,raining:false,thundering:false},
    received_rules:{difficulty:'normal',game_mode:'survival',world_border_size:1000},
    nearby_hostiles:[{entity_id:7,type:'minecraft:zombie',health:20,visible:true,distance:2,
      position:{dimension:'minecraft:overworld',x:2,y:64,z:0}}],hostiles_truncated:false,unknown_fields:[] } });
  planner.lastCall = f.manager.clock();
  await planner.tick();
  assert.equal(retreats, 1);
  assert.equal(contexts.length, 0, 'a blocked escape does not spend a long model call while the player is being hit');
  await planner.tick(); assert.equal(retreats, 1, 'emergency retries remain bounded');
  await observe({}, 500); await planner.tick(); assert.equal(retreats, 2);
  assert.equal(f.manager.tasks.active(), null, 'this scheduler test never bypasses native admission');
});

test('a fresh threat cancels active production once and waits for the native terminal instead of overlapping escape', async t => {
  const { f, game, contexts, observe } = await setup(t);
  f.manager.config.planner.engine = 'mindcraft_native';
  const task = (await f.api('/tasks', game.request(goal, 'production-before-threat'))).value;
  await game.next('task_start');
  await observe({ active_task_id:task.task_id, details:swimmingDetails() });
  await f.manager.planner.tick();
  const cancel = await game.next('task_cancel');
  assert.equal(cancel.payload.task_id,task.task_id);
  assert.equal(cancel.payload.reason,'AGENT_EMERGENCY_THREAT');
  await f.manager.planner.tick();
  assert.equal(game.messages.filter(row=>row.type==='task_cancel').length,1);
  assert.equal(game.messages.filter(row=>row.type==='task_start').length,1);
  assert.equal(f.manager.tasks.active().task_id,task.task_id,'cancel request is not terminal/release confirmation');
  assert.equal(contexts.length,0);
});

test('threat cancellation preserves an existing checked escape and eating', async t => {
  for (const eating of [false,true]) {
    const { f, game, observe } = await setup(t);
    f.manager.config.planner.engine = 'mindcraft_native';
    const next = eating ? {skill:'use_item',item_id:'minecraft:bread',purpose:'eat'}
      : {skill:'navigate',target:{...game.observation.player.position,x:4},radius:0};
    const task = (await f.api('/tasks',game.request(next,'protect-survival-task'))).value;
    await game.next('task_start');
    if (!eating) f.manager.planner.mindcraft.pending={task_id:task.task_id,emergencyRetreat:true,goal:next};
    await observe({active_task_id:task.task_id,details:swimmingDetails()});
    await f.manager.planner.tick();
    assert.equal(game.messages.filter(row=>row.type==='task_cancel').length,0);
  }
});

test('paused or stale state cannot issue a threat cancellation', async t => {
  const { f, game } = await setup(t);
  f.manager.config.planner.engine = 'mindcraft_native';
  const task=(await f.api('/tasks',game.request(goal,'production-remains-owned'))).value;
  await game.next('task_start');
  const state=f.manager.stateView();
  const threatened={...state,active_task_id:task.task_id,details:{hazards:{in_water:true}}};
  f.manager.planner.interruptForThreat({...threatened,mode:'PAUSED'});
  f.manager.planner.interruptForThreat({...threatened,freshness:'stale'});
  assert.equal(game.messages.filter(row=>row.type==='task_cancel').length,0);
});
