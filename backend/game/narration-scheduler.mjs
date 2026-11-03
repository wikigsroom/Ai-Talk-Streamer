import { hash } from './store.mjs';
import { utc } from './errors.mjs';

export const NARRATION_DEFAULTS = Object.freeze({ enabled: true, merge_window_ms: 3000,
  aging_step_ms: 2000, topic_cooldown_ms: 3000, critical_interrupt: true,
  interrupt_fresh_ms: 2000, interrupt_cooldown_ms: 10000 });
export const sourceIds = item => item.source_ids || [item.source_id];
const baseScore = { urgent: 80, question: 30, task: 25, gift: 15, status: 10 };
const levels = { normal: 0, important: 1, critical: 2 };
const eventTime = source => typeof source.occurred_at === 'number' ? source.occurred_at : Date.parse(source.occurred_at);

// Policy operates on the existing candidate and StreamState, without owning a
// second model loop, speaker, game controller or playback authority.
export class NarrationScheduler {
  constructor(queue) { this.queue = queue; this.manager = queue.manager; }
  settings() { return { ...NARRATION_DEFAULTS, ...this.manager.config.narration }; }
  severity(source) {
    const state = this.manager.state.view();
    const lowHealth = source.kind === 'damage' && Number.isFinite(source.data?.health) && source.data.health <= 4 &&
      source.data.health >= 0 && Number.isFinite(state.player?.health) && state.player.health <= 4;
    return source.severity === 'critical' || lowHealth ? 'critical' : source.severity || 'normal';
  }
  metadata(kind, id) {
    const source = this.queue.rawSource(kind, id); if (!source) return null;
    let topic;
    if (kind === 'question') topic = String(source.text).normalize('NFKC').trim().replace(/\s+/gu, ' ').toLocaleLowerCase('und');
    // An unknown platform identity is never merged by nickname.
    else if (kind === 'gift') topic = source.gift_name ? [source.user_key || id, source.gift_name, source.platform_fields?.quality || 'unverified'] : id;
    else if (kind === 'game_event') topic = [source.kind, source.task_id, source.data?.item_id || null, source.data?.entity_id || null];
    else if(kind==='task_result')topic=[source.goal?.skill??null,source.goal?.item_id??null,source.state??null,source.reason??null];
    else if(kind==='programme_beat')topic='autonomous_programme';
    else topic = id;
    const at = Date.parse(source.updated_at||source.observed_at)||eventTime(source);
    return { topic_key: hash([kind, topic]), severity: kind === 'game_event' ? this.severity(source) : 'normal',
      first_event_at: utc(Number.isFinite(at) ? at : this.manager.wall()),
      last_event_at: utc(Number.isFinite(at) ? at : this.manager.wall()) };
  }
  merge(kind, id, sourceEventIds, metadata) {
    const settings = this.settings(), now = this.manager.wall();
    if (!metadata || !settings.merge_window_ms || !['question', 'gift', 'game_event'].includes(kind)) return null;
    const state = this.manager.state.value, live = this.queue.live();
    const item = this.queue.open().find(value => value.state === 'pending' && value.attempt === 0 && value.kind === kind &&
      value.topic_key === metadata.topic_key && value.broadcast_id === live.broadcast_id && value.room_id === this.manager.roomId() &&
      value.world_session_id === state.world_session_id && now < Date.parse(value.expires_at) &&
      now - Date.parse(value.created_at) <= settings.merge_window_ms && sourceIds(value).length < 32 &&
      Math.max(Date.parse(value.last_event_at), Date.parse(metadata.last_event_at)) -
        Math.min(Date.parse(value.first_event_at), Date.parse(metadata.first_event_at)) <= settings.merge_window_ms);
    if (!item) return null;
    return this.queue.save(item, { source_ids: [...sourceIds(item), id],
      source_event_ids: [...new Set([...item.source_event_ids, ...sourceEventIds])],
      first_event_at: utc(Math.min(Date.parse(item.first_event_at), Date.parse(metadata.first_event_at))),
      last_event_at: utc(Math.max(Date.parse(item.last_event_at), Date.parse(metadata.last_event_at))),
      severity: levels[metadata.severity] > levels[item.severity] ? metadata.severity : item.severity });
  }
  source(item) {
    const entries = sourceIds(item).map(id => this.queue.rawSource(item.kind, id)).filter(Boolean);
    if (!entries.length) return null;
    if (entries.length === 1) return entries[0];
    const timing = { event_count: entries.length, first_event_at: item.first_event_at, last_event_at: item.last_event_at };
    if (item.kind === 'question') return { ...entries[0], aggregation: { ...timing,
      matching_question_ids: entries.map(value => value.id),
      messages: entries.map(({ id, nickname, notice_kind, platform_fields: fields }) => ({ id, nickname, notice_kind,
        quality: fields?.quality || 'unverified', superchat: fields?.superchat ? { amount_fen: fields.superchat.amount_fen, currency: fields.superchat.currency } : null, roles: fields?.roles || null })) } };
    if (item.kind === 'gift') {
      const counts = entries.map(value => value.gift_count), total = counts.reduce((sum, count) => sum + count, 0);
      const known = counts.every(value => Number.isSafeInteger(value) && value > 0) && Number.isSafeInteger(total), first = entries[0].platform_fields;
      const fields = first ? { ...first, gift: { ...first.gift, count: known ? total : null },
        field_status: { ...first.field_status, 'gift.count': known ? 'known' : 'missing' },
        unknown_fields: [...new Set([...entries.flatMap(value => value.platform_fields?.unknown_fields || []), ...(!known ? ['gift.count'] : [])])] } : undefined;
      return { ...entries[0], gift_count: known ? total : null, ...(fields ? { platform_fields: fields } : {}),
        aggregation: { ...timing, unknown_fields: known ? [] : ['gift_count'], gifts: entries.map(({ id, gift_name, gift_count, occurred_at, platform_fields: fields }) => ({ id, gift_name, gift_count, occurred_at,
          quality: fields?.quality || 'unverified', count_status: fields?.field_status?.['gift.count'] || 'missing' })) } };
    }
    const changes = {};
    for (const key of ['health_delta', 'count_delta']) {
      const values = entries.map(value => value.data?.[key]);
      changes[key] = values.every(Number.isFinite) ? values.reduce((sum, value) => sum + value, 0) : null;
    }
    return { ...entries.at(-1), aggregation: { ...timing, severity: item.severity, changes,
      unknown_fields: Object.keys(changes).filter(key => changes[key] === null),
      events: entries.map(({ event_id, seq, occurred_at, severity, data }) => ({ event_id, seq, occurred_at, severity, data })) } };
  }
  wait(item) { return Math.max(0, this.manager.wall() - Date.parse(item.created_at)); }
  score(item) { return baseScore[item.group] + Math.min(50, Math.floor(this.wait(item) / this.settings().aging_step_ms) * 5); }
  replacement(active, incomingGroup, incomingSeverity) {
    const pending = active.filter(item => item.state === 'pending' && item.attempt === 0);
    const ordinary = pending.filter(item => item.group !== 'urgent');
    const lessUrgent = pending.filter(item => !this.freshCritical(item));
    const allowed = ordinary.length ? ordinary : incomingGroup === 'urgent' ?
      lessUrgent.length ? lessUrgent : incomingSeverity === 'critical' ? pending : [] : [];
    const counts = new Map();
    for (const item of allowed) counts.set(item.group, (counts.get(item.group) || 0) + 1);
    return allowed.sort((a, b) => (counts.get(b.group) - counts.get(a.group)) ||
      this.score(a) - this.score(b) || Date.parse(b.created_at) - Date.parse(a.created_at))[0] || null;
  }
  topicId(item) { return hash([item.broadcast_id, item.world_session_id, item.topic_key]); }
  cooldown(item) {
    if (!item.topic_key || item.attempt || item.group === 'urgent') return 0;
    const last = this.manager.store.meta('narration_topics', {})[this.topicId(item)];
    const gap=item.kind==='task_result'&&this.queue.rawSource(item.kind,item.source_id)?.state==='failed'?30000:this.settings().topic_cooldown_ms;
    return last ? Math.max(0, gap - Math.max(0, this.manager.wall() - last)) : 0;
  }
  next(pending) {
    const eligible = pending.filter(item => !this.cooldown(item));
    const urgent = eligible.filter(item => item.group === 'urgent'), ordinary = eligible.filter(item => item.group !== 'urgent');
    const streak = this.manager.store.meta('narration_urgent_streak', 0);
    const useUrgent = urgent.length && (streak < 2 || !ordinary.length);
    const freshCritical = useUrgent ? urgent.filter(item => this.freshCritical(item)) : [];
    const candidates = useUrgent ? freshCritical.length ? freshCritical : urgent : ordinary;
    // open() is in durable insertion order; stable sorting preserves FIFO when
    // timestamps and weights match, including bursts within one millisecond.
    return candidates.sort((a, b) => this.score(b) - this.score(a) || Date.parse(a.created_at) - Date.parse(b.created_at))[0] || null;
  }
  submitted(item) {
    const now = this.manager.wall(), topics = this.manager.store.meta('narration_topics', {});
    if (item.topic_key) topics[this.topicId(item)] = now;
    const retained = Object.entries(topics).filter(([, at]) => at <= now && now - at < 60000).sort((a, b) => b[1] - a[1]).slice(0, 256);
    this.manager.store.setMeta('narration_topics', Object.fromEntries(retained));
    const streak = this.manager.store.meta('narration_urgent_streak', 0);
    this.manager.store.setMeta('narration_urgent_streak', item.group === 'urgent' ? streak + 1 : 0);
  }
  freshCritical(item) {
    const now = this.manager.wall(), maximumAge = this.settings().interrupt_fresh_ms;
    return item.kind === 'game_event' && item.severity === 'critical' && sourceIds(item).some(id => {
      const source = this.queue.rawSource('game_event', id), at = source && eventTime(source);
      return source && this.severity(source) === 'critical' && Number.isFinite(at) && at <= now + 2000 && now - at <= maximumAge;
    });
  }
  preempt(pending) {
    const m = this.manager, bridge = m.bridge, settings = this.settings(), active = bridge.state.active();
    if (!settings.enabled || !settings.critical_interrupt || !active || typeof bridge.mediaCommand !== 'function' ||
        typeof bridge.state.cancel !== 'function' || !bridge.state.listenerCount?.('cancel')) return;
    const last = m.store.meta('narration_interruption', null);
    if (last && m.wall() - Date.parse(last.at) < settings.interrupt_cooldown_ms) return;
    const victim = this.queue.byRequest(active.request_id);
    // Private/operator announcements and urgent responses retain their turn.
    if (!victim || victim.group === 'urgent' || !['queued', 'thinking', 'synthesizing', 'playing'].includes(victim.state)) return;
    const urgent = pending.find(item => this.freshCritical(item));
    if (!urgent) return;
    this.queue.valid(urgent);
    const interruption = { at: utc(m.wall()), narration_id: urgent.narration_id, request_id: active.request_id, status: 'cancel_unconfirmed' };
    m.store.setMeta('narration_interruption', interruption);
    this.queue.save(victim, { state: 'cancelled', reason: 'CRITICAL_EVENT_PREEMPTED', preempted_by: urgent.narration_id });
    this.queue.observations.delete(active.request_id);
    try {
      const barrier = bridge.state.cancel(active.request_id, 'CRITICAL_EVENT_PREEMPTED');
      if (!barrier || bridge.state.active()?.request_id === active.request_id) throw new Error('cancel_unconfirmed');
      m.store.setMeta('narration_interruption', { ...interruption, status: 'cancel_requested', ...(barrier.barrier_id ? { barrier_id: barrier.barrier_id } : {}) });
      this.queue.save(urgent, { interrupted_request_id: active.request_id });
    } catch {
      this.queue.save(this.queue.get(victim.narration_id), { state: 'unknown', reason: 'CRITICAL_CANCEL_UNCONFIRMED' });
    }
  }
  view() {
    const pending = this.queue.open().filter(item => item.state === 'pending');
    return { settings: this.settings(), next_narration_id: this.settings().enabled ? this.next(pending)?.narration_id || null : null,
      last_interruption: this.manager.store.meta('narration_interruption', null) };
  }
}
