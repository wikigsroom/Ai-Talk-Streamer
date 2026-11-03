import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { gameFixture, until } from './game-fixture.mjs';

test('bridge diagnostics distinguish a protocol rejection from a storage fault and retain the disconnect', async () => {
 const f = await gameFixture({ fakeClock: true }); try {
  const game = await f.connect();
  const initial = f.manager.snapshot().health;
  assert.equal(initial.storage_error, false); assert.equal(initial.last_fault, null);
  assert.equal(initial.last_bridge_message.frame_type, 'snapshot');
  game.snapshot({ seq: 2, control_epoch: 6 });
  await until(() => !f.manager.state.connected);
  const health = f.manager.healthView();
  assert.equal(health.storage_error, false); assert.equal(health.last_fault, null);
  assert.equal(health.last_protocol_error.code, 'GAME_STALE_EPOCH');
  assert.equal(health.last_protocol_error.frame_type, 'snapshot');
  assert.equal(health.last_disconnect.reason, 'connection_closed');
  assert.ok(Number.isFinite(health.slowest_bridge_message.duration_ms));
 } finally { await f.close(); }
});

test('first-snapshot storage failure records its sanitized cause and actual handler time before fixture teardown', async () => {
 const f = await gameFixture({ fakeClock: true }); try {
  f.manager.worlds.observe = () => {
   Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 15);
   const error = Error('private viewer secret C:/private/state.sqlite and SELECT text');
   error.code = 'ERR_SQLITE_ERROR'; error.errcode = 5; throw error;
  };
  let failed;
  try { await f.connect(); } catch (error) { failed = error; }
  assert.ok(failed?.connection_diagnostic);
  const report = JSON.parse(readFileSync(failed.connection_diagnostic, 'utf8'));
  assert.equal(report.phase, 'first_snapshot');
  assert.equal(report.health.storage_error, true);
  assert.equal(report.health.last_fault.code, 'ERR_SQLITE_ERROR');
  assert.equal(report.health.last_fault.sqlite_code, 5);
  assert.equal(report.health.last_fault.frame_type, 'snapshot');
  assert.equal(report.health.last_fault.phase, 'bridge_message');
  assert.ok(report.health.slowest_bridge_message.duration_ms >= 10);
  assert.equal(JSON.stringify(report).includes('private viewer secret'), false);
  assert.equal(JSON.stringify(report).includes('C:/private'), false);
  assert.equal(f.manager.lease, null);
 } finally { await f.close(); }
});

test('a faulted game serves in-memory diagnostics over existing SSE while storage reads and control remain blocked', async () => {
 const f = await gameFixture({ fakeClock: true }), abort = new AbortController();
 const original = f.manager.store.get.bind(f.manager.store);
 try {
  f.manager.storageFault({ code: 'GAME_STORE_OWNER_LOST' }, 'http_request');
  f.manager.store.get = () => { throw Error('diagnostics must not touch the failed database'); };
  assert.equal((await f.api('/state')).status, 503);
  assert.equal((await f.api('/control', {})).status, 503);
  const response = await fetch(f.base + '/api/dsh/game/events', { signal: abort.signal });
  assert.equal(response.status, 200);
  const reader = response.body.getReader(), first = await reader.read(), text = new TextDecoder().decode(first.value);
  assert.match(text, /event: health/); assert.match(text, /GAME_STORE_OWNER_LOST/);
  assert.equal(text.includes('event: snapshot'), false);
  await reader.cancel();
 } finally { abort.abort(); f.manager.store.get = original; await f.close(); }
});

test('the first fault is preserved and untrusted exception messages never enter the public health record', async () => {
 const f = await gameFixture(); try {
  const error = Error('raw SQL and private text'); error.code = 'private-token=123';
  f.manager.storageFault(error, 'http_request');
  const first = f.manager.healthView().last_fault;
  f.manager.storageFault({ code: 'ERR_SQLITE_ERROR', errcode: 5 }, 'scheduler');
  assert.deepEqual(f.manager.healthView().last_fault, first);
  assert.equal(first.code, 'GAME_STORAGE_ERROR');
  assert.equal(first.phase, 'http_request');
  assert.equal(JSON.stringify(f.manager.healthView()).includes('private-token'), false);
  assert.equal(JSON.stringify(f.manager.healthView()).includes('raw SQL'), false);
 } finally { await f.close(); }
});
