import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createServer, request as httpRequest } from 'node:http';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { gameFixture, until } from './game-fixture.mjs';
import { NativeVisionProvider } from '../backend/game/vision.mjs';
import { FRAME_MAX_BYTES } from '../backend/game/frames.mjs';
const require = createRequire(new URL('../backend/game/package.json', import.meta.url));
const jpeg = require('jpeg-js');
const IMAGE = jpeg.encode({ width: 32, height: 18, data: Buffer.alloc(32 * 18 * 4, 170) }, 85).data;
const description = { caption: 'SYNTHETIC_FIXTURE_ONLY: 画面颜色', visible_text: [], unknowns: ['无法确定真实游戏内容'],
  model_id: 'fixture-model', runtime_id: 'fixture-runtime' };
const mock = () => ({ available: () => true, analyze: async () => structuredClone(description) });

async function rawFrame(f, request_id = 'raw-frame-fixture') {
  const state = f.manager.state.view();
  const response = await f.api('/queries', { request_id, bridge_boot_id: state.bridge_boot_id,
    world_session_id: state.world_session_id, kind: 'frame', params: {} });
  assert.equal(response.status, 202, JSON.stringify(response));
  const frame = metadata(f, response.value, 'frame-' + request_id); frame.result.kind = 'frame';
  return { operation: response.value, frame };
}

test('raw frames pass real JPEG validation without a prepared model or any inference claim', async t => {
  let calls = 0;
  const f = await withGame(t, { available: () => false, analyze: async () => { calls++; throw Error('Must not call a model'); } });
  assert.equal((await observation(f, 'still-requires-model')).value.error, 'GAME_VISION_NOT_PREPARED');
  const { operation, frame } = await rawFrame(f);
  assert.equal((await upload(f, frame)).status, 201); complete(f, operation, frame);
  await until(() => f.manager.operation(operation.operation_id).state === 'succeeded');
  const result = f.manager.operation(operation.operation_id).result;
  assert.deepEqual(result, frame.result); assert.equal(calls, 0); assert.equal(f.manager.vision.busy, null);
  assert.equal(result.caption, undefined); assert.equal(result.model_id, undefined);
  assert.deepEqual(Buffer.from(await (await fetch(f.base + '/api/dsh/game/frames/' + frame.id)).arrayBuffer()), IMAGE);
  assert.equal(f.manager.state.value.mode, 'PAUSED');
});

test('raw and inferred captures share one bounded slot and rate limit', async t => {
  const f = await withGame(t), { operation, frame } = await rawFrame(f);
  assert.equal((await observation(f, 'model-waits-for-raw')).status, 429);
  assert.equal((await upload(f, frame)).status, 201); complete(f, operation, frame);
  await until(() => f.manager.operation(operation.operation_id).state === 'succeeded');
  assert.equal((await observation(f, 'raw-rate-limit')).value.error, 'GAME_VISION_RATE_LIMIT');
  f.advance(1100); assert.equal((await observation(f, 'model-after-raw')).status, 202);
});

test('automatic visual observation requires fresh AUTO, shares frame slot and enters the next model context', async t => {
  const provider={...mock(),status:()=>({ready:true,observe_interval_ms:20000})};
  const f=await withGame(t,provider), queries=f.manager.tools.observations;
  queries.tick();await new Promise(resolve=>setTimeout(resolve,10));assert.equal(queries.handles.size,0);
  const game=f._visionGame;await game.auto('vision-observer-auto');
  await f.api('/config',{expected_revision:f.manager.configRevision,patch:{planner:{enabled:true}}});
  queries.tick();await until(()=>queries.handles.size===1);
  const operation=f.manager.operation([...queries.handles.keys()][0]),frame=metadata(f,operation,'frame-automatic-observer');
  assert.equal((await upload(f,frame)).status,201);complete(f,operation,frame);
  await until(()=>f.manager.operation(operation.operation_id).state==='succeeded');queries.tick();
  const summary=f.manager.tools.observationSummary();assert.equal(summary.result.model_id,'fixture-model');
  assert.equal(summary.result.frame_id,frame.id);assert.equal(summary.result.source,'vision_inference');
  queries.tick();assert.equal(queries.handles.size,1,'no unbounded screenshot loop');
});

test('disabling capture cancels raw operations, releases the slot and rejects late upload', async t => {
  const f = await withGame(t), { operation, frame } = await rawFrame(f);
  assert.equal((await f.api('/config', { expected_revision: 1, patch: { vision: { enabled: false } } })).status, 200);
  assert.equal(f.manager.operation(operation.operation_id).error, 'GAME_VISION_DISABLED');
  assert.equal(f.manager.vision.busy, null); assert.notEqual((await upload(f, frame)).status, 201);
  complete(f, operation, frame); await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(f.manager.operation(operation.operation_id).state, 'failed'); assert.equal(f.manager.state.connected, true);
});

test('raw capture rejects a receipt that differs from its decoded frame', async t => {
  const f = await withGame(t), { operation, frame } = await rawFrame(f);
  assert.equal((await upload(f, frame)).status, 201); frame.result.width = 31;
  complete(f, operation, frame);
  await until(() => !f.manager.state.connected);
  assert.notEqual(f.manager.operation(operation.operation_id).state, 'succeeded');
  assert.equal(f.manager.healthView().last_protocol_error.code, 'GAME_FRAME_RESULT_CONTEXT');
});

async function setup(t, provider = mock()) {
  const f = await gameFixture({ fakeClock: true, visionProvider: provider }); t.after(() => f.close());
  await f.connect({ features: { screenshots: true } });
  assert.equal((await f.api('/config', { expected_revision: 0, patch: { vision: { enabled: true } } })).status, 200);
  return f;
}
async function observation(f, name = 'vision-fixture', purpose = 'text') {
  const s = f.manager.state.view();
  return f.api('/queries', { request_id: name, bridge_boot_id: s.bridge_boot_id, world_session_id: s.world_session_id,
    kind: 'observation', params: { purpose } });
}
function metadata(f, operation, id = 'frame-fixture') {
  const state = f.manager.state.view(), captured = new Date(f.manager.wall()).toISOString();
  return { id, headers: { 'Content-Type': 'image/jpeg', 'X-MC-Operation-Id': operation.operation_id,
    'X-MC-Bridge-Boot-Id': state.bridge_boot_id, 'X-MC-World-Session-Id': state.world_session_id,
    'X-MC-Seq': String(state.seq), 'X-MC-Captured-At': captured, 'X-MC-Width': '32', 'X-MC-Height': '18' },
    result: { kind: 'observation', world_session_id: state.world_session_id, frame_id: id, source_seq: state.seq,
      captured_at: captured, width: 32, height: 18 } };
}
function upload(f, frame, bytes = IMAGE, extra = {}) {
  return fetch(f.base + '/api/dsh/game/frames/' + frame.id, { method: 'POST', headers: { ...frame.headers, ...extra }, body: bytes });
}
function complete(f, operation, frame) {
  const now = new Date(f.manager.wall()).toISOString();
  const game = f._visionGame;
  game.send('query_result', { ...operation, state: 'succeeded', updated_at: now, result: frame.result, error: null });
}
async function queriedFrame(f, name = 'vision-fixture') {
  const op = await observation(f, name); assert.equal(op.status, 202, JSON.stringify(op));
  return { operation: op.value, frame: metadata(f, op.value, 'frame-' + name) };
}
async function withGame(t, provider, fakeClock = true) {
  // Capture the bridge fixture through its normal socket API, not internal message dispatch.
  const f = await gameFixture({ fakeClock, visionProvider: provider || mock() }); t.after(() => f.close());
  f._visionGame = await f.connect({ features: { screenshots: true, raw_frames: true } });
  if (!fakeClock) {
    const sampling = setInterval(() => {
      if (f._visionGame.socket.readyState === 1) f._visionGame.snapshot({ seq: f._visionGame.observation.seq + 1,
        observed_at: new Date(f.manager.wall()).toISOString() });
    }, 200);
    t.after(() => clearInterval(sampling));
  }
  await f.api('/config', { expected_revision: 0, patch: { vision: { enabled: true } } }); return f;
}

test('raw capture is refused for a legacy peer that did not advertise it', async t => {
  const f = await withGame(t); delete f.manager.capabilities.features.raw_frames;
  const state = f.manager.state.view();
  const result = await f.api('/queries', { request_id: 'legacy-frame-capability', bridge_boot_id: state.bridge_boot_id,
    world_session_id: state.world_session_id, kind: 'frame', params: {} });
  assert.equal(result.status, 503); assert.equal(result.value.error, 'GAME_CAPABILITY_UNAVAILABLE');
  assert.equal(f.manager.pending.size, 0); assert.equal(f.manager.vision.busy, null);
});

test('real JPEG upload and decode become bounded vision provenance, without image bytes in SSE or persistence', async t => {
  let calls = 0;
  const f = await withGame(t, { available: () => true, analyze: async (entry, purpose) => {
    calls++; assert.deepEqual(entry.bytes, IMAGE); assert.equal(purpose, 'text'); return description;
  } }, false);
  const events = []; f.manager.on('operation', value => events.push(value));
  const { operation, frame } = await queriedFrame(f);
  const response = await upload(f, frame); assert.equal(response.status, 201, await response.clone().text());
  const receipt = await response.json(); assert.equal(receipt.byte_length, IMAGE.length);
  const downloaded = await fetch(f.base + '/api/dsh/game/frames/' + frame.id);
  assert.equal(downloaded.headers.get('cache-control'), 'no-store'); assert.deepEqual(Buffer.from(await downloaded.arrayBuffer()), IMAGE);
  complete(f, operation, frame); complete(f, operation, frame);
  await until(() => f.manager.operation(operation.operation_id).state === 'succeeded');
  const result = f.manager.operation(operation.operation_id).result;
  assert.equal(calls, 1); assert.equal(result.source, 'vision_inference'); assert.equal(result.runtime_id, 'fixture-runtime');
  assert.equal(result.frame_id, frame.id); assert.deepEqual(result.crop, { x: 0, y: 0, width: 32, height: 18 });
  assert.ok(result.unknowns.some(x => x.includes('结构化'))); assert.equal(f.manager.state.value.mode, 'PAUSED');
  assert.ok(!JSON.stringify([events, f.manager.snapshot()]).includes(IMAGE.toString('base64')));
  assert.equal(f.manager.store.all("SELECT * FROM objects WHERE kind='frame'").length, 0);
});

test('Java nanosecond timestamps, idempotent retries, conflicting bytes and 30-second memory expiry', async t => {
  const f = await withGame(t); const { operation, frame } = await queriedFrame(f);
  frame.result.captured_at = frame.headers['X-MC-Captured-At'] = frame.result.captured_at.replace('.000Z', '.000123456Z');
  assert.equal((await upload(f, frame)).status, 201); complete(f, operation, frame);
  await until(() => f.manager.operation(operation.operation_id).state === 'succeeded');
  f.advance(2500); f._visionGame.snapshot({ seq: 2 }); await until(() => f.manager.state.value.seq === 2);
  assert.equal((await upload(f, frame)).status, 201);
  const another = jpeg.encode({ width: 32, height: 18, data: Buffer.alloc(32 * 18 * 4, 60) }, 85).data;
  assert.equal((await upload(f, frame, another)).status, 409);
  f.advance(30000); assert.equal((await fetch(f.base + '/api/dsh/game/frames/' + frame.id)).status, 404);
});

test('frame context, header type, dimensions, stale time and malformed JPEG are rejected without control failure', async t => {
  const f = await withGame(t); const { frame } = await queriedFrame(f);
  for (const [headers, status] of [
    [{ 'Content-Type': 'application/json' }, 415], [{ 'Content-Encoding': 'gzip' }, 415],
    [{ 'X-MC-Bridge-Boot-Id': 'wrong-boot' }, 409], [{ 'X-MC-Operation-Id': 'absent-operation' }, 409],
    [{ 'X-MC-World-Session-Id': 'wrong-world' }, 409], [{ 'X-MC-Seq': '9000' }, 409],
    [{ 'X-MC-Captured-At': '2025-01-01T00:00:00Z' }, 409], [{ 'X-MC-Width': '1921' }, 413],
    [{ 'X-MC-Width': '31' }, 400], [{ 'X-MC-Seq': '-1' }, 400]
  ]) assert.equal((await upload(f, frame, IMAGE, headers)).status, status, JSON.stringify(headers));
  assert.equal((await upload(f, frame, Buffer.from('not a jpeg'))).status, 400);
  // Keep the JPEG header/dimensions but remove entropy data: full decode must also reject it.
  const broken = Buffer.concat([IMAGE.subarray(0, IMAGE.indexOf(Buffer.from([255, 218])) + 12), Buffer.from([255, 217])]);
  assert.equal((await upload(f, frame, broken)).status, 400);
  assert.equal(f.manager.state.connected, true); assert.equal(f.manager.faulted, undefined);
});

test('both declared and chunked uploads over 4MiB are rejected before cache insertion', async t => {
  const f = await withGame(t); const { frame } = await queriedFrame(f);
  // Send headers before pixels, so a deliberate rejection cannot race a still-writing fetch client.
  const rejected = await new Promise((resolve, reject) => {
    const req = httpRequest(f.base + '/api/dsh/game/frames/' + frame.id, { method: 'POST',
      headers: { ...frame.headers, 'Content-Length': FRAME_MAX_BYTES + 1 } }, res => {
      res.resume(); res.on('end', () => { resolve(res.statusCode); req.destroy(); });
    }); req.on('error', reject); req.flushHeaders();
  });
  assert.equal(rejected, 413);
  // Use the native client to observe HTTP rejection directly. Fetch can cancel
  // its streaming body on an early Connection: close and report ECONNRESET
  // instead of exposing a rejection. This client must observe an actual 413.
  const chunkedStatus = await new Promise((resolve, reject) => {
    const req = httpRequest(f.base + '/api/dsh/game/frames/' + frame.id, { method: 'POST',
      headers: { ...frame.headers, 'Transfer-Encoding': 'chunked' } }, res => {
      res.resume(); res.on('end', () => resolve(res.statusCode)); res.on('error', reject);
    });
    req.on('error', reject); req.setTimeout(5000, () => req.destroy(new Error('chunked rejection timed out')));
    for (let index = 0; index < 64; index++) req.write(Buffer.alloc(65536));
    req.end(Buffer.alloc(1));
  });
  assert.equal(chunkedStatus, 413); assert.equal(f.manager.frames.entries.size, 0);
});

test('one observation at a time, minimum interval, cache two frames and late query receipts preserve the bridge', async t => {
  const f = await withGame(t); const first = await queriedFrame(f);
  assert.equal((await observation(f, 'busy')).status, 429);
  assert.equal((await upload(f, first.frame)).status, 201); complete(f, first.operation, first.frame);
  await until(() => f.manager.operation(first.operation.operation_id).state === 'succeeded');
  assert.equal((await observation(f, 'too-fast')).status, 429);
  for (let index = 2; index <= 3; index++) {
    f.advance(1000); f._visionGame.snapshot({ seq: index }); await until(() => f.manager.state.value.seq === index);
    const next = await queriedFrame(f, 'next-' + index); assert.equal((await upload(f, next.frame)).status, 201);
    complete(f, next.operation, next.frame); await until(() => f.manager.operation(next.operation.operation_id).state === 'succeeded');
  }
  assert.equal(f.manager.frames.entries.size, 2); assert.equal((await fetch(f.base + '/api/dsh/game/frames/' + first.frame.id)).status, 404);
  complete(f, first.operation, first.frame); await new Promise(r => setTimeout(r, 15)); assert.equal(f.manager.state.connected, true);
});

test('disabling vision aborts a running inference, clears raw pixels and ignores its late output', async t => {
  let resolve, signal;
  const f = await withGame(t, { available: () => true, analyze: async (_entry, _purpose, incoming) => {
    signal = incoming; return new Promise(r => { resolve = r; });
  } });
  const { operation, frame } = await queriedFrame(f); assert.equal((await upload(f, frame)).status, 201); complete(f, operation, frame);
  await until(() => signal); await f.api('/config', { expected_revision: 1, patch: { vision: { enabled: false } } });
  assert.ok(signal.aborted); assert.equal(f.manager.frames.entries.size, 0);
  resolve(description); await new Promise(r => setTimeout(r, 15));
  assert.equal(f.manager.operation(operation.operation_id).error, 'GAME_VISION_DISABLED'); assert.equal(f.manager.state.connected, true);
});

test('disconnects and observation deadlines cancel work without stale facts', async t => {
  const f = await withGame(t, { available: () => true, analyze: async () => new Promise(() => {}) });
  const { operation, frame } = await queriedFrame(f); assert.equal((await upload(f, frame)).status, 201); complete(f, operation, frame);
  await until(() => f.manager.vision.busy?.started); f.advance(8001); f.manager.tick();
  assert.equal(f.manager.operation(operation.operation_id).state, 'failed'); assert.equal(f.manager.vision.busy, null);
  assert.equal(f.manager.faulted, undefined);
  // A real socket disconnect also clears all in-memory images.
  f._visionGame.socket.terminate(); await until(() => !f.manager.state.connected); assert.equal(f.manager.frames.entries.size, 0);
});

test('changing worlds aborts in-flight vision and clears the old frame without altering new world facts', async t => {
  let signal, resolve;
  const f = await withGame(t, { available: () => true, analyze: async (_entry, _purpose, incoming) => {
    signal = incoming; return new Promise(r => { resolve = r; });
  } });
  const { operation, frame } = await queriedFrame(f); await upload(f, frame); complete(f, operation, frame);
  await until(() => signal);
  f._visionGame.snapshot({ seq: 2, world_session_id: 'world-new-fixture', control_epoch: 8 });
  await until(() => f.manager.state.value.world_session_id === 'world-new-fixture');
  assert.ok(signal.aborted); assert.equal(f.manager.frames.entries.size, 0);
  resolve(description); await new Promise(r => setTimeout(r, 15));
  assert.equal(f.manager.operation(operation.operation_id).error, 'GAME_WORLD_CHANGED');
  assert.equal(f.manager.state.value.world_session_id, 'world-new-fixture'); assert.equal(f.manager.state.connected, true);
});

test('an accepted async tool returns before inference and explicit cancellation aborts the native provider', async t => {
  let providerSignal;
  const f = await withGame(t, { available: () => true, analyze: async (_entry, _purpose, signal) => {
    providerSignal = signal; return new Promise(() => {});
  } });
  const controller = new AbortController();
  const admitted = await f.manager.tools.invoke('game_request_observation', { purpose: 'screen' }, { purpose: 'speech', signal: controller.signal });
  assert.equal(admitted.state, 'pending'); assert.equal(admitted.result, null);
  const operation = f.manager.operation(admitted.operation_id);
  const frame = metadata(f, operation); await upload(f, frame); complete(f, operation, frame); await until(() => providerSignal);
  // SDK call disposal after successful admission cannot kill the accepted job.
  controller.abort(); assert.equal(providerSignal.aborted, false);
  const cancelled = await f.manager.tools.invoke('game_request_observation', { operation_id: admitted.operation_id, cancel: true });
  assert.equal(cancelled.state, 'failed'); assert.ok(providerSignal.aborted);
  assert.equal(f.manager.operation(operation.operation_id).error, 'GAME_VISION_CANCELLED');
  assert.equal(f.manager.vision.busy, null); assert.equal(f.manager.state.connected, true);
});

test('async vision survives the 10s tool boundary, reports increasing capture age and never starts a second inference on reads', async t => {
  let resolve, calls = 0;
  const f = await withGame(t, { available: () => true, analyze: async () => {
    calls++; return new Promise(done => { resolve = done; });
  } });
  await f.api('/config', { expected_revision: 1, patch: { vision: { timeout_ms: 30000 } } });
  const started = await f.manager.tools.invoke('game_request_observation', { purpose: 'screen' });
  assert.equal(started.state, 'pending'); assert.equal(started.result, null);
  const operation = f.manager.operation(started.operation_id), frame = metadata(f, operation);
  await upload(f, frame); complete(f, operation, frame); await until(() => resolve);
  async function advance(ms) {
    f.advance(ms); f._visionGame.snapshot({ seq: f._visionGame.observation.seq + 1, observed_at: new Date(f.manager.wall()).toISOString() });
    await until(() => f.manager.state.value.seq === f._visionGame.observation.seq);
  }
  await advance(11000);
  assert.equal((await f.manager.tools.invoke('game_request_observation', { operation_id: started.operation_id })).state, 'pending');
  assert.equal(f.manager.tools.observationSummary().operation_id, started.operation_id);
  resolve(description); await until(() => f.manager.operation(started.operation_id).state === 'succeeded');
  const first = await f.manager.tools.invoke('game_request_observation', { operation_id: started.operation_id });
  assert.equal(first.result.source, 'vision_inference'); assert.equal(first.result.frame_id, frame.id);
  assert.equal(first.result.age_ms, 11000); assert.equal(first.result.world_session_id, frame.result.world_session_id);
  await advance(5000);
  const second = await f.manager.tools.invoke('game_request_observation', { operation_id: started.operation_id });
  assert.equal(second.result.age_ms, 16000); assert.equal(calls, 1); assert.equal(f.manager.vision.busy, null);
  assert.equal(f.manager.operation(started.operation_id).result.age_ms, 11000, 'reads must not rewrite the authoritative result');
  await advance(44000);
  await assert.rejects(f.manager.tools.invoke('game_request_observation', { operation_id: started.operation_id }), { code: 'GAME_VISION_HANDLE_NOT_FOUND' });
  assert.equal(f.manager.tools.observationSummary(), null);
});

test('async vision rejects cancelled admission, mixed arguments, foreign operations, stale reads and changed boot scope', async t => {
  const f = await withGame(t);
  await assert.rejects(f.manager.tools.invoke('game_request_observation', { purpose: 'screen' }, { signal: AbortSignal.abort() }), { code: 'GAME_PLAN_CANCELLED' });
  assert.equal(f.manager.pending.size, 0);
  const direct = await observation(f, 'foreign-to-dsh-tool');
  await assert.rejects(f.manager.tools.invoke('game_request_observation', { operation_id: direct.value.operation_id }), { code: 'GAME_VISION_HANDLE_NOT_FOUND' });
  for (const args of [{}, { purpose: 'screen', cancel: true }, { purpose: 'screen', operation_id: direct.value.operation_id },
    { operation_id: direct.value.operation_id, cancel: 'true' }])
    await assert.rejects(f.manager.tools.invoke('game_request_observation', args), { code: 'GAME_REQUEST_INVALID' });
  f.manager.finishOperation(direct.value, null, 'FIXTURE_ONLY'); f.advance(1100);
  const started = await f.manager.tools.invoke('game_request_observation', { purpose: 'screen' });
  f.advance(3000);
  await assert.rejects(f.manager.tools.invoke('game_request_observation', { operation_id: started.operation_id }), { code: 'GAME_STATE_STALE' });
  assert.equal(f.manager.tools.observationSummary(), null);
  const next = await f.connect({ generation: 2, boot: 'new-boot-fixture', helloOnly: true,
    features: { screenshots: true, raw_frames: true } });
  await next.next('hello_ack');
  next.snapshot({ world_session_id: 'world-session-new-boot', observed_at: new Date(f.manager.wall()).toISOString() });
  await until(() => f.manager.state.view().freshness === 'fresh');
  await assert.rejects(f.manager.tools.invoke('game_request_observation', { operation_id: started.operation_id }), { code: 'GAME_WORLD_CHANGED' });
  assert.equal(f.manager.tools.observationSummary(), null);
  assert.equal(f.manager.operation(started.operation_id).state, 'failed');
});

test('invalid provider fields cannot overwrite the frame context or become successful facts', async t => {
  const f = await withGame(t, { available: () => true, analyze: async () => ({ ...description, caption: 'x'.repeat(2001),
    world_session_id: 'invented', source: 'observed_game_fact' }) });
  const { operation, frame } = await queriedFrame(f); await upload(f, frame); complete(f, operation, frame);
  await until(() => f.manager.operation(operation.operation_id).state === 'failed');
  assert.equal(f.manager.operation(operation.operation_id).result, null);
  assert.equal(f.manager.state.value.world_session_id, frame.result.world_session_id);
  assert.equal(f.manager.state.connected, true); assert.equal(f.manager.faulted, undefined);
});

test('provider errors and invalid descriptions fail only the query; an absent runtime cannot be admitted', async t => {
  const f = await withGame(t, { available: () => true, analyze: async () => { throw new Error('private local path must stay private'); } });
  const { operation, frame } = await queriedFrame(f); await upload(f, frame); complete(f, operation, frame);
  await until(() => f.manager.operation(operation.operation_id).state === 'failed');
  assert.equal(f.manager.operation(operation.operation_id).error, 'GAME_VISION_PROVIDER_FAILED'); assert.equal(f.manager.state.connected, true);
  const absent = await setup(t, { available: () => false }); assert.equal((await observation(absent)).status, 503);
});

async function nativeFixture(t) {
  const f = await gameFixture(); t.after(() => f.close()); mkdirSync(join(f.folder, 'configs'));
  let propsOverride = {}, outputOverride = null, received;
  const server = createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    if (req.url === '/props') return res.end(JSON.stringify({ modalities: { vision: true }, total_slots: 1,
      model_path: join(f.folder, 'model.fixture'), build_info: 'SYNTHETIC_FIXTURE_ONLY', is_sleeping: false, ...propsOverride }));
    const chunks = []; for await (const chunk of req) chunks.push(chunk); received = JSON.parse(Buffer.concat(chunks));
    res.end(outputOverride ?? JSON.stringify({ model: 'fixture-model', choices: [{ message: { content: JSON.stringify({
      caption: 'SYNTHETIC_FIXTURE_ONLY', visible_text: ['fixture'], unknowns: ['未知'] }) } }] }));
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r)); t.after(async () => { server.closeAllConnections(); await new Promise(r => server.close(r)); });
  const lock = { schema_version: 1, runtime_id: 'fixture-runtime', base_url: 'http://127.0.0.1:' + server.address().port + '/',
    model_alias: 'fixture-model', build_info: 'SYNTHETIC_FIXTURE_ONLY' };
  for (const key of ['executable', 'model', 'projector']) {
    const bytes = Buffer.from('TEST_FIXTURE_ONLY ' + key); const path = key + '.fixture'; writeFileSync(join(f.folder, path), bytes);
    lock[key] = { path, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
  }
  const save = () => writeFileSync(join(f.folder, 'configs/mc-vision.json'), JSON.stringify(lock)); save();
  const provider = new NativeVisionProvider(f.folder); t.after(() => provider.close()); await provider.prepare();
  return { f, lock, save, provider, analyze: () => provider.analyze({ bytes: IMAGE }, 'text', AbortSignal.timeout(2000)),
    setProps: value => { propsOverride = value; }, setOutput: value => { outputOverride = value; }, get received() { return received; } };
}

test('native adapter verifies fixture file pins, loopback runtime properties and embedded JPEG request', async t => {
  const n = await nativeFixture(t); assert.equal(n.provider.available(), true);
  assert.equal((await n.analyze()).runtime_id, 'fixture-runtime');
  assert.equal(n.received.messages[1].content[1].image_url.url, 'data:image/jpeg;base64,' + IMAGE.toString('base64'));
  assert.equal(n.provider.pins.size, 3); await n.analyze(); assert.equal(n.provider.pins.size, 3);
  writeFileSync(join(n.f.folder, n.lock.model.path), Buffer.from('X'.repeat(n.lock.model.bytes)));
  await assert.rejects(n.analyze(), { code: 'GAME_VISION_RUNTIME_LOCK' });
});

test('native adapter rejects wrong build, model path, vision modality, slot count, response bounds and remote origins', async t => {
  const n = await nativeFixture(t);
  for (const value of [{ build_info: 'wrong' }, { model_path: 'model.fixture' }, { modalities: { vision: false } }, { total_slots: 2 }, { is_sleeping: true }]) {
    n.setProps(value); await assert.rejects(n.analyze(), { code: 'GAME_VISION_RUNTIME_MISMATCH' });
  }
  n.setProps({}); n.setOutput(' '.repeat(65537)); await assert.rejects(n.analyze(), { code: 'GAME_VISION_RESPONSE_TOO_LARGE' });
  n.setOutput(JSON.stringify({ model: 'fixture-model', choices: [{ message: { content: '{"caption":"incomplete"}' } }] }));
  await assert.rejects(n.analyze()); n.lock.base_url = 'http://example.com/'; n.save(); assert.equal(n.provider.available(), false);
  await assert.rejects(n.analyze(), { code: 'GAME_VISION_LOCAL_ONLY' });
});
