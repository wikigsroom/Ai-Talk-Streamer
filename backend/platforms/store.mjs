import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { eventDetails } from './details.mjs';
import { eventPrincipal } from './events.mjs';

export class PlatformStore {
  constructor(file, now = () => Date.now()) {
    this.now = now; mkdirSync(dirname(file), { recursive: true }); this.db = new DatabaseSync(file);
    const version = this.db.prepare('PRAGMA user_version').get().user_version;
    if (version > 3) { this.db.close(); throw Object.assign(new Error('PLATFORM_SCHEMA_UNSUPPORTED'), { code: 'PLATFORM_SCHEMA_UNSUPPORTED' }); }
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
      CREATE TABLE IF NOT EXISTS platform_deletions(platform TEXT NOT NULL,room_id TEXT NOT NULL,message_id TEXT NOT NULL,deleted_at INTEGER NOT NULL,source_event_key TEXT NOT NULL,PRIMARY KEY(platform,room_id,message_id));`);
    if (!this.all('PRAGMA table_info(events)').some(column => column.name === 'detail')) this.db.exec("ALTER TABLE events ADD COLUMN detail TEXT NOT NULL DEFAULT '{}'");
    this.db.exec(`CREATE TABLE IF NOT EXISTS privacy_deletions(event_key TEXT PRIMARY KEY,deleted_at INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS privacy_fences(subject_key TEXT PRIMARY KEY,cutoff INTEGER NOT NULL);
      PRAGMA user_version=3`);
  }
  get(sql, ...args) { return this.db.prepare(sql).get(...args); }
  all(sql, ...args) { return this.db.prepare(sql).all(...args); }
  run(sql, ...args) { return this.db.prepare(sql).run(...args); }
  count(name, amount = 1) { this.run('INSERT INTO counters VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value', name, amount); }
  insert(event, status = 'PENDING', reason = null) {
    const privacy = this.isPrivacyDeleted(event);
    if (privacy) { event = { ...event, user_id: null, nickname: '', text: '', identity_quality: 'display_only', session_id: null }; status = 'DROPPED'; reason = 'privacy_deleted'; }
    const result = this.run(`INSERT OR IGNORE INTO events(event_key,platform,room_id,event_id,type,user_id,nickname,text,occurred_at,received_at,identity_quality,source,status,request_id,reason,session_id,detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?)`, event.event_key, event.platform, event.room_id, event.event_id, event.type, event.user_id || null, event.nickname, event.text, event.occurred_at, this.now(), event.identity_quality, event.source, status, reason, event.session_id || null, JSON.stringify(privacy ? {} : eventDetails(event)));
    if (!result.changes) this.count('duplicates'); else this.count('received');
    return !!result.changes;
  }
  isPrivacyDeleted(event) {
    if (this.get('SELECT 1 FROM privacy_deletions WHERE event_key=?', event.event_key)) return true;
    if (!event.user_id) return false;
    const subject = eventPrincipal(event).viewer_id;
    return !!this.get('SELECT 1 FROM privacy_fences WHERE subject_key=? AND cutoff>=?', subject, event.occurred_at);
  }
  expand(row) {
    if (!row) return null;
    let detail = {}; try { detail = eventDetails(JSON.parse(row.detail || '{}')); } catch { /* legacy/damaged optional metadata stays unknown */ }
    const { detail: _stored, ...base } = row; return { ...base, ...detail };
  }
  isDeleted(event) {
    return event.notice_kind === 'superchat' && !!event.platform_message_id && !!this.get('SELECT 1 FROM platform_deletions WHERE platform=? AND room_id=? AND message_id=? AND deleted_at>=?', event.platform, event.room_id, event.platform_message_id, this.now() - 7 * 86400000);
  }
  recordDeletion(event) {
    for (const id of event.deletion_target_ids) this.run('INSERT INTO platform_deletions VALUES (?,?,?,?,?) ON CONFLICT(platform,room_id,message_id) DO UPDATE SET deleted_at=MAX(deleted_at,excluded.deleted_at),source_event_key=excluded.source_event_key', event.platform, event.room_id, id, this.now(), event.event_key);
    this.markDeleted(this.deletionCandidates(event).filter(row => this.expand(row).notice_kind === 'superchat').map(row => row.event_key));
  }
  deletionCandidates(event) {
    const ids = event.deletion_target_ids, aliases = ids.flatMap(id => [id, 'sc-' + id]), marks = values => values.map(() => '?').join(',');
    return this.all(`SELECT * FROM events WHERE platform=? AND room_id=? AND type='comment' AND (event_id IN (${marks(aliases)}) OR json_extract(detail,'$.platform_message_id') IN (${marks(ids)}))`, event.platform, event.room_id, ...aliases, ...ids);
  }
  markDeleted(keys) {
    for (const key of keys) {
      const row = this.get('SELECT * FROM events WHERE event_key=?', key); if (!row) continue;
      const detail = { ...eventDetails(this.expand(row)), platform_deleted: true };
      this.run("UPDATE events SET detail=?,status=CASE WHEN status='COMPLETED' THEN status ELSE 'DROPPED' END,reason='platform_deleted' WHERE event_key=?", JSON.stringify(detail), key);
    }
  }
  setOutput(platform, values) {
    const old = this.get('SELECT * FROM outputs WHERE platform=?', platform) || { state: 'OFFLINE', broadcast_id: null, owned_broadcast: 0, owned_output: 0, error: null };
    const value = { ...old, ...values };
    this.run('INSERT OR REPLACE INTO outputs VALUES (?,?,?,?,?,?,?)', platform, value.state, value.broadcast_id, Number(!!value.owned_broadcast), Number(!!value.owned_output), this.now(), value.error);
    return this.get('SELECT * FROM outputs WHERE platform=?', platform);
  }
  recent(limit = 50) { return this.all('SELECT * FROM events ORDER BY received_at DESC,rowid DESC LIMIT ?', limit).map(row => this.expand(row)); }
  pruneCandidates({ protectedRequests = [], protectedKeys = [], limit = 1000 } = {}) {
    const keys = new Set(protectedKeys), requests = [...new Set(protectedRequests)];
    if (requests.length > 1000) throw Object.assign(new Error('RETENTION_PROTECTION_LIMIT'), { code: 'RETENTION_PROTECTION_LIMIT', status: 503 });
    return this.all(`SELECT * FROM events WHERE received_at<? AND status!='PENDING' ${requests.length ? `AND (request_id IS NULL OR request_id NOT IN (${requests.map(() => '?').join(',')}))` : ''} ORDER BY received_at,rowid LIMIT ?`,
      this.now() - 7 * 86400000, ...requests, limit + keys.size).filter(row => !keys.has(row.event_key)).slice(0, limit);
  }
  prune({ beforeRemove, protectedRequests = [], protectedKeys = [] } = {}) {
    const options = { protectedRequests, protectedKeys }, rows = this.pruneCandidates(options);
    // Persist canonical ownership before the only raw identity row can vanish.
    // Its monotonic hash index may survive a later platform rollback safely.
    beforeRemove?.(rows);
    this.db.exec('BEGIN IMMEDIATE');
    let removed = 0, tombstones = 0;
    try {
      for (const row of rows) removed += Number(this.run('DELETE FROM events WHERE event_key=?', row.event_key).changes);
      tombstones = Number(this.run('DELETE FROM platform_deletions WHERE deleted_at<?', this.now() - 7 * 86400000).changes);
      this.db.exec('COMMIT');
    } catch (error) { this.db.exec('ROLLBACK'); throw error; }
    return { removed, tombstones_removed: tombstones, more: this.pruneCandidates({ ...options, limit: 1 }).length > 0 };
  }
  close() { this.db.close(); }
}
