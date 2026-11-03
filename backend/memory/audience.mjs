import { canonical, digest } from '../dsh-bridge/channel.mjs';
import { requireValue } from '../dsh-bridge/state.mjs';
import { eventPrincipal } from '../platforms/events.mjs';

export const audiencePrincipal = source => source.identity_quality === 'platform_id' && ['blivedm', 'open_live'].includes(source.source) ? eventPrincipal(source) : null;
const changed = () => requireValue(false, 'GAME_NARRATION_FACTS_CHANGED');

// Only the canonical StateStore writes memory. This class binds actual input
// identities; it does not create another memory store or a second player.
export class AudienceMemory {
  constructor(memory, resolve) { this.memory = memory; this.db = memory.db; this.state = memory.state; this.resolve = resolve; }
  descriptors(value) {
    requireValue(value && typeof value.scope_id === 'string' && Array.isArray(value.sources) && value.sources.length <= 32, 'AUDIENCE_SCOPE_INVALID', 422);
    const seen = new Set();
    return value.sources.map(source => {
      requireValue(source && source.platform === 'bilibili' && typeof source.room_id === 'string' && /^[a-f0-9]{64}$/.test(source.event_key) && typeof source.text === 'string' && source.text.length <= 1500 && !seen.has(source.event_key), 'AUDIENCE_SOURCE_INVALID', 422);
      seen.add(source.event_key);
      const principal = audiencePrincipal(source);
      const subject = principal?.role === 'viewer' ? principal.viewer_id : null;
      const fingerprint = digest({ key: source.event_key, platform: source.platform, room: source.room_id, text: source.text, subject, occurred_at: source.occurred_at });
      return { source, subject, principal, fingerprint };
    });
  }
  marker(request) { return this.db.get("SELECT e.*,p.payload_json,p.redacted_at FROM stream_events e JOIN event_payloads p USING(event_seq) WHERE e.request_id=? AND e.event_type='audience.bound' ORDER BY e.event_seq DESC LIMIT 1", request.request_id); }
  bind(request) {
    request = this.state.request(request.request_id);
    requireValue(request, 'REQUEST_NOT_FOUND', 404);
    const value = this.resolve(request);
    requireValue(value, 'AUDIENCE_SCOPE_UNAVAILABLE', 503);
    const sources = this.descriptors(value), prior = this.marker(request);
    if (prior) return this.scope(request);
    return this.db.tx(() => {
      const saved = this.state.request(request.request_id);
      requireValue(saved?.status === 'QUEUED' && saved.runtime_epoch === request.runtime_epoch, 'AUDIENCE_REQUEST_INVALID');
      const refs = [];
      for (const { source, subject, principal, fingerprint } of sources) {
        const index = 'audience-source:' + digest([...this.state.characterRoom, source.event_key]);
        const old = this.db.get('SELECT value_json FROM runtime_meta WHERE key=?', index);
        let event;
        if (old) {
          const ref = JSON.parse(old.value_json);
          event = this.db.get('SELECT e.*,p.payload_json,p.redacted_at FROM stream_events e JOIN event_payloads p USING(event_seq) WHERE e.event_id=?', ref.event_id);
          requireValue(event && !event.redacted_at && event.broadcast_id === request.broadcast_id, 'AUDIENCE_SOURCE_UNAVAILABLE');
          requireValue(JSON.parse(event.payload_json).audience_source.fingerprint === fingerprint, 'AUDIENCE_SOURCE_CHANGED');
        } else {
          const seq = this.db.event(this.state.scope(request, { actor_kind: subject ? 'viewer' : 'operator', actor_id: principal?.principal_id || 'mc-public-source', occurred_at: new Date(source.occurred_at).toISOString() }), 'input.accepted', {
            text: source.text, partition_key: subject || 'public', viewer_id: subject, verified_principal: principal?.principal_id || null,
            audience_source: { scope_id: value.scope_id, platform_event_key: source.event_key, fingerprint, personal: !!subject,
              platform: source.platform, room_id: source.room_id, collector: source.source, occurred_at: source.occurred_at,
              room_user_key: source.room_user_key || null },
          });
          event = this.db.get('SELECT * FROM stream_events WHERE event_seq=?', seq);
          this.db.run('INSERT INTO runtime_meta VALUES (?,?)', index, canonical({ event_id: event.event_id, event_seq: seq }));
        }
        const fence = this.memory.fence(subject || 'public');
        requireValue(!fence || event.event_seq > fence.event_seq, 'DELETION_FENCE');
        refs.push({ event_id: event.event_id, event_seq: event.event_seq, platform_event_key: source.event_key, fingerprint });
      }
      this.db.event(this.state.scope(request), 'audience.bound', { schema_version: 1, scope_id: value.scope_id, sources: refs });
      return refs;
    });
  }
  scope(request) {
    request = this.state.request(request.request_id);
    requireValue(request, 'REQUEST_NOT_FOUND', 404);
    const marker = this.marker(request), input = this.state.input(request);
    if (!marker) {
      requireValue(input.source?.collector !== 'mc-narration', 'AUDIENCE_SCOPE_UNBOUND', 503);
      requireValue(!input.redacted, 'CONTEXT_REDACTED', 409);
      return null;
    }
    requireValue(!marker.redacted_at && marker.payload_json, 'CONTEXT_REDACTED', 409);
    const bound = JSON.parse(marker.payload_json), current = this.resolve(request);
    if (!current || current.scope_id !== bound.scope_id) changed();
    const actual = this.descriptors(current);
    if (canonical(actual.map(value => [value.source.event_key, value.fingerprint])) !== canonical(bound.sources.map(value => [value.platform_event_key, value.fingerprint]))) changed();
    const sources = bound.sources.map(ref => {
      const event = this.db.get('SELECT e.*,p.payload_json,p.redacted_at FROM stream_events e JOIN event_payloads p USING(event_seq) WHERE e.event_id=?', ref.event_id);
      requireValue(event && !event.redacted_at && event.payload_json, 'CONTEXT_REDACTED');
      const data = JSON.parse(event.payload_json), fence = this.memory.fence(data.partition_key);
      requireValue(!fence || event.event_seq > fence.event_seq, 'DELETION_FENCE');
      return { ...ref, payload_sha256: event.payload_sha256, partition_key: data.partition_key, personal: data.audience_source.personal, text: data.text };
    });
    return { scope_id: bound.scope_id, sources };
  }
  view(scope, query, request) {
    const participants = [], partitions = [...new Set(scope.sources.filter(source => source.personal).map(source => source.partition_key))];
    let remaining = this.memory.policy.memory.viewer_max_chars, historyChars = 1200;
    for (const partition of partitions) {
      const found = this.memory.recall(partition, query).viewer, entries = [];
      for (const entry of found) if (entry.content.length <= remaining) { entries.push(entry); remaining -= entry.content.length; }
      const currentIds = new Set(scope.sources.map(source => source.event_id));
      const history = this.memory.eligibleEvents(request.broadcast_id, partition, { end: request.input_event_seq - 1 }).filter(event => !currentIds.has(event.event_id)).slice(-4);
      const recent = [];
      for (const event of history) {
        const text = event.text.slice(0, 200);
        if (text.length <= historyChars) { recent.push({ event_id: event.event_id, role: event.event_type === 'input.accepted' ? 'user' : 'assistant', text }); historyChars -= text.length; }
      }
      const owned = scope.sources.filter(source => source.partition_key === partition);
      participants.push({ source_event_ids: owned.map(source => source.event_id), platform_event_keys: owned.map(source => source.platform_event_key),
        confirmed_memory: entries.map(({ subject_key, ...entry }) => entry), omitted_memory_count: found.length - entries.length, ...(recent.length ? { recent_confirmed_events: recent } : {}) });
    }
    return { schema_version: 1, participants, unidentified_events: scope.sources.filter(source => !source.personal).length,
      rules: '各账号记忆只属于所列来源，不代表所有观众。身份未知来源不建立个人记忆。需要查询指定账号时用其source_event_id，禁止自行指定身份。' };
  }
  select(scope, eventId) {
    const identified = scope.sources.filter(source => source.personal), partitions = new Set(identified.map(source => source.partition_key));
    if (!eventId && partitions.size === 1 && identified.length === scope.sources.length) return identified[0];
    if (!eventId) return null;
    const source = scope.sources.find(source => source.event_id === eventId);
    requireValue(source?.personal, 'MEMORY_SOURCE_OUT_OF_SCOPE', 422);
    return source;
  }
}
