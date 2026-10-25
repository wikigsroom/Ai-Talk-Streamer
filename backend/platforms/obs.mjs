import { createHash, randomUUID } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { spawn } from 'node:child_process';
import { check, PlatformError } from './config.mjs';
const sha = value => createHash('sha256').update(value).digest('base64');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

export class ObsClient {
  constructor(root, config, { WebSocketClass = WebSocket } = {}) { this.root = root; this.config = config; this.WebSocketClass = WebSocketClass; this.pending = new Map(); }
  async connect() {
    if (this.ws?.readyState === 1 && this.identified) return;
    if (this.connecting) return this.connecting;
    this.connecting = new Promise((resolve, reject) => {
      const ws = this.ws = new this.WebSocketClass(this.config.value.obs.url);
      const timeout = setTimeout(() => { reject(new PlatformError('OBS_UNAVAILABLE', 503)); ws.close(); }, 5000);
      const fail = () => { clearTimeout(timeout); reject(new PlatformError('OBS_UNAVAILABLE', 503)); if(this.ws!==ws)return; this.identified = false; for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(new PlatformError('OBS_DISCONNECTED', 503)); } this.pending.clear(); };
      ws.addEventListener('error', fail); ws.addEventListener('close', fail);
      ws.addEventListener('message', event => {
        let packet; try { packet = JSON.parse(String(event.data)); } catch { return; }
        if (packet.op === 0) {
          const identify = { rpcVersion: 1, eventSubscriptions: 0 };
          if (packet.d.authentication) {
            const file = join(this.root, 'tools/obs/config/obs-studio/plugin_config/obs-websocket/config.json');
            let saved; try { saved = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8').replace(/^\uFEFF/, '')) : {}; }
            catch { clearTimeout(timeout); reject(new PlatformError('OBS_WEBSOCKET_SETTINGS_INVALID', 503)); ws.close(); return; }
            if (!saved.server_password) { clearTimeout(timeout); reject(new PlatformError('OBS_WEBSOCKET_SETTINGS_MISSING', 503)); ws.close(); return; }
            identify.authentication = sha(sha(saved.server_password + packet.d.authentication.salt) + packet.d.authentication.challenge);
          }
          ws.send(JSON.stringify({ op: 1, d: identify }));
        } else if (packet.op === 2) { clearTimeout(timeout); this.identified = true; resolve(); }
        else if (packet.op === 7) {
          const p = this.pending.get(packet.d.requestId); if (!p) return;
          clearTimeout(p.timer); this.pending.delete(packet.d.requestId);
          if (packet.d.requestStatus.result) p.resolve(packet.d.responseData || {});
          else p.reject(new PlatformError('OBS_REQUEST_' + packet.d.requestStatus.code + '_' + p.type, 409));
        }
      });
    }).finally(() => { this.connecting = null; });
    return this.connecting;
  }
  async call(type, data = {}) {
    await this.connect(); const requestId = randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(requestId); reject(new PlatformError('OBS_REQUEST_TIMEOUT', 503)); }, 8000);
      this.pending.set(requestId, { type, resolve, reject, timer });
      try { this.ws.send(JSON.stringify({ op: 6, d: { requestType: type, requestId, requestData: data } })); }
      catch { clearTimeout(timer); this.pending.delete(requestId); reject(new PlatformError('OBS_DISCONNECTED', 503)); }
    });
  }
  async launch() {
    try { await this.connect(); return { already_running: true }; } catch {}
    const exe = join(this.root, 'tools/obs/bin/64bit/obs64.exe'); check(existsSync(exe), 'OBS_NOT_INSTALLED', 503);
    const child = spawn(exe, ['--portable', '--disable-updater', '--profile', 'Avatar Local', '--collection', 'Avatar Local'], { cwd: dirname(exe), windowsHide: true, detached: true, stdio: 'ignore' }); child.on('error', () => {}); child.unref();
    for (let i = 0; i < 10; i++) { await delay(1000); try { await this.connect(); return { started: true }; } catch {} }
    throw new PlatformError('OBS_START_TIMEOUT', 503);
  }
  async status() {
    const [version, stream, record, virtualcam, video, stats] = await Promise.all(['GetVersion', 'GetStreamStatus', 'GetRecordStatus', 'GetVirtualCamStatus', 'GetVideoSettings', 'GetStats'].map(type => this.call(type).catch(error => { if(type==='GetVirtualCamStatus'&&error.code==='OBS_REQUEST_604_GetVirtualCamStatus')return {outputActive:false,available:false}; throw error; })));
    return { connected: true, version: version.obsVersion, available_requests: version.availableRequests, streaming: stream.outputActive, stream_reconnecting: stream.outputReconnecting, stream_duration_ms: stream.outputDuration, stream_bytes: stream.outputBytes, stream_skipped_frames: stream.outputSkippedFrames, stream_total_frames: stream.outputTotalFrames, recording: record.outputActive, virtual_camera: virtualcam.outputActive, virtual_camera_available:virtualcam.available!==false, video, stats };
  }
  async prepare({ monitorAudio = false } = {}) {
    await this.launch(); const before = await this.status();
    check(!before.streaming && !before.recording && !before.virtual_camera, 'OBS_OUTPUT_ACTIVE');
    const settings = this.config.value.obs;
    const folder = join(this.root, '.setup/platforms'); mkdirSync(folder, { recursive: true });
    const profile=join(this.root,'tools/obs/config/obs-studio/basic/profiles/Avatar_Local/basic.ini');
    if(existsSync(profile))copyFileSync(profile,join(folder,'obs-profile-before-'+Date.now()+'.ini'));
    writeFileSync(join(folder, 'obs-before-' + Date.now() + '.json'), JSON.stringify({ video: before.video, scene: await this.call('GetCurrentProgramScene') }, null, 2));
    const scenes = await this.call('GetSceneList');
    if (!scenes.scenes.some(row => row.sceneName === settings.scene)) await this.call('CreateScene', { sceneName: settings.scene });
    const inputs = await this.call('GetInputList');
    const source = { url: 'http://127.0.0.1:8010/obs.html?output=platform', width: settings.width, height: settings.height, fps: settings.fps, reroute_audio: true, shutdown: false, restart_when_active: false };
    if (!inputs.inputs.some(row => row.inputName === settings.input)) await this.call('CreateInput', { sceneName: settings.scene, inputName: settings.input, inputKind: 'browser_source', inputSettings: source, sceneItemEnabled: true });
    else {
      await this.call('SetInputSettings', { inputName: settings.input, inputSettings: source, overlay: true });
      const items = await this.call('GetSceneItemList', { sceneName: settings.scene });
      if (!items.sceneItems.some(row => row.sourceName === settings.input)) await this.call('CreateSceneItem', { sceneName: settings.scene, sourceName: settings.input, sceneItemEnabled: true });
    }
    await this.call('SetVideoSettings', { baseWidth: settings.width, baseHeight: settings.height, outputWidth: settings.width, outputHeight: settings.height, fpsNumerator: settings.fps, fpsDenominator: 1 });
    const items = await this.call('GetSceneItemList', { sceneName: settings.scene });
    const item = items.sceneItems.find(row => row.sourceName === settings.input);
    await this.call('SetSceneItemTransform', { sceneName: settings.scene, sceneItemId: item.sceneItemId, sceneItemTransform: { positionX: 0, positionY: 0, rotation: 0, scaleX: 1, scaleY: 1, alignment: 5, boundsType: 'OBS_BOUNDS_NONE', cropLeft: 0, cropRight: 0, cropTop: 0, cropBottom: 0 } });
    await this.call('SetCurrentProgramScene', { sceneName: settings.scene });
    await this.call('SetInputMute', { inputName: settings.input, inputMuted: false });
    await this.call('SetInputVolume', { inputName: settings.input, inputVolumeDb: -3 });
    await this.call('SetInputAudioMonitorType', { inputName: settings.input, monitorType: monitorAudio ? 'OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT' : 'OBS_MONITORING_TYPE_NONE' });
    for (const [category, parameter, parameterValue] of [['Output', 'Mode', 'Simple'], ['SimpleOutput', 'StreamEncoder', 'nvenc'], ['SimpleOutput', 'VBitrate', String(settings.bitrate)], ['SimpleOutput', 'ABitrate', '160'], ['SimpleOutput', 'NVENCPreset2', 'p4'], ['SimpleOutput', 'RecQuality', 'Stream'], ['SimpleOutput', 'RecFormat2', 'mkv']]) await this.call('SetProfileParameter', { parameterCategory: category, parameterName: parameter, parameterValue });
    const recordings = join(this.root, 'outputs/platforms/recordings'); mkdirSync(recordings, { recursive: true });
    await this.call('SetRecordDirectory', { recordDirectory: recordings });
    return { prepared: true, scene: settings.scene, audio_monitoring: monitorAudio, status: await this.status() };
  }
  async setTarget(server, key) {
    const state = await this.call('GetStreamStatus'); check(!state.outputActive, 'OBS_STREAM_ALREADY_ACTIVE');
    check(/^rtmps?:\/\//.test(server) && key, 'STREAM_TARGET_NOT_CONFIGURED');
    return this.call('SetStreamServiceSettings', { streamServiceType: 'rtmp_custom', streamServiceSettings: { server, key, use_auth: false } });
  }
  async projector() { return this.call('OpenVideoMixProjector', { videoMixType: 'OBS_WEBSOCKET_VIDEO_MIX_TYPE_PROGRAM' }); }
  async close() { this.ws?.close(); this.identified = false; }
}
