import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { join } from 'node:path';
import { GameStore } from '../backend/game/store.mjs';
import { HISTORY_LIMITS } from '../backend/game/history.mjs';
import { gameFixture, samples, until } from './game-fixture.mjs';
import { historyFixture, historyContext, historyRecord, historyPage, historyQuery, historyReply, finishHistory } from './game-history-fixture.mjs';

test('history imports all delivery dispositions and independent task versions without replaying live facts', async t => {
  const { f, game } = await historyFixture(t);
  const request = historyContext(f); assert.equal((await f.api('/history/imports', request)).status, 202);
  const records = [1, 2, 3].map(id => historyRecord({ id, payload: { ...samples['bridge-game_event'].value.payload,
    delivery_seq: id, event_id: 'historical-event-' + id, world_session_id: 'old-world-' + id },
    ...(id === 1 ? { acked_at: 1793332800100 } : id === 2 ? { archived_at: 1793332800200, archive_reason: 'world_changed' } : {}) }));
  const task = { ...samples['task-complete'].value, bridge_boot_id: 'old-task-boot', world_session_id: 'old-task-world' };
  task.evidence = task.evidence.map(proof => ({ ...proof, world_session_id: task.world_session_id }));
  const delivery = historyRecord({ id: 4, payload: { delivery_seq: 1, transition_seq: task.version, task } });
  const versions = [1, 2, 3].map(version => historyRecord({ source: 'task_versions', id: version,
    payload: { ...task, version, state: version < 3 ? 'running' : 'succeeded' } }));
  const status = await finishHistory(f, game, [...records, delivery], versions);
  assert.equal(status.latest_import.state, 'completed'); assert.equal(status.totals.records, 7);
  assert.equal(f.manager.tasks.page().items.length, 0); assert.equal(f.manager.narration.page().items.length, 0);
  for (const table of ['game_events', 'task_transitions', 'stream_receipts']) assert.equal(f.manager.store.get('SELECT count(*) n FROM ' + table).n, 0);
  assert.equal(game.messages.filter(m => ['ack', 'task_start', 'lease_grant'].includes(m.type)).length, 0);
  assert.equal(f.manager.state.value.mode, 'PAUSED');
  const detail = (await f.api('/history/entries/' + records[1].info.record_key)).value;
  assert.equal(detail.metadata.archive_reason, 'world_changed'); assert.equal(detail.payload.world_session_id, 'old-world-2');
  assert.equal((await f.api('/history/imports', request)).value.history_import_id, status.latest_import.history_import_id);
});

test('repeated imports deduplicate immutable payloads and retain known delivery metadata', async t => {
  const { f, game } = await historyFixture(t), record = historyRecord({ acked_at: 1793332800100 });
  await f.api('/history/imports', historyContext(f, 'first')); await finishHistory(f, game, [record]);
  await f.api('/history/imports', historyContext(f, 'second')); const second = await finishHistory(f, game, [{ ...record, info: { ...record.info, source_id: 9, acked_at: null } }]);
  assert.equal(second.totals.records, 1); assert.equal(second.latest_import.duplicate_records, 1);
  assert.equal(f.manager.history.entry(record.info.record_key).metadata.acked_at, 1793332800100);
  await f.api('/history/imports', historyContext(f, 'third')); await finishHistory(f, game, [{ ...record, info: { ...record.info, acked_at: 1793332800200 } }]);
  assert.equal(f.manager.history.entry(record.info.record_key).metadata_conflict, true);
  assert.equal(f.manager.history.entry(record.info.record_key).metadata.acked_at, 1793332800100);
});

test('UTF-8 records larger than one chunk reassemble with their original hash and no partial publication', async t => {
  const { f, game } = await historyFixture(t), record = historyRecord({ payload: { ...samples['bridge-game_event'].value.payload,
    data: { note: '界'.repeat(39000) } } });
  await f.api('/history/imports', historyContext(f));
  let pages = 0;
  while (f.manager.history.job.source === 'reliable') {
    const query = await historyQuery(f, game), result = historyPage(f, query, [record]);
    const operation = await historyReply(f, game, query, result); assert.equal(operation.state, 'succeeded', JSON.stringify(operation));
    pages++; if (!result.complete) assert.equal(f.manager.history.totals().records, 0);
  }
  const query = await historyQuery(f, game); await historyReply(f, game, query, historyPage(f, query));
  assert.ok(pages >= 4); assert.equal(f.manager.history.totals().records, 1);
  assert.equal(f.manager.history.entry(record.info.record_key).payload.data.note, '界'.repeat(39000));
  assert.equal(f.manager.store.get('SELECT count(*) n FROM history_partial').n, 0);
  assert.ok(JSON.stringify(f.manager.operation(query.payload.operation_id)).length < 1500);
});

for (const [name, mutate, code] of [
  ['payload hash', result => { result.chunks[0].payload_sha256 = '0'.repeat(64); }, 'GAME_HISTORY_PAYLOAD_HASH'],
  ['record identity', result => { result.chunks[0].source_boot_id = 'forged-boot'; }, 'GAME_HISTORY_RECORD_CONTEXT'],
  ['next cursor', result => { result.next_after++; }, 'GAME_HISTORY_CURSOR_INVALID'],
  ['early completion', result => { result.through++; }, 'GAME_HISTORY_CURSOR_INVALID'],
  ['page source', result => { result.source = 'task_versions'; }, 'GAME_HISTORY_PAGE_CONTEXT'],
  ['offset', result => { result.chunks[0].offset = 1; }, 'GAME_HISTORY_CHUNK_ORDER']
]) test('invalid historical ' + name + ' rolls back the whole page and fails its import', async t => {
  const { f, game } = await historyFixture(t); await f.api('/history/imports', historyContext(f));
  const query = await historyQuery(f, game), result = historyPage(f, query, [historyRecord()]); mutate(result);
  const operation = await historyReply(f, game, query, result);
  assert.equal(operation.error, code); assert.equal(f.manager.history.status().latest_import.state, 'failed');
  assert.equal(f.manager.history.totals().records, 0); assert.equal(f.manager.faulted, undefined);
});

test('conflicting immutable history preserves the original and rolls back preceding rows in the same page', async t => {
  const { f, game } = await historyFixture(t), record = historyRecord();
  await f.api('/history/imports', historyContext(f, 'original')); await finishHistory(f, game, [record]);
  await f.api('/history/imports', historyContext(f, 'conflict'));
  const other = historyRecord({ id: 1, payload: { ...samples['bridge-game_event'].value.payload, delivery_seq: 2, event_id: 'new-first' } });
  const changed = historyRecord({ id: 2, payload: { ...samples['bridge-game_event'].value.payload, data: { changed: true } } });
  const query = await historyQuery(f, game), operation = await historyReply(f, game, query, historyPage(f, query, [other, changed]));
  assert.equal(operation.error, 'GAME_HISTORY_RECORD_CONFLICT'); assert.equal(f.manager.history.totals().records, 1);
  assert.deepEqual(f.manager.history.entry(record.info.record_key).payload, samples['bridge-game_event'].value.payload);
});

test('history is capability gated, rejects free-standing queries and never delays an explicit AUTO request', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close());
  let game = await f.connect(); assert.equal((await f.api('/history/imports', historyContext(f))).value.error, 'GAME_CAPABILITY_UNAVAILABLE');
  game = await f.connect({ generation: 2, features: { journal_history: true } });
  const request = { ...historyContext(f, 'unowned'), kind: 'journal_history', params: { source: 'reliable', after: 0, offset: 0, through: null, limit: 20 } };
  assert.equal((await f.api('/queries', request)).value.error, 'GAME_HISTORY_IMPORT_REQUIRED');
  await f.api('/history/imports', historyContext(f)); const query = await historyQuery(f, game);
  await game.auto('history-to-auto'); assert.equal(f.manager.history.status().latest_import.reason, 'GAME_HISTORY_MODE_CHANGED');
  assert.equal(f.manager.operation(query.payload.operation_id).state, 'failed');
  assert.equal((await f.api('/history/imports', historyContext(f, 'in-auto'))).value.error, 'GAME_HISTORY_MODE_BLOCKED');
});

test('cancellation is scoped, repeatable and ignores a late reply without affecting the next import', async t => {
  const { f, game } = await historyFixture(t);
  const first = (await f.api('/history/imports', historyContext(f, 'cancel-one'))).value, query = await historyQuery(f, game);
  const path = '/history/imports/' + first.history_import_id + '/cancel';
  assert.equal((await f.api(path, { request_id: 'cancel-one' })).value.state, 'cancelled');
  const second = (await f.api('/history/imports', historyContext(f, 'import-two'))).value;
  assert.equal((await f.api(path, { request_id: 'cancel-repeat' })).value.state, 'cancelled');
  assert.equal(f.manager.history.job.history_import_id, second.history_import_id);
  await historyReply(f, game, query, historyPage(f, query, [historyRecord()]));
  await finishHistory(f, game); assert.equal(f.manager.history.totals().records, 0);
});

test('host restart retains complete history but discards a partial transfer and cannot resume it implicitly', async t => {
  const { f, game } = await historyFixture(t), small = historyRecord();
  await f.api('/history/imports', historyContext(f, 'complete-first')); await finishHistory(f, game, [small]);
  await f.api('/history/imports', historyContext(f, 'partial-next'));
  const record = historyRecord({ payload: { ...samples['bridge-game_event'].value.payload, data: { large: 'a'.repeat(70000) } } });
  const query = await historyQuery(f, game); await historyReply(f, game, query, historyPage(f, query, [record]));
  assert.equal(f.manager.store.get('SELECT count(*) n FROM history_partial').n, 1);
  await f.restartHost(); assert.equal(f.manager.history.job, null);
  assert.equal(f.manager.history.totals().records, 1); assert.equal(f.manager.store.get('SELECT count(*) n FROM history_partial').n, 0);
  assert.ok(['interrupted'].includes(f.manager.history.status().latest_import.state));
  assert.equal((await f.api('/history/entries')).value.items.length, 1);
});

test('offline and disabled installations can browse saved history with bounded filters and pages', async t => {
  const { f, game } = await historyFixture(t);
  await f.api('/history/imports', historyContext(f));
  const records = [1, 2, 3].map(id => historyRecord({ id, payload: { ...samples['bridge-game_event'].value.payload, delivery_seq: id, event_id: 'page-' + id } }));
  await finishHistory(f, game, records); f.manager.disconnect('history-offline');
  await f.api('/config', { expected_revision: f.manager.configRevision, patch: { enabled: false } });
  const first = (await f.api('/history/entries?limit=2&kind=events')).value; assert.equal(first.items.length, 2); assert.ok(first.next_cursor);
  const next = (await f.api('/history/entries?limit=2&kind=events&cursor=' + first.next_cursor)).value; assert.equal(next.items.length, 1);
  assert.equal(new Set([...first.items, ...next.items].map(v => v.record_key)).size, 3);
  assert.equal((await f.api('/history/entries?kind=task_versions')).value.items.length, 0);
  for (const path of ['/history/entries?limit=101', '/history/entries?kind=bad', '/history/entries?cursor=1%20OR%201=1']) assert.equal((await f.api(path)).status, 400);
  assert.equal((await f.api('/history/status')).status, 200); assert.equal((await f.api('/state')).value.error, 'GAME_DISABLED');
});

test('connection loss, changed world, stale observations and operation timeout interrupt import progress', async t => {
  for (const reason of ['disconnect', 'world', 'stale', 'timeout']) {
    const f = await gameFixture({ fakeClock: true });
    try {
      const game = await f.connect({ features: { journal_history: true } }); await f.api('/history/imports', historyContext(f));
      const query = await historyQuery(f, game);
      if (reason === 'disconnect') f.manager.disconnect('test');
      if (reason === 'world') { game.snapshot({ seq: 2, world_session_id: 'new-history-world' }); await until(() => !f.manager.history.job); }
      if (reason === 'stale') f.advance(2100);
      if (reason === 'timeout') { f.manager.pending.get(query.payload.operation_id).deadline = f.manager.clock(); }
      f.manager.tick(); assert.equal(f.manager.history.job, null, reason);
      assert.equal(f.manager.history.totals().records, 0); assert.notEqual(f.manager.operation(query.payload.operation_id).state, 'pending');
    } finally { await f.close(); }
  }
});

test('capacity rejects a new page atomically and a storage failure retains the first fault', async t => {
  const { f, game } = await historyFixture(t); await f.api('/history/imports', historyContext(f));
  const oldTotals = f.manager.history.totals.bind(f.manager.history);
  f.manager.history.totals = () => ({ records: HISTORY_LIMITS.entries, payload_bytes: 0 });
  const query = await historyQuery(f, game); const operation = await historyReply(f, game, query, historyPage(f, query, [historyRecord()]));
  assert.equal(operation.error, 'GAME_HISTORY_CAPACITY'); f.manager.history.totals = oldTotals;
  assert.equal(f.manager.history.totals().records, 0);
  const error = Error('private database path'); error.code = 'ERR_SQLITE_ERROR'; f.manager.storageFault(error, 'history-import');
  assert.equal((await f.api('/history/status')).value.error, 'GAME_STORAGE_ERROR'); assert.equal(f.manager.healthView().last_fault.phase, 'history-import');
});

test('schema v3 upgrade takes a consistent WAL backup before adding separate historical tables', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const path = join(f.folder, 'legacy-v3.sqlite3');
  const initial = new GameStore(path); initial.close(); const raw = new DatabaseSync(path); let upgraded;
  raw.exec('DROP TABLE bridge_history; DROP TABLE history_partial; DELETE FROM schema_migrations WHERE version=4; PRAGMA journal_mode=WAL');
  raw.prepare('INSERT OR REPLACE INTO meta VALUES(?,?)').run('history-migration-proof', '{"preserved":true}');
  try {
    upgraded = new GameStore(path); assert.equal(upgraded.schemaVersion, 4);
    const proof = upgraded.meta('schema_v4_migration'); assert.equal(proof.from, 3);
    const backup = new DatabaseSync(join(f.folder, 'backups', proof.backup_file), { readOnly: true });
    try { assert.equal(backup.prepare('SELECT MAX(version) n FROM schema_migrations').get().n, 3);
      assert.equal(backup.prepare('SELECT value FROM meta WHERE key=?').get('history-migration-proof').value, '{"preserved":true}');
      assert.equal(backup.prepare("SELECT count(*) n FROM sqlite_master WHERE name='bridge_history'").get().n, 0);
    } finally { backup.close(); }
    assert.deepEqual(upgraded.meta('history-migration-proof'), { preserved: true });
  } finally { upgraded?.close(); raw.close(); }
});

test('a changed partial-record identity fails before publication and removes only the incomplete transfer', async t => {
  const { f, game } = await historyFixture(t); await f.api('/history/imports', historyContext(f));
  const record = historyRecord({ payload: { ...samples['bridge-game_event'].value.payload, data: { large: 'x'.repeat(70000) } } });
  let query = await historyQuery(f, game); await historyReply(f, game, query, historyPage(f, query, [record]));
  query = await historyQuery(f, game); const page = historyPage(f, query, [record]); page.chunks[0].source_boot_id = 'changed-partial-boot';
  assert.equal((await historyReply(f, game, query, page)).error, 'GAME_HISTORY_CHUNK_CHANGED');
  assert.equal(f.manager.history.totals().records, 0); assert.equal(f.manager.store.get('SELECT count(*) n FROM history_partial').n, 0);
});

test('a real import write failure rolls back its complete page, closes the connection and exposes a sanitized first fault', async t => {
  const { f, game } = await historyFixture(t); await f.api('/history/imports', historyContext(f));
  const query = await historyQuery(f, game), original = f.manager.store.run; let inserts = 0;
  f.manager.store.run = function(sql, ...args) {
    if (sql.startsWith('INSERT INTO bridge_history') && ++inserts === 2) { const error = Error('private failure details'); error.code = 'ERR_SQLITE_ERROR'; throw error; }
    return original.call(this, sql, ...args);
  };
  try {
    const records = [1, 2].map(id => historyRecord({ id, payload: { ...samples['bridge-game_event'].value.payload, delivery_seq: id, event_id: 'failure-' + id } }));
    await historyReply(f, game, query, historyPage(f, query, records));
    await until(() => f.manager.faulted && !f.manager.state.connected);
    assert.equal(f.manager.history.totals().records, 0); assert.equal(f.manager.healthView().last_fault.code, 'ERR_SQLITE_ERROR');
    assert.equal(JSON.stringify(f.manager.healthView()).includes('private failure details'), false);
    assert.equal((await f.api('/history/status')).status, 503);
  } finally { f.manager.store.run = original; }
});
