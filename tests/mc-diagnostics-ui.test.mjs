import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { gameFixture } from './game-fixture.mjs';

const { chromium } = createRequire(import.meta.url)(resolve('node_modules/playwright-core'));
test('game console shows a sanitized fault live and after reload even when normal APIs reject reads', async () => {
 const f = await gameFixture({ fakeClock: true, ui: true });
 const output = resolve(process.env.MC_UI_EVIDENCE_ROOT || 'outputs/mc-diagnostics-ui'); mkdirSync(output, { recursive: true });
 const errors = [], external = []; let browser, context;
 try {
  await f.connect();
  browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--disable-gpu', '--disable-background-networking'] });
  context = await browser.newContext({ viewport: { width: 1440, height: 1080 } });
  await context.route(/^https?:\/\//, async route => { if (route.request().url().startsWith(f.base + '/')) await route.continue(); else { external.push(route.request().url()); await route.abort(); } });
  const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
  await page.goto(f.base + '/mc-control');
  await page.getByText('连接正常', { exact: true }).waitFor();
  const error = Error('secret viewer text and C:/private/database'); error.code = 'ERR_SQLITE_ERROR'; error.errcode = 5;
  f.manager.storageFault(error, 'http_request');
  await page.getByText('服务故障待恢复', { exact: true }).waitFor();
  assert.equal(await page.locator('[data-mode="AUTO"]').isDisabled(), true);
  await page.reload();
  await page.getByText('服务故障待恢复', { exact: true }).waitFor();
  await page.locator('#game-diagnostics-details summary').click();
  const record = await page.locator('#game-diagnostics-record').innerText();
  assert.match(record, /ERR_SQLITE_ERROR/); assert.match(record, /http_request/);
  assert.equal(record.includes('secret viewer'), false); assert.equal(record.includes('C:/private'), false);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: join(output, 'game-fault-after-reload-390.png'), fullPage: true });
  assert.deepEqual(errors, []); assert.deepEqual(external, []);
 } finally {
  await context?.close(); await browser?.close(); await f.close();
  writeFileSync(join(output, 'game-diagnostics-browser-cleanup.json'), JSON.stringify({ browser_closed: !browser?.isConnected(), page_errors: errors, external_requests: external, real_minecraft: false }, null, 2) + '\n');
 }
});
