import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { hash } from '../backend/game/store.mjs';
import { validate } from '../backend/game/protocol.mjs';
import { gameFixture, samples, until } from './game-fixture.mjs';
import { historyContext, maintenanceRecord, historyPage, historyQuery, historyReply, finishHistory } from './game-history-fixture.mjs';

const sources = ['retention_summaries', 'retired_tasks', 'retention_runs'];
async function fixture(t) {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close());
  const game = await f.connect({ features: { journal_history: true, journal_maintenance_history: true } });
  return { f, game };
}
async function start(f, request = 'maintenance-history') {
  const result = await f.api('/history/imports', historyContext(f, request));
  assert.equal(result.status, 202, JSON.stringify(result)); return result.value;
}
async function maintenanceQuery(f, game, source) {
  while (true) {
    const query = await historyQuery(f, game);
    if (query.payload.request.params.source === source) return query;
    const operation = await historyReply(f, game, query, historyPage(f, query));
    assert.equal(operation.state, 'succeeded', JSON.stringify(operation));
  }
}

test('five-source import projects maintenance history with correct contracts and no live effects or memory writes', async t => {
  const { f, game } = await fixture(t); const job = await start(f);
  assert.deepEqual(job.source_order, ['reliable', 'task_versions', ...sources]); validate('HistoryImport', job);
  const records = Object.fromEntries(sources.map(source => [source, [maintenanceRecord({ source })]]));
  const status = await finishHistory(f, game, [], [], records); assert.equal(status.latest_import.state, 'completed');
  assert.equal(status.totals.records, 3); validate('HistoryStatus', status);
  for (const source of sources) {
    const page = await f.api('/history/entries?kind=' + source); assert.equal(page.status, 200); validate('HistoryPage', page.value);
    assert.equal(page.value.items.length, 1); assert.equal(page.value.items[0].source, source);
    const entry = (await f.api('/history/entries/' + page.value.items[0].record_key)).value; validate('HistoryEntry', entry);
    assert.deepEqual(entry.payload, JSON.parse(records[source][0].raw));
  }
  for (const table of ['game_events', 'task_transitions', 'stream_receipts']) assert.equal(f.manager.store.get('SELECT count(*) n FROM ' + table).n, 0);
  assert.equal(f.manager.tasks.page().items.length, 0); assert.equal(f.manager.narration.page().items.length, 0);
  assert.equal(game.messages.filter(m => ['ack', 'task_start', 'lease_grant'].includes(m.type)).length, 0);
  assert.equal(f.manager.state.value.mode, 'PAUSED');
});

test('old bridge imports exactly its original two sources and cannot request maintenance tables', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close());
  const game = await f.connect({ features: { journal_history: true } });
  const job = await start(f); assert.deepEqual(job.source_order, ['reliable', 'task_versions']);
  await finishHistory(f, game);
  assert.deepEqual(game.messages.filter(m => m.type === 'query').map(m => m.payload.request.params.source), ['reliable', 'task_versions']);
  const denied = await f.api('/queries', { ...historyContext(f, 'unsupported-history'), kind: 'journal_history',
    params: { source: 'retired_tasks', after: 0, offset: 0, through: null, limit: 20 } });
  assert.equal(denied.status, 503); assert.equal(denied.value.error, 'GAME_CAPABILITY_UNAVAILABLE');
});

test('fresh PAUSED snapshot without released inputs refuses maintenance history until a later release is observed', async t => {
  const { f, game } = await fixture(t);
  game.snapshot({ seq: 2, inputs_released: false }); await until(() => f.manager.state.value.seq === 2);
  assert.equal(f.manager.state.view().freshness, 'fresh'); assert.equal(f.manager.state.value.mode, 'PAUSED');
  assert.equal(f.manager.tasks.active(), null);
  const blocked = await f.api('/history/imports', historyContext(f, 'before-input-release'));
  assert.equal(blocked.status, 409); assert.equal(blocked.value.error, 'GAME_HISTORY_MODE_BLOCKED');
  assert.equal(f.manager.history.job, null); assert.equal(game.messages.filter(m => m.type === 'query').length, 0);
  game.snapshot({ seq: 3, inputs_released: true }); await until(() => f.manager.state.value.seq === 3);
  const job = await start(f, 'after-input-release'); assert.equal(job.state, 'running');
  const status = await finishHistory(f, game); assert.equal(status.latest_import.state, 'completed');
  assert.equal(status.totals.records, 0); assert.equal(game.messages.filter(m => m.type === 'task_start').length, 0);
});

test('repeated maintenance imports deduplicate stable proofs and preserve distinct summary versions', async t => {
  const { f, game } = await fixture(t), first = maintenanceRecord(), retired = maintenanceRecord({ source: 'retired_tasks' });
  await start(f, 'summary-v1'); await finishHistory(f, game, [], [], { retention_summaries: [first], retired_tasks: [retired] });
  const changed = structuredClone(samples['maintenance-summary-payload'].value.value); changed.count++;
  const second = maintenanceRecord({ value: changed }); assert.notEqual(second.info.record_key, first.info.record_key);
  await start(f, 'summary-v2'); await finishHistory(f, game, [], [], { retention_summaries: [second], retired_tasks: [{ ...retired, info: { ...retired.info, source_id: 7 } }] });
  assert.equal(f.manager.history.totals().records, 3); assert.equal(f.manager.history.status().latest_import.duplicate_records, 1);
  assert.deepEqual(f.manager.history.page({ kind: 'retention_summaries' }).items.map(v => v.summary.count), [4, 3]);
  await start(f, 'summary-v2-repeat'); const status = await finishHistory(f, game, [], [], { retention_summaries: [second], retired_tasks: [retired] });
  assert.equal(status.totals.records, 3); assert.equal(status.latest_import.duplicate_records, 2);
  assert.equal(f.manager.history.entry(first.info.record_key).payload.value.count, 3);
});

test('summary records and global maintenance runs keep real nullable contexts in storage and HTTP', async t => {
  const { f, game } = await fixture(t); await start(f);
  const summary = maintenanceRecord(), run = maintenanceRecord({ source: 'retention_runs' });
  await finishHistory(f, game, [], [], { retention_summaries: [summary], retention_runs: [run] });
  const entry = f.manager.history.entry(run.info.record_key);
  assert.equal(entry.metadata.source_boot_id, null); assert.equal(entry.metadata.world_session_id, null); assert.equal(entry.metadata.sequence, 0);
  assert.equal(f.manager.store.get('SELECT world_session_id FROM bridge_history WHERE record_key=?', run.info.record_key).world_session_id, '');
  assert.equal(f.manager.history.entry(summary.info.record_key).metadata.world_session_id, 'old-maintenance-world');
  assert.notEqual(entry.metadata.world_session_id, f.manager.state.value.world_session_id);
});

test('maintenance versions page beyond twenty records without gaps and remain readable offline', async t => {
  const { f, game } = await fixture(t), records = Array.from({ length: 25 }, (_, i) => {
    const value = structuredClone(samples['maintenance-summary-payload'].value.value); value.kind = 'fixture-kind-' + i;
    return maintenanceRecord({ id: i + 1, value });
  });
  await start(f); let query = await maintenanceQuery(f, game, 'retention_summaries');
  await historyReply(f, game, query, historyPage(f, query, records.slice(0, 20), { complete: false, through: 25 }));
  query = await historyQuery(f, game); await historyReply(f, game, query, historyPage(f, query, records.slice(20), { through: 25 }));
  await finishHistory(f, game);
  f.manager.disconnect('offline-maintenance-history');
  const one = (await f.api('/history/entries?kind=retention_summaries')).value, two = (await f.api('/history/entries?kind=retention_summaries&cursor=' + one.next_cursor)).value;
  assert.equal(one.items.length, 20); assert.equal(two.items.length, 5); assert.equal(two.next_cursor, null);
  assert.deepEqual(new Set([...one.items, ...two.items].map(v => v.record_key)), new Set(records.map(v => v.info.record_key)));
  assert.equal((await f.api('/history/entries/' + records[0].info.record_key)).status, 200);
});

for (const [name, source, mutate] of [
  ['record key', 'retention_summaries', (record) => { record.info.record_key = '0'.repeat(64); }],
  ['summary world', 'retention_summaries', record => { record.info.world_session_id = 'forged-world'; }],
  ['retired original boot', 'retired_tasks', record => { record.info.source_boot_id = 'forged-boot'; }],
  ['retired original time', 'retired_tasks', record => { record.info.recorded_at++; }],
  ['global run time', 'retention_runs', record => { record.info.recorded_at++; }]
]) test('maintenance ' + name + ' mismatch rolls back the complete page and fails only its import', async t => {
  const { f, game } = await fixture(t); await start(f);
  const query = await maintenanceQuery(f, game, source), first = maintenanceRecord({ source, id: 1 }), second = maintenanceRecord({ source, id: 2 });
  mutate(second); const op = await historyReply(f, game, query, historyPage(f, query, [first, second]));
  assert.equal(op.state, 'failed'); assert.equal(op.error, 'GAME_HISTORY_RECORD_CONTEXT');
  assert.equal(f.manager.history.totals().records, 0); assert.equal(f.manager.history.status().latest_import.state, 'failed');
  assert.equal((await f.api('/history/status')).status, 200); assert.equal(f.manager.state.view().connected, true);
});

for (const [name, source, change] of [
  ['summary grouping key', 'retention_summaries', value => { value.kind = 'changed-kind'; }],
  ['summary date', 'retention_summaries', value => { value.utc_day = '2026-09-11'; }],
  ['summary range', 'retention_summaries', value => { value.first_recorded_at = value.last_recorded_at + 1; }],
  ['unsupported timestamp', 'retention_summaries', value => { value.first_recorded_at = value.last_recorded_at = Number.MAX_SAFE_INTEGER; }],
  ['retired identity', 'retired_tasks', value => { value.summary.task_id = 'different-retired-task'; }],
  ['retired temporal order', 'retired_tasks', value => { value.summary.updated_at = '2026-10-31T04:00:00Z'; }],
  ['run installation', 'retention_runs', value => { value.game_instance_id = 'mc-another-installation'; }]
]) test('self-consistent chunk digest cannot authorize a forged maintenance ' + name, async t => {
  const { f, game } = await fixture(t); await start(f);
  const query = await maintenanceQuery(f, game, source), label = { retention_summaries: 'summary', retired_tasks: 'retired', retention_runs: 'run' }[source];
  const value = structuredClone(samples['maintenance-' + label + '-payload'].value.value); change(value);
  const record = maintenanceRecord({ source, value });
  // Group identity is separately bound to the canonical scope, beyond transport hashes.
  if (name === 'summary grouping key') {
    const payload = JSON.parse(record.raw); payload.source_key = samples['maintenance-summary-payload'].value.source_key;
    record.raw = Buffer.from(JSON.stringify(payload)); record.info.payload_bytes = record.raw.length;
    record.info.payload_sha256 = createHash('sha256').update(record.raw).digest('hex');
    record.info.record_key = hash([source, payload.source_key, record.info.payload_sha256]);
  }
  const op = await historyReply(f, game, query, historyPage(f, query, [record]));
  assert.equal(op.state, 'failed'); assert.equal(op.error, 'GAME_HISTORY_RECORD_CONTEXT'); assert.equal(f.manager.history.totals().records, 0);
});

test('maintenance history cancellation keeps completed earlier sources and prevents later publication', async t => {
  const { f, game } = await fixture(t); const job = await start(f), query = await maintenanceQuery(f, game, 'retention_summaries');
  assert.equal((await f.api('/history/imports/' + job.history_import_id + '/cancel', { request_id: 'cancel-maintenance' })).status, 200);
  const row = maintenanceRecord();
  game.send('query_result', { ...f.manager.operation(query.payload.operation_id), operation_id: query.payload.operation_id,
    request_id: query.payload.request.request_id, state: 'succeeded', result: historyPage(f, query, [row]), error: null });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.manager.history.status().latest_import.state, 'cancelled'); assert.equal(f.manager.history.totals().records, 0);
});
