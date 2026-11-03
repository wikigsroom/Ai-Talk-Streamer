import { randomUUID } from 'node:crypto';
import { validate } from './protocol.mjs';
import { ensure, GameError, utc } from './errors.mjs';
import { canonical } from '../dsh-bridge/channel.mjs';
import { hash } from './store.mjs';

const ITEM = '[a-z0-9_.-]+:[a-z0-9_./-]+';
const LIVE = new Set(['proposed', 'accepted']);
export const AUDIENCE_HINT = '建议 采集 minecraft:oak_log 4；建议 合成 minecraft:oak_planks 4；建议 进食 minecraft:apple；建议 回基地';

// Unknown chat stays chat. Text is never evaluated or treated as tool permission.
export function audienceGoal(text, activeBase) {
  let match = text.match(new RegExp('^建议\\s+(采集|合成)\\s+(' + ITEM + ')\\s+([1-9][0-9]{0,3})$', 'u'));
  if (match) return { skill: match[1] === '采集' ? 'gather' : 'craft', item_id: match[2], count: Number(match[3]) };
  match = text.match(new RegExp('^建议\\s+进食\\s+(' + ITEM + ')$', 'u'));
  if (match) return { skill: 'use_item', item_id: match[1], purpose: 'eat' };
  if (text === '建议 回基地' && activeBase) return { skill: 'return_base', base_id: activeBase.base_id };
  return null;
}

export class SuggestionService {
  constructor(manager) { this.manager = manager; this.store = manager.store; this.dispatching = new Map(); }
  page(params = {}) {
    const world = this.manager.state.value.world_session_id, room = this.manager.roomId();
    if (!world || !room) return { items: [], next_cursor: null };
    const page = this.store.list('suggestion', { ...params, world, room });
    return { ...page, items: page.items.map(value => this.manager.audienceSources.refresh(value)) };
  }
  pending(limit = 64) {
    const world = this.manager.state.value.world_session_id, room = this.manager.roomId();
    if (!world || !room) return [];
    return this.store.all("SELECT value FROM objects WHERE kind='suggestion' AND world_session_id=? AND json_extract(value,'$.origin.room_id')=? AND json_extract(value,'$.state') IN ('proposed','accepted') AND json_extract(value,'$.expires_at')>? ORDER BY rowid DESC LIMIT ?",
      world, room, utc(this.manager.wall()), limit).map(row => JSON.parse(row.value));
  }
  create(goal, sourceIds, { ttlMs = 120000, origin, publish = true, supportCount = 1 } = {}) {
    validate('Goal', goal); const state = this.manager.state.requireFresh();
    ensure(Number.isInteger(ttlMs) && ttlMs >= 1000 && ttlMs <= 120000, 'GAME_REQUEST_INVALID', 400);
    const value = { suggestion_id: 'suggestion-' + randomUUID(), world_id: state.world_id,
      world_session_id: state.world_session_id, revision: 1, source_event_ids: [...new Set(sourceIds)], goal,
      state: 'proposed', task_id: null, reason: null, created_at: utc(this.manager.wall()), expires_at: utc(this.manager.wall() + ttlMs),
      ...(origin ? { origin, support_count: supportCount } : {}) };
    validate('Suggestion', value); this.store.put('suggestion', value);
    const result = this.manager.audienceSources.refresh(value, { publish: false, bump: false });
    if (publish) this.manager.publish('suggestion', result); return result;
  }
  ingest(event) {
    const now = this.manager.wall(), state = this.manager.state.view(), room = this.manager.roomId();
    if (!room || event.platform !== 'bilibili' || event.room_id !== room || event.type !== 'comment' || event.hidden || event.test ||
        typeof event.event_key !== 'string' || !event.event_key.length || event.event_key.length > 240 ||
        typeof event.text !== 'string' || event.text.length > 1500 || !Number.isFinite(event.occurred_at) || !Number.isFinite(event.received_at) ||
        now - event.occurred_at > 30000 || event.occurred_at > now + 2000 || now - event.received_at > 30000 || event.received_at > now + 2000 ||
        state.freshness !== 'fresh') return null;
    const goal = audienceGoal(event.text.trim(), this.manager.worlds.summary().active_base);
    if (!goal) return null;
    try { validate('Goal', goal); } catch (error) { if (error instanceof GameError) return null; throw error; }
    const receiptId = hash(['bilibili', room, event.event_key]);
    if (this.store.object('audience_receipt', receiptId)) return null;
    const candidates = this.pending();
    const previous = candidates.find(value => value.state === 'proposed' && value.origin.kind === 'audience' && canonical(value.goal) === canonical(goal));
    if (!previous && candidates.length >= 64) return null;
    if (!this.manager.audienceSources.canAdd(previous, event.event_key)) return null;
    let value;
    this.store.transaction(() => {
      if (previous) {
        value = { ...previous, revision: previous.revision + 1, support_count: Math.min(1000000, (previous.support_count || 1) + 1),
          source_event_ids: [...previous.source_event_ids.filter(id => id !== event.event_key), event.event_key].slice(-32) };
        this.manager.audienceSources.record(value, event.event_key);
        value = this.manager.audienceSources.refresh(value, { publish: false, bump: false });
        validate('Suggestion', value); this.store.put('suggestion', value);
      } else value = this.create(goal, [event.event_key], { publish: false, origin: { kind: 'audience', platform: 'bilibili', room_id: room, vote_id: null } });
      this.store.put('audience_receipt', { audience_receipt_id: receiptId, world_session_id: state.world_session_id, expires_at: now + 60000 });
      // This exceeds the admissible event age; pruned replays still fail the time gate.
      this.store.run("DELETE FROM objects WHERE kind='audience_receipt' AND (json_extract(value,'$.expires_at')<? OR rowid NOT IN (SELECT rowid FROM objects WHERE kind='audience_receipt' ORDER BY rowid DESC LIMIT 4096))", now);
    });
    this.manager.publish('suggestion', value); return value;
  }
  get(id) { const value = this.store.object('suggestion', id); ensure(value, 'GAME_SUGGESTION_NOT_FOUND', 404); return this.manager.audienceSources.refresh(value); }
  withdrawSources(ids) {
    this.manager.intents?.eraseSources(ids);
    if (ids.length) this.reconcileSources();
  }
  reconcileSources() {
    for (const value of this.pending()) {
      const current = this.manager.audienceSources.refresh(value);
      if (current.origin && !this.sourceAvailable(current)) this.withdraw(current);
    }
  }
  withdraw(value) {
    if (!LIVE.has(value.state)) return null;
    const next = { ...value, state: 'cancelled', reason: 'PLATFORM_SOURCE_REMOVED', revision: value.revision + 1 };
    this.store.put('suggestion', next); this.manager.publish('suggestion', next); return next;
  }
  sourceAvailable(value) {
    if (!value.origin || value.origin.room_id !== this.manager.roomId()) return false;
    if (value.origin.kind === 'vote') {
      const vote = this.manager.votes.get(value.origin.vote_id);
      return vote.state === 'closed' && vote.suggestion_id === value.suggestion_id && vote.world_session_id === value.world_session_id &&
        vote.options.some(option => option.option_id === vote.winning_option_id && canonical(option.goal) === canonical(value.goal));
    }
    return this.manager.audienceSources.support(value).visible_events > 0;
  }
  decision(id, request) {
    validate('SuggestionDecision', request);
    const scope = 'suggestion-decision:' + id, replay = this.store.replay(scope, request); if (replay) return replay;
    const value = this.get(id); ensure(value.revision === request.expected_revision, 'GAME_SUGGESTION_CONFLICT');
    ensure(LIVE.has(value.state), 'GAME_SUGGESTION_CLOSED');
    ensure(this.manager.wall() < Date.parse(value.expires_at), 'GAME_SUGGESTION_EXPIRED');
    ensure(value.world_session_id === this.manager.state.value.world_session_id, 'GAME_WORLD_CHANGED');
    if (request.action === 'accept' && value.origin) ensure(this.sourceAvailable(value), 'GAME_SUGGESTION_SOURCE_UNAVAILABLE');
    const next = { ...value, revision: value.revision + 1,
      state: { accept: 'accepted', reject: 'rejected', cancel: 'cancelled' }[request.action], reason: request.reason };
    this.store.transaction(() => this.store.remember(scope, request, 'suggestion', next));
    this.manager.publish('suggestion', next); return next;
  }
  reference(id, revision, goal) {
    const value = this.get(id);
    ensure(value.revision === revision, 'GAME_SUGGESTION_CONFLICT');
    ensure(value.state === 'accepted', 'GAME_SUGGESTION_NOT_ACCEPTED');
    ensure(this.manager.wall() < Date.parse(value.expires_at), 'GAME_SUGGESTION_EXPIRED');
    ensure(value.world_session_id === this.manager.state.value.world_session_id, 'GAME_WORLD_CHANGED');
    ensure(this.sourceAvailable(value), 'GAME_SUGGESTION_SOURCE_UNAVAILABLE');
    ensure(canonical(goal) === canonical(value.goal), 'GAME_SUGGESTION_GOAL_CHANGED');
    return { suggestion_id: id, expected_revision: revision };
  }
  linkTask(reference, task) {
    this.reference(reference.suggestion_id, reference.expected_revision, task.goal);
    const value = this.get(reference.suggestion_id), next = { ...value, state: 'converted', task_id: task.task_id, revision: value.revision + 1 };
    this.store.put('suggestion', next);
    if (value.origin?.kind === 'vote') {
      const vote = this.manager.votes.get(value.origin.vote_id);
      this.store.put('vote', { ...vote, task_id: task.task_id, revision: vote.revision + 1 });
    }
  }
  publishTask(taskId) {
    for (const row of this.store.all("SELECT value FROM objects WHERE kind='suggestion' AND json_extract(value,'$.task_id')=?", taskId)) {
      const value = JSON.parse(row.value); this.manager.publish('suggestion', value);
      if (value.origin?.kind === 'vote') this.manager.publish('vote', this.manager.votes.get(value.origin.vote_id));
    }
  }
  dispatch(id, request) {
    validate('SuggestionDispatch', request); this.manager.requireEnabled();
    const scope = 'suggestion-dispatch:' + id, replay = this.store.replay(scope, request); if (replay) return replay;
    ensure(this.dispatching.size === 0, 'GAME_AUDIENCE_BUSY');
    const value = this.get(id); this.reference(id, request.expected_revision, value.goal);
    this.manager.readyForAction({ ...request, based_on_seq: this.manager.state.value.seq });
    ensure(!this.manager.tasks.active(), 'GAME_TASK_BUSY');
    const operation = this.manager.newOperation('audience', request, { scope }), controller = new AbortController();
    this.dispatching.set(operation.operation_id, controller);
    void this.runDispatch(value, request, operation, controller).catch(() => { if (!this.manager.closed) this.manager.storageFault(); }); return operation;
  }
  async runDispatch(value, request, operation, controller) {
    const m = this.manager, signal = AbortSignal.any([controller.signal, AbortSignal.timeout(7000)]);
    const changed = () => {
      const state = m.state.view();
      if (state.freshness !== 'fresh' || state.mode !== 'AUTO' || state.world_session_id !== request.world_session_id ||
          state.bridge_boot_id !== request.bridge_boot_id || state.control_epoch !== request.expected_control_epoch) controller.abort();
    };
    m.on('state', changed);
    try {
      const checked = await m.tools.query('check_action', { goal: value.goal }, { signal });
      ensure(!signal.aborted && !m.closed, 'GAME_QUERY_CANCELLED');
      ensure(checked.result?.allowed === true, 'GAME_PRECONDITION_FAILED');
      const state = m.checkContext(request);
      this.reference(value.suggestion_id, request.expected_revision, value.goal);
      const result = m.tasks.start({ request_id: 'audience-' + hash([value.suggestion_id, request.request_id]),
        bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id, expected_control_epoch: request.expected_control_epoch,
        based_on_seq: state.seq, accept_within_ms: m.config.control.accept_within_ms, max_duration_ms: m.config.control.max_task_duration_ms,
        goal: value.goal, ...(value.goal.skill === 'return_base' ? { base_ref: m.worlds.baseReference(checked.result.base_target) } : {}),
        suggestion_ref: { suggestion_id: value.suggestion_id, expected_revision: request.expected_revision } });
      m.finishOperation(operation, { suggestion_id: value.suggestion_id, task_id: result.value.task_id, submission: 'accepted_locally', effect_status: 'unknown' });
    } catch (error) {
      if (!m.closed) {
        const taskId = this.get(value.suggestion_id).task_id;
        m.finishOperation(operation, taskId ? { suggestion_id: value.suggestion_id, task_id: taskId, submission: 'dispatch_unknown', effect_status: 'unknown' } : null,
          error instanceof GameError ? error.code : 'GAME_STORAGE_ERROR');
        if (!(error instanceof GameError) || error.code === 'GAME_STORE_OWNER_LOST') m.storageFault();
      }
    } finally { m.off('state', changed); this.dispatching.delete(operation.operation_id); }
  }
  summary() {
    const suggestions = this.pending(16).map(value => this.manager.audienceSources.refresh(value)), world = this.manager.state.value.world_session_id, room = this.manager.roomId();
    const linked = world && room ? this.store.all("SELECT value FROM objects WHERE kind='suggestion' AND world_session_id=? AND json_extract(value,'$.origin.room_id')=? AND json_extract(value,'$.task_id') IS NOT NULL ORDER BY rowid DESC LIMIT 16", world, room).map(row => JSON.parse(row.value)) : [];
    const feedback = linked.map(value => {
      const task = this.manager.tasks.get(value.task_id), speech = this.manager.narration?.taskFeedback(task.task_id);
      return { suggestion_id: value.suggestion_id, task_id: task.task_id, vote_id: value.origin?.vote_id || null,
        state: task.state, effect_status: task.effect_status, task_version: task.version,
        recovery_status: task.recovery?.status || null, disposition_status: task.disposition?.status || null, reason: task.reason,
        evidence: task.evidence.slice(-8), updated_at: task.updated_at, speech_status: speech?.state || 'not_scheduled',
        narration_id: speech?.narration_id || null, speech_request_id: speech?.request_id || null, speech_reason: speech?.reason || null,
        speech_completion_event_seq: speech?.completion_event_seq || null };
    });
    return { platform: 'bilibili', room_id: this.manager.roomId(), server_time: utc(this.manager.wall()), suggestions, votes: this.manager.votes.page({ limit: 3 }).items,
      feedback, pending_limit: 64, command_hint: AUDIENCE_HINT, support_budget: this.manager.audienceSources.budget(), natural_language: this.manager.intents?.status() || { enabled: false, model_ready: false, pending_limit: 16, running: false, pending: 0 } };
  }
  expire(worldChanged = false) {
    for (const row of this.store.all("SELECT value FROM objects WHERE kind='suggestion' AND json_extract(value,'$.state') IN ('proposed','accepted')")) {
      const value = JSON.parse(row.value);
      if (LIVE.has(value.state) && (worldChanged || this.manager.wall() >= Date.parse(value.expires_at) || value.origin && value.origin.room_id !== this.manager.roomId())) {
        value.state = 'expired'; value.revision++; value.reason = worldChanged ? 'WORLD_CHANGED' : value.origin && value.origin.room_id !== this.manager.roomId() ? 'ROOM_CHANGED' : 'EXPIRED';
        this.store.put('suggestion', value); this.manager.publish('suggestion', value);
      }
    }
  }
  close() { for (const controller of this.dispatching.values()) controller.abort(); }
}
