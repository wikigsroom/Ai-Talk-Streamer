import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fixture } from './room-fixture.mjs';
import { patchSettings, DEFAULTS } from '../backend/room/defaults.mjs';
import { normalizeEvent } from '../backend/platforms/events.mjs';
import { uploadAudio } from '../backend/room/media.mjs';

test('room config validates keys, numeric bounds and compare-and-swap revisions atomically', async () => {
  const f = await fixture(); try {
    assert.throws(() => patchSettings(DEFAULTS, { audio: { music_volume: NaN } })); assert.throws(() => patchSettings(DEFAULTS, { __bad: {} }));
    assert.throws(() => patchSettings(DEFAULTS, { filters: { brightness: 9 } }));
    let r = await f.post('config', { expected_revision: 1, patch: { audio: { music_volume: .4 }, identity: { topic: '新的话题' } } }); assert.equal(r.status, 200); assert.equal(r.value.revision, 2);
    r = await f.post('config', { expected_revision: 1, patch: { audio: { music_volume: .9 } } }); assert.equal(r.status, 409); assert.equal(f.manager.store.settings.audio.music_volume, .4);
    r = await f.post('config', { expected_revision: 2, patch: { audio: { muted: true, music_volume: 2 } } }); assert.equal(r.status, 400); assert.equal(f.manager.store.settings.audio.muted, false);
  } finally { await f.close(); }
});
test('playlist play/pause/seek, ordering, repeat and invalid inputs preserve state', async () => {
  const f = await fixture(); try {
    let r = await f.post('music', { action: 'play', track_id: 'window-breeze' }); assert.equal(r.value.music.playing, true); assert.equal(r.value.music.track_id, 'window-breeze');
    r = await f.post('music', { action: 'seek', seconds: 10 }); assert.ok(r.value.music.position >= 10 && r.value.music.position < 11);
    await f.post('music', { action: 'pause' }); assert.equal(f.manager.music.playing, false);
    assert.equal((await f.post('music', { action: 'seek', seconds: -5 })).status, 400);
    const ids = f.manager.tracks().map(t => t.id).reverse(); await f.post('music', { action: 'order', ids }); assert.deepEqual(f.manager.tracks().map(t => t.id), ids);
    assert.equal((await f.post('tracks/delete', { id: ids[0] })).status, 400); assert.equal((await f.post('music', { action: 'repeat', value: 'forever' })).status, 400);
  } finally { await f.close(); }
});
test('new platform comments and gifts deduplicate, retain metadata, and moderation removes active board', async () => {
  const f = await fixture(); try {
    const e = normalizeEvent('bilibili', { type: 'gift', event_id: 'gift-1', uid: 7, nickname: '测试昵称', room_id: '1', gift_name: '鲜花', gift_count: 6 });
    f.manager.acceptPlatformEvent(e); f.manager.acceptPlatformEvent(e); assert.equal(f.manager.store.recent().length, 1); assert.equal(f.manager.store.recent()[0].gift_count, 6);
    const m = f.manager.store.recent()[0]; await f.post('messages', { action: 'feature', id: m.id }); assert.equal(f.manager.snapshot().board.featured.id, m.id);
    await f.post('config', { expected_revision: 1, patch: { moderation: { blocked_names: ['测试昵称'] } } }); assert.equal(f.manager.snapshot().board.featured, null); assert.equal(f.manager.blocked(e), true);
    const sc = normalizeEvent('bilibili', { cmd: 'SUPER_CHAT_MESSAGE', data: { id: 'sc1', uid: 8, room_id: '1', message: '支持知夏', user_info: { uname: 'SC观众' } } });
    assert.equal(sc.type, 'comment'); assert.equal(sc.notice_kind, 'superchat'); assert.equal(sc.nickname, 'SC观众');
    assert.equal(normalizeEvent('bilibili', { type: 'gift', room_id: '1', gift_count: 'oops' }).gift_count, 1);
    assert.equal(normalizeEvent('bilibili', { type: 'comment', room_id: '1', test: true }).test, true);
    assert.equal(normalizeEvent('bilibili', { type: 'comment', room_id: '1', test: true }, { source: 'blivedm' }).test, false);
  } finally { await f.close(); }
});
test('message board can create, pin, hide, mark answered and clear test data without changing real messages', async () => {
  const f = await fixture(); try {
    await f.post('messages', { action: 'create', text: '<script>not HTML</script>', feature: true }); const m = f.manager.store.recent()[0];
    await f.post('messages', { action: 'pin', id: m.id }); assert.equal(f.manager.snapshot().board.pinned.text, '<script>not HTML</script>');
    await f.post('messages', { action: 'hide', id: m.id }); assert.equal(f.manager.snapshot().board.featured, null);
    await f.post('messages', { action: 'restore', id: m.id }); await f.post('messages', { action: 'answered', id: m.id }); assert.equal(f.manager.store.message(m.id).answered, true);
    await f.post('test-event', { type: 'gift' }); await f.post('messages', { action: 'clear_tests' }); assert.equal(f.manager.store.recent().length, 1);
  } finally { await f.close(); }
});
test('SSE reconnect begins with snapshot; old gift messages are data, never replay events', async () => {
  const f = await fixture(); const abort = new AbortController(); try {
    await f.post('test-event', { type: 'gift' }); const res = await fetch(f.base + '/api/dsh/room/events', { signal: abort.signal, headers: { 'Last-Event-ID': 'previous-process:900' } });
    const reader = res.body.getReader(), text = new TextDecoder().decode((await reader.read()).value); assert.match(text, /event: snapshot/); assert.doesNotMatch(text, /event: message/); assert.match(text, /"gift_name":"小星星"/); await reader.cancel();
  } finally { abort.abort(); await f.close(); }
});
test('audio endpoint serves exact bounded byte ranges and rejects invalid ranges', async () => {
  const f = await fixture(); try {
    const url = f.base + '/api/dsh/room/audio/daylight-notes'; let r = await fetch(url, { headers: { Range: 'bytes=0-43' } }); assert.equal(r.status, 206); assert.equal((await r.arrayBuffer()).byteLength, 44); assert.match(r.headers.get('content-range'), /^bytes 0-43\//);
    r = await fetch(url, { headers: { Range: 'bytes=999999999-' } }); assert.equal(r.status, 416);
    r = await fetch(url, { headers: { Range: 'bytes=-12' } }); assert.equal((await r.arrayBuffer()).byteLength, 12);
    assert.equal((await fetch(url, { method: 'HEAD' })).status, 200);
  } finally { await f.close(); }
});
test('upload streams validate names/size and remove partials when audio probing fails', async () => {
  const f = await fixture(); try {
    function request() { const r = Readable.from([Buffer.alloc(100)]); r.headers = {}; return r; }
    await assert.rejects(uploadAudio(f.folder, request(), '../bad.wav'), /AUDIO_NAME_INVALID/);
    await assert.rejects(uploadAudio(f.folder, request(), 'bad.wav', async () => { throw Error('INVALID_AUDIO'); }), /INVALID_AUDIO/);
    const folder = join(f.folder, 'assets/custom/room-bgm'); assert.deepEqual(readdirSync(folder), []);
    const t = await uploadAudio(f.folder, request(), 'valid.wav', async () => 2); assert.equal(t.bytes, 100); assert.equal(t.sha256.length, 64); assert.ok(existsSync(t.path));
  } finally { await f.close(); }
});
test('private agent uses persona host and budget, does not speak or mutate viewer memory', async () => {
  let options; const f = await fixture({ generate: async o => { options = o; return { text: '这是后台建议。' }; } }); try {
    const result = await f.post('agent', { action: 'ask', text: '给我一个开场话题' }); assert.equal(result.status, 202);
    for (let i = 0; i < 30 && f.manager.agentJob.status === 'RUNNING'; i++) await new Promise(r => setTimeout(r, 5));
    assert.equal(f.manager.agentJob.status, 'COMPLETED'); assert.equal(f.accepted.length, 0); assert.equal(f.manager.agentHistory().at(-1).text, '这是后台建议。');
    const context = JSON.parse(options.context); assert.equal(context.humanity_public_snapshot.memory_ids.length, 0); assert.equal((await options.tools('stream_memory_propose', {})).memory_write_enabled, false); assert.equal(typeof options.onCall, 'function');
    const nativeSession = options.sessionId, logicalSession = f.manager.agentSession;
    await f.post('agent', { action: 'ask', text: '接着给我一句自然的过渡' });
    for (let i = 0; i < 30 && f.manager.agentJob.status === 'RUNNING'; i++) await new Promise(r => setTimeout(r, 5));
    assert.equal(f.manager.agentJob.status, 'COMPLETED'); assert.notEqual(options.sessionId, nativeSession);
    assert.equal(f.manager.agentSession, logicalSession); assert.equal(f.manager.agentHistory().length, 4);
    assert.ok(JSON.parse(options.context).operator_history.some(m => m.role === 'assistant' && m.text === '这是后台建议。'));
    assert.equal(f.accepted.length, 0);
    const old = f.manager.agentSession; await f.post('agent', { action: 'new' }); assert.notEqual(f.manager.agentSession, old); assert.equal(f.manager.agentHistory().length, 0);
  } finally { await f.close(); }
});
test('agent cancellation fences late model replies', async () => {
  let finish; const f = await fixture({ generate: () => new Promise(r => { finish = r; }) }); try {
    await f.post('agent', { action: 'ask', text: '请等待' }); await f.post('agent', { action: 'cancel' }); finish({ text: '应当丢弃的回复' }); await new Promise(r => setTimeout(r, 10)); assert.equal(f.manager.agentJob.status, 'CANCELLED'); assert.equal(f.manager.agentHistory().length, 1);
  } finally { await f.close(); }
});
test('broadcast speech is explicit and requires live state; panic cancels and mutes without playing later', async () => {
  const f = await fixture(); try {
    assert.equal((await f.post('speak', { text: '你好' })).status, 409);
    await fetch(f.base + '/api/dsh/platforms/bilibili/start', { method: 'POST' }); assert.equal((await f.post('speak', { text: '你好', mode: 'echo', idempotency_key: 'once' })).status, 202); assert.equal(f.accepted.length, 1);
    f.bridge.state.active = () => ({ request_id: 'active-1' }); f.bridge.state.status = () => ({ queued: [{ request_id: 'queued-1' }] }); await f.post('music', { action: 'play' }); await f.post('panic', {});
    assert.equal(f.manager.music.playing, false); assert.equal(f.manager.store.settings.audio.muted, true); assert.deepEqual(f.cancelled.map(c => c[0]), ['queued-1', 'active-1']);
  } finally { await f.close(); }
});
test('only official program consumer may report bounded mixer observations', async () => {
  const f = await fixture(); try {
    assert.equal((await f.post('player', { consumer_id: 'admin-preview' })).status, 409);
    const r = await f.post('player', { consumer_id: 'fixture-program', current_time: 7, music_gain: -5, arbitrary: 'ignore', audio_state: 'running' }); assert.equal(r.status, 200); const p = f.manager.snapshot().player; assert.equal(p.current_time, 7); assert.equal(p.music_gain, undefined); assert.equal(p.arbitrary, undefined);
  } finally { await f.close(); }
});
