import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, createHmac } from 'node:crypto';
import { deflateSync, brotliCompressSync } from 'node:zlib';
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createServer } from 'node:http';
import { PlatformConfig } from '../backend/platforms/config.mjs';
import { PlatformStore } from '../backend/platforms/store.mjs';
import { normalizeEvent, eventPrincipal } from '../backend/platforms/events.mjs';
import { signBilibili, encodePacket, decodePackets, BilibiliOpenAdapter } from '../backend/platforms/bilibili.mjs';
import { douyinSignature, verifyDouyin } from '../backend/platforms/douyin.mjs';
import { PlatformManager } from '../backend/platforms/manager.mjs';
import { StateStore } from '../backend/memory/store.mjs';
import { StreamState } from '../backend/dsh-bridge/state.mjs';
import { MemoryService } from '../backend/memory/service.mjs';
import { loadPolicy } from '../backend/dsh-bridge/policy.mjs';
const root = resolve(process.cwd()), output = join(root, 'outputs/platforms/tests'); mkdirSync(output, { recursive: true });
const operator = { role: 'operator', principal_id: 'local', viewer_id: 'operator-local' };
function fixture() {
  const folder = mkdtempSync(join(output, 'case-')); let now = 1792926000000;
  const db = new StateStore(':memory:', { now: () => now, heartbeat: false }), policy = loadPolicy(root), state = new StreamState(db, policy, 'persona-test');
  const memory = new MemoryService(db, state, policy, { mirrorRevision: 0, setNativeMemoryInjection() {}, setVerifiedMirrorRevision() {}, inspectProjection() { return null; } });
  const bridge = { state, db, ready: true, administration: { locked: false }, auth: { resolve: () => operator }, host: { ready: true }, health: () => ({ persona_injection_ready: true }), refreshMedia: async () => ({ tts_ready: true, avatar_ready: true }), tick: async () => {}, async body(req) { let raw = ''; for await (const chunk of req) raw += chunk; return raw ? JSON.parse(raw) : {}; } };
  const manager = new PlatformManager(folder, bridge, { now: () => now });
  const start = () => { const b = state.createBroadcast(operator); const lease = state.claimAuthority(operator, b.broadcast_id, 'obs-test'); state.readyBroadcast(b.broadcast_id, true); return lease; };
  const event = (id = 'event-1', user = '123', platform = 'bilibili') => ({ platform, event: { type: 'comment', event_id: id, room_id: '456', user_id: user, nickname: '同一个昵称', text: '我喜欢茶。', timestamp: now } });
  return { folder, db, state, policy, memory, bridge, manager, start, event, advance(ms) { db.tx(() => db.run('UPDATE bridge_owner SET lease_until=?', now + ms + 30000)); now += ms; }, async close() { await manager.close(); db.close(); rmSync(folder, { recursive: true, force: true }); } };
}

test('private platform settings never return secrets and blank edits preserve them', async () => {
  const f = fixture(); try {
    const cfg = f.manager.config;
    cfg.update({ platforms: { bilibili: { room_id: '123', stream_server: 'rtmp://127.0.0.1/live', stream_key: 'test-stream-secret', cookie: 'test-cookie-secret', access_key: 'test-access-secret', access_secret: 'test-signing-secret' } } });
    const view = JSON.stringify(cfg.public()); for (const value of ['test-stream-secret', 'test-cookie-secret', 'test-access-secret', 'test-signing-secret']) assert.ok(!view.includes(value));
    assert.equal(cfg.public().platforms.bilibili.has_stream_key, true); cfg.update({ platforms: { bilibili: { stream_key: '' } } });
    assert.equal(new PlatformConfig(f.folder).value.platforms.bilibili.stream_key, 'test-stream-secret');
    cfg.update({ platforms: { bilibili: { stream_key: null } } }); assert.equal(cfg.public().platforms.bilibili.has_stream_key, false);
    cfg.update({ platforms: { bilibili: { room_url: 'http://live.bilibili.com/595139?source=share', room_id: '' } } });
    assert.equal(cfg.value.platforms.bilibili.room_id, '595139'); assert.equal(cfg.value.platforms.bilibili.room_url, 'https://live.bilibili.com/595139');
    assert.throws(() => cfg.update({ platforms: { douyin: { room_url: 'https://example.com/private' } } }), /ROOM_URL/);
  } finally { await f.close(); }
});
test('platform IDs, rooms and stable user IDs partition memories even for equal nicknames', async () => {
  const f = fixture(); try {
    f.start(); const a = f.event(), b = f.event('e2', '123', 'douyin'), c = f.event('e3', 'other');
    for (const data of [a, b, c]) { f.manager.ingest(data.platform, data.event); await f.manager.dispatch(); f.manager.lastReply = 0; }
    // Manual queue takes precedence, so drain explicitly between observations.
    const first = f.db.get('SELECT * FROM requests'); assert.ok(first.viewer_id.startsWith('viewer:bilibili:'));
    const principals = [a, b, c].map(data => eventPrincipal(normalizeEvent(data.platform, data.event, { now: data.event.timestamp })));
    assert.equal(new Set(principals.map(p => p.viewer_id)).size, 3);
    assert.equal(f.state.input(first).source.platform, 'bilibili');
    const other = f.state.accept(principals[1], { text: '另一位观众的私事', idempotency_key: 'other-user-input' });
    const ctx = JSON.parse(f.memory.context(other, { revision: 'test' })); assert.ok(!JSON.stringify(ctx).includes('我喜欢茶'));
    assert.equal(ctx.viewer_source, null);
  } finally { await f.close(); }
});
test('display-only identities use public context and never pretend nicknames are verified users', () => {
  const base = { type: 'comment', room_id: '1', event_id: '2', user_id: 0, nickname: 'alice', text: 'hi' };
  const p = eventPrincipal(normalizeEvent('douyin', base)); assert.equal(p.public_input, true); assert.equal(p.viewer_id, 'public');
  assert.notEqual(eventPrincipal(normalizeEvent('douyin', { ...base, user_id: 'stable-123' })).viewer_id, p.viewer_id);
});
test('durable event de-duplication survives closing and reopening its SQLite database', async () => {
  const f = fixture(); try {
    const file = join(f.folder, 'dedup.sqlite3'), event = normalizeEvent('douyin', f.event().event, { now: f.event().event.timestamp });
    const first = new PlatformStore(file); assert.equal(first.insert(event), true); first.close();
    const second = new PlatformStore(file); assert.equal(second.insert(event), false); assert.equal(second.recent().length, 1); second.close();
    f.start(); f.manager.ingest('bilibili', [f.event().event, f.event().event]); await f.manager.dispatch();
    assert.equal(f.db.get('SELECT COUNT(*) n FROM requests').n, 1); assert.equal(f.manager.status().counters.duplicates, 1);
  } finally { await f.close(); }
});
test('expired input, backpressure and disabled interaction cannot generate delayed speech', async () => {
  const f = fixture(); try {
    f.start(); f.manager.config.update({ interaction: { max_pending: 1 } });
    f.manager.ingest('bilibili', [f.event('a').event, f.event('b').event]); assert.equal(f.manager.status().counters.overload_drops, 1);
    f.advance(46000); await f.manager.dispatch(); assert.equal(f.db.get('SELECT COUNT(*) n FROM requests').n, 0); assert.equal(f.manager.status().pending, 0);
    f.manager.config.update({ interaction: { enabled: false } }); f.manager.ingest('bilibili', f.event('c').event); await f.manager.dispatch(); assert.equal(f.db.get('SELECT COUNT(*) n FROM requests').n, 0);
  } finally { await f.close(); }
});
test('paused sessions and missing playback authority do not consume a comment', async () => {
  const f = fixture(); try {
    const lease = f.start(); f.manager.ingest('douyin', f.event().event); f.state.pause(operator); await f.manager.dispatch(); assert.equal(f.manager.status().pending, 1);
    f.state.readyBroadcast(f.state.current().broadcast_id, true); f.advance(9000); await f.manager.dispatch(); assert.equal(f.manager.status().pending, 1);
    f.state.claimAuthority(operator, f.state.current().broadcast_id, lease.consumer_id, true); await f.manager.dispatch(); assert.equal(f.manager.status().pending, 0);
  } finally { await f.close(); }
});

test('intermediate DSH audio readiness never prevents a platform event reaching its terminal state', async () => {
  const f=fixture();
  try {
    f.start(); f.manager.ingest('bilibili', f.event().event); await f.manager.dispatch();
    const event=f.manager.store.recent()[0];
    for(const status of ['THINKING','TEXT_READY','SYNTHESIZING','AUDIO_READY','BUFFERING','PLAYING']){
      f.db.tx(()=>f.db.run('UPDATE requests SET status=? WHERE request_id=?',status,event.request_id));
      await f.manager.dispatch(); assert.equal(f.manager.store.recent()[0].status,'QUEUED');
    }
    // Repair records written by the earlier bridge build as well.
    f.manager.store.run("UPDATE events SET status='AUDIO_READY' WHERE event_key=?",event.event_key);
    f.db.tx(()=>f.db.run("UPDATE requests SET status='COMPLETED' WHERE request_id=?",event.request_id));
    await f.manager.dispatch();assert.equal(f.manager.store.recent()[0].status,'COMPLETED');
  }finally{await f.close();}
});
test('Bilibili official request signatures follow sorted headers and exact body bytes', () => {
  const body = '{"app_id":1234567890123,"code":"测试"}', headers = signBilibili(body, 'test-id', 'test-secret', { timestamp: 100, nonce: 'fixed' });
  assert.equal(headers['x-bili-content-md5'], createHash('md5').update(body).digest('hex'));
  const names = Object.keys(headers).filter(name => name.startsWith('x-bili-')).sort();
  assert.equal(headers.Authorization, createHmac('sha256', 'test-secret').update(names.map(name => name + ':' + headers[name]).join('\n')).digest('hex'));
});
test('Bilibili binary frames parse batched zlib and Brotli messages and reject truncated packets', () => {
  const a = encodePacket(5, { cmd: 'OPEN_LIVE_DM', data: { msg: '你好' } }), b = encodePacket(8, { code: 0 });
  for (const [version, compressor] of [[2, deflateSync], [3, brotliCompressSync]]) {
    const data = compressor(Buffer.concat([a, b])), packet = Buffer.alloc(16 + data.length); packet.writeUInt32BE(packet.length, 0); packet.writeUInt16BE(16, 4); packet.writeUInt16BE(version, 6); packet.writeUInt32BE(5, 8); data.copy(packet, 16);
    assert.equal(decodePackets(packet)[0].data.data.msg, '你好'); assert.equal(decodePackets(packet)[1].operation, 8);
  }
  assert.throws(() => decodePackets(a.subarray(0, 18)), /PACKET_LENGTH/); assert.throws(() => decodePackets(Buffer.from([1])), /TRUNCATED/);
});
test('Bilibili app lifetime always calls end after a successful start', async () => {
  const calls = []; const adapter = new BilibiliOpenAdapter({ app_id: '1234567890123', identity_code: 'x', access_key: 'a', access_secret: 's' }, { onEvent() {}, onState() {}, fetcher: async (url) => { calls.push(new URL(url).pathname); return { ok: true, json: async () => ({ code: 0, data: { game_info: { game_id: 'game' }, websocket_info: { wss_link: [] } } }) }; } });
  await adapter.start(); await adapter.stop(); assert.deepEqual(calls, ['/v2/app/start', '/v2/app/end']);
});
test('Douyin callback verification matches official vector and detects byte tampering', () => {
  const headers = { 'x-nonce-str': '123456', 'x-timestamp': '456789', 'x-roomid': '268', 'x-msg-type': 'live_gift' };
  assert.equal(douyinSignature(headers, 'abc123你好', '123abc'), 'PDcKhdlsrKEJif6uMKD2dw==');
  const body = Buffer.from('[{"msg_id":"a","sec_open_id":"stable","content":"你好"}]'); headers['x-signature'] = douyinSignature(headers, body, 'secret');
  assert.equal(verifyDouyin(headers, body, 'secret', 456789)[0].room_id, '268');
  assert.throws(() => verifyDouyin(headers, Buffer.from(body.toString() + ' '), 'secret', 456789), /SIGNATURE/);
  assert.throws(() => verifyDouyin(headers, body, 'secret', 999999999), /EXPIRED/);
});
test('companion preparation never reports external streaming as verified', async () => {
  const f = fixture(); try { const result = await f.manager.preflight('douyin'); assert.equal(result.checks.audience_delivery_verified, false); assert.equal(result.checks.stream_target, true); assert.equal(result.obs.connected, false); } finally { await f.close(); }
});
test('platform configuration and event submission work over HTTP without application login', async () => {
  const f = fixture(); const server = createServer(async (req, res) => { try { await f.manager.handle(req, res, new URL(req.url, 'http://localhost'), (data, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); }); } catch (e) { res.writeHead(e.status || 500); res.end(JSON.stringify({ error: e.code || e.message })); } });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve)); const base = 'http://127.0.0.1:' + server.address().port;
  try {
    assert.equal((await (await fetch(base + '/api/dsh/platforms/status')).json()).authentication_required, false);
    const event = f.event(); const response = await fetch(base + '/api/dsh/platforms/events', { method: 'POST', body: JSON.stringify(event) }); assert.equal(response.status, 202); assert.equal((await response.json()).accepted, 1);
    const config = await fetch(base + '/api/dsh/platforms/config', { method: 'POST', body: JSON.stringify({ interaction: { mode: 'echo' } }) }); assert.equal(config.status, 200);
    assert.equal((await config.json()).interaction.mode, 'echo');
  } finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await f.close(); }
});

function nativeOutputFixture(f, { loseStartReply = false } = {}) {
  const calls = []; let streaming = false, statusAvailable = true;
  f.manager.obs = {
    async status() { return { connected: true, streaming, video: { baseWidth: 720, baseHeight: 1280 } }; },
    async setTarget() { calls.push('SetStreamServiceSettings'); }, async projector() { calls.push('OpenVideoMixProjector'); }, close() {},
    async call(name) {
      calls.push(name);
      if (name === 'GetCurrentProgramScene') return { sceneName: f.manager.config.value.obs.scene };
      if (name === 'StartStream') { streaming = true; if (loseStartReply) { statusAvailable = false; throw Object.assign(new Error('reply lost'), { code: 'OBS_TIMEOUT' }); } }
      if (name === 'StopStream') streaming = false;
      if (name === 'GetStreamStatus') { if (!statusAvailable) throw Object.assign(new Error('disconnected'), { code: 'OBS_UNAVAILABLE' }); return { outputActive: streaming }; }
      return {};
    }
  };
  // Independent playback client: claims the real state lease, including the
  // new epoch required when readyBroadcast resumes a paused broadcast.
  const timer = setInterval(() => {
    const broadcast = f.state.current(); if (!broadcast || broadcast.state === 'DRAINING') return;
    const { claim } = f.manager.outputPlayer({ consumer_id: 'obs-fixture', frames: 25, audio_state: 'running' });
    if (claim) f.state.claimAuthority(operator, broadcast.broadcast_id, 'obs-fixture', true);
  }, 10);
  return { calls, allowStatus() { statusAvailable = true; }, stop() { clearInterval(timer); } };
}

test('two platforms share one owned broadcast and only the last output ends it', async () => {
  const f = fixture(), output = nativeOutputFixture(f);
  try {
    f.manager.config.update({ platforms: { bilibili: { output_mode:'obs', stream_server: 'rtmp://127.0.0.1/live', stream_key: 'fixture' } } });
    const first = await f.manager.startOutput('bilibili'), second = await f.manager.startOutput('douyin');
    assert.equal(first.state, 'STREAMING'); assert.equal(second.state, 'COMPANION_READY');
    assert.equal(first.broadcast_id, second.broadcast_id); assert.equal(first.owned_broadcast, 1); assert.equal(second.owned_broadcast, 0);
    assert.equal(f.state.current().state, 'LIVE');
    await f.manager.stopOutput('bilibili'); assert.equal(f.state.current().state, 'LIVE');
    await f.manager.stopOutput('douyin'); assert.equal(f.state.current().state, 'DRAINING');
    assert.equal(output.calls.filter(x => x === 'StartStream').length, 1); assert.equal(output.calls.filter(x => x === 'StopStream').length, 1);
  } finally { output.stop(); await f.close(); }
});

test('a lost OBS start reply retains output ownership until stopping is confirmed', async () => {
  const f = fixture(), output = nativeOutputFixture(f, { loseStartReply: true });
  try {
    f.manager.config.update({ platforms: { bilibili: { output_mode:'obs', stream_server: 'rtmp://127.0.0.1/live', stream_key: 'fixture' } } });
    await assert.rejects(f.manager.startOutput('bilibili'), { code: 'OBS_TIMEOUT' });
    const row = f.manager.store.get('SELECT * FROM outputs WHERE platform=?', 'bilibili');
    assert.equal(row.state, 'ERROR'); assert.equal(row.owned_output, 1); assert.equal(f.state.current().state, 'LIVE');
    await assert.rejects(f.manager.startOutput('bilibili'), { code: 'PLATFORM_OUTPUT_ALREADY_ACTIVE' });
    output.allowStatus(); await f.manager.stopOutput('bilibili');
    assert.equal(f.manager.status().outputs[0].owned_output, 0); assert.equal(f.state.current().state, 'DRAINING');
  } finally { output.stop(); await f.close(); }
});

test('explicit resume preserves the broadcast and reclaims playback after the epoch changes', async () => {
  const f = fixture(), output = nativeOutputFixture(f);
  try {
    const initial = await f.manager.startOutput('douyin'), beforeEpoch = f.state.room().runtime_epoch;
    f.state.pause(operator);
    await assert.rejects(f.manager.ensureSession('douyin'), { code: 'BROADCAST_NOT_STARTABLE' });
    const result = await f.manager.resumeOutput('douyin');
    assert.equal(result.broadcast_id, initial.broadcast_id); assert.equal(result.owned_broadcast, 1); assert.equal(result.state, 'COMPANION_READY');
    assert.equal(f.state.current().state, 'LIVE'); assert.ok(f.state.room().runtime_epoch > beforeEpoch);
    assert.equal(f.state.authorityReady(initial.broadcast_id), true); assert.ok(!output.calls.includes('StartStream'));
  } finally { output.stop(); await f.close(); }
});

test('stopping a platform does not end a broadcast opened by the existing web studio', async () => {
  const f = fixture(), output = nativeOutputFixture(f);
  try {
    f.start(); const id = f.state.current().broadcast_id;
    const row = await f.manager.startOutput('douyin'); assert.equal(row.owned_broadcast, 0);
    await f.manager.stopOutput('douyin'); assert.equal(f.state.current().state, 'LIVE'); assert.equal(f.state.current().broadcast_id, id);
  } finally { output.stop(); await f.close(); }
});

function livehimeFixture(f) {
  const calls = [];
  f.manager.obs = { close() {}, status() { throw Error('Unexpected OBS dependency'); }, prepare() { throw Error('Unexpected OBS preparation'); }, call() { throw Error('Unexpected OBS RPC'); } };
  f.manager.livehime = {
    async prepare() { calls.push('prepare'); return { prepared: true }; },
    async status() { return { client_installed: true, window_open: true, player: { video_width: 720, video_height: 1280, audio_state: 'running' } }; },
    async close() { calls.push('close'); },
  };
  const timer = setInterval(() => {
    const broadcast = f.state.current(); if (!broadcast || broadcast.state === 'DRAINING') return;
    const result = f.manager.outputPlayer({ renderer: 'livehime', consumer_id: 'livehime-fixture', frames: 25, width: 720, height: 1280, audio_state: 'running' });
    if (result.claim) f.state.claimAuthority(operator, broadcast.broadcast_id, 'livehime-fixture', true);
  }, 10);
  return { calls, stop() { clearInterval(timer); } };
}

test('Bilibili defaults to native Livehime while other destinations reject its mode', async () => {
  const f = fixture();
  try {
    assert.equal(f.manager.config.value.platforms.bilibili.output_mode, 'livehime');
    assert.throws(() => f.manager.config.update({ platforms: { douyin: { output_mode: 'livehime' } } }), /OUTPUT_MODE/);
  } finally { await f.close(); }
});

test('native Livehime prepares, checks, starts, resumes and stops without any OBS call', async () => {
  const f = fixture(), output = livehimeFixture(f);
  try {
    assert.equal((await f.manager.prepareOutput('bilibili')).prepared, true);
    assert.equal((await f.manager.preflight('bilibili')).checks.livehime_browser_connected, false);
    f.manager.outputPlayer({ renderer: 'livehime', consumer_id: 'livehime-fixture', frames: 25, width: 720, height: 1280, audio_state: 'running' });
    const preflight = await f.manager.preflight('bilibili');
    assert.equal(preflight.obs_required, false); assert.equal(preflight.obs, undefined);
    assert.equal(preflight.checks.vertical_video, true); assert.equal(preflight.checks.output_audio, true);
    assert.equal(preflight.checks.audience_delivery_verified, false);
    const initial = await f.manager.startOutput('bilibili');
    assert.equal(initial.state, 'COMPANION_READY'); assert.equal(initial.owned_output, 0);
    assert.equal(output.calls.at(-1), 'close');
    assert.equal(f.manager.status().output_player.renderer, 'livehime');
    const lease = f.db.get('SELECT * FROM playback_leases WHERE broadcast_id=?', initial.broadcast_id);
    assert.equal(lease.consumer_id, 'livehime-fixture');
    assert.equal(f.manager.outputPlayer({ renderer: 'obs', consumer_id: 'unused-obs', frames: 10, audio_state: 'running' }).ignored, true);
    assert.equal(f.manager.player.consumer_id, 'livehime-fixture');
    f.state.pause(operator); await f.manager.resumeOutput('bilibili');
    assert.equal(f.state.current().broadcast_id, initial.broadcast_id); assert.equal(f.state.current().state, 'LIVE');
    await f.manager.stopOutput('bilibili');
    assert.equal(f.state.current().state, 'DRAINING'); assert.equal(output.calls.at(-1), 'close');
    assert.equal(f.manager.status().outputs[0].state, 'STOPPED');
  } finally { output.stop(); await f.close(); }
});

test('native output refuses to take over an active OBS platform renderer', async () => {
  const f = fixture(), output = livehimeFixture(f);
  try {
    f.manager.store.setOutput('custom', { state: 'STREAMING', owned_output: true });
    await assert.rejects(f.manager.prepareOutput('bilibili'), { code: 'OUTPUT_RENDERER_CONFLICT' });
    await assert.rejects(f.manager.startOutput('bilibili'), { code: 'OUTPUT_RENDERER_CONFLICT' });
    assert.deepEqual(output.calls, []);
  } finally { output.stop(); await f.close(); }
});

test('failed native preparation preserves an existing studio broadcast and closes its window', async () => {
  const f = fixture(), output = livehimeFixture(f);
  try {
    f.start(); const id = f.state.current().broadcast_id;
    f.manager.livehime.prepare = async () => { throw Object.assign(Error('missing client'), { code: 'LIVEHIME_NOT_INSTALLED' }); };
    await assert.rejects(f.manager.startOutput('bilibili'), { code: 'LIVEHIME_NOT_INSTALLED' });
    assert.equal(f.state.current().broadcast_id, id); assert.equal(f.state.current().state, 'LIVE');
    assert.equal(f.manager.status().outputs[0].state, 'ERROR'); assert.equal(output.calls.at(-1), 'close');
  } finally { output.stop(); await f.close(); }
});

test('split-device preflight follows fresh B-device playback and ignores an A-device preview', async () => {
  const f = fixture();
  try {
    f.manager.config.update({ platforms: { bilibili: { client_location: 'receiver' } } });
    const heartbeat = { renderer: 'livehime', consumer_id: 'receiver-player', frames: 125, width: 720, height: 1280, audio_state: 'running' };
    assert.equal(f.manager.outputPlayer(heartbeat).receiver_required, true);
    assert.equal(f.manager.player, undefined);
    assert.throws(() => f.manager.outputPlayer({ ...heartbeat, receiver_id: '<invalid>' }), /RECEIVER_ID_INVALID/);
    assert.equal(f.manager.player, undefined);
    f.manager.outputPlayer({ ...heartbeat, receiver_id: 'test-b', receiver_client_ready: true });
    const preflight = await f.manager.preflight('bilibili');
    assert.equal(preflight.native.deployment, 'split_device');
    assert.equal(preflight.native.client_installed, true);
    assert.equal(preflight.native.receiver_id, 'test-b');
    assert.equal(preflight.checks.livehime_browser_connected, true);
    assert.equal(f.manager.status().output_player.receiver_id, 'test-b');
    f.advance(7000);
    assert.equal((await f.manager.preflight('bilibili')).native.client_installed, false);
  } finally { await f.close(); }
});
