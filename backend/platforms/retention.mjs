import { canonical, digest } from '../dsh-bridge/channel.mjs';
import { requireValue } from '../dsh-bridge/state.mjs';
import { id, utc } from '../memory/store.mjs';
import { TERMINAL } from '../game/tasks.mjs';
import { existsSync } from 'node:fs';
import { join } from 'node:path';

const POLICY = Object.freeze({ platform_event_days: 7, room_message_days: 7, room_minimum_count: 500, room_maximum_count: 5000, batch_limit: 1000 });

export class AudienceRetention {
  constructor(privacy) { this.privacy = privacy; this.bridge = privacy.bridge; this.running = false; this.key = 'audience-retention:' + digest(this.bridge.state.characterRoom) + ':last'; }
  status() {
    const row = this.bridge.db.get('SELECT value_json FROM runtime_meta WHERE key=?', this.key), last = row ? JSON.parse(row.value_json) : null;
    const saved = this.bridge.db.get('SELECT value_json FROM runtime_meta WHERE key=?', this.key + ':history');
    const present = value => value.status === 'running' && (!this.running || value.run_id !== last?.run_id) ? { ...value, status: 'interrupted', error: 'AUDIENCE_RETENTION_INTERRUPTED' } : value;
    return { schema_version: 1, policy: POLICY, ownership_records: this.privacy.ownership.count(),
      privacy_pending: !!this.bridge.administration?.privacyPending, last_run: last ? present(last) : null,
      recent_runs: saved ? JSON.parse(saved.value_json).map(present) : [] };
  }
  save(value) {
    this.bridge.db.tx(() => {
      const key = this.key + ':history', row = this.bridge.db.get('SELECT value_json FROM runtime_meta WHERE key=?', key);
      const history = row ? JSON.parse(row.value_json) : [];
      requireValue(Array.isArray(history), 'AUDIENCE_RETENTION_STATE_INVALID', 503);
      const recent = [...history.filter(item => item.run_id !== value.run_id), value].slice(-20);
      this.bridge.db.run('INSERT INTO runtime_meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json', this.key, canonical(value));
      this.bridge.db.run('INSERT INTO runtime_meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json', key, canonical(recent));
    });
  }
  protectedSources() {
    requireValue(this.bridge.game && !this.bridge.game.closed || !existsSync(join(this.bridge.root, this.bridge.policy.deployment.state_relative_path, 'game/game.sqlite3')), 'AUDIENCE_RETENTION_GAME_UNAVAILABLE', 503);
    const b = this.bridge, current = b.state.status(), requests = [current.active_request?.request_id, ...current.queued.map(row => row.request_id)].filter(Boolean);
    const keys = new Set([b.room.board.pinned_id, b.room.board.featured_id].filter(Boolean));
    for (const request of requests) for (const key of b.room.speechLinks[request] || []) keys.add(key);
    if (b.game) for (const row of b.game.store.all("SELECT value FROM objects WHERE kind='suggestion' AND json_extract(value,'$.task_id') IS NOT NULL")) {
      const suggestion = JSON.parse(row.value); let task;
      try { task = b.game.tasks.get(suggestion.task_id); } catch { /* Missing effects remain unresolved and protected. */ }
      if (task && TERMINAL.has(task.state) && (task.effect_status !== 'unknown' || task.disposition?.status === 'closed_unknown') &&
        (!task.recovery || ['verified','operator_closed'].includes(task.recovery.status))) continue;
      for (const key of suggestion.source_event_ids || []) keys.add(key);
      for (const source of b.game.audienceSources.rows(suggestion.suggestion_id)) keys.add(source.event_id);
    }
    return { requests, keys: [...keys] };
  }
  run() {
    const b = this.bridge;
    requireValue(!this.running && !b.administration?.locked && !b.administration?.privacyPending, 'AUDIENCE_RETENTION_BUSY', 503);
    requireValue(!b.platforms.closed && !b.room.closed, 'AUDIENCE_RETENTION_UNAVAILABLE', 503);
    this.running = true;
    const report = { run_id: id('retention'), started_at: utc(b.db.now()), status: 'running', phase: 'ownership',
      platform_events_removed: 0, room_messages_removed: 0, room_sources_replayed: 0, ownership_records_updated: 0, counts_complete: false };
    try {
      this.save(report);
      const protectedSources = this.protectedSources(); report.protected_sources = protectedSources.keys.length;
      report.phase = 'platform';
      const platform = b.platforms.store.prune({ protectedRequests: protectedSources.requests, protectedKeys: protectedSources.keys,
        beforeRemove: rows => { report.ownership_records_updated += this.privacy.ownership.record(rows); } });
      report.platform_events_removed = platform.removed; this.save(report);
      report.phase = 'room';
      const room = b.room.pruneHistory({ protectedKeys: protectedSources.keys });
      report.room_messages_removed = room.removed_ids.length;
      report.room_sources_replayed = room.recovered_sources;
      report.more = platform.more || room.more;
      report.unmapped_room_messages = this.privacy.expand({ schema_version: 1, subject_key: 'public', cutoff: b.db.now(), all: true, event_keys: [], room_user_keys: [] }).unmapped;
      report.status = report.more ? 'remaining' : 'completed'; report.phase = 'complete'; report.finished_at = utc(b.db.now()); report.counts_complete = true;
      this.save(report); return this.status();
    } catch (error) {
      if (Number.isSafeInteger(error.retentionRoomRemoved)) report.room_messages_removed = error.retentionRoomRemoved;
      report.status = 'failed'; report.error = error.code || 'AUDIENCE_RETENTION_FAILED'; report.finished_at = utc(b.db.now());
      try { this.save(report); } catch { /* A failed canonical writer must not allow further pruning. */ }
      throw error;
    } finally { this.running = false; }
  }
}
