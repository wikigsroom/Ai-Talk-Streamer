import test from 'node:test';
import assert from 'node:assert/strict';
import { gameFixture, until } from './game-fixture.mjs';
import { validate } from '../backend/game/protocol.mjs';

async function setup(t) {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); const game = await f.connect();
  const state = f.manager.state.value, worldId = state.world_id;
  const registered = await f.api('/worlds/' + worldId + '/bases', { request_id: 'home-registration',
    bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id,
    expected_world_revision: 1, label: '测试登记基地', radius: 3 });
  assert.equal(registered.status, 201, JSON.stringify(registered)); const base = registered.value;
  const goal = { skill: 'return_base', base_id: base.base_id };
  const query = (extra = {}) => {
    const state = f.manager.state.value;
    return { request_id: 'home-query-' + crypto.randomUUID(), bridge_boot_id: state.bridge_boot_id,
      world_session_id: state.world_session_id, kind: 'check_action', params: { goal, ...extra } };
  };
  const rename = () => f.manager.worlds.label(worldId, { request_id: 'rename-' + crypto.randomUUID(),
    expected_revision: f.manager.worlds.get(worldId).revision, local_label: '变更后的世界名' });
  return { f, game, base, goal, query, rename, worldId };
}
async function reply(f, game, frame) {
  frame ??= await game.next('query', m => f.manager.pending.has(m.payload.operation_id));
  const operation = f.manager.operation(frame.payload.operation_id);
  game.send('query_result', { ...operation, state: 'succeeded', result: { kind: 'check_action',
    world_session_id: game.observation.world_session_id, allowed: true, base_target: frame.payload.base_target } });
  await until(() => f.manager.operation(operation.operation_id).state !== 'pending');
  return f.manager.operation(operation.operation_id);
}

test('base preflight reads registered coordinates and records the full immutable target on the wire', async t => {
  const { f, game, base, goal, query } = await setup(t);
  const response = await f.api('/queries', query()); assert.equal(response.status, 202);
  const frame = await game.next('query'), target = frame.payload.base_target; validate('BaseTarget', target);
  assert.deepEqual(target.position, base.position); assert.equal(target.base_id, goal.base_id);
  assert.equal(target.radius, 3); assert.equal(target.world_revision, 2); assert.equal(target.source, 'operator_observed');
  assert.equal(target.registered_world_session_id, base.world_session_id); assert.equal(target.registered_seq, base.based_on_seq);
  assert.deepEqual((await reply(f, game, frame)).result.base_target, target);
  assert.equal(f.manager.tasks.active(), null);
});

test('public requests reject arbitrary base coordinates and base references on unrelated skills', async t => {
  const { f, game, goal, query } = await setup(t); const target = f.manager.worlds.resolveBase(goal);
  assert.equal((await f.api('/queries', { ...query(), params: { goal, base_target: target } })).status, 400);
  await game.auto();
  assert.equal((await f.api('/tasks', { ...game.request(goal), base_target: target })).status, 400);
  assert.equal((await f.api('/tasks', { ...game.request(), base_ref: f.manager.worlds.baseReference(target) })).status, 400);
  assert.equal(game.messages.filter(m => m.type === 'task_start').length, 0);
});

test('archived base preflight fails before creating an operation or sending a query', async t => {
  const { f, game, base, worldId, query } = await setup(t);
  f.manager.worlds.archiveBase(worldId, base.base_id, { request_id: 'archive-home', expected_revision: 1, expected_world_revision: 2 });
  const response = await f.api('/queries', query()); assert.equal(response.value.error, 'GAME_BASE_ARCHIVED');
  assert.equal(game.messages.filter(m => m.type === 'query').length, 0);
});

test('base lookup is scoped to the current stable world rather than a matching coordinate', async t => {
  const { f, game, query } = await setup(t);
  game.snapshot({ world_id: 'world-home-other', world_session_id: 'session-home-other', seq: 1 });
  await until(() => f.manager.state.value.world_id === 'world-home-other');
  assert.equal((await f.api('/queries', query())).value.error, 'GAME_BASE_NOT_FOUND');
  assert.equal(game.messages.filter(m => m.type === 'query').length, 0);
});

test('a registered base in another dimension cannot be dispatched', async t => {
  const { f, game, query } = await setup(t);
  const player = structuredClone(game.observation.player); player.position.dimension = 'minecraft:the_nether';
  game.snapshot({ seq: 2, player }); await until(() => f.manager.state.value.seq === 2);
  assert.equal((await f.api('/queries', query())).value.error, 'GAME_BASE_DIMENSION_CHANGED');
});

test('registry revision changes while preflight is pending invalidate its result', async t => {
  const { f, game, query, rename } = await setup(t);
  const pending = await f.api('/queries', query()); assert.equal(pending.status, 202);
  const frame = await game.next('query'); rename(); const done = await reply(f, game, frame);
  assert.equal(done.state, 'failed'); assert.equal(done.error, 'GAME_BASE_CHANGED');
  assert.equal(f.manager.tasks.active(), null);
});

test('a successful preflight reference prevents retargeting between check and admission', async t => {
  const { f, game, query, goal, rename } = await setup(t);
  await f.api('/queries', query()); const checked = await reply(f, game);
  const reference = f.manager.worlds.baseReference(checked.result.base_target); rename(); await game.auto();
  const response = await f.api('/tasks', { ...game.request(goal), base_ref: reference });
  assert.equal(response.value.error, 'GAME_BASE_CHANGED'); assert.equal(f.manager.tasks.active(), null);
  assert.equal(game.messages.filter(m => m.type === 'task_start').length, 0);
});

test('DSH preflight pins the base reference in the dispatched request and durable task', async t => {
  const { f, game, goal } = await setup(t); await game.auto(); const state = f.manager.state.view();
  const invoked = f.manager.tools.invoke('game_start_task', { goal }, { purpose: 'game_plan',
    worldSessionId: state.world_session_id, controlEpoch: state.control_epoch });
  const checked = await reply(f, game); const task = await invoked; const sent = await game.next('task_start');
  assert.deepEqual(sent.payload.request.base_ref, f.manager.worlds.baseReference(checked.result.base_target));
  assert.deepEqual(sent.payload.base_target, task.base_target); assert.deepEqual(task.goal, goal);
  assert.deepEqual(f.manager.tasks.raw(task.task_id).base_target, checked.result.base_target);
});

test('audience return-base dispatch uses the same registry binding as DSH', async t => {
  const { f, game, base } = await setup(t); const event = f.platformEvent({ text: '建议 回基地' });
  const proposal = f.manager.suggestions.page().items.find(s => s.source_event_ids.includes(event.event_key));
  assert.equal(proposal.goal.base_id, base.base_id);
  const accepted = f.manager.suggestions.decision(proposal.suggestion_id, { request_id: 'approve-home',
    expected_revision: proposal.revision, action: 'accept', reason: 'fixture_review' });
  await game.auto(); const state = f.manager.state.view();
  const operation = f.manager.suggestions.dispatch(accepted.suggestion_id, { request_id: 'dispatch-home',
    bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id,
    expected_control_epoch: state.control_epoch, expected_revision: accepted.revision });
  const checked = await reply(f, game);
  await until(() => f.manager.operation(operation.operation_id).state !== 'pending');
  assert.equal(f.manager.operation(operation.operation_id).state, 'succeeded'); const sent = await game.next('task_start');
  assert.deepEqual(sent.payload.request.base_ref, f.manager.worlds.baseReference(checked.result.base_target));
  assert.equal(f.manager.suggestions.get(accepted.suggestion_id).task_id, sent.payload.task_id);
});

test('a task update cannot change or remove the accepted base target', async t => {
  const { f, game, goal } = await setup(t); await game.auto(); const task = (await f.api('/tasks', game.request(goal))).value;
  for (const mutate of [value => value.base_target.position.x++, value => delete value.base_target]) {
    const changed = structuredClone(task); changed.version = 2; changed.state = 'running'; mutate(changed);
    assert.throws(() => f.manager.tasks.update({ task: changed, transition_seq: 2 }), e => e.code === 'GAME_TASK_BASE_CHANGED');
    assert.deepEqual(f.manager.tasks.raw(task.task_id).base_target, task.base_target);
  }
});

test('ledger reconciliation cannot replace a base target even with an otherwise newer valid task', async t => {
  const { f, game, goal } = await setup(t); await game.auto(); const task = (await f.api('/tasks', game.request(goal))).value;
  const changed = structuredClone(task); changed.base_target.base_revision++; changed.version = 2; changed.state = 'running';
  const result = { kind: 'task_ledger', game_instance_id: task.game_instance_id, world_session_id: task.world_session_id,
    based_on_seq: 2, entries: [{ task_id: task.task_id, status: 'found', task: changed }] };
  assert.throws(() => f.manager.tasks.reconcile(result, [task.task_id]), e => e.code === 'GAME_TASK_BASE_CHANGED');
  assert.equal(f.manager.tasks.get(task.task_id).recovery.status, 'conflict');
  assert.deepEqual(f.manager.tasks.raw(task.task_id).base_target, task.base_target);
});

test('idempotent replay preserves the admitted target after registry change and host restart', async t => {
  const { f, game, goal, rename } = await setup(t); await game.auto(); const request = game.request(goal);
  const task = (await f.api('/tasks', request)).value; await game.next('task_start'); rename();
  const replay = await f.api('/tasks', request); assert.equal(replay.status, 200); assert.deepEqual(replay.value.base_target, task.base_target);
  assert.equal(game.messages.filter(m => m.type === 'task_start').length, 1);
  await f.restartHost(); const restored = f.manager.tasks.get(task.task_id);
  assert.equal(restored.recovery.status, 'required'); assert.deepEqual(restored.base_target, task.base_target);
  assert.deepEqual((await f.api('/tasks', request)).value.base_target, task.base_target); assert.ok(!f.manager.lease);
});
