import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { join, resolve, extname } from 'node:path';
import { createServer } from 'node:http';
import { PlatformManager } from '../backend/platforms/manager.mjs';

const root = resolve(process.cwd()), modulePath = process.env.PLATFORM_PLAYWRIGHT_MODULE || [join(root, 'node_modules/playwright-core'), join(root, 'tools/dsh-browser/node_modules/playwright-core')].find(existsSync) || join(root, 'node_modules/playwright-core');
test('platform page saves real redacted settings, renders comments safely, and fits mobile', { skip: !existsSync(modulePath) }, async () => {
  const output = join(root, 'outputs/platforms/ui-tests'); mkdirSync(output, { recursive: true });
  const folder = mkdtempSync(join(output, 'case-')), accepted = [];
  let broadcast = null;
  const bridge = { state: { current: () => broadcast }, refreshMedia: async () => ({ tts_ready: true, avatar_ready: true }), health: () => ({ persona_injection_ready: true }) };
  const obs = { status: async () => ({ connected: true, version: 'fixture-31.1.2', video: { baseWidth: 720, baseHeight: 1280 } }), close() {} };
  const livehime={status:async()=>({client_installed:true,window_open:false,player:null}),close:async()=>{}};
  const manager = new PlatformManager(folder, bridge, { obs,livehime });
  const send = (res, value, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(value)); };
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    try {
      if (url.pathname.startsWith('/api/dsh/platforms')) {
        if (req.method === 'POST') accepted.push(url.pathname);
        await manager.handle(req, res, url, (v, status) => send(res, v, status)); return;
      }
      if (url.pathname === '/api/studio/poster') { res.writeHead(200, { 'Content-Type': 'image/png' }); res.end(readFileSync(join(root, 'assets/vertical/student-dorm-720x1280.png'))); return; }
      const allowed = { '/platforms': 'platforms.html', '/platforms.js': 'platforms.js', '/platforms.css': 'platforms.css' };
      if (!allowed[url.pathname]) { res.writeHead(404); res.end(); return; }
      const file = allowed[url.pathname]; res.writeHead(200, { 'Content-Type': { '.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.css': 'text/css' }[extname(file)] }); res.end(readFileSync(join(root, 'web', file)));
    } catch (e) { send(res, { error: e.code || e.message }, e.status || 500); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  const { chromium } = createRequire(import.meta.url)(modulePath);
  const browser = await chromium.launch({ executablePath: ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(existsSync), headless: true, args: ['--disable-gpu'] });
  try {
    const context = await browser.newContext({ viewport: { width: 1536, height: 1100 } }); const page = await context.newPage(), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base + '/platforms');
    await page.waitForFunction(() => document.querySelector('#setupTitle').textContent === '连接哔哩哔哩');
    await page.locator('#roomUrl').fill('https://live.bilibili.com/595139');
    assert.equal(await page.locator('#streamFields').isVisible(),false);
    assert.equal(await page.locator('#recordBtn').isVisible(),false);
    assert.equal(await page.locator('#outputMode').inputValue(),'livehime');
    await page.locator('[data-platform="custom"]').click();
    await page.locator('#streamServer').fill('rtmp://127.0.0.1/live');
    await page.locator('#streamKey').fill('fixture-private-key');
    await page.getByRole('button', { name: '保存平台配置' }).click();
    await page.waitForFunction(() => document.querySelector('#saveFeedback').textContent === '平台配置已保存。');
    assert.equal(manager.config.value.platforms.custom.room_id, '');
    assert.equal(await page.locator('#streamKey').inputValue(), '');
    const redacted = JSON.stringify(await (await fetch(base + '/api/dsh/platforms/config')).json());
    assert.ok(!redacted.includes('fixture-private-key')); assert.equal(manager.config.public().platforms.custom.has_stream_key, true);
    await page.locator('[data-platform="bilibili"]').click();
    await page.locator('#roomUrl').fill('https://live.bilibili.com/595139');
    await page.getByRole('button', { name: '保存平台配置' }).click();
    await page.waitForFunction(() => document.querySelector('#saveFeedback').textContent === '平台配置已保存。');
    await page.getByRole('button', { name: '检查连接', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#avatarState').textContent === '人物与 MOSS 声音就绪');
    manager.ingest('bilibili', { type: 'comment', event_id: 'fixture-xss', room_id: '595139', nickname: '选型观众', user_id: 'test-viewer', text: '<img src=x onerror="window.injected=true">这是一条测试评论' });
    await page.waitForFunction(() => document.querySelector('#receivedCount').textContent === '1');
    assert.ok((await page.locator('#eventRows').textContent()).includes('<img src=x'));
    assert.equal(await page.locator('#eventRows img').count(), 0); assert.equal(await page.evaluate(() => window.injected), undefined);
    await page.screenshot({ path: join(output, 'platform-desktop-fixture.png'), fullPage: true });
    await page.locator('[data-platform="douyin"]').click();
    await page.waitForFunction(() => !document.querySelector('#companionHelp').hidden);
    assert.equal(await page.locator('#streamFields').isVisible(), false);
    assert.equal(await page.locator('#preflight').isVisible(), false, 'A platform switch clears the previous destination checks');
    broadcast = { state: 'PAUSED', broadcast_id: 'fixture-broadcast' };
    manager.store.setOutput('douyin', { state: 'COMPANION_READY', broadcast_id: broadcast.broadcast_id });
    await page.waitForFunction(() => !document.querySelector('#resumeBtn').hidden);
    assert.equal(await page.locator('#stopBtn').isEnabled(), true);
    manager.store.setOutput('douyin', { state: 'ERROR', owned_output: true });
    await page.waitForFunction(() => document.querySelector('#outputState').textContent === '连接失败');
    assert.equal(await page.locator('#stopBtn').isEnabled(), true);
    broadcast = null; manager.store.setOutput('douyin', { state: 'STOPPED', owned_output: false });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.querySelector('#outputState').textContent === '已停止');
    await page.screenshot({ path: join(output, 'platform-mobile-fixture.png'), fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal page overflow on a 390px phone');
    assert.equal(accepted.filter(path=>path.includes('/obs/')).length,0,'Bilibili page never calls OBS');
    assert.deepEqual(errors, []); assert.ok(!accepted.some(path => path.endsWith('/start')), 'UI never starts publishing while saving or inspecting');
    await context.close(); assert.equal(browser.contexts().length, 0);
  } finally { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await manager.close(); rmSync(folder, { recursive: true, force: true }); }
});
