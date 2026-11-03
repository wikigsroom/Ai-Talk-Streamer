import assert from 'node:assert/strict';
import { join } from 'node:path';
import { gameFixture, until, sourceRoot } from './game-fixture.mjs';
import { StateStore } from '../backend/memory/store.mjs';
import { StreamState } from '../backend/dsh-bridge/state.mjs';
import { StreamBridge } from '../backend/dsh-bridge/server.mjs';
import { Auth } from '../backend/dsh-bridge/auth.mjs';
import { loadPolicy } from '../backend/dsh-bridge/policy.mjs';
import { digest } from '../backend/dsh-bridge/channel.mjs';
import { RoomManager } from '../backend/room/manager.mjs';
import { PlatformManager } from '../backend/platforms/manager.mjs';
import { PlatformStore } from '../backend/platforms/store.mjs';

export async function narrationFixture(t, generate, { ui = false } = {}) {
  const f = await gameFixture({ fakeClock: true, ui }), game = await f.connect(), b = f.bridge;
  // Keep the production request lifecycle when borrowing bridge request methods.
  Object.setPrototypeOf(b, StreamBridge.prototype);
  const db = new StateStore(':memory:', { now: () => f.manager.wall(), heartbeat: false }), loaded = loadPolicy(sourceRoot);
  const policy = { ...loaded, deployment: { ...loaded.deployment, state_relative_path: b.policy.deployment.state_relative_path } };
  const state = new StreamState(db, policy, 'persona-test'), auth = new Auth(f.folder, db, state);
  Object.assign(b, { db, state, auth, policy, ready: true, administration: { locked: false }, controllers: new Map(),
    channel: { snapshot: () => ({ revision: 'fixture', model: 'fixture' }) }, health: () => ({ persona_injection_ready: true }),
    memory: { context: () => '{}', recall: () => ({}), propose: () => ({ pending: true }) },
    onCall: () => () => {}, recordProbe() {}, tick: async () => {}, mediaChain: Promise.resolve() });
  const room = new RoomManager(f.folder, b, { now: () => f.manager.wall() }); b.room = room;
  const config = { value: { interaction: { enabled: true, mode: 'chat', ttl_ms: 30000, max_pending: 100, minimum_interval_ms: 0, viewer_cooldown_ms: 0 }, platforms: { bilibili: { room_id: '100' } } } };
  const platforms = new PlatformManager(f.folder, b, { config, store: new PlatformStore(join(f.folder, 'platforms.sqlite3'), () => f.manager.wall()), now: () => f.manager.wall() }); b.platforms = platforms;
  const broadcast = state.createBroadcast(auth.resolve()), lease = state.claimAuthority(auth.resolve(), broadcast.broadcast_id, 'formal-fixture'); state.readyBroadcast(broadcast.broadcast_id, true);
  const media = [], calls = [];
  b.host = { generate: async options => { calls.push(options); return generate ? generate(options, f) : { text: '我会继续留意游戏里的变化。' }; } };
  b.mediaCommand = async (action, body) => { media.push({ action, ...body }); return { accepted: true }; };
  state.on('cancel', barrier => b.controllers.get(barrier.request_id)?.abort());
  const originalClose = f.close.bind(f);
  f.close = async () => { await f.manager.close(); await room.close(); platforms.store.close(); db.close(); await originalClose(); };
  t.after(() => f.close());
  let eventSeq = 0;
  return Object.assign(f, { game, db, state, lease, room, platforms, media, calls,
    async comment(text = '现在有多少木头？', extra = {}) {
      const id = 'comment-' + (++eventSeq), result = platforms.ingest('bilibili', { type: 'comment', room_id: '100', event_id: id, user_id: 'viewer-' + eventSeq, nickname: '观众', text, occurred_at: f.manager.wall(), ...extra }, { source: 'blivedm' });
      await platforms.dispatch(); const key = result.results[0].event_key;
      return { key, item: f.manager.narration.all().find(item => (item.source_ids || [item.source_id]).includes(key)) };
    },
    async run() { f.manager.narration.tick(); const request = state.activate(); if (request) await StreamBridge.prototype.processRequest.call(b, request); return request; },
    advanceClock(ms) { db.tx(() => db.run('UPDATE bridge_owner SET lease_until=?', f.manager.wall() + ms + 30000)); f.advance(ms); },
    complete(utterance = media.at(-1)) {
      state.audioReady({ ...utterance, valid_sample_count: 640, audio_sha256: digest('fixture-audio') });
      state.mediaMap({ ...utterance, valid_sample_count: 640, transport_instance_id: 'fixture-transport', ranges: [{ packet_seq: 1, packet_offset: 0, sample_start: 0, sample_count: 640 }], final: true });
      const receipt = { ...utterance, consumer_id: lease.consumer_id, lease_id: lease.lease_id, authority_epoch: lease.authority_epoch, receipt_sequence: media.length, contiguous_played_samples: 640, natural_end: true, transport_instance_id: 'fixture-transport' };
      const result = state.receipt(auth.resolve(), receipt); f.manager.narration.sweep(); return { result, receipt };
    }
  });
}

export async function terminalTask(f, { outcome = 'succeeded', requestPatch = {}, reason } = {}) {
  if (f.manager.state.value.mode !== 'AUTO') await f.game.auto();
  f.taskIndex = (f.taskIndex || 0) + 1;
  const response = await f.api('/tasks', { ...f.game.request(undefined, 'narration-task-' + f.taskIndex), ...requestPatch });
  assert.equal(response.status, 202);
  const task = response.value;
  await f.game.next('task_start', message => message.payload.task_id === task.task_id);
  assert.equal(f.manager.narration.taskFeedback(task.task_id), null, 'acceptance is not a result');
  f.reliableSeq = (f.reliableSeq || 0) + 1;
  f.game.send('task_update', { delivery_seq: f.reliableSeq, transition_seq: 2, task: { ...task, state: 'running', version: 2 } });
  await until(() => f.manager.tasks.get(task.task_id).state === 'running');
  assert.equal(f.manager.narration.taskFeedback(task.task_id), null, 'running is not a result');
  const result = { ...task, state: outcome, version: 3, effect_status: outcome === 'succeeded' ? 'verified' : 'partial',
    reason: outcome === 'succeeded' ? null : reason ?? 'FIXTURE_' + outcome.toUpperCase(), evidence: [{ world_session_id: task.world_session_id,
      seq: f.manager.state.value.seq, kind: 'inventory', summary: 'TEST_FIXTURE_ONLY verified or partial effects' }] };
  const frame = { delivery_seq: ++f.reliableSeq, transition_seq: 3, task: result };
  f.game.send('task_update', frame); await until(() => f.manager.tasks.get(task.task_id).version === 3);
  const item = f.manager.narration.taskFeedback(task.task_id); assert(item);
  return { task: result, item, frame };
}

