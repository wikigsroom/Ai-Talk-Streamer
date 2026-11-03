// Real HTTP/WS, SQLite, game planner, tools, Room and speech lifecycle.
// MC, model output and PCM are explicit fixtures, never runtime acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import { gameFixture, until } from './game-fixture.mjs';
import { narrationFixture } from './game-narration-fixture.mjs';

const logs = { step_id: 'logs', label: '采集木材', goal: { skill: 'gather', item_id: 'minecraft:oak_log', count: 4 },
  condition: { kind: 'inventory_at_least', item_id: 'minecraft:oak_log', count: 4 } };
const planks = { step_id: 'planks', label: '合成木板', goal: { skill: 'craft', item_id: 'minecraft:oak_planks', count: 4 },
  condition: { kind: 'inventory_at_least', item_id: 'minecraft:oak_planks', count: 4 } };
const context = (f, request_id) => ({ request_id, bridge_boot_id: f.manager.state.value.bridge_boot_id,
  world_session_id: f.manager.state.value.world_session_id });

async function approve(f, steps = [logs, planks]) {
  const world = f.manager.state.value.world_id;
  const created = await f.api('/worlds/' + world + '/goals', { ...context(f, 'objective-create'),
    expected_world_revision: f.manager.worlds.get(world).revision, title: '本次直播生存目标', description: '', steps });
  assert.equal(created.status, 201, JSON.stringify(created));
  const result = await f.api('/world-goals/' + created.value.goal_id + '/decision', { ...context(f, 'objective-approve'),
    expected_revision: created.value.revision, action: 'activate', reason: '操作者核对本世界任务步骤' });
  assert.equal(result.status, 200, JSON.stringify(result)); return result.value;
}
async function setup(t, { auto = true } = {}) {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close());
  const game = await f.connect(); f.game = game;
  const goal = await approve(f); let modelCalls = 0;
  f.bridge.health = () => ({ persona_injection_ready: true });
  f.bridge.host = { generate: async () => { modelCalls++; return { session_id: 'fixture-fallback' }; } };
  f.bridge.channel = { snapshot: () => ({}) }; f.manager.config.planner.enabled = true;
  const events = []; f.manager.on('planner', value => events.push(value));
  if (auto) await game.auto();
  return { f, game, goal, events, modelCalls: () => modelCalls };
}
function reply(f, game, query, { allowed = true, reason = null } = {}) {
  game.send('query_result', { ...f.manager.operation(query.payload.operation_id), state: 'succeeded',
    result: { world_session_id: game.observation.world_session_id, kind: 'check_action', allowed, reason } });
}
async function entering(t, f, game) {
  const previous = new Set(game.messages.filter(message => message.type === 'query').map(message => message.message_id));
  const pending = f.manager.planner.tick(); t.after(async () => { f.manager.planner.cancel(); await pending; });
  const query = await game.next('query', message => !previous.has(message.message_id));
  return { pending, query };
}
async function dispatch(t, f, game) {
  const { pending, query } = await entering(t, f, game); reply(f, game, query); await pending;
  const task = f.manager.tasks.active(); assert(task); await game.next('task_start', message => message.payload.task_id === task.task_id);
  return task;
}
async function observe(f, game, patch = {}, elapsed = 0) {
  f.advance(elapsed); game.snapshot({ seq: game.observation.seq + 1, ...patch });
  await until(() => f.manager.state.value.seq === game.observation.seq);
}
async function terminal(f, game, task, { success = true, effect = success ? 'verified' : 'unknown' } = {}) {
  const delivery = (f.objectiveDelivery || 0) + 1;
  game.send('task_update', { delivery_seq: delivery, transition_seq: 2, task: { ...task, version: 2, state: 'running' } });
  await until(() => f.manager.tasks.raw(task.task_id).version === 2);
  game.send('task_update', { delivery_seq: delivery + 1, transition_seq: 3, task: { ...task, version: 3,
    state: success ? 'succeeded' : 'failed', effect_status: effect, reason: success ? null : 'FIXTURE_EXECUTOR_FAILED',
    evidence: success ? [{ world_session_id: task.world_session_id, seq: game.observation.seq + 1, kind: 'inventory', summary: 'FIXTURE_ONLY' }] : [] } });
  f.objectiveDelivery = delivery + 1; await until(() => f.manager.tasks.raw(task.task_id).version === 3);
}

test('approved gameplay dispatches the exact next step after a real peer precondition query without a new model call', async t => {
  const { f, game, goal, modelCalls } = await setup(t);
  const { pending, query } = await entering(t, f, game);
  assert.deepEqual(query.payload.request.params.goal, logs.goal);
  assert.equal(game.messages.filter(message => message.type === 'task_start').length, 0);
  reply(f, game, query); await pending;
  const sent = await game.next('task_start');
  assert.deepEqual(sent.payload.request.goal, logs.goal);
  assert.deepEqual(sent.payload.request.world_goal_ref, { goal_id: goal.goal_id, step_id: 'logs', expected_revision: goal.revision });
  assert.equal(f.manager.continuity.goal(goal.goal_id).steps[0].state, 'running');
  assert.equal(modelCalls(), 0);
});

test('running and awaiting-observation steps never dispatch a duplicate or fall back to model planning', async t => {
  const { f, game, goal, modelCalls } = await setup(t); const task = await dispatch(t, f, game);
  await f.manager.planner.tick(); await terminal(f, game, task);
  await observe(f, game, { unknown_fields: ['inventory'] }, 3000);
  assert.equal(f.manager.continuity.goal(goal.goal_id).steps[0].state, 'awaiting_observation');
  await f.manager.planner.tick();
  assert.equal(game.messages.filter(message => message.type === 'task_start').length, 1); assert.equal(modelCalls(), 0);
});

test('verified execution plus later known inventory advances to the next approved skill and completes both steps', async t => {
  const { f, game, goal, modelCalls } = await setup(t); const first = await dispatch(t, f, game);
  await terminal(f, game, first);
  assert.equal(f.manager.continuity.goal(goal.goal_id).steps[0].state, 'awaiting_observation');
  await observe(f, game, { inventory: [{ item_id: 'minecraft:oak_log', count: 4 }], unknown_fields: [] }, 3000);
  const second = await dispatch(t, f, game); assert.deepEqual(second.goal, planks.goal);
  const link = f.manager.store.get('SELECT goal_id,step_id FROM world_goal_tasks WHERE task_id=?', second.task_id);
  assert.equal(link.goal_id, goal.goal_id); assert.equal(link.step_id, 'planks');
  await terminal(f, game, second);
  await observe(f, game, { inventory: [{ item_id: 'minecraft:oak_planks', count: 4 }] });
  const completed = f.manager.continuity.goal(goal.goal_id);
  assert.equal(completed.status, 'completed');
  assert.deepEqual(completed.steps.map(step => step.proof.task_id), [first.task_id, second.task_id]);
  assert.equal(modelCalls(), 0);
});

test('approval alone cannot grant AUTO or start gameplay', async t => {
  const { f, game, modelCalls } = await setup(t, { auto: false }); await f.manager.planner.tick();
  assert.equal(f.manager.state.value.mode, 'PAUSED'); assert.equal(f.manager.lease, null);
  assert.equal(game.messages.filter(message => ['query', 'task_start'].includes(message.type)).length, 0); assert.equal(modelCalls(), 0);
});

test('disabled planning, unavailable persona and stale facts each prevent approved execution', async t => {
  const { f, game } = await setup(t);
  f.manager.config.planner.enabled = false; await f.manager.planner.tick();
  f.manager.config.planner.enabled = true; f.bridge.health = () => ({ persona_injection_ready: false }); await f.manager.planner.tick();
  f.bridge.health = () => ({ persona_injection_ready: true }); f.advance(3000); await f.manager.planner.tick();
  assert.equal(game.messages.filter(message => ['query', 'task_start'].includes(message.type)).length, 0);
});

test('a failed game precondition leaves the step pending and never sends an action', async t => {
  const { f, game, goal, events } = await setup(t); const { pending, query } = await entering(t, f, game);
  reply(f, game, query, { allowed: false, reason: 'GAME_RESOURCE_NOT_CATALOGUED' }); await pending;
  assert.equal(events.at(-1).error, 'GAME_PRECONDITION_FAILED');
  assert.equal(f.manager.continuity.goal(goal.goal_id).steps[0].state, 'pending');
  assert.equal(game.messages.filter(message => message.type === 'task_start').length, 0);
  await f.manager.planner.tick(); assert.equal(game.messages.filter(message => message.type === 'query').length, 1);
});

test('an objective completed by fresh observation during precondition checking cannot become an unlinked extra action', async t => {
  const { f, game, goal, events } = await setup(t); const { pending, query } = await entering(t, f, game);
  await observe(f, game, { inventory: [{ item_id: 'minecraft:oak_log', count: 4 }] });
  reply(f, game, query); await pending;
  assert.equal(f.manager.continuity.goal(goal.goal_id).steps[0].state, 'completed');
  assert.equal(events.at(-1).error, 'GAME_WORLD_GOAL_CONFLICT');
  assert.equal(f.manager.tasks.active(), null); assert.equal(game.messages.filter(message => message.type === 'task_start').length, 0);
});

test('an approval revision change during precondition checking rejects the original step', async t => {
  const { f, game, goal, events } = await setup(t); const { pending, query } = await entering(t, f, game);
  // Synchronous competing transaction represents a committed authority revision.
  const revised = f.manager.continuity.goal(goal.goal_id); revised.revision++; f.manager.continuity.putGoal(revised);
  reply(f, game, query); await pending;
  assert.equal(events.at(-1).error, 'GAME_WORLD_GOAL_CONFLICT'); assert.equal(f.manager.tasks.active(), null);
});

test('manual takeover cancels a pending step and discards the late positive check', async t => {
  const { f, game } = await setup(t); const { pending, query } = await entering(t, f, game);
  await observe(f, game, { mode: 'MANUAL_COMMENTARY', control_epoch: game.observation.control_epoch + 1,
    automation_ready: false, inputs_released: true, lease_remaining_ms: null });
  await pending; reply(f, game, query); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.manager.tasks.active(), null); assert.equal(f.manager.planner.running, null);
  assert.equal(game.messages.filter(message => message.type === 'task_start').length, 0);
});

test('a new world session cancels the pending step and requires review', async t => {
  const { f, game, goal } = await setup(t); const { pending } = await entering(t, f, game);
  await observe(f, game, { world_session_id: 'objective-new-session' }); await pending;
  assert.equal(f.manager.continuity.goal(goal.goal_id).status, 'needs_review');
  assert.equal(game.messages.filter(message => message.type === 'task_start').length, 0);
});

test('an unknown failed effect blocks the objective and cannot advance from inventory alone', async t => {
  const { f, game, goal } = await setup(t); const task = await dispatch(t, f, game);
  await terminal(f, game, task, { success: false });
  await observe(f, game, { inventory: [{ item_id: 'minecraft:oak_log', count: 4 }] });
  const blocked = f.manager.continuity.goal(goal.goal_id);
  assert.equal(blocked.status, 'blocked'); assert.equal(blocked.steps[0].state, 'blocked');
  assert.equal(blocked.steps[1].state, 'pending'); assert.equal(blocked.steps[0].proof, null);
});

test('the original model planner remains available when there is no approved objective', async t => {
  const { f, game, goal, modelCalls } = await setup(t, { auto: false });
  const result = await f.api('/world-goals/' + goal.goal_id + '/decision', { ...context(f, 'archive-goal'),
    expected_revision: goal.revision, action: 'archive', reason: '本次没有继续该目标' });
  assert.equal(result.status, 200); await game.auto(); await f.manager.planner.tick(); assert.equal(modelCalls(), 1);
});

test('audience speech reads game facts during an approved running task and completes independently of gameplay', async t => {
  const f = await narrationFixture(t, async options => {
    assert.equal(options.purpose, 'speech');
    const facts = await options.tools('game_query_inventory', {});
    assert.equal(facts.world_session_id, f.manager.state.value.world_session_id);
    assert.deepEqual(facts.inventory, f.manager.state.value.inventory);
    return { text: '我正在采集木材，目前背包里的数量以新观测为准。' };
  });
  const goal = await approve(f); await f.game.auto(); f.manager.config.planner.enabled = true;
  const task = await dispatch(t, f, f.game);
  f.game.send('task_update', { delivery_seq: 1, transition_seq: 2, task: { ...task, version: 2, state: 'running' } });
  await until(() => f.manager.tasks.raw(task.task_id).state === 'running');
  const { item, key } = await f.comment('你在做什么？'); assert(item);
  await f.run(); assert.equal(f.calls.length, 1); assert.equal(f.calls[0].purpose, 'speech');
  assert.equal(f.room.store.message(key).answered, false); f.complete(); await new Promise(resolve => queueMicrotask(resolve));
  assert.equal(f.room.store.message(key).answered, true);
  assert.equal(f.manager.tasks.raw(task.task_id).state, 'running');
  assert.equal(f.manager.continuity.goal(goal.goal_id).steps[0].state, 'running');
  assert.equal(f.game.messages.filter(message => message.type === 'task_start').length, 1);
});
