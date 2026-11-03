import { randomUUID } from 'node:crypto';
import { canonical } from '../dsh-bridge/channel.mjs';
import { ensure, GameError, utc } from './errors.mjs';
import { hash } from './store.mjs';
import { validate } from './protocol.mjs';
import { SUPPORT_LIMITS } from './audience-sources.mjs';

export const INTENT_DEFAULTS = Object.freeze({ enabled: false, min_interval_ms: 1000, max_call_ms: 8000 });
export const INTENT_LIMITS = Object.freeze({ pending: 16, retained: 512, sources: 4, age_ms: 30000 });
const OPEN = new Set(['pending', 'interpreting', 'clarification']);
const READS = new Set(['game_get_state', 'game_query_inventory', 'game_get_recipe', 'game_check_action']);

// Interprets proposals only. All game writes remain in reviewed suggestions and
// the existing AUTO/preflight/lease/task path; this service cannot acquire AUTO.
export class AudienceIntents {
  constructor(manager) {
    this.manager = manager; this.store = manager.store; this.running = null; this.lastCall = -Infinity; this.deadlines = new Map();
    for (const row of this.rows()) if (['pending', 'interpreting'].includes(row.state)) this.save(row, { state: 'cancelled', reason: 'HOST_RESTART' });
    this.onState = () => this.sweep();
    manager.on('state', this.onState);
  }
  settings() { return { ...INTENT_DEFAULTS, ...this.manager.config.audience_intents }; }
  rows() { return this.store.all("SELECT value FROM objects WHERE kind='audience_intent' ORDER BY rowid").map(row => JSON.parse(row.value)); }
  get(id) { const value = this.store.object('audience_intent', id); ensure(value, 'GAME_INTENT_NOT_FOUND', 404); return value; }
  page(params = {}) {
    const state = this.manager.state.value, room = this.manager.roomId();
    if (!room || !state.world_session_id) return { items: [], next_cursor: null };
    return this.store.list('audience_intent', { ...params, world: state.world_session_id, room });
  }
  status() {
    const state = this.manager.state.value, room = this.manager.roomId();
    return { enabled: this.settings().enabled, pending_limit: INTENT_LIMITS.pending,
      model_ready: !!this.manager.bridge.host && !!this.manager.bridge.health?.().persona_injection_ready,
      running: !!this.running, pending: this.rows().filter(row => OPEN.has(row.state) && row.world_session_id === state.world_session_id && row.room_id === room).length };
  }
  save(value, patch, { publish = true } = {}) {
    const next = { ...value, ...patch, revision: value.revision + 1, updated_at: utc(this.manager.wall()) };
    validate('AudienceIntent', next); this.store.put('audience_intent', next);
    if (!['pending', 'interpreting'].includes(next.state)) this.deadlines.delete(value.audience_intent_id);
    if (publish) this.manager.publish('audience_intent', next); return next;
  }
  message(id, room) {
    const service = this.manager.bridge.room, value = service?.store?.message(id);
    return value && value.platform === 'bilibili' && value.room_id === room && value.type === 'comment' && !value.test && !value.hidden && !service.closed && !service.blocked(value) ? value : null;
  }
  sources(value) {
    const messages = value.source_event_ids.map(id => this.message(id, value.room_id));
    ensure(messages.every(Boolean), 'GAME_INTENT_SOURCE_REMOVED');
    ensure(hash(messages.map(row => [row.id || row.event_key, row.text])) === value.source_hash, 'GAME_INTENT_SOURCE_CHANGED');
    return messages;
  }
  current(value) {
    const m = this.manager, state = m.state.requireFresh();
    ensure(!m.closed && !m.faulted && !m.bridge.administration?.locked && m.config.enabled && this.settings().enabled, 'GAME_INTENT_DISABLED');
    ensure(value.room_id === m.roomId() && value.world_session_id === state.world_session_id && value.world_id === state.world_id && value.bridge_boot_id === state.bridge_boot_id, 'GAME_INTENT_CONTEXT_CHANGED');
    ensure(m.wall() < Date.parse(value.expires_at), 'GAME_INTENT_EXPIRED');
    return this.sources(value);
  }
  ingest(event) {
    const m = this.manager, state = m.state.view(), now = m.wall(), room = m.roomId();
    if (!this.settings().enabled || !m.config.enabled || m.closed || m.faulted || state.freshness !== 'fresh' || !room ||
      event.platform !== 'bilibili' || event.room_id !== room || event.type !== 'comment' || event.test || event.hidden ||
      typeof event.event_key !== 'string' || !event.event_key.length || event.event_key.length > 240 ||
      typeof event.text !== 'string' || !event.text.trim() || event.text.length > 1500 ||
      !Number.isFinite(event.occurred_at) || !Number.isFinite(event.received_at) ||
      now - event.occurred_at >= INTENT_LIMITS.age_ms || event.occurred_at > now + 2000 ||
      now - event.received_at >= INTENT_LIMITS.age_ms || event.received_at > now + 2000) return null;
    const source = this.message(event.event_key, room);
    if (!source || source.text !== event.text) return null;
    const receiptId = hash(['bilibili', room, event.event_key]);
    if (this.store.object('audience_receipt', receiptId)) return null;
    const id = 'intent-' + hash([state.world_session_id, room, event.event_key]);
    if (this.store.object('audience_intent', id)) return null;
    this.sweep(); this.prune();
    const rows = this.rows();
    if (rows.filter(value => OPEN.has(value.state)).length >= INTENT_LIMITS.pending || rows.length >= INTENT_LIMITS.retained) return null;
    const principal = typeof source.user_key === 'string' && source.user_key ? hash([room, source.user_key]) : null;
    const prior = principal && rows.findLast(value => value.state === 'clarification' && value.principal_hash === principal && value.world_session_id === state.world_session_id && value.room_id === room && value.source_event_ids.length < INTENT_LIMITS.sources);
    let ids = [event.event_key], expires = event.occurred_at + INTENT_LIMITS.age_ms;
    if (prior) { this.current(prior); ids = [...prior.source_event_ids, event.event_key]; expires = Math.min(expires, Date.parse(prior.expires_at)); }
    const messages = ids.map(key => this.message(key, room));
    const value = { audience_intent_id: id, revision: 1, room_id: room, world_id: state.world_id,
      world_session_id: state.world_session_id, bridge_boot_id: state.bridge_boot_id,
      source_event_ids: ids, source_hash: hash(messages.map(row => [row.id || row.event_key, row.text])), principal_hash: principal,
      state: 'pending', question: null, goal: null, suggestion_id: null, reason: null,
      created_at: utc(now), updated_at: utc(now), expires_at: utc(expires) };
    try { validate('AudienceIntent', value); } catch (error) { if (error instanceof GameError) return null; throw error; }
    let superseded;
    this.store.transaction(() => {
      if (prior) superseded = this.save(prior, { state: 'superseded', reason: 'FOLLOWUP_RECEIVED', question: null }, { publish: false });
      this.store.put('audience_intent', value);
      this.store.put('audience_receipt', { audience_receipt_id: receiptId, world_session_id: state.world_session_id, expires_at: now + 60000 });
      this.store.run("DELETE FROM objects WHERE kind='audience_receipt' AND (json_extract(value,'$.expires_at')<? OR rowid NOT IN (SELECT rowid FROM objects WHERE kind='audience_receipt' ORDER BY rowid DESC LIMIT 4096))", now);
    });
    if (superseded) this.manager.publish('audience_intent', superseded);
    this.manager.publish('audience_intent', value); return value;
  }
  cancel(value, reason, clear = false) {
    if (this.running?.id === value.audience_intent_id) this.running.controller.abort();
    return this.save(value, { state: 'cancelled', reason, ...(clear ? { question: null, goal: null, principal_hash: null, source_event_ids: [], source_hash: hash([]) } : {}) });
  }
  eraseSources(ids) {
    const removed = new Set(ids);
    for (const value of this.rows()) if (value.source_event_ids.some(id => removed.has(id))) this.cancel(value, 'GAME_INTENT_SOURCE_REMOVED', true);
  }
  interpretations(ids) {
    const wanted = new Set(ids), state = this.manager.state.value;
    return this.rows().filter(value => value.world_session_id === state.world_session_id && value.room_id === this.manager.roomId() &&
      ['clarification', 'proposed'].includes(value.state) && value.source_event_ids.some(id => wanted.has(id)))
      .slice(-4).map(({ audience_intent_id, state, question, goal, suggestion_id }) => ({ audience_intent_id, state, question, goal, suggestion_id }));
  }
  waiting(ids) {
    if (!this.settings().enabled || !this.manager.bridge.host || !this.manager.bridge.health?.().persona_injection_ready) return false;
    const wanted = new Set(ids);
    return this.rows().some(value => ['pending', 'interpreting'].includes(value.state) && value.source_event_ids.some(id => wanted.has(id)) && this.manager.wall() < Date.parse(value.expires_at));
  }
  sweep() {
    if (this.manager.closed || this.manager.faulted) { this.running?.controller.abort(); return; }
    for (const value of this.rows()) {
      // Purge derived text and account linkage even for already completed intent
      // records, when a source is filtered/withdrawn/deleted.
      if (value.source_event_ids.length) {
        try { this.sources(value); }
        catch { this.cancel(value, 'GAME_INTENT_SOURCE_REMOVED', true); continue; }
      }
      if (!OPEN.has(value.state)) continue;
      try { this.current(value); }
      catch (error) {
        if (this.running?.id === value.audience_intent_id) this.running.controller.abort();
        this.save(value, { state: error.code === 'GAME_INTENT_EXPIRED' ? 'expired' : 'cancelled', reason: error.code || 'GAME_INTENT_CONTEXT_CHANGED' });
        continue;
      }
      if (['pending', 'interpreting'].includes(value.state) &&
          (this.deadlines.get(value.audience_intent_id) ?? Infinity) <= this.manager.clock()) {
        if (this.running?.id === value.audience_intent_id) this.running.controller.abort();
        this.save(value, { state: 'cancelled', reason: 'GAME_INTENT_CANCELLED' });
      }
    }
  }
  prune() {
    const terminal = this.rows().filter(value => !OPEN.has(value.state));
    const all = this.rows().length;
    for (let index = 0; index < terminal.length; index++) {
      const value = terminal[index];
      if (Date.parse(value.updated_at) > this.manager.wall() - 86400000 && index >= Math.max(0, all - INTENT_LIMITS.retained + 1)) continue;
      this.store.run("DELETE FROM objects WHERE kind='audience_intent' AND id=?", value.audience_intent_id);
    }
  }
  async tick() {
    const m = this.manager, host = m.bridge.host;
    this.sweep();
    if (this.running || !this.settings().enabled || !host || m.bridge.administration?.locked ||
      !m.bridge.health?.().persona_injection_ready || m.clock() - this.lastCall < this.settings().min_interval_ms) return;
    const value = this.rows().find(row => row.state === 'pending'); if (!value) return;
    const deadline = this.deadlines.get(value.audience_intent_id) ?? m.clock() + this.settings().max_call_ms;
    const remaining = deadline - m.clock();
    if (remaining <= 0) { this.save(value, { state: 'cancelled', reason: 'GAME_INTENT_CANCELLED' }); return; }
    this.deadlines.set(value.audience_intent_id, deadline);
    const controller = new AbortController(); this.running = { id: value.audience_intent_id, controller }; this.lastCall = m.clock();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(Math.ceil(Math.min(remaining, this.settings().max_call_ms)))]);
    try {
      const sources = this.current(value), state = m.state.view();
      this.save(value, { state: 'interpreting', reason: null });
      let result = null;
      await host.generate({ sessionId: 'mc-intent-' + randomUUID(), snapshot: m.bridge.channel.snapshot(), purpose: 'audience_intent', signal, maxTokens: 512,
        input: '识别观众是否在建议Minecraft动作；普通聊天或问题提交none。缺少物品种类、数量、坐标或基地存在歧义时提交clarify并提出一个简短中文问题，不能自行补默认数量或物品种类。明确时提交goal；count表示额外采集或新增产物数量。只能通过stream_audience_intent_result提交一次严格JSON：{kind:"goal"|"clarify"|"none",goal:Goal或null,question:字符串或null}。goal必须是既有五种固定高层目标。回基地只能引用当前登记基地，不猜坐标。识别结果只供审核，不表示执行。',
        context: canonical({ sources: sources.map(row => ({ event_id: row.id || row.event_key, text: row.text })),
          game: { world_id: state.world_id, world_session_id: state.world_session_id, player: state.player, inventory: state.inventory?.slice(0, 64),
            inventory_truncated: state.inventory?.length > 64, unknown_fields: state.unknown_fields, active_base: m.worlds.summary().active_base }, capabilities: m.capabilities }),
        toolCatalogue: m.tools.catalogue('speech').filter(tool => READS.has(tool.name)),
        tools: async (name, args, execution) => {
          const toolSignal = execution?.signal ? AbortSignal.any([signal, execution.signal]) : signal;
          ensure(!toolSignal.aborted, 'GAME_INTENT_CANCELLED'); this.current(this.get(value.audience_intent_id));
          if (name === 'stream_audience_intent_result') {
            ensure(!result, 'GAME_INTENT_DUPLICATE_RESULT'); validate('AudienceIntentResult', args); result = structuredClone(args); return { received: true };
          }
          ensure(READS.has(name), 'GAME_TOOL_PERMISSION');
          return m.tools.invoke(name, args, { purpose: 'audience_intent', worldSessionId: value.world_session_id, signal: toolSignal });
        }, onCall: m.bridge.onCall?.({ maxTokens: 512 }) });
      ensure(!signal.aborted, 'GAME_INTENT_CANCELLED');
      let current = this.get(value.audience_intent_id); ensure(current.state === 'interpreting', 'GAME_INTENT_CANCELLED'); this.current(current);
      ensure(result, 'GAME_INTENT_RESULT_MISSING');
      if (result.kind === 'goal') {
        let suggestion, next;
        this.store.transaction(() => {
          suggestion = this.propose(current, result.goal, false);
          next = this.save(current, { state: 'proposed', goal: result.goal, suggestion_id: suggestion.suggestion_id }, { publish: false });
        });
        m.publish('suggestion', suggestion); m.publish('audience_intent', next);
      } else this.save(current, { state: result.kind === 'clarify' ? 'clarification' : 'ignored', question: result.question });
    } catch (error) {
      if (!m.closed && !m.faulted) {
        let current = this.get(value.audience_intent_id);
        const yielded = ['MODEL_PREEMPTED', 'MODEL_QUEUE_FULL'].includes(error.code);
        if (current.state === 'interpreting' && yielded && !signal.aborted && m.clock() < deadline) {
          // Recheck withdrawal, world, privacy and original lifetime before
          // retaining a proposal. A retry keeps the first call's time budget.
          this.sweep(); current = this.get(value.audience_intent_id);
          if (current.state === 'interpreting') {
            this.current(current); this.save(current, { state: 'pending', reason: error.code }); return;
          }
        }
        const cancelled = signal.aborted || ['MODEL_CANCELLED', 'GAME_INTENT_CANCELLED',
          'GAME_INTENT_SUPERSEDED_BY_SPEECH', 'GAME_QUERY_CANCELLED'].includes(error.code || error.message);
        if (current.state === 'interpreting') this.save(current, { state: cancelled ? 'cancelled' : 'failed',
          reason: cancelled ? 'GAME_INTENT_CANCELLED' : error instanceof GameError ? error.code : 'GAME_INTENT_MODEL_FAILED' });
        if (error?.code === 'GAME_STORE_OWNER_LOST' || Number.isInteger(error?.errcode)) m.storageFault(error, 'audience_intent');
      }
    } finally { if (this.running?.id === value.audience_intent_id) this.running = null; }
  }
  propose(value, goal, publish = true) {
    this.current(value); validate('Goal', goal);
    ensure(this.manager.suggestions.pending().length < 64, 'GAME_AUDIENCE_BUSY');
    const service = this.manager.suggestions;
    ensure(this.manager.audienceSources.total() + value.source_event_ids.length <= SUPPORT_LIMITS.total, 'GAME_AUDIENCE_BUSY');
    return service.create(goal, value.source_event_ids, { origin: { kind: 'audience', platform: 'bilibili', room_id: value.room_id, vote_id: null },
      supportCount: value.source_event_ids.length, publish });
  }
  decision(id, request) {
    validate('AudienceIntentDecision', request);
    const scope = 'audience-intent:' + id, replay = this.store.replay(scope, request); if (replay) return replay;
    const value = this.get(id); ensure(value.revision === request.expected_revision, 'GAME_INTENT_CONFLICT');
    ensure(OPEN.has(value.state), 'GAME_INTENT_CLOSED'); this.current(value);
    let result, suggestion;
    this.store.transaction(() => {
      if (request.action === 'resolve') {
        suggestion = this.propose(value, request.goal, false);
        result = this.save(value, { state: 'proposed', goal: request.goal, question: null, suggestion_id: suggestion.suggestion_id, reason: 'OPERATOR_RESOLVED' }, { publish: false });
      } else result = this.save(value, { state: 'cancelled', question: null, reason: 'OPERATOR_DISMISSED' }, { publish: false });
      this.store.remember(scope, request, 'audience_intent', result);
    });
    if (suggestion) this.manager.publish('suggestion', suggestion);
    this.manager.publish('audience_intent', result);
    if (this.running?.id === id) this.running.controller.abort();
    return result;
  }
  close() { this.running?.controller.abort(); this.deadlines.clear(); this.manager.off('state', this.onState); }
}
