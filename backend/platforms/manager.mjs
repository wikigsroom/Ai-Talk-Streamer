import { join } from 'node:path';
import { PlatformConfig, PlatformError, PLATFORM_IDS, check } from './config.mjs';
import { PlatformStore } from './store.mjs';
import { normalizeEvent, eventPrincipal } from './events.mjs';
import { ObsClient } from './obs.mjs';
import { LivehimeOutput } from './livehime.mjs';
import { BilibiliOpenAdapter } from './bilibili.mjs';
import { BrowserChatAdapter } from './browser.mjs';
import { RelayAdapter } from './relay.mjs';
import { BliveDmAdapter } from './blivedm.mjs';
import { verifyDouyin } from './douyin.mjs';
import { ACTIVE_REQUESTS, TERMINAL_REQUESTS } from '../dsh-bridge/state.mjs';
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const ACTIVE_OUTPUTS = ['STARTING', 'STREAMING', 'COMPANION_READY', 'MANUAL_LIVE'];

export class PlatformManager {
  constructor(root, bridge, { store, config, obs, livehime, now = () => Date.now() } = {}) {
    this.root = root; this.bridge = bridge; this.now = now; this.config = config || new PlatformConfig(root); this.store = store || new PlatformStore(join(root, 'state/platforms/control.sqlite3'), now); this.obs = obs || new ObsClient(root, this.config);
    this.livehime = livehime || new LivehimeOutput(root, { receiverConfig: () => this.config.value.platforms.bilibili });
    this.collectors = new Map(); this.collectorStatus = {}; this.cooldowns = new Map(); this.lastReply = 0; this.controlChain = Promise.resolve(); this.wantOutputAuthority = false; this.closed = false;
  }
  start() { this.timer = setInterval(() => { void this.dispatch().catch(() => this.store.count('dispatch_errors')); }, 1000); this.timer.unref(); this.pruneTimer = setInterval(() => this.store.prune(), 3600000); this.pruneTimer.unref(); return this; }
  exclusive(work) { const result = this.controlChain.then(work); this.controlChain = result.catch(() => {}); return result; }
  async body(req) { let bytes=0;const chunks=[];for await(const chunk of req){bytes+=chunk.length;check(bytes<=1024*1024,'PLATFORM_BODY_TOO_LARGE',413);chunks.push(chunk);}try{return chunks.length?JSON.parse(Buffer.concat(chunks).toString('utf8')):{};}catch{throw new PlatformError('PLATFORM_JSON_INVALID',400);} }
  status() {
    return { access_mode: 'open', authentication_required: false, config: this.config.public(), collectors: this.collectorStatus, outputs: this.store.all('SELECT * FROM outputs'), counters: Object.fromEntries(this.store.all('SELECT * FROM counters').map(row => [row.name, row.value])), pending: this.store.get("SELECT COUNT(*) n FROM events WHERE status='PENDING'").n, events: this.store.recent(), output_player: this.player ? { consumer_id: this.player.consumer_id, last_seen: this.player.at, connected: this.now() - this.player.at < 6000, renderer: this.player.renderer, frames: this.player.frames, width: this.player.width, height: this.player.height, audio_state: this.player.audio_state, receiver_id: this.player.receiver_id || null, receiver_client_ready: !!this.player.receiver_client_ready } : null, broadcast: this.bridge.state.current() || null };
  }
  ingest(platform, payloads, options = {}) {
    check(!this.closed, 'PLATFORM_SERVICE_STOPPED', 503); const rows = Array.isArray(payloads) ? payloads : [payloads]; check(rows.length <= 1000, 'PLATFORM_BATCH_LIMIT');
    const results = [];
    this.store.db.exec('BEGIN IMMEDIATE');
    try {
      for (const payload of rows) {
        const event = normalizeEvent(platform, payload, { now: this.now(), ...options });
        let status = 'PENDING', reason = null;
        if (event.type !== 'comment') { status = 'OBSERVED'; reason = 'not_a_comment'; }
        if (event.type === 'comment' && !event.text) { status = 'IGNORED'; reason = 'empty_comment'; }
        if (!this.config.value.interaction.enabled) { status = 'IGNORED'; reason = 'interaction_disabled'; }
        if (this.now() - event.occurred_at > this.config.value.interaction.ttl_ms) { status = 'EXPIRED'; reason = 'event_ttl'; }
        if (status === 'PENDING' && this.store.get("SELECT COUNT(*) n FROM events WHERE status='PENDING'").n >= this.config.value.interaction.max_pending) { status = 'DROPPED'; reason = 'event_queue_full'; this.store.count('overload_drops'); }
        const added = this.store.insert(event, status, reason); results.push({ event_key: event.event_key, duplicate: !added, status });
      }
      this.store.db.exec('COMMIT');
    } catch (error) { this.store.db.exec('ROLLBACK'); throw error; }
    return { accepted: results.length, results };
  }
  async dispatch() {
    if (this.closed || this.dispatching) return; this.dispatching = true;
    try {
      const policy = this.config.value.interaction;
      this.store.run("UPDATE events SET status='EXPIRED',reason='event_ttl' WHERE status='PENDING' AND occurred_at<?", this.now() - policy.ttl_ms);
      const observedStates = ['QUEUED', ...ACTIVE_REQUESTS].map(value => "'"+value+"'").join(',');
      for (const event of this.store.all(`SELECT * FROM events WHERE request_id IS NOT NULL AND status IN (${observedStates}) LIMIT 100`)) {
        const request = this.bridge.state.request(event.request_id);
        if (request && TERMINAL_REQUESTS.includes(request.status)) this.store.run('UPDATE events SET status=? WHERE event_key=?', request.status, event.event_key);
        else if (request && event.status!=='QUEUED') this.store.run("UPDATE events SET status='QUEUED' WHERE event_key=?",event.event_key);
      }
      if (!policy.enabled || !this.bridge.ready || this.bridge.administration.locked || this.bridge.state.current()?.state !== 'LIVE' || !this.bridge.state.authorityReady(this.bridge.state.current().broadcast_id) || this.bridge.state.active() || this.bridge.state.status().queued.length || this.now() - this.lastReply < policy.minimum_interval_ms) return;
      if (policy.mode === 'chat' && !this.bridge.health().persona_injection_ready) return;
      const rows = this.store.all("SELECT * FROM events WHERE status='PENDING' ORDER BY received_at,rowid LIMIT 50");
      for (const event of rows) {
        const principal = eventPrincipal(event), last = this.cooldowns.get(principal.principal_id) || 0;
        if (last && this.now() - last < policy.viewer_cooldown_ms) { this.store.run("UPDATE events SET status='IGNORED',reason='viewer_cooldown' WHERE event_key=?", event.event_key); continue; }
        const key = 'platform-' + event.event_key;
        try {
          const request = this.bridge.state.accept(principal, { text: event.text, mode: policy.mode, idempotency_key: key, public_input: principal.public_input, source: { platform: event.platform, room_id: event.room_id, event_id: event.event_id, nickname: event.nickname, identity_quality: event.identity_quality, collector: event.source } });
          this.store.run("UPDATE events SET status='QUEUED',request_id=?,reason=NULL WHERE event_key=?", request.request_id, event.event_key);
          this.cooldowns.set(principal.principal_id, this.now()); this.lastReply = this.now(); this.store.count('replies_queued'); void this.bridge.tick();
        } catch (error) { if (error.code === 'QUEUE_FULL' || error.code === 'BROADCAST_NOT_LIVE') break; this.store.run("UPDATE events SET status='FAILED',reason=? WHERE event_key=?", error.code || 'ROUTING_FAILED', event.event_key); }
        break;
      }
      if (this.cooldowns.size > 10000) for (const [key, at] of this.cooldowns) if (this.now() - at > policy.viewer_cooldown_ms) this.cooldowns.delete(key);
    } finally { this.dispatching = false; }
  }
  async startCollector(platform, options = {}) {
    check(PLATFORM_IDS.includes(platform), 'PLATFORM_INVALID'); check(!this.collectors.has(platform), 'COLLECTOR_ALREADY_RUNNING');
    const config = this.config.value.platforms[platform];
    const callbacks = { onEvent: (data, info = {}) => { try { this.ingest(platform, data, { roomId: config.room_id, source: config.comment_mode, ...info }); } catch (error) { this.store.count('invalid_events'); this.collectorStatus[platform] = { ...this.collectorStatus[platform], last_error: error.code || 'EVENT_INVALID' }; } }, onState: (state, error = null, info = {}) => { this.collectorStatus[platform] = { state, error, ...info, updated_at: this.now() }; } };
    let adapter;
    if (config.comment_mode === 'browser') { check(platform !== 'custom', 'CUSTOM_BROWSER_NOT_SUPPORTED'); adapter = new BrowserChatAdapter(this.root, platform, config, callbacks); }
    else if (config.comment_mode === 'open_live') { check(platform === 'bilibili', 'PLATFORM_MODE_INVALID'); adapter = new BilibiliOpenAdapter(config, callbacks); }
    else if (config.comment_mode === 'relay') adapter = new RelayAdapter(config, callbacks);
    else if (config.comment_mode === 'blivedm') { check(platform==='bilibili','PLATFORM_MODE_INVALID'); adapter=new BliveDmAdapter(this.root,config,callbacks); }
    else if (config.comment_mode === 'official_callback') { check(platform === 'douyin' && config.callback_secret, 'DOUYIN_CALLBACK_NOT_CONFIGURED'); this.collectors.set(platform, { async stop() {} }); callbacks.onState('WAITING_FOR_CALLBACK'); return { state: 'WAITING_FOR_CALLBACK' }; }
    else throw new PlatformError('COLLECTOR_MODE_NOT_AVAILABLE');
    this.collectors.set(platform, adapter);
    try { await adapter.start(options); } catch (error) { this.collectors.delete(platform); throw error; }
    return this.collectorStatus[platform];
  }
  async stopCollector(platform) { const adapter = this.collectors.get(platform); this.collectors.delete(platform); await adapter?.stop(); this.collectorStatus[platform] = { state: 'STOPPED', updated_at: this.now() }; return { stopped: true }; }
  outputPlayer(body) {
    check(typeof body.consumer_id === 'string' && body.consumer_id.length <= 150, 'OUTPUT_PLAYER_INVALID');
    if (body.receiver_id !== undefined) check(typeof body.receiver_id === 'string' && /^[a-zA-Z0-9_-]{1,100}$/.test(body.receiver_id), 'RECEIVER_ID_INVALID');
    if (this.config.value.platforms.bilibili.client_location === 'receiver' && body.renderer === 'livehime' && !body.receiver_id) return { claim: false, ignored: true, receiver_required: true };
    const nativeActive = this.store.all('SELECT * FROM outputs').some(row => ACTIVE_OUTPUTS.includes(row.state) && this.config.value.platforms[row.platform]?.output_mode === 'livehime');
    const anyActive = this.store.all('SELECT * FROM outputs').some(row => ACTIVE_OUTPUTS.includes(row.state) || row.owned_output);
    const nativeConfigured = this.config.value.platforms.bilibili.output_mode === 'livehime';
    if ((nativeActive || nativeConfigured && !anyActive ? 'livehime' : 'obs') !== (body.renderer || 'obs')) return { claim: false, ignored: true };
    this.player = { consumer_id: body.consumer_id, at: this.now(), renderer: body.renderer || 'obs', frames: Number(body.frames) || 0, width: Number(body.width) || 0, height: Number(body.height) || 0, audio_state: String(body.audio_state || '').slice(0, 30) };
    if (body.receiver_id !== undefined) {
      this.player.receiver_id = body.receiver_id;
      this.player.receiver_client_ready = body.receiver_client_ready === true;
    }
    const broadcast = this.bridge.state.current();
    const lease = broadcast && this.bridge.db.get('SELECT * FROM playback_leases WHERE broadcast_id=?', broadcast.broadcast_id);
    return { claim: !!this.wantOutputAuthority && !!broadcast && broadcast.state !== 'DRAINING' && (!this.bridge.state.authorityReady(broadcast.broadcast_id) || lease?.consumer_id !== body.consumer_id), broadcast_id: broadcast?.broadcast_id || null };
  }
  async ensureSession(platform,{resume=false}={}) {
    if (this.config.value.interaction.mode === 'chat' && !this.bridge.health().persona_injection_ready) await this.bridge.probe();
    const old = this.bridge.state.current(); check(!old || old.state!=='DRAINING'&&(resume||!['PAUSED','RECOVERING'].includes(old.state)), 'BROADCAST_NOT_STARTABLE');
    const broadcast = old || this.bridge.state.createBroadcast(this.bridge.auth.resolve());
    const saved=this.store.get('SELECT * FROM outputs WHERE platform=?',platform);
    this.store.setOutput(platform, { state: 'STARTING', broadcast_id: broadcast.broadcast_id, owned_broadcast: saved?.broadcast_id===broadcast.broadcast_id?saved.owned_broadcast:!old, error: null });
    this.wantOutputAuthority = true;
    for (let i = 0; i < 50; i++) {
      const current = this.bridge.state.current(); check(current?.broadcast_id === broadcast.broadcast_id, 'BROADCAST_CHANGED');
      const lease = this.bridge.db.get('SELECT * FROM playback_leases WHERE broadcast_id=?', broadcast.broadcast_id);
      if (this.player && this.now() - this.player.at < 6000 && this.player.frames>0 && this.player.audio_state==='running' && lease?.consumer_id === this.player.consumer_id && this.bridge.state.authorityReady(broadcast.broadcast_id)) {
        if (current.state !== 'LIVE') { const media = await this.bridge.refreshMedia(); this.bridge.state.readyBroadcast(current.broadcast_id, this.bridge.host.ready && media.tts_ready && media.avatar_ready && (this.config.value.interaction.mode === 'echo' || this.bridge.health().persona_injection_ready), { broadcast_id: current.broadcast_id, expected_revision: current.revision }); continue; }
        return broadcast.broadcast_id;
      }
      await wait(500);
    }
    throw new PlatformError(this.config.value.platforms[platform].output_mode === 'livehime' ? 'LIVEHIME_PLAYER_NOT_READY' : 'OBS_PLAYER_NOT_READY', 503);
  }
  async prepareOutput(platform) {
    check(PLATFORM_IDS.includes(platform), 'PLATFORM_INVALID');
    this.checkRenderer(platform);
    return this.config.value.platforms[platform].output_mode === 'livehime' ? this.livehime.prepare() : this.obs.prepare();
  }
  checkRenderer(platform) {
    const native = this.config.value.platforms[platform].output_mode === 'livehime';
    const conflict = this.store.all('SELECT * FROM outputs').some(row => row.platform !== platform
      && (ACTIVE_OUTPUTS.includes(row.state) || row.owned_output)
      && (this.config.value.platforms[row.platform]?.output_mode === 'livehime') !== native);
    check(!conflict, 'OUTPUT_RENDERER_CONFLICT');
  }
  async startOutput(platform) {
    return this.exclusive(async () => {
      check(PLATFORM_IDS.includes(platform), 'PLATFORM_INVALID'); const config = this.config.value.platforms[platform];
      const existing = this.store.get('SELECT * FROM outputs WHERE platform=?', platform); check(!existing || !(ACTIVE_OUTPUTS.includes(existing.state)||existing.owned_output), 'PLATFORM_OUTPUT_ALREADY_ACTIVE');
      this.checkRenderer(platform);
      if (config.output_mode === 'livehime') {
        try {
          await this.livehime.prepare();
          const broadcastId = await this.ensureSession(platform);
          // Livehime now owns playback; release the redundant preview and its GPU resources.
          await this.livehime.close();
          return this.store.setOutput(platform, { state: 'COMPANION_READY', broadcast_id: broadcastId, owned_output: false, error: null });
        } catch (error) {
          this.store.setOutput(platform, { state: 'ERROR', error: error.code || 'LIVEHIME_PREPARE_FAILED' });
          await this.endIfUnused(); await this.livehime.close(); throw error;
        }
      }
      if (config.output_mode === 'obs') check(config.stream_server && config.stream_key, 'STREAM_TARGET_NOT_CONFIGURED');
      const state = await this.obs.status(); if (config.output_mode === 'obs') check(!state.streaming, 'OBS_STREAM_ALREADY_ACTIVE');
      check(state.video.baseWidth === 720 && state.video.baseHeight === 1280, 'OBS_SCENE_NOT_PREPARED');
      const scene = await this.obs.call('GetCurrentProgramScene'); check(scene.sceneName === this.config.value.obs.scene, 'OBS_SCENE_NOT_PREPARED');
      try {
        const broadcastId = await this.ensureSession(platform);
        if (config.output_mode === 'obs') {
          await this.obs.setTarget(config.stream_server, config.stream_key); this.store.setOutput(platform,{owned_output:true}); await this.obs.call('StartStream');
          for (let i = 0; i < 15; i++) { if ((await this.obs.call('GetStreamStatus')).outputActive) return this.store.setOutput(platform, { state: 'STREAMING', error: null }); await wait(500); }
          throw new PlatformError('OBS_STREAM_NOT_ACTIVE', 503);
        }
        await this.obs.call('SetInputAudioMonitorType', { inputName: this.config.value.obs.input, monitorType: 'OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT' });
        await this.obs.projector();
        return this.store.setOutput(platform, { state: 'COMPANION_READY', broadcast_id: broadcastId, owned_output: false, error: null });
      } catch (error) {
        const row=this.store.get('SELECT * FROM outputs WHERE platform=?',platform);
        if(row?.owned_output){try{if((await this.obs.call('GetStreamStatus')).outputActive)await this.obs.call('StopStream');if(!(await this.obs.call('GetStreamStatus')).outputActive)this.store.setOutput(platform,{owned_output:false});}catch{}}
        this.store.setOutput(platform, { state: 'ERROR', error: error.code || 'OUTPUT_START_FAILED' }); await this.endIfUnused(); throw error;
      }
    });
  }
  async endIfUnused() {
    const broadcast = this.bridge.state.current(); if (!broadcast) { this.wantOutputAuthority = false; return; }
    const rows = this.store.all('SELECT * FROM outputs WHERE broadcast_id=?', broadcast.broadcast_id);
    if (rows.some(row => ACTIVE_OUTPUTS.includes(row.state)||row.owned_output)) return;
    this.wantOutputAuthority = false;
    if (rows.some(row => row.owned_broadcast)) { this.bridge.state.end(this.bridge.auth.resolve(), { broadcast_id: broadcast.broadcast_id, expected_revision: broadcast.revision }); void this.bridge.tick(); }
  }
  async stopOutput(platform) {
    return this.exclusive(async () => {
      const row = this.store.get('SELECT * FROM outputs WHERE platform=?', platform); check(row && (ACTIVE_OUTPUTS.includes(row.state)||row.owned_output), 'PLATFORM_OUTPUT_NOT_ACTIVE');
      if (row.owned_output) { await this.obs.call('StopStream'); for (let i = 0; i < 20 && (await this.obs.call('GetStreamStatus')).outputActive; i++) await wait(500); check(!(await this.obs.call('GetStreamStatus')).outputActive, 'OBS_STREAM_STOP_TIMEOUT'); }
      const result = this.store.setOutput(platform, { state: 'STOPPED', owned_output: false, error: null }); await this.endIfUnused();
      if (this.config.value.platforms[platform].output_mode === 'livehime') await this.livehime.close();
      return result;
    });
  }
  async preflight(platform) {
    check(PLATFORM_IDS.includes(platform), 'PLATFORM_INVALID'); const target = this.config.value.platforms[platform]; let obs;
    if (target.output_mode === 'livehime') {
      let native;
      try { native = await this.livehime.status(); } catch (error) { native = { client_installed: false, window_open: false, error: error.code || 'LIVEHIME_UNAVAILABLE' }; }
      const media = await this.bridge.refreshMedia();
      const source = this.player?.renderer === 'livehime' && this.now() - this.player.at < 6000 ? this.player : null;
      if (target.client_location === 'receiver') native = { ...native, client_installed: !!source?.receiver_client_ready, receiver_id: source?.receiver_id || null };
      return { platform, renderer: 'livehime', obs_required: false, native,
        checks: { tts_ready: !!media.tts_ready, avatar_ready: !!media.avatar_ready,
          channel_ready: this.config.value.interaction.mode === 'echo' || this.bridge.health().persona_injection_ready,
          client_installed: native.client_installed, preview_window: native.window_open,
          livehime_browser_connected: !!source,
          vertical_video: source?.width === 720 && source?.height === 1280,
          output_audio: source?.audio_state === 'running', room_configured: !!target.room_url || !!target.room_id,
          official_application_required: ['open_live', 'official_callback'].includes(target.comment_mode),
          collector_running: !!this.collectors.get(platform), audience_delivery_verified: false } };
    }
    try { obs = await this.obs.status(); } catch (error) { obs = { connected: false, error: error.code || 'OBS_UNAVAILABLE' }; }
    const health = await this.bridge.refreshMedia();
    return { platform, obs, checks: { tts_ready: !!health.tts_ready, avatar_ready: !!health.avatar_ready, channel_ready: this.config.value.interaction.mode === 'echo' || this.bridge.health().persona_injection_ready, obs_connected: obs.connected, vertical_video: obs.connected && obs.video.baseWidth === 720 && obs.video.baseHeight === 1280, stream_target: target.output_mode === 'companion' || !!target.stream_server && !!target.stream_key, room_configured: !!target.room_url || !!target.room_id, official_application_required: ['open_live', 'official_callback'].includes(target.comment_mode), collector_running: !!this.collectors.get(platform), audience_delivery_verified: false } };
  }
  async resumeOutput(platform){return this.exclusive(async()=>{const row=this.store.get('SELECT * FROM outputs WHERE platform=?',platform);check(row&&ACTIVE_OUTPUTS.includes(row.state),'PLATFORM_OUTPUT_NOT_ACTIVE');check(this.bridge.state.current()?.broadcast_id===row.broadcast_id,'BROADCAST_CHANGED');try{await this.ensureSession(platform,{resume:true});return this.store.setOutput(platform,{state:row.state,error:null});}catch(error){this.store.setOutput(platform,{state:row.state,error:error.code||'SESSION_RESUME_FAILED'});throw error;}});}
  async handle(req, res, url, send) {
    const path = url.pathname.slice('/api/dsh/platforms'.length), method = req.method;
    if (method === 'GET' && (!path || path === '/status')) return send(this.status());
    if (method === 'GET' && path === '/config') return send(this.config.public());
    if (method === 'POST' && path === '/config') { const patch=await this.body(req); for(const platform of Object.keys(patch.platforms||{})){const row=this.store.get('SELECT state,owned_output FROM outputs WHERE platform=?',platform);check(!this.collectors.has(platform)&&!(row&&(ACTIVE_OUTPUTS.includes(row.state)||row.owned_output)),'STOP_PLATFORM_CONNECTIONS_BEFORE_CONFIG');} return send(this.config.update(patch)); }
    if (method === 'POST' && path === '/output/player') return send(this.outputPlayer(await this.body(req)));
    if (method === 'POST' && path === '/events') { const body = await this.body(req); return send(this.ingest(body.platform, body.events || body.event, { roomId: body.room_id || this.config.value.platforms[body.platform]?.room_id, source: 'local_relay' }), 202); }
    if (method === 'POST' && path === '/douyin/callback') {
      const chunks = []; let size = 0; for await (const chunk of req) { size += chunk.length; check(size <= 1024 * 1024, 'CALLBACK_TOO_LARGE', 413); chunks.push(chunk); }
      const rows = verifyDouyin(req.headers, Buffer.concat(chunks), this.config.value.platforms.douyin.callback_secret, this.now());
      this.collectorStatus.douyin = { state: 'RECEIVING', updated_at: this.now() };
      return send(this.ingest('douyin', rows, { source: 'official_callback' }));
    }
    if (method === 'POST' && path === '/obs/launch') return send(await this.obs.launch());
    if (method === 'GET' && path === '/obs/status') return send(await this.obs.status());
    if (method === 'POST' && path === '/obs/prepare') return send(await this.exclusive(() => this.obs.prepare()));
    if (method === 'POST' && path === '/obs/projector') return send(await this.obs.projector());
    if (method === 'POST' && path === '/obs/record/start') { check(!(await this.obs.call('GetRecordStatus')).outputActive, 'OBS_RECORDING_ALREADY_ACTIVE'); await this.obs.call('StartRecord'); this.ownedRecording = true; return send({ recording: true }); }
    if (method === 'POST' && path === '/obs/record/stop') { check(this.ownedRecording, 'OBS_RECORDING_NOT_OWNED'); const recording = await this.obs.call('StopRecord'); this.ownedRecording = false; return send({ recording: false, path: recording.outputPath }); }
    const match = path.match(/^\/(bilibili|douyin|custom)\/(preflight|prepare|client\/launch|window\/close|collector\/start|collector\/stop|start|stop|resume|confirm-live)$/);
    if (match) {
      const [, platform, action] = match;
      if (method === 'GET' && action === 'preflight') return send(await this.preflight(platform));
      if (method === 'POST') {
        const body = await this.body(req);
        if (action === 'prepare') return send(await this.exclusive(() => this.prepareOutput(platform)));
        if (action === 'client/launch') { check(platform === 'bilibili' && this.config.value.platforms[platform].output_mode === 'livehime', 'PLATFORM_MODE_INVALID'); return send(await this.livehime.launchClient(true)); }
        if (action === 'window/close') return send(await this.exclusive(async () => { check(platform === 'bilibili', 'PLATFORM_MODE_INVALID'); const row = this.store.get('SELECT * FROM outputs WHERE platform=?', platform); check(!row || !ACTIVE_OUTPUTS.includes(row.state), 'STOP_PLATFORM_OUTPUT_FIRST'); await this.livehime.close(); return { closed: true, public_broadcast_stopped: false }; }));
        if (action === 'collector/start') return send(await this.startCollector(platform, { visible: body.visible === true }));
        if (action === 'collector/stop') return send(await this.stopCollector(platform));
        if (action === 'start') return send(await this.startOutput(platform));
        if (action === 'stop') return send(await this.stopOutput(platform));
        if (action === 'resume') return send(await this.resumeOutput(platform));
        if (action === 'confirm-live') { const row = this.store.get('SELECT * FROM outputs WHERE platform=?', platform); check(row?.state === 'COMPANION_READY', 'COMPANION_NOT_PREPARED'); return send(this.store.setOutput(platform, { state: 'MANUAL_LIVE', error: null })); }
      }
    }
    throw new PlatformError('NOT_FOUND', 404);
  }
  async close() { this.closed = true; clearInterval(this.timer); clearInterval(this.pruneTimer); await Promise.allSettled([...this.collectors.keys()].map(p => this.stopCollector(p))); await this.controlChain; await this.obs.close(); await this.livehime.close(); this.store.close(); }
}
