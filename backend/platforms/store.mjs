import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

export class PlatformStore {
  constructor(file, now = () => Date.now()) {
    this.now = now; mkdirSync(dirname(file), { recursive: true }); this.db = new DatabaseSync(file);
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=3000;
      CREATE TABLE IF NOT EXISTS events (
        event_key TEXT PRIMARY KEY, platform TEXT NOT NULL, room_id TEXT NOT NULL,
        event_id TEXT NOT NULL, type TEXT NOT NULL, user_id TEXT, nickname TEXT NOT NULL,
        text TEXT NOT NULL, occurred_at INTEGER NOT NULL, received_at INTEGER NOT NULL,
        identity_quality TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
        request_id TEXT, reason TEXT, session_id TEXT, UNIQUE(platform,room_id,event_id));
      CREATE INDEX IF NOT EXISTS events_pending ON events(status,received_at);
      CREATE TABLE IF NOT EXISTS outputs (platform TEXT PRIMARY KEY, state TEXT NOT NULL, broadcast_id TEXT, owned_broadcast INTEGER NOT NULL DEFAULT 0, owned_output INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL, error TEXT);
      CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
      PRAGMA user_version=1;`);
  }
  get(sql, ...args) { return this.db.prepare(sql).get(...args); }
  all(sql, ...args) { return this.db.prepare(sql).all(...args); }
  run(sql, ...args) { return this.db.prepare(sql).run(...args); }
  count(name, amount = 1) { this.run('INSERT INTO counters VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value', name, amount); }
  insert(event, status = 'PENDING', reason = null) {
    const result = this.run(`INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?)`, event.event_key, event.platform, event.room_id, event.event_id, event.type, event.user_id || null, event.nickname, event.text, event.occurred_at, this.now(), event.identity_quality, event.source, status, reason, event.session_id || null);
    if (!result.changes) this.count('duplicates'); else this.count('received');
    return !!result.changes;
  }
  setOutput(platform, values) {
    const old = this.get('SELECT * FROM outputs WHERE platform=?', platform) || { state: 'OFFLINE', broadcast_id: null, owned_broadcast: 0, owned_output: 0, error: null };
    const value = { ...old, ...values };
    this.run('INSERT OR REPLACE INTO outputs VALUES (?,?,?,?,?,?,?)', platform, value.state, value.broadcast_id, Number(!!value.owned_broadcast), Number(!!value.owned_output), this.now(), value.error);
    return this.get('SELECT * FROM outputs WHERE platform=?', platform);
  }
  recent(limit = 50) { return this.all('SELECT * FROM events ORDER BY received_at DESC,rowid DESC LIMIT ?', limit); }
  prune() { this.run("DELETE FROM events WHERE received_at<? AND status!='PENDING'", this.now() - 7 * 86400000); }
  close() { this.db.close(); }
}
