import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { DEFAULTS, patchSettings } from './defaults.mjs';

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
  recent(limit = 100) { return this.all('SELECT * FROM messages ORDER BY received_at DESC,rowid DESC LIMIT ?', limit).reverse().map(r => ({ ...JSON.parse(r.value), hidden: !!r.hidden, answered: !!r.answered })); }
  message(id) { const r = this.one('SELECT * FROM messages WHERE id=?', id); return r ? { ...JSON.parse(r.value), hidden: !!r.hidden, answered: !!r.answered } : null; }
  prune(now = Date.now()) {
    this.run('DELETE FROM messages WHERE received_at<? AND id NOT IN (SELECT id FROM messages ORDER BY received_at DESC LIMIT 500)', now - 7 * 86400000);
    this.run('DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY received_at DESC LIMIT 5000)');
    this.run('DELETE FROM audit WHERE seq NOT IN (SELECT seq FROM audit ORDER BY seq DESC LIMIT 2000)');
    this.run('DELETE FROM agent WHERE seq NOT IN (SELECT seq FROM agent ORDER BY seq DESC LIMIT 300)');
  }
  close() { this.db.close(); }
}
