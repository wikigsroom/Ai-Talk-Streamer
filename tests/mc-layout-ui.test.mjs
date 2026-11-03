import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fixture, root } from './room-fixture.mjs';

const playwright = join(root, 'node_modules/playwright-core');
const executablePath = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const output = join(root, 'docs/design/mc-landscape-v1');

test('backend admin moves the frozen MC chat left/right through SSE without resetting messages or media', { skip: !existsSync(executablePath) || !existsSync(playwright) }, async () => {
  const f = await fixture(), report = { classification: 'LOCAL_BACKEND_POSITION_CONTROL_ONLY', result: 'FAIL', real_platform_connected: false, inference_started: false, browser_closed: false, external_requests: [], page_errors: [] };
  let browser, context;
  try {
    const temp = join(root, 'cache/mc-layout-tests'); mkdirSync(temp, { recursive: true });
    browser = await createRequire(import.meta.url)(playwright).chromium.launch({ executablePath, headless: true, env: { ...process.env, TEMP: temp, TMP: temp }, args: ['--disable-gpu', '--disable-background-networking'] });
    context = await browser.newContext({ viewport: { width: 1984, height: 1510 } });
    await context.route(/^https?:\/\//, async route => { if (route.request().url().startsWith(f.base + '/')) await route.continue(); else { report.external_requests.push(route.request().url()); await route.abort(); } });
    const admin = await context.newPage(), preview = await context.newPage();
    for (const page of [admin, preview]) page.on('pageerror', e => report.page_errors.push(e.message));
    await admin.setViewportSize({ width: 1440, height: 1100 });
    await admin.goto(f.base + '/admin'); await admin.waitForFunction(() => window.adminRoom?.connected && window.adminRoom.state);
    await admin.locator('[data-page=visual]').click();
    await preview.goto(f.base + '/docs/design/mc-landscape-v1/preview.html?room_control=1');
    await preview.waitForFunction(() => document.querySelector('#chat-position-source').textContent === '位置由后台控制');
    assert.equal(await preview.locator('#chat-side').isDisabled(), true);
    await preview.evaluate(() => { mcDesign.freezeForCapture(); mcDesign.enqueue('队列样例', '换边时保持待显示队列', { id: 'keep-queue' }); });
    const before = await preview.evaluate(() => ({ ids: [...document.querySelector('#chat-list').children].map(el => el.dataset.message), state: mcDesign.inspectChat(), avatarLeft: document.querySelector('.avatar').style.left }));
    for (const side of ['left', 'right']) {
      await admin.locator('#mcChatSide').selectOption(side);
      await admin.waitForFunction(value => adminRoom.state.settings.overlay.mc_chat_side === value, side);
      await preview.waitForFunction(value => document.querySelector('#programme').dataset.chatSide === value, side);
      const observed = await preview.evaluate(() => ({ ids: [...document.querySelector('#chat-list').children].map(el => el.dataset.message), state: mcDesign.inspectChat(), chatLeft: document.querySelector('[data-region=chat]').style.left, giftLeft: document.querySelector('[data-region=gift]').style.left, avatarLeft: document.querySelector('.avatar').style.left, players: document.querySelectorAll('audio,video,iframe').length }));
      assert.deepEqual(observed.ids, before.ids); assert.equal(observed.state.pending, before.state.pending);
      assert.equal(observed.avatarLeft, before.avatarLeft); assert.equal(observed.players, 0);
      assert.equal(observed.chatLeft, side === 'left' ? '32px' : '1480px'); assert.equal(observed.giftLeft, observed.chatLeft);
    }
    await admin.locator('#mcChatSide').selectOption('left');
    await preview.waitForFunction(() => document.querySelector('#programme').dataset.chatSide === 'left');
    await admin.locator('section.panel').filter({ has: admin.locator('#mcChatSide') }).screenshot({ path: join(output, 'preview-backend-position-control.png') });
    await preview.reload(); await preview.waitForFunction(() => document.querySelector('#programme').dataset.chatSide === 'left');
    assert.equal((await (await fetch(f.base + '/api/dsh/room/state')).json()).settings.overlay.mc_chat_side, 'left');
    assert.equal(f.accepted.length, 0); assert.deepEqual(report.external_requests, []); assert.deepEqual(report.page_errors, []);
    report.checks = ['admin saves left/right strings through the actual config API', 'server SSE moves chat and gift together', 'nodes, queue and avatar position preserved', 'reload restores server value', 'no media player, model, speech or external service'];
    report.result = 'PASS';
  } catch (error) { report.error = String(error.stack || error); report.connection_diagnostic = await Promise.all((context?.pages() || []).map(async page => { try { return await page.evaluate(() => ({ path: location.pathname, ready: document.readyState, room_created: !!window.adminRoom, room_connected: window.adminRoom?.connected ?? null, room_revision: window.adminRoom?.state?.revision ?? null, event_source_state: window.adminRoom?.events?.readyState ?? null })); } catch { return { page_unavailable: true }; } })); throw error; }
  finally {
    if (context) await context.close();
    if (browser) { await browser.close(); report.browser_closed = !browser.isConnected(); }
    await f.close(); report.recorded_at = new Date().toISOString();
    writeFileSync(join(output, 'backend-position-verification.json'), JSON.stringify(report, null, 2) + '\n');
    assert(report.browser_closed || !browser);
  }
});
