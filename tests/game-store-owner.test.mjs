import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { GameStore } from '../backend/game/store.mjs';
import { narrationFixture } from './game-narration-fixture.mjs';
import { until } from './game-fixture.mjs';

function fixture(t) {
  const root = resolve('outputs/mc-tests/store-owner'); mkdirSync(root, { recursive: true });
  const folder = mkdtempSync(join(root, 'owner-')), store = new GameStore(join(folder, 'game.sqlite3'));
  t.after(() => {
    store.close(); const within = relative(root, folder);
    assert(within && !within.startsWith('..') && resolve(folder) !== root);
    rmSync(folder, { recursive: true, force: true });
  });
  return store;
}

function clock(t, now) {
  const original = Date.now; let current = now;
  Date.now = () => current; t.after(() => { Date.now = original; });
  return value => { current = value; };
}

test('sustained synchronous owned writes remain valid beyond the first lease without waiting for interval timers', t => {
  const store = fixture(t), start = Date.now(), advance = clock(t, start);
  for (let step = 1; step <= 12; step++) {
    const at = start + step * 5000; advance(at); store.setMeta('synchronous-batch', { step });
    const owner = store.get('SELECT * FROM game_owner');
    assert.equal(owner.owner_id, store.ownerId); assert(owner.lease_until > at); assert(owner.lease_until <= at + 30000);
  }
  assert.deepEqual(store.meta('synchronous-batch'), { step: 12 });
});

test('an expired owner cannot renew itself or persist a new mutation', t => {
  const store = fixture(t), owner = store.get('SELECT * FROM game_owner'); clock(t, owner.lease_until + 1);
  assert.throws(() => store.setMeta('forbidden-after-expiry', true), { code: 'GAME_STORE_OWNER_LOST' });
  assert.equal(store.get('SELECT lease_until FROM game_owner').lease_until, owner.lease_until);
  assert.equal(store.meta('forbidden-after-expiry', null), null);
});

test('a foreign valid owner is neither replaced nor used to authorize the old writer', t => {
  const store = fixture(t), expires = Date.now() + 10000;
  store.db.prepare('UPDATE game_owner SET owner_id=?,lease_until=?').run('replacement-owner', expires);
  assert.throws(() => store.setMeta('forbidden-foreign-owner', true), { code: 'GAME_STORE_OWNER_LOST' });
  assert.equal(store.get('SELECT owner_id FROM game_owner').owner_id, 'replacement-owner');
  assert.equal(store.get('SELECT lease_until FROM game_owner').lease_until, expires);
  assert.equal(store.meta('forbidden-foreign-owner', null), null);
});

test('ownership is rechecked after a delayed write lock and an expired lease is not resurrected', t => {
  const store = fixture(t), owner = store.get('SELECT * FROM game_owner'), advance = clock(t, owner.lease_until - 10000);
  const exec = store.db.exec.bind(store.db);
  store.db.exec = sql => { const result = exec(sql); if (sql === 'BEGIN IMMEDIATE') advance(owner.lease_until + 1); return result; };
  try { assert.throws(() => store.setMeta('forbidden-after-lock-wait', true), { code: 'GAME_STORE_OWNER_LOST' }); }
  finally { store.db.exec = exec; }
  assert.equal(store.db.isTransaction, false); assert.equal(store.meta('forbidden-after-lock-wait', null), null);
  assert.equal(store.get('SELECT lease_until FROM game_owner').lease_until, owner.lease_until);
});

test('renewal inside an existing transaction respects its rollback and does not commit another write', t => {
  const store = fixture(t), owner = store.get('SELECT * FROM game_owner'); clock(t, owner.lease_until - 10000);
  const refusal = new Error('rollback owned batch');
  assert.throws(() => store.transaction(() => { store.setMeta('rolled-back-batch', true); throw refusal; }), error => error === refusal);
  assert.equal(store.meta('rolled-back-batch', null), null); assert.equal(store.db.isTransaction, false);
  assert.equal(store.get('SELECT lease_until FROM game_owner').lease_until, owner.lease_until);
  store.setMeta('later-owned-write', true); assert.equal(store.meta('later-owned-write'), true);
});

test('shutdown after lost ownership cancels active stream work and releases game resources despite an unwritable narration ledger', async t => {
  const f = await narrationFixture(t); await f.comment(); const request = await f.run(); assert(request);
  assert(f.manager.narration.open().some(item => item.request_id === request.request_id));
  f.manager.store.db.prepare('UPDATE game_owner SET owner_id=?').run('replacement-owner');
  await f.manager.close();
  assert.equal(f.manager.store.closed, true); assert.equal(f.manager.narration.closed, true);
  assert.equal(f.manager.state.connected, false); assert.equal(f.manager.lease, null);
  assert(f.manager.closeErrors.includes('GAME_STORE_OWNER_LOST'));
  assert.equal(f.state.request(request.request_id).status, 'CANCELLED');
  await until(() => f.game.socket.readyState === 3 && f.manager.wsServer.clients.size === 0);
  assert.throws(() => f.manager.store.db.prepare('SELECT 1'), { message: 'database is not open' });
});

test('database shutdown closes SQLite even if removing its own lease fails', t => {
  const store = fixture(t), prepare = store.db.prepare.bind(store.db), failure = new Error('fixture disk write unavailable');
  store.db.prepare = sql => sql.startsWith('DELETE FROM game_owner') ? { run() { throw failure; } } : prepare(sql);
  try { assert.throws(() => store.close(), error => error === failure); }
  finally { store.db.prepare = prepare; }
  assert.equal(store.closed, true); assert.throws(() => store.db.prepare('SELECT 1'), { message: 'database is not open' });
});
