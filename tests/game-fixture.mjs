import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { join, resolve, relative } from 'node:path';
import { once } from 'node:events';
import { GameManager } from '../backend/game/manager.mjs';
import { DEFAULT_CONFIG } from '../backend/game/config.mjs';
const require = createRequire(new URL('../backend/game/package.json', import.meta.url));
const { WebSocket } = require('ws');
export const sourceRoot = resolve(process.cwd());
// Native ephemeral allocation can select a port rejected by Fetch/Chromium.
// Keep their restrictions intact and rebind only this fixture-owned listener.
const FETCH_BLOCKED_PORTS = new Set([1,7,9,11,13,15,17,19,20,21,22,23,25,37,42,43,53,69,77,79,87,95,
  101,102,103,104,109,110,111,113,115,117,119,123,135,137,139,143,161,179,389,427,465,512,513,514,515,
  526,530,531,532,540,548,554,556,563,587,601,636,989,990,993,995,1719,1720,1723,2049,3659,4045,4190,
  5060,5061,6000,6566,6665,6666,6667,6668,6669,6679,6697,10080]);
export const samples = Object.fromEntries(JSON.parse(readFileSync(join(sourceRoot, 'docs/technical/mc-live-v1/contracts/examples.json'), 'utf8')).cases.map(c => [c.name, c]));
export async function until(fn, timeout = 4000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const value = fn(); if (value) return value; await new Promise(r => setTimeout(r, 5)); }
  throw new Error('fixture condition timed out');
}
export async function gameFixture({ enabled = true, fakeClock = false, ui = false, visionProvider } = {}) {
  const output = join(sourceRoot, 'outputs/mc-tests'); mkdirSync(output, { recursive: true });
  const folder = mkdtempSync(join(output, 'game-')); let mono = 100, wall = Date.parse('2026-10-30T04:00:00Z');
  const config = structuredClone(DEFAULT_CONFIG); config.enabled = enabled;
  config.planner.engine = 'dsh'; // Existing model fixtures explicitly exercise the original DSH loop.
  config.control.enabled_skills = ['navigate', 'gather', 'craft', 'use_item', 'return_base', 'cancel'];
  const audienceMessages = new Map();
  const bridge = { policy: { deployment: { state_relative_path: 'state/testing' } }, state: { characterRoom: ['female-a', 'persona-room-is-not-platform'] },
    platforms: { config: { value: { platforms: { bilibili: { room_id: '100' } } } } },
    health: () => ({ persona_injection_ready: false }), room: { store: { message: id => audienceMessages.get(id) || null }, blocked: message => !!message.blocked,
      panic: () => ({ audio: { muted: true }, public_broadcast_started: false }) } };
  const managerOptions = { config, visionProvider, ...(fakeClock ? { clock: () => mono, wall: () => wall } : {}) };
  let manager = new GameManager(folder, bridge, managerOptions); bridge.game = manager;
  const server = createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const file = { '/mc-control': 'mc-control.html', '/mc-control.css': 'mc-control.css', '/mc-control.js': 'mc-control.js', '/mc-task-failures.js': 'mc-task-failures.js', '/mc-player-safety.mjs': 'mc-player-safety.mjs' }[url.pathname];
    if (ui && file) { res.writeHead(200, { 'Content-Type': file.endsWith('.html') ? 'text/html; charset=utf-8' : file.endsWith('.css') ? 'text/css' : 'text/javascript' });
      res.end(readFileSync(join(sourceRoot, 'web', file))); return; }
    if (ui && url.pathname === '/favicon.ico') { res.writeHead(204); res.end(); return; }
    void manager.handle(req, res, url, (value, status = 200) => {
      if (!res.headersSent) { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(value)); }
    });
  });
  const sockets = new Set();
  server.on('connection', socket => { sockets.add(socket); socket.once('close', () => sockets.delete(socket)); });
  server.on('upgrade', (req, socket, head) => manager.upgrade(req, socket, head));
  for (let attempt = 0; ; attempt++) {
    await new Promise(r => server.listen(0, '127.0.0.1', r));
    if (!FETCH_BLOCKED_PORTS.has(server.address().port)) break;
    await new Promise(r => server.close(r));
    if (attempt === 15) { await manager.close(); throw new Error('fixture could not bind a Fetch-compatible port'); }
  }
  const base = 'http://127.0.0.1:' + server.address().port, games = [];
  const api = async (path, body) => {
    const response = await fetch(base + '/api/dsh/game' + path, body === undefined ? {} : { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    return { status: response.status, value: await response.json() };
  };
  const connect = async ({ generation = 1, boot = 'boot-example-001', instance = 'mc-instance-example', helloOnly = false, features = {}, itemUses } = {}) => {
    const socket = new WebSocket(base.replace('http:', 'ws:') + '/api/dsh/game/bridge'); const messages = [];
    socket.on('message', bytes => messages.push(JSON.parse(String(bytes)))); socket.on('error', () => {});
    await once(socket, 'open');
    const identity = { game_instance_id: instance, bridge_boot_id: boot, connection_generation: generation };
    let messageIndex = 0;
    const send = (type, payload) => socket.send(JSON.stringify({ protocol_version: '1.0', type,
      message_id: 'fixture-' + (++messageIndex), ...identity, sent_at: new Date(wall).toISOString(), payload }));
    const capabilities = structuredClone(samples.capabilities.value); capabilities.game_instance_id = instance;
    Object.assign(capabilities.features, features);
    if (itemUses) capabilities.item_uses = [...itemUses];
    send('hello', { capabilities, mode: 'PAUSED', control_epoch: 7, world_session_id: 'world-session-example-001' });
    const game = { socket, messages, send, identity,
      observation: { ...structuredClone(samples['bridge-snapshot'].value.payload), ...identity, seq: 1,
        mode: 'PAUSED', control_epoch: 7, automation_ready: false, lease_remaining_ms: null },
      snapshot(patch = {}) { Object.assign(this.observation, patch); send('snapshot', this.observation); },
      next(type, predicate = () => true) { return until(() => messages.find(m => m.type === type && predicate(m))); },
      heartbeat(seq, patch = {}) { send('heartbeat', { heartbeat_seq: seq, controller_session_id: manager.controllerId,
        control_epoch: manager.state.value.control_epoch, last_seq: manager.state.value.seq,
        lease_id: manager.lease?.id || null, grant_seq: null, automation_ready: !!manager.lease, ...patch }); },
      async auto(requestId = 'auto-fixture') {
        const response = await api('/control', { request_id: requestId, target_mode: 'AUTO', reason: 'fixture_explicit_auto',
          bridge_boot_id: boot, world_session_id: this.observation.world_session_id, expected_control_epoch: manager.state.value.control_epoch });
        if (response.status !== 202) throw new Error(JSON.stringify(response));
        const request = await this.next('control_request', m => m.payload.operation_id === response.value.operation_id);
        const result = { operation_id: response.value.operation_id, request_id: requestId, world_session_id: this.observation.world_session_id,
          mode: 'AUTO', control_epoch: manager.state.value.control_epoch + 1, inputs_released: true, automation_ready: false,
          lease_id: 'lease-fixture-' + requestId, heartbeat_seq: 1, error: null };
        send('control_result', result);
        const grant = await this.next('lease_grant', m => m.payload.control_epoch === result.control_epoch);
        send('control_result', { ...result, inputs_released: true, automation_ready: true });
        await until(() => manager.operation(response.value.operation_id).state === 'succeeded');
        Object.assign(this.observation, { mode: 'AUTO', control_epoch: result.control_epoch, automation_ready: true,
          lease_remaining_ms: 3000, seq: this.observation.seq + 1 }); this.snapshot();
        await until(() => manager.state.value.seq === this.observation.seq);
        return { operation: response.value, request, grant, result };
      },
      request(goal = { skill: 'gather', item_id: 'minecraft:oak_log', count: 4 }, requestId = 'task-fixture') {
        const state = manager.state.view(); return { request_id: requestId, bridge_boot_id: state.bridge_boot_id,
          world_session_id: state.world_session_id, expected_control_epoch: state.control_epoch, based_on_seq: state.seq,
          accept_within_ms: 1500, max_duration_ms: 120000, goal };
      } };
    games.push(game);
    if (!helloOnly) {
      let phase = 'hello_ack';
      try {
        await game.next('hello_ack'); phase = 'first_snapshot'; game.snapshot();
        await until(() => {
          if (manager.faulted || socket.readyState >= 2) throw Error('fixture game connection failed before first fresh snapshot');
          return manager.state.view().freshness === 'fresh';
        });
      } catch (error) {
        const state = manager.state.view(), diagnostic = { classification: 'LOCAL_FIXTURE_CONNECTION_FAILURE_NOT_RUNTIME_ACCEPTANCE', phase,
          health: manager.healthView(), state: Object.fromEntries(['connected','freshness','age_ms','seq','view_revision'].map(key => [key, state[key]])),
          socket_ready_state: socket.readyState, received_message_types: messages.map(message => message.type), requested_snapshot_seq: game.observation.seq };
        const folder = resolve(process.env.MC_GAME_DIAGNOSTIC_ROOT || join(output, 'connection-diagnostics'));
        try { mkdirSync(folder, { recursive: true }); const path = join(folder, 'connection-' + Date.now() + '-' + randomUUID() + '.json');
          writeFileSync(path, JSON.stringify(diagnostic, null, 2) + '\n', { flag: 'wx' }); error.connection_diagnostic = path;
        } catch { /* retain the original connection failure */ }
        throw error;
      }
    }
    return game;
  };
  return { folder, get manager() { return manager; }, bridge, base, api, connect,
    platformEvent(patch = {}) { const now = manager.wall(), event = { platform: 'bilibili', room_id: '100', type: 'comment', user_key: 'fixture-viewer',
      event_key: 'audience-' + audienceMessages.size, occurred_at: now, received_at: now, hidden: false, test: false, ...patch };
      audienceMessages.set(event.event_key, event); manager.acceptPlatformEvent(event); return event; },
    async restartHost() { await manager.close(); manager = new GameManager(folder, bridge, managerOptions); bridge.game = manager; manager.start(); return manager; },
    advance(ms) { mono += ms; wall += ms; },
    async close() {
      for (const game of games) game.socket.terminate(); await manager.close();
      const closed = new Promise(r => server.close(r));
      // HTTP shutdown does not include upgraded sockets. Close the listener first, then every fixture-owned socket.
      for (const socket of sockets) socket.destroy();
      server.closeAllConnections(); await closed;
      const path = relative(output, folder); if (!path || path.startsWith('..') || resolve(folder) === resolve(output)) throw new Error('unsafe test cleanup');
      rmSync(folder, { recursive: true, force: true });
    } };
}
