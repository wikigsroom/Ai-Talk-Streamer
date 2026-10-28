import { EventEmitter } from 'node:events';
import { mkdtempSync, mkdirSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { join, resolve, extname } from 'node:path';
import { createServer } from 'node:http';
import { RoomManager } from '../backend/room/manager.mjs';
export const root = resolve(process.cwd());
export async function fixture({ generate } = {}) {
  const output = join(root, 'outputs/room-admin/tests'); mkdirSync(output, { recursive: true }); const folder = mkdtempSync(join(output, 'room-'));
  const accepted = [], cancelled = [], db = new EventEmitter(); let broadcast = null;
  const bridge = { db, ready: true, administration: { locked: false }, state: {
    current: () => broadcast, active: () => null,
    accept: (_p, body) => { if (!broadcast) { const e = new Error('BROADCAST_NOT_LIVE'); e.code = e.message; e.status = 409; throw e; } accepted.push(body); return { request_id: 'fixture-request-' + accepted.length, status: 'QUEUED' }; },
    cancel: (...args) => cancelled.push(args),
  }, auth: { resolve: () => ({ role: 'operator' }) }, tick: async () => {}, health: () => ({ persona_injection_ready: true }), channel: { snapshot: () => ({ model: 'fixture', revision: 'fixture' }) }, onCall: () => () => {}, host: { generate: generate || (async () => { await new Promise(r => setTimeout(r, 30)); return { text: '可以从今天的一件小事聊起。' }; }) } };
  const manager = new RoomManager(folder, bridge, { probe: async () => 2 }); bridge.room = manager;
  const manifest = JSON.parse(readFileSync(join(root, 'assets/room/bgm/manifest.json'), 'utf8'));
  for (const t of manifest.tracks) manager.store.run('INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?,?)', t.id, t.name, join(root, t.path), 'audio/wav', t.duration, t.bytes, t.sha256, 1, t.position);
  manager.music.track_id = manifest.tracks[0].id; manager.start();
  bridge.platforms = { player: { consumer_id: 'fixture-program', at: Date.now() } };
  const send = (res, value, status = 200) => { if (res.headersSent) return; res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(value)); };
  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, 'http://localhost'), path = url.pathname;
      if (path.startsWith('/api/dsh/room/')) return await manager.handle(req, res, url, (v, s) => send(res, v, s));
      if (path === '/api/studio/status') return send(res, { ready: true, avatar_ready: true, voice: { voice_id: 'O07', engine: 'OmniVoice', workers: { F07: { ready: true } } } });
      if (path === '/api/dsh/status') return send(res, { health: { persona_injection_ready: true, memory_ready: true }, queued: [] });
      if (path === '/api/dsh/platforms/status') return send(res, { output_player: { connected: true, receiver_id: 'fixture-receiver', audio_state: 'running', width: 720, height: 1280 } });
      if (path === '/api/dsh/platforms/bilibili/start' || path.endsWith('/resume')) { broadcast = { broadcast_id: 'fixture-broadcast', state: 'LIVE', revision: 1 }; manager.emit(); return send(res, { started: true, public_broadcast_started: false }); }
      if (path === '/api/dsh/platforms/bilibili/stop') { broadcast = null; manager.emit(); return send(res, { stopped: true }); }
      if (path === '/character/reference.png') { res.writeHead(200, { 'Content-Type': 'image/png' }); res.end(readFileSync(join(root, 'assets/vertical/student-dorm-720x1280.png'))); return; }
      const file = path === '/admin' ? 'web/admin.html' : path === '/overlay' ? 'web/room-overlay.html' : path === '/output.html' ? 'integration/obs.html' : 'web' + path;
      const target = resolve(root, file);
      if (!target.startsWith(root) || !existsSync(target) || path.includes('..')) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { 'Content-Type': { '.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.css': 'text/css' }[extname(target)] || 'application/octet-stream' }); res.end(readFileSync(target));
    } catch (error) { send(res, { error: error.code || error.message }, error.status || 500); }
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = 'http://127.0.0.1:' + server.address().port;
  const post = async (path, body) => { const r = await fetch(base + '/api/dsh/room/' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); return { status: r.status, value: await r.json() }; };
  return { manager, bridge, base, post, accepted, cancelled, folder, async close() { await manager.close(); server.closeAllConnections(); await new Promise(r => server.close(r)); rmSync(folder, { recursive: true, force: true }); } };
}
