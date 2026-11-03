import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { digest } from '../dsh-bridge/channel.mjs';
import { requireValue } from '../dsh-bridge/state.mjs';
import { eventPrincipal } from './events.mjs';
import { AudienceOwnership, roomOwnerKey } from './ownership.mjs';
import { AudienceRetention } from './retention.mjs';

const roomKey = roomOwnerKey;
const opaque = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

// A durable canonical deletion plan contains opaque references, never a second
// copy of an erased account, nickname or message body. Each store is retriable.
export class PlatformPrivacy {
  constructor(bridge) { this.bridge = bridge; this.ownership = new AudienceOwnership(bridge); this.retention = new AudienceRetention(this); }
  plans() {
    return this.bridge.db.all("SELECT value_json FROM runtime_meta WHERE key LIKE 'privacy-projection:%' ORDER BY key").map(row => JSON.parse(row.value_json));
  }
  prepare({ subject, selectedMemoryId, sources }) {
    const all = !selectedMemoryId && subject !== 'public', keys = new Set(), users = new Set(), requests = new Set();
    for (const event of sources) {
      const source = event.data?.audience_source;
      if (opaque(source?.platform_event_key)) keys.add(source.platform_event_key);
      if (opaque(source?.room_user_key)) users.add(source.room_user_key);
      const input = event.data?.source;
      if (input?.collector !== 'mc-narration' && opaque(input?.event_key)) keys.add(input.event_key);
      if (input?.platform === 'bilibili' && ['blivedm','open_live'].includes(input.collector) &&
        typeof input.room_id === 'string' && input.room_id.length > 0 && input.room_id.length <= 100 &&
        typeof input.event_id === 'string' && input.event_id.length > 0 && input.event_id.length <= 203)
        keys.add(digest([input.platform, input.room_id, input.event_id]));
      if (!source && input?.collector !== 'mc-narration' && event.request_id) requests.add(event.request_id);
    }
    const cutoff = this.bridge.db.now();
    if (all) for (const owner of this.ownership.mappings()) if (owner.subject_key === subject) users.add(owner.room_user_key);
    for (const row of this.bridge.platforms.store.all('SELECT * FROM events')) {
      if (keys.has(row.event_key) || requests.has(row.request_id) || all && row.user_id && eventPrincipal(row).viewer_id === subject && row.received_at <= cutoff) {
        keys.add(row.event_key); const key = roomKey(row); if (key) users.add(key);
      }
    }
    return { schema_version: 1, subject_key: subject, cutoff, all, event_keys: [...keys].sort(), room_user_keys: [...users].sort() };
  }
  expand(plan) {
    requireValue(plan?.schema_version === 1 && typeof plan.subject_key === 'string' && plan.subject_key.length <= 300 &&
      Number.isSafeInteger(plan.cutoff) && typeof plan.all === 'boolean' && Array.isArray(plan.event_keys) && plan.event_keys.every(opaque) &&
      Array.isArray(plan.room_user_keys) && plan.room_user_keys.every(opaque), 'PRIVACY_PLAN_INVALID', 503);
    const keys = new Set(plan.event_keys), users = new Set(plan.room_user_keys), known = new Set(users);
    for (const owner of this.ownership.mappings()) {
      known.add(owner.room_user_key);
      if (plan.all && owner.subject_key === plan.subject_key) users.add(owner.room_user_key);
    }
    for (const prior of this.plans()) for (const key of prior.room_user_keys) known.add(key);
    for (const row of this.bridge.db.all("SELECT payload_json FROM event_payloads WHERE json_extract(payload_json,'$.audience_source.room_user_key') IS NOT NULL")) {
      const key = JSON.parse(row.payload_json).audience_source.room_user_key; if (opaque(key)) known.add(key);
    }
    for (const row of this.bridge.platforms.store.all('SELECT * FROM events')) {
      const key = roomKey(row); if (key) known.add(key);
      if (plan.all && row.user_id && eventPrincipal(row).viewer_id === plan.subject_key && (row.received_at <= plan.cutoff || row.occurred_at <= plan.cutoff)) {
        keys.add(row.event_key); if (key) users.add(key);
      }
    }
    let unmapped = 0;
    for (const row of this.bridge.room.store.all('SELECT * FROM messages')) {
      const value = JSON.parse(row.value);
      if (plan.all && value.user_key && value.platform !== 'operator' && !known.has(value.user_key)) unmapped++;
      if (keys.has(row.event_key) || plan.all && users.has(value.user_key) && (row.received_at <= plan.cutoff || value.occurred_at <= plan.cutoff)) keys.add(row.event_key || row.id);
    }
    return { keys: [...keys], users, unmapped };
  }
  applyGame(game, plan, keys) {
    const removed = new Set(keys);
    game.intents?.eraseSources(keys);
    game.narration.observations.clear(); game.planner.cancel();
    for (let offset = 0; offset < keys.length; offset += 200) game.votes.withdrawSources(keys.slice(offset, offset + 200));
    game.store.transaction(() => {
      for (const row of game.store.all("SELECT id,value FROM objects WHERE kind='audience_support'")) {
        if (removed.has(JSON.parse(row.value).event_id)) game.store.run("DELETE FROM objects WHERE kind='audience_support' AND id=?", row.id);
      }
      for (const row of game.store.all("SELECT value FROM objects WHERE kind='suggestion'")) {
        const value = JSON.parse(row.value), refs = value.source_event_ids.filter(key => !removed.has(key));
        if (refs.length !== value.source_event_ids.length) { value.source_event_ids = refs; value.revision++; game.store.put('suggestion', value); }
      }
    });
    game.suggestions.reconcileSources(); game.narration.sweep();
  }
  applyGameHistory(game) {
    for (const plan of this.plans()) this.applyGame(game, plan, this.expand(plan).keys);
  }
  async apply(plan) {
    const b = this.bridge, { keys, unmapped } = this.expand(plan), store = b.platforms.store;
    store.db.exec('BEGIN IMMEDIATE');
    try {
      if (plan.all) store.run('INSERT INTO privacy_fences VALUES (?,?) ON CONFLICT(subject_key) DO UPDATE SET cutoff=MAX(cutoff,excluded.cutoff)', plan.subject_key, plan.cutoff);
      for (const key of keys) {
        store.run('INSERT OR IGNORE INTO privacy_deletions VALUES (?,?)', key, plan.cutoff);
        store.run("UPDATE events SET user_id=NULL,nickname='',text='',identity_quality='display_only',detail='{}',session_id=NULL,status=CASE WHEN status='COMPLETED' THEN status ELSE 'DROPPED' END,reason='privacy_deleted' WHERE event_key=?", key);
      }
      store.db.exec('COMMIT');
    } catch (error) { store.db.exec('ROLLBACK'); throw error; }
    b.room.eraseSources(keys);
    const file = join(b.root, b.policy.deployment.state_relative_path, 'game/game.sqlite3');
    if (!b.game && existsSync(file)) await b.loadGame();
    if (b.game) this.applyGame(b.game, plan, keys);
    requireValue(!unmapped, 'MEMORY_PRIVACY_COVERAGE_INCOMPLETE', 503);
  }
}
