// Production host admission/queue/lifecycle; SDK and provider are explicit seams.
// Native pinned SDK checks use a separate loopback-only probe.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { DshHost } from '../backend/dsh-bridge/host.mjs';
import { policyTemplate } from '../backend/dsh-bridge/policy.mjs';
import { modelFailure } from '../backend/dsh-bridge/model-errors.mjs';
import { StreamBridge } from '../backend/dsh-bridge/server.mjs';
import { createServer } from 'node:http';

const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const intentId = 'mc-intent-11111111-1111-4111-8111-111111111111';
const request = purpose => ({ purpose, sessionId: purpose === 'audience_intent' ? intentId : 'lifecycle-' + purpose });
const outcome = promise => promise.then(value => ({ value }), error => ({ error }));
function fixture(t) {
  const base = resolve(process.env.MC_INTENT_EVIDENCE_ROOT || 'outputs/dsh-lifecycle-fixtures');
  mkdirSync(base, { recursive: true });
  const root = mkdtempSync(join(base, 'lifecycle-')), events = [];
  const host = new DshHost(root, join(root, 'unused-runtime'), policyTemplate);
  host.ready = true;
  host.port = { flush: async () => { events.push('flush'); } };
  host.ctx = { fiber: { dispose: async () => { events.push('fiber.dispose'); } } };
  t.after(() => { assert(relative(base, root) && !relative(base, root).startsWith('..')); rmSync(root, { recursive: true, force: true }); });
  return { host, events };
}

test('host shutdown cancels an admitted model call before flushing or disposing the writer', async t => {
  const { host, events } = fixture(t), entered = deferred(), released = deferred(); let signal;
  host.generateInternal = async options => {
    signal = options.signal; entered.resolve();
    signal.addEventListener('abort', () => { events.push('abort'); released.resolve(); }, { once: true });
    await released.promise; events.push('model.finally');
    if (signal.aborted) throw modelFailure(null, { signal });
    return { text: 'test seam' };
  };
  const generated = host.generate({ sessionId: 'running-maintenance', purpose: 'maintenance' });
  const result = generated.then(value => ({ value }), error => ({ error }));
  try {
    await entered.promise;
    await host.close();
    assert.equal(signal.aborted, true);
    assert.equal((await result).error.code, 'MODEL_CANCELLED');
    assert.deepEqual(events, ['abort', 'model.finally', 'flush', 'fiber.dispose']);
  } finally { released.resolve(); await result; }
});

for (const purpose of ['speech', 'operator_private', 'game_plan', 'audience_intent']) {
  test('shutdown cancels a running ' + purpose + ' purpose and drains its finalizer', async t => {
    const { host, events } = fixture(t), entered = deferred();
    host.generateInternal = async options => {
      entered.resolve();
      await new Promise(resolve => options.signal.addEventListener('abort', resolve, { once: true }));
      events.push('model.finally'); throw modelFailure(null, { signal: options.signal });
    };
    const generated = outcome(host.generate(request(purpose)));
    await entered.promise; await host.close();
    assert.equal((await generated).error.code, 'MODEL_CANCELLED');
    assert.deepEqual(events, ['model.finally', 'flush', 'fiber.dispose']);
    assert.equal(host.modelCalls.size, 0); assert.equal(host.foregroundQueued || 0, 0);
  });
}

for (const purpose of ['speech', 'maintenance', 'operator_private', 'game_plan', 'audience_intent']) {
  test('shutdown removes queued ' + purpose + ' work before it can enter the adapter', async t => {
    const { host } = fixture(t), entered = deferred(); let starts = 0;
    host.generateInternal = async options => {
      starts++; entered.resolve();
      await new Promise(resolve => options.signal.addEventListener('abort', resolve, { once: true }));
      throw modelFailure(null, { signal: options.signal });
    };
    const running = outcome(host.generate(request('operator_private')));
    await entered.promise;
    const queued = outcome(host.generate(request(purpose)));
    assert.equal(host.modelCalls.size, 2);
    await host.close();
    assert.equal((await running).error.code, 'MODEL_CANCELLED');
    assert.equal((await queued).error.code, 'MODEL_CANCELLED');
    assert.equal(starts, 1); assert.equal(host.modelCalls.size, 0);
  });
}

test('quiescence preserves the writer until explicit close and rejects late work', async t => {
  const { host, events } = fixture(t);
  await host.quiesce();
  assert.equal(host.ready, false); assert.equal(host.stopping, true); assert.deepEqual(events, []);
  await assert.rejects(host.generate(request('speech')), { code: 'DSH_HOST_CLOSING', status: 503 });
  await assert.rejects(host.start(), { code: 'DSH_HOST_CLOSING' });
  await host.close(); assert.deepEqual(events, ['flush', 'fiber.dispose']);
});

test('concurrent and repeated close share completion and flush the writer once', async t => {
  const { host, events } = fixture(t), gate = deferred(); let entered = false;
  host.port.flush = async () => { events.push('flush'); entered = true; await gate.promise; };
  const first = host.close(), second = host.close();
  assert.strictEqual(first, second);
  await new Promise(resolve => setImmediate(resolve)); assert(entered);
  gate.resolve(); await Promise.all([first, second, host.close()]);
  assert.deepEqual(events, ['flush', 'fiber.dispose']);
});

test('a noncooperative call times out without releasing the writer and can be drained on retry', async t => {
  const { host, events } = fixture(t), entered = deferred(), gate = deferred();
  host.generateInternal = async options => {
    entered.resolve(); await gate.promise; events.push('model.finally');
    if (options.signal.aborted) throw modelFailure(null, { signal: options.signal });
  };
  const generated = outcome(host.generate(request('maintenance')));
  try {
    await entered.promise;
    await assert.rejects(host.close({ modelDrainTimeoutMs: 20 }), { code: 'DSH_HOST_DRAIN_TIMEOUT' });
    assert.deepEqual(events, []); assert.equal(host.modelCalls.size, 1);
    await assert.rejects(host.generate(request('speech')), { code: 'DSH_HOST_CLOSING' });
  } finally { gate.resolve(); await generated; }
  await host.close(); assert.deepEqual(events, ['model.finally', 'flush', 'fiber.dispose']);
});

test('failed writer flush prevents fiber disposal and retry does not reopen admission', async t => {
  const { host, events } = fixture(t); let attempts = 0;
  host.port.flush = async () => { events.push('flush'); if (++attempts === 1) throw new Error('private-path-sentinel'); };
  await assert.rejects(host.close(), { code: 'DSH_HOST_CLOSE_FAILED', message: 'DSH_HOST_CLOSE_FAILED' });
  assert.deepEqual(events, ['flush']);
  await assert.rejects(host.generate(request('maintenance')), { code: 'DSH_HOST_CLOSING' });
  await host.close(); assert.deepEqual(events, ['flush', 'flush', 'fiber.dispose']);
});

test('a failed fiber disposal does not repeat an already successful writer flush', async t => {
  const { host, events } = fixture(t); let attempts = 0;
  host.ctx.fiber.dispose = async () => { events.push('fiber.dispose'); if (++attempts === 1) throw Error('fixture'); };
  await assert.rejects(host.close(), { code: 'DSH_HOST_CLOSE_FAILED' });
  await host.close(); assert.deepEqual(events, ['flush', 'fiber.dispose', 'fiber.dispose']);
});

test('an untracked active session is not reported as safely drained or forcibly double disposed', async t => {
  const { host, events } = fixture(t);
  host.active.set('untracked-fixture', { dispose() { throw Error('must not dispose here'); } });
  await assert.rejects(host.close(), { code: 'DSH_HOST_DRAIN_INCOMPLETE' });
  assert.deepEqual(events, []);
  host.active.clear(); await host.close(); assert.deepEqual(events, ['flush', 'fiber.dispose']);
});

function bridgeFixture(t) {
  const bridge = Object.create(StreamBridge.prototype), events = [];
  Object.assign(bridge, { controllers: new Map(), ready: true,
    scheduler: { close() { events.push('scheduler.close'); } },
    events: { close() { events.push('events.close'); } },
    game: { async close() { events.push('game.close'); } },
    room: { async close() { events.push('room.close'); } },
    platforms: { async close() { events.push('platforms.close'); } },
    state: { active: () => null }, host: { stopAdmission() { events.push('admission.stop'); }, async close() { events.push('host.close'); } },
    db: { close() { events.push('db.close'); } } });
  return { bridge, events };
}

test('bridge cancels requests before component teardown and waits for the host before closing its DB', async t => {
  const { bridge, events } = bridgeFixture(t), controller = new AbortController();
  controller.signal.addEventListener('abort', () => events.push('request.abort'));
  bridge.controllers.set('fixture', controller);
  const first = bridge.close(); assert.strictEqual(first, bridge.close()); await first;
  assert.deepEqual(events, ['scheduler.close', 'events.close', 'admission.stop', 'request.abort',
    'game.close', 'room.close', 'platforms.close', 'host.close', 'db.close']);
});

test('bridge close failure retains DB ownership and permits a real retry', async t => {
  const { bridge, events } = bridgeFixture(t); let attempts = 0;
  bridge.host.close = async () => { events.push('host.close'); if (++attempts === 1) throw Object.assign(Error('fixture'), { code: 'DSH_HOST_DRAIN_TIMEOUT' }); };
  await assert.rejects(bridge.close(), { code: 'DSH_HOST_DRAIN_TIMEOUT' });
  assert(!events.includes('db.close')); assert.equal(bridge.ready, false);
  await bridge.close(); assert.equal(events.filter(x => x === 'db.close').length, 1);
});

test('fire-and-forget shutdown records a finite failure code without exposing failure text', async t => {
  const { bridge } = bridgeFixture(t); const messages = [], original = console.error;
  bridge.host.close = async () => { throw Error('private-source-sentinel'); };
  console.error = message => messages.push(message);
  try { await assert.rejects(bridge.requestShutdown()); await Promise.resolve(); }
  finally { console.error = original; }
  assert.deepEqual(messages.map(message => JSON.parse(message)), [{ event: 'bridge.shutdown_failed', code: 'BRIDGE_SHUTDOWN_FAILED' }]);
});

test('privacy restart waits for full quiescence before listing sessions or releasing the old host', async t => {
  const { bridge } = bridgeFixture(t), gate = deferred(), events = [];
  bridge.host.quiesce = async () => { events.push('quiesce'); await gate.promise; events.push('quiescent'); };
  bridge.host.ctx = { sessionPersistence: { async list() { events.push('list'); return []; } } };
  bridge.host.close = async () => { events.push('host.close'); throw Error('stop before test would instantiate a replacement'); };
  const pending = outcome(bridge.restartHostForPrivacy());
  await new Promise(resolve => setImmediate(resolve)); assert.deepEqual(events, ['quiesce']);
  gate.resolve(); assert((await pending).error);
  assert.deepEqual(events, ['quiesce', 'quiescent', 'list', 'host.close']);
});

test('draining HTTP bridge rejects new work but keeps shutdown retry and health available', async t => {
  const { bridge } = bridgeFixture(t); bridge.closed = true;
  bridge.auth = { resolve: () => ({}) }; bridge.state.current = () => null;
  bridge.refreshMedia = async () => {}; bridge.health = () => ({ process_alive: true, ready: false });
  let retries = 0; bridge.requestShutdown = () => { retries++; return Promise.resolve(); };
  const server = createServer((req, res) => bridge.handle(req, res));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const base = 'http://127.0.0.1:' + server.address().port;
  const denied = await fetch(base + '/api/dsh/game/config', { method: 'POST', body: '{}' });
  assert.equal(denied.status, 503); assert.deepEqual(await denied.json(), { error: 'BRIDGE_STOPPING' });
  const health = await fetch(base + '/health'); assert.equal(health.status, 200); assert.equal((await health.json()).ready, false);
  const retry = await fetch(base + '/api/dsh/shutdown', { method: 'POST', body: '{}' });
  assert.equal(retry.status, 200); assert.deepEqual(await retry.json(), { stopping: true });
  await new Promise(resolve => setTimeout(resolve, 40)); assert.equal(retries, 1);
  bridge.state.current = () => ({ state: 'LIVE' });
  const refused = await fetch(base + '/api/dsh/shutdown', { method: 'POST', body: '{}' });
  assert.equal(refused.status, 409); assert.equal((await refused.json()).error, 'SHUTDOWN_REQUIRES_OFFAIR');
});
