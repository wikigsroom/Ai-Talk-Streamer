import { join, resolve } from 'node:path';
import { existsSync, readFileSync } from 'node:fs';
import { unlink } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { RoomStore } from './store.mjs';
import { DEFAULTS, FILTERS, patchSettings, check, isBlocked } from './defaults.mjs';
import { sendAudio, uploadAudio } from './media.mjs';

const keyFor = e => e.user_id ? createHash('sha256').update(JSON.stringify([e.platform, e.room_id, e.user_id])).digest('hex') : null;
const cleanTrack = ({ path: _path, ...track }) => ({ ...track, url: '/api/dsh/room/audio/' + track.id });
export class RoomManager {
  constructor(root, bridge, { now = () => Date.now(), store, probe } = {}) {
    this.root = resolve(root); this.bridge = bridge; this.now = now; this.store = store || new RoomStore(join(root, 'state/live-room/control.sqlite3')); this.probe = probe;
    this.clients = new Set(); this.sequence = 0; this.epoch = randomUUID(); this.closed = false; this.uploading = false; this.player = null;
    this.music = { track_id: null, playing: false, position: 0, anchor_at: now(), repeat: 'one', shuffle: false, version: 1, ...this.store.get('music', {}) };
    // Restarts never resume music unexpectedly in a running official client.
    this.music.playing = false; this.music.anchor_at = now(); this.music.version++;
    this.board = this.store.get('board', { pinned_id: null, featured_id: null });
    this.agentSession = this.store.get('agent_session', 'operator-' + randomUUID()); this.agentJob = null;
    this.seedTracks(); if (!this.track(this.music.track_id)) this.music.track_id = this.tracks()[0]?.id || null;
    this.persistMusic(); this.store.put('agent_session', this.agentSession);
    this.stateChanged = event => {
      if (this.closed) return;
      if (event.event_type === 'utterance.text_ready') {
        const payload = this.bridge.db.payload(event.event_seq);
        this.caption = { request_id: event.request_id, text: String(payload.text || '').slice(0, 1000) };
      }
      if (event.event_type.startsWith('broadcast.') || /text_ready|completed|cancelled|interrupted|failed/.test(event.event_type)) {
        clearTimeout(this.stateTimer); this.stateTimer = setTimeout(() => this.emit(), 30);
      }
    };
    this.bridge.db?.on('event', this.stateChanged);
  }
  start() {
    this.timer = setInterval(() => this.tick(), 1000); this.timer.unref();
    this.heartbeat = setInterval(() => { for (const res of this.clients) if (!res.write(': heartbeat\n\n')) this.drop(res); }, 15000); this.heartbeat.unref();
    this.pruneTimer = setInterval(() => this.store.prune(this.now()), 3600000); this.pruneTimer.unref(); return this;
  }
  seedTracks() {
    const manifest = join(this.root, 'assets/room/bgm/manifest.json'); if (!existsSync(manifest)) return;
    for (const item of JSON.parse(readFileSync(manifest, 'utf8')).tracks) {
      const path = resolve(this.root, item.path); check(path.startsWith(this.root + (process.platform === 'win32' ? '\\' : '/')), 'BGM_MANIFEST_PATH');
      if (!existsSync(path)) continue;
      this.store.run('INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,path=excluded.path,duration=excluded.duration,bytes=excluded.bytes,sha256=excluded.sha256', item.id, item.name, path, 'audio/wav', item.duration, item.bytes, item.sha256, 1, item.position);
    }
  }
  track(id) { return this.store.one('SELECT * FROM tracks WHERE id=?', id || ''); }
  tracks() { return this.store.all('SELECT * FROM tracks ORDER BY position,id').map(cleanTrack); }
  position() { const duration = this.track(this.music.track_id)?.duration || 0; let p = this.music.position + (this.music.playing ? (this.now() - this.music.anchor_at) / 1000 : 0); if (this.music.repeat === 'one' && duration) p %= duration; return Math.min(duration, Math.max(0, p)); }
  persistMusic() { this.store.put('music', this.music); }
  audit(action, value) { this.store.log(action, value, this.now()); }
  publicMessage(e) { return { id: e.event_key || randomUUID(), event_key: e.event_key || null, platform: e.platform || 'operator', room_id: e.room_id || '', type: e.type || 'note', notice_kind: e.notice_kind || '', nickname: String(e.nickname || '导播').slice(0, 80), text: String(e.text || '').slice(0, 1500), user_key: e.user_key || keyFor(e), gift_name: String(e.gift_name || '礼物').slice(0, 80), gift_count: Number.isFinite(e.gift_count) ? e.gift_count : 1, received_at: this.now(), occurred_at: e.occurred_at || this.now(), test: !!e.test, hidden: false, answered: false }; }
  blocked(e) { return isBlocked(this.store.settings, { ...e, user_key: e.user_key || keyFor(e) }); }
  acceptPlatformEvent(event) {
    if (this.closed || !['comment', 'gift', 'follow', 'fansclub', 'enter', 'note'].includes(event.type)) return;
    const message = this.publicMessage(event), hidden = this.blocked(message);
    const result = this.store.run('INSERT OR IGNORE INTO messages(id,event_key,received_at,value,hidden) VALUES (?,?,?,?,?)', message.id, message.event_key, message.received_at, JSON.stringify(message), hidden ? 1 : 0);
    if (!result.changes) return;
    if (!hidden && this.store.settings.overlay.auto_board && message.type === 'comment' && !this.board.featured_id) this.setBoard({ featured_id: message.id });
    this.emit('message', { ...message, hidden });
  }
  setBoard(patch) { this.board = { ...this.board, ...patch }; this.store.put('board', this.board); }
  boardMessage(id) { const m = this.store.message(id); return m && !m.hidden && !this.blocked(m) ? m : null; }
  snapshot({ messages = true } = {}) {
    const current = this.bridge.state?.current?.();
    return { schema_version: 1, version: 'room-v1.2', epoch: this.epoch, sequence: this.sequence, server_time: this.now(), revision: this.store.revision, settings: this.store.settings, presets: FILTERS,
      music: { ...this.music, position: this.position() }, tracks: this.tracks(), board: { ...this.board, pinned: this.boardMessage(this.board.pinned_id), featured: this.boardMessage(this.board.featured_id) },
      ...(messages ? { messages: this.store.recent(100).map(m => ({ ...m, blocked: this.blocked(m) })) } : {}),
      agent: { session: this.agentSession, job: this.agentJob ? { ...this.agentJob, controller: undefined } : null },
      player: this.player ? { ...this.player, connected: this.now() - this.player.at < 7000 } : null,
      broadcast: current ? { broadcast_id: current.broadcast_id, state: current.state, revision: current.revision } : null,
      active: this.bridge.state?.active?.() ? { request_id: this.bridge.state.active().request_id, status: this.bridge.state.active().status } : null, caption: this.caption || null,
      storage_error: this.lastError || null, authentication_required: false, public_broadcast_control: 'official_client_only' };
  }
  emit(type = 'state', value) {
    if (this.closed) return; this.sequence++;
    const packet = `id: ${this.epoch}:${this.sequence}\nevent: ${type}\ndata: ${JSON.stringify(value || this.snapshot({ messages: false }))}\n\n`;
    for (const res of this.clients) if (res.writableLength > 256 * 1024 || !res.write(packet)) this.drop(res);
  }
  drop(res) { this.clients.delete(res); res.end(); }
  subscribe(req, res) {
    check(this.clients.size < 24, 'ROOM_EVENT_CLIENT_LIMIT', 503);
    res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' });
    // Reconnect always sends an authoritative snapshot. Old gifts are not replayed.
    res.write(`retry: 2500\nevent: snapshot\ndata: ${JSON.stringify(this.snapshot())}\n\n`);
    this.clients.add(res); req.on('close', () => this.clients.delete(res));
  }
  async body(req) {
    const chunks = []; let bytes = 0; for await (const chunk of req) { bytes += chunk.length; check(bytes <= 128 * 1024, 'ROOM_BODY_TOO_LARGE', 413); chunks.push(chunk); }
    try { const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {}; check(body && typeof body === 'object' && !Array.isArray(body), 'ROOM_BODY_INVALID'); return body; } catch (e) { if (e.code) throw e; check(false, 'ROOM_JSON_INVALID'); }
  }
  configure(body) {
    check(body.expected_revision === this.store.revision, 'ROOM_CONFIG_CONFLICT_REFRESH', 409);
    const settings = patchSettings(this.store.settings, body.patch);
    this.store.saveSettings(settings); this.audit('config', { groups: Object.keys(body.patch), revision: this.store.revision }); this.emit(); return this.snapshot();
  }
  musicControl(body) {
    check(['play', 'pause', 'seek', 'next', 'previous', 'repeat', 'shuffle', 'order'].includes(body.action), 'MUSIC_ACTION_INVALID');
    this.music.position = this.position(); this.music.anchor_at = this.now();
    if (body.action === 'play') {
      if (body.track_id && body.track_id !== this.music.track_id) { check(this.track(body.track_id), 'TRACK_NOT_FOUND', 404); this.music.track_id = body.track_id; this.music.position = 0; }
      check(this.track(this.music.track_id), 'TRACK_NOT_FOUND', 404); this.music.playing = true;
    } else if (body.action === 'pause') this.music.playing = false;
    else if (body.action === 'seek') { check(typeof body.seconds === 'number' && Number.isFinite(body.seconds) && body.seconds >= 0 && body.seconds <= (this.track(this.music.track_id)?.duration || 0), 'MUSIC_SEEK_INVALID'); this.music.position = body.seconds; }
    else if (['next', 'previous'].includes(body.action)) {
      const rows = this.tracks(); check(rows.length, 'PLAYLIST_EMPTY'); const i = rows.findIndex(t => t.id === this.music.track_id);
      const next = this.music.shuffle && rows.length > 1 ? (i + 1 + Math.floor(Math.random() * (rows.length - 1))) % rows.length : (i + (body.action === 'next' ? 1 : -1) + rows.length) % rows.length;
      this.music.track_id = rows[next].id; this.music.position = 0;
    } else if (body.action === 'repeat') { check(['one', 'all', 'off'].includes(body.value), 'MUSIC_REPEAT_INVALID'); this.music.repeat = body.value; }
    else if (body.action === 'shuffle') { check(typeof body.value === 'boolean', 'MUSIC_SHUFFLE_INVALID'); this.music.shuffle = body.value; }
    else if (body.action === 'order') {
      const ids = this.tracks().map(t => t.id); check(Array.isArray(body.ids) && body.ids.length === ids.length && new Set(body.ids).size === ids.length && body.ids.every(id => ids.includes(id)), 'PLAYLIST_ORDER_INVALID');
      this.store.transaction(() => body.ids.forEach((id, i) => this.store.run('UPDATE tracks SET position=? WHERE id=?', i, id)));
    }
    this.music.version++; this.persistMusic(); this.audit('music.' + body.action, { track_id: this.music.track_id }); this.emit(); return this.snapshot();
  }
  tick() {
    try {
      const track = this.track(this.music.track_id);
      if (this.music.playing && track && this.music.repeat !== 'one' && this.music.position + (this.now() - this.music.anchor_at) / 1000 >= track.duration) {
        const tracks = this.tracks(), last = tracks.at(-1)?.id === track.id;
        if (this.music.repeat === 'off' && last && !this.music.shuffle) this.musicControl({ action: 'pause' }); else this.musicControl({ action: 'next' });
      }
    } catch (error) { this.lastError = error.code || 'ROOM_STORAGE_ERROR'; }
  }
  messageControl(body) {
    check(['create', 'pin', 'unpin', 'feature', 'unfeature', 'hide', 'restore', 'answered', 'next', 'clear_tests'].includes(body.action), 'MESSAGE_ACTION_INVALID');
    if (body.action === 'create') {
      check(typeof body.text === 'string' && body.text.trim() && body.text.length <= 300 && (!body.nickname || typeof body.nickname === 'string' && body.nickname.length <= 60), 'MESSAGE_TEXT_INVALID');
      const message = this.publicMessage({ text: body.text.trim(), nickname: body.nickname || '导播留言', type: 'note', test: !!body.test });
      this.store.run('INSERT INTO messages(id,event_key,received_at,value) VALUES (?,?,?,?)', message.id, null, message.received_at, JSON.stringify(message)); this.emit('message', message);
      if (body.feature === true) this.setBoard({ featured_id: message.id });
    } else if (body.action === 'unpin') this.setBoard({ pinned_id: null });
    else if (body.action === 'unfeature') this.setBoard({ featured_id: null });
    else if (body.action === 'clear_tests') {
      for (const m of this.store.recent(5000).filter(m => m.test)) this.store.run('DELETE FROM messages WHERE id=?', m.id);
      for (const k of ['pinned_id', 'featured_id']) if (!this.store.message(this.board[k])) this.setBoard({ [k]: null });
    } else if (body.action === 'next') {
      const messages = this.store.recent(200).filter(m => !m.hidden && !m.answered && !this.blocked(m) && ['note', 'comment'].includes(m.type));
      const old = this.board.featured_id; if (old) this.store.run('UPDATE messages SET answered=1 WHERE id=?', old);
      this.setBoard({ featured_id: messages.find(m => m.id !== old)?.id || null });
    } else {
      const m = this.store.message(body.id); check(m, 'MESSAGE_NOT_FOUND', 404);
      if (body.action === 'pin' || body.action === 'feature') { check(!m.hidden && !this.blocked(m), 'MESSAGE_HIDDEN'); this.setBoard({ [body.action === 'pin' ? 'pinned_id' : 'featured_id']: m.id }); }
      else if (body.action === 'answered') this.store.run('UPDATE messages SET answered=1 WHERE id=?', m.id);
      else this.store.run('UPDATE messages SET hidden=? WHERE id=?', body.action === 'hide' ? 1 : 0, m.id);
    }
    this.audit('message.' + body.action, { id: body.id || null }); this.emit('snapshot', this.snapshot()); return this.snapshot();
  }
  speak(body) {
    check(typeof body.text === 'string' && body.text.trim() && body.text.length <= 1000, 'SPEECH_TEXT_INVALID');
    check(['echo', 'chat'].includes(body.mode || 'echo'), 'SPEECH_MODE_INVALID');
    check(this.bridge.ready && !this.bridge.administration?.locked, 'BRIDGE_NOT_READY', 503);
    if (body.mode === 'chat') check(this.bridge.health().persona_injection_ready, 'CHANNEL_COMPATIBILITY_REQUIRED', 503);
    const request = this.bridge.state.accept(this.bridge.auth.resolve(), { text: body.text.trim(), mode: body.mode || 'echo', idempotency_key: 'room-' + (typeof body.idempotency_key === 'string' && body.idempotency_key.length <= 100 ? body.idempotency_key : randomUUID()), public_input: true });
    if (body.message_id && this.store.message(body.message_id)) this.store.run('UPDATE messages SET answered=1 WHERE id=?', body.message_id);
    this.audit('speech.queued', { request_id: request.request_id, mode: body.mode || 'echo' }); void this.bridge.tick(); this.emit(); return request;
  }
  agentHistory() { return this.store.all('SELECT at,role,text FROM agent WHERE session=? ORDER BY seq DESC LIMIT 40', this.agentSession).reverse(); }
  async agentControl(body) {
    check(['ask', 'cancel', 'new'].includes(body.action), 'AGENT_ACTION_INVALID');
    if (body.action === 'cancel' || body.action === 'new') {
      this.agentJob?.controller?.abort(); if (this.agentJob?.status === 'RUNNING') this.agentJob.status = 'CANCELLED';
      if (body.action === 'new') { this.agentSession = 'operator-' + randomUUID(); this.store.put('agent_session', this.agentSession); this.agentJob = null; }
      this.audit('agent.' + body.action, {}); this.emit(); return this.snapshot();
    }
    check(this.agentJob?.status !== 'RUNNING', 'AGENT_BUSY', 409);
    check(typeof body.text === 'string' && body.text.trim() && body.text.length <= 2000, 'AGENT_TEXT_INVALID');
    check(this.bridge.ready && !this.bridge.administration?.locked, 'BRIDGE_NOT_READY', 503);
    const controller = new AbortController(), session = this.agentSession, job = { id: randomUUID(), status: 'RUNNING', started_at: this.now(), controller };
    this.store.run('INSERT INTO agent(session,at,role,text) VALUES (?,?,?,?)', session, this.now(), 'user', body.text.trim()); this.agentJob = job;
    this.emit(); void this.generateAgent(job, session, body.text.trim()); return this.snapshot();
  }
  async generateAgent(job, session, text) {
    try {
      const context = JSON.stringify({ task: '这是主播与导播之间的私下对话，不向观众播报。保持林知夏人格，协助规划话题、解释当前房间设置。不得声称已操作后台。不要记忆观众资料。', operator_history: this.agentHistory().slice(-12), room: { title: this.store.settings.identity.title, topic: this.store.settings.identity.topic, music_playing: this.music.playing, muted: this.store.settings.audio.muted }, humanity_public_snapshot: { text: '本次为导播私聊；无观众记忆注入，不生成观众记忆候选。', memory_ids: [], mirror_revision: 0 } });
      const timeout = this.bridge.policy?.conversation?.model_timeout_ms || 90000;
      // Chat history belongs to the stable operator session; the pinned DSH
      // per-request host needs a fresh native agent/session for every turn.
      const result = await this.bridge.host.generate({ sessionId: session + '-turn-' + job.id, snapshot: this.bridge.channel.snapshot(), input: text, context, signal: AbortSignal.any([job.controller.signal, AbortSignal.timeout(timeout)]), maxTokens: 384,
        tools: async () => ({ public: [], viewer: [], private_operator_conversation: true, memory_write_enabled: false }), onCall: this.bridge.onCall({ maxTokens: 384 }) });
      if (this.closed || job.controller.signal.aborted || this.agentJob !== job || session !== this.agentSession) return;
      check(typeof result.text === 'string' && result.text.trim(), 'AGENT_EMPTY_REPLY', 502);
      const reply = result.text.slice(0, 4000); this.store.run('INSERT INTO agent(session,at,role,text) VALUES (?,?,?,?)', session, this.now(), 'assistant', reply);
      job.status = 'COMPLETED'; job.finished_at = this.now(); this.audit('agent.completed', { id: job.id, elapsed_ms: job.finished_at - job.started_at });
    } catch (error) {
      if (this.closed) return; job.status = job.controller.signal.aborted ? 'CANCELLED' : 'FAILED'; job.error = error.code || (error.name === 'TimeoutError' ? 'AGENT_TIMEOUT' : 'AGENT_PROVIDER_UNAVAILABLE'); job.finished_at = this.now(); this.audit('agent.' + job.status.toLowerCase(), { id: job.id, error: job.error || null });
    } finally { if (!this.closed) this.emit('agent', { ...this.snapshot({ messages: false }), history: this.agentHistory() }); }
  }
  playerFeedback(body) {
    // Only the existing official output consumer may report program mixer state.
    const player = this.bridge.platforms?.player;
    check(player && player.consumer_id === body.consumer_id && this.now() - player.at < 7000, 'ROOM_PLAYER_NOT_PROGRAM', 409);
    const safe = { consumer_id: body.consumer_id, at: this.now(), track_id: typeof body.track_id === 'string' ? body.track_id.slice(0, 80) : null, audio_state: ['running', 'suspended', 'closed'].includes(body.audio_state) ? body.audio_state : 'unknown', music_playing: body.music_playing === true, ducked: body.ducked === true, muted: body.muted === true, error: typeof body.error === 'string' ? body.error.slice(0, 120) : null };
    safe.speaking_request_id = typeof body.speaking_request_id === 'string' ? body.speaking_request_id.slice(0, 100) : null;
    for (const key of ['current_time', 'music_gain', 'speech_gain', 'speech_progress', 'config_revision']) if (typeof body[key] === 'number' && Number.isFinite(body[key]) && body[key] >= 0 && body[key] <= (key === 'speech_progress' ? 1 : 1e12)) safe[key] = body[key];
    this.player = safe; return { accepted: true, server_time: this.now() };
  }
  async handle(req, res, url, send) {
    const path = url.pathname.slice('/api/dsh/room'.length);
    if (path.startsWith('/audio/') && ['GET', 'HEAD'].includes(req.method)) return sendAudio(req, res, this.track(path.slice(7)));
    if (path === '/events' && req.method === 'GET') return this.subscribe(req, res);
    if (path === '/state' && req.method === 'GET') return send(this.snapshot());
    if (path === '/agent' && req.method === 'GET') return send({ history: this.agentHistory(), ...this.snapshot({ messages: false }).agent });
    if (path === '/audit' && req.method === 'GET') return send({ audit: this.store.all('SELECT * FROM audit ORDER BY seq DESC LIMIT 100').map(r => ({ ...r, detail: JSON.parse(r.detail) })) });
    if (path === '/export' && req.method === 'GET') return send({ schema_version: 1, settings: this.store.settings, exported_at: this.now() });
    if (path === '/tracks/upload' && req.method === 'POST') {
      check(!this.uploading, 'AUDIO_UPLOAD_BUSY', 409); check(this.tracks().length < 103, 'AUDIO_LIBRARY_LIMIT'); this.uploading = true;
      try { const track = await uploadAudio(this.root, req, url.searchParams.get('name'), this.probe); this.store.run('INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?,?)', track.id, track.name, track.path, track.mime, track.duration, track.bytes, track.sha256, 0, this.tracks().length); this.audit('track.upload', { id: track.id, bytes: track.bytes }); this.emit(); return send(cleanTrack(track), 201); }
      finally { this.uploading = false; }
    }
    check(req.method === 'POST', 'ROOM_ROUTE_NOT_FOUND', 404); const body = await this.body(req);
    if (path === '/config') return send(this.configure(body));
    if (path === '/import') { check(body.schema_version === 1, 'ROOM_IMPORT_SCHEMA'); return send(this.configure({ expected_revision: body.expected_revision, patch: body.settings })); }
    if (path === '/reset') return send(this.configure({ expected_revision: body.expected_revision, patch: DEFAULTS }));
    if (path === '/music') return send(this.musicControl(body));
    if (path === '/messages') return send(this.messageControl(body));
    if (path === '/speak') return send(this.speak(body), 202);
    if (path === '/agent') return send(await this.agentControl(body), 202);
    if (path === '/player') return send(this.playerFeedback(body));
    if (path === '/tracks/delete') {
      const track = this.track(body.id); check(track && !track.builtin, 'BUILTIN_TRACK_CANNOT_DELETE');
      if (this.music.track_id === track.id) { this.musicControl({ action: 'pause' }); this.music.track_id = this.tracks().find(t => t.id !== track.id)?.id || null; this.music.position = 0; this.persistMusic(); }
      this.store.run('DELETE FROM tracks WHERE id=?', track.id); await unlink(track.path).catch(() => {}); this.audit('track.delete', { id: track.id }); this.emit(); return send(this.snapshot());
    }
    if (path === '/test-event') {
      check(['comment', 'gift', 'follow'].includes(body.type), 'TEST_EVENT_TYPE_INVALID');
      const event = { event_key: 'test-' + randomUUID(), platform: 'custom', room_id: 'local-preview', nickname: '本地测试', type: body.type, text: typeof body.text === 'string' ? body.text.slice(0, 300) : '知夏，今天有什么开心的小事？', gift_name: '小星星', gift_count: 3, test: true }; this.acceptPlatformEvent(event); this.audit('test.' + body.type, {}); return send({ created: true, test: true });
    }
    if (path === '/panic') {
      const queued = this.bridge.state.status?.().queued || [];
      for (const request of queued) this.bridge.state.cancel(request.request_id, 'operator_room_panic');
      const active = this.bridge.state.active?.(); if (active) this.bridge.state.cancel(active.request_id, 'operator_room_panic');
      this.musicControl({ action: 'pause' }); this.store.saveSettings(patchSettings(this.store.settings, { audio: { muted: true } })); this.audit('panic', { cancelled: active?.request_id || null, cancelled_queue: queued.map(r => r.request_id) }); this.emit(); return send(this.snapshot());
    }
    check(false, 'ROOM_ROUTE_NOT_FOUND', 404);
  }
  async close() {
    if (this.closed) return; this.closed = true; clearInterval(this.timer); clearInterval(this.heartbeat); clearInterval(this.pruneTimer); clearTimeout(this.stateTimer); this.bridge.db?.off('event', this.stateChanged);
    this.agentJob?.controller?.abort(); for (const res of this.clients) this.drop(res);
    this.music.position = this.position(); this.music.playing = false; this.persistMusic(); this.store.prune(this.now()); this.store.close();
  }
}
