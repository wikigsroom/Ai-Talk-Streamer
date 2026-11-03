import { randomUUID } from 'node:crypto';
import { validate } from './protocol.mjs';
import { canonical } from '../dsh-bridge/channel.mjs';
import { ensure, utc } from './errors.mjs';
import { hash } from './store.mjs';

export const TERMINAL = new Set(['succeeded', 'failed', 'cancelled']);
export class TaskService {
  constructor(manager) { this.manager = manager; this.store = manager.store; this.repairLegacyProjections(); }
  raw(id) { const value = this.store.object('task', id); ensure(value, 'GAME_TASK_NOT_FOUND', 404); return value; }
  recovery(id) { const row = this.store.get('SELECT value FROM task_recovery WHERE task_id=?', id); return row ? JSON.parse(row.value) : null; }
  disposition(id) { const row = this.store.get('SELECT value FROM task_dispositions WHERE task_id=?', id); return row ? JSON.parse(row.value) : null; }
  get(id) { const value = this.raw(id), recovery = this.recovery(id), disposition = this.disposition(id);
    return { ...value, ...(recovery ? { recovery } : {}), ...(disposition ? { disposition } : {}) }; }
  page(params = {}) {
    if (params.worldId !== undefined) {
      ensure(typeof params.worldId === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(params.worldId), 'GAME_REQUEST_INVALID', 400);
      this.manager.worlds.get(params.worldId);
    }
    const page = this.store.list('task', params); return { ...page, items: page.items.map(task => this.get(task.task_id)) };
  }
  setRecovery(id, status, reason, extra = {}) {
    const now = utc(this.manager.wall()), old = this.recovery(id);
    const value = { task_id: id, revision: (old?.revision || 0) + 1, status, reason: reason || old?.reason || 'LEDGER_RECONCILIATION', created_at: old?.created_at || now,
      updated_at: now, attempts: old?.attempts || 0, checked_bridge_boot_id: old?.checked_bridge_boot_id || null,
      confirmed_version: old?.confirmed_version || null, last_error: null, ...extra };
    validate('TaskRecovery', value);
    this.store.run('INSERT INTO task_recovery VALUES(?,?,?) ON CONFLICT(task_id) DO UPDATE SET status=excluded.status,value=excluded.value', id, status, canonical(value));
    return value;
  }
  repairLegacyProjections() {
    for (const row of this.store.all("SELECT value FROM objects WHERE kind='task'")) {
      const task = JSON.parse(row.value);
      if (task.state !== 'failed' || task.effect_status !== 'unknown' || !['INTERRUPTED_HOST_RESTART', 'WORLD_CHANGED'].includes(task.reason)) continue;
      const confirmed = this.store.get('SELECT value FROM task_transitions WHERE task_id=? ORDER BY transition_seq DESC LIMIT 1', task.task_id);
      const authoritative = confirmed ? JSON.parse(confirmed.value) : { ...task, state: 'accepted', version: 1,
        reason: null, effect_status: 'unknown', evidence: [], updated_at: task.created_at };
      if (TERMINAL.has(authoritative.state)) continue;
      this.store.transaction(() => {
        this.store.audit('repair_legacy_host_projection', { previous: task, authoritative });
        this.store.put('task', authoritative); this.setRecovery(task.task_id, 'required', 'LEGACY_HOST_PROJECTION');
      });
    }
  }
  active() {
    return this.store.all("SELECT value FROM objects WHERE kind='task'").map(r => JSON.parse(r.value))
      .find(t => !TERMINAL.has(t.state) && this.disposition(t.task_id)?.status !== 'closed_unknown') || null;
  }
  start(request) {
    validate('TaskCreate', request);
    const identity = this.manager.state.value;
    const scope = `${identity.game_instance_id ?? this.store.meta('bound_instance', null)}:${request.world_session_id}:task`;
    const replay = this.store.replay(scope, request); if (replay) return { value: this.get(replay.task_id), duplicate: true };
    const state = this.manager.readyForAction(request);
    ensure(!this.active(), 'GAME_TASK_BUSY');
    ensure(this.manager.capabilities.skills.includes(request.goal.skill), 'GAME_CAPABILITY_UNAVAILABLE', 503);
    ensure(this.manager.config.control.enabled_skills.includes(request.goal.skill), 'GAME_SKILL_DISABLED');
    if (request.goal.skill === 'use_item') {
      ensure(this.manager.capabilities.item_uses.includes(request.goal.purpose), 'GAME_CAPABILITY_UNAVAILABLE', 503);
      if (request.goal.target) {
        const feature = request.goal.item_id==='minecraft:dirt' ? 'targeted_terrain_placement'
          : ['minecraft:crafting_table','minecraft:furnace'].includes(request.goal.item_id) ? 'targeted_block_placement' : 'targeted_planting';
        ensure(this.manager.capabilities.features[feature] === true, 'GAME_CAPABILITY_UNAVAILABLE', 503);
        ensure(request.goal.target.dimension === state.player?.position?.dimension, 'GAME_PRECONDITION_FAILED');
      }
    }
    if (request.goal.skill === 'navigate') ensure(request.goal.target.dimension === state.player?.position?.dimension, 'GAME_PRECONDITION_FAILED');
    const baseTarget = this.manager.worlds.resolveBase(request.goal, request.base_ref, state);
    const task = { task_id: 'task-' + randomUUID(), game_instance_id: state.game_instance_id,
      bridge_boot_id: state.bridge_boot_id, world_id: state.world_id, world_session_id: state.world_session_id,
      request_id: request.request_id, control_epoch: state.control_epoch, version: 1, goal: request.goal,
      state: 'accepted', created_at: utc(this.manager.wall()), updated_at: utc(this.manager.wall()),
      reason: null, effect_status: 'unknown', evidence: [], ...(baseTarget ? { base_target: baseTarget } : {}) };
    validate('Task', task);
    this.store.transaction(() => {
      this.store.remember(scope, request, 'task', task);
      if (request.world_goal_ref) this.manager.continuity.linkTask(request.world_goal_ref, task);
      if (request.suggestion_ref) this.manager.suggestions.linkTask(request.suggestion_ref, task);
    });
    // Persist the idempotency record before dispatch. A failed send is unknown,
    // never permission to invent a new request or replay a side effect.
    try { this.manager.send('task_start', { controller_session_id: this.manager.controllerId,
      lease_id: this.manager.lease.id, control_epoch: state.control_epoch, task_id: task.task_id, request,
      ...(baseTarget ? { base_target: baseTarget } : {}) }); }
    catch (error) { this.manager.disconnect('task_dispatch_failed'); throw error; }
    this.manager.publish('task', task); this.manager.continuity.publishTaskGoal(task.task_id); this.manager.suggestions.publishTask(task.task_id);
    return { value: task, duplicate: false };
  }
  update(payload, { publish = true } = {}) {
    const task = payload.task, previous = this.raw(task.task_id);
    ensure(!Object.hasOwn(task, 'recovery') && !Object.hasOwn(task, 'disposition'), 'GAME_TASK_SOURCE_INVALID');
    for (const key of ['game_instance_id', 'bridge_boot_id', 'world_id', 'world_session_id', 'request_id', 'control_epoch'])
      ensure(task[key] === previous[key], 'GAME_TASK_CONTEXT_CHANGED');
    ensure(canonical(task.goal) === canonical(previous.goal), 'GAME_TASK_GOAL_CHANGED');
    ensure(canonical(task.base_target ?? null) === canonical(previous.base_target ?? null), 'GAME_TASK_BASE_CHANGED');
    ensure(payload.transition_seq === task.version, 'GAME_TASK_VERSION_INVALID', 400);
    if (task.version <= previous.version) {
      if (task.version === previous.version) {
        const confirmed = this.store.get('SELECT value FROM task_transitions WHERE task_id=? AND transition_seq=?', task.task_id, task.version);
        if (!confirmed && previous.state === 'accepted' && task.state === 'accepted' && task.version === 1) {
          this.store.run('INSERT INTO task_transitions VALUES(?,?,?)', task.task_id, task.version, canonical(task));
          this.store.put('task', task); this.reopenRecord(task); if (publish) this.manager.publish('task', task); return task;
        }
        ensure(canonical(task) === canonical(previous), 'GAME_TASK_VERSION_CONFLICT');
      }
      this.reopenRecord(previous); return previous;
    }
    ensure(!TERMINAL.has(previous.state), 'GAME_TASK_TERMINAL');
    ensure(task.version === previous.version + 1, 'GAME_TASK_TRANSITION_GAP');
    ensure(task.evidence.every(e => e.world_session_id === task.world_session_id), 'GAME_TASK_EVIDENCE_WORLD');
    this.store.run('INSERT OR IGNORE INTO task_transitions VALUES(?,?,?)', task.task_id, payload.transition_seq, canonical(task));
    this.store.put('task', task);
    this.reopenRecord(task); this.manager.continuity?.applyTask(task);
    if (TERMINAL.has(task.state) && this.recovery(task.task_id)) this.setRecovery(task.task_id, 'verified', null, {
      confirmed_version: task.version, checked_bridge_boot_id: this.manager.state.identity?.bridge_boot_id || null });
    if (publish) { this.manager.publish('task', task); if (TERMINAL.has(task.state)) this.manager.finishCancellations(task); }
    return task;
  }
  interrupted(reason) {
    for (const row of this.store.all("SELECT value FROM objects WHERE kind='task'")) {
      const task = JSON.parse(row.value); if (TERMINAL.has(task.state) || this.disposition(task.task_id)?.status === 'closed_unknown') continue;
      const old = this.recovery(task.task_id);
      this.setRecovery(task.task_id, ['conflict', 'missing'].includes(old?.status) ? old.status : 'required', reason,
        { last_error: old?.last_error || null, ...(reason === 'INTERRUPTED_HOST_RESTART' ? { attempts: 0 } : {}) });
      this.manager.publish('task', this.get(task.task_id));
    }
  }
  candidates() {
    return this.store.all("SELECT task_id,value FROM task_recovery WHERE status IN ('required','waiting_terminal') ORDER BY rowid")
      .filter(row => JSON.parse(row.value).attempts < 3 && !TERMINAL.has(this.raw(row.task_id).state)).slice(0, 1).map(row => row.task_id);
  }
  querying(ids) {
    for (const id of ids) this.setRecovery(id, 'querying', null, { attempts: (this.recovery(id)?.attempts || 0) + 1 });
  }
  queryFailed(ids, error) {
    for (const id of ids) if (!TERMINAL.has(this.raw(id).state) && !['conflict', 'missing'].includes(this.recovery(id)?.status))
      this.setRecovery(id, 'required', null, { last_error: error });
  }
  reconcile(result, requested) {
    validate('TaskLedgerResult', result);
    ensure(result.game_instance_id === this.manager.state.identity.game_instance_id && result.entries.length === requested.length &&
      result.entries.every((entry, i) => entry.task_id === requested[i]), 'GAME_LEDGER_CONTEXT');
    for (const entry of result.entries) {
      const previous = this.raw(entry.task_id);
      if (entry.status === 'missing') {
        this.setRecovery(entry.task_id, 'missing', null, { last_error: 'GAME_LEDGER_TASK_MISSING', checked_bridge_boot_id: this.manager.state.identity.bridge_boot_id });
        this.manager.publish('task', this.get(entry.task_id)); continue;
      }
      const task = entry.task;
      try {
        ensure(!Object.hasOwn(task, 'recovery') && !Object.hasOwn(task, 'disposition') && task.task_id === previous.task_id, 'GAME_TASK_SOURCE_INVALID');
        for (const key of ['game_instance_id', 'bridge_boot_id', 'world_id', 'world_session_id', 'request_id', 'control_epoch'])
          ensure(task[key] === previous[key], 'GAME_TASK_CONTEXT_CHANGED');
        ensure(canonical(task.goal) === canonical(previous.goal), 'GAME_TASK_GOAL_CHANGED');
        ensure(canonical(task.base_target ?? null) === canonical(previous.base_target ?? null), 'GAME_TASK_BASE_CHANGED');
        if (task.version < previous.version) {
          ensure(TERMINAL.has(previous.state), 'GAME_LEDGER_VERSION_REGRESSION'); continue;
        }
        const known = this.store.get('SELECT value FROM task_transitions WHERE task_id=? AND transition_seq=?', task.task_id, task.version);
        ensure(!known || known.value === canonical(task), 'GAME_TASK_VERSION_CONFLICT');
        if (TERMINAL.has(previous.state)) ensure(canonical(task) === canonical(previous), 'GAME_TASK_TERMINAL');
        ensure(task.evidence.every(e => e.world_session_id === task.world_session_id), 'GAME_TASK_EVIDENCE_WORLD');
        this.store.transaction(() => {
          this.store.run('INSERT OR IGNORE INTO task_transitions VALUES(?,?,?)', task.task_id, task.version, canonical(task));
          this.store.put('task', task);
          this.manager.continuity?.applyTask(task);
          this.setRecovery(task.task_id, TERMINAL.has(task.state) ? 'verified' : 'waiting_terminal', null, {
            confirmed_version: task.version, checked_bridge_boot_id: this.manager.state.identity.bridge_boot_id });
          this.reopenRecord(task);
          this.store.audit('bridge_ledger_reconciled', { task_id: task.task_id, from_version: previous.version,
            to_version: task.version, bridge_boot_id: this.manager.state.identity.bridge_boot_id });
        });
        this.enforceReopened(task.task_id); this.manager.continuity?.publishTaskGoal(task.task_id);
        this.manager.publish('task', this.get(task.task_id)); if (TERMINAL.has(task.state)) this.manager.finishCancellations(task);
      } catch (error) {
        this.setRecovery(entry.task_id, 'conflict', null, { last_error: error.code || 'GAME_LEDGER_CONFLICT',
          checked_bridge_boot_id: this.manager.state.identity.bridge_boot_id }); throw error;
      }
    }
  }
  closeUnknown(id, request) {
    validate('TaskDispositionRequest', request); const scope = 'task-disposition:' + id;
    const replay = this.store.get('SELECT * FROM idempotency WHERE scope=? AND request_id=?', scope, request.request_id);
    if (replay) { ensure(replay.body_hash === hash(request), 'GAME_IDEMPOTENCY_CONFLICT'); return this.get(id); }
    const task = this.raw(id), recovery = this.recovery(id), state = this.manager.checkContext(request);
    ensure(task.game_instance_id === state.game_instance_id, 'GAME_INSTANCE_CONFLICT');
    ensure(state.mode !== 'AUTO' && state.inputs_released && !state.automation_ready && !this.manager.lease
      && state.active_task_id === null, 'GAME_DISPOSITION_BRIDGE_BUSY');
    ensure(request.expected_control_epoch === state.control_epoch && request.based_on_seq === state.seq, 'GAME_DISPOSITION_OBSERVATION_CHANGED');
    ensure(task.version === request.expected_task_version && (recovery?.revision || 0) === request.expected_recovery_revision, 'GAME_DISPOSITION_CONFLICT');
    ensure(task.effect_status !== 'verified' && this.disposition(id)?.status !== 'closed_unknown'
      && (TERMINAL.has(task.state) ? !recovery || recovery.status === 'verified'
        : ['missing', 'conflict'].includes(recovery?.status) && recovery.checked_bridge_boot_id === state.bridge_boot_id), 'GAME_DISPOSITION_NOT_READY');
    ensure(request.reason.trim().length > 0, 'GAME_REQUEST_INVALID', 400);
    const old = this.disposition(id), now = utc(this.manager.wall());
    const value = { task_id: id, revision: (old?.revision || 0) + 1, status: 'closed_unknown', reason: request.reason,
      acknowledged_unknown: true, task_version: task.version, task_hash: hash(task), recovery_revision: recovery?.revision || 0,
      created_at: old?.created_at || now, updated_at: now, reopen_reason: null,
      observed_context: Object.fromEntries(['game_instance_id', 'bridge_boot_id', 'world_id', 'world_session_id', 'seq', 'control_epoch',
        'mode', 'inputs_released', 'active_task_id', 'observed_at'].map(key => [key, state[key]])) };
    validate('TaskDisposition', value);
    this.store.transaction(() => {
      this.store.run('INSERT INTO task_dispositions VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET revision=excluded.revision,status=excluded.status,value=excluded.value', id, value.revision, value.status, canonical(value));
      this.setRecovery(id, 'operator_closed', 'OPERATOR_CLOSED_UNKNOWN');
      this.manager.continuity.disposed(id);
      this.store.run('INSERT INTO idempotency VALUES(?,?,?,?,?)', scope, request.request_id, hash(request), 'task_disposition', id);
      this.store.audit('operator_closed_unknown_task', { task_id: id, disposition: value });
    });
    this.manager.publish('task', this.get(id)); this.manager.continuity.publishTaskGoal(id); return this.get(id);
  }
  reopenRecord(task) {
    const disposition = this.disposition(task.task_id);
    if (!disposition || disposition.status !== 'closed_unknown' || TERMINAL.has(task.state)) return;
    disposition.status = 'reopened'; disposition.revision++; disposition.updated_at = utc(this.manager.wall());
    disposition.reopen_reason = 'GAME_DISPOSED_TASK_REAPPEARED'; validate('TaskDisposition', disposition);
    this.store.run('UPDATE task_dispositions SET revision=?,status=?,value=? WHERE task_id=?', disposition.revision, disposition.status, canonical(disposition), task.task_id);
    this.setRecovery(task.task_id, 'conflict', 'GAME_DISPOSED_TASK_REAPPEARED');
    this.store.audit('disposed_task_reappeared', { task_id: task.task_id, disposition_revision: disposition.revision });
  }
  enforceReopened(id) {
    if (this.disposition(id)?.status !== 'reopened' || TERMINAL.has(this.raw(id).state)) return;
    this.manager.lease = null; this.manager.planner.cancel();
    try { this.manager.send('control_request', { request_id: 'disposition-fence-' + randomUUID(), operation_id: 'operation-' + randomUUID(),
      controller_session_id: this.manager.controllerId, target_mode: 'PAUSED', reason: 'GAME_DISPOSED_TASK_REAPPEARED' }); }
    catch { this.manager.disconnect('disposed_task_reappeared'); }
  }
  observe(state) {
    if (state.active_task_id && this.disposition(state.active_task_id)?.status === 'closed_unknown') {
      this.store.transaction(() => this.reopenRecord(this.raw(state.active_task_id)));
      this.enforceReopened(state.active_task_id); this.manager.publish('task', this.get(state.active_task_id));
    }
  }
}
