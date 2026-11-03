import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { gameFixture, samples, until } from './game-fixture.mjs';
import { historyRecord, maintenanceRecord, historyPage, historyQuery, historyReply, finishHistory } from './game-history-fixture.mjs';

const { chromium } = createRequire(import.meta.url)(resolve('node_modules/playwright-core'));
async function browserFixture(t, label, features = {}) {
  const f = await gameFixture({ fakeClock: true, ui: true }), game = await f.connect({ features: { journal_history: true, ...features } });
  const output = resolve(process.env.MC_UI_EVIDENCE_ROOT || 'outputs/mc-history-ui'); mkdirSync(output, { recursive: true });
  const errors = [], external = [];
  let browser, context;
  t.after(async () => {
    try { await context?.close(); } finally { try { await browser?.close(); } finally { await f.close(); } }
    writeFileSync(join(output, label + '-cleanup.json'), JSON.stringify({ browser_closed: !browser?.isConnected(), page_errors: errors,
      external_requests: external, real_minecraft: false }, null, 2) + '\n');
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
  });
  browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true,
    args: ['--disable-gpu', '--disable-background-networking'] });
  context = await browser.newContext({ viewport: { width: 1440, height: 1080 } });
  await context.route(/^https?:\/\//, async route => { if (route.request().url().startsWith(f.base + '/')) await route.continue(); else { external.push(route.request().url()); await route.abort(); } });
  context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
  const page = await context.newPage(); await page.goto(f.base + '/mc-control');
  await page.getByText('连接正常', { exact: true }).waitFor();
  return { f, game, context, page, output };
}

test('operator imports historical worlds, filters and pages summaries, and reads escaped original content on mobile', async t => {
  const { f, game, page, output } = await browserFixture(t, 'history-console');
  await page.locator('#history-import').click(); await until(() => !!f.manager.history.job);
  const records = Array.from({ length: 23 }, (_, index) => historyRecord({ id: index + 1,
    payload: { ...samples['bridge-game_event'].value.payload, event_id: 'browser-history-' + index,
      delivery_seq: index + 1, world_session_id: 'world-old-browser', data: { note: '<img src=x onerror="window.HISTORY_XSS=true">' } },
    acked_at: 1793332800100 }));
  const first = await historyQuery(f, game);
  await historyReply(f, game, first, historyPage(f, first, records.slice(0, 20), { complete: false, through: 23 }));
  const second = await historyQuery(f, game); await historyReply(f, game, second, historyPage(f, second, records.slice(20), { through: 23 }));
  const third = await historyQuery(f, game); await historyReply(f, game, third, historyPage(f, third));
  await page.getByText('已存 23 条历史', { exact: true }).waitFor();
  await page.locator('#more-history:visible').waitFor();
  assert.equal(await page.locator('#history-entries .history-row').count(), 20);
  await page.locator('#more-history').click();
  await page.waitForFunction(() => document.querySelectorAll('#history-entries .history-row').length === 23);
  await page.locator('#history-filter').selectOption('task_versions');
  await page.locator('#history-entries .empty').waitFor();
  await page.locator('#history-filter').selectOption('events');
  await page.locator('#history-entries .history-row').first().getByRole('button', { name: '查看原文' }).click();
  await page.locator('#history-view-dialog[open]').waitFor();
  const record = await page.locator('#history-view-record').innerText(); assert.match(record, /world-old-browser/); assert.match(record, /<img/);
  assert.equal(await page.evaluate(() => window.HISTORY_XSS), undefined); assert.equal(await page.locator('#history-view-record img').count(), 0);
  await page.locator('#history-view-dialog [data-close]').click();
  await page.locator('#history-heading').scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(output, 'history-console-1440.png'), fullPage: false });
  await page.setViewportSize({ width: 390, height: 844 }); await page.locator('#history-heading').scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: join(output, 'history-console-390.png'), fullPage: false });
});

test('operator reads all maintenance record types, pages past twenty, and inspects escaped snapshots on mobile', async t => {
  const { f, game, page, output } = await browserFixture(t, 'maintenance-history-console', { journal_maintenance_history: true });
  await page.locator('#history-import').click(); await until(() => !!f.manager.history.job);
  const records = Array.from({ length: 23 }, (_, index) => {
    const value = structuredClone(samples['maintenance-summary-payload'].value.value);
    value.kind = index === 22 ? '<img src=x onerror="window.MAINTENANCE_XSS=true">' : 'historical-kind-' + index;
    return maintenanceRecord({ id: index + 1, value });
  });
  for (const source of ['reliable', 'task_versions']) {
    const query = await historyQuery(f, game); assert.equal(query.payload.request.params.source, source);
    await historyReply(f, game, query, historyPage(f, query));
  }
  let query = await historyQuery(f, game);
  await historyReply(f, game, query, historyPage(f, query, records.slice(0, 20), { complete: false, through: 23 }));
  await page.locator('#history-progress').getByText(/正在读取保留汇总/).waitFor();
  query = await historyQuery(f, game); await historyReply(f, game, query, historyPage(f, query, records.slice(20), { through: 23 }));
  await finishHistory(f, game, [], [], { retired_tasks: [maintenanceRecord({ source: 'retired_tasks' })], retention_runs: [maintenanceRecord({ source: 'retention_runs' })] });
  await page.getByText('已存 25 条历史', { exact: true }).waitFor();
  await page.locator('#history-filter').selectOption('retention_summaries');
  await page.waitForFunction(() => document.querySelector('#history-entries strong')?.textContent.includes('<img'));
  assert.equal(await page.locator('#history-entries .history-row').count(), 20);
  await page.locator('#more-history').click();
  await page.waitForFunction(() => document.querySelectorAll('#history-entries .history-row').length === 23);
  assert.equal(await page.locator('#history-entries img').count(), 0); assert.equal(await page.evaluate(() => window.MAINTENANCE_XSS), undefined);
  await page.locator('#history-entries .history-row').first().getByRole('button', { name: '查看原文' }).click();
  await page.locator('#history-view-dialog[open]').waitFor();
  assert.match(await page.locator('#history-view-record').innerText(), /old-maintenance-world/);
  assert.equal(await page.locator('#history-view-record img').count(), 0);
  await page.locator('#history-view-dialog [data-close]').click();
  await page.locator('#history-filter').selectOption('retired_tasks');
  await page.locator('#history-entries strong').getByText('采集 · v3 · 任务防重记录', { exact: true }).waitFor();
  assert.equal(await page.locator('#history-entries').getByText('尚未确认', { exact: false }).count(), 0);
  await page.locator('#history-filter').selectOption('retention_runs');
  await page.locator('#history-entries strong').getByText('维护完成 · 事件 3 条、任务 1 条', { exact: true }).waitFor();
  assert.match(await page.locator('#history-entries').innerText(), /跨世界维护 · 历史存档/);
  await page.locator('#history-heading').scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(output, 'maintenance-history-1440.png'), fullPage: false });
  await page.setViewportSize({ width: 390, height: 844 }); await page.locator('#history-heading').scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: join(output, 'maintenance-history-390.png'), fullPage: false });
});

test('maintenance summaries retain separate historical versions and stay readable after the operator page closes', async t => {
  const { f, game, page, context } = await browserFixture(t, 'maintenance-history-offline', { journal_maintenance_history: true });
  await page.locator('#history-import').click(); await until(() => !!f.manager.history.job);
  await page.close(); await finishHistory(f, game, [], [], { retention_summaries: [maintenanceRecord()] });
  const request = { request_id: 'maintenance-ui-second-version', bridge_boot_id: f.manager.state.value.bridge_boot_id,
    world_session_id: f.manager.state.value.world_session_id };
  assert.equal((await f.api('/history/imports', request)).status, 202);
  const value = structuredClone(samples['maintenance-summary-payload'].value.value); value.count = 5;
  await finishHistory(f, game, [], [], { retention_summaries: [maintenanceRecord({ value })] });
  f.manager.disconnect('maintenance-ui-offline');
  const reopened = await context.newPage(); await reopened.goto(f.base + '/mc-control');
  await reopened.getByText('已存 2 条历史', { exact: true }).waitFor();
  await reopened.locator('#history-filter').selectOption('retention_summaries');
  await reopened.waitForFunction(() => document.querySelectorAll('#history-entries .history-row').length === 2);
  const titles = await reopened.locator('#history-entries strong').allTextContents();
  assert.match(titles[0], /5 条/); assert.match(titles[1], /3 条/);
  assert.match(await reopened.locator('.history-archive').innerText(), /按时间查阅/);
  assert.equal(await reopened.locator('#history-import').isDisabled(), true);
});

test('closing the operator page preserves background import, and disabled offline history remains readable after reopening', async t => {
  const { f, game, page, context, output } = await browserFixture(t, 'history-background');
  await page.locator('#history-import').click(); await until(() => !!f.manager.history.job);
  const record = historyRecord(); await page.close(); await finishHistory(f, game, [record]);
  f.manager.disconnect('browser-offline-history');
  f.manager.configure({ expected_revision: f.manager.configRevision, patch: { enabled: false } });
  const reopened = await context.newPage(); await reopened.goto(f.base + '/mc-control');
  await reopened.getByText('已存 1 条历史', { exact: true }).waitFor();
  assert.equal(await reopened.locator('#history-import').isDisabled(), true);
  await reopened.locator('#history-entries').getByRole('button', { name: '查看原文' }).click();
  await reopened.locator('#history-view-dialog[open]').waitFor();
  assert.match(await reopened.locator('#history-view-record').innerText(), /event-example/);
  await reopened.screenshot({ path: join(output, 'history-offline-reopened.png'), fullPage: false });
});

test('expanded history keeps its paging window through later imports and explicit refresh traverses every record', async t => {
  const { f, game, page } = await browserFixture(t, 'history-continuity');
  const records = Array.from({ length: 48 }, (_, index) => historyRecord({ id: index + 1,
    payload: { ...samples['bridge-game_event'].value.payload, event_id: 'continuity-' + index, delivery_seq: index + 1 } }));
  async function importRecords(values) {
    await page.locator('#history-import').click(); await until(() => !!f.manager.history.job);
    for (let start = 0; start < values.length; start += 20) {
      const query = await historyQuery(f, game);
      await historyReply(f, game, query, historyPage(f, query, values.slice(start, start + 20),
        { through: values.length, complete: start + 20 >= values.length }));
    }
    const query = await historyQuery(f, game); await historyReply(f, game, query, historyPage(f, query));
    await page.getByText(`已存 ${values.length} 条历史`, { exact: true }).waitFor();
    await page.locator('#history-cancel').waitFor({ state: 'hidden' });
  }
  const rows = page.locator('#history-entries .history-row');
  const keys = () => rows.evaluateAll(values => values.map(value => value.dataset.history));
  await importRecords(records.slice(0, 23)); await page.locator('#more-history:visible').click();
  await page.waitForFunction(() => document.querySelectorAll('#history-entries .history-row').length === 23);
  const original = await keys();
  await importRecords(records);
  await page.waitForResponse(async response => {
    if (response.url() !== f.base + '/api/dsh/game/history/entries' || response.status() !== 200) return false;
    return (await response.json()).items[0]?.metadata.sequence === 48;
  });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.deepEqual(await keys(), original, 'expanded pages stay stable while new records arrive');
  await page.locator('#history-refresh').click();
  await page.waitForFunction(() => document.querySelector('#history-entries .history-row .code')?.textContent.includes('原序号 48'));
  assert.equal(await rows.count(), 20);
  await page.locator('#more-history').click();
  await page.waitForFunction(() => document.querySelectorAll('#history-entries .history-row').length === 40);
  await page.locator('#more-history').click();
  await page.waitForFunction(() => document.querySelectorAll('#history-entries .history-row').length === 48);
  assert.deepEqual(new Set(await keys()), new Set(records.map(record => record.info.record_key)));
});
