import { randomUUID } from 'node:crypto';
import { canonical } from '../dsh-bridge/channel.mjs';
import { hash } from './store.mjs';
import { validate } from './protocol.mjs';
import { ensure, utc } from './errors.mjs';
import { TERMINAL } from './tasks.mjs';

/** World history and operator-approved objectives. Never restores input authority. */
export class WorldContinuity {
  constructor(manager) {
    this.manager = manager; this.store = manager.store;
    this.suspend('host_restart');
  }
  now() { return utc(this.manager.wall()); }
  session(id) { const row = this.store.get('SELECT value FROM world_sessions WHERE session_id=?', id);
    ensure(row, 'GAME_WORLD_SESSION_NOT_FOUND', 404); return JSON.parse(row.value); }
  goal(id) { const row = this.store.get('SELECT value FROM world_goals WHERE goal_id=?', id);
    ensure(row, 'GAME_WORLD_GOAL_NOT_FOUND', 404); return JSON.parse(row.value); }
  putSession(value) {
    validate('WorldSession', value);
    this.store.run('INSERT INTO world_sessions VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET status=excluded.status,value=excluded.value',
      value.world_session_id, value.world_id, value.status, canonical(value));
  }
  putGoal(value) {
    validate('WorldGoal', value);
    this.store.run('INSERT INTO world_goals VALUES(?,?,?,?,?) ON CONFLICT(goal_id) DO UPDATE SET revision=excluded.revision,status=excluded.status,value=excluded.value',
      value.goal_id, value.world_id, value.revision, value.status, canonical(value));
  }
  touch(goal, reason) { goal.revision++; goal.updated_at = this.now(); if (reason !== undefined) goal.reason = reason; this.putGoal(goal); }
  page(kind, worldId, { limit = 20, cursor } = {}) {
    this.manager.worlds.get(worldId); ensure(Number.isInteger(limit) && limit >= 1 && limit <= 100, 'GAME_REQUEST_INVALID', 400);
    let before = Number.MAX_SAFE_INTEGER;
    if (cursor) { ensure(/^[1-9][0-9]{0,15}$/.test(cursor), 'GAME_CURSOR_INVALID', 400); before = Number(cursor); ensure(Number.isSafeInteger(before), 'GAME_CURSOR_INVALID', 400); }
    const table = { session: 'world_sessions', goal: 'world_goals' }[kind]; ensure(table, 'GAME_RECORD_KIND_INVALID', 500);
    const rows = this.store.all(`SELECT rowid,value FROM ${table} WHERE world_id=? AND rowid<? ORDER BY rowid DESC LIMIT ?`, worldId, before, limit + 1);
    return { items: rows.slice(0, limit).map(row => JSON.parse(row.value)), next_cursor: rows.length > limit ? String(rows[limit - 1].rowid) : null };
  }
  summary(worldId) {
    const id = this.manager.state.value.world_session_id;
    const current = id ? this.store.get('SELECT value FROM world_sessions WHERE session_id=?', id) : null;
    const goals = worldId ? this.store.all("SELECT value FROM world_goals WHERE world_id=? AND status<>'archived' ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'needs_review' THEN 1 WHEN 'blocked' THEN 2 ELSE 3 END,rowid DESC LIMIT 16", worldId).map(row => {
      const value = JSON.parse(row.value); return { goal_id: value.goal_id, world_id: value.world_id, revision: value.revision,
        title: value.title, status: value.status, completed_steps: value.steps.filter(step => step.state === 'completed').length,
        total_steps: value.steps.length, last_review_session_id: value.last_review_session_id, reason: value.reason,
        next_step: value.steps.find(step => step.state !== 'completed') || null };
    }) : [];
    return { current_session: current ? JSON.parse(current.value) : null, world_goals: goals };
  }
  suspend(reason) {
    const changed = [];
    this.store.transaction(() => {
      for (const row of this.store.all("SELECT value FROM world_sessions WHERE status='observed'")) {
        const value = JSON.parse(row.value); value.status = reason === 'world_changed' ? 'ended' : 'unobserved'; value.closed_at = this.now(); value.close_reason = reason;
        if (this.lastObservation?.world_session_id === value.world_session_id) {
          value.last_observed_at = this.lastObservation.observed_at; value.last_seq = this.lastObservation.seq;
        }
        this.putSession(value);
      }
      for (const row of this.store.all("SELECT value FROM world_goals WHERE status='active'")) {
        const goal = JSON.parse(row.value); goal.status = 'needs_review'; this.touch(goal, reason); changed.push(goal);
      }
    });
    for (const goal of changed) this.manager.publish('world_goal', goal);
  }
  observe(observation) {
    this.lastObservation = structuredClone(observation);
    const row = this.store.get('SELECT value FROM world_sessions WHERE session_id=?', observation.world_session_id);
    let session = row ? JSON.parse(row.value) : null;
    ensure(!session || session.world_id === observation.world_id && session.game_instance_id === observation.game_instance_id
      && (!session.bridge_boot_id || session.bridge_boot_id === observation.bridge_boot_id), 'GAME_WORLD_SESSION_CONTEXT');
    const connectionChanged = !session || session.last_connection_generation !== observation.connection_generation;
    const writeSession = !session || session.status !== 'observed' || connectionChanged || this.manager.wall() - Date.parse(session.last_observed_at) >= 15000;
    const candidateRows = this.store.all("SELECT value FROM world_goals WHERE world_id=? AND status='active'", observation.world_id);
    const changed = [];
    if (!writeSession && candidateRows.length === 0) return;
    this.store.transaction(() => {
      if (writeSession) {
        ensure(session || this.store.get('SELECT count(*) n FROM world_sessions').n < 10000, 'GAME_WORLD_SESSION_LIMIT', 503);
        for (const old of this.store.all("SELECT value FROM world_sessions WHERE session_id<>? AND status='observed'", observation.world_session_id)) {
          const value = JSON.parse(old.value); value.status = 'ended'; value.closed_at = this.now(); value.close_reason = 'world_changed'; this.putSession(value);
        }
        session = { world_session_id: observation.world_session_id, world_id: observation.world_id, game_instance_id: observation.game_instance_id,
          bridge_boot_id: observation.bridge_boot_id, status: 'observed', source: 'observed', first_observed_at: session?.first_observed_at || observation.observed_at,
          last_observed_at: observation.observed_at, last_seq: observation.seq, last_connection_generation: observation.connection_generation,
          connection_count: (session?.connection_count || 0) + (connectionChanged ? 1 : 0), closed_at: null, close_reason: null };
        this.putSession(session);
      }
      for (const candidate of candidateRows) {
        const goal = JSON.parse(candidate.value);
        if (goal.last_review_session_id !== observation.world_session_id) {
          goal.status = 'needs_review'; this.touch(goal, 'new_world_session'); changed.push(goal); continue;
        }
        if (this.manager.state.view().freshness === 'fresh' && this.advance(goal, observation)) changed.push(goal);
      }
    });
    if (writeSession) this.manager.publish('world_session', session);
    for (const goal of changed) this.manager.publish('world_goal', goal);
  }
  stopped(worldId, request) {
    const state = this.manager.worlds.current(worldId, request);
    ensure(state.screen === 'gameplay' && !state.automation_ready && !this.manager.lease
      && state.active_task_id === null && !this.manager.tasks.active(), 'GAME_WORLD_GOAL_BUSY'); return state;
  }
  replay(scope, request) {
    const row = this.store.get('SELECT body_hash,object_id FROM idempotency WHERE scope=? AND request_id=?', scope, request.request_id);
    if (!row) return null; ensure(row.body_hash === hash(request), 'GAME_IDEMPOTENCY_CONFLICT'); return this.goal(row.object_id);
  }
  remember(scope, request, goal) { this.store.run('INSERT INTO idempotency VALUES(?,?,?,?,?)', scope, request.request_id, hash(request), 'world_goal', goal.goal_id); }
  create(worldId, request) {
    validate('WorldGoalCreate', request); const scope = 'world-goal-create:' + worldId;
    const replay = this.replay(scope, request); if (replay) return { value: replay, duplicate: true };
    this.stopped(worldId, request); const world = this.manager.worlds.get(worldId);
    ensure(world.revision === request.expected_world_revision, 'GAME_WORLD_CONFLICT');
    ensure(request.title.trim() && new Set(request.steps.map(step => step.step_id)).size === request.steps.length
      && request.steps.every(step => step.label.trim()), 'GAME_REQUEST_INVALID', 400);
    ensure(this.store.get('SELECT count(*) n FROM world_goals WHERE world_id=?', worldId).n < 128, 'GAME_WORLD_GOAL_LIMIT', 503);
    const now = this.now(), goal = { goal_id: 'world-goal-' + randomUUID(), world_id: worldId, revision: 1, title: request.title,
      description: request.description, status: 'draft', steps: request.steps.map(step => ({ ...step, state: 'pending', task_ids: [], proof: null, reason: null })),
      created_at: now, updated_at: now, last_review_session_id: null, reason: null };
    this.store.transaction(() => { this.putGoal(goal); this.remember(scope, request, goal); this.store.audit('world_goal_created', { goal_id: goal.goal_id, world_id: worldId }); });
    this.manager.publish('world_goal', goal); return { value: goal, duplicate: false };
  }
  decision(id, request) {
    validate('WorldGoalDecision', request); const scope = 'world-goal-decision:' + id;
    const replay = this.replay(scope, request); if (replay) return replay;
    const goal = this.goal(id), state = this.stopped(goal.world_id, request);
    ensure(goal.revision === request.expected_revision, 'GAME_WORLD_GOAL_CONFLICT'); ensure(request.reason.trim(), 'GAME_REQUEST_INVALID', 400);
    if (request.action === 'activate') {
      ensure(['draft', 'needs_review', 'blocked'].includes(goal.status), 'GAME_WORLD_GOAL_STATE');
      ensure(!goal.steps.some(step => step.state === 'blocked' || step.state === 'running'), 'GAME_WORLD_GOAL_RETRY_REQUIRED');
      ensure(!this.store.get("SELECT goal_id FROM world_goals WHERE world_id=? AND status='active' AND goal_id<>?", goal.world_id, id), 'GAME_WORLD_GOAL_ACTIVE');
      goal.status = 'active'; goal.last_review_session_id = state.world_session_id;
    } else if (request.action === 'retry_step') {
      const step = goal.steps.find(value => value.state !== 'completed');
      ensure(['blocked', 'needs_review'].includes(goal.status) && step?.state === 'blocked' && step.task_ids.length < 10, 'GAME_WORLD_GOAL_STATE');
      const taskId = step.task_ids.at(-1), task = taskId ? this.manager.tasks.get(taskId) : null;
      ensure(!task || task.effect_status === 'verified' || task.disposition?.status === 'closed_unknown', 'GAME_WORLD_GOAL_UNKNOWN_EFFECT');
      step.state = 'pending'; step.reason = null; goal.status = 'needs_review';
    } else if (request.action === 'pause') {
      ensure(!['archived', 'completed'].includes(goal.status), 'GAME_WORLD_GOAL_STATE'); goal.status = 'needs_review';
    } else { ensure(goal.status !== 'archived', 'GAME_WORLD_GOAL_STATE'); goal.status = 'archived'; }
    this.store.transaction(() => { this.touch(goal, request.reason); this.remember(scope, request, goal);
      this.store.audit('world_goal_decision', { goal_id: id, action: request.action, revision: goal.revision, world_session_id: state.world_session_id }); });
    this.manager.publish('world_goal', goal); return goal;
  }
  referenceFor(goalValue) {
    const world = this.manager.state.value.world_id;
    const row = this.store.get("SELECT value FROM world_goals WHERE world_id=? AND status='active'", world);
    if (!row) return null; const goal = JSON.parse(row.value), step = goal.steps.find(value => value.state !== 'completed');
    return step && step.state === 'pending' && canonical(step.goal) === canonical(goalValue)
      ? { goal_id: goal.goal_id, step_id: step.step_id, expected_revision: goal.revision } : null;
  }
  linkTask(reference, task) {
    validate('WorldGoalRef', reference); const goal = this.goal(reference.goal_id), step = goal.steps.find(value => value.state !== 'completed');
    ensure(goal.revision === reference.expected_revision, 'GAME_WORLD_GOAL_CONFLICT');
    ensure(goal.status === 'active' && goal.world_id === task.world_id && goal.last_review_session_id === task.world_session_id
      && step?.step_id === reference.step_id && step.state === 'pending' && step.task_ids.length < 10
      && canonical(step.goal) === canonical(task.goal), 'GAME_WORLD_GOAL_TASK_CONTEXT');
    step.task_ids.push(task.task_id); step.state = 'running'; this.touch(goal, null);
    this.store.run('INSERT INTO world_goal_tasks VALUES(?,?,?)', task.task_id, goal.goal_id, step.step_id);
  }
  applyTask(task) {
    const link = this.store.get('SELECT goal_id,step_id FROM world_goal_tasks WHERE task_id=?', task.task_id); if (!link || !TERMINAL.has(task.state)) return;
    const goal = this.goal(link.goal_id), step = goal.steps.find(value => value.step_id === link.step_id);
    if (step.state === 'completed' || step.task_ids.at(-1) !== task.task_id) return;
    if (task.state === 'succeeded' && task.effect_status === 'verified') { step.state = 'awaiting_observation'; step.reason = null; }
    else { step.state = 'blocked'; step.reason = task.reason || 'GAME_TASK_NOT_COMPLETED'; if (goal.status !== 'archived') goal.status = 'blocked'; }
    this.touch(goal, step.reason);
  }
  publishTaskGoal(taskId) {
    const link = this.store.get('SELECT goal_id FROM world_goal_tasks WHERE task_id=?', taskId);
    if (link) this.manager.publish('world_goal', this.goal(link.goal_id));
  }
  disposed(taskId) {
    const link = this.store.get('SELECT goal_id,step_id FROM world_goal_tasks WHERE task_id=?', taskId); if (!link) return;
    const goal = this.goal(link.goal_id), step = goal.steps.find(value => value.step_id === link.step_id);
    if (step.state === 'completed' || step.task_ids.at(-1) !== taskId) return;
    step.state = 'blocked'; step.reason = 'OPERATOR_CLOSED_UNKNOWN';
    if (goal.status !== 'archived') goal.status = 'blocked'; this.touch(goal, step.reason);
  }
  conditionMet(condition, observation, task) {
    if (condition.kind === 'inventory_at_least') return !observation.unknown_fields.some(field => field === 'inventory' || field.startsWith('inventory.'))
      && observation.inventory.filter(item => item.item_id === condition.item_id).reduce((sum, item) => sum + item.count, 0) >= condition.count;
    if (condition.kind === 'food_at_least') return !observation.unknown_fields.some(field => ['player', 'player.food'].includes(field))
      && observation.player?.food !== null && observation.player?.food >= condition.food;
    if (condition.kind === 'position_within') {
      const position = observation.player?.position, target = condition.target;
      return !observation.unknown_fields.some(field => field === 'player' || field === 'player.position' || field.startsWith('player.position.'))
        && !!position && position.dimension === target.dimension && Math.hypot(position.x - target.x, position.y - target.y, position.z - target.z) <= condition.radius;
    }
    return !!task && task.state === 'succeeded' && task.effect_status === 'verified' && task.evidence.length > 0
      && [undefined, 'verified'].includes(this.manager.tasks.recovery(task.task_id)?.status);
  }
  advance(goal, observation) {
    const step = goal.steps.find(value => value.state !== 'completed'); if (!step || !['pending', 'awaiting_observation'].includes(step.state)) return false;
    const taskId = step.task_ids.at(-1), task = taskId ? this.manager.tasks.raw(taskId) : null;
    if (task && (!TERMINAL.has(task.state) || task.state !== 'succeeded' || task.effect_status !== 'verified'
      || ![undefined, 'verified'].includes(this.manager.tasks.recovery(task.task_id)?.status))) return false;
    if (!this.conditionMet(step.condition, observation, task)) return false;
    if (task && (task.world_id !== observation.world_id || task.evidence.some(e => e.world_session_id !== task.world_session_id)
      || task.world_session_id === observation.world_session_id && task.evidence.some(e => e.seq > observation.seq))) return false;
    step.state = 'completed'; step.reason = null; step.proof = { source: task ? 'task_and_observation' : 'observation',
      world_session_id: observation.world_session_id, seq: observation.seq, observed_at: observation.observed_at,
      task_id: taskId || null, condition: structuredClone(step.condition) };
    if (goal.steps.every(value => value.state === 'completed')) goal.status = 'completed';
    this.touch(goal, null); return true;
  }
}
