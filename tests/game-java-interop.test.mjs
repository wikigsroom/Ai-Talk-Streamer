import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { join } from 'node:path';
import { once } from 'node:events';
import { DatabaseSync } from 'node:sqlite';
import { gameFixture, until } from './game-fixture.mjs';
import { historyContext } from './game-history-fixture.mjs';

function journalView(folder) {
  const db = new DatabaseSync(join(folder, 'b-ledger/mc-control.sqlite3'), { readOnly: true });
  try {
    return { tasks: db.prepare('SELECT task_id,task FROM tasks').all().map(r => ({ task_id: r.task_id, task: JSON.parse(r.task) })),
      outbox: db.prepare('SELECT boot,world,stream,delivery_seq,type,payload FROM reliable WHERE acked_at IS NULL AND archived_at IS NULL').all(),
      archived: db.prepare('SELECT boot,world,stream,delivery_seq,archive_reason FROM reliable WHERE archived_at IS NOT NULL').all() };
  } finally { db.close(); }
}

function explain(f, taskId, error, javaStats = null) {
  let ledger;
  try { ledger = journalView(f.folder); }
  catch (readError) { ledger = { read_error: readError.code }; }
  return new Error(error.message + ': ' + JSON.stringify({ host: f.manager.state.view(),
    health: f.manager.healthView(),
    task: taskId ? f.manager.tasks.get(taskId) : null, ledger, java_stderr: f.errors.join('').slice(-3000),
    java_output: f.lines.slice(-12), java_stats: javaStats }), { cause: error });
}
async function taskState(f, taskId, state, timeout = 8000) {
  try { return await until(() => f.manager.tasks.get(taskId).state === state, timeout); }
  catch (error) {
    let stats; try { stats = await f.stats(); } catch (probe) { stats = { probe_error: probe.code || probe.name }; }
    throw explain(f, taskId, error, stats);
  }
}
async function javaFixture(t, options = {}) {
  assert.ok(process.env.MC_JAVA_TEST_CLASSPATH, 'MC_JAVA_TEST_CLASSPATH must name compiled core/test classes and locked dependencies');
  const began = Date.now(), phase = label => t.diagnostic(label + ' at ' + (Date.now() - began) + 'ms');
  const fixture = await gameFixture(options); fixture.manager.start();
  phase('A fixture prepared');
  const lines = [], errors = []; let exited = false, child, output;
  const start = () => {
    exited = false;
    child = spawn(process.env.MC_TEST_JAVA || 'java', ['-Xmx128m', '-cp', process.env.MC_JAVA_TEST_CLASSPATH,
      'dev.aitalkstreamer.mc.core.HeadlessBridge', fixture.base.replace('http:', 'ws:') + '/api/dsh/game/bridge', join(fixture.folder, 'b-ledger'),
      ...(options.noExecutor ? ['no-executor'] : [])],
      { cwd: process.cwd(), stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
    const current = child;
    output = createInterface({ input: child.stdout }); output.on('line', line => lines.push(line));
    child.stderr.on('data', bytes => errors.push(String(bytes))); child.on('exit', () => { if (child === current) exited = true; });
    child.on('error', error => { errors.push(String(error)); if (child === current) exited = true; });
  };
  const stats = async () => {
    if (exited) throw new Error('Java fixture already exited');
    const from = lines.length; child.stdin.write('stats\n');
    return until(() => {
      const line = lines.slice(from).find(l => l.startsWith('{')); return line ? JSON.parse(line) : null;
    });
  };
  t.after(async () => {
    phase('B cleanup begins');
    if (child && !exited) {
      let timer;
      child.stdin.end('quit\n');
      try { await Promise.race([once(child, 'exit'), new Promise(r => { timer = setTimeout(r, 6000); })]); }
      finally { clearTimeout(timer); }
    }
    if (child && !exited) { child.kill(); await once(child, 'exit'); }
    output?.close(); phase('B process closed'); await fixture.close(); phase('A fixture closed');
  });
  if (options.beforeBridgeStart) await options.beforeBridgeStart(fixture.folder);
  start();
  await until(() => {
    if (exited) throw new Error('Java fixture exited: ' + errors.join(''));
    const state = fixture.manager.state.view();
    return state.freshness === 'fresh' && state.inputs_released === true && state.mode === 'PAUSED';
  }, 12000).catch(async error => {
    // Diagnose only after the original readiness deadline has failed. This probe
    // never turns a late connection into a passing setup or extends that limit.
    let javaStats;
    try { javaStats = await stats(); }
    catch (probe) { javaStats = { probe_error: probe.code || probe.name }; }
    throw explain({ ...fixture, errors, lines }, null, error, javaStats);
  });
  phase('B fresh snapshot and initial input release confirmed');
  return { ...fixture, get manager() { return fixture.manager; }, get child() { return child; }, lines, errors,
    async restartBridge({ beforeStart } = {}) {
      const oldBoot = fixture.manager.state.value.bridge_boot_id;
      if (!exited) { const ended = once(child, 'exit'); child.kill(); await ended; }
      output.close(); if (beforeStart) await beforeStart(fixture.folder); start();
      await until(() => fixture.manager.state.view().freshness === 'fresh' && fixture.manager.state.value.bridge_boot_id !== oldBoot, 15000);
      phase('B restarted with fresh snapshot');
    },
    async auto(id = 'interop-auto') {
      const state = fixture.manager.state.view();
      const response = await fixture.api('/control', { request_id: id, target_mode: 'AUTO', reason: 'explicit_protocol_fixture',
        bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id, expected_control_epoch: state.control_epoch });
      assert.equal(response.status, 202, JSON.stringify(response));
      await until(() => fixture.manager.operation(response.value.operation_id).state !== 'pending', 7000);
      assert.equal(fixture.manager.operation(response.value.operation_id).state, 'succeeded', JSON.stringify(fixture.manager.operation(response.value.operation_id)));
      await until(() => fixture.manager.state.view().automation_ready, 5000);
      phase('AUTO confirmed');
    },
    request(id) { const state = fixture.manager.state.view(); return { request_id: id, bridge_boot_id: state.bridge_boot_id,
      world_session_id: state.world_session_id, expected_control_epoch: state.control_epoch, based_on_seq: state.seq,
      accept_within_ms: 1500, max_duration_ms: 10000, goal: { skill: 'use_item', item_id: 'minecraft:bread', purpose: 'eat' } }; },
    stats
  };
}

async function registeredHomeFixture(t) {
  const f = await javaFixture(t), state = f.manager.state.view();
  const registered = await f.api('/worlds/' + state.world_id + '/bases', { request_id: 'interop-register-home',
    bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id,
    expected_world_revision: f.manager.worlds.get(state.world_id).revision, label: 'TEST_FIXTURE_ONLY home', radius: 2 });
  assert.equal(registered.status, 201, JSON.stringify(registered));
  f.child.stdin.write('move-fixture-player\n'); await until(() => f.manager.state.value.player?.position?.x === 12, 5000);
  const goal = { skill: 'return_base', base_id: registered.value.base_id };
  return { f, goal, base: registered.value };
}

test('an expired admission is durably failed without stopping AUTO or scheduling an input', {timeout:90000}, async t => {
  const f=await javaFixture(t); await f.auto(); const stale={...f.request('expired-admission'),accept_within_ms:250};
  await new Promise(resolve=>setTimeout(resolve,450));
  const response=await f.api('/tasks',stale); assert.equal(response.status,202,JSON.stringify(response));
  await taskState(f,response.value.task_id,'failed'); const rejected=f.manager.tasks.get(response.value.task_id);
  assert.equal(rejected.version,2); assert.equal(rejected.reason,'GAME_OBSERVATION_EXPIRED');
  assert.equal(rejected.effect_status,'unknown'); assert.deepEqual(rejected.evidence,[]);
  assert.equal(f.manager.state.value.mode,'AUTO'); assert.equal((await f.stats()).effects,0);
  assert(!f.lines.some(line=>line==='FIXTURE_PORT_STARTED '+response.value.task_id));
  const fresh=await f.api('/tasks',f.request('fresh-after-expired')); assert.equal(fresh.status,202,JSON.stringify(fresh));
  await taskState(f,fresh.value.task_id,'running'); await until(()=>f.lines.includes('FIXTURE_PORT_STARTED '+fresh.value.task_id));
  f.child.stdin.write('complete\n'); await taskState(f,fresh.value.task_id,'succeeded');
  assert.equal((await f.stats()).effects,1);
  const duplicate=await f.api('/tasks',stale); assert.equal(duplicate.value.task_id,rejected.task_id); assert.equal((await f.stats()).effects,1);
});

test('compiled Java fences an undispatched host request before a fresh AUTO handshake and blocks its delayed arrival', {timeout:90000}, async t => {
  const f=await javaFixture(t); await f.auto();
  const send=f.manager.send.bind(f.manager); let dropped;
  f.manager.send=(type,payload)=>{ if(type==='task_start'&&!dropped){dropped=structuredClone(payload);return;} return send(type,payload); };
  const response=await f.api('/tasks',f.request('undispatched-host-request')); assert.equal(response.status,202); assert(dropped);
  f.manager.send=send;
  const stopped=await f.api('/control',{request_id:'pause-before-absence-check',target_mode:'PAUSED',reason:'PROTOCOL_FIXTURE_ONLY'});
  assert.equal(stopped.status,202); await until(()=>f.manager.state.value.mode==='PAUSED'&&f.manager.state.value.inputs_released);
  const checked=await f.api('/tasks/'+response.value.task_id+'/reconcile',{request_id:'native-absence-check'}); assert.equal(checked.status,202,JSON.stringify(checked));
  await until(()=>f.manager.operation(checked.value.operation_id).state==='succeeded');
  const task=f.manager.tasks.get(response.value.task_id); assert.equal(task.recovery.status,'not_admitted');
  assert.equal(task.recovery.admission_fence.game_instance_id,task.game_instance_id);
  assert.equal(task.state,'accepted'); assert.equal(task.effect_status,'unknown'); assert.equal(f.manager.tasks.active(),null);
  assert.equal(journalView(f.folder).tasks.length,0); assert.equal((await f.stats()).effects,0);
  await importNativeHistory(f,'absence-guard-history'); assert.equal(f.manager.history.page({kind:'retired_tasks'}).items.length,0);
  await f.auto('new-handshake-after-native-fence'); send('task_start',dropped);
  await until(()=>f.manager.state.value.mode==='PAUSED'||!f.manager.state.connected,8000);
  assert.equal((await f.stats()).effects,0); assert.equal(journalView(f.folder).tasks.length,0);
});

test('late input binding renegotiates the existing bridge and world without authorizing AUTO', { timeout: 90000 }, async t => {
  const f = await javaFixture(t, { noExecutor: true }), before = f.manager.state.view();
  assert.equal(f.manager.capabilities.features.local_takeover, false);
  f.child.stdin.write('bind-executor\n');
  await until(() => {
    const state = f.manager.state.view();
    return state.freshness === 'fresh' && state.connection_generation > before.connection_generation
      && f.manager.capabilities.features.local_takeover && state.inputs_released;
  }, 12000);
  const after = f.manager.state.view();
  assert.equal(after.bridge_boot_id, before.bridge_boot_id); assert.equal(after.world_session_id, before.world_session_id);
  assert.equal(after.mode, 'PAUSED'); assert.equal(after.automation_ready, false);
  assert(after.control_epoch > before.control_epoch); assert.equal((await f.stats()).effects, 0);
  await f.auto('explicit-auto-after-binding'); assert.equal((await f.stats()).effects, 0);
});

test('capability loss revokes active work before renegotiation and never replays a late effect', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto('auto-before-capability-loss');
  const response = await f.api('/tasks', f.request('active-during-capability-loss'));
  assert.equal(response.status, 202); await taskState(f, response.value.task_id, 'running');
  await until(() => f.lines.includes('FIXTURE_PORT_STARTED ' + response.value.task_id));
  const before = f.manager.state.view(); f.child.stdin.write('unbind-executor\n');
  await until(() => {
    const state = f.manager.state.view();
    return state.freshness === 'fresh' && state.connection_generation > before.connection_generation
      && !f.manager.capabilities.features.local_takeover && state.mode === 'PAUSED' && state.inputs_released;
  }, 12000);
  await taskState(f, response.value.task_id, 'cancelled');
  const task = f.manager.tasks.get(response.value.task_id);
  assert.equal(task.reason, 'GAME_CAPABILITIES_CHANGED'); assert.equal(task.effect_status, 'unknown');
  f.child.stdin.write('complete\n'); const stats = await f.stats();
  assert.equal(stats.effects, 0); assert.equal(stats.active_fixture_effect, false);
  assert.equal(stats.fault, null); assert.equal(f.manager.state.view().automation_ready, false);
  assert.equal(f.manager.state.view().bridge_boot_id, before.bridge_boot_id);
  assert.equal(f.manager.state.view().world_session_id, before.world_session_id);
  const durable = journalView(f.folder).tasks.find(row => row.task_id === response.value.task_id).task;
  assert.equal(durable.state, 'cancelled'); assert.equal(durable.reason, 'GAME_CAPABILITIES_CHANGED');
});

test('B refuses AUTO with no bound input adapter even if the host inflates its capabilities', { timeout: 90000 }, async t => {
  const f = await javaFixture(t, { noExecutor: true });
  assert.equal(f.manager.capabilities.features.local_takeover, false);
  // Deliberately exercise the client boundary against a mistaken host, beyond the host's own guard.
  f.manager.capabilities.features.local_takeover = true;
  f.manager.capabilities.features.cancel_all = true;
  const state = f.manager.state.view();
  const response = await f.api('/control', { request_id: 'interop-no-input-adapter', target_mode: 'AUTO', reason: 'explicit_protocol_fixture',
    bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id, expected_control_epoch: state.control_epoch });
  assert.equal(response.status, 202, JSON.stringify(response));
  await until(() => f.manager.operation(response.value.operation_id).state !== 'pending', 8000);
  const operation = f.manager.operation(response.value.operation_id);
  assert.equal(operation.state, 'failed', JSON.stringify(operation));
  assert.equal(operation.error, 'GAME_EXECUTOR_ADAPTER_NOT_BOUND');
  assert.equal(f.manager.state.value.mode, 'PAUSED');
  assert.equal(f.manager.state.value.control_epoch, state.control_epoch);
  assert.equal((await f.stats()).effects, 0);
});

test('B Java raw frame upload reaches production storage without a vision model', { timeout: 90000 }, async t => {
  const f = await javaFixture(t), state = f.manager.state.view();
  assert.equal(f.manager.vision.available(), false);
  assert.equal((await f.api('/config', { expected_revision: 0, patch: { vision: { enabled: true } } })).status, 200);
  const response = await f.api('/queries', { request_id: 'interop-raw-frame', bridge_boot_id: state.bridge_boot_id,
    world_session_id: state.world_session_id, kind: 'frame', params: {} });
  assert.equal(response.status, 202, JSON.stringify(response));
  await until(() => f.manager.operation(response.value.operation_id).state !== 'pending', 8000);
  const operation = f.manager.operation(response.value.operation_id);
  assert.equal(operation.state, 'succeeded', JSON.stringify(operation));
  assert.equal(operation.result.kind, 'frame'); assert.equal(operation.result.width, 32); assert.equal(operation.result.height, 18);
  const frame = await fetch(f.base + '/api/dsh/game/frames/' + operation.result.frame_id);
  assert.equal(frame.status, 200); assert.ok((await frame.arrayBuffer()).byteLength > 0);
  assert.equal(operation.result.model_id, undefined); assert.equal((await f.stats()).effects, 0);
});

async function nativeMaintenanceFixture(t, folder, action) {
  const child = spawn(process.env.MC_TEST_JAVA || 'java', ['-Xmx128m', '-cp', process.env.MC_JAVA_TEST_CLASSPATH,
    'dev.aitalkstreamer.mc.core.MaintenanceHistoryFixture', join(folder, 'b-ledger'), action],
    { cwd: process.cwd(), stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
  let stdout = '', stderr = '', timedOut = false;
  child.stdout.on('data', bytes => { stdout += bytes; }); child.stderr.on('data', bytes => { stderr += bytes; });
  const timeout = setTimeout(() => { timedOut = true; child.kill(); }, 20000);
  let code;
  try { [code] = await once(child, 'exit'); } finally { clearTimeout(timeout); }
  t.diagnostic('native journal fixture ' + action + ': ' + stdout.trim());
  assert.equal(timedOut, false, stderr); assert.equal(code, 0, stderr);
  return JSON.parse(stdout.trim().split('\n').at(-1));
}

async function importNativeHistory(f, id) {
  const admission = () => {
    const state = f.manager.state.view();
    return { freshness: state.freshness, mode: state.mode, inputs_released: state.inputs_released,
      active_task_id: f.manager.tasks.active()?.task_id ?? null, bridge_boot_id: state.bridge_boot_id,
      world_session_id: state.world_session_id, seq: state.seq };
  };
  // A new bridge can publish its first snapshot before its initial input release.
  // Wait for the real import preconditions, then submit once; never retry a refusal.
  await until(() => {
    const state = admission();
    return state.freshness === 'fresh' && state.mode !== 'AUTO' && state.inputs_released === true && state.active_task_id === null;
  }).catch(error => { throw explain(f, null, error); });
  const before = admission(), result = await f.api('/history/imports', historyContext(f, id));
  assert.equal(result.status, 202, JSON.stringify({ result, admission_before_request: before, admission_after_response: admission() }));
  await until(() => !f.manager.history.job, 12000);
  const status = f.manager.history.status(); assert.equal(status.latest_import.state, 'completed', JSON.stringify(status)); return status;
}

test('compiled Java retention records reach the operator API after an actual offline SQLite maintenance commit', { timeout: 90000 }, async t => {
  const f = await javaFixture(t, { beforeBridgeStart: folder => nativeMaintenanceFixture(t, folder, '1') });
  const before = await f.stats(); assert.equal(f.manager.capabilities.features.journal_maintenance_history, true);
  const imported = await importNativeHistory(f, 'native-maintenance-first'); assert.equal(imported.totals.records, 4);
  assert.deepEqual(imported.latest_import.source_order, ['reliable', 'task_versions', 'retention_summaries', 'retired_tasks', 'retention_runs']);
  for (const [source, count] of [['retention_summaries', 2], ['retired_tasks', 1], ['retention_runs', 1]]) {
    const page = await f.api('/history/entries?kind=' + source); assert.equal(page.status, 200); assert.equal(page.value.items.length, count);
  }
  const retired = f.manager.history.page({ kind: 'retired_tasks' }).items[0];
  assert.equal(retired.metadata.source_boot_id, 'old-maintenance-boot-1'); assert.equal(retired.metadata.world_session_id, 'old-maintenance-world');
  assert.equal(f.manager.tasks.page().items.length, 0); assert.equal((await f.stats()).effects, before.effects);
  const repeated = await importNativeHistory(f, 'native-maintenance-repeat');
  assert.equal(repeated.totals.records, 4); assert.equal(repeated.latest_import.duplicate_records, 4);
});

test('compiled Java later maintenance creates summary versions while stable retired proofs and runs deduplicate', { timeout: 90000 }, async t => {
  const f = await javaFixture(t, { beforeBridgeStart: folder => nativeMaintenanceFixture(t, folder, '1') });
  await importNativeHistory(f, 'native-maintenance-v1');
  await f.restartBridge({ beforeStart: folder => nativeMaintenanceFixture(t, folder, '2') });
  const imported = await importNativeHistory(f, 'native-maintenance-v2'); assert.equal(imported.totals.records, 8);
  assert.equal(imported.latest_import.duplicate_records, 2);
  const values = f.manager.history.page({ kind: 'retention_summaries' }).items;
  assert.deepEqual(values.map(v => v.summary.count).sort(), [1, 1, 2, 2]);
  assert.equal(f.manager.history.page({ kind: 'retired_tasks' }).items.length, 2);
  assert.equal(f.manager.history.page({ kind: 'retention_runs' }).items.length, 2);
  assert.equal((await f.stats()).effects, 0); assert.equal(f.manager.state.value.mode, 'PAUSED');
});

test('compiled Java old-backup restore preserves retired proof and A keeps previously observed summaries as history', { timeout: 90000 }, async t => {
  const f = await javaFixture(t, { beforeBridgeStart: folder => nativeMaintenanceFixture(t, folder, '1') });
  await importNativeHistory(f, 'native-maintenance-before-restore');
  await f.restartBridge({ beforeStart: folder => nativeMaintenanceFixture(t, folder, 'restore') });
  const imported = await importNativeHistory(f, 'native-maintenance-after-restore');
  assert.equal(imported.totals.records, 5); assert.equal(imported.latest_import.duplicate_records, 1);
  assert.equal(f.manager.history.page({ kind: 'retention_summaries' }).items.length, 2);
  assert.equal(f.manager.history.page({ kind: 'retired_tasks' }).items.length, 1);
  const db = new DatabaseSync(join(f.folder, 'b-ledger/mc-control.sqlite3'), { readOnly: true });
  try {
    assert.equal(db.prepare('SELECT count(*) n FROM journal_summaries').get().n, 0);
    assert.equal(db.prepare('SELECT count(*) n FROM journal_retention_runs').get().n, 0);
    assert.equal(db.prepare('SELECT count(*) n FROM journal_retired_tasks').get().n, 1);
    assert.equal(db.prepare('SELECT count(*) n FROM tasks').get().n, 0);
  } finally { db.close(); }
  assert.equal((await f.stats()).effects, 0); assert.equal(f.manager.state.value.mode, 'PAUSED');
});

test('compiled Java journal projects every original task version and ACKed delivery across worlds without repeating effects', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto('history-java-auto');
  const created = await f.api('/tasks', f.request('history-java-task')); assert.equal(created.status, 202, JSON.stringify(created));
  await taskState(f, created.value.task_id, 'running'); f.child.stdin.write('complete\n');
  await taskState(f, created.value.task_id, 'succeeded');
  const oldWorld = f.manager.state.value.world_session_id, effects = (await f.stats()).effects;
  f.child.stdin.write('next-world\n');
  await until(() => f.manager.state.view().freshness === 'fresh' && f.manager.state.value.world_session_id !== oldWorld && f.manager.state.value.inputs_released, 8000);
  assert.equal(f.manager.capabilities.features.journal_history, true);
  const current = f.manager.tasks.get(created.value.task_id), receipt = f.manager.store.all('SELECT * FROM stream_receipts');
  const start = await f.api('/history/imports', historyContext(f, 'history-java-import')); assert.equal(start.status, 202, JSON.stringify(start));
  await until(() => !f.manager.history.job, 12000);
  assert.equal(f.manager.history.status().latest_import.state, 'completed', JSON.stringify(f.manager.history.status()));
  const deliveries = (await f.api('/history/entries?kind=task_deliveries')).value.items;
  const versions = (await f.api('/history/entries?kind=task_versions')).value.items;
  assert.deepEqual(versions.filter(v => v.summary.task_id === current.task_id).map(v => v.summary.version).sort(), [1, 2, 3]);
  assert.ok(deliveries.some(v => v.metadata.acked_at !== null));
  assert.ok(deliveries.every(v => v.metadata.world_session_id === oldWorld));
  assert.deepEqual(f.manager.tasks.get(current.task_id), current); assert.deepEqual(f.manager.store.all('SELECT * FROM stream_receipts'), receipt);
  assert.equal((await f.stats()).effects, effects); assert.equal(f.manager.state.value.mode, 'PAUSED');
  const total = f.manager.history.totals().records;
  assert.equal((await f.api('/history/imports', historyContext(f, 'history-java-repeat'))).status, 202);
  await until(() => !f.manager.history.job, 12000);
  assert.equal(f.manager.history.totals().records, total); assert.equal(f.manager.history.status().latest_import.duplicate_records, total);
});

test('compiled Java history query completes an empty journal in PAUSED without touching task recovery or control', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); const before = await f.stats();
  assert.equal((await f.api('/history/imports', historyContext(f, 'history-java-empty'))).status, 202);
  await until(() => !f.manager.history.job, 12000);
  assert.equal(f.manager.history.status().latest_import.state, 'completed'); assert.equal(f.manager.history.totals().records, 0);
  assert.equal((await f.stats()).effects, before.effects); assert.equal(f.manager.state.value.mode, 'PAUSED');
});

for (const [purpose, item] of [['eat', 'minecraft:bread'], ['equip', 'minecraft:iron_helmet'], ['activate', 'minecraft:cobblestone']]) {
  test('compiled Java item-use session persists a bound ' + purpose + ' receipt after a later observation', { timeout: 90000 }, async t => {
    const f = await javaFixture(t); await f.auto();
    const request = { ...f.request('item-' + purpose), goal: { skill: 'use_item', item_id: item, purpose } };
    const created = await f.api('/tasks', request); assert.equal(created.status, 202);
    await until(() => f.lines.includes('FIXTURE_PORT_STARTED ' + created.value.task_id));
    f.child.stdin.write('complete\n'); await taskState(f, created.value.task_id, 'succeeded');
    const task = f.manager.tasks.get(created.value.task_id); assert.equal(task.effect_status, 'verified');
    assert.equal(task.evidence[0].kind, 'item_effect'); assert.ok(task.evidence[0].seq > request.based_on_seq);
    assert.match(task.evidence[0].summary, new RegExp('purpose ' + purpose));
    assert.equal(journalView(f.folder).tasks.find(v => v.task_id === task.task_id).task.effect_status, 'verified');
    const replay = await f.api('/tasks', request); assert.equal(replay.status, 200); assert.equal(replay.value.task_id, task.task_id);
    assert.equal((await f.stats()).effects, 1);
  });
}

test('compiled Java rejects a predicted item effect that has no bound receipt', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); f.child.stdin.write('omit-item-receipt\n'); await until(() => f.lines.includes('FIXTURE_OMIT_ITEM_RECEIPT'));
  await f.auto(); const created = await f.api('/tasks', f.request('item-no-receipt')); assert.equal(created.status, 202);
  await until(() => f.lines.includes('FIXTURE_PORT_STARTED ' + created.value.task_id));
  f.child.stdin.write('complete\n'); await taskState(f, created.value.task_id, 'failed');
  assert.equal(f.manager.tasks.get(created.value.task_id).effect_status, 'unknown'); assert.equal((await f.stats()).effects, 1);
});

test('compiled Java cancellation retains the confirmed item effect without repeating it', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); f.child.stdin.write('hold-item-after-effect\n'); await until(() => f.lines.includes('FIXTURE_HOLD_ITEM_AFTER_EFFECT'));
  await f.auto(); const created = await f.api('/tasks', f.request('item-partial-cancel')); assert.equal(created.status, 202);
  await until(() => f.lines.includes('FIXTURE_PORT_STARTED ' + created.value.task_id)); f.child.stdin.write('complete\n');
  await until(() => f.lines.includes('FIXTURE_SYNTHETIC_ITEM_EFFECT'));
  const response = await f.api('/tasks/' + created.value.task_id + '/cancel', { request_id: 'item-cancel', reason: 'fixture' }); assert.equal(response.status, 202);
  await taskState(f, created.value.task_id, 'cancelled'); assert.equal(f.manager.tasks.get(created.value.task_id).effect_status, 'partial');
  f.child.stdin.write('complete\n'); assert.equal((await f.stats()).effects, 1); assert.equal((await f.stats()).inputs_released, true);
});

test('compiled Java craft result retains rounded batches and durable evidence after a newer inventory observation', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto();
  const request = { ...f.request('craft-fixture-confirmed'), goal: { skill: 'craft', item_id: 'minecraft:oak_planks', count: 5 } };
  const created = await f.api('/tasks', request); assert.equal(created.status, 202);
  const id = created.value.task_id; await taskState(f, id, 'succeeded');
  const task = f.manager.tasks.get(id); assert.equal(task.effect_status, 'verified'); assert.equal(task.goal.count, 5);
  assert.equal(task.evidence[0].kind, 'craft_result'); assert.match(task.evidence[0].summary, /8 produced units/);
  assert.ok(task.evidence[0].seq > request.based_on_seq); assert.equal((await f.stats()).effects, 1);
  const durable = journalView(f.folder).tasks.find(row => row.task_id === id).task;
  assert.equal(durable.effect_status, 'verified'); assert.equal(durable.evidence[0].kind, 'craft_result');
});

test('compiled Java refuses to turn an inventory increase without a crafting receipt into success', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); f.child.stdin.write('omit-craft-receipt\n'); await until(() => f.lines.includes('FIXTURE_OMIT_CRAFT_RECEIPT'));
  await f.auto(); const created = await f.api('/tasks', { ...f.request('craft-fixture-no-receipt'), goal: { skill: 'craft', item_id: 'minecraft:oak_planks', count: 5 } });
  assert.equal(created.status, 202); await taskState(f, created.value.task_id, 'failed');
  const task = f.manager.tasks.get(created.value.task_id); assert.equal(task.effect_status, 'unknown');
  assert.equal(task.evidence[0].kind, 'inventory'); assert.match(task.evidence[0].summary, /does not prove crafting/);
});

test('compiled Java cancellation preserves partial crafting evidence and prevents another fixture batch', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); f.child.stdin.write('hold-craft-after-batch\n'); await until(() => f.lines.includes('FIXTURE_HOLD_CRAFT_AFTER_BATCH'));
  await f.auto(); const created = await f.api('/tasks', { ...f.request('craft-fixture-cancel'), goal: { skill: 'craft', item_id: 'minecraft:oak_planks', count: 5 } });
  assert.equal(created.status, 202); await until(() => f.lines.includes('FIXTURE_SYNTHETIC_CRAFT_BATCHES 1'));
  const cancelled = await f.api('/tasks/' + created.value.task_id + '/cancel', { request_id: 'craft-fixture-cancel-op', reason: 'fixture_operator_cancel' });
  assert.equal(cancelled.status, 202); await taskState(f, created.value.task_id, 'cancelled');
  const task = f.manager.tasks.get(created.value.task_id); assert.equal(task.effect_status, 'partial');
  assert.equal(task.evidence[0].kind, 'craft_result'); assert.match(task.evidence[0].summary, /4 produced units/);
  assert.equal((await f.stats()).effects, 1); assert.equal((await f.stats()).inputs_released, true);
});

for (const [mode, reason, effect, effects] of [
  ['missing', 'GAME_RESOURCE_MATERIAL_UNAVAILABLE', 'unknown', 0],
  ['cycle', 'GAME_RESOURCE_MATERIAL_CYCLE', 'unknown', 0],
  ['smelting', 'GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE', 'unknown', 0],
  ['partial', 'GAME_CRAFT_SERVER_DIVERGED', 'partial', 1],
  ['startup', 'GAME_MATERIAL_RESERVATION_LIMIT', 'unknown', 0],
  ['unknown', 'GAME_EXECUTOR_FAILED', 'unknown', 0]
]) test('compiled Java craft failure ' + mode + ' retains its durable reason, effects and no replay after reconnect', { timeout: 90000 }, async t => {
  const f = await javaFixture(t);f.child.stdin.write('craft-failure ' + mode + '\n');
  await until(() => f.lines.includes('FIXTURE_CRAFT_FAILURE ' + mode));await f.auto();
  const response = await f.api('/tasks', { ...f.request('craft-failure-' + mode), goal: { skill: 'craft', item_id: 'minecraft:oak_planks', count: 5 } });
  assert.equal(response.status, 202);const id = response.value.task_id;await taskState(f, id, 'failed');
  const task = f.manager.tasks.get(id);assert.equal(task.reason, reason);assert.equal(task.effect_status, effect);
  if (mode === 'partial') {assert.equal(task.evidence[0].kind, 'craft_result');assert.match(task.evidence[0].summary, /4 produced units/);}
  assert.equal((await f.stats()).effects, effects);assert.equal((await f.stats()).inputs_released, true);
  const durable = journalView(f.folder).tasks.find(row => row.task_id === id).task;
  assert.equal(durable.reason, reason);assert.equal(durable.effect_status, effect);assert.deepEqual(durable.evidence, task.evidence);
  assert(!JSON.stringify(task).includes('PRIVATE_FIXTURE_MESSAGE'));const version = task.version;
  await f.restartBridge();await until(() => f.manager.state.value.mode === 'PAUSED' && f.manager.state.value.inputs_released);
  const beforeCheck = f.manager.tasks.get(id);t.diagnostic(JSON.stringify({ task_id: id, reason: beforeCheck.reason, recovery: beforeCheck.recovery?.status || null, phase: 'before_explicit_terminal_ledger_query' }));
  const query = await f.api('/tasks/' + id + '/reconcile', { request_id: 'craft-failure-query-' + mode });
  assert.equal(query.status, 202, JSON.stringify(query));await until(() => f.manager.operation(query.value.operation_id).state !== 'pending');
  assert.equal(f.manager.operation(query.value.operation_id).state, 'succeeded', JSON.stringify(f.manager.operation(query.value.operation_id)));
  assert.equal(f.manager.tasks.get(id).recovery.status, 'verified');
  const restored = f.manager.tasks.get(id);assert.equal(restored.reason, reason);assert.equal(restored.version, version);assert.equal(restored.effect_status, effect);
  assert.equal((await f.stats()).effects, effects);assert.deepEqual(restored.evidence, task.evidence);
});

test('compiled Java validates A registered base preflight, later synthetic arrival and unchanged durable recovery', { timeout: 90000 }, async t => {
  const { f, goal, base } = await registeredHomeFixture(t); const state = f.manager.state.view();
  const query = await f.api('/queries', { request_id: 'interop-check-home', bridge_boot_id: state.bridge_boot_id,
    world_session_id: state.world_session_id, kind: 'check_action', params: { goal } });
  assert.equal(query.status, 202, JSON.stringify(query));
  await until(() => f.manager.operation(query.value.operation_id).state !== 'pending', 8000);
  const checked = f.manager.operation(query.value.operation_id); assert.equal(checked.state, 'succeeded', JSON.stringify(checked));
  assert.deepEqual(checked.result.base_target.position, base.position); assert.equal((await f.stats()).effects, 0);
  await f.auto(); const request = { ...f.request('interop-return-home'), goal,
    base_ref: f.manager.worlds.baseReference(checked.result.base_target) };
  const accepted = await f.api('/tasks', request); assert.equal(accepted.status, 202, JSON.stringify(accepted));
  const taskId = accepted.value.task_id; await taskState(f, taskId, 'succeeded'); const task = f.manager.tasks.get(taskId);
  assert.deepEqual(task.base_target, checked.result.base_target); assert.equal(task.evidence[0].kind, 'position');
  assert.ok(task.evidence[0].seq > request.based_on_seq); assert.equal((await f.stats()).effects, 1);
  const paused = await f.api('/control', { request_id: 'interop-home-stop', target_mode: 'PAUSED', reason: 'fixture_receipt_barrier' });
  await until(() => f.manager.operation(paused.value.operation_id).state === 'succeeded', 6000);
  const reconcile = await f.api('/tasks/' + taskId + '/reconcile', { request_id: 'interop-home-proof' });
  await until(() => f.manager.operation(reconcile.value.operation_id).state !== 'pending', 8000);
  assert.equal(f.manager.operation(reconcile.value.operation_id).state, 'succeeded');
  assert.deepEqual(journalView(f.folder).tasks.find(row => row.task_id === taskId).task.base_target, task.base_target);
  await f.restartBridge(); assert.equal((await f.stats()).effects, 1);
  const replay = await f.api('/tasks', request); assert.equal(replay.status, 200); assert.deepEqual(replay.value.base_target, task.base_target);
  assert.equal(f.manager.state.value.mode, 'PAUSED'); assert.equal((await f.stats()).fault, null);
});

test('compiled Java rejects a duplicate task wire command with changed base coordinates before another fixture effect', { timeout: 90000 }, async t => {
  const { f, goal } = await registeredHomeFixture(t); await f.auto(); const request = { ...f.request('interop-home-no-retarget'), goal };
  const accepted = await f.api('/tasks', request); assert.equal(accepted.status, 202, JSON.stringify(accepted));
  const id = accepted.value.task_id; await taskState(f, id, 'succeeded'); const target = structuredClone(accepted.value.base_target);
  target.position.x++;
  f.manager.send('task_start', { controller_session_id: f.manager.controllerId, lease_id: f.manager.lease.id,
    control_epoch: request.expected_control_epoch, task_id: id, request, base_target: target });
  try { await until(() => f.manager.state.value.mode !== 'AUTO', 6000); }
  catch (error) {
    let stats; try { stats = await f.stats(); } catch (probe) { stats = { probe_error: probe.code || probe.name }; }
    throw explain(f, id, error, stats);
  }
  const stats = await f.stats(); assert.equal(stats.effects, 1); assert.equal(stats.diagnostics.first_stop_since_auto.reason, 'GAME_REQUEST_CONFLICT');
  assert.deepEqual(journalView(f.folder).tasks.find(row => row.task_id === id).task.base_target, accepted.value.base_target);
  assert.equal(f.manager.tasks.get(id).state, 'succeeded'); assert.equal(stats.fault, null);
});

test('compiled Java captures a synthetic frame, uploads JPEG and receives an explicitly mocked vision result', { timeout: 90000 }, async t => {
  let calls = 0;
  const f = await javaFixture(t, { visionProvider: { available: () => true, analyze: async entry => {
    calls++; assert.equal(entry.receipt.width, 32); assert.equal(entry.receipt.height, 18);
    assert.equal(entry.bytes[0], 255); assert.equal(entry.bytes[1], 216);
    return { caption: 'TEST_FIXTURE_ONLY: synthetic pixels', visible_text: [], unknowns: ['This is not a real Minecraft capture'],
      model_id: 'synthetic-fixture', runtime_id: 'synthetic-fixture' };
  } } });
  const configured = await f.api('/config', { expected_revision: 0, patch: { vision: { enabled: true } } });
  assert.equal(configured.status, 200); const state = f.manager.state.view();
  const response = await f.api('/queries', { request_id: 'interop-frame', bridge_boot_id: state.bridge_boot_id,
    world_session_id: state.world_session_id, kind: 'observation', params: { purpose: 'screen' } });
  assert.equal(response.status, 202, JSON.stringify(response)); const id = response.value.operation_id;
  await until(() => f.manager.operation(id).state !== 'pending', 8000);
  const operation = f.manager.operation(id); assert.equal(operation.state, 'succeeded', JSON.stringify(operation));
  assert.equal(calls, 1); assert.equal(operation.result.model_id, 'synthetic-fixture');
  assert.equal((await f.stats()).fault, null); assert.equal(f.manager.state.value.mode, 'PAUSED');
});

// The outer budget includes native process/SQLite preparation and cleanup. Task
// observation waits stay within the fixture's 10s task duration; production
// freshness, admission and lease deadlines keep their original limits.
test('compiled Java bridge and Node host complete two-stage AUTO and one durable task', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); assert.equal(f.manager.capabilities.execution_profile, 'native_core');
  await f.auto(); const request = f.request('interop-effect-once'); const created = await f.api('/tasks', request);
  assert.equal(created.status, 202, JSON.stringify(created)); const taskId = created.value.task_id;
  await taskState(f, taskId, 'running'); f.child.stdin.write('complete\n');
  await taskState(f, taskId, 'succeeded', 8000);
  const duplicate = await f.api('/tasks', request); assert.equal(duplicate.value.task_id, taskId);
  assert.equal((await f.stats()).effects, 1); assert.equal(f.manager.tasks.get(taskId).effect_status, 'verified');
  // Use the ordered protocol as a receipt barrier, then inspect SQLite through
  // a short-lived read-only connection including the committed WAL.
  const paused = await f.api('/control', { request_id: 'interop-receipt-stop', target_mode: 'PAUSED', reason: 'verify_durable_receipts' });
  assert.equal(paused.status, 202, JSON.stringify(paused));
  await until(() => f.manager.operation(paused.value.operation_id).state === 'succeeded', 6000);
  const proof = await f.api('/tasks/' + taskId + '/reconcile', { request_id: 'interop-receipt-proof' });
  assert.equal(proof.status, 202, JSON.stringify(proof));
  await until(() => f.manager.operation(proof.value.operation_id).state === 'succeeded', 8000).catch(async error => {
    const ledger = journalView(f.folder);
    throw new Error(error.message + ': ' + JSON.stringify({ outbox: ledger.outbox, java: await f.stats(), host: f.manager.state.view(),
      receipts: f.manager.store.all('SELECT * FROM stream_receipts') }));
  });
  assert.equal((await f.stats()).fault, null);
  const persisted = journalView(f.folder); assert.equal(persisted.outbox.length, 0);
  assert.equal(persisted.tasks.find(row => row.task_id === taskId).task.state, 'succeeded');
  assert.equal(f.manager.tasks.get(taskId).recovery.status, 'verified');
});

test('A host restart reconciles a running Java task without another effect or AUTO grant', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto(); const created = await f.api('/tasks', f.request('host-restart-task'));
  assert.equal(created.status, 202); const id = created.value.task_id;
  await taskState(f, id, 'running'); const before = f.manager.controllerId;
  await f.restartHost(); assert.notEqual(f.manager.controllerId, before);
  await until(() => f.manager.tasks.get(id).recovery?.status === 'verified', 18000).catch(error => { throw explain(f, id, error); });
  const task = f.manager.tasks.get(id); assert.equal(task.state, 'cancelled'); assert.equal(task.effect_status, 'unknown');
  f.child.stdin.write('complete\n'); assert.equal((await f.stats()).effects, 0);
  assert.equal(f.manager.state.value.mode, 'PAUSED'); assert.equal(f.manager.lease, null);
});

test('a durably accepted task rechecks current facts after a delayed game-thread start', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto();
  f.child.stdin.write('delay-next-execution\n'); await until(() => f.lines.includes('FIXTURE_EXECUTION_DELAY_SET'));
  const created = await f.api('/tasks', f.request('delayed-accepted-task')); assert.equal(created.status, 202, JSON.stringify(created));
  const id = created.value.task_id; await taskState(f, id, 'running', 8000);
  const running = f.manager.tasks.get(id);
  assert.ok(Date.parse(running.updated_at) - Date.parse(running.created_at) >= 1800);
  assert.equal((await f.stats()).effects, 0);
  f.child.stdin.write('complete\n'); await taskState(f, id, 'succeeded', 8000);
  assert.equal((await f.stats()).effects, 1);
});

test('a stalled Java game thread cannot apply a queued old effect after the local permit is revoked', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto();
  const created = await f.api('/tasks', f.request('stalled-client-task')); assert.equal(created.status, 202);
  const id = created.value.task_id; await taskState(f, id, 'running'); const epoch = f.manager.state.view().control_epoch;
  f.child.stdin.write('stall-game-thread\n'); await until(() => f.lines.includes('FIXTURE_GAME_THREAD_STALLED'));
  // The effect is already queued before the watchdog cancellation reaches the client.
  f.child.stdin.write('complete\n');
  await until(() => !f.manager.state.view().automation_ready, 6000);
  f.child.stdin.write('resume-game-thread\n');
  await until(() => f.lines.includes('FIXTURE_GAME_THREAD_RESUMED'));
  await until(() => ['cancelled', 'failed'].includes(f.manager.tasks.get(id).state), 8000);
  await until(() => f.manager.state.view().freshness === 'fresh' && f.manager.state.view().mode === 'PAUSED', 7000);
  const before = await f.stats(); assert.equal(before.effects, 0); assert.equal(before.mode, 'PAUSED');
  assert.equal(before.inputs_released, true); assert.equal(before.active_fixture_effect, false); assert.ok(before.epoch > epoch);
  assert.equal(f.manager.tasks.get(id).effect_status, 'unknown'); assert.equal(before.fault, null);
  await f.auto('auto-after-stall');
  const fresh = await f.api('/tasks', f.request('fresh-after-stall')); assert.equal(fresh.status, 202);
  await taskState(f, fresh.value.task_id, 'running'); f.child.stdin.write('complete\n');
  await taskState(f, fresh.value.task_id, 'succeeded'); assert.equal((await f.stats()).effects, 1);
});

test('a task whose final start is delayed past its duration terminates and cannot cancel the next task', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto();
  f.child.stdin.write('delay-final-start\n'); await until(() => f.lines.includes('FIXTURE_FINAL_START_DELAY_SET'));
  const request = { ...f.request('timeout-before-final-start'), max_duration_ms: 1000 };
  const created = await f.api('/tasks', request); assert.equal(created.status, 202, JSON.stringify(created));
  await taskState(f, created.value.task_id, 'failed', 6000);
  assert.equal(f.manager.tasks.get(created.value.task_id).reason, 'TASK_TIMEOUT'); assert.equal((await f.stats()).effects, 0);
  await until(() => f.manager.state.view().freshness === 'fresh' && f.manager.state.view().automation_ready, 5000);
  const next = await f.api('/tasks', f.request('next-after-timeout')); assert.equal(next.status, 202, JSON.stringify(next));
  await taskState(f, next.value.task_id, 'running');
  await until(() => f.lines.includes('FIXTURE_DELAYED_ACTION_RELEASED'), 5000);
  assert.equal(f.manager.tasks.get(next.value.task_id).state, 'running'); assert.equal((await f.stats()).active_fixture_effect, true);
  f.child.stdin.write('complete\n'); await taskState(f, next.value.task_id, 'succeeded');
  const final = await f.stats(); assert.equal(final.effects, 1); assert.equal(final.fault, null);
});

test('B process crash exposes its durable unknown terminal on the next boot without replay', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto(); const created = await f.api('/tasks', f.request('bridge-crash-task'));
  assert.equal(created.status, 202); const id = created.value.task_id;
  await taskState(f, id, 'running'); const oldTaskBoot = created.value.bridge_boot_id;
  await f.restartBridge(); await until(() => f.manager.tasks.get(id).recovery?.status === 'verified', 16000).catch(error => { throw explain(f, id, error); });
  const task = f.manager.tasks.get(id); assert.equal(task.state, 'failed'); assert.equal(task.reason, 'INTERRUPTED_RESTART');
  assert.equal(task.effect_status, 'unknown'); assert.equal(task.bridge_boot_id, oldTaskBoot);
  assert.notEqual(f.manager.state.value.bridge_boot_id, oldTaskBoot);
  const persisted = journalView(f.folder);
  assert.ok(persisted.archived.some(row => row.boot === oldTaskBoot));
  assert.ok(persisted.outbox.every(row => row.boot !== oldTaskBoot));
  f.child.stdin.write('complete\n'); assert.equal((await f.stats()).effects, 0);
  assert.equal(f.manager.state.value.mode, 'PAUSED'); assert.equal(f.manager.state.value.automation_ready, false);
});

test('world change archives old delivery context and requires a new AUTO grant for a new task', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto();
  const created = await f.api('/tasks', f.request('old-world-task')); assert.equal(created.status, 202, JSON.stringify(created));
  const id = created.value.task_id, oldWorld = created.value.world_session_id, oldBoot = created.value.bridge_boot_id;
  await taskState(f, id, 'running'); f.child.stdin.write('next-world\n');
  await until(() => f.manager.state.view().freshness === 'fresh' && f.manager.state.value.world_session_id !== oldWorld, 12000);
  await until(() => f.manager.tasks.get(id).recovery?.status === 'verified', 12000).catch(error => { throw explain(f, id, error); });
  assert.equal(f.manager.tasks.get(id).state, 'cancelled'); assert.equal(f.manager.tasks.get(id).reason, 'GAME_WORLD_CHANGED');
  assert.equal(f.manager.state.value.bridge_boot_id, oldBoot); assert.equal(f.manager.state.value.mode, 'PAUSED');
  assert.equal((await f.stats()).effects, 0);
  const persisted = journalView(f.folder);
  assert.ok(persisted.archived.some(row => row.world === oldWorld));
  assert.ok(persisted.outbox.every(row => row.world !== oldWorld));
  await f.auto('new-world-auto'); const next = await f.api('/tasks', f.request('new-world-task'));
  assert.equal(next.status, 202, JSON.stringify(next)); await taskState(f, next.value.task_id, 'running');
  f.child.stdin.write('complete\n'); await taskState(f, next.value.task_id, 'succeeded');
  assert.equal((await f.stats()).effects, 1);
});

test('takeover before the first queued execution terminates the accepted task without a port callback', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto(); f.child.stdin.write('hold-next-execution\n');
  await until(() => f.lines.includes('FIXTURE_EXECUTION_HOLD_SET'));
  const accepted = await f.api('/tasks', f.request('takeover-before-first-execution')); assert.equal(accepted.status, 202);
  await until(() => f.lines.includes('FIXTURE_HELD_ACTION_QUEUED'));
  assert.equal(journalView(f.folder).tasks.find(row => row.task_id === accepted.value.task_id)?.task.state, 'accepted');
  f.child.stdin.write('takeover\n'); await taskState(f, accepted.value.task_id, 'cancelled', 6000);
  f.child.stdin.write('release-held-execution\n'); await until(() => f.lines.includes('FIXTURE_HELD_ACTION_RELEASED'));
  const stats = await f.stats(); assert.equal(stats.effects, 0); assert.equal(stats.inputs_released, true);
  assert.equal(stats.mode, 'MANUAL_COMMENTARY'); assert.equal(stats.fault, null);
  assert.equal(f.manager.tasks.get(accepted.value.task_id).reason, 'FIXTURE_PHYSICAL_INPUT');
});

test('takeover between running and final queued start cannot strand the task or cancel its replacement', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto(); f.child.stdin.write('hold-final-start\n');
  await until(() => f.lines.includes('FIXTURE_FINAL_START_HOLD_SET'));
  const accepted = await f.api('/tasks', f.request('takeover-before-final-start')); assert.equal(accepted.status, 202);
  await until(() => f.lines.includes('FIXTURE_HELD_ACTION_QUEUED'));
  await taskState(f, accepted.value.task_id, 'running'); f.child.stdin.write('takeover\n');
  await taskState(f, accepted.value.task_id, 'cancelled', 6000);
  await until(() => f.manager.state.value.mode === 'MANUAL_COMMENTARY'); await f.auto('auto-after-queued-takeover');
  const next = await f.api('/tasks', f.request('replacement-after-queued-takeover')); assert.equal(next.status, 202);
  await taskState(f, next.value.task_id, 'running'); f.child.stdin.write('release-held-execution\n');
  await until(() => f.lines.includes('FIXTURE_HELD_ACTION_RELEASED'));
  const before = await f.stats(); assert.equal(before.effects, 0); assert.equal(before.active_fixture_effect, true);
  f.child.stdin.write('complete\n'); await taskState(f, next.value.task_id, 'succeeded');
  const after = await f.stats(); assert.equal(after.effects, 1); assert.equal(after.fault, null);
  assert.equal(f.manager.tasks.get(accepted.value.task_id).state, 'cancelled');
});

test('physical takeover cancels the active Java task and a delayed grant preserves manual mode', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto(); const created = await f.api('/tasks', f.request('interop-takeover'));
  assert.equal(created.status, 202, JSON.stringify(created));
  const oldLease = { ...f.manager.lease }, oldHeartbeat = f.manager.heartbeat.heartbeat_seq, oldGrant = f.manager.grantSeq + 1;
  await taskState(f, created.value.task_id, 'running'); f.child.stdin.write('takeover\n');
  await until(() => f.manager.state.value.mode === 'MANUAL_COMMENTARY').catch(async error => {
    throw new Error(error.message + ': ' + JSON.stringify({ java: await f.stats(), host: f.manager.state.view(), task: f.manager.tasks.get(created.value.task_id) }));
  });
  await taskState(f, created.value.task_id, 'cancelled');
  const before = f.manager.state.value.seq;
  f.manager.send('lease_grant', { controller_session_id: f.manager.controllerId, lease_id: oldLease.id,
    control_epoch: oldLease.epoch, grant_seq: oldGrant, based_on_heartbeat_seq: oldHeartbeat, ttl_ms: f.manager.config.control.lease_ttl_ms });
  f.child.stdin.write('complete\n');
  await until(() => f.manager.state.value.seq > before);
  assert.equal(f.manager.state.value.mode, 'MANUAL_COMMENTARY');
  const finalStats = await f.stats();
  assert.equal(finalStats.effects, 0); assert.equal(f.manager.state.value.automation_ready, false);
  assert(finalStats.diagnostics.journal.transactions > 0);
  assert(finalStats.diagnostics.max_observation_gap_ms > 0);
  t.diagnostic('takeover timing evidence ' + JSON.stringify(finalStats.diagnostics));
});

test('a task-owned inventory stays in AUTO, but a same-type replacement revokes it before an effect', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto(); const created = await f.api('/tasks', f.request('owned-gui-replacement'));
  assert.equal(created.status, 202); await taskState(f, created.value.task_id, 'running');
  await until(() => f.lines.includes('FIXTURE_PORT_STARTED ' + created.value.task_id));
  f.child.stdin.write('open-owned-inventory\n'); await until(() => f.manager.state.value.screen === 'inventory');
  const seq = f.manager.state.value.seq; await until(() => f.manager.state.value.seq >= seq + 4);
  assert.equal(f.manager.state.value.mode, 'AUTO'); assert.equal((await f.stats()).effects, 0);
  f.child.stdin.write('replace-unowned-inventory\n'); await taskState(f, created.value.task_id, 'cancelled');
  const stats = await f.stats(); assert.equal(stats.mode, 'PAUSED'); assert.equal(stats.inputs_released, true);
  assert.equal(f.manager.tasks.get(created.value.task_id).reason, 'GUI_BLOCKED'); assert.equal(stats.effects, 0);
});

test('an expired GUI lease stops a running Java task without extending the control lease or replaying an effect', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto(); const created = await f.api('/tasks', f.request('owned-gui-expiry'));
  assert.equal(created.status, 202); await taskState(f, created.value.task_id, 'running');
  await until(() => f.lines.includes('FIXTURE_PORT_STARTED ' + created.value.task_id));
  f.child.stdin.write('open-owned-inventory\n'); await until(() => f.manager.state.value.screen === 'inventory');
  assert.equal(f.manager.state.value.mode, 'AUTO'); f.child.stdin.write('expire-owned-gui\n');
  await taskState(f, created.value.task_id, 'cancelled'); const stats = await f.stats();
  assert.equal(f.manager.tasks.get(created.value.task_id).reason, 'GUI_BLOCKED'); assert.equal(stats.inputs_released, true);
  assert.equal(stats.effects, 0); assert.equal(stats.screen, 'inventory');
});

test('physical takeover preserves the task GUI for the operator and requires gameplay before a fresh AUTO', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto(); const created = await f.api('/tasks', f.request('owned-gui-takeover'));
  assert.equal(created.status, 202); await taskState(f, created.value.task_id, 'running');
  await until(() => f.lines.includes('FIXTURE_PORT_STARTED ' + created.value.task_id));
  f.child.stdin.write('open-owned-inventory\n'); await until(() => f.manager.state.value.screen === 'inventory');
  f.child.stdin.write('takeover\n'); await taskState(f, created.value.task_id, 'cancelled');
  await until(() => f.manager.state.value.mode === 'MANUAL_COMMENTARY');
  const stats = await f.stats(); assert.equal(stats.screen, 'inventory'); assert.equal(stats.effects, 0);
  assert.equal(stats.inputs_released, true); assert.equal(f.manager.tasks.get(created.value.task_id).reason, 'FIXTURE_PHYSICAL_INPUT');
  const state = f.manager.state.view();
  const denied = await f.api('/control', { request_id: 'gui-not-new-auto', target_mode: 'AUTO', reason: 'fixture',
    bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id, expected_control_epoch: state.control_epoch });
  assert.equal(denied.status, 409); assert.equal(denied.value.error, 'GAME_PRECONDITION_FAILED');
  f.child.stdin.write('close-fixture-gui\n'); await until(() => f.manager.state.value.screen === 'gameplay');
  await f.auto('gui-explicit-new-auto'); const next = await f.api('/tasks', f.request('gui-next-task')); assert.equal(next.status, 202);
  await taskState(f, next.value.task_id, 'running'); f.child.stdin.write('complete\n'); await taskState(f, next.value.task_id, 'succeeded');
  assert.equal((await f.stats()).effects, 1);
});

test('compiled Java bridge handles cancellation and preflight query without a side effect', { timeout: 90000 }, async t => {
  const f = await javaFixture(t); await f.auto(); const state = f.manager.state.view();
  const query = await f.api('/queries', { request_id: 'interop-query', bridge_boot_id: state.bridge_boot_id,
    world_session_id: state.world_session_id, kind: 'check_action', params: { goal: { skill: 'use_item', item_id: 'minecraft:bread', purpose: 'eat' } } });
  assert.equal(query.status, 202, JSON.stringify(query));
  await until(() => f.manager.operation(query.value.operation_id).state === 'succeeded');
  assert.equal(f.manager.operation(query.value.operation_id).result.allowed, true);
  const created = await f.api('/tasks', f.request('interop-cancel')); assert.equal(created.status, 202, JSON.stringify(created));
  const cancel = await f.api('/tasks/' + created.value.task_id + '/cancel', { request_id: 'interop-cancel-op', reason: 'fixture_cancel' });
  assert.equal(cancel.status, 202, JSON.stringify(cancel));
  await until(() => f.manager.operation(cancel.value.operation_id).state === 'succeeded');
  f.child.stdin.write('complete\n');
  assert.equal((await f.stats()).effects, 0);
});

test('DSH reads a bounded recipe projection through the compiled Java game-thread query without AUTO or an effect', { timeout: 90000 }, async t => {
  const f = await javaFixture(t), state = f.manager.state.view();
  const op = await f.manager.tools.invoke('game_get_recipe', { item_id: 'minecraft:oak_planks', count: 7 }, { worldSessionId: state.world_session_id });
  assert.equal(op.result.source, 'TEST_FIXTURE_ONLY'); assert.equal(op.result.recipe_known, true);
  assert.equal(op.result.recipes[0].batches, 2); assert.equal(op.result.recipes[0].output_for_batches, 8);
  assert.equal(op.result.inventory_checked, false); assert.equal(op.result.world_session_id, state.world_session_id);
  assert.equal((await f.stats()).effects, 0); assert.equal(f.manager.state.value.mode, 'PAUSED');
});

test('compiled Java recipe query preserves a missing received recipe as unknown', { timeout: 90000 }, async t => {
  const f = await javaFixture(t), state = f.manager.state.view();
  const op = await f.manager.tools.invoke('game_get_recipe', { item_id: 'minecraft:diamond', count: 1 }, { worldSessionId: state.world_session_id });
  assert.equal(op.result.recipe_known, false); assert.equal(op.result.candidate_count, 0);
  assert.deepEqual(op.result.recipes, []); assert.ok(op.result.unknown_fields.includes('unreceived_server_recipes'));
  assert.equal((await f.stats()).effects, 0);
});

test('B Java preflight and embedded schema accept one reviewed vote-linked task and return durable result feedback', { timeout: 90000 }, async t => {
  const f = await javaFixture(t), state = f.manager.state.view();
  const goal = { skill: 'use_item', item_id: 'minecraft:bread', purpose: 'eat' };
  const vote = f.manager.votes.create({ request_id: 'interop-audience-vote', bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id,
    title: 'TEST_FIXTURE_ONLY choose a fixed item', duration_seconds: 60,
    options: [{ option_id: '1', label: 'fixture bread', goal }, { option_id: '2', label: 'fixture apple', goal: { ...goal, item_id: 'minecraft:apple' } }] }).value;
  f.platformEvent({ text: '#1' });
  const closed = f.manager.votes.close(vote.vote_id, { request_id: 'interop-audience-close', expected_revision: vote.revision, action: 'close', reason: 'fixture_operator_close' });
  const suggestion = f.manager.votes.promote(vote.vote_id, { request_id: 'interop-audience-promote', bridge_boot_id: state.bridge_boot_id,
    world_session_id: state.world_session_id, expected_revision: closed.revision }).value;
  const reviewed = f.manager.suggestions.decision(suggestion.suggestion_id, { request_id: 'interop-audience-approve', expected_revision: suggestion.revision,
    action: 'accept', reason: 'fixture_operator_review' });
  assert.equal((await f.stats()).effects, 0); await f.auto();
  const request = { request_id: 'interop-audience-dispatch', bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id,
    expected_control_epoch: f.manager.state.value.control_epoch, expected_revision: reviewed.revision };
  const response = await f.api('/suggestions/' + suggestion.suggestion_id + '/dispatch', request); assert.equal(response.status, 202, JSON.stringify(response));
  await until(() => f.manager.operation(response.value.operation_id).state !== 'pending', 8000);
  const operation = f.manager.operation(response.value.operation_id); assert.equal(operation.state, 'succeeded', JSON.stringify(operation));
  const taskId = operation.result.task_id; await taskState(f, taskId, 'running');
  f.child.stdin.write('complete\n'); await taskState(f, taskId, 'succeeded', 8000);
  assert.equal(f.manager.votes.get(vote.vote_id).task_id, taskId); assert.equal(f.manager.suggestions.get(suggestion.suggestion_id).task_id, taskId);
  const feedback = (await f.api('/audience')).value.feedback.find(value => value.task_id === taskId);
  assert.equal(feedback.state, 'succeeded'); assert.equal(feedback.effect_status, 'verified'); assert.equal(feedback.speech_status, 'not_scheduled');
  assert.equal((await f.api('/suggestions/' + suggestion.suggestion_id + '/dispatch', request)).value.result.task_id, taskId);
  assert.equal((await f.stats()).effects, 1); assert.equal(journalView(f.folder).tasks.filter(value => value.task_id === taskId).length, 1);
});
