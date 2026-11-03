import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { join } from 'node:path';
import { GameStore, hash } from '../backend/game/store.mjs';
import { gameFixture, until } from './game-fixture.mjs';

const context = (f, request_id) => ({ request_id, bridge_boot_id: f.manager.state.value.bridge_boot_id,
  world_session_id: f.manager.state.value.world_session_id });
const step = { step_id: 'logs', label: '备好木材', goal: { skill: 'gather', item_id: 'minecraft:oak_log', count: 4 },
  condition: { kind: 'inventory_at_least', item_id: 'minecraft:oak_log', count: 4 } };
async function setup(t) { const f = await gameFixture({ fakeClock: true }); t.after(() => f.close());
  const game = await f.connect({ features: { task_ledger: true } }); return { f, game, world: f.manager.state.value.world_id }; }
async function create(f, world, steps = [step]) {
  const response = await f.api('/worlds/' + world + '/goals', { ...context(f, 'goal-create'),
    expected_world_revision: f.manager.worlds.get(world).revision, title: '准备生存物资', description: '', steps });
  assert.equal(response.status, 201, JSON.stringify(response)); return response.value;
}
async function decide(f, goal, action = 'activate') { return f.api('/world-goals/' + goal.goal_id + '/decision', {
  ...context(f, action + '-' + goal.revision), expected_revision: goal.revision, action, reason: '操作者核对当前世界后确认' }); }
async function stopped(f, game) {
  game.send('control_result', { operation_id: 'local-stop', request_id: 'local-stop', world_session_id: game.observation.world_session_id,
    mode: 'PAUSED', control_epoch: game.observation.control_epoch + 1, inputs_released: true, automation_ready: false,
    lease_id: null, heartbeat_seq: null, error: null });
  game.snapshot({ seq: game.observation.seq + 1, control_epoch: game.observation.control_epoch + 1,
    mode: 'PAUSED', inputs_released: true, automation_ready: false, lease_remaining_ms: null, active_task_id: null });
  await until(() => f.manager.state.value.seq === game.observation.seq && !f.manager.lease);
}
async function transition(f, game, task, value, delivery_seq) {
  game.send('task_update', { task: value, transition_seq: value.version, delivery_seq });
  await until(() => f.manager.tasks.raw(task.task_id).version === value.version);
}
async function missing(t) {
  const { f, game, world } = await setup(t); await game.auto();
  const task = (await f.api('/tasks', game.request())).value;
  game.socket.terminate(); await until(() => !f.manager.state.connected);
  const next = await f.connect({ generation: 2, features: { task_ledger: true } });
  const response = await f.api('/tasks/' + task.task_id + '/reconcile', { request_id: 'reconcile-missing' });
  await next.next('query', frame => frame.payload.operation_id === response.value.operation_id);
  const operation = f.manager.operation(response.value.operation_id);
  next.send('query_result', { ...operation, state: 'succeeded', result: { kind: 'task_ledger', game_instance_id: task.game_instance_id,
    world_session_id: next.observation.world_session_id, based_on_seq: next.observation.seq,
    entries: [{ task_id: task.task_id, status: 'missing', task: null }] }, error: null });
  await until(() => f.manager.tasks.recovery(task.task_id)?.status === 'missing');
  return { f, game: next, world, task };
}
function disposition(f, task, id = 'close-unknown') { return { ...context(f, id), expected_control_epoch: f.manager.state.value.control_epoch,
  based_on_seq: f.manager.state.value.seq, expected_task_version: task.version,
  expected_recovery_revision: f.manager.tasks.recovery(task.task_id)?.revision || 0,
  acknowledge_unknown: true, reason: '已检查游戏现况；原操作结果仍未知，允许重新规划' }; }

test('v2 migration backs up committed WAL and labels imported sessions as legacy, without inventing observations', async t => {
  const { f, world } = await setup(t), path = join(f.folder, 'legacy-v2.sqlite3');
  const seed = new GameStore(path); seed.close(); const old = new DatabaseSync(path); let upgraded;
  old.exec('DROP TABLE bridge_history; DROP TABLE history_partial; DROP TABLE world_goal_tasks; DROP TABLE world_goals; DROP TABLE world_sessions; DROP TABLE task_dispositions; DELETE FROM schema_migrations WHERE version>=3; PRAGMA journal_mode=WAL');
  old.prepare('INSERT INTO world_registry VALUES(?,?,?,?)').run(world, 'mc-instance-example', 1, JSON.stringify(f.manager.worlds.get(world)));
  old.prepare('INSERT INTO task_recovery VALUES(?,?,?)').run('task-old', 'missing', JSON.stringify({ task_id: 'task-old', status: 'missing' }));
  old.prepare('INSERT OR REPLACE INTO meta VALUES(?,?)').run('committed_v2_wal', '{"kept":true}');
  try {
    upgraded = new GameStore(path); assert.equal(upgraded.schemaVersion, 4); assert.deepEqual(upgraded.meta('committed_v2_wal'), { kept: true });
    const imported = JSON.parse(upgraded.get('SELECT value FROM world_sessions').value);
    assert.equal(imported.source, 'legacy_registry'); assert.equal(imported.status, 'unobserved');
    assert.equal(imported.last_seq, null); assert.equal(imported.connection_count, 0);
    assert.equal(JSON.parse(upgraded.get('SELECT value FROM task_recovery').value).revision, 1);
    const backup = new DatabaseSync(join(f.folder, 'backups', upgraded.meta('schema_v3_migration').backup_file), { readOnly: true });
    try { assert.equal(backup.prepare('SELECT MAX(version) n FROM schema_migrations').get().n, 2);
      assert.equal(backup.prepare('SELECT value FROM meta WHERE key=?').get('committed_v2_wal').value, '{"kept":true}');
      assert.equal(JSON.parse(backup.prepare('SELECT value FROM task_recovery').get().value).revision, undefined);
    } finally { backup.close(); }
  } finally { upgraded?.close(); old.close(); }
});

test('world session history survives disconnect, reconnect and host restart without replaying input', async t => {
  const { f, game, world } = await setup(t); const first = (await f.api('/worlds/' + world + '/sessions')).value.items[0];
  assert.equal(first.status, 'observed'); assert.equal(first.connection_count, 1);
  game.snapshot({ seq: 2 }); await until(() => f.manager.state.value.seq === 2);
  game.socket.terminate(); await until(() => !f.manager.state.connected);
  assert.equal(f.manager.continuity.session(first.world_session_id).last_seq, 2);
  assert.equal(f.manager.continuity.session(first.world_session_id).status, 'unobserved');
  const next = await f.connect({ generation: 2 });
  assert.equal(f.manager.continuity.session(first.world_session_id).connection_count, 2);
  await f.restartHost(); assert.equal(f.manager.continuity.session(first.world_session_id).status, 'unobserved');
  assert.equal(next.messages.filter(frame => frame.type === 'task_start').length, 0);
  assert.equal((await f.api('/worlds/' + world + '/sessions?limit=101')).status, 400);
});

test('goal draft approval uses CAS and does not grant AUTO; new sessions require review', async t => {
  const { f, game, world } = await setup(t); const goal = await create(f, world);
  const approved = await decide(f, goal); assert.equal(approved.status, 200); assert.equal(approved.value.status, 'active');
  assert.equal(f.manager.lease, null); assert.equal(f.manager.state.value.mode, 'PAUSED');
  const stale = await f.api('/world-goals/' + goal.goal_id + '/decision', { ...context(f, 'stale-approve'), expected_revision: 1, action: 'pause', reason: '旧版本' });
  assert.equal(stale.value.error, 'GAME_WORLD_GOAL_CONFLICT');
  game.snapshot({ seq: 2, world_session_id: 'new-world-session' });
  await until(() => f.manager.state.value.world_session_id === 'new-world-session');
  assert.equal(f.manager.continuity.goal(goal.goal_id).status, 'needs_review');
  const history = (await f.api('/worlds/' + world + '/sessions')).value.items;
  assert.equal(history.length, 2); assert.equal(history.find(s => s.world_session_id !== 'new-world-session').status, 'ended');
  const rereview = await decide(f, f.manager.continuity.goal(goal.goal_id)); assert.equal(rereview.value.last_review_session_id, 'new-world-session');
  assert.equal(game.messages.filter(frame => frame.type === 'task_start').length, 0);
});

test('goal completion requires fresh known inventory and records observation provenance without claiming task execution', async t => {
  const { f, game, world } = await setup(t), goal = await create(f, world); await decide(f, goal);
  game.snapshot({ seq: 2, inventory: [{ item_id: 'minecraft:oak_log', count: 4 }], unknown_fields: ['inventory'] });
  await until(() => f.manager.state.value.seq === 2); assert.equal(f.manager.continuity.goal(goal.goal_id).status, 'active');
  game.snapshot({ seq: 3, unknown_fields: [] }); await until(() => f.manager.continuity.goal(goal.goal_id).status === 'completed');
  const proof = f.manager.continuity.goal(goal.goal_id).steps[0].proof;
  assert.equal(proof.source, 'observation'); assert.equal(proof.task_id, null); assert.equal(proof.seq, 3);
  const summary = (await f.api('/state')).value.world_ledger; assert.equal(summary.world_goals[0].completed_steps, 1);
});

test('a linked goal waits for verified task and later observation, retaining canonical B task separately', async t => {
  const { f, game, world } = await setup(t), goal = await create(f, world); await decide(f, goal); await game.auto();
  const request = { ...game.request(step.goal), world_goal_ref: f.manager.continuity.referenceFor(step.goal) };
  const created = await f.api('/tasks', request); assert.equal(created.status, 202); const task = created.value;
  assert.equal(Object.hasOwn(task, 'world_goal_ref'), false);
  game.snapshot({ seq: 3, inventory: [{ item_id: 'minecraft:oak_log', count: 4 }] }); await until(() => f.manager.state.value.seq === 3);
  assert.equal(f.manager.continuity.goal(goal.goal_id).steps[0].state, 'running');
  await transition(f, game, task, { ...task, version: 2, state: 'running' }, 1);
  const done = { ...task, version: 3, state: 'succeeded', effect_status: 'verified', evidence: [{ world_session_id: task.world_session_id,
    seq: 4, kind: 'inventory', summary: 'FIXTURE_ONLY' }] };
  await transition(f, game, task, done, 2); assert.equal(f.manager.continuity.goal(goal.goal_id).steps[0].state, 'awaiting_observation');
  game.snapshot({ seq: 4 }); await until(() => f.manager.continuity.goal(goal.goal_id).status === 'completed');
  assert.equal(f.manager.continuity.goal(goal.goal_id).steps[0].proof.task_id, task.task_id);
});

test('invalid goal links roll back task and idempotency writes before any dispatch', async t => {
  const { f, game, world } = await setup(t), goal = await create(f, world); await decide(f, goal); await game.auto();
  const response = await f.api('/tasks', { ...game.request(), world_goal_ref: { goal_id: goal.goal_id, step_id: 'logs', expected_revision: 99 } });
  assert.equal(response.value.error, 'GAME_WORLD_GOAL_CONFLICT'); assert.equal(f.manager.tasks.page().items.length, 0);
  assert.equal(game.messages.filter(m => m.type === 'task_start').length, 0);
  assert.equal(f.manager.store.get("SELECT count(*) n FROM idempotency WHERE kind='task'").n, 0);
});

test('closing unknown effects is a fenced, idempotent audit decision and preserves B bytes and unknown effect', async t => {
  const { f, game, task } = await missing(t), raw = f.manager.tasks.raw(task.task_id), request = disposition(f, task);
  assert.equal((await f.api('/tasks/' + task.task_id + '/disposition', { ...request, based_on_seq: request.based_on_seq - 1 })).status, 409);
  assert.equal((await f.api('/tasks/' + task.task_id + '/disposition', { ...request, acknowledge_unknown: false })).status, 400);
  const response = await f.api('/tasks/' + task.task_id + '/disposition', request); assert.equal(response.status, 200, JSON.stringify(response));
  assert.deepEqual(f.manager.tasks.raw(task.task_id), raw); assert.equal(response.value.effect_status, 'unknown');
  assert.equal(response.value.disposition.task_hash, hash(raw)); assert.equal(response.value.recovery.status, 'operator_closed');
  assert.equal(f.manager.tasks.active(), null); assert.equal(f.manager.lease, null);
  assert.equal((await f.api('/tasks/' + task.task_id + '/disposition', request)).value.disposition.revision, 1);
  assert.equal((await f.api('/tasks/' + task.task_id + '/disposition', { ...request, reason: '改写相同请求' })).value.error, 'GAME_IDEMPOTENCY_CONFLICT');
  assert.equal(game.messages.filter(frame => ['task_start', 'lease_grant'].includes(frame.type)).length, 0);
  await f.restartHost(); assert.equal(f.manager.tasks.get(task.task_id).disposition.status, 'closed_unknown');
});

test('a disposed task reappearing as active reopens the fence, revokes AUTO and requests PAUSED', async t => {
  const { f, game, task } = await missing(t); await f.api('/tasks/' + task.task_id + '/disposition', disposition(f, task));
  await game.auto('new-explicit-auto'); game.snapshot({ seq: game.observation.seq + 1, active_task_id: task.task_id });
  await game.next('control_request', frame => frame.payload.reason === 'GAME_DISPOSED_TASK_REAPPEARED');
  assert.equal(f.manager.lease, null); assert.equal(f.manager.tasks.get(task.task_id).disposition.status, 'reopened');
  assert.equal(f.manager.tasks.get(task.task_id).recovery.status, 'conflict');
});

test('terminal unknown effects require acknowledgement before goal retry and never count as completion', async t => {
  const { f, game, world } = await setup(t), goal = await create(f, world); await decide(f, goal); await game.auto();
  const task = (await f.api('/tasks', { ...game.request(step.goal), world_goal_ref: f.manager.continuity.referenceFor(step.goal) })).value;
  const failed = { ...task, version: 2, state: 'failed', reason: 'FIXTURE_UNCERTAIN', effect_status: 'unknown' };
  await transition(f, game, task, failed, 1); await stopped(f, game);
  assert.equal((await decide(f, f.manager.continuity.goal(goal.goal_id), 'retry_step')).value.error, 'GAME_WORLD_GOAL_UNKNOWN_EFFECT');
  const closed = await f.api('/tasks/' + task.task_id + '/disposition', disposition(f, failed)); assert.equal(closed.status, 200, JSON.stringify(closed));
  assert.equal(closed.value.disposition.recovery_revision, 0); assert.equal(closed.value.state, 'failed');
  const retry = await decide(f, f.manager.continuity.goal(goal.goal_id), 'retry_step'); assert.equal(retry.value.status, 'needs_review');
  assert.equal(retry.value.steps[0].state, 'pending'); assert.equal(retry.value.steps[0].proof, null);
  assert.equal((await decide(f, retry.value)).value.status, 'active');
  assert.equal(game.messages.filter(frame => frame.type === 'task_start').length, 1);
});

test('disposition is refused with stale observation or active B input authority', async t => {
  const { f, game, task } = await missing(t); f.advance(2100);
  assert.equal((await f.api('/tasks/' + task.task_id + '/disposition', disposition(f, task))).value.error, 'GAME_STATE_STALE');
  game.snapshot({ seq: 2, active_task_id: task.task_id }); await until(() => f.manager.state.value.seq === 2);
  assert.equal((await f.api('/tasks/' + task.task_id + '/disposition', disposition(f, task))).value.error, 'GAME_DISPOSITION_BRIDGE_BUSY');
  assert.equal(f.manager.tasks.disposition(task.task_id), null);
});

test('unknown player fields cannot satisfy food or position goal conditions', async t => {
  const { f, game, world } = await setup(t); const goal = await create(f, world, [{...step, condition:{kind:'food_at_least',food:18}}]); await decide(f,goal);
  game.snapshot({seq:2,player:{...game.observation.player,food:20},unknown_fields:['player.food']}); await until(()=>f.manager.state.value.seq===2);
  assert.equal(f.manager.continuity.goal(goal.goal_id).status,'active');
  assert.equal(f.manager.continuity.conditionMet({kind:'position_within',target:{dimension:'minecraft:overworld',x:0,y:64,z:0},radius:3},
    {...game.observation,player:{...game.observation.player,position:{dimension:'minecraft:overworld',x:0,y:64,z:0}},unknown_fields:['player.position.x']}),false);
  game.snapshot({seq:3,unknown_fields:[]}); await until(()=>f.manager.continuity.goal(goal.goal_id).status==='completed');
});

test('human closure of a nonterminal linked task blocks its goal and permits only explicit replanning', async t => {
  const { f, game, world } = await setup(t), goal=await create(f,world); await decide(f,goal); await game.auto();
  const task=(await f.api('/tasks',{...game.request(step.goal),world_goal_ref:f.manager.continuity.referenceFor(step.goal)})).value;
  await stopped(f,game); f.manager.tasks.setRecovery(task.task_id,'missing','FIXTURE_MISSING',{checked_bridge_boot_id:game.identity.bridge_boot_id});
  const closed=await f.api('/tasks/'+task.task_id+'/disposition',disposition(f,task));assert.equal(closed.status,200);
  assert.equal(f.manager.tasks.raw(task.task_id).state,'accepted');assert.equal(f.manager.continuity.goal(goal.goal_id).steps[0].state,'blocked');
  const retry=await decide(f,f.manager.continuity.goal(goal.goal_id),'retry_step');assert.equal(retry.value.steps[0].state,'pending');
  game.snapshot({seq:game.observation.seq+1,inventory:[{item_id:'minecraft:oak_log',count:4}]});await until(()=>f.manager.state.value.seq===game.observation.seq);
  assert.equal(f.manager.continuity.goal(goal.goal_id).status,'needs_review');assert.equal(game.messages.filter(m=>m.type==='task_start').length,1);
});

test('a reliable nonterminal report after disposition reopens the fence before ACK', async t => {
  const { f, game, task }=await missing(t);await f.api('/tasks/'+task.task_id+'/disposition',disposition(f,task));
  game.send('task_update',{task:{...task,version:2,state:'running'},transition_seq:2,delivery_seq:1});
  await game.next('control_request',frame=>frame.payload.reason==='GAME_DISPOSED_TASK_REAPPEARED');
  const ack=await game.next('ack',frame=>frame.payload.ack_kind==='task_transitions');assert.equal(ack.payload.through_seq,1);
  assert.equal(f.manager.tasks.get(task.task_id).disposition.status,'reopened');assert.equal(f.manager.tasks.get(task.task_id).recovery.status,'conflict');
});
