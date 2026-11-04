import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { join } from 'node:path';
import { readdirSync } from 'node:fs';
import { GameStore } from '../backend/game/store.mjs';
import { validate } from '../backend/game/protocol.mjs';
import { gameFixture, until } from './game-fixture.mjs';

const context = (f, request_id) => ({ request_id, bridge_boot_id: f.manager.state.value.bridge_boot_id,
  world_session_id: f.manager.state.value.world_session_id });
async function interruptedFixture(t) {
  const f = await gameFixture(); t.after(() => f.close());
  const game = await f.connect({ features: { task_ledger: true } }); await game.auto();
  const request = game.request(undefined, 'recovery-task'), created = await f.api('/tasks', request);
  assert.equal(created.status, 202); game.socket.terminate(); await until(() => !f.manager.state.connected);
  const next = await f.connect({ generation: 2, features: { task_ledger: true } });
  return { f, next, task: created.value, request };
}
async function ledgerReply(f, game, task, entry) {
  const response = await f.api('/tasks/' + task.task_id + '/reconcile', { request_id: 'manual-reconcile' });
  assert.equal(response.status, 202, JSON.stringify(response));
  const query = await game.next('query', frame => frame.payload.operation_id === response.value.operation_id);
  const operation = f.manager.operation(response.value.operation_id);
  game.send('query_result', { ...operation, state: 'succeeded', result: { kind: 'task_ledger',
    game_instance_id: task.game_instance_id, world_session_id: f.manager.state.value.world_session_id,
    based_on_seq: f.manager.state.value.seq, entries: [entry] }, error: null });
  return { query, operation };
}

test('schema v1 migration takes a consistent backup containing committed WAL data', async t => {
  const f = await gameFixture(); t.after(() => f.close());
  const path = join(f.folder, 'legacy.sqlite3'); const seed = new GameStore(path); seed.close();
  const old = new DatabaseSync(path);
  old.exec('DROP TABLE bridge_history; DROP TABLE history_partial; DROP TABLE world_goal_tasks; DROP TABLE world_goals; DROP TABLE world_sessions; DROP TABLE task_dispositions; DROP TABLE world_bases; DROP TABLE world_checkpoints; DROP TABLE world_registry; DROP TABLE task_recovery; DELETE FROM schema_migrations WHERE version>=2; PRAGMA journal_mode=WAL');
  old.prepare('INSERT OR REPLACE INTO meta VALUES(?,?)').run('committed_wal', JSON.stringify({ marker: 'preserved' }));
  let upgraded;
  try {
    upgraded = new GameStore(path); assert.equal(upgraded.schemaVersion, 4);
    assert.deepEqual(upgraded.meta('committed_wal'), { marker: 'preserved' });
    const backupName = upgraded.meta('schema_v2_migration').backup_file;
    assert.ok(readdirSync(join(f.folder, 'backups')).includes(backupName));
    const backup = new DatabaseSync(join(f.folder, 'backups', backupName), { readOnly: true });
    try {
      assert.equal(backup.prepare('SELECT max(version) n FROM schema_migrations').get().n, 1);
      assert.equal(JSON.parse(backup.prepare('SELECT value FROM meta WHERE key=?').get('committed_wal').value).marker, 'preserved');
      assert.equal(backup.prepare("SELECT name FROM sqlite_master WHERE name='world_registry'").get(), undefined);
    } finally { backup.close(); }
  } finally { upgraded?.close(); old.close(); }
});

test('a future database version is refused before ownership or migration changes', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const path = join(f.folder, 'future.sqlite3');
  const seed = new GameStore(path); seed.close(); const raw = new DatabaseSync(path);
  raw.prepare('INSERT INTO schema_migrations VALUES(?,?)').run(99, new Date().toISOString());
  try {
    assert.throws(() => new GameStore(path), /GAME_DATABASE_VERSION/);
    assert.equal(raw.prepare('SELECT count(*) n FROM game_owner').get().n, 0);
    assert.equal(raw.prepare('SELECT max(version) n FROM schema_migrations').get().n, 99);
  } finally { raw.close(); }
});

test('world labels use CAS and survive new sessions without changing stable identity', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect();
  const worldId = f.manager.state.value.world_id; const world = (await f.api('/worlds/' + worldId)).value;
  assert.equal(world.revision, 1);
  const label = { request_id: 'label-one', expected_revision: 1, local_label: '测试世界' };
  assert.equal((await f.api('/worlds/' + worldId + '/label', label)).value.revision, 2);
  assert.equal((await f.api('/worlds/' + worldId + '/label', label)).status, 200);
  assert.equal((await f.api('/worlds/' + worldId + '/label', { ...label, request_id: 'stale-label' })).status, 409);
  game.snapshot({ world_session_id: 'world-session-second', seq: 1 });
  await until(() => f.manager.worlds.get(worldId).last_world_session_id === 'world-session-second');
  assert.equal(f.manager.worlds.get(worldId).local_label, '测试世界'); assert.equal(f.manager.worlds.get(worldId).revision, 2);
  assert.equal((await f.api('/worlds')).value.items.length, 1);
});

test('base registration uses the actual fresh position, isolates worlds and preserves idempotency', async t => {
  const f = await gameFixture(); t.after(() => f.close()); await f.connect();
  const state = f.manager.state.view(), path = '/worlds/' + state.world_id + '/bases';
  const request = { ...context(f, 'register-base'), expected_world_revision: 1, label: '测试基地', radius: 8 };
  assert.equal((await f.api(path, { ...request, position: { x: 999, y: 0, z: 0 } })).status, 400);
  const created = await f.api(path, request); assert.equal(created.status, 201, JSON.stringify(created));
  assert.deepEqual(created.value.position, state.player.position); assert.equal(created.value.based_on_seq, state.seq);
  assert.equal((await f.api(path, request)).value.base_id, created.value.base_id);
  assert.equal((await f.api(path, { ...request, radius: 16 })).status, 409);
  assert.equal((await f.api('/worlds/world-foreign/bases', { ...request, request_id: 'foreign-base' })).status, 409);
  assert.equal(f.manager.worlds.get(state.world_id).active_base_id, created.value.base_id);
});

test('base archive clears the active reference and checkpoints preserve immutable observed state', async t => {
  const f = await gameFixture(); t.after(() => f.close()); await f.connect(); const world = f.manager.state.value.world_id;
  const base = (await f.api('/worlds/' + world + '/bases', { ...context(f, 'base'), expected_world_revision: 1, label: '基地', radius: 8 })).value;
  const request = { ...context(f, 'checkpoint'), reason: 'operator_stop' };
  const checkpoint = await f.api('/worlds/' + world + '/checkpoints', request); assert.equal(checkpoint.status, 201);
  assert.deepEqual(checkpoint.value.base_refs, [base.base_id]); assert.equal(checkpoint.value.snapshot.mode, 'PAUSED');
  const archive = await f.api('/worlds/' + world + '/bases/' + base.base_id + '/archive', { request_id: 'archive', expected_revision: 1, expected_world_revision: 2 });
  assert.equal(archive.status, 200); assert.equal(f.manager.worlds.get(world).active_base_id, null);
  assert.deepEqual((await f.api('/checkpoints/' + checkpoint.value.checkpoint_id)).value.base_refs, [base.base_id]);
  assert.equal((await f.api('/worlds/' + world + '/checkpoints', request)).value.checkpoint_id, checkpoint.value.checkpoint_id);
  await f.restartHost();
  assert.equal((await f.api('/worlds/' + world + '/checkpoints')).value.items[0].checkpoint_id, checkpoint.value.checkpoint_id);
  assert.equal(f.manager.state.value.mode, null); assert.equal(f.manager.lease, undefined);
});

test('checkpoint creation rejects AUTO and stale state', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); const game = await f.connect();
  const path = '/worlds/' + f.manager.state.value.world_id + '/checkpoints';
  await game.auto(); assert.equal((await f.api(path, { ...context(f, 'auto-checkpoint'), reason: 'invalid_auto' })).status, 409);
  f.advance(3000); assert.equal((await f.api(path, { ...context(f, 'stale-checkpoint'), reason: 'invalid_stale' })).status, 503);
});

test('authoritative ledger recovery fills missed terminal versions without dispatching another task', async t => {
  const { f, next, task, request } = await interruptedFixture(t);
  assert.equal(f.manager.tasks.get(task.task_id).version, 1); assert.equal(f.manager.tasks.get(task.task_id).recovery.status, 'required');
  const terminal = { ...task, version: 3, state: 'succeeded', effect_status: 'verified', evidence: [{
    world_session_id: task.world_session_id, seq: 3, kind: 'inventory', summary: 'PROTOCOL_FIXTURE_ONLY' }] };
  const { operation } = await ledgerReply(f, next, task, { task_id: task.task_id, status: 'found', task: terminal });
  await until(() => f.manager.operation(operation.operation_id).state === 'succeeded');
  const recovered = f.manager.tasks.get(task.task_id); assert.equal(recovered.state, 'succeeded'); assert.equal(recovered.version, 3);
  assert.equal(recovered.recovery.status, 'verified'); assert.equal((await f.api('/tasks', request)).value.task_id, task.task_id);
  assert.equal(next.messages.filter(frame => frame.type === 'task_start').length, 0);
});

test('a missing B record remains unknown and blocks AUTO instead of replaying the request', async t => {
  const { f, next, task } = await interruptedFixture(t);
  const { operation } = await ledgerReply(f, next, task, { task_id: task.task_id, status: 'missing', task: null });
  await until(() => f.manager.operation(operation.operation_id).state === 'succeeded');
  const current = f.manager.tasks.get(task.task_id); assert.equal(current.state, 'accepted'); assert.equal(current.effect_status, 'unknown');
  assert.equal(current.recovery.status, 'missing'); assert.equal(next.messages.filter(frame => frame.type === 'task_start').length, 0);
  const state = f.manager.state.view();
  const auto = await f.api('/control', { ...context(f, 'unsafe-auto'), target_mode: 'AUTO', expected_control_epoch: state.control_epoch, reason: 'unknown_effect' });
  assert.equal(auto.status, 409);
});

test('a conflicting ledger identity cannot overwrite the task or remove the recovery fence', async t => {
  const { f, next, task } = await interruptedFixture(t);
  await ledgerReply(f, next, task, { task_id: task.task_id, status: 'found', task: { ...task, world_id: 'foreign-world' } });
  await until(() => !f.manager.state.connected);
  const current = f.manager.tasks.get(task.task_id); assert.equal(current.world_id, task.world_id);
  assert.equal(current.recovery.status, 'conflict'); assert.equal(current.recovery.last_error, 'GAME_TASK_CONTEXT_CHANGED');
});

const absenceProof = (f, task) => ({ kind: 'never_admitted', fence_id: 'admission-fence-fixture', task_id: task.task_id,
  game_instance_id: task.game_instance_id, fenced_at: new Date().toISOString(),
  checked_bridge_boot_id: f.manager.state.identity.bridge_boot_id, checked_world_session_id: f.manager.state.value.world_session_id });

test('the admission proof contract requires a proof for not-admitted recovery and forbids it on a found task', () => {
  const proof={kind:'never_admitted',fence_id:'fence-one',task_id:'task-one',game_instance_id:'mc-one',fenced_at:new Date().toISOString(),checked_bridge_boot_id:'boot-one',checked_world_session_id:'world-one'};
  const recovery={task_id:'task-one',revision:1,status:'not_admitted',reason:'NATIVE_FENCE',created_at:proof.fenced_at,updated_at:proof.fenced_at,attempts:1,checked_bridge_boot_id:'boot-one',confirmed_version:null,last_error:null,admission_fence:proof};
  validate('TaskRecovery',recovery); validate('LedgerEntry',{task_id:'task-one',status:'missing',task:null,admission_fence:proof});
  const {admission_fence,...withoutProof}=recovery; assert.throws(()=>validate('TaskRecovery',withoutProof));
  assert.throws(()=>validate('TaskRecovery',{...recovery,status:'verified'}));
  assert.throws(()=>validate('LedgerEntry',{task_id:'task-one',status:'found',task:null,admission_fence:proof}));
  assert.throws(()=>validate('AdmissionFence',{...proof,kind:'executed_successfully'}));
});

test('native absence proof releases only the admission blocker and survives a host restart without inventing an outcome', async t => {
  const { f, next, task } = await interruptedFixture(t);
  const { operation } = await ledgerReply(f, next, task, { task_id: task.task_id, status: 'missing', task: null, admission_fence: absenceProof(f,task) });
  await until(() => f.manager.operation(operation.operation_id).state === 'succeeded');
  assert.deepEqual(f.manager.tasks.raw(task.task_id), task); assert.equal(f.manager.tasks.active(), null);
  assert.equal(f.manager.tasks.get(task.task_id).recovery.status, 'not_admitted');
  assert.equal(f.manager.state.value.mode, 'PAUSED'); assert.equal(f.manager.lease, null);
  assert.equal(next.messages.filter(frame => frame.type === 'task_start').length, 0);
  assert.equal(f.manager.tasks.planningOutcomes(f.manager.state.view()).length, 0);
  await f.restartHost(); assert.equal(f.manager.tasks.active(), null);
  assert.equal(f.manager.tasks.get(task.task_id).recovery.status, 'not_admitted');
});

for (const field of ['task_id','game_instance_id','checked_bridge_boot_id','checked_world_session_id']) {
  test('an absence proof with a foreign '+field+' cannot clear an unknown task', async t => {
    const { f, next, task } = await interruptedFixture(t), proof = { ...absenceProof(f,task), [field]: 'foreign-id' };
    await ledgerReply(f,next,task,{ task_id:task.task_id,status:'missing',task:null,admission_fence:proof });
    await until(() => !f.manager.state.connected);
    assert.equal(f.manager.tasks.active().task_id,task.task_id); assert.deepEqual(f.manager.tasks.raw(task.task_id),task);
    assert.equal(f.manager.tasks.recovery(task.task_id).status,'conflict');
  });
}

test('an accepted native transition contradicting an absence proof reinstates the blocker', async t => {
  const { f,next,task }=await interruptedFixture(t);
  const { operation }=await ledgerReply(f,next,task,{ task_id:task.task_id,status:'missing',task:null,admission_fence:absenceProof(f,task) });
  await until(()=>f.manager.operation(operation.operation_id).state==='succeeded');
  assert.throws(()=>f.manager.tasks.update({task,transition_seq:task.version}),{code:'GAME_ADMISSION_FENCE_CONFLICT'});
  assert.equal(f.manager.tasks.active().task_id,task.task_id); assert.equal(f.manager.tasks.recovery(task.task_id).status,'conflict');
});

test('host restart gives a legacy missing record one fresh reconciliation without clearing it', async t => {
  const {f,next,task}=await interruptedFixture(t);
  const {operation}=await ledgerReply(f,next,task,{task_id:task.task_id,status:'missing',task:null});
  await until(()=>f.manager.operation(operation.operation_id).state==='succeeded');
  assert.equal(f.manager.tasks.recovery(task.task_id).status,'missing');
  await f.restartHost();assert.equal(f.manager.tasks.recovery(task.task_id).status,'required');
  assert.equal(f.manager.tasks.active().task_id,task.task_id);assert.deepEqual(f.manager.tasks.raw(task.task_id),task);
});

test('a previously confirmed native acceptance cannot be cleared by an absence proof', async t => {
  const {f,next,task}=await interruptedFixture(t);f.manager.tasks.update({task,transition_seq:task.version});
  await ledgerReply(f,next,task,{task_id:task.task_id,status:'missing',task:null,admission_fence:absenceProof(f,task)});
  await until(()=>!f.manager.state.connected);assert.equal(f.manager.tasks.recovery(task.task_id).status,'conflict');
  assert.equal(f.manager.tasks.active().task_id,task.task_id);
});

test('legacy host-created terminal projections recover the last B version and retain an audit record', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect(); await game.auto();
  const task = (await f.api('/tasks', game.request())).value;
  f.manager.store.put('task', { ...task, version: 2, state: 'failed', reason: 'INTERRUPTED_HOST_RESTART', effect_status: 'unknown' });
  await f.restartHost(); const restored = f.manager.tasks.get(task.task_id);
  assert.equal(restored.version, 1); assert.equal(restored.state, 'accepted'); assert.equal(restored.recovery.status, 'required');
  assert.equal(f.manager.store.get("SELECT count(*) n FROM audit WHERE action='repair_legacy_host_projection'").n, 1);
});
