import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { ObsClient } from '../backend/platforms/obs.mjs';
import { PlatformConfig } from '../backend/platforms/config.mjs';

const output = resolve('outputs/platforms/obs-tests'); mkdirSync(output, { recursive: true });
const sha = value => createHash('sha256').update(value).digest('base64');
function socketType() {
  return class ObsSocket extends EventTarget {
    static instances = [];
    constructor() { super(); this.readyState = 0; this.messages = []; this.constructor.instances.push(this); queueMicrotask(() => { this.readyState = 1; this.receive({ op: 0, d: { rpcVersion: 1, authentication: { salt: 'fixture-salt', challenge: 'fixture-challenge' } } }); }); }
    receive(value) { this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(value) })); }
    send(raw) {
      const value = JSON.parse(raw); this.messages.push(value);
      if (value.op === 1) queueMicrotask(() => this.receive({ op: 2, d: { negotiatedRpcVersion: 1 } }));
      if (value.op === 6 && value.d.requestType !== 'WaitForDisconnect') setTimeout(() => this.receive({ op: 7, d: { requestId: value.d.requestId, requestStatus: { result: value.d.requestType !== 'Unsupported', code: 204 }, responseData: { type: value.d.requestType } } }), value.d.requestType === 'Slow' ? 30 : 0);
    }
    close() { this.readyState = 3; this.dispatchEvent(new Event('close')); }
  };
}
function fixture(raw = '\uFEFF'+JSON.stringify({ server_password: 'fixture-only-password' })) {
  const root = mkdtempSync(join(output, 'case-')), config = new PlatformConfig(root), Socket = socketType();
  const dir = join(root, 'tools/obs/config/obs-studio/plugin_config/obs-websocket'); mkdirSync(dir, { recursive: true }); writeFileSync(join(dir, 'config.json'), raw);
  const obs = new ObsClient(root, config, { WebSocketClass: Socket });
  return { obs, Socket, async close() { await obs.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('OBS challenge authentication and concurrent out-of-order RPC replies use one connection', async () => {
  const f = fixture(); try {
    const results = await Promise.all([f.obs.call('Slow'), f.obs.call('Fast')]);
    assert.deepEqual(results, [{ type: 'Slow' }, { type: 'Fast' }]); assert.equal(f.Socket.instances.length, 1);
    const identify = f.Socket.instances[0].messages.find(x => x.op === 1);
    assert.equal(identify.d.authentication, sha(sha('fixture-only-passwordfixture-salt')+'fixture-challenge'));
    assert.equal(f.obs.pending.size, 0);
    await assert.rejects(f.obs.call('Unsupported'), { code: 'OBS_REQUEST_204_Unsupported' });
    const pending = f.obs.call('WaitForDisconnect'); await new Promise(resolve => setImmediate(resolve));
    f.Socket.instances[0].close(); await assert.rejects(pending, { code: 'OBS_DISCONNECTED' }); assert.equal(f.obs.pending.size, 0);
  } finally { await f.close(); }
});

test('invalid OBS private settings fail cleanly without leaking or crashing the bridge', async () => {
  const f = fixture('{invalid-json'); try { await assert.rejects(f.obs.connect(), { code: 'OBS_WEBSOCKET_SETTINGS_INVALID' }); } finally { await f.close(); }
});

test('preparing a scene refuses to change a canvas while OBS already has an output', async () => {
  const f = fixture(), changes = [];
  try {
    f.obs.launch = async () => ({ already_running: true });
    f.obs.status = async () => ({ streaming: true, recording: false, virtual_camera: false });
    f.obs.call = async name => { changes.push(name); return {}; };
    await assert.rejects(f.obs.prepare(), { code: 'OBS_OUTPUT_ACTIVE' }); assert.deepEqual(changes, []);
  } finally { await f.close(); }
});

test('a portable OBS without its optional virtual camera still supports status and streaming', async () => {
  const f = fixture();
  try {
    f.obs.call = async name => {
      if (name === 'GetVirtualCamStatus') throw Object.assign(new Error('missing virtual camera'), { code: 'OBS_REQUEST_604_GetVirtualCamStatus' });
      if (name === 'GetVersion') return { obsVersion: '31.1.2' };
      if (name === 'GetVideoSettings') return { baseWidth: 720, baseHeight: 1280 };
      return { outputActive: false };
    };
    const status = await f.obs.status(); assert.equal(status.connected, true); assert.equal(status.virtual_camera_available, false); assert.equal(status.virtual_camera, false);
  } finally { await f.close(); }
});
