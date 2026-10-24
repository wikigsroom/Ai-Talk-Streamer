import { DatabaseSync } from 'node:sqlite';
import { mkdirSync, readFileSync, existsSync } from 'node:fs';
import { dirname } from 'node:path';
import { randomUUID } from 'node:crypto';
import { EventEmitter } from 'node:events';
import { canonical, digest } from '../dsh-bridge/channel.mjs';

export const utc = (millis = Date.now()) => new Date(millis).toISOString();
export const id = prefix => prefix + '-' + randomUUID();
const OWNER_LEASE_MS = 30000;

function migrationHashes(sql) {
  const lf=sql.replace(/\r\n/g,'\n');
  // Git/native Windows transfers may change line endings, never SQL content.
  return {canonical:digest(lf),accepted:new Set([digest(sql),digest(lf),digest(lf.replace(/\n/g,'\r\n'))])};
}

function alive(pid) {
  if (!Number.isSafeInteger(pid) || pid < 1) return true;
  try { process.kill(pid, 0); return true; } catch (error) { return error.code !== 'ESRCH'; }
}

// All business writes are synchronous, fenced transactions on this one connection.
// No network work, model promise or external storage mutation belongs in tx().
export class StateStore extends EventEmitter {
  #db;
  #transaction = false;
  #closed = false;
  #heartbeat;
  #pendingEvents = [];
  constructor(file, { now = () => Date.now(), ownerId = id('owner'), heartbeat = true } = {}) {
    super();
    this.now = now;
    this.ownerId = ownerId;
    this.file = file;
    this.faulted=false;
    if (file !== ':memory:') mkdirSync(dirname(file), { recursive: true });
    this.#db = new DatabaseSync(file);
    this.#db.exec('PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA busy_timeout=5000;');
    try {
      // Refuse a second owner's migration before touching schema or versions.
      if(this.get("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bridge_owner'")) {
        const prior=this.get('SELECT * FROM bridge_owner WHERE singleton=1');
        if(prior&&prior.lease_until>now()&&alive(prior.pid))throw new Error('STORE_OWNER_ACTIVE');
      }
      this.#migrate();
      this.#db.exec('CREATE TABLE IF NOT EXISTS bridge_owner (singleton INTEGER PRIMARY KEY CHECK(singleton=1), owner_id TEXT NOT NULL, pid INTEGER NOT NULL, lease_until INTEGER NOT NULL)');
      this.#db.exec('BEGIN IMMEDIATE');
      try {
        const owner = this.#db.prepare('SELECT * FROM bridge_owner WHERE singleton=1').get();
        if (owner && owner.lease_until > now() && alive(owner.pid)) throw new Error('STORE_OWNER_ACTIVE');
        this.#db.prepare('INSERT INTO bridge_owner VALUES (1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET owner_id=excluded.owner_id,pid=excluded.pid,lease_until=excluded.lease_until').run(ownerId, process.pid, now() + OWNER_LEASE_MS);
        this.#db.exec('COMMIT');
      } catch (error) { this.#db.exec('ROLLBACK'); throw error; }
      if (heartbeat) {
        this.#heartbeat = setInterval(() => {
          try { this.tx(() => this.run('UPDATE bridge_owner SET lease_until=? WHERE owner_id=?', now() + OWNER_LEASE_MS, ownerId)); }
          catch (error) { this.emit('owner-lost', { code: 'STORE_OWNER_LOST' }); }
        }, 5000);
        this.#heartbeat.unref();
      }
    } catch (error) { this.#db.close(); throw error; }
  }

  #migrate() {
    const sql = readFileSync(new URL('./migrations/001-init.sql', import.meta.url), 'utf8');
    const firstHashes=migrationHashes(sql),hash=firstHashes.canonical;
    const version = this.#db.prepare('PRAGMA user_version').get().user_version;
    if (version > 2) throw new Error('STORE_SCHEMA_NEWER');
    if (version === 0) {
      // Record the migration hash in the very transaction that creates the schema.
      const record = `INSERT INTO schema_migrations VALUES (1,'${utc(this.now())}','${hash}');\n`;
      this.#db.exec(sql.replace('PRAGMA user_version = 1;', record + 'PRAGMA user_version = 1;'));
    }
    const applied = this.#db.prepare('SELECT migration_sha256 FROM schema_migrations WHERE version=1').get();
    if (!applied || !firstHashes.accepted.has(applied.migration_sha256)) throw new Error('STORE_MIGRATION_HASH');
    const second = readFileSync(new URL('./migrations/002-runtime.sql', import.meta.url), 'utf8');
    const secondHashes=migrationHashes(second),secondHash=secondHashes.canonical;
    if (version < 2) {
      if (this.file !== ':memory:' && version > 0) this.backup(this.file + '.before-v2-' + this.now() + '.sqlite3');
      this.#db.exec(second.replace('__APPLIED_AT__', utc(this.now())).replace('__MIGRATION_SHA256__', secondHash));
    }
    if (!secondHashes.accepted.has(this.#db.prepare('SELECT migration_sha256 FROM schema_migrations WHERE version=2').get()?.migration_sha256)) throw new Error('STORE_MIGRATION_HASH');
    const integrity = this.#db.prepare('PRAGMA quick_check').get();
    if (Object.values(integrity)[0] !== 'ok') throw new Error('STORE_INTEGRITY');
  }

  get(sql, ...params) { return this.#db.prepare(sql).get(...params); }
  all(sql, ...params) { return this.#db.prepare(sql).all(...params); }
  run(sql, ...params) {
    if (!this.#transaction) throw new Error('STORE_WRITE_OUTSIDE_TRANSACTION');
    return this.#db.prepare(sql).run(...params);
  }
  tx(fn) {
    if (this.#closed) throw new Error('STORE_CLOSED');
    if(this.faulted)throw new Error('STORE_STORAGE_FAULT');
    if (this.#transaction) throw new Error('STORE_NESTED_TRANSACTION');
    try{this.#db.exec('BEGIN IMMEDIATE');}catch(error){this.#storageFault(error);throw error;}
    this.#transaction = true;
    this.#pendingEvents = [];
    let result, events;
    try {
      const owner = this.get('SELECT * FROM bridge_owner WHERE singleton=1');
      if (!owner || owner.owner_id !== this.ownerId || owner.lease_until <= this.now()) throw new Error('STORE_OWNER_LOST');
      result = fn(this);
      if (result && typeof result.then === 'function') throw new Error('STORE_ASYNC_TRANSACTION');
      this.#db.exec('COMMIT');
      events = this.#pendingEvents;
    } catch (error) { this.#db.exec('ROLLBACK');this.#storageFault(error); throw error; }
    finally { this.#transaction = false; this.#pendingEvents = []; }
    if (events.length) queueMicrotask(() => { for (const event of events) this.emit('event', event); });
    return result;
  }
  #storageFault(error) {
    if([8,10,11,13].includes(Number(error.errcode)&255)) {
      this.faulted=true;queueMicrotask(()=>this.emit('storage-fault',{code:'STORE_STORAGE_FAULT',sqlite_code:error.errcode}));
    }
  }
  event(scope, type, payload) {
    if (!this.#transaction) throw new Error('STORE_EVENT_OUTSIDE_TRANSACTION');
    if (!/^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/.test(type)) throw new Error('EVENT_TYPE');
    const body = canonical(payload), eventId = id('evt'), received = utc(this.now());
    const seq = Number(this.run(`INSERT INTO stream_events(event_id,event_type,character_id,room_id,broadcast_id,request_id,utterance_id,runtime_epoch,generation,source_revision,actor_kind,actor_id,occurred_at,received_at,payload_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
      eventId, type, scope.character_id, scope.room_id, scope.broadcast_id ?? null, scope.request_id ?? null, scope.utterance_id ?? null,
      scope.runtime_epoch, scope.generation ?? null, scope.source_revision ?? 1, scope.actor_kind, scope.actor_id,
      scope.occurred_at || received, received, digest(body)).lastInsertRowid);
    this.run('INSERT INTO event_payloads(event_seq,payload_json) VALUES (?,?)', seq, body);
    this.#pendingEvents.push({ event_seq: seq, event_id: eventId, event_type: type, character_id: scope.character_id, room_id: scope.room_id, request_id: scope.request_id ?? null });
    return seq;
  }
  payload(eventSeq) {
    const record = this.get('SELECT * FROM event_payloads WHERE event_seq=?', eventSeq);
    if (!record || record.redacted_at || record.payload_json === null) return { redacted: true };
    return JSON.parse(record.payload_json);
  }
  integrity() {
    return { integrity: Object.values(this.get('PRAGMA integrity_check'))[0], foreign_keys: this.all('PRAGMA foreign_key_check') };
  }
  backup(destination) {
    if (destination === this.file || existsSync(destination)) throw new Error('BACKUP_TARGET_EXISTS');
    mkdirSync(dirname(destination), { recursive: true });
    // VACUUM INTO captures the live WAL state; copying the main file alone does not.
    this.#db.prepare('VACUUM INTO ?').run(destination);
    return { file: destination, sha256: digest(readFileSync(destination)) };
  }
  close() {
    if (this.#closed) return;
    clearInterval(this.#heartbeat);
    try { if(!this.faulted)this.tx(() => this.run('UPDATE bridge_owner SET lease_until=0 WHERE owner_id=?', this.ownerId)); }
    finally { this.#closed = true; this.#db.close(); }
  }
}
