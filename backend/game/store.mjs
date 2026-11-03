import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname, join, basename } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { canonical } from '../dsh-bridge/channel.mjs';
import { ensure, utc } from './errors.mjs';

export const hash = value => createHash('sha256').update(canonical(value)).digest('hex');
const alive = pid => { try { process.kill(pid, 0); return true; } catch (error) { return error.code !== 'ESRCH'; } };
export class GameStore {
  constructor(path) {
    mkdirSync(dirname(path), { recursive: true }); this.db = new DatabaseSync(path); this.closed = false;
    this.ownerId = randomUUID();
    this.db.exec('PRAGMA busy_timeout=3000');
    const previousVersion = this.get("SELECT name FROM sqlite_master WHERE name='schema_migrations'")
      ? this.get('SELECT MAX(version) n FROM schema_migrations').n : 0;
    if (previousVersion > 4 || previousVersion < 0) { this.db.close(); throw new Error('GAME_DATABASE_VERSION'); }
    if (this.get("SELECT name FROM sqlite_master WHERE name='game_owner'")) {
      const owner = this.get('SELECT * FROM game_owner WHERE singleton=1');
      if (owner && owner.lease_until > Date.now() && alive(owner.pid)) { this.db.close(); throw new Error('GAME_STORE_OWNER_ACTIVE'); }
    }
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;
      CREATE TABLE IF NOT EXISTS game_owner(singleton INTEGER PRIMARY KEY,owner_id TEXT NOT NULL,pid INTEGER NOT NULL,lease_until INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL);
      INSERT OR IGNORE INTO schema_migrations VALUES(1,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
      CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS objects(kind TEXT NOT NULL,id TEXT NOT NULL,world_session_id TEXT,revision INTEGER NOT NULL,value TEXT NOT NULL,PRIMARY KEY(kind,id));
      CREATE INDEX IF NOT EXISTS object_world ON objects(kind,world_session_id);
      CREATE TABLE IF NOT EXISTS idempotency(scope TEXT NOT NULL,request_id TEXT NOT NULL,body_hash TEXT NOT NULL,kind TEXT NOT NULL,object_id TEXT NOT NULL,PRIMARY KEY(scope,request_id));
      CREATE TABLE IF NOT EXISTS task_transitions(task_id TEXT NOT NULL,transition_seq INTEGER NOT NULL,value TEXT NOT NULL,PRIMARY KEY(task_id,transition_seq));
      CREATE TABLE IF NOT EXISTS game_events(event_id TEXT PRIMARY KEY,world_session_id TEXT NOT NULL,received_at TEXT NOT NULL,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS vote_ballots(vote_id TEXT NOT NULL,user_key TEXT NOT NULL,event_id TEXT NOT NULL UNIQUE,option_id TEXT NOT NULL,PRIMARY KEY(vote_id,user_key));
      CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,action TEXT NOT NULL,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS stream_receipts(stream TEXT NOT NULL,session TEXT NOT NULL,through_seq INTEGER NOT NULL,PRIMARY KEY(stream,session));
    `);
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const owner = this.get('SELECT * FROM game_owner WHERE singleton=1');
      ensure(!owner || owner.lease_until <= Date.now() || !alive(owner.pid), 'GAME_STORE_OWNER_ACTIVE', 503);
      this.db.prepare('INSERT INTO game_owner VALUES(1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET owner_id=excluded.owner_id,pid=excluded.pid,lease_until=excluded.lease_until')
        .run(this.ownerId, process.pid, Date.now() + 30000);
      this.db.exec('COMMIT');
    } catch(error) { this.db.exec('ROLLBACK'); this.db.close(); throw error; }
    try {
      if (this.get('SELECT MAX(version) n FROM schema_migrations').n === 1) this.migrateWorlds(path, previousVersion === 1);
      if (this.get('SELECT MAX(version) n FROM schema_migrations').n === 2) this.migrateContinuity(path, previousVersion > 0);
      if (this.get('SELECT MAX(version) n FROM schema_migrations').n === 3) this.migrateHistory(path, previousVersion > 0);
      this.schemaVersion = this.get('SELECT MAX(version) n FROM schema_migrations').n;
      ensure(this.schemaVersion === 4, 'GAME_DATABASE_VERSION', 503);
    } catch (error) {
      this.db.prepare('DELETE FROM game_owner WHERE owner_id=?').run(this.ownerId); this.db.close(); throw error;
    }
    this.ownerTimer = setInterval(() => {
      try { this.db.prepare('UPDATE game_owner SET lease_until=? WHERE singleton=1 AND owner_id=? AND lease_until>?').run(Date.now() + 30000, this.ownerId, Date.now()); } catch { /* subsequent writes fail closed */ }
    }, 9000); this.ownerTimer.unref();
  }
  migrateWorlds(path, backupRequired) {
    let backup = null;
    if (backupRequired) {
      const folder = join(dirname(path), 'backups'); mkdirSync(folder, { recursive: true });
      backup = join(folder, 'schema-v1-' + Date.now() + '-' + randomUUID() + '.sqlite3');
      // VACUUM INTO creates a transactionally consistent snapshot, including committed WAL data.
      this.db.prepare('VACUUM INTO ?').run(backup);
    }
    this.transaction(() => {
      this.db.exec(`
        CREATE TABLE world_registry(world_id TEXT PRIMARY KEY,game_instance_id TEXT NOT NULL,revision INTEGER NOT NULL,value TEXT NOT NULL);
        CREATE TABLE world_bases(base_id TEXT PRIMARY KEY,world_id TEXT NOT NULL REFERENCES world_registry(world_id),revision INTEGER NOT NULL,value TEXT NOT NULL);
        CREATE INDEX base_world ON world_bases(world_id);
        CREATE TABLE world_checkpoints(checkpoint_id TEXT PRIMARY KEY,world_id TEXT NOT NULL REFERENCES world_registry(world_id),created_at TEXT NOT NULL,value TEXT NOT NULL);
        CREATE INDEX checkpoint_world ON world_checkpoints(world_id);
        CREATE TABLE task_recovery(task_id TEXT PRIMARY KEY,status TEXT NOT NULL,value TEXT NOT NULL);
      `);
      this.run('INSERT INTO schema_migrations VALUES(2,?)', utc());
      this.setMeta('schema_v2_migration', { from: 1, to: 2, at: utc(), backup_file: backup ? basename(backup) : null });
    });
  }
  get(sql, ...args) { return this.db.prepare(sql).get(...args); }
  migrateContinuity(path, backupRequired) {
    let backup = null;
    if (backupRequired) {
      const folder = join(dirname(path), 'backups'); mkdirSync(folder, { recursive: true });
      backup = join(folder, 'schema-v2-' + Date.now() + '-' + randomUUID() + '.sqlite3');
      this.db.prepare('VACUUM INTO ?').run(backup);
    }
    this.transaction(() => {
      this.db.exec(`
        CREATE TABLE world_sessions(session_id TEXT PRIMARY KEY,world_id TEXT NOT NULL REFERENCES world_registry(world_id),status TEXT NOT NULL,value TEXT NOT NULL);
        CREATE INDEX session_world ON world_sessions(world_id);
        CREATE TABLE world_goals(goal_id TEXT PRIMARY KEY,world_id TEXT NOT NULL REFERENCES world_registry(world_id),revision INTEGER NOT NULL,status TEXT NOT NULL,value TEXT NOT NULL);
        CREATE INDEX goal_world ON world_goals(world_id,status);
        CREATE TABLE world_goal_tasks(task_id TEXT PRIMARY KEY,goal_id TEXT NOT NULL REFERENCES world_goals(goal_id),step_id TEXT NOT NULL);
        CREATE TABLE task_dispositions(task_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,status TEXT NOT NULL,value TEXT NOT NULL);
      `);
      for (const row of this.all('SELECT task_id,value FROM task_recovery')) {
        const value = JSON.parse(row.value); value.revision ??= 1;
        this.run('UPDATE task_recovery SET value=? WHERE task_id=?', canonical(value), row.task_id);
      }
      for (const row of this.all('SELECT value FROM world_registry')) {
        const world = JSON.parse(row.value), session = { world_session_id: world.last_world_session_id, world_id: world.world_id,
          game_instance_id: world.game_instance_id, bridge_boot_id: null, status: 'unobserved', source: 'legacy_registry',
          first_observed_at: world.last_seen, last_observed_at: world.last_seen, last_seq: null, last_connection_generation: null,
          connection_count: 0, closed_at: null, close_reason: 'legacy_registry_only' };
        this.run('INSERT INTO world_sessions VALUES(?,?,?,?)', session.world_session_id, world.world_id, session.status, canonical(session));
      }
      this.run('INSERT INTO schema_migrations VALUES(3,?)', utc());
      this.setMeta('schema_v3_migration', { from: 2, to: 3, at: utc(), backup_file: backup ? basename(backup) : null });
    });
  }
  all(sql, ...args) { return this.db.prepare(sql).all(...args); }
  migrateHistory(path, backupRequired) {
    let backup = null;
    if (backupRequired) {
      const folder = join(dirname(path), 'backups'); mkdirSync(folder, { recursive: true });
      backup = join(folder, 'schema-v3-' + Date.now() + '-' + randomUUID() + '.sqlite3');
      this.db.prepare('VACUUM INTO ?').run(backup);
    }
    this.transaction(() => {
      this.db.exec(`CREATE TABLE bridge_history(instance TEXT NOT NULL,source TEXT NOT NULL,record_key TEXT NOT NULL,
        world_session_id TEXT NOT NULL,payload_hash TEXT NOT NULL,payload_bytes INTEGER NOT NULL,value TEXT NOT NULL,
        PRIMARY KEY(instance,source,record_key));
        CREATE INDEX bridge_history_world ON bridge_history(instance,world_session_id);
        CREATE TABLE history_partial(import_id TEXT PRIMARY KEY,value TEXT NOT NULL);`);
      this.run('INSERT INTO schema_migrations VALUES(4,?)', utc());
      this.setMeta('schema_v4_migration', { from: 3, to: 4, at: utc(), backup_file: backup ? basename(backup) : null });
    });
  }
  run(sql, ...args) {
    const owner = this.get('SELECT owner_id,lease_until FROM game_owner WHERE singleton=1');
    const now = Date.now();
    ensure(owner?.owner_id === this.ownerId && owner.lease_until > now, 'GAME_STORE_OWNER_LOST', 503);
    // A sustained synchronous input batch may keep the interval from running.
    // Renew only a still-valid owner, after acquiring the SQLite write lock.
    if (owner.lease_until > now + 20000) return this.db.prepare(sql).run(...args);
    const nested = this.db.isTransaction;
    if (!nested) this.db.exec('BEGIN IMMEDIATE');
    try {
      const current = this.get('SELECT owner_id,lease_until FROM game_owner WHERE singleton=1'), lockedAt = Date.now();
      ensure(current?.owner_id === this.ownerId && current.lease_until > lockedAt, 'GAME_STORE_OWNER_LOST', 503);
      const renewed = this.db.prepare('UPDATE game_owner SET lease_until=? WHERE singleton=1 AND owner_id=? AND lease_until>?')
        .run(lockedAt + 30000, this.ownerId, lockedAt);
      ensure(renewed.changes === 1, 'GAME_STORE_OWNER_LOST', 503);
      const result = this.db.prepare(sql).run(...args);
      if (!nested) this.db.exec('COMMIT');
      return result;
    } catch (error) { if (!nested) this.db.exec('ROLLBACK'); throw error; }
  }
  transaction(fn) {
    this.db.exec('BEGIN IMMEDIATE');
    try { const value = fn(); this.db.exec('COMMIT'); return value; }
    catch (error) { this.db.exec('ROLLBACK'); throw error; }
  }
  meta(key, fallback) { const row = this.get('SELECT value FROM meta WHERE key=?', key); return row ? JSON.parse(row.value) : structuredClone(fallback); }
  setMeta(key, value) { this.run('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', key, canonical(value)); }
  object(kind, id) { const row = this.get('SELECT value FROM objects WHERE kind=? AND id=?', kind, id); return row ? JSON.parse(row.value) : null; }
  put(kind, value) {
    const id = value[kind + '_id']; ensure(typeof id === 'string', 'GAME_RECORD_ID_INVALID', 500);
    this.run('INSERT INTO objects VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET world_session_id=excluded.world_session_id,revision=excluded.revision,value=excluded.value',
      kind, id, value.world_session_id || null, value.version || value.revision || 1, canonical(value)); return value;
  }
  list(kind, { world, worldId, room, limit = 20, cursor } = {}) {
    ensure(Number.isInteger(limit) && limit >= 1 && limit <= 100, 'GAME_REQUEST_INVALID', 400);
    let before = Number.MAX_SAFE_INTEGER;
    if (cursor) { ensure(/^[1-9][0-9]{0,15}$/.test(cursor), 'GAME_CURSOR_INVALID', 400); before = Number(cursor); ensure(Number.isSafeInteger(before), 'GAME_CURSOR_INVALID', 400); }
    const roomPath = kind === 'suggestion' ? '$.origin.room_id' : '$.room_id';
    const rows = this.all(`SELECT rowid,value FROM objects WHERE kind=? AND rowid<? ${world ? 'AND world_session_id=?' : ''} ${worldId === undefined ? '' : "AND json_extract(value,'$.world_id')=?"} ${room === undefined ? '' : 'AND json_extract(value,?)=?'} ORDER BY rowid DESC LIMIT ?`,
      kind, before, ...(world ? [world] : []), ...(worldId === undefined ? [] : [worldId]), ...(room === undefined ? [] : [roomPath, room]), limit + 1);
    return { items: rows.slice(0, limit).map(r => JSON.parse(r.value)), next_cursor: rows.length > limit ? String(rows[limit - 1].rowid) : null };
  }
  replay(scope, request) {
    const row = this.get('SELECT * FROM idempotency WHERE scope=? AND request_id=?', scope, request.request_id);
    if (!row) return null;
    ensure(row.body_hash === hash(request), 'GAME_IDEMPOTENCY_CONFLICT');
    return this.object(row.kind, row.object_id);
  }
  remember(scope, request, kind, value) {
    this.put(kind, value); this.run('INSERT INTO idempotency VALUES(?,?,?,?,?)', scope, request.request_id, hash(request), kind, value[kind + '_id']); return value;
  }
  audit(action, value) { this.run('INSERT INTO audit(at,action,value) VALUES(?,?,?)', utc(), action, canonical(value)); }
  receipt(stream, session, seq) {
    const previous = this.get('SELECT through_seq FROM stream_receipts WHERE stream=? AND session=?', stream, session)?.through_seq || 0;
    if (seq <= previous) return { duplicate: true, through: previous };
    ensure(seq === previous + 1, 'GAME_DELIVERY_GAP', 409, { expected: previous + 1 });
    return { duplicate: false, through: seq };
  }
  acknowledge(stream, session, seq) { this.run('INSERT INTO stream_receipts VALUES(?,?,?) ON CONFLICT(stream,session) DO UPDATE SET through_seq=excluded.through_seq', stream, session, seq); }
  close() {
    if (!this.closed) { this.closed = true; clearInterval(this.ownerTimer);
      try { this.db.prepare('DELETE FROM game_owner WHERE owner_id=?').run(this.ownerId); }
      finally { this.db.close(); } }
  }
}
