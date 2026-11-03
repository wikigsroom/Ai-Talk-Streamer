import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { retentionFixture } from './audience-retention-fixture.mjs';
import { sourceRoot } from './game-fixture.mjs';

const executablePath = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const playwright = join(sourceRoot, 'node_modules/playwright-core');
const skip = !existsSync(executablePath) || !existsSync(playwright);
const output = resolve(process.env.MC_RETENTION_EVIDENCE_ROOT || join(sourceRoot, 'outputs/mc-validation/round-027/browser'));

async function withPage(t, name, work) {
  const f = await retentionFixture(t); await f.serve(); mkdirSync(output, { recursive: true });
  const report = { classification: 'LOCAL_REAL_BROWSER_PLATFORM_ROOM_SQLITE_WITH_GAME_AND_MODEL_FIXTURES',
    result: 'FAIL', page_errors: [], external_requests: [], browser_closed: false, real_game: false, real_models: false, public_broadcast: false };
  let browser, context;
  try {
    const temp = join(sourceRoot, 'cache/mc-retention-browser'); mkdirSync(temp, { recursive: true });
    browser = await createRequire(import.meta.url)(playwright).chromium.launch({ executablePath, headless: true,
      env: { ...process.env, TEMP: temp, TMP: temp }, args: ['--disable-gpu', '--disable-background-networking'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1080 } });
    await context.route(/^https?:\/\//, route => {
      if (route.request().url().startsWith(f.maintenanceBase + '/')) return route.continue();
      report.external_requests.push(route.request().url()); return route.abort();
    });
    const page = await context.newPage(); page.on('pageerror', error => report.page_errors.push(error.message));
    await work(f, page, report);
    assert.deepEqual(report.page_errors, []); assert.deepEqual(report.external_requests, []); report.result = 'PASS';
  } finally {
    try { await context?.close(); } finally { await browser?.close(); report.browser_closed = !browser?.isConnected();
      writeFileSync(join(output, name + '.json'), JSON.stringify(report, null, 2) + '\n'); }
  }
}

test('platform history maintenance runs against the real public API and remains usable in a narrow viewport', { skip }, async t => withPage(t, 'maintenance-complete', async (f, page, report) => {
  const a = await f.add(); f.age([a.key]);
  await page.goto(f.maintenanceBase + '/platforms.html');
  await page.waitForFunction(() => document.querySelector('#retentionStatus').textContent.includes('已保存账号归属 1 项'));
  await page.getByRole('button', { name: '清理到期历史', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#retentionStatus').textContent.includes('到期历史清理完成'));
  assert.match(await page.locator('#retentionStatus').innerText(), /平台事件 1 条、留言 0 条/u);
  assert.equal(f.platforms.store.get('SELECT * FROM events WHERE event_key=?', a.key), undefined); assert(f.room.store.message(a.key));
  await page.setViewportSize({ width: 390, height: 844 }); await page.locator('#retentionTitle').scrollIntoViewIfNeeded();
  const button = await page.locator('#retentionRun').boundingBox(); assert(button && button.x >= 0 && button.x + button.width <= 391);
  await page.screenshot({ path: join(output, 'maintenance-narrow.png') });
  report.checks = ['public_real_api', 'ownership_count', 'actual_platform_prune', 'minimum_room_history_preserved', 'narrow_button_visible'];
}));

test('platform maintenance displays failure and retries after a Room storage fault clears', { skip }, async t => withPage(t, 'maintenance-retry', async (f, page, report) => {
  const a = await f.add(); f.age([a.key]); const prune = f.room.pruneHistory;
  f.room.pruneHistory = () => { throw Object.assign(new Error('private-disk-detail'), { code: 'SQLITE_BUSY' }); };
  await page.goto(f.maintenanceBase + '/platforms.html'); await page.waitForFunction(() => !document.querySelector('#retentionRun').disabled);
  await page.locator('#retentionRun').click(); await page.waitForFunction(() => document.querySelector('#retentionStatus').textContent.includes('清理未完成'));
  assert(!((await page.locator('body').innerText()).includes('private-disk-detail')));
  f.room.pruneHistory = prune;
  await page.locator('#retentionRun').click(); await page.waitForFunction(() => document.querySelector('#retentionStatus').textContent.includes('到期历史清理完成'));
  await page.getByText('最近维护记录（最多20次）', { exact: true }).click();
  assert.equal(await page.locator('#retentionHistory li').count(), 2); assert.match(await page.locator('#retentionHistory').innerText(), /清理未完成/u);
  assert.equal(f.privacy.ownership.count(), 1); await f.remove(a); assert.equal(f.room.store.message(a.key), null);
  await page.screenshot({ path: join(output, 'maintenance-retry.png') });
  report.checks = ['failed_phase_visible', 'no_raw_storage_error', 'same_canonical_ownership_survives_retry', 'account_deletion_after_prune'];
}));
