import { randomUUID } from 'node:crypto';
import { canonical } from '../dsh-bridge/channel.mjs';
import { hash } from './store.mjs';
import { ensure, utc } from './errors.mjs';
import { validate } from './protocol.mjs';

/** World facts belong to the game ledger, never to a second personality writer. */
export class WorldService {
  constructor(manager) { this.manager = manager; this.store = manager.store; }
  now() { return utc(this.manager.wall()); }
  summary() {
    const id = this.manager.state.value.world_id;
    const row = id ? this.store.get('SELECT value FROM world_registry WHERE world_id=?', id) : null;
    const world = row ? JSON.parse(row.value) : null;
    const recent = world ? this.store.get('SELECT value FROM world_checkpoints WHERE world_id=? ORDER BY rowid DESC LIMIT 1', id) : null;
    const checkpoint = recent ? JSON.parse(recent.value) : null;
    return { world, active_base: world?.active_base_id ? this.base(id, world.active_base_id) : null,
      latest_checkpoint: checkpoint ? { checkpoint_id: checkpoint.checkpoint_id, created_at: checkpoint.created_at,
        reason: checkpoint.reason, world_session_id: checkpoint.world_session_id, seq: checkpoint.snapshot.seq } : null,
      task_recovery: this.store.all("SELECT value FROM task_recovery WHERE status NOT IN ('verified','operator_closed') ORDER BY rowid LIMIT 100").map(row => JSON.parse(row.value)),
      ...this.manager.continuity.summary(id) };
  }
  get(worldId) {
    const row = this.store.get('SELECT value FROM world_registry WHERE world_id=?', worldId);
    ensure(row, 'GAME_WORLD_NOT_FOUND', 404); return JSON.parse(row.value);
  }
  base(worldId, baseId) {
    const row = this.store.get('SELECT value FROM world_bases WHERE world_id=? AND base_id=?', worldId, baseId);
    ensure(row, 'GAME_BASE_NOT_FOUND', 404); return JSON.parse(row.value);
  }
  baseReference(target) {
    const reference = Object.fromEntries(['game_instance_id', 'world_id', 'base_id', 'base_revision', 'world_revision'].map(key => [key, target[key]]));
    validate('BaseRef', reference); return reference;
  }
  resolveBase(goal, expected, state = this.manager.state.value) {
    if (goal.skill !== 'return_base') { ensure(expected === undefined, 'GAME_BASE_CONTEXT_INVALID'); return null; }
    const world = this.get(state.world_id), base = this.base(state.world_id, goal.base_id);
    ensure(world.game_instance_id === state.game_instance_id && base.world_id === state.world_id, 'GAME_BASE_CONTEXT_INVALID');
    ensure(!base.archived, 'GAME_BASE_ARCHIVED');
    ensure(state.player?.position?.dimension === base.position.dimension, 'GAME_BASE_DIMENSION_CHANGED');
    const target = { game_instance_id: state.game_instance_id, world_id: world.world_id, base_id: base.base_id,
      base_revision: base.revision, world_revision: world.revision, position: structuredClone(base.position), radius: base.radius,
      source: base.source, registered_world_session_id: base.world_session_id, registered_seq: base.based_on_seq };
    validate('BaseTarget', target);
    if (expected !== undefined) {
      validate('BaseRef', expected);
      ensure(canonical(expected) === canonical(this.baseReference(target)), 'GAME_BASE_CHANGED');
    }
    return target;
  }
  checkpoint(id) {
    const row = this.store.get('SELECT value FROM world_checkpoints WHERE checkpoint_id=?', id);
    ensure(row, 'GAME_CHECKPOINT_NOT_FOUND', 404); return JSON.parse(row.value);
  }
  putWorld(value) {
    validate('World', value);
    this.store.run('INSERT INTO world_registry VALUES(?,?,?,?) ON CONFLICT(world_id) DO UPDATE SET revision=excluded.revision,value=excluded.value',
      value.world_id, value.game_instance_id, value.revision, canonical(value));
  }
  observe(observation) {
    const row = this.store.get('SELECT value FROM world_registry WHERE world_id=?', observation.world_id);
    const old = row ? JSON.parse(row.value) : null;
    ensure(!old || old.game_instance_id === observation.game_instance_id, 'GAME_WORLD_INSTANCE_CONFLICT');
    const ruleChanged = old && old.rule_fingerprint !== observation.rule_fingerprint;
    if (old && !ruleChanged && old.last_world_session_id === observation.world_session_id &&
        Date.parse(this.now()) - Date.parse(old.last_seen) < 15000) return;
    ensure(old || this.store.get('SELECT count(*) n FROM world_registry').n < 1024, 'GAME_WORLD_LIMIT', 503);
    const world = old ? { ...old, last_seen: this.now(), last_world_session_id: observation.world_session_id,
      rule_fingerprint: observation.rule_fingerprint, revision: old.revision + (ruleChanged ? 1 : 0) } : {
      world_id: observation.world_id, game_instance_id: observation.game_instance_id, local_label: observation.world_id,
      revision: 1, rule_fingerprint: observation.rule_fingerprint, first_seen: this.now(), last_seen: this.now(),
      last_world_session_id: observation.world_session_id, active_base_id: null };
    this.store.transaction(() => { this.putWorld(world); this.store.setMeta('last_world', {
      world_id: observation.world_id, world_session_id: observation.world_session_id }); });
    this.manager.publish('world', world);
  }
  page(kind, { worldId, limit = 20, cursor } = {}) {
    ensure(Number.isInteger(limit) && limit >= 1 && limit <= 100, 'GAME_REQUEST_INVALID', 400);
    let before = Number.MAX_SAFE_INTEGER;
    if (cursor) { ensure(/^[1-9][0-9]{0,15}$/.test(cursor), 'GAME_CURSOR_INVALID', 400); before = Number(cursor); }
    const table = { world: 'world_registry', base: 'world_bases', checkpoint: 'world_checkpoints' }[kind];
    ensure(table, 'GAME_RECORD_KIND_INVALID', 500);
    if (worldId) this.get(worldId);
    const rows = this.store.all(`SELECT rowid,value FROM ${table} WHERE rowid<? ${worldId ? 'AND world_id=?' : ''} ORDER BY rowid DESC LIMIT ?`,
      before, ...(worldId ? [worldId] : []), limit + 1);
    return { items: rows.slice(0, limit).map(row => JSON.parse(row.value)), next_cursor: rows.length > limit ? String(rows[limit - 1].rowid) : null };
  }
  replay(scope, request) {
    const row = this.store.get('SELECT * FROM idempotency WHERE scope=? AND request_id=?', scope, request.request_id);
    if (!row) return null;
    ensure(row.body_hash === hash(request), 'GAME_IDEMPOTENCY_CONFLICT');
    if (row.kind === 'world') return this.get(row.object_id);
    if (row.kind === 'checkpoint') return this.checkpoint(row.object_id);
    const base = this.store.get('SELECT value FROM world_bases WHERE base_id=?', row.object_id);
    ensure(row.kind === 'base' && base, 'GAME_IDEMPOTENCY_RECORD_INVALID', 503); return JSON.parse(base.value);
  }
  remember(scope, request, kind, value) {
    this.store.run('INSERT INTO idempotency VALUES(?,?,?,?,?)', scope, request.request_id, hash(request), kind, value[kind + '_id']);
  }
  current(worldId, request) {
    const state = this.manager.checkContext(request);
    ensure(state.world_id === worldId, 'GAME_WORLD_CHANGED');
    ensure(state.mode !== 'AUTO' && state.inputs_released, 'GAME_MODE_BLOCKED'); return state;
  }
  label(worldId, request) {
    validate('WorldLabelRequest', request); const scope = 'world-label:' + worldId;
    const replay = this.replay(scope, request); if (replay) return replay;
    const world = this.get(worldId); ensure(world.revision === request.expected_revision, 'GAME_WORLD_CONFLICT');
    world.local_label = request.local_label; world.revision++;
    this.store.transaction(() => { this.putWorld(world); this.remember(scope, request, 'world', world); });
    this.manager.publish('world', world); return world;
  }
  registerBase(worldId, request) {
    validate('BaseCreate', request); const scope = 'base-create:' + worldId;
    const replay = this.replay(scope, request); if (replay) return { value: replay, duplicate: true };
    const state = this.current(worldId, request), world = this.get(worldId);
    ensure(world.revision === request.expected_world_revision, 'GAME_WORLD_CONFLICT');
    ensure(state.screen === 'gameplay' && state.player?.position, 'GAME_PRECONDITION_FAILED');
    ensure(this.store.get('SELECT count(*) n FROM world_bases WHERE world_id=?', worldId).n < 128, 'GAME_BASE_LIMIT', 503);
    const base = { base_id: 'base-' + randomUUID(), world_id: worldId, revision: 1, label: request.label,
      position: structuredClone(state.player.position), radius: request.radius, source: 'operator_observed',
      world_session_id: state.world_session_id, based_on_seq: state.seq, observed_at: state.observed_at, created_at: this.now(), archived: false };
    validate('Base', base); world.active_base_id = base.base_id; world.revision++;
    this.store.transaction(() => {
      this.store.run('INSERT INTO world_bases VALUES(?,?,?,?)', base.base_id, worldId, base.revision, canonical(base));
      this.putWorld(world); this.remember(scope, request, 'base', base);
    });
    this.manager.publish('base', base); this.manager.publish('world', world); return { value: base, duplicate: false };
  }
  archiveBase(worldId, baseId, request) {
    validate('BaseArchiveRequest', request); const scope = 'base-archive:' + worldId + ':' + baseId;
    const replay = this.replay(scope, request); if (replay) return replay;
    const world = this.get(worldId), base = this.base(worldId, baseId);
    ensure(world.revision === request.expected_world_revision && base.revision === request.expected_revision, 'GAME_WORLD_CONFLICT');
    ensure(this.manager.state.value.mode !== 'AUTO' && !this.manager.tasks.active(), 'GAME_MODE_BLOCKED');
    base.archived = true; base.revision++; if (world.active_base_id === baseId) world.active_base_id = null; world.revision++;
    this.store.transaction(() => {
      this.store.run('UPDATE world_bases SET revision=?,value=? WHERE base_id=? AND world_id=?', base.revision, canonical(base), baseId, worldId);
      this.putWorld(world); this.remember(scope, request, 'base', base);
    });
    this.manager.publish('base', base); this.manager.publish('world', world); return base;
  }
  selectBase(worldId, baseId, request) {
    validate('BaseSelectRequest', request); const scope = 'base-select:' + worldId + ':' + baseId;
    const replay = this.replay(scope, request); if (replay) return replay;
    const state = this.current(worldId, request), world = this.get(worldId), base = this.base(worldId, baseId);
    ensure(!state.automation_ready && !this.manager.lease && state.active_task_id === null && !this.manager.tasks.active(), 'GAME_TASK_BUSY');
    ensure(world.revision === request.expected_world_revision && base.revision === request.expected_revision, 'GAME_WORLD_CONFLICT');
    ensure(!base.archived, 'GAME_BASE_ARCHIVED');
    world.active_base_id = baseId; world.revision++;
    this.store.transaction(() => {
      this.putWorld(world); this.remember(scope, request, 'world', world);
      this.store.audit('world_base_selected', { world_id: worldId, base_id: baseId, revision: world.revision });
    });
    this.manager.publish('world', world); return world;
  }
  createCheckpoint(worldId, request) {
    validate('CheckpointCreate', request); const scope = 'checkpoint-create:' + worldId;
    const replay = this.replay(scope, request); if (replay) return { value: replay, duplicate: true };
    this.current(worldId, request); this.get(worldId);
    const active = this.manager.tasks.active();
    ensure(!active || this.manager.tasks.recovery(active.task_id), 'GAME_TASK_BUSY');
    ensure(this.store.get('SELECT count(*) n FROM world_checkpoints WHERE world_id=?', worldId).n < 256, 'GAME_CHECKPOINT_LIMIT', 503);
    const snapshot = structuredClone(this.manager.state.value); validate('Observation', snapshot);
    const checkpoint = { checkpoint_id: 'checkpoint-' + randomUUID(), world_id: worldId, game_instance_id: snapshot.game_instance_id,
      world_session_id: snapshot.world_session_id, bridge_boot_id: snapshot.bridge_boot_id, created_at: this.now(), reason: request.reason,
      snapshot, task_refs: this.store.all("SELECT id FROM objects WHERE kind='task' AND json_extract(value,'$.world_id')=? ORDER BY rowid DESC LIMIT 100", worldId).map(row => row.id),
      base_refs: this.store.all('SELECT base_id,value FROM world_bases WHERE world_id=?', worldId)
        .filter(row => !JSON.parse(row.value).archived).map(row => row.base_id) };
    validate('Checkpoint', checkpoint);
    this.store.transaction(() => {
      this.store.run('INSERT INTO world_checkpoints VALUES(?,?,?,?)', checkpoint.checkpoint_id, worldId, checkpoint.created_at, canonical(checkpoint));
      this.remember(scope, request, 'checkpoint', checkpoint);
    });
    this.manager.publish('checkpoint', checkpoint); return { value: checkpoint, duplicate: false };
  }
}
