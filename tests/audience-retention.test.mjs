import test from 'node:test';
import assert from 'node:assert/strict';
import { retentionFixture } from './audience-retention-fixture.mjs';
import { normalizeEvent } from '../backend/platforms/events.mjs';
import { digest } from '../backend/dsh-bridge/channel.mjs';
import { PlatformPrivacy } from '../backend/platforms/privacy.mjs';
import { terminalTask } from './game-narration-fixture.mjs';

test('canonical ownership contains opaque trusted identities and separates same-name viewers', async t => {
  const f = await retentionFixture(t), a = await f.add(), b = await f.add('retention-private-B');
  const rows = f.privacy.ownership.mappings(); assert.equal(rows.length, 2);
  assert.deepEqual(new Set(rows.map(x => x.subject_key)), new Set([a.subject, b.subject]));
  const raw = JSON.stringify(rows); assert(!raw.includes('retention-private')); assert(!raw.includes('同名观众')); assert(!raw.includes('茶'));
  const relay = normalizeEvent('bilibili', { type: 'comment', room_id: '100', event_id: 'untrusted', user_id: 'invented', text: '伪造身份' }, { source: 'local_relay', now: f.manager.wall() });
  assert.equal(f.privacy.ownership.record([relay]), 0);
});

test('ownership storage failure rolls back the complete platform batch before Room receives it', async t => {
  const f = await retentionFixture(t), original = f.privacy.ownership.record;
  f.privacy.ownership.record = () => { throw Object.assign(new Error('disk'), { code: 'SQLITE_FULL' }); };
  assert.throws(() => f.platforms.ingest('bilibili', [{ type: 'comment', room_id: '100', event_id: 'a', user_id: 'A', text: '第一条' }, { type: 'comment', room_id: '100', event_id: 'b', user_id: 'B', text: '第二条' }], { source: 'blivedm' }), /disk/);
  assert.equal(f.platforms.store.get('SELECT COUNT(*) n FROM events').n, 0);
  assert.equal(f.room.store.one('SELECT COUNT(*) n FROM messages').n, 0);
  f.privacy.ownership.record = original;
});

test('conflicting canonical ownership fails closed without replacing its owner', async t => {
  const f = await retentionFixture(t), a = await f.add(), owner = f.privacy.ownership.mappings()[0];
  const key = f.privacy.ownership.prefix + owner.room_user_key;
  f.db.tx(() => f.db.run('UPDATE runtime_meta SET value_json=? WHERE key=?', JSON.stringify({ ...owner, subject_key: 'viewer:bilibili:' + '0'.repeat(40) }), key));
  assert.throws(() => f.privacy.ownership.record([a.row]), { code: 'AUDIENCE_OWNER_CONFLICT' });
  assert.equal(f.privacy.ownership.mappings()[0].subject_key, 'viewer:bilibili:' + '0'.repeat(40));
});

test('raw platform pruning retains enough ownership to delete the remaining minimum Room history', async t => {
  const f = await retentionFixture(t), a = await f.add(), b = await f.add('retention-private-B'); f.age([a.key, b.key]);
  const result = f.privacy.retention.run(); assert.equal(result.last_run.platform_events_removed, 2);
  assert(f.room.store.message(a.key)); assert(f.room.store.message(b.key));
  await f.remove(a); assert.equal(f.room.store.message(a.key), null); assert(f.room.store.message(b.key));
  assert.equal(f.admin.privacyPending, false);
});

test('a durable account deletion plan carries aliases even when its ownership index is absent after restore', async t => {
  const f = await retentionFixture(t), a = await f.add(); f.age([a.key]); f.privacy.retention.run();
  const plan = f.privacy.prepare({ subject: a.subject, sources: [] });
  assert.equal(plan.room_user_keys.length, 1);
  f.db.tx(() => f.db.run('DELETE FROM runtime_meta WHERE key LIKE ?', f.privacy.ownership.prefix + '%'));
  await f.privacy.apply(plan); assert.equal(f.room.store.message(a.key), null);
});

test('selected ordinary-platform memory still resolves its exact event after raw event pruning', async t => {
  const f = await retentionFixture(t), a = await f.add();
  const request = f.state.accept({ role: 'viewer', principal_id: a.subject.slice(7), viewer_id: a.subject }, {
    text: '我喜欢茶。', idempotency_key: 'retention-ordinary-source', source: { platform: 'bilibili', room_id: '100', event_id: a.row.event_id, collector: 'blivedm' },
  });
  const source = f.memory.eligibleEvents(request.broadcast_id, a.subject).find(x => x.event_seq === request.input_event_seq);
  const memory = f.seed(a.subject, source); f.state.cancel(request.request_id, 'FIXTURE_DONE');
  const later = await f.add(); f.age([a.key]); f.privacy.retention.run();
  await f.remove(a, { memory_id: memory.memory_id });
  assert.equal(f.room.store.message(a.key), null); assert(f.room.store.message(later.key));
});

test('trusted receive time removes a future-occurrence historical message during deletion replay', async t => {
  const f = await retentionFixture(t), a = await f.add(), now = f.manager.wall();
  f.platforms.store.run('UPDATE events SET occurred_at=? WHERE event_key=?', now + 100000, a.key);
  const value = f.room.store.message(a.key); value.occurred_at = now + 100000;
  f.room.store.run('UPDATE messages SET value=? WHERE id=?', JSON.stringify(value), a.key);
  const plan = { ...f.privacy.prepare({ subject: a.subject, sources: [] }), event_keys: [] };
  await f.privacy.apply(plan); assert.equal(f.room.store.message(a.key), null);
});

test('Room time retention keeps the newest 500 and pruning withdraws linked pending narration', async t => {
  const f = await retentionFixture(t), a = await f.add(); f.age([a.key]); f.fillRoom(501);
  const candidate = f.manager.narration.all().find(x => x.source_ids.includes(a.key)); assert(candidate);
  let snapshots = 0; const emit = f.room.emit.bind(f.room); f.room.emit = (name, value) => { if (name === 'snapshot') snapshots++; return emit(name, value); };
  const result = f.privacy.retention.run(); assert.equal(result.last_run.room_messages_removed, 1);
  assert.equal(f.room.store.message(a.key), null); assert.equal(f.manager.narration.get(candidate.narration_id).state, 'discarded');
  assert(snapshots > 0);
});

test('Room count retention is deterministic, bounded and resumes until only 5000 recent rows remain', async t => {
  const f = await retentionFixture(t); f.fillRoom(6105);
  const first = f.privacy.retention.run(); assert.equal(first.last_run.room_messages_removed, 1000); assert.equal(first.last_run.status, 'remaining');
  const second = f.privacy.retention.run(); assert.equal(second.last_run.room_messages_removed, 105); assert.equal(second.last_run.status, 'completed');
  assert.equal(f.room.store.one('SELECT COUNT(*) n FROM messages').n, 5000);
});

test('pinned messages and active speech sources survive both platform and Room cleanup', async t => {
  const f = await retentionFixture(t), a = await f.add(), b = await f.add('retention-private-B');
  f.room.board.pinned_id = a.key;
  const request = f.state.accept(f.bridge.auth.resolve(), { text: '正在回复', public_input: true, idempotency_key: 'retention-active-speech' });
  f.room.trackSpeech(request.request_id, b.key); f.age([a.key, b.key]); f.fillRoom(501);
  f.privacy.retention.run();
  for (const key of [a.key, b.key]) { assert(f.room.store.message(key)); assert(f.platforms.store.get('SELECT * FROM events WHERE event_key=?', key)); }
});

test('unresolved game effects keep their audience sources even when a task says failed', async t => {
  const f = await retentionFixture(t), a = await f.add(); f.age([a.key]); f.fillRoom(501);
  f.manager.store.transaction(() => f.manager.store.put('suggestion', { suggestion_id: 'retention-unresolved', task_id: 'missing-task', source_event_ids: [a.key] }));
  const get = f.manager.tasks.get.bind(f.manager.tasks);
  f.manager.tasks.get = id => id === 'missing-task' ? { state: 'failed', effect_status: 'unknown', recovery: { status: 'required' } } : get(id);
  f.privacy.retention.run(); assert(f.room.store.message(a.key)); assert(f.platforms.store.get('SELECT * FROM events WHERE event_key=?', a.key));
});

test('ownership must commit before any legacy raw event can be pruned', async t => {
  const f = await retentionFixture(t), a = await f.add(); f.age([a.key]);
  const original = f.privacy.ownership.record; f.privacy.ownership.record = () => { throw Object.assign(new Error('canonical full'), { code: 'SQLITE_FULL' }); };
  assert.throws(() => f.privacy.retention.run(), /canonical full/);
  assert(f.platforms.store.get('SELECT * FROM events WHERE event_key=?', a.key));
  assert.equal(f.privacy.retention.status().last_run.status, 'failed'); f.privacy.ownership.record = original;
  assert.equal(f.privacy.retention.run().last_run.status, 'completed');
});

test('a Room failure after platform deletion remains diagnosable and the same ownership survives retry', async t => {
  const f = await retentionFixture(t), a = await f.add(); f.age([a.key]);
  const prune = f.room.pruneHistory; f.room.pruneHistory = () => { throw Object.assign(new Error('room busy'), { code: 'SQLITE_BUSY' }); };
  assert.throws(() => f.privacy.retention.run(), /room busy/);
  assert.equal(f.privacy.retention.status().last_run.platform_events_removed, 1);
  assert.equal(f.privacy.retention.status().last_run.status, 'failed'); assert.equal(f.privacy.ownership.count(), 1);
  f.room.pruneHistory = prune; f.privacy.retention.run(); await f.remove(a); assert.equal(f.room.store.message(a.key), null);
  assert.deepEqual(f.privacy.retention.status().recent_runs.map(row => row.status), ['failed','completed']);
});

test('maintenance blocks during privacy recovery without replacing the last completed report', async t => {
  const f = await retentionFixture(t); f.privacy.retention.run(); const before = f.privacy.retention.status();
  const old = f.bridge.administration; f.bridge.administration = { locked: false, privacyPending: true };
  assert.throws(() => f.privacy.retention.run(), { code: 'AUDIENCE_RETENTION_BUSY' });
  assert.equal(f.privacy.retention.status().last_run.run_id, before.last_run.run_id); f.bridge.administration = old;
});

test('maintenance reports historical ownership gaps without inventing an account or exposing text', async t => {
  const f = await retentionFixture(t); f.fillRoom(1);
  const row = f.room.store.one('SELECT * FROM messages'), value = JSON.parse(row.value);
  Object.assign(value, { platform: 'bilibili', user_key: digest('unknown-legacy'), text: 'private-legacy-body' });
  f.room.store.run('UPDATE messages SET value=? WHERE id=?', JSON.stringify(value), row.id);
  const result = f.privacy.retention.run(); assert.equal(result.last_run.unmapped_room_messages, 1);
  assert(!JSON.stringify(result).includes('private-legacy-body')); assert.equal(result.ownership_records, 0);
});

test('real maintenance HTTP API remains public and rejects attempts to alter retention limits', async t => {
  const f = await retentionFixture(t); await f.serve();
  assert.equal((await f.maintenance()).status, 200);
  for (const body of [null, [], { cutoff: 0 }, { limit: 1 }]) assert.equal((await f.maintenance(body)).status, 400);
  const done = await f.maintenance({}); assert.equal(done.status, 200); assert.equal(done.value.last_run.status, 'completed');
  const status = await f.maintenance(undefined, '/status'); assert.equal(status.value.authentication_required, false); assert.equal(status.value.history_retention.last_run.run_id, done.value.last_run.run_id);
});

test('Room expiry retracts actual suggestion support and votes without deleting a previously completed task', async t => {
  const f = await retentionFixture(t), a = await f.add(undefined, '建议 采集 minecraft:oak_log 4');
  const suggestion = f.manager.suggestions.page().items[0]; assert.equal(suggestion.support.visible_events, 1);
  const s = f.manager.state.value, vote = f.manager.votes.create({ request_id: 'retention-vote', bridge_boot_id: s.bridge_boot_id, world_session_id: s.world_session_id,
    title: '采什么', duration_seconds: 60, options: [{ option_id: 'wood', label: '木头', goal: { skill: 'gather', item_id: 'minecraft:oak_log', count: 4 } }, { option_id: 'stone', label: '石头', goal: { skill: 'gather', item_id: 'minecraft:cobblestone', count: 4 } }] }).value;
  const b = await f.add('retention-private-B', '投票 wood'); assert.equal(f.manager.votes.get(vote.vote_id).options[0].votes, 1);
  const { task } = await terminalTask(f), before = f.manager.tasks.get(task.task_id);
  f.age([a.key, b.key]); f.fillRoom(501); f.privacy.retention.run();
  assert.equal(f.manager.suggestions.get(suggestion.suggestion_id).support.visible_events, 0);
  assert.equal(f.manager.suggestions.get(suggestion.suggestion_id).state, 'cancelled');
  assert.equal(f.manager.votes.get(vote.vote_id).options[0].votes, 0);
  assert.deepEqual(f.manager.tasks.get(task.task_id), before);
});

test('platform pruning backfills legacy ownership and continues after a bounded 1000-row batch', async t => {
  const f = await retentionFixture(t), at = f.manager.wall() - 8 * 86400000;
  f.platforms.store.db.exec('BEGIN IMMEDIATE');
  for (let i = 0; i < 1001; i++) {
    const e = normalizeEvent('bilibili', { type: 'gift', room_id: '100', event_id: 'legacy-' + i, user_id: 'old-owner' }, { source: 'blivedm', now: f.manager.wall() });
    f.platforms.store.insert(e, 'OBSERVED'); f.platforms.store.run('UPDATE events SET received_at=? WHERE event_key=?', at, e.event_key);
  }
  f.platforms.store.db.exec('COMMIT'); assert.equal(f.privacy.ownership.count(), 0);
  const first = f.privacy.retention.run(); assert.equal(first.last_run.platform_events_removed, 1000); assert(first.last_run.more); assert.equal(first.ownership_records, 1);
  const last = f.privacy.retention.run(); assert.equal(last.last_run.platform_events_removed, 1); assert.equal(last.last_run.status, 'completed');
});

test('maintenance report and canonical ownership are scoped to the actual bound character-room', async t => {
  const f = await retentionFixture(t); await f.add(); f.privacy.retention.run();
  const other = new PlatformPrivacy({ ...f.bridge, state: { characterRoom: ['female-a', 'another-room'] } });
  assert.equal(other.retention.status().last_run, null); assert.equal(other.ownership.count(), 0);
  assert(f.privacy.retention.status().last_run); assert.equal(f.privacy.ownership.count(), 1);
});

test('an interrupted persisted run stays explicit and the diagnostic history is bounded to 20 runs', async t => {
  const f = await retentionFixture(t), retention = f.privacy.retention;
  retention.save({ run_id: 'interrupted-run', status: 'running', phase: 'room', platform_events_removed: 1, room_messages_removed: 0 });
  assert.equal(retention.status().last_run.status, 'interrupted');
  assert.equal(retention.status().recent_runs[0].status, 'interrupted');
  retention.run(); assert.equal(retention.status().recent_runs[0].status, 'interrupted');
  for (let i = 0; i < 21; i++) retention.run();
  const state = retention.status(); assert.equal(state.recent_runs.length, 20); assert(state.recent_runs.every(row => row.status === 'completed'));
});
