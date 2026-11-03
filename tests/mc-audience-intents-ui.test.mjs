import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { gameFixture, sourceRoot, until } from './game-fixture.mjs';

const chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe', playwright = join(sourceRoot, 'node_modules/playwright-core');
const skip = !existsSync(chrome) || !existsSync(playwright);
async function withPage(t, name, run) {
  const f = await gameFixture({ fakeClock: true, ui: true }), output = resolve(process.env.MC_INTENT_EVIDENCE_ROOT || 'outputs/mc-intent-ui');
  mkdirSync(output, { recursive: true });
  const report = { classification: 'OWNED_BROWSER_WITH_HTTP_WS_SQLITE_FIXTURE_ONLY', result: 'FAIL', page_errors: [], external_requests: [], browser_closed: false,
    real_minecraft: false, real_models: false, official_client: false, public_broadcast: false };
  let browser, context;
  try {
    f.game = await f.connect(); f.bridge.health = () => ({ persona_injection_ready: true });
    f.bridge.channel = { snapshot: () => ({ model: 'fixture' }) };
    f.bridge.host = { generate: options => options.tools('stream_audience_intent_result', { kind: 'clarify', goal: null, question: '想采什么、要多少个？' }) };
    f.manager.configure({ expected_revision: 0, patch: { audience_intents: { enabled: true } } });
    const temp = join(sourceRoot, 'cache/mc-intent-browser'); mkdirSync(temp, { recursive: true });
    browser = await createRequire(import.meta.url)(playwright).chromium.launch({ executablePath: chrome, headless: true,
      env: { ...process.env, TEMP: temp, TMP: temp }, args: ['--disable-gpu','--disable-background-networking'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, reducedMotion: 'reduce' });
    await context.route(/^https?:\/\//, async route => { if (route.request().url().startsWith(f.base + '/')) await route.continue(); else { report.external_requests.push(route.request().url()); await route.abort(); } });
    const page = await context.newPage(); page.on('pageerror', error => report.page_errors.push(error.message));
    await run(f, page, report, output);
    assert.deepEqual(report.page_errors, []); assert.deepEqual(report.external_requests, []); report.result = 'PASS';
  } catch(error) { report.error = String(error.stack || error); throw error; }
  finally {
    try { await context?.close(); } finally {
      try { await browser?.close(); report.browser_closed = !browser?.isConnected(); } finally {
        await f.close(); writeFileSync(join(output, name + '.json'), JSON.stringify(report, null, 2) + '\n');
      }
    }
  }
}
test('natural suggestion console resolves a clarification through HTTP without accepting, executing or exposing unsafe markup', { skip }, async t => withPage(t, 'clarification', async (f, page, report, output) => {
  f.platformEvent({ text: '去弄点木头吧' }); await f.manager.intents.tick(); const value = f.manager.intents.rows().at(-1);
  value.question = '<img src=x onerror=alert(1)> 想采哪种木头？'; f.manager.store.put('audience_intent', value);
  await page.goto(f.base + '/mc-control'); const card = page.locator(`[data-intent="${value.audience_intent_id}"]`);
  await card.getByRole('button', { name: '补全为待审核建议' }).waitFor(); assert.equal(await card.locator('img').count(), 0);
  await card.getByRole('button', { name: '补全为待审核建议' }).click();
  assert.equal(await page.locator('#intent-goal [name=count]').inputValue(), '', 'quantity requires an explicit operator value');
  await page.locator('#intent-goal [name=item_id]').fill('minecraft:oak_log'); await page.locator('#intent-goal [name=count]').fill('8');
  await page.getByRole('button', { name: '保存为待审核建议', exact: true }).click(); await page.locator('#intent-dialog').waitFor({ state: 'hidden' });
  const suggestion = f.manager.suggestions.pending()[0]; assert.equal(suggestion.state, 'proposed'); assert.equal(suggestion.goal.count, 8);
  await page.locator(`[data-suggestion="${suggestion.suggestion_id}"]`).waitFor(); assert.equal(f.manager.state.value.mode, 'PAUSED'); assert.equal(f.manager.tasks.active(), null);
  await page.selectOption('#intent-filter', 'all'); await card.getByText('已生成待审核建议', { exact: true }).waitFor();
  await page.locator('#intent-heading').scrollIntoViewIfNeeded(); await page.screenshot({ path: join(output, 'intent-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 }); await page.screenshot({ path: join(output, 'intent-mobile.png'), fullPage: true });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)); assert.equal(await page.locator('audio,video,iframe').count(), 0);
  writeFileSync(join(output, 'intent-accessibility.txt'), await page.locator('.intent-panel').ariaSnapshot());
  report.checks = ['HTTP typed clarification with explicit quantity','untrusted question plain text','proposal remains reviewed separately','no AUTO or task','desktop1440/mobile390','no media consumer'];
}));
test('natural suggestion settings preserve unsaved input, reject stale revision and apply only explicit refresh-reviewed settings', { skip }, async t => withPage(t, 'settings', async (f, page, report) => {
  await page.goto(f.base + '/mc-control'); const checkbox = page.locator('#intent-settings-form [name=enabled]');
  await checkbox.waitFor(); await page.waitForFunction(() => document.querySelector('#intent-settings-form').dataset.revision === '1');
  await checkbox.uncheck(); f.manager.configure({ expected_revision: 1, patch: { audience_intents: { max_call_ms: 7000 } } });
  await page.getByRole('button', { name: '刷新记录', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#narration-settings-form').dataset.revision === '2');
  assert.equal(await checkbox.isChecked(), false);
  await Promise.all([page.waitForResponse(response => response.url() === f.base + '/api/dsh/game/config' && response.status() === 409), page.getByRole('button', { name: '保存建议设置', exact: true }).click()]);
  await page.locator('#notice').filter({ hasText: '设置已被其他操作更新' }).waitFor(); assert.equal(f.manager.config.audience_intents.enabled, true);
  await page.getByRole('button', { name: '恢复已保存建议设置', exact: true }).click(); await page.waitForFunction(() => document.querySelector('#intent-settings-form').dataset.revision === '2');
  await checkbox.uncheck(); await page.getByRole('button', { name: '保存建议设置', exact: true }).click();
  await until(() => !f.manager.config.audience_intents.enabled); await page.getByText('自然语言建议设置已应用。', { exact: true }).waitFor();
  assert.equal(f.manager.config.audience_intents.max_call_ms, 7000); assert.equal(f.manager.state.value.mode, 'PAUSED');
  report.checks = ['unsaved enable value survives SSE refresh','CAS conflict does not overwrite new configuration','reload then explicit save','other intent settings preserved'];
}));
test('removed source and changed live room prevent obsolete clarification decisions and late list insertion', { skip }, async t => withPage(t, 'invalidation', async (f, page, report) => {
  const event = f.platformEvent({ text: '能不能采点木头？' }); await f.manager.intents.tick(); const value = f.manager.intents.rows().at(-1);
  await page.goto(f.base + '/mc-control'); const card = page.locator(`[data-intent="${value.audience_intent_id}"]`);
  await card.getByRole('button', { name: '补全为待审核建议' }).click();
  event.hidden = true; f.manager.suggestions.withdrawSources([event.event_key]);
  await page.locator('#intent-goal [name=item_id]').fill('minecraft:oak_log'); await page.locator('#intent-goal [name=count]').fill('4');
  await page.getByRole('button', { name: '保存为待审核建议', exact: true }).click(); await page.locator('#intent-error').filter({ hasText: /已更新|已处理|来源/ }).waitFor();
  assert.equal(f.manager.suggestions.pending().length, 0); await page.locator('[data-close=intent-dialog]').first().click();
  f.bridge.platforms.config.value.platforms.bilibili.room_id = '101'; f.manager.reconcileAudienceSources(); f.manager.publish('state', f.manager.state.view());
  await page.locator('#audience-room').filter({ hasText: '101' }).waitFor(); assert.equal(await page.locator('#intents [data-intent]').count(), 0);
  report.checks = ['source removed while dialog open cannot resolve','no suggestion created','room change clears old intent view'];
}));
test('expanded intent history keeps a stable window while new events arrive, then explicit refresh pages all unique records', { skip }, async t => withPage(t, 'pagination', async (f, page, report) => {
  const add=count=>{for(let index=0;index<count;index++){f.platformEvent({text:'自然建议 '+f.manager.intents.rows().length});const value=f.manager.intents.rows().at(-1);f.manager.intents.decision(value.audience_intent_id,{request_id:'dismiss-'+value.audience_intent_id,expected_revision:value.revision,action:'dismiss'});}};
  add(23);await page.goto(f.base+'/mc-control');await page.selectOption('#intent-filter','all');
  await page.waitForFunction(()=>document.querySelectorAll('#intents [data-intent]').length===20);
  await page.locator('#more-intents').click();await page.waitForFunction(()=>document.querySelectorAll('#intents [data-intent]').length===23);
  add(25);await page.getByRole('button',{name:'刷新记录',exact:true}).click();
  await page.locator('#intent-page-hint').filter({hasText:'已展开较早记录'}).waitFor();assert.equal(await page.locator('#intents [data-intent]').count(),23);
  await page.getByRole('button',{name:'刷新理解记录',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('#intents [data-intent]').length===20);
  await page.locator('#more-intents').click();await page.waitForFunction(()=>document.querySelectorAll('#intents [data-intent]').length===40);
  await page.locator('#more-intents').click();await page.waitForFunction(()=>document.querySelectorAll('#intents [data-intent]').length===48);
  const actual=await page.locator('#intents [data-intent]').evaluateAll(rows=>rows.map(row=>row.dataset.intent));
  assert.deepEqual([...actual].sort(),f.manager.intents.rows().map(value=>value.audience_intent_id).sort());assert.equal(new Set(actual).size,48);
  report.checks=['20 row first page','expanded 23 rows preserved after 25 new records','explicit refresh then all 48 unique ids without gaps'];
}));
