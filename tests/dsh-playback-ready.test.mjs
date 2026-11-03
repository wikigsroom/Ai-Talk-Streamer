import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { resolve } from 'node:path';
import { StateStore } from '../backend/memory/store.mjs';
import { StreamState } from '../backend/dsh-bridge/state.mjs';
import { StreamBridge } from '../backend/dsh-bridge/server.mjs';
import { loadPolicy } from '../backend/dsh-bridge/policy.mjs';

const principal = { role: 'operator', principal_id: 'local-playback-test', viewer_id: 'viewer-ready-test' };
function fixture() {
 let now = Date.now();
 const db = new StateStore(':memory:', { now: () => now, heartbeat: false });
 const policy = loadPolicy(resolve('.'));
 const state = new StreamState(db, policy, 'test');
 const broadcast = state.createBroadcast(principal);
 const claim = (consumer = 'ready-player-one', defer = true, replace = false) => state.claimAuthority(principal, broadcast.broadcast_id, consumer, replace, defer);
 return { db, state, policy, broadcast, claim, advance(ms) { now += ms; db.tx(() => db.run('UPDATE bridge_owner SET lease_until=?', now + 30000)); }, close() { db.close(); } };
}

test('deferred playback reserves the sole consumer but cannot start generation until local output is ready', () => {
 const f = fixture(); try {
  const lease = f.claim();
  assert.equal(lease.ready, false);
  assert.equal(f.state.authorityReady(f.broadcast.broadcast_id), false);
  assert.throws(() => f.state.readyBroadcast(f.broadcast.broadcast_id, true), /DEPENDENCIES_NOT_READY/);
  assert.equal(f.state.activate(), null);
  const active = f.state.readyAuthority(lease.lease_id, lease.consumer_id);
  assert.equal(active.ready, true);
  f.state.readyBroadcast(f.broadcast.broadcast_id, true);
  const queued = f.state.accept(principal, { mode: 'echo', text: '首段声音必须完整。', idempotency_key: 'ready-full-prefix' });
  assert.equal(f.state.activate().request_id, queued.request_id);
 } finally { f.close(); }
});

test('pending playback cannot be stolen and a duplicate pending claim preserves its lease and epoch', () => {
 const f = fixture(); try {
  const lease = f.claim(), repeat = f.claim();
  assert.equal(repeat.lease_id, lease.lease_id);
  assert.equal(repeat.authority_epoch, lease.authority_epoch);
  assert.equal(repeat.ready, false);
  assert.throws(() => f.claim('ready-player-two'), /AUTHORITY_ALREADY_HELD/);
  assert.equal(f.state.lease(f.broadcast.broadcast_id).consumer_id, lease.consumer_id);
 } finally { f.close(); }
});

test('wrong consumer and old replaced lease cannot activate a new output authority', () => {
 const f = fixture(); try {
  const old = f.claim();
  assert.throws(() => f.state.readyAuthority(old.lease_id, 'ready-player-two'), /PLAYBACK_LEASE_EXPIRED/);
  const next = f.claim('ready-player-two', true, true);
  assert.notEqual(next.lease_id, old.lease_id);
  assert.throws(() => f.state.readyAuthority(old.lease_id, old.consumer_id), /PLAYBACK_LEASE_EXPIRED/);
  assert.equal(f.state.authorityReady(f.broadcast.broadcast_id), false);
  assert.equal(f.state.readyAuthority(next.lease_id, next.consumer_id).ready, true);
 } finally { f.close(); }
});

test('pending readiness has a deadline and cannot be kept alive with a playback heartbeat', () => {
 const f = fixture(); try {
  const lease = f.claim();
  assert.throws(() => f.state.heartbeat(lease.lease_id, lease.consumer_id), /PLAYBACK_LEASE_EXPIRED/);
  f.advance(f.policy.playback.lease_timeout_ms + 1);
  assert.throws(() => f.state.readyAuthority(lease.lease_id, lease.consumer_id), /PLAYBACK_LEASE_EXPIRED/);
  const next = f.claim('ready-player-two');
  assert.notEqual(next.lease_id, lease.lease_id);
  assert.equal(next.ready, false);
 } finally { f.close(); }
});

test('ready confirmation is idempotent and keeps a single durable readiness record per character room', () => {
 const f = fixture(); try {
  let lease = f.claim();
  f.state.readyAuthority(lease.lease_id, lease.consumer_id);
  const before = f.db.all("SELECT * FROM stream_events WHERE event_type='playback.authority_ready'").length;
  f.state.readyAuthority(lease.lease_id, lease.consumer_id);
  assert.equal(f.db.all("SELECT * FROM stream_events WHERE event_type='playback.authority_ready'").length, before);
  assert.equal(before, 1);
  for (let i = 0; i < 12; i++) lease = f.claim('ready-player-' + i, true, true);
  const rows = f.db.all("SELECT value_json FROM runtime_meta WHERE key LIKE 'playback-readiness:%'");
  assert.equal(rows.length, 1);
  assert.equal(JSON.parse(rows[0].value_json).lease_id, lease.lease_id);
  assert.equal(f.state.authorityReady(f.broadcast.broadcast_id), false);
 } finally { f.close(); }
});

test('restart fences a pending ready confirmation and legacy immediate claim remains usable', () => {
 const f = fixture(); try {
  const lease = f.claim();
  const recovered = new StreamState(f.db, f.policy, 'test');
  assert.throws(() => recovered.readyAuthority(lease.lease_id, lease.consumer_id), /PLAYBACK_LEASE_EXPIRED/);
  assert.equal(recovered.authorityReady(f.broadcast.broadcast_id), false);
  const legacy = recovered.claimAuthority(principal, f.broadcast.broadcast_id, 'legacy-player-one');
  assert.equal(legacy.ready, true);
  assert.equal(recovered.authorityReady(f.broadcast.broadcast_id), true);
 } finally { f.close(); }
});

test('missing and corrupt readiness proofs cannot authorize generation or renewal', () => {
 const f = fixture(); try {
  const lease = f.claim('legacy-player-one', false);
  f.state.readyBroadcast(f.broadcast.broadcast_id, true);
  f.state.accept(principal, { mode: 'echo', text: '就绪记录必须可核验。', idempotency_key: 'readiness-proof' });
  f.db.tx(() => f.db.run('DELETE FROM runtime_meta WHERE key=?', f.state.readinessKey));
  assert.equal(f.state.authorityHeld(f.broadcast.broadcast_id), true);
  assert.equal(f.state.authorityReady(f.broadcast.broadcast_id), false);
  assert.equal(f.state.activate(), null);
  assert.throws(() => f.state.heartbeat(lease.lease_id, lease.consumer_id), /PLAYBACK_LEASE_EXPIRED/);
  assert.equal(f.state.readyAuthority(lease.lease_id, lease.consumer_id).ready, true);
  const marker = JSON.parse(f.db.get('SELECT value_json FROM runtime_meta WHERE key=?', f.state.readinessKey).value_json);
  for (const value of ['invalid-json', JSON.stringify({ ...marker, authority_epoch: marker.authority_epoch + 1 })]) {
   f.db.tx(() => f.db.run('UPDATE runtime_meta SET value_json=? WHERE key=?', value, f.state.readinessKey));
   assert.throws(() => f.state.authorityReady(f.broadcast.broadcast_id), /PLAYBACK_READINESS_INVALID/);
   assert.throws(() => f.state.activate(), /PLAYBACK_READINESS_INVALID/);
   assert.throws(() => f.state.readyAuthority(lease.lease_id, lease.consumer_id), /PLAYBACK_READINESS_INVALID/);
  }
  const next = f.claim('ready-player-two', true, true);
  assert.equal(next.ready, false);
  assert.equal(f.state.authorityReady(f.broadcast.broadcast_id), false);
 } finally { f.close(); }
});

test('queued work on a live broadcast stays queued while replacement output is pending', () => {
 const f = fixture(); try {
  f.claim('legacy-player-one', false);
  f.state.readyBroadcast(f.broadcast.broadcast_id, true);
  const queued = f.state.accept(principal, { mode: 'echo', text: '请等正式声音准备好。', idempotency_key: 'pending-queued' });
  const next = f.claim('ready-player-two', true, true);
  assert.equal(f.state.activate(), null);
  assert.equal(f.state.request(queued.request_id).status, 'QUEUED');
  f.state.readyAuthority(next.lease_id, next.consumer_id);
  assert.equal(f.state.activate().request_id, queued.request_id);
 } finally { f.close(); }
});

test('actual public HTTP exposes deferred claim and ready confirmation with strict request validation', async () => {
 const f = fixture(), bridge = Object.create(StreamBridge.prototype);
 Object.assign(bridge, { db: f.db, state: f.state, auth: { resolve: () => principal }, ready: true, administration: { locked: false } });
 const server = createServer((req, res) => bridge.handle(req, res));
 try {
  await new Promise(done => server.listen(0, '127.0.0.1', done));
  const base = 'http://127.0.0.1:' + server.address().port;
  const call = async (suffix, body) => { const response = await fetch(base + '/api/dsh/playback/' + suffix, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); return { status: response.status, value: await response.json() }; };
  const body = { broadcast_id: f.broadcast.broadcast_id, consumer_id: 'http-ready-player', defer_ready: true };
  for (const defer_ready of ['true', 1, null, []]) assert.equal((await call('claim', { ...body, defer_ready })).status, 400);
  for (const replace of ['true', 1, null, []]) assert.equal((await call('claim', { ...body, replace })).status, 400);
  for (const invalid of [null, [], {}, { consumer_id: body.consumer_id }, { ...body, broadcast_id: 1 }, { ...body, consumer_id: 1 }, { ...body, unexpected: true }]) assert.equal((await call('claim', invalid)).status, 400);
  const claim = await call('claim', body);
  assert.equal(claim.status, 200); assert.equal(claim.value.ready, false);
  const ready = { lease_id: claim.value.lease_id, consumer_id: body.consumer_id };
  for (const invalid of [null, [], {}, { ...ready, replace: true }, { ...ready, lease_id: 1 }]) assert.equal((await call('ready', invalid)).status, 400);
  assert.equal((await call('ready', { ...ready, consumer_id: 'different-player' })).status, 409);
  const active = await call('ready', ready);
  assert.equal(active.status, 200); assert.equal(active.value.ready, true);
  assert.equal(active.value.lease_id, ready.lease_id);
 } finally { const closed = new Promise(done => server.close(done)); server.closeAllConnections(); await closed; f.close(); }
});

test('a storage fault during ready confirmation rolls readiness and its event back before any generation', () => {
 const f = fixture(); try {
  const lease = f.claim(), run = f.db.run.bind(f.db);
  f.db.run = (sql, ...args) => { if (sql.startsWith('UPDATE playback_leases SET expires_at=')) throw Error('injected ready persistence failure'); return run(sql, ...args); };
  assert.throws(() => f.state.readyAuthority(lease.lease_id, lease.consumer_id), /injected/);
  f.db.run = run;
  assert.equal(f.state.authorityReady(f.broadcast.broadcast_id), false);
  assert.equal(f.db.all("SELECT * FROM stream_events WHERE event_type='playback.authority_ready'").length, 0);
  assert.equal(f.state.readyAuthority(lease.lease_id, lease.consumer_id).ready, true);
 } finally { f.close(); }
});
