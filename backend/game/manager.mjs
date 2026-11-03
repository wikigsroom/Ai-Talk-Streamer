import { EventEmitter } from 'node:events';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { performance } from 'node:perf_hooks';
import { WebSocketServer } from 'ws';
import { canonical } from '../dsh-bridge/channel.mjs';
import { GameError, ensure, utc } from './errors.mjs';
import { validate, parseEnvelope, readBody } from './protocol.mjs';
import { GameStore, hash } from './store.mjs';
import { GameState } from './state.mjs';
import { applyPatch, initialConfig } from './config.mjs';
import { TaskService, TERMINAL } from './tasks.mjs';
import { SuggestionService } from './suggestions.mjs';
import { VoteService } from './votes.mjs';
import { GameTools } from '../dsh-bridge/game-tools.mjs';
import { GamePlanner } from './planner.mjs';
import { GameNarration } from './narration.mjs';
import { WorldService } from './worlds.mjs';
import { WorldContinuity } from './continuity.mjs';
import { FrameStore } from './frames.mjs';
import { GameVision } from './vision.mjs';
import { modelState, speechState } from './model-state.mjs';
import { recipeResult } from './recipes.mjs';
import { AudienceSources } from './audience-sources.mjs';
import { GameHistory } from './history.mjs';
import { AudienceIntents } from './audience-intents.mjs';

const PREFIX = '/api/dsh/game';
const uid = prefix => prefix + '-' + randomUUID();
export class GameManager extends EventEmitter {
  constructor(root, bridge, { store, config, clock = () => performance.now(), wall = () => Date.now(), roomId, visionProvider } = {}) {
    super(); this.root = root; this.bridge = bridge; this.clock = clock; this.wall = wall;
    const stateRoot = bridge.policy?.deployment?.state_relative_path || 'state/mc-local';
    this.store = store || new GameStore(join(root, stateRoot, 'game/game.sqlite3'));
    this.config = this.store.meta('config', config || initialConfig(root, validate));
    validate('GameConfig', this.config); this.config = applyPatch(this.config, {});
    this.configRevision = this.store.meta('config_revision', 0);
    this.state = new GameState({ clock, staleMs: this.config.control.state_stale_ms });
    this.controllerId = uid('controller'); this.clients = new Set(); this.viewRevision = 0; this.pending = new Map();
    this.tasks = new TaskService(this); this.suggestions = new SuggestionService(this); this.votes = new VoteService(this);
    this.worlds = new WorldService(this);
    this.continuity = new WorldContinuity(this);
    this.frames = new FrameStore(this); this.vision = new GameVision(this, visionProvider);
    this.history = new GameHistory(this);
    this.tools = new GameTools(this); this.planner = new GamePlanner(this);
    // DSH's character room is a persona namespace, not the selected platform room.
    this.roomId = roomId || (() => { const value = bridge.platforms?.config?.value?.platforms?.bilibili?.room_id; return typeof value === 'string' && value.length ? value : null; });
    this.audienceSources = new AudienceSources(this);
    this.intents = new AudienceIntents(this);
    this.narration = new GameNarration(this);
    this.wsServer = new WebSocketServer({ noServer: true, maxPayload: 131072, perMessageDeflate: false });
    this.state.on('change', value => this.publish('state', value));
    this.state.on('gap', () => this.send('snapshot_request', { reason: 'sequence_gap' }));
    this.state.on('world', () => { this.lease = null; this.frames.clear(); this.history.stop('GAME_HISTORY_CONTEXT_CHANGED'); this.tasks.interrupted('WORLD_CHANGED'); this.continuity.suspend('world_changed'); this.suggestions.expire(true); this.votes.tick();
      for (const pending of [...this.pending.values()]) if (['observation','frame'].includes(pending.queryKind)) this.finishOperation(pending.operation, null, 'GAME_WORLD_CHANGED'); });
    this.tasks.interrupted('INTERRUPTED_HOST_RESTART');
    // Startup never replays a task or a control request from persistence.
    for (const row of this.store.all("SELECT value FROM objects WHERE kind='operation'")) {
      const operation = JSON.parse(row.value);
      if (['pending', 'running'].includes(operation.state)) this.finishOperation(operation, null, 'INTERRUPTED_HOST_RESTART');
    }
    this.closed = false; this.lastFreshness = 'unavailable';
  }
  start() {
    ensure(!this.closing && !this.closed, 'GAME_DISABLED', 503);
    // Verify pinned files while the native client is loading, before its first observation request.
    if (this.config.vision.enabled) this.vision.available();
    this.timer = setInterval(() => { try { this.tick(); } catch (error) { this.storageFault(error, 'scheduler'); } }, 250); this.timer.unref(); return this;
  }
  requireEnabled() { ensure(this.config.enabled && !this.closed && !this.closing, 'GAME_DISABLED', 503); ensure(!this.faulted, 'GAME_STORAGE_ERROR', 503); }
  stopAdmission() {
    if(this.closed || this.closing)return;
    this.closing=true;clearInterval(this.timer);
    this.planner.cancel();this.intents.running?.controller.abort();
    this.disconnect('host_shutdown');
  }
  faultDetail(error, phase, frameType = null) {
    const code = typeof error?.code === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(error.code) ? error.code : 'GAME_STORAGE_ERROR';
    return { schema_version: 1, at: utc(this.wall()), phase, code, frame_type: frameType,
      sqlite_code: Number.isSafeInteger(error?.errcode) ? error.errcode : null, observed_seq: this.state.value.seq };
  }
  healthView() {
    return { storage_error: !!this.faulted, controller_session_id: this.controllerId, connected: this.state.connected,
      last_fault: structuredClone(this.lastFault || null), last_protocol_error: structuredClone(this.lastProtocolError || null),
      last_disconnect: structuredClone(this.lastDisconnect || null), last_bridge_message: structuredClone(this.lastBridgeMessage || null),
      slowest_bridge_message: structuredClone(this.slowestBridgeMessage || null) };
  }
  storageFault(error, phase = 'unspecified', frameType = null) {
    this.lastFault ||= this.faultDetail(error, phase, frameType);
    if (this.faulted) return; this.faulted = true; this.lease = null;
    try { if (this.socket?.readyState === 1) this.send('control_request', { request_id: uid('fault'),
      operation_id: uid('operation'), controller_session_id: this.controllerId, target_mode: 'PAUSED', reason: 'storage_error' }); } catch { /* lease expiry is the local final stop */ }
    this.socket?.close(1011, 'storage_error'); this.publish('health', this.healthView());
  }
  configure(request) {
    ensure(!this.closed && !this.closing, 'GAME_DISABLED', 503);
    validate('ConfigPatch', request); ensure(request.expected_revision === this.configRevision, 'GAME_CONFIG_CONFLICT');
    if (request.patch.control || request.patch.enabled === false) ensure(this.state.value.mode !== 'AUTO' && !this.tasks.active(), 'GAME_CONTROL_CONFLICT');
    const next = applyPatch(this.config, request.patch); validate('GameConfig', next);
    this.store.transaction(() => { this.store.setMeta('config', next); this.store.setMeta('config_revision', this.configRevision + 1); });
    const prepareVision = next.vision.enabled && !this.config.vision.enabled;
    const armAutostart = next.planner.enabled && next.planner.autostart &&
      (!this.config.planner.enabled || !this.config.planner.autostart);
    this.config = next; this.configRevision++; this.state.staleMs = next.control.state_stale_ms;
    if (armAutostart) this.planner.autostart = null;
    if (prepareVision) this.vision.available();
    if (!next.planner.enabled) this.planner.cancel();
    if (!next.vision.enabled) {
      this.frames.clear();
      for (const pending of [...this.pending.values()]) if (['observation','frame'].includes(pending.queryKind)) this.finishOperation(pending.operation, null, 'GAME_VISION_DISABLED');
    }
    if (!next.enabled) this.disconnect('disabled');
    this.narration.sweep();
    this.intents.sweep();
    this.publish('config', this.configuration()); return this.configuration();
  }
  configuration() { return { revision: this.configRevision, settings: structuredClone(this.config) }; }
  stateView() { return { ...this.state.view(), world_ledger: this.worlds.summary(), audience: this.suggestions.summary() }; }
  modelStateView(options) { return modelState(this.stateView(), options); }
  speechStateView() { return speechState({ ...this.state.view(), world_ledger: this.worlds.summary() }); }
  snapshot() {
    return { state: this.stateView(), configuration: this.configuration(),
      capabilities: this.capabilities || null, tasks: this.tasks.page(), operations: this.store.list('operation'),
      suggestions: this.suggestions.page(), votes: this.votes.page(), audience_intents: this.intents.page(),
      narration: this.narration.page(),
      worlds: this.worlds.page('world'),
      health: this.healthView(),
      view_revision: this.viewRevision };
  }
  publish(type, value) {
    this.viewRevision++; this.emit(type, value);
    const frame = `id: ${this.viewRevision}\nevent: ${type}\ndata: ${JSON.stringify(value)}\n\n`;
    for (const res of this.clients) {
      if (res.writableLength > 262144 || !res.write(frame)) { this.clients.delete(res); res.end(); }
    }
  }
  subscribe(req, res, diagnosticsOnly = false) {
    ensure(this.clients.size < 24, 'GAME_EVENT_CLIENT_LIMIT', 503);
    res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' });
    res.write(`retry: 2500\nid: ${this.viewRevision}\nevent: ${diagnosticsOnly ? 'health' : 'snapshot'}\ndata: ${JSON.stringify(diagnosticsOnly ? this.healthView() : this.snapshot())}\n\n`);
    this.clients.add(res); req.on('close', () => this.clients.delete(res));
  }
  upgrade(req, socket, head) {
    try {
      this.requireEnabled(); ensure(new URL(req.url, 'http://localhost').pathname === PREFIX + '/bridge', 'GAME_NOT_FOUND', 404);
      this.wsServer.handleUpgrade(req, socket, head, ws => this.acceptSocket(ws));
    } catch (error) { socket.end(`HTTP/1.1 ${error.status || 503} Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`); }
  }
  acceptSocket(socket) {
    let identity = null, count = 0, window = this.clock();
    const deadline = setTimeout(() => { if (!identity) socket.close(1008, 'hello_required'); }, 5000); deadline.unref();
    socket.on('error', () => {});
    socket.on('message', (data, binary) => {
      if(this.closed || this.closing){socket.terminate();return;}
      const started = performance.now(); let frame = null, failed = false; const phase = identity ? 'bridge_message' : 'bridge_handshake';
      try {
        if (this.clock() - window > 1000) { window = this.clock(); count = 0; }
        ensure(++count <= 200, 'GAME_RATE_LIMIT', 429);
        frame = parseEnvelope(data, binary);
        if (!identity) {
          ensure(frame.type === 'hello', 'GAME_HELLO_REQUIRED', 400);
          ensure(frame.payload.capabilities.game_instance_id === frame.game_instance_id, 'GAME_INSTANCE_MISMATCH');
          const bound = this.store.meta('bound_instance', null);
          ensure(!bound || bound === frame.game_instance_id, 'GAME_INSTANCE_CONFLICT');
          if (this.socket) {
            const prior = this.state.identity;
            ensure(prior.game_instance_id === frame.game_instance_id, 'GAME_INSTANCE_CONFLICT');
            ensure(frame.bridge_boot_id !== prior.bridge_boot_id || frame.connection_generation > prior.connection_generation, 'GAME_CONNECTION_GENERATION');
            this.disconnect('replaced_connection');
          }
          const remembered = this.store.meta('last_connection', null);
          ensure(!remembered || frame.bridge_boot_id !== remembered.bridge_boot_id || frame.connection_generation > remembered.connection_generation, 'GAME_CONNECTION_GENERATION');
          ensure(frame.payload.mode === 'PAUSED' || frame.payload.mode === 'MANUAL_COMMENTARY', 'GAME_RECONNECT_REQUIRES_PAUSED');
          identity = Object.fromEntries(['game_instance_id', 'bridge_boot_id', 'connection_generation'].map(k => [k, frame[k]]));
          this.store.transaction(() => { this.store.setMeta('bound_instance', frame.game_instance_id); this.store.setMeta('last_connection', identity); });
          this.socket = socket; this.capabilities = frame.payload.capabilities; this.lease = null; this.grantSeq = 0;
          this.lastHeartbeat = this.clock(); this.state.attach(identity); clearTimeout(deadline);
          this.send('hello_ack', { controller_session_id: this.controllerId, accepted_protocol: '1.0', snapshot_required: true });
          return;
        }
        ensure(socket === this.socket, 'GAME_STALE_CONNECTION'); this.state.assertIdentity(frame);
        this.receive(frame);
      } catch (error) {
        failed = true;
        if (!(error instanceof GameError)) { this.storageFault(error, phase, frame?.type || null); return; }
        if (error.code === 'GAME_STORE_OWNER_LOST') { this.storageFault(error, phase, frame?.type || null); return; }
        this.lastProtocolError = this.faultDetail(error, phase, frame?.type || null);
        this.publish('health', { ...this.healthView(), protocol_error: error.code });
        if (identity && socket === this.socket) {
          try { this.send('protocol_error', error.public()); } catch { /* closing below */ }
        }
        socket.close(1008, error.code.slice(0, 100));
      } finally {
        const timing = { at: utc(this.wall()), phase, frame_type: frame?.type || null, duration_ms: Math.round(Math.max(0, performance.now() - started) * 1000) / 1000 };
        this.lastBridgeMessage = timing;
        if (!this.slowestBridgeMessage || timing.duration_ms > this.slowestBridgeMessage.duration_ms) this.slowestBridgeMessage = timing;
        if (failed || timing.duration_ms >= 250) {
          try { this.publish('health', this.healthView()); } catch { /* diagnostics never override the control failure */ }
        }
      }
    });
    socket.on('close', () => { clearTimeout(deadline); if (this.socket === socket) this.disconnect('connection_closed'); });
  }
  send(type, payload) {
    ensure(this.socket?.readyState === 1, 'GAME_DISCONNECTED', 503);
    ensure(this.socket.bufferedAmount <= 262144, 'GAME_SEND_BACKPRESSURE', 503);
    const frame = { protocol_version: '1.0', type, message_id: uid('message'), ...this.state.identity, sent_at: utc(this.wall()), payload };
    validate('BridgeEnvelope', frame); this.socket.send(canonical(frame));
  }
  disconnect(reason) {
    this.frames.clear();
    const socket = this.socket; this.socket = null; this.lease = null; this.heartbeat = null;
    if (socket || this.state.connected) {
      this.lastDisconnect = { at: utc(this.wall()), reason };
      try { this.history.stop('GAME_HISTORY_DISCONNECTED'); }
      catch (error) { this.lastFault ||= this.faultDetail(error, 'disconnect_history'); this.faulted = true; }
      try { this.tasks.interrupted('CONNECTION_LOST:' + reason); this.continuity.suspend('connection_lost:' + reason); }
      catch (error) { this.lastFault ||= this.faultDetail(error, 'disconnect_tasks'); this.faulted = true; }
    }
    if (socket && socket.readyState < 2) socket.close(1001, reason.slice(0, 100));
    this.state.disconnect();
    for (const pending of this.pending.values()) {
      try { this.finishOperation(pending.operation, null, 'GAME_DISCONNECTED'); }
      catch (error) { this.lastFault ||= this.faultDetail(error, 'disconnect_operations'); this.faulted = true; }
    }
    this.pending.clear();
  }
  receive(frame) {
    ensure(!this.closed && !this.closing, 'GAME_DISABLED', 503);
    const p = frame.payload;
    if (frame.type === 'snapshot') {
      const applied = this.state.snapshot(p);
      if (applied) { this.worlds.observe(p); this.tasks.observe(p); this.continuity.observe(p); }
      return;
    }
    if (frame.type === 'delta') {
      const applied = this.state.delta(p);
      if (applied) { this.worlds.observe(this.state.value); this.tasks.observe(this.state.value); this.continuity.observe(this.state.value); }
      return applied;
    }
    if (frame.type === 'heartbeat') {
      ensure(p.controller_session_id === null || p.controller_session_id === this.controllerId, 'GAME_CONTROLLER_CHANGED');
      ensure(!this.heartbeat || p.heartbeat_seq > this.heartbeat.heartbeat_seq, 'GAME_HEARTBEAT_SEQUENCE');
      this.heartbeat = p; this.lastHeartbeat = this.clock();
      if (this.lease && p.lease_id === this.lease.id && p.control_epoch === this.lease.epoch) this.grant(p.heartbeat_seq);
      return;
    }
    if (frame.type === 'control_result') return this.controlResult(p);
    if (frame.type === 'task_update' || frame.type === 'game_event') {
      const taskUpdate = frame.type === 'task_update', session = taskUpdate ? p.task.world_session_id : p.world_session_id;
      ensure(session === this.state.value.world_session_id, 'GAME_WORLD_CHANGED');
      const stream = taskUpdate ? 'task_transitions' : 'events';
      const deliverySession = frame.bridge_boot_id + ':' + session;
      const receipt = this.store.receipt(stream, deliverySession, p.delivery_seq);
      if (!receipt.duplicate) this.store.transaction(() => {
        if (taskUpdate) this.tasks.update(p, { publish: false });
        else this.store.run('INSERT OR IGNORE INTO game_events VALUES(?,?,?,?)', p.event_id, session, utc(this.wall()), canonical(p));
        this.store.acknowledge(stream, deliverySession, p.delivery_seq);
      });
      this.send('ack', { world_session_id: session, ack_kind: stream, through_seq: receipt.through });
      if (taskUpdate && !receipt.duplicate) {
        this.tasks.enforceReopened(p.task.task_id); this.continuity.publishTaskGoal(p.task.task_id);
        this.publish('task', this.tasks.get(p.task.task_id)); if (TERMINAL.has(p.task.state)) this.finishCancellations(p.task);
      }
      if (!taskUpdate && !receipt.duplicate) this.publish('game_event', p);
      return;
    }
    if (frame.type === 'query_result') {
      const pending = this.pending.get(p.operation_id);
      if (!pending) { const old = this.store.object('operation', p.operation_id);
        if (old?.kind === 'query' && old.request_id === p.request_id && TERMINAL.has(old.state)) return; }
      ensure(pending?.operation.kind === 'query' && p.request_id === pending.operation.request_id, 'GAME_QUERY_CORRELATION');
      ensure(pending.world === this.state.value.world_session_id, 'GAME_WORLD_CHANGED');
      ensure(['succeeded', 'failed'].includes(p.state), 'GAME_QUERY_RESULT_INVALID', 400);
      if (p.state === 'succeeded') ensure(p.result?.world_session_id === pending.world && p.result?.kind === pending.queryKind, 'GAME_QUERY_RESULT_CONTEXT');
      if (pending.queryKind === 'journal_history' && p.state === 'succeeded') {
        try { return this.finishOperation(pending.operation, this.history.accept(p.result, pending)); }
        catch (error) {
          if (!(error instanceof GameError) || error.code === 'GAME_STORE_OWNER_LOST') throw error;
          return this.finishOperation(pending.operation, null, error.code);
        }
      }
      if (pending.queryKind === 'recipe' && p.state === 'succeeded') recipeResult(p.result, pending);
      if (pending.queryKind === 'check_action' && p.state === 'succeeded') {
        ensure(canonical(p.result.base_target ?? null) === canonical(pending.baseTarget), 'GAME_QUERY_BASE_CHANGED');
        if (pending.baseTarget) {
          try {
            const current = this.worlds.resolveBase(pending.baseGoal, this.worlds.baseReference(pending.baseTarget));
            ensure(canonical(current) === canonical(pending.baseTarget), 'GAME_BASE_CHANGED');
          } catch (error) { return this.finishOperation(pending.operation, null, error instanceof GameError ? error.code : 'GAME_BASE_CHANGED'); }
        }
      }
      if (pending.ledgerIds && p.state === 'succeeded') this.tasks.reconcile(p.result, pending.ledgerIds);
      if (pending.queryKind === 'frame' && p.state === 'succeeded') {
        validate('RawFrameResult', p.result);
        const entry = this.frames.claim(p.operation_id, p.result); entry.pinned = false;
        return this.finishOperation(pending.operation, p.result);
      }
      if (pending.queryKind === 'observation' && p.state === 'succeeded') {
        if (pending.visionResultReceived) return;
        pending.visionResultReceived = true;
        void this.vision.result(p.operation_id, p.result).catch(error => {
          if (this.pending.get(p.operation_id) === pending) this.finishOperation(pending.operation, null, error instanceof GameError ? error.code : 'GAME_VISION_PROVIDER_FAILED');
        }); return;
      }
      return this.finishOperation(pending.operation, p.result, p.error || (p.state === 'failed' ? 'GAME_QUERY_FAILED' : null));
    }
    if (frame.type === 'protocol_error') { this.publish('health', { bridge_error: p.error }); return; }
    if (frame.type !== 'ack') throw new GameError('GAME_UNEXPECTED_MESSAGE', 400);
  }
  grant(heartbeatSeq) {
    if (!this.lease || this.faulted || this.state.view().freshness !== 'fresh') return;
    this.send('lease_grant', { controller_session_id: this.controllerId, lease_id: this.lease.id,
      control_epoch: this.lease.epoch, grant_seq: ++this.grantSeq, based_on_heartbeat_seq: heartbeatSeq,
      ttl_ms: this.config.control.lease_ttl_ms });
  }
  checkContext(request) {
    this.requireEnabled(); const state = this.state.requireFresh();
    ensure(request.bridge_boot_id === state.bridge_boot_id, 'GAME_BOOT_CHANGED');
    ensure(request.world_session_id === state.world_session_id, 'GAME_WORLD_CHANGED'); return state;
  }
  readyForAction(request) {
    const state = this.checkContext(request);
    ensure(state.mode === 'AUTO' && state.automation_ready && this.lease, 'GAME_MODE_BLOCKED');
    ensure(request.expected_control_epoch === state.control_epoch && state.control_epoch === this.lease.epoch, 'GAME_CONTROL_CONFLICT');
    ensure(request.based_on_seq <= state.seq && request.based_on_seq >= Math.max(0, state.seq - 50), 'GAME_OBSERVATION_SEQUENCE');
    ensure(state.screen === 'gameplay', 'GAME_PRECONDITION_FAILED'); return state;
  }
  newOperation(kind, request, { scope = kind, result = null } = {}) {
    const operation = { operation_id: uid('operation'), request_id: request.request_id, kind, state: 'pending',
      created_at: utc(this.wall()), updated_at: utc(this.wall()), result, error: null };
    this.store.transaction(() => this.store.remember(scope, request, 'operation', operation));
    this.publish('operation', operation); return operation;
  }
  finishOperation(operation, result, error = null) {
    const pending = this.pending.get(operation.operation_id);
    if (['observation', 'frame'].includes(pending?.queryKind)) this.vision.release(operation.operation_id);
    if (error && pending?.ledgerIds) this.tasks.queryFailed(pending.ledgerIds, error);
    Object.assign(operation, { state: error ? 'failed' : 'succeeded', updated_at: utc(this.wall()), result, error });
    this.store.put('operation', operation); this.pending.delete(operation.operation_id); this.publish('operation', operation);
    if (error && pending?.historyImportId) this.history.operationFailed(pending, error);
    return operation;
  }
  operation(id) { const value = this.store.object('operation', id); ensure(value, 'GAME_OPERATION_NOT_FOUND', 404); return value; }
  control(request) {
    validate('ControlRequest', request); this.requireEnabled();
    const replay = this.store.replay('control', request); if (replay) return replay;
    ensure(this.state.connected, 'GAME_DISCONNECTED', 503);
    if (request.target_mode === 'AUTO') {
      const state = this.checkContext(request); ensure(request.expected_control_epoch === state.control_epoch, 'GAME_CONTROL_CONFLICT');
      const respawn = state.screen === 'death' && state.player?.health === 0 && this.capabilities.features.autonomous_respawn === true;
      ensure((respawn || (state.screen === 'gameplay' || state.screen === 'menu' && this.capabilities.features.autonomous_resume === true)
        && state.player?.health > 0) && !this.tasks.active(), 'GAME_PRECONDITION_FAILED');
      ensure(this.capabilities.features.local_takeover && this.capabilities.features.cancel_all, 'GAME_CAPABILITY_UNAVAILABLE', 503);
      this.history.stop('GAME_HISTORY_MODE_CHANGED');
    } else {
      this.planner.suspendAutostart();
      this.lease = null; this.planner.cancel();
      for (const previous of [...this.pending.values()]) if (previous.target === 'AUTO')
        this.finishOperation(previous.operation, null, 'SUPERSEDED_CONTROL');
    }
    ensure(![...this.pending.values()].some(p => p.operation.kind === 'control' && p.target === 'AUTO' && request.target_mode === 'AUTO'), 'GAME_CONTROL_CONFLICT');
    const operation = this.newOperation('control', request);
    this.pending.set(operation.operation_id, { operation, target: request.target_mode, world: this.state.value.world_session_id,
      deadline: this.clock() + this.config.control.lease_ttl_ms + 3000 });
    this.send('control_request', { ...request, operation_id: operation.operation_id, controller_session_id: this.controllerId }); return operation;
  }
  controlResult(result) {
    const pending = this.pending.get(result.operation_id);
    // Local takeover may arrive without an outstanding HTTP request. It can
    // only revoke authority; it cannot remotely grant AUTO.
    if (!pending) {
      ensure(result.mode !== 'AUTO' && result.inputs_released, 'GAME_CONTROL_CORRELATION');
      // Death releases the old lease first. Only the native capability may
      // leave normal respawn eligible; startSession still needs a fresh death
      // observation. Never clear an earlier physical or explicit stop fence.
      const normalDeath = result.stop_reason === 'PLAYER_DEATH' && result.mode === 'PAUSED' &&
        result.world_session_id === this.state.value.world_session_id &&
        this.capabilities?.features?.autonomous_respawn === true && !result.error &&
        !result.automation_ready && result.lease_id === null;
      const transientStop = ['LEASE_EXPIRED','GAME_CLIENT_TICK_STALLED'].includes(result.stop_reason) &&
        result.mode === 'PAUSED' && result.world_session_id === this.state.value.world_session_id &&
        this.capabilities?.features?.autonomous_resume === true && !result.error &&
        !result.automation_ready && result.lease_id === null && this.state.value.details?.environment?.singleplayer === true &&
        this.state.value.details.environment.local_server_published === false;
      if (!normalDeath && !transientStop) this.planner.suspendAutostart();
      if (transientStop) this.planner.retryAutostart();
      this.lease = null; this.state.control(result); return;
    }
    ensure(pending.operation.kind === 'control' && pending.operation.request_id === result.request_id, 'GAME_CONTROL_CORRELATION');
    if (result.error) return this.finishOperation(pending.operation, result, result.error);
    ensure(result.mode === pending.target, 'GAME_CONTROL_MODE_MISMATCH');
    if (result.mode === 'AUTO') {
      ensure(result.lease_id && result.heartbeat_seq, 'GAME_LEASE_HANDSHAKE_INVALID');
      if (!result.automation_ready) {
        this.state.control(result);
        this.lease = { id: result.lease_id, epoch: result.control_epoch };
        this.grant(result.heartbeat_seq); return;
      }
      ensure(this.lease?.id === result.lease_id && this.lease.epoch === result.control_epoch, 'GAME_LEASE_HANDSHAKE_INVALID');
    } else { ensure(result.inputs_released, 'GAME_INPUTS_NOT_RELEASED'); this.lease = null; }
    this.state.value.lease_remaining_ms = result.mode === 'AUTO' ? this.config.control.lease_ttl_ms : null;
    this.state.control(result);
    return this.finishOperation(pending.operation, result);
  }
  cancel(taskId, request) {
    validate('CancelRequest', request); this.requireEnabled(); const scope = 'cancel:' + taskId;
    const replay = this.store.replay(scope, request); if (replay) return replay;
    const task = this.tasks.get(taskId);
    if (!TERMINAL.has(task.state)) ensure(this.state.connected, 'GAME_DISCONNECTED', 503);
    const operation = this.newOperation('cancel', request, { scope });
    if (TERMINAL.has(task.state)) return this.finishOperation(operation, { task_id: taskId, state: task.state });
    this.pending.set(operation.operation_id, { operation, taskId, deadline: this.clock() + 5000 });
    this.send('task_cancel', { controller_session_id: this.controllerId, operation_id: operation.operation_id,
      request_id: request.request_id, task_id: taskId, reason: request.reason }); return operation;
  }
  finishCancellations(task) {
    for (const pending of this.pending.values()) if (pending.taskId === task.task_id)
      this.finishOperation(pending.operation, { task_id: task.task_id, state: task.state, effect_status: task.effect_status });
  }
  query(request, { historyImportId } = {}) {
    validate('QueryRequest', request); const replay = this.store.replay('query', request); if (replay) return replay;
    const state = this.checkContext(request);
    if (request.kind === 'check_action' && request.params.goal.skill === 'use_item' && request.params.goal.target) {
      const feature = request.params.goal.item_id==='minecraft:dirt' ? 'targeted_terrain_placement'
        : ['minecraft:crafting_table','minecraft:furnace'].includes(request.params.goal.item_id) ? 'targeted_block_placement' : 'targeted_planting';
      ensure(this.capabilities.features[feature] === true, 'GAME_CAPABILITY_UNAVAILABLE', 503);
      ensure(request.params.goal.target.dimension === state.player?.position?.dimension, 'GAME_PRECONDITION_FAILED');
    }
    ensure([...this.pending.values()].filter(p => p.operation.kind === 'query').length < 8, 'GAME_QUEUE_FULL', 429);
    if (request.kind === 'recipe') ensure(this.capabilities.features.recipes, 'GAME_CAPABILITY_UNAVAILABLE', 503);
    if (request.kind === 'journal_history') {
      ensure(this.capabilities.features.journal_history, 'GAME_CAPABILITY_UNAVAILABLE', 503);
      if (!['reliable', 'task_versions'].includes(request.params.source))
        ensure(this.capabilities.features.journal_maintenance_history, 'GAME_CAPABILITY_UNAVAILABLE', 503);
      ensure(historyImportId && this.history.job?.history_import_id === historyImportId, 'GAME_HISTORY_IMPORT_REQUIRED');
      this.history.stoppedContext(this.history.job);
    }
    if (['observation', 'frame'].includes(request.kind)) {
      ensure(this.config.vision.enabled && this.capabilities.features.screenshots, 'GAME_CAPABILITY_UNAVAILABLE', 503);
      if (request.kind === 'frame') ensure(this.capabilities.features.raw_frames === true, 'GAME_CAPABILITY_UNAVAILABLE', 503);
      this.vision.admit({ inference: request.kind === 'observation' });
    }
    const ledgerIds = request.kind === 'task_ledger' ? request.params.task_ids : null;
    if (ledgerIds) {
      ensure(this.capabilities.features.task_ledger && this.state.value.mode !== 'AUTO' && this.state.value.inputs_released, 'GAME_RECOVERY_MODE_BLOCKED', 503);
      for (const id of ledgerIds) this.tasks.raw(id);
    }
    const baseTarget = request.kind === 'check_action' ? this.worlds.resolveBase(request.params.goal, request.params.base_ref, state) : null;
    const operation = this.newOperation('query', request);
    this.pending.set(operation.operation_id, { operation, world: request.world_session_id, boot: this.state.value.bridge_boot_id,
      generation: this.state.value.connection_generation, admittedSeq: this.state.value.seq, purpose: request.params.purpose, queryKind: request.kind, ledgerIds,
      recipeParams: request.kind === 'recipe' ? structuredClone(request.params) : null,
      historyImportId: request.kind === 'journal_history' ? historyImportId : null,
      historyParams: request.kind === 'journal_history' ? structuredClone(request.params) : null,
      baseTarget, baseGoal: baseTarget ? structuredClone(request.params.goal) : null,
      deadline: this.clock() + this.config.vision.timeout_ms });
    if (['observation', 'frame'].includes(request.kind)) this.vision.reserve(operation.operation_id);
    if (ledgerIds) this.tasks.querying(ledgerIds);
    this.send('query', { operation_id: operation.operation_id, request, ...(baseTarget ? { base_target: baseTarget } : {}) }); return operation;
  }
  async waitOperation(id, signal, timeout = 10000) {
    const initial = this.operation(id); if (TERMINAL.has(initial.state)) return initial;
    return new Promise((resolve, reject) => {
      const clean = () => { clearTimeout(timer); this.off('operation', listener); signal?.removeEventListener('abort', abort); };
      const listener = op => { if (op.operation_id === id && TERMINAL.has(op.state)) { clean(); resolve(op); } };
      const abort = () => { clean(); reject(new GameError('GAME_QUERY_CANCELLED')); };
      const timer = setTimeout(() => { clean(); reject(new GameError('GAME_OPERATION_TIMEOUT', 504)); }, timeout);
      this.on('operation', listener); signal?.addEventListener('abort', abort, { once: true }); if (signal?.aborted) abort();
    });
  }
  async panic(request) {
    validate('PanicRequest', request); this.requireEnabled();
    const replay = this.store.replay('panic', request); if (replay) return replay;
    const operation = this.newOperation('panic', request); const result = { game: null, room: null };
    try { const control = this.control({ request_id: uid('panic-stop'), target_mode: 'PAUSED', reason: request.reason }); result.game = { operation_id: control.operation_id, state: control.state }; }
    catch (error) { result.game = { error: error.code || 'GAME_STOP_FAILED' }; }
    try { result.room = await this.bridge.room.panic(); }
    catch (error) { result.room = { error: error.code || 'ROOM_PANIC_FAILED' }; }
    const controlId = result.game?.operation_id;
    if (controlId) {
      const control = this.operation(controlId);
      if (['pending', 'running'].includes(control.state)) { this.pending.set(operation.operation_id, { operation, controlId, roomResult: result.room, deadline: this.clock() + 6000 }); return operation; }
    }
    return this.finishOperation(operation, result, result.game?.error || result.room?.error || null);
  }
  acceptPlatformEvent(event) {
    if (!this.config.enabled || this.faulted || event.hidden || event.test) return;
    try { this.votes.cast(event); const fixed = this.suggestions.ingest(event); if (!fixed) this.intents.ingest(event); this.emit('platform', structuredClone(event)); }
    catch (error) { this.storageFault(error, 'platform_event'); }
  }
  reconcileAudienceSources() {
    if (this.closed || this.faulted || !this.bridge.room?.store || this.bridge.room.closed) return;
    try { this.votes.reconcileSources(); this.suggestions.reconcileSources(); this.intents.sweep(); }
    catch (error) { this.storageFault(error, 'audience_sources'); throw error; }
  }
  reconcilePending() {
    if (!this.config.enabled || this.faulted || !this.state.connected || this.clock() < (this.nextReconciliation || 0)) return;
    const ids = this.tasks.candidates(); if (!ids.length) return;
    if (!this.capabilities.features.task_ledger) {
      for (const id of ids) { this.tasks.setRecovery(id, 'unsupported', null, { last_error: 'GAME_LEDGER_UNSUPPORTED' }); this.publish('task', this.tasks.get(id)); }
      return;
    }
    const state = this.state.view();
    if (state.freshness !== 'fresh' || state.mode === 'AUTO' || !state.inputs_released || [...this.pending.values()].some(p => p.ledgerIds)) return;
    this.nextReconciliation = this.clock() + 2000;
    this.query({ request_id: uid('ledger'), bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id,
      kind: 'task_ledger', params: { task_ids: ids } });
  }
  tick() {
    if(this.closed || this.closing)return;
    const view = this.state.view();
    if (view.freshness !== this.lastFreshness) { this.lastFreshness = view.freshness; this.publish('state', view); }
    if (this.socket && this.clock() - this.lastHeartbeat > Math.max(5000, 3 * this.config.control.heartbeat_ms)) this.disconnect('heartbeat_timeout');
    for (const pending of [...this.pending.values()]) {
      if (pending.controlId) {
        const control = this.operation(pending.controlId);
        if (TERMINAL.has(control.state)) {
          this.finishOperation(pending.operation, { game: control.result || { error: control.error }, room: pending.roomResult },
            control.error || pending.roomResult?.error || null); continue;
        }
      }
      if (this.clock() >= pending.deadline) {
        if (pending.target === 'AUTO') { this.lease = null; this.disconnect('auto_handshake_timeout'); }
        this.finishOperation(pending.operation, null, 'GAME_OPERATION_TIMEOUT');
      }
    }
    this.suggestions.expire();
    if (!this.nextAudienceReconciliation || this.clock() >= this.nextAudienceReconciliation) {
      this.reconcileAudienceSources(); this.nextAudienceReconciliation = this.clock() + 1000;
    }
    if (!this.nextSupportPrune || this.clock() >= this.nextSupportPrune) {
      this.audienceSources.prune(); this.nextSupportPrune = this.clock() + 60000;
    }
    this.votes.tick();
    this.tools.observations.tick();
    this.narration.tick();
    this.reconcilePending();
    this.history.tick();
    const intents=()=>this.intents.tick().catch(error => this.storageFault(error, 'audience_intent_scheduler'));
    if(typeof this.bridge.background==='function') {
      this.bridge.background('game_audience_intent',intents);
      this.bridge.background('game_planning',()=>this.planner.tick());
    } else { void intents();void this.planner.tick(); }
    if (!this.lastSseHeartbeat || this.clock() - this.lastSseHeartbeat >= 15000) {
      this.lastSseHeartbeat = this.clock();
      for (const res of this.clients) if (!res.write(': heartbeat\n\n')) { this.clients.delete(res); res.end(); }
    }
  }
  async handle(req, res, url, send) {
    try {
      const path = url.pathname.slice(PREFIX.length), method = req.method;
      if (path === '/config' && method === 'GET') return send(this.configuration());
      if (path === '/config' && method === 'POST') return send(this.configure(await readBody(req)));
      // A failed store must not hide the in-memory cause behind another store
      // read. Existing state/task/mutation routes keep their failure guards.
      if (path === '/events' && method === 'GET' && this.faulted && this.config.enabled && !this.closed) return this.subscribe(req, res, true);
      if (method === 'GET' && path.startsWith('/history/')) {
        ensure(!this.closed && !this.faulted, 'GAME_STORAGE_ERROR', 503);
        if (path === '/history/status') return send(this.history.status());
        if (path === '/history/entries') return send(this.history.page({ limit: url.searchParams.has('limit') ? Number(url.searchParams.get('limit')) : 20,
          cursor: url.searchParams.get('cursor') || undefined, kind: url.searchParams.get('kind') || undefined }));
        const historyEntry = path.match(/^\/history\/entries\/([0-9a-f]{64})$/);
        if (historyEntry) return send(this.history.entry(historyEntry[1]));
        throw new GameError('GAME_NOT_FOUND', 404);
      }
      this.requireEnabled();
      if (path === '/state' && method === 'GET') return send(this.stateView());
      if (path === '/audience' && method === 'GET') return send(this.suggestions.summary());
      if (path === '/audience/intents' && method === 'GET') return send(this.intents.page({ limit: url.searchParams.has('limit') ? Number(url.searchParams.get('limit')) : 20, cursor: url.searchParams.get('cursor') || undefined }));
      if (path === '/narration' && method === 'GET') return send(this.narration.page({ limit: url.searchParams.has('limit') ? Number(url.searchParams.get('limit')) : 20, cursor: url.searchParams.get('cursor') || undefined }));
      if (path === '/capabilities' && method === 'GET') { ensure(this.state.connected && this.capabilities, 'GAME_DISCONNECTED', 503); return send(this.capabilities); }
      if (path === '/events' && method === 'GET') return this.subscribe(req, res);
      const frameMatch = path.match(/^\/frames\/([A-Za-z0-9_.:-]+)$/);
      if (frameMatch && method === 'POST') { res.shouldKeepAlive = false; return send(await this.frames.upload(req, frameMatch[1]), 201); }
      if (frameMatch && method === 'GET') { const frame = this.frames.get(frameMatch[1]);
        res.writeHead(200, { 'Content-Type': 'image/jpeg', 'Content-Length': frame.bytes.length, 'Cache-Control': 'no-store',
          'X-Content-Type-Options': 'nosniff', 'Access-Control-Allow-Origin': '*' }); res.end(frame.bytes); return; }
      const params = { limit: url.searchParams.has('limit') ? Number(url.searchParams.get('limit')) : 20, cursor: url.searchParams.get('cursor') || undefined };
      if (method === 'GET' && path === '/tasks') return send(this.tasks.page({ ...params, ...(url.searchParams.has('world_id') ? { worldId: url.searchParams.get('world_id') } : {}) }));
      if (method === 'GET' && path === '/worlds') return send(this.worlds.page('world', params));
      if (method === 'GET' && path === '/suggestions') return send(this.suggestions.page(params));
      if (method === 'GET' && path === '/votes') return send(this.votes.page(params));
      let match;
      if (method === 'GET' && (match = path.match(/^\/tasks\/([A-Za-z0-9_.:-]+)$/))) return send(this.tasks.get(match[1]));
      if (method === 'GET' && (match = path.match(/^\/operations\/([A-Za-z0-9_.:-]+)$/))) return send(this.operation(match[1]));
      if (method === 'GET' && (match = path.match(/^\/votes\/([A-Za-z0-9_.:-]+)$/))) return send(this.votes.get(match[1]));
      if (method === 'GET' && (match = path.match(/^\/worlds\/([A-Za-z0-9_.:-]+)$/))) return send(this.worlds.get(match[1]));
      if (method === 'GET' && (match = path.match(/^\/worlds\/([A-Za-z0-9_.:-]+)\/(bases|checkpoints)$/)))
        return send(this.worlds.page(match[2] === 'bases' ? 'base' : 'checkpoint', { ...params, worldId: match[1] }));
      if (method === 'GET' && (match = path.match(/^\/checkpoints\/([A-Za-z0-9_.:-]+)$/))) return send(this.worlds.checkpoint(match[1]));
      if (method === 'GET' && (match = path.match(/^\/worlds\/([A-Za-z0-9_.:-]+)\/(sessions|goals)$/)))
        return send(this.continuity.page(match[2] === 'sessions' ? 'session' : 'goal', match[1], params));
      if (method === 'GET' && (match = path.match(/^\/world-sessions\/([A-Za-z0-9_.:-]+)$/))) return send(this.continuity.session(match[1]));
      if (method === 'GET' && (match = path.match(/^\/world-goals\/([A-Za-z0-9_.:-]+)$/))) return send(this.continuity.goal(match[1]));
      const body = method === 'POST' ? await readBody(req) : {};
      this.requireEnabled();
      if (method === 'POST' && (match = path.match(/^\/audience\/intents\/([A-Za-z0-9_.:-]+)\/decision$/))) return send(this.intents.decision(match[1], body));
      if (method === 'POST' && path === '/history/imports') return send(this.history.start(body), 202);
      if (method === 'POST' && (match = path.match(/^\/history\/imports\/([A-Za-z0-9_.:-]+)\/cancel$/))) return send(this.history.cancel(match[1], body));
      if (method === 'POST' && (match = path.match(/^\/narration\/([A-Za-z0-9_.:-]+)\/cancel$/))) return send(this.narration.cancel(match[1], body));
      if (method === 'POST' && path === '/control') return send(this.control(body), 202);
      if (method === 'POST' && path === '/tasks') { const result = this.tasks.start(body); return send(result.value, result.duplicate ? 200 : 202); }
      if (method === 'POST' && (match = path.match(/^\/tasks\/([A-Za-z0-9_.:-]+)\/cancel$/))) return send(this.cancel(match[1], body), 202);
      if (method === 'POST' && (match = path.match(/^\/tasks\/([A-Za-z0-9_.:-]+)\/disposition$/))) return send(this.tasks.closeUnknown(match[1], body));
      if (method === 'POST' && path === '/queries') return send(this.query(body), 202);
      if (method === 'POST' && (match = path.match(/^\/tasks\/([A-Za-z0-9_.:-]+)\/reconcile$/))) {
        validate('ReconcileRequest', body); this.tasks.raw(match[1]); const state = this.state.requireFresh();
        return send(this.query({ request_id: 'reconcile-' + hash([match[1], body.request_id]), bridge_boot_id: state.bridge_boot_id,
          world_session_id: state.world_session_id, kind: 'task_ledger', params: { task_ids: [match[1]] } }), 202);
      }
      if (method === 'POST' && (match = path.match(/^\/worlds\/([A-Za-z0-9_.:-]+)\/label$/))) return send(this.worlds.label(match[1], body));
      if (method === 'POST' && (match = path.match(/^\/worlds\/([A-Za-z0-9_.:-]+)\/bases$/))) {
        const result = this.worlds.registerBase(match[1], body); return send(result.value, result.duplicate ? 200 : 201);
      }
      if (method === 'POST' && (match = path.match(/^\/worlds\/([A-Za-z0-9_.:-]+)\/bases\/([A-Za-z0-9_.:-]+)\/archive$/))) return send(this.worlds.archiveBase(match[1], match[2], body));
      if (method === 'POST' && (match = path.match(/^\/worlds\/([A-Za-z0-9_.:-]+)\/bases\/([A-Za-z0-9_.:-]+)\/select$/))) return send(this.worlds.selectBase(match[1], match[2], body));
      if (method === 'POST' && (match = path.match(/^\/worlds\/([A-Za-z0-9_.:-]+)\/checkpoints$/))) {
        const result = this.worlds.createCheckpoint(match[1], body); return send(result.value, result.duplicate ? 200 : 201);
      }
      if (method === 'POST' && (match = path.match(/^\/worlds\/([A-Za-z0-9_.:-]+)\/goals$/))) {
        const result = this.continuity.create(match[1], body); return send(result.value, result.duplicate ? 200 : 201);
      }
      if (method === 'POST' && (match = path.match(/^\/world-goals\/([A-Za-z0-9_.:-]+)\/decision$/))) return send(this.continuity.decision(match[1], body));
      if (method === 'POST' && path === '/panic') return send(await this.panic(body), 202);
      if (method === 'POST' && (match = path.match(/^\/suggestions\/([A-Za-z0-9_.:-]+)\/decision$/))) return send(this.suggestions.decision(match[1], body));
      if (method === 'POST' && (match = path.match(/^\/suggestions\/([A-Za-z0-9_.:-]+)\/dispatch$/))) return send(this.suggestions.dispatch(match[1], body), 202);
      if (method === 'POST' && path === '/votes') { const result = this.votes.create(body); return send(result.value, result.duplicate ? 200 : 201); }
      if (method === 'POST' && (match = path.match(/^\/votes\/([A-Za-z0-9_.:-]+)\/close$/))) return send(this.votes.close(match[1], body));
      if (method === 'POST' && (match = path.match(/^\/votes\/([A-Za-z0-9_.:-]+)\/suggestion$/))) {
        const result = this.votes.promote(match[1], body); return send(result.value, result.duplicate ? 200 : 201);
      }
      throw new GameError('GAME_NOT_FOUND', 404);
    } catch (error) {
      const known = error instanceof GameError ? error : new GameError('GAME_STORAGE_ERROR', 503);
      if (!(error instanceof GameError) || error.code === 'GAME_STORE_OWNER_LOST') this.storageFault(error, 'http_request');
      if (!res.headersSent) return send(known.public(), known.status); res.end();
    }
  }
  async close() {
    if (this.closed) return; this.closed = true; clearInterval(this.timer);
    this.closeErrors = [];
    const close = work => { try { work(); } catch (error) { this.faulted = true; this.closeErrors.push(error.code || 'GAME_SHUTDOWN_FAILED'); } };
    close(() => this.intents.close()); close(() => this.planner.close()); close(() => this.narration.close()); close(() => this.suggestions.close()); close(() => this.disconnect('host_shutdown'));
    for (const res of this.clients) close(() => res.end()); this.clients.clear();
    close(() => this.vision.provider.close?.());
    for (const socket of this.wsServer.clients) close(() => socket.terminate());
    close(() => this.wsServer.close()); close(() => this.store.close());
  }
}
