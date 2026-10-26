import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdirSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { LivehimeOutput, LIVEHIME_OUTPUT_URL } from '../backend/platforms/livehime.mjs';
import { PlatformConfig } from '../backend/platforms/config.mjs';

const output = resolve('outputs/platforms/livehime-tests'); mkdirSync(output, { recursive: true });
function fixture({ failWindow = false } = {}) {
  const root = mkdtempSync(join(output, 'case-')), calls = [], events = new Map();
  const page = { closed: false, isClosed() { return this.closed; }, url: () => LIVEHIME_OUTPUT_URL,
    on(name, handler) { events.set('page:' + name, handler); },
    async evaluate() { return { width: 720, height: 1280, video_width: 720, video_height: 1280, audio_state: 'running', frames: 25 }; },
    async waitForFunction() { if (failWindow) throw Error('fixture media timeout'); },
  };
  const unused = { async close() { calls.push('unused-page-closed'); } };
  const context = { pages: () => [page, unused], on(name, handler) { events.set('context:' + name, handler); },
    async close() { calls.push('context-closed'); page.closed = true; events.get('context:close')?.(); } };
  const playwright = { chromium: { async launchPersistentContext(profile, options) { calls.push({ profile, options }); return context; } } };
  const spawnChild = (executable, args, options) => {
    calls.push({ executable, args, options }); const child = new EventEmitter(); child.unref = () => calls.push('client-detached');
    queueMicrotask(() => child.emit('spawn')); return child;
  };
  const instance = new LivehimeOutput(root, { playwright, spawnChild });
  const installed = () => {
    mkdirSync(join(root, 'tools/livehime'), { recursive: true });
    writeFileSync(join(root, 'tools/livehime/livehime.exe'), 'fixture executable, never executed');
    mkdirSync(join(root, 'outputs/platforms/setup'), { recursive: true });
    writeFileSync(join(root, 'outputs/platforms/setup/bilibili-livehime.json'), JSON.stringify({ prepared: true, version: 'fixture', application: 'tools/livehime/livehime.exe', application_signature: { status: 'Valid' } }));
  };
  return { root, instance, calls, installed, async close() { await instance.close(); rmSync(root, { recursive: true, force: true }); } };
}

test('native Livehime preparation needs an installed client and never opens a placeholder window', async () => {
  const f = fixture(); try {
    await assert.rejects(f.instance.prepare(), { code: 'LIVEHIME_NOT_INSTALLED' });
    assert.deepEqual(f.calls, []); assert.equal((await f.instance.status()).client_installed, false);
  } finally { await f.close(); }
});

test('native renderer owns one 720x1280 app window and closes all unused pages', async () => {
  const f = fixture(); try {
    f.installed(); const result = await f.instance.prepare(); await f.instance.prepare();
    assert.equal(result.prepared, true); assert.equal(result.status.obs_required, false);
    assert.equal(result.status.account_login_verified, false); assert.equal(result.status.audience_delivery_verified, false);
    assert.equal(f.calls.filter(call => call?.options?.headless === false).length, 1);
    const browser = f.calls.find(call => call?.options?.headless === false);
    assert.deepEqual(browser.options.viewport, { width: 720, height: 1280 });
    assert.ok(browser.options.args.includes('--app=' + LIVEHIME_OUTPUT_URL));
    assert.ok(browser.profile.startsWith(f.root)); assert.ok(f.calls.includes('unused-page-closed'));
    const client = f.calls.find(call => call?.executable);
    assert.ok(client.executable.startsWith(f.root)); assert.ok(client.options.env.APPDATA.startsWith(f.root));
    assert.ok(!JSON.stringify(f.calls).includes('obs64.exe'));
    await f.instance.close(); assert.equal((await f.instance.status()).window_open, false);
  } finally { await f.close(); }
});

test('failed native media readiness closes the created browser context', async () => {
  const f = fixture({ failWindow: true }); try {
    f.installed(); await assert.rejects(f.instance.prepare(), { code: 'LIVEHIME_WINDOW_NOT_READY' });
    assert.ok(f.calls.includes('context-closed')); assert.equal((await f.instance.status()).window_open, false);
  } finally { await f.close(); }
});

test('an installation receipt cannot launch an application outside the project', async () => {
  const f = fixture(); try {
    f.installed(); writeFileSync(join(f.root, 'outputs/platforms/setup/bilibili-livehime.json'), JSON.stringify({ prepared: true, application: '../outside.exe', application_signature: { status: 'Valid' } }));
    await assert.rejects(f.instance.launchClient(), { code: 'LIVEHIME_RECEIPT_INVALID' }); assert.deepEqual(f.calls, []);
  } finally { await f.close(); }
});

test('split-device preparation never launches a client or preview on the inference host', async () => {
  const f = fixture(); try {
    f.instance.receiverConfig = () => ({ client_location: 'receiver', receiver_url: 'http://127.0.0.1:8020' });
    const value = await f.instance.prepare();
    assert.equal(value.client_location, 'receiver'); assert.equal(value.receiver_connection_required, true);
    assert.equal(value.status.deployment, 'split_device'); assert.equal(value.status.client_required_on, 'receiver');
    assert.equal(value.status.source_url, 'http://127.0.0.1:8020/output.html?output=platform&renderer=livehime');
    assert.equal((await f.instance.launchClient()).launch_requested, false);
    assert.deepEqual(f.calls, []);
  } finally { await f.close(); }
});

test('split-device settings are explicit, persist, and reject malformed receiver origins', async () => {
  const f = fixture(); try {
    const config = new PlatformConfig(f.root);
    assert.equal(config.value.platforms.bilibili.client_location, 'same_device');
    config.update({ platforms: { bilibili: { client_location: 'receiver', receiver_url: 'http://127.0.0.1:8020/' } } });
    assert.equal(new PlatformConfig(f.root).value.platforms.bilibili.receiver_url, 'http://127.0.0.1:8020');
    assert.throws(() => config.update({ platforms: { douyin: { client_location: 'receiver' } } }), /CLIENT_LOCATION/);
    for (const receiver_url of ['file:///tmp', 'http://user:secret@localhost:8020', 'http://localhost:8020/path', 'http://localhost:8020/?source=x']) {
      assert.throws(() => config.update({ platforms: { bilibili: { receiver_url } } }), /RECEIVER_URL/);
    }
  } finally { await f.close(); }
});
