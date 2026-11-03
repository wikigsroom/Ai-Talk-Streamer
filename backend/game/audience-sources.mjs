import { canonical } from '../dsh-bridge/channel.mjs';
import { hash } from './store.mjs';
import { utc } from './errors.mjs';

export const SUPPORT_LIMITS = Object.freeze({ per_suggestion: 4096, total: 32768, terminal_retention_ms: 86400000 });
const live = value => ['proposed', 'accepted'].includes(value.state);

// Store source identities independently of the bounded32-item public preview.
// No viewer text, nickname or original platform UID is duplicated here.
export class AudienceSources {
  constructor(manager) { this.manager = manager; this.store = manager.store; }
  prefix(id) { return id + ':'; }
  rows(id) { const prefix = this.prefix(id); return this.store.all("SELECT value FROM objects WHERE kind='audience_support' AND id>=? AND id<? ORDER BY id", prefix, prefix + '\uffff').map(row => JSON.parse(row.value)); }
  total() { return this.store.get("SELECT COUNT(*) n FROM objects WHERE kind='audience_support'").n; }
  budget() { return { per_suggestion: SUPPORT_LIMITS.per_suggestion, total_limit: SUPPORT_LIMITS.total, tracked_events: this.total(), terminal_retention_ms: SUPPORT_LIMITS.terminal_retention_ms }; }
  expired(value) { return !live(value) && Date.parse(value.expires_at) + SUPPORT_LIMITS.terminal_retention_ms <= this.manager.wall(); }
  ensure(value) {
    const saved = this.store.object('audience_support_manifest', value.suggestion_id);
    if (saved || this.expired(value)) return saved;
    const existing = new Set(this.rows(value.suggestion_id).map(row => row.event_id));
    let available = Math.min(SUPPORT_LIMITS.per_suggestion - existing.size, SUPPORT_LIMITS.total - this.total());
    for (const eventId of value.source_event_ids) if (!existing.has(eventId) && available-- > 0) {
      this.record(value, eventId); existing.add(eventId);
    }
    const manifest = { audience_support_manifest_id: value.suggestion_id, world_session_id: value.world_session_id,
      coverage: existing.size === value.support_count ? 'complete' : 'legacy_partial' };
    this.store.put('audience_support_manifest', manifest); return manifest;
  }
  record(value, eventId) {
    this.store.put('audience_support', { audience_support_id: this.prefix(value.suggestion_id) + hash(eventId),
      suggestion_id: value.suggestion_id, world_session_id: value.world_session_id, event_id: eventId });
  }
  canAdd(value, eventId) {
    if (value) {
      if (value.support_count >= 1000000) return false;
      this.ensure(value);
      const rows = this.rows(value.suggestion_id);
      if (rows.some(row => row.event_id === eventId) || rows.length >= SUPPORT_LIMITS.per_suggestion) return false;
    }
    return this.total() < SUPPORT_LIMITS.total;
  }
  messages(ids) {
    const room = this.manager.bridge.room;
    if (!room?.store) return new Map();
    const messages = room.store.messagesById ? room.store.messagesById(ids) : ids.map(id => room.store.message(id)).filter(Boolean);
    return new Map(messages.map(message => [message.id || message.event_key, message]));
  }
  visible(message, roomId) {
    const room = this.manager.bridge.room;
    return !!message && message.platform === 'bilibili' && message.room_id === roomId && !message.test && !message.hidden && !room.blocked(message);
  }
  visibleIds(value) {
    this.ensure(value);
    const ids = this.rows(value.suggestion_id).map(row => row.event_id), messages = this.messages(ids);
    return ids.filter(id => this.visible(messages.get(id), value.origin.room_id)).slice(0, 32);
  }
  support(value) {
    const manifest = this.ensure(value), rows = this.expired(value) ? [] : this.rows(value.suggestion_id), messages = this.messages(rows.map(row => row.event_id));
    const available = !!this.manager.bridge.room?.store && !this.manager.bridge.room.closed;
    const visible = rows.map(row => messages.get(row.event_id)).filter(message => this.visible(message, value.origin.room_id));
    const identified = visible.filter(message => typeof message.user_key === 'string' && message.user_key.length);
    return { schema_version: 1, historical_events: value.support_count, tracked_events: rows.length, source_availability: available ? 'available' : 'unavailable', visible_events: available ? visible.length : null,
      visible_viewers: available ? new Set(identified.map(message => message.user_key)).size : null, unidentified_events: available ? visible.length - identified.length : null,
      coverage: this.expired(value) ? 'retained_window_expired' : manifest.coverage, evaluated_at: utc(this.manager.wall()) };
  }
  refresh(value, { publish = true, bump = true } = {}) {
    if (value.origin?.kind !== 'audience') return value;
    const support = this.support(value), comparable = ({ evaluated_at, ...fields }) => fields;
    if (value.support && canonical(comparable(value.support)) === canonical(comparable(support))) return value;
    const next = { ...value, support, revision: value.revision + (bump ? 1 : 0) };
    this.store.put('suggestion', next); if (publish) this.manager.publish('suggestion', next); return next;
  }
  prune() {
    for (const row of this.store.all("SELECT id FROM objects WHERE kind='audience_support_manifest'")) {
      const value = this.store.object('suggestion', row.id);
      if (value && !this.expired(value)) continue;
      const prefix = this.prefix(row.id);
      this.store.transaction(() => {
        this.store.run("DELETE FROM objects WHERE kind='audience_support' AND id>=? AND id<?", prefix, prefix + '\uffff');
        this.store.run("DELETE FROM objects WHERE kind='audience_support_manifest' AND id=?", row.id);
      });
    }
  }
}
