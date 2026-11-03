import { canonical, digest } from '../dsh-bridge/channel.mjs';
import { requireValue } from '../dsh-bridge/state.mjs';
import { eventPrincipal } from './events.mjs';

export const roomOwnerKey = event => event.user_id ? digest([event.platform, event.room_id, event.user_id]) : null;
const opaque = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

// This is canonical provenance, not a second viewer-memory store. It survives
// removal of raw collector rows and contains neither UID nor display content.
export class AudienceOwnership {
  constructor(bridge) { this.bridge = bridge; this.prefix = 'audience-owner:' + digest(bridge.state.characterRoom) + ':'; }
  record(events) {
    const rows = new Map();
    for (const event of events) {
      if (event.platform !== 'bilibili' || event.identity_quality !== 'platform_id' || !['blivedm','open_live'].includes(event.source) || !event.user_id) continue;
      const key = roomOwnerKey(event), principal = eventPrincipal(event);
      requireValue(opaque(key) && principal.role === 'viewer', 'AUDIENCE_OWNER_INVALID', 503);
      const seen = Number.isSafeInteger(event.received_at) ? event.received_at : this.bridge.db.now();
      const old = rows.get(key);
      rows.set(key, { schema_version: 1, room_user_key: key, subject_key: principal.viewer_id,
        first_seen_at: Math.min(old?.first_seen_at ?? seen, seen), last_seen_at: Math.max(old?.last_seen_at ?? seen, seen) });
    }
    if (!rows.size) return 0;
    return this.bridge.db.tx(() => {
      let changed = 0;
      for (const [key, next] of rows) {
        const row = this.bridge.db.get('SELECT value_json FROM runtime_meta WHERE key=?', this.prefix + key);
        const old = row && JSON.parse(row.value_json);
        requireValue(!old || old.schema_version === 1 && old.room_user_key === key && old.subject_key === next.subject_key &&
          Number.isSafeInteger(old.first_seen_at) && Number.isSafeInteger(old.last_seen_at) && old.first_seen_at <= old.last_seen_at, 'AUDIENCE_OWNER_CONFLICT', 503);
        if (old) { next.first_seen_at = Math.min(old.first_seen_at, next.first_seen_at); next.last_seen_at = Math.max(old.last_seen_at, next.last_seen_at); }
        if (canonical(old || null) === canonical(next)) continue;
        this.bridge.db.run('INSERT INTO runtime_meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json', this.prefix + key, canonical(next)); changed++;
      }
      return changed;
    });
  }
  mappings() {
    return this.bridge.db.all('SELECT key,value_json FROM runtime_meta WHERE key LIKE ?', this.prefix + '%').map(row => {
      const value = JSON.parse(row.value_json);
      requireValue(value.schema_version === 1 && opaque(value.room_user_key) && row.key === this.prefix + value.room_user_key &&
        typeof value.subject_key === 'string' && /^viewer:bilibili:[a-f0-9]{40}$/.test(value.subject_key) &&
        Number.isSafeInteger(value.first_seen_at) && Number.isSafeInteger(value.last_seen_at) && value.first_seen_at <= value.last_seen_at, 'AUDIENCE_OWNER_INVALID', 503);
      return value;
    });
  }
  count() { return this.bridge.db.get('SELECT COUNT(*) n FROM runtime_meta WHERE key LIKE ?', this.prefix + '%').n; }
}
