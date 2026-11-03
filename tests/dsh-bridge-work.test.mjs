// Actual HTTP handlers and SQLite; model, media and game runtime are explicit seams.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer, request as httpRequest } from 'node:http';
import { mkdtempSync, mkdirSync, rmSync, copyFileSync } from 'node:fs';
import { resolve, join, relative } from 'node:path';
import { StreamBridge } from '../backend/dsh-bridge/server.mjs';
import { StateStore } from '../backend/memory/store.mjs';
import { StreamState } from '../backend/dsh-bridge/state.mjs';
import { policyTemplate } from '../backend/dsh-bridge/policy.mjs';
import { MemoryService, validateExtraction } from '../backend/memory/service.mjs';
import { RoomManager } from '../backend/room/manager.mjs';
import { PlatformManager } from '../backend/platforms/manager.mjs';
import { gameFixture, until } from './game-fixture.mjs';

const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const outcome = promise => promise.then(value => ({ value }), error => ({ error }));
const turn = () => new Promise(resolve => setImmediate(resolve));
function fixture(t) {
  const base = resolve(process.env.MC_INTENT_EVIDENCE_ROOT || 'outputs/dsh-bridge-work-fixtures');
  mkdirSync(base, { recursive: true });
  const root = mkdtempSync(join(base, 'bridge-')), events = [];
  const bridge = Object.create(StreamBridge.prototype);
  const db = new StateStore(join(root, 'stream.sqlite3'));
  const close = db.close.bind(db);
  let dbClosed = false;
  db.close = () => { events.push('db.close'); dbClosed = true; close(); };
  Object.assign(bridge, { root, policy: structuredClone(policyTemplate), controllers: new Map(), ready: true,
    mediaChain: Promise.resolve(), db, state: new StreamState(db, policyTemplate, 'fixture-persona'),
    auth: { resolve: () => ({ principal_id: 'fixture-operator' }) }, administration: { locked: false },
    host: { port: { readPersona: () => ({ document: { identityCard: { name: 'fixture' } } }) },
      stopAdmission() { events.push('host.stop'); }, async close() { events.push('host.close'); } },
    scheduler: { close() { events.push('scheduler.stop'); } }, events: { close() {} },
    game: { async close() { events.push('game.close'); } }, room: { async close() { events.push('room.close'); } },
    platforms: { async close() { events.push('platforms.close'); } },
  });
  t.after(async () => {
    bridge.server?.closeAllConnections();
    await bridge.close();
    assert(relative(base, root) && !relative(base, root).startsWith('..'));
    rmSync(root, { recursive: true, force: true });
  });
  return { bridge, events, dbClosed: () => dbClosed };
}
async function listen(bridge) {
  bridge.server = createServer((req, res) => { void bridge.handle(req, res); });
  await new Promise(resolve => bridge.server.listen(0, '127.0.0.1', resolve));
  return 'http://127.0.0.1:' + bridge.server.address().port;
}

test('shutdown waits for an admitted HTTP publication to finish its SQLite commit before releasing the host and database', async t => {
  const { bridge, events, dbClosed } = fixture(t), entered = deferred(), release = deferred();
  bridge.host.publishCharacter = async () => { entered.resolve(); await release.promise; events.push('persona.published'); };
  const base = await listen(bridge);
  const response = outcome(fetch(base + '/api/dsh/persona', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_version: 'fixture-persona', document: { identityCard: { name: 'fixture' }, description: 'fixture revision' } }) }));
  let closing;
  try {
    await entered.promise;
    closing = outcome(bridge.close());
    await turn();
    assert.equal(dbClosed(), false, 'admitted publication still owns a SQLite continuation');
    assert(!events.includes('host.close'));
  } finally { release.resolve(); await response; if (closing) await closing; }
  const result = await response;
  assert.equal(result.value.status, 200);
  const published = await result.value.json();
  assert.match(published.persona_version, /^female-a-/);
  assert(events.indexOf('persona.published') < events.indexOf('host.close'));
  assert(events.indexOf('host.close') < events.indexOf('db.close'));
});

test('shutdown waits for actual public-memory projection and its SQLite receipt before flushing the host', async t => {
  const { bridge, events } = fixture(t), entered = deferred(), release = deferred(), projections = new Map();
  const port = { mirrorRevision: 0, setNativeMemoryInjection() {}, inspectProjection: id => projections.get(id),
    setVerifiedMirrorRevision() {
      assert.equal(bridge.db.get("SELECT COUNT(*) n FROM mirror_outbox WHERE state='APPLIED'").n, 1);
      events.push('projection.committed');
    },
    async applyPublicProjection(value) {
      entered.resolve(); await release.promise;
      projections.set(value.memory_id, { memory_revision: value.memory_revision, entry: { content: value.content, status: 'active' } });
      return { entry_id: value.memory_id };
    } };
  const memory = new MemoryService(bridge.db, bridge.state, bridge.policy, port);
  const operator = { role: 'operator', principal_id: 'fixture-operator', viewer_id: 'fixture-viewer' };
  const broadcast = bridge.state.createBroadcast(operator);
  bridge.state.claimAuthority(operator, broadcast.broadcast_id, 'fixture-player');
  bridge.state.readyBroadcast(broadcast.broadcast_id, true);
  const request = bridge.state.accept(operator, { text: '我喜欢茶。', mode: 'echo', public_input: true, idempotency_key: 'fixture-public-memory' });
  const source = memory.eligibleEvents(request.broadcast_id, 'public')[0];
  const candidate = validateExtraction({ schema_version: 1, summary: '公开饮品偏好', open_questions: [], candidate_facts: [{
    fact_key: 'preference.drink', value: 'tea', polarity: 'positive', evidence_kind: 'viewer_statement', validity: 'persistent_candidate',
    source_refs: [{ event_id: source.event_id, quote: source.text }] }] }, [source], 'public')[0];
  bridge.db.tx(() => memory.mergeInTransaction(candidate, 'fixture-job', 0));
  bridge.background('memory_projection', () => memory.project());
  await entered.promise;
  const closing = outcome(bridge.close());
  try { await turn(); assert(!events.includes('host.close')); assert(!events.includes('db.close')); }
  finally { release.resolve(); await closing; }
  assert.equal((await closing).error, undefined);
  assert(events.indexOf('projection.committed') < events.indexOf('host.close'));
});

test('work-drain timeout preserves stores and permits retry after a noncooperative continuation actually finishes', async t => {
  const { bridge, events } = fixture(t), release = deferred();
  const job = bridge.trackWork('maintenance', async () => {
    await release.promise;
    bridge.db.tx(() => bridge.db.run("INSERT INTO runtime_meta VALUES ('late-maintenance','{}')"));
    events.push('maintenance.settled');
  });
  try {
    await assert.rejects(bridge.close({ workDrainTimeoutMs: 20 }), { code: 'BRIDGE_WORK_DRAIN_TIMEOUT', status: 503 });
    assert(!events.includes('host.close')); assert(!events.includes('db.close'));
    let entered = false;
    await assert.rejects(bridge.trackWork('late-business', () => { entered = true; }), { code: 'BRIDGE_STOPPING' });
    assert.equal(entered, false);
  } finally { release.resolve(); await job; }
  await bridge.close();
  assert(events.indexOf('maintenance.settled') < events.indexOf('host.close'));
  assert.equal(events.filter(x => x === 'db.close').length, 1);
});

test('background failure is observed with a finite diagnostic while shutdown still drains other owned work', async t => {
  const { bridge, events } = fixture(t), release = deferred(), messages = [], original = console.error;
  console.error = message => messages.push(JSON.parse(message));
  try {
    bridge.background('maintenance', async () => { await release.promise; throw Error('private-path-sentinel'); });
    const closing = bridge.close(); await turn(); assert(!events.includes('db.close'));
    release.resolve(); await closing; await turn();
    assert.deepEqual(messages, [{ event: 'bridge.background_failed', kind: 'maintenance', code: 'BRIDGE_BACKGROUND_FAILED' }]);
    let invoked = false; bridge.background('maintenance', () => { invoked = true; }); assert.equal(invoked, false);
  } finally { release.resolve(); console.error = original; }
});

test('shutdown waits for the actual loopback media-cancel acknowledgement and rejects cancellation after teardown', async t => {
  const { bridge, events } = fixture(t), entered = deferred(), release = deferred();
  const receiver = createServer(async (req, res) => {
    assert.equal(req.url, '/internal/dsh/cancel'); entered.resolve(); await release.promise;
    events.push('media.ack'); res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{"cancelled":true}');
  });
  await new Promise(resolve => receiver.listen(0, '127.0.0.1', resolve));
  bridge.avatarUrl = 'http://127.0.0.1:' + receiver.address().port;
  t.after(async () => { receiver.closeAllConnections(); await new Promise(resolve => receiver.close(resolve)); });
  const pending = bridge.mediaCommand('cancel', { barrier_id: 'fixture-cancel' });
  await entered.promise;
  const closing = outcome(bridge.close());
  try { await turn(); assert(!events.includes('host.close')); }
  finally { release.resolve(); await pending; await closing; }
  assert(events.indexOf('media.ack') < events.indexOf('host.close'));
  await assert.rejects(bridge.mediaCommand('cancel', {}), { code: 'BRIDGE_STOPPING' });
});

test('speech cancellation completes application failure handling before game history or the main database closes', async t => {
  const { bridge, events } = fixture(t), entered = deferred(), finish = deferred();
  const request = { request_id: 'fixture-speech', mode: 'chat', runtime_epoch: 1, generation: 2, dsh_session_id: 'fixture-session' };
  bridge.channel = { snapshot: () => ({}) }; bridge.memory = { context: () => '{}' };
  bridge.state.input = () => ({ text: 'fixture question' }); bridge.state.matches = () => false;
  bridge.game.config = { enabled: false };
  bridge.game.narration = { begin: () => null, generationFailed() {
    bridge.db.get('SELECT COUNT(*) n FROM runtime_meta'); events.push('speech.finally');
  } };
  bridge.host.generate = async ({ signal }) => {
    entered.resolve(); await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
    await finish.promise; throw Object.assign(Error('MODEL_CANCELLED'), { code: 'MODEL_CANCELLED' });
  };
  const generated = bridge.processRequest(request); await entered.promise;
  const closing = outcome(bridge.close());
  try { await turn(); assert(!events.includes('game.close')); assert(!events.includes('db.close')); }
  finally { finish.resolve(); await generated; await closing; }
  assert(events.indexOf('speech.finally') < events.indexOf('game.close'));
  assert.equal(bridge.controllers.size, 0);
});

test('lazy game import completing during shutdown cannot construct or start a replacement game service', async t => {
  const { bridge, events } = fixture(t), release = deferred(); let imports = 0, constructors = 0;
  bridge.game = null;
  bridge.importGame = () => { imports++; return release.promise; };
  const loading = outcome(bridge.loadGame()), closing = outcome(bridge.close());
  try { await turn(); assert(!events.includes('host.close')); }
  finally { release.resolve({ GameManager: class { constructor() { constructors++; } } }); await loading; await closing; }
  assert.equal((await loading).error.code, 'BRIDGE_STOPPING'); assert.equal(constructors, 0);
  await assert.rejects(bridge.loadGame(), { code: 'BRIDGE_STOPPING' }); assert.equal(imports, 1);
});

test('shutdown during privacy quiescence prevents session listing and replacement-host creation', async t => {
  const { bridge } = fixture(t), entered = deferred(), release = deferred(); let listed = 0, created = 0;
  bridge.host.quiesce = async () => { entered.resolve(); await release.promise; };
  bridge.host.ctx = { sessionPersistence: { async list() { listed++; return []; } } };
  bridge.createHost = () => { created++; throw Error('must not create'); };
  const restarting = outcome(bridge.restartHostForPrivacy()); await entered.promise;
  const closing = outcome(bridge.close()); release.resolve(); await restarting; await closing;
  assert.equal((await restarting).error.code, 'BRIDGE_STOPPING'); assert.equal(listed, 0); assert.equal(created, 0);
  assert.equal(bridge.ready, false);
});

test('shutdown owns a replacement host whose privacy boot was already admitted and never republishes it as ready', async t => {
  const { bridge, events } = fixture(t), entered = deferred(), release = deferred(); let stopped = 0;
  bridge.memory = {}; bridge.administration = {};
  bridge.host.quiesce = async () => {};
  bridge.host.ctx = { sessionPersistence: { async list() { return []; } } };
  const replacement = { async start() { entered.resolve(); await release.promise; return this; },
    stopAdmission() { stopped++; }, async close() { events.push('replacement.close'); }, port: {} };
  bridge.createHost = () => replacement;
  const restarting = outcome(bridge.restartHostForPrivacy()); await entered.promise;
  const closing = outcome(bridge.close());
  try { await turn(); assert.equal(stopped, 1); assert(!events.includes('replacement.close')); }
  finally { release.resolve(); await restarting; await closing; }
  assert.equal((await restarting).error.code, 'BRIDGE_STOPPING'); assert.equal(bridge.ready, false);
  assert.equal(bridge.memory.port, undefined); assert(events.includes('replacement.close'));
});

for (const [kind, read] of [['bridge', StreamBridge.prototype.body], ['room', RoomManager.prototype.body], ['platform', PlatformManager.prototype.body]]) {
  test(kind + ' body arriving after shutdown cannot admit a delayed mutation', async t => {
    const { bridge } = fixture(t), entered = deferred(), release = deferred();
    const req = { async *[Symbol.asyncIterator]() { entered.resolve(); await release.promise; yield Buffer.from('{}'); } };
    const pending = outcome(read.call(kind === 'bridge' ? bridge : { bridge }, req));
    await entered.promise;
    const closing = bridge.close(); release.resolve();
    assert.equal((await pending).error.code, 'BRIDGE_STOPPING'); await closing;
  });
}

test('an actual HTTP body arriving after close receives 503 and cannot create a new broadcast', async t => {
  const { bridge } = fixture(t), entered = deferred(), originalBody = bridge.body;
  bridge.body = function (...args) { entered.resolve(); return originalBody.apply(this, args); };
  const base = await listen(bridge);
  const request = httpRequest(base + '/api/dsh/broadcast/start', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
  const response = new Promise((resolve, reject) => { request.on('response', res => { res.resume(); res.on('end', () => resolve(res.statusCode)); }); request.on('error', reject); });
  request.flushHeaders(); await entered.promise;
  const closing = bridge.close(); request.end('{}');
  assert.equal(await response, 503); await closing;
});

test('game shutdown revokes the actual protocol-fixture lease before work drains and preserves its readable history until final close', async () => {
  const f = await gameFixture();
  try {
    const peer = await f.connect(); await peer.auto('shutdown-work');
    assert(f.manager.lease); f.manager.stopAdmission();
    assert.equal(f.manager.lease, null); assert.equal(f.manager.state.connected, false);
    assert.throws(() => f.manager.start(), { code: 'GAME_DISABLED' });
    assert.throws(() => f.manager.requireEnabled(), { code: 'GAME_DISABLED' });
    assert(Array.isArray(f.manager.store.all("SELECT value FROM objects WHERE kind='task'"))); // Store remains open for admitted finalizers.
    const result = await f.api('/control', { target_mode: 'AUTO' }); assert.equal(result.status, 503);
    f.manager.tick(); await until(() => peer.socket.readyState === 3);
  } finally { await f.close(); }
});

test('game intent scheduling keeps its actual SQLite store until the admitted application continuation settles', async t => {
  const { bridge, events } = fixture(t), f = await gameFixture(), entered = deferred(), release = deferred();
  bridge.game = f.manager;
  f.manager.bridge.background = bridge.background.bind(bridge);
  const originalClose = f.manager.store.close.bind(f.manager.store);
  f.manager.store.close = () => { events.push('game.store.close'); originalClose(); };
  f.manager.intents.tick = async () => {
    entered.resolve(); await release.promise;
    f.manager.store.all('SELECT value FROM objects'); events.push('game.intent.settled');
  };
  let closing;
  try {
    f.manager.tick(); await entered.promise; closing = outcome(bridge.close());
    await turn(); assert(!events.includes('game.store.close')); assert.equal(f.manager.closing, true);
  } finally { release.resolve(); if(closing)await closing; await f.close(); }
  assert.equal((await closing).error, undefined);
  assert(events.indexOf('game.intent.settled') < events.indexOf('game.store.close'));
});

test('shutdown during admitted bridge startup owns the booting host and prevents persona publication or listeners', async t => {
  const base = resolve(process.env.MC_INTENT_EVIDENCE_ROOT || 'outputs/dsh-bridge-work-fixtures'); mkdirSync(base, { recursive: true });
  const root = mkdtempSync(join(base, 'startup-')), entered = deferred(), release = deferred();
  mkdirSync(join(root, 'configs/characters'), { recursive: true });
  copyFileSync(resolve('configs/characters/female-a.json'), join(root, 'configs/characters/female-a.json'));
  const bridge = new StreamBridge(root, join(root, 'unused-runtime')); let stopped = 0, disposed = 0, published = 0;
  bridge.createHost = () => ({ async start() { entered.resolve(); await release.promise; }, stopAdmission() { stopped++; },
    async publishCharacter() { published++; }, async close() { disposed++; } });
  t.after(async () => { release.resolve(); await bridge.close(); assert(relative(base, root) && !relative(base, root).startsWith('..')); rmSync(root, { recursive: true, force: true }); });
  const starting = outcome(bridge.start()); await entered.promise;
  const closing = outcome(bridge.close());
  try { await turn(); assert.equal(stopped, 1); assert.equal(disposed, 0); }
  finally { release.resolve(); await starting; await closing; }
  assert.equal((await starting).error.code, 'BRIDGE_STOPPING'); assert.equal((await closing).error, undefined);
  assert.equal(published, 0); assert.equal(disposed, 1); assert.equal(bridge.server, undefined); assert.equal(bridge.ready, false);
});
