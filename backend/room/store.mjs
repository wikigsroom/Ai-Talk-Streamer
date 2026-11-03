import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { DEFAULTS, patchSettings } from './defaults.mjs';
import { platformDetails } from '../platforms/details.mjs';

export class RoomStore {
  constructor(path) {
    mkdirSync(dirname(path), { recursive: true }); this.db = new DatabaseSync(path);
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=3000;
      CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS tracks(id TEXT PRIMARY KEY,name TEXT NOT NULL,path TEXT NOT NULL,mime TEXT NOT NULL,duration REAL NOT NULL,bytes INTEGER NOT NULL,sha256 TEXT NOT NULL,builtin INTEGER NOT NULL,position INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,event_key TEXT UNIQUE,received_at INTEGER NOT NULL,value TEXT NOT NULL,hidden INTEGER NOT NULL DEFAULT 0,answered INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,at INTEGER NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS agent(seq INTEGER PRIMARY KEY AUTOINCREMENT,session TEXT NOT NULL,at INTEGER NOT NULL,role TEXT NOT NULL,text TEXT NOT NULL);
    `);
    this.settings = patchSettings(DEFAULTS, this.get('settings', DEFAULTS));
    this.revision = this.get('revision', 1);
  }
  all(sql, ...args) { return this.db.prepare(sql).all(...args); }
  one(sql, ...args) { return this.db.prepare(sql).get(...args); }
  run(sql, ...args) { return this.db.prepare(sql).run(...args); }
  get(key, fallback) { const row = this.one('SELECT value FROM meta WHERE key=?', key); return row ? JSON.parse(row.value) : structuredClone(fallback); }
  put(key, value) { this.run('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', key, JSON.stringify(value)); }
  transaction(fn) { this.db.exec('BEGIN IMMEDIATE'); try { const r = fn(); this.db.exec('COMMIT'); return r; } catch (e) { this.db.exec('ROLLBACK'); throw e; } }
  saveSettings(settings) { this.transaction(() => { this.put('settings', settings); this.put('revision', this.revision + 1); }); this.settings = settings; this.revision++; }
  log(action, detail, at = Date.now()) { this.run('INSERT INTO audit(at,action,detail) VALUES (?,?,?)', at, action, JSON.stringify(detail)); }
  decode(r) {
    const value = JSON.parse(r.value);
    // Earlier Room versions fabricated gift count=1/name="礼物". Stored legacy
    // values lack field provenance, so do not promote them to verified facts.
    if (!value.platform_fields) {
      value.platform_fields = platformDetails(value.platform, {}, { source: 'legacy', type: value.type, noticeKind: value.notice_kind });
      value.gift_count = null; value.gift_name = null;
    }
    return { ...value, hidden: !!r.hidden, answered: !!r.answered };
  }
  recent(limit = 100) { return this.all('SELECT * FROM messages ORDER BY received_at DESC,rowid DESC LIMIT ?', limit).reverse().map(r => this.decode(r)); }
  message(id) { const r = this.one('SELECT * FROM messages WHERE id=?', id); return r ? this.decode(r) : null; }
  messagesById(ids) {
    const found = [], unique = [...new Set(ids)];
    for (let offset = 0; offset < unique.length; offset += 200) {
      const batch = unique.slice(offset, offset + 200);
      found.push(...this.all(`SELECT * FROM messages WHERE id IN (${batch.map(() => '?').join(',')})`, ...batch).map(row => this.decode(row)));
    }
    return found;
  }
  pruneCandidates(now, { protectedKeys = [], limit = 1000 } = {}) {
    const keys = new Set(protectedKeys);
    return this.all(`SELECT id FROM messages WHERE
      (received_at<? AND id NOT IN (SELECT id FROM messages ORDER BY received_at DESC,rowid DESC LIMIT 500))
      OR id NOT IN (SELECT id FROM messages ORDER BY received_at DESC,rowid DESC LIMIT 5000)
      ORDER BY received_at,rowid LIMIT ?`, now - 7 * 86400000, limit + keys.size).filter(row => !keys.has(row.id)).slice(0, limit);
  }
  prune(now = Date.now(), options = {}) {
    const ids = this.pruneCandidates(now, options).map(row => row.id);
    this.transaction(() => {
      if (ids.length) {
        const pending = this.get('retention_withdrawal', []);
        if (!Array.isArray(pending) || !pending.every(id => typeof id === 'string')) throw Object.assign(new Error('ROOM_RETENTION_STATE_INVALID'), { code: 'ROOM_RETENTION_STATE_INVALID', status: 503 });
        this.put('retention_withdrawal', [...new Set([...pending, ...ids])]);
      }
      for (const id of ids) this.run('DELETE FROM messages WHERE id=?', id);
      this.run('DELETE FROM audit WHERE seq NOT IN (SELECT seq FROM audit ORDER BY seq DESC LIMIT 2000)');
      this.run('DELETE FROM agent WHERE seq NOT IN (SELECT seq FROM agent ORDER BY seq DESC LIMIT 300)');
    });
    return { removed_ids: ids, more: this.pruneCandidates(now, { ...options, limit: 1 }).length > 0 };
  }
  close() { this.db.close(); }
}
