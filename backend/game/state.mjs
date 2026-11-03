import { EventEmitter } from 'node:events';
import { performance } from 'node:perf_hooks';
import { validate } from './protocol.mjs';
import { ensure } from './errors.mjs';

const EMPTY = { schema_version: 1, game_instance_id: null, bridge_boot_id: null, world_id: null,
  world_session_id: null, connection_generation: null, seq: null, observed_at: null, rule_fingerprint: null,
  mode: null, control_epoch: null, inputs_released: null, automation_ready: false, lease_remaining_ms: null,
  player: null, inventory: [], screen: 'unknown', environment: null, unknown_fields: ['not_connected'], active_task_id: null };
export class GameState extends EventEmitter {
  constructor({ clock = () => performance.now(), staleMs = 2000 } = {}) {
    super(); this.clock = clock; this.staleMs = staleMs; this.value = structuredClone(EMPTY);
    this.connected = false; this.received = null; this.revision = 0; this.gap = false;
  }
  attach(identity) {
    this.identity = { ...identity }; this.connected = true; this.received = null; this.gap = false;
    this.value = { ...structuredClone(EMPTY), ...identity }; this.changed();
  }
  assertIdentity(envelope) {
    ensure(this.connected && this.identity, 'GAME_DISCONNECTED', 503);
    for (const key of ['game_instance_id', 'bridge_boot_id', 'connection_generation'])
      ensure(envelope[key] === this.identity[key], 'GAME_STALE_CONNECTION');
  }
  snapshot(value) {
    validate('Observation', value); this.assertIdentity(value);
    const changedWorld = this.value.world_session_id && value.world_session_id !== this.value.world_session_id;
    if (!changedWorld && this.value.seq !== null && value.seq <= this.value.seq) return false;
    if (!changedWorld) ensure(value.control_epoch >= (this.value.control_epoch ?? 0), 'GAME_STALE_EPOCH');
    const oldWorld = this.value.world_session_id;
    this.value = structuredClone(value); this.received = this.clock(); this.gap = false;
    if (changedWorld) this.emit('world', { previous: oldWorld, current: value.world_session_id });
    this.changed(); return true;
  }
  delta(value) {
    ensure(value.world_session_id === this.value.world_session_id, 'GAME_WORLD_CHANGED');
    if (this.value.seq !== null && value.seq <= this.value.seq) return false;
    if (this.gap || value.base_seq !== this.value.seq) { this.gap = true; this.changed(); this.emit('gap'); return false; }
    ensure(value.seq > value.base_seq, 'GAME_SEQUENCE_INVALID', 400);
    const next = { ...this.value, ...value.changes, seq: value.seq, observed_at: value.observed_at };
    validate('Observation', next); this.value = next; this.received = this.clock(); this.changed(); return true;
  }
  control(result) {
    ensure(result.world_session_id === this.value.world_session_id, 'GAME_WORLD_CHANGED');
    ensure(result.control_epoch >= (this.value.control_epoch ?? 0), 'GAME_STALE_EPOCH');
    Object.assign(this.value, { mode: result.mode, control_epoch: result.control_epoch,
      inputs_released: result.inputs_released, automation_ready: result.automation_ready }); this.changed();
  }
  disconnect() {
    this.connected = false; this.gap = true; this.value.automation_ready = false; this.value.lease_remaining_ms = null; this.changed();
  }
  view() {
    const age = this.received === null ? null : Math.max(0, Math.floor(this.clock() - this.received));
    const fresh = this.connected && !this.gap && age !== null && age <= this.staleMs;
    return { ...structuredClone(this.value), connected: this.connected, age_ms: age,
      freshness: fresh ? 'fresh' : this.received === null ? 'unavailable' : 'stale',
      automation_ready: fresh && this.value.mode === 'AUTO' && !!this.value.automation_ready && this.value.lease_remaining_ms > 0,
      view_revision: this.revision };
  }
  requireFresh() {
    ensure(this.connected, 'GAME_DISCONNECTED', 503);
    const state = this.view(); ensure(state.freshness === 'fresh', 'GAME_STATE_STALE', 503); return state;
  }
  changed() { this.revision++; this.emit('change', this.view()); }
}
