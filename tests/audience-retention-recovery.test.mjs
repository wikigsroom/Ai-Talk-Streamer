import test from 'node:test';
import assert from 'node:assert/strict';
import { retentionFixture } from './audience-retention-fixture.mjs';
import { StreamBridge } from '../backend/dsh-bridge/server.mjs';

async function ballot(f) {
  const state = f.manager.state.value;
  const vote = f.manager.votes.create({ request_id: 'retention-recovery-vote', bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id,
    title: '恢复测试', duration_seconds: 60, options: [{ option_id: 'wood', label: '木头', goal: { skill: 'gather', item_id: 'minecraft:oak_log', count: 4 } }, { option_id: 'stone', label: '石头', goal: { skill: 'gather', item_id: 'minecraft:cobblestone', count: 4 } }] }).value;
  const a = await f.add(undefined, '投票 wood'); f.age([a.key]); f.fillRoom(501);
  return { a, vote };
}

test('a committed Room prune replays its durable withdrawal after the game-store projection fails', async t => {
  const f = await retentionFixture(t), { a, vote } = await ballot(f), original = f.manager.votes.withdrawSources;
  f.manager.votes.withdrawSources = () => { throw Object.assign(new Error('game store full'), { code: 'SQLITE_FULL' }); };
  assert.throws(() => f.privacy.retention.run(), /game store full/);
  assert.equal(f.room.store.message(a.key), null);
  assert(f.room.store.get('retention_withdrawal', []).includes(a.key));
  assert.equal(f.manager.votes.get(vote.vote_id).options[0].votes, 1);
  f.manager.votes.withdrawSources = original;
  const result = f.privacy.retention.run();
  assert.equal(f.manager.votes.get(vote.vote_id).options[0].votes, 0);
  assert.deepEqual(f.room.store.get('retention_withdrawal', []), []);
  assert(result.last_run.room_sources_replayed >= 1);
});

test('a snapshot publication failure keeps the withdrawal record until a successful retry', async t => {
  const f = await retentionFixture(t), a = await f.add(); f.age([a.key]); f.fillRoom(501);
  const original = f.room.emit;
  f.room.emit = function(name, value) { if (name === 'snapshot') throw new Error('snapshot publication fault'); return original.call(this, name, value); };
  assert.throws(() => f.privacy.retention.run(), /snapshot publication fault/);
  assert(f.room.store.get('retention_withdrawal', []).includes(a.key));
  f.room.emit = original; f.privacy.retention.run();
  assert.deepEqual(f.room.store.get('retention_withdrawal', []), []); assert.equal(f.room.store.message(a.key), null);
});

test('lazy game loading replays committed Room withdrawals before starting its services', async t => {
  const f = await retentionFixture(t), { a, vote } = await ballot(f), original = f.manager.votes.withdrawSources;
  f.manager.votes.withdrawSources = () => { throw new Error('persist before restart'); };
  assert.throws(() => f.privacy.retention.run(), /persist before restart/); f.manager.votes.withdrawSources = original;
  await f.manager.close(); f.bridge.game = null; f.bridge.gameLoading = null;
  const loaded = await StreamBridge.prototype.loadGame.call(f.bridge);
  try {
    assert.equal(loaded.votes.get(vote.vote_id).options[0].votes, 0);
    assert.deepEqual(f.room.store.get('retention_withdrawal', []), []); assert.equal(f.room.store.message(a.key), null);
  } finally { await loaded.close(); }
});

test('maintenance refuses to prune an existing game ledger whose dependencies are not loaded', async t => {
  const f = await retentionFixture(t), a = await f.add(); f.age([a.key]); f.fillRoom(501);
  f.bridge.game = null;
  try {
    assert.throws(() => f.privacy.retention.run(), { code: 'AUDIENCE_RETENTION_GAME_UNAVAILABLE' });
    assert(f.room.store.message(a.key)); assert(f.platforms.store.get('SELECT * FROM events WHERE event_key=?', a.key));
  } finally { f.bridge.game = f.manager; }
});

test('a resumed maintenance response marks an older unfinished run interrupted, even before its own finally block', async t => {
  const f = await retentionFixture(t), retention = f.privacy.retention;
  retention.save({ run_id: 'older-run', status: 'running', phase: 'room', platform_events_removed: 1, room_messages_removed: 0 });
  assert.equal(retention.run().recent_runs[0].status, 'interrupted');
});
