import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { gameFixture, sourceRoot, until } from './game-fixture.mjs';

const executablePath = 'C:/Program Files/Google/Chrome/Application/chrome.exe', playwright = join(sourceRoot, 'node_modules/playwright-core');
test('audience admin performs actual HTTP review, guarded dispatch, feedback and tied-vote promotion with responsive plain-text UI',
  { skip: !existsSync(executablePath) || !existsSync(playwright) }, async () => {
  const output = resolve(sourceRoot, process.env.MC_UI_EVIDENCE_ROOT || 'outputs/mc-validation/round-007'); mkdirSync(output, { recursive: true });
  const f = await gameFixture({ fakeClock: true, ui: true });
  const report = { classification: 'LOCAL_BROWSER_WITH_PROTOCOL_FIXTURE_ONLY', result: 'FAIL', browser_closed: false, page_errors: [], external_requests: [],
    real_minecraft: false, inference: false, public_broadcast: false }; let browser, context;
  try {
    const game = await f.connect();
    f.platformEvent({ text: '建议 采集 minecraft:oak_log 4' }); f.platformEvent({ text: '建议 采集 minecraft:oak_log 4' });
    const temp = join(sourceRoot, 'cache/mc-audience-browser'); mkdirSync(temp, { recursive: true });
    browser = await createRequire(import.meta.url)(playwright).chromium.launch({ executablePath, headless: true, env: { ...process.env, TEMP: temp, TMP: temp },
      args: ['--disable-gpu', '--disable-background-networking'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, reducedMotion: 'reduce' });
    await context.route(/^https?:\/\//, async route => { if (route.request().url().startsWith(f.base + '/')) await route.continue();
      else { report.external_requests.push(route.request().url()); await route.abort(); } });
    const page = await context.newPage(); page.on('pageerror', error => report.page_errors.push(error.message)); await page.goto(f.base + '/mc-control');
    const first = page.locator('#suggestions .audience-card').first(); await first.getByRole('button', { name: '采纳', exact: true }).waitFor();
    assert.match(await first.textContent(), /累计 2 条来源合并/); await first.getByRole('button', { name: '采纳', exact: true }).click();
    await page.locator('#suggestion-form [name=reason]').fill('已核对木材目标，采纳后等待明确允许自动游玩。');
    await page.getByRole('button', { name: '确认决定', exact: true }).click(); await page.locator('#suggestion-dialog').waitFor({ state: 'hidden' });
    assert.equal(f.manager.state.value.mode, 'PAUSED'); assert.equal(await first.getByRole('button', { name: '核验并执行', exact: true }).isDisabled(), true);
    await game.auto(); await first.getByRole('button', { name: '核验并执行', exact: true }).click();
    const query = await game.next('query', frame => frame.payload.request.kind === 'check_action'), operation = f.manager.operation(query.payload.operation_id);
    game.send('query_result', { ...operation, state: 'succeeded', result: { kind: 'check_action', world_session_id: game.observation.world_session_id, allowed: true } });
    await game.next('task_start'); const task = f.manager.tasks.active();
    game.send('task_update', { delivery_seq: 1, transition_seq: 2, task: { ...task, version: 2, state: 'succeeded', effect_status: 'verified', reason: null,
      evidence: [{ world_session_id: task.world_session_id, seq: f.manager.state.value.seq, kind: 'inventory', summary: 'TEST_FIXTURE_ONLY inventory received' }] } });
    await until(() => f.manager.tasks.raw(task.task_id).version === 2); await page.selectOption('#suggestion-filter', 'all');
    await first.locator('.audience-result').filter({ hasText: '成功 · 已验证' }).waitFor();
    await first.getByText('尚未安排口播', { exact: true }).waitFor(); assert.match(await first.textContent(), /成功 · 已验证/);
    await page.getByRole('button', { name: '新建投票', exact: true }).click(); await page.locator('#vote-form [name=title]').fill('接下来先准备哪种物资？');
    await page.getByRole('button', { name: '开始投票', exact: true }).click(); await page.locator('#vote-dialog').waitFor({ state: 'hidden' });
    const vote = f.manager.votes.active(); assert.equal(vote.options.length, 2);
    f.platformEvent({ text: '#1', user_key: 'one' }); f.platformEvent({ text: '#2', user_key: 'two' });
    await until(() => f.manager.votes.get(vote.vote_id).tally_version === 2); await page.getByRole('button', { name: '结束投票', exact: true }).click();
    await page.getByRole('button', { name: '平票选择：先收集木材', exact: true }).click();
    await page.getByRole('button', { name: '生成待审核建议', exact: true }).click();
    await until(() => !!f.manager.votes.get(vote.vote_id).suggestion_id);
    assert.equal(f.manager.store.list('task').items.length, 1, 'vote promotion is not task execution');
    const promoted = f.manager.suggestions.get(f.manager.votes.get(vote.vote_id).suggestion_id); assert.equal(promoted.state, 'proposed');
    await page.locator(`[data-suggestion="${promoted.suggestion_id}"]`).waitFor();
    // An operator-defined label is shown as text, never as DOM or a remote image.
    const injection = '<img src=x onerror=alert(1)>', saved = f.manager.votes.get(vote.vote_id); saved.title = injection;
    f.manager.store.put('vote', saved); f.manager.publish('vote', saved);
    await page.getByRole('heading', { name: injection, exact: true }).waitFor(); assert.equal(await page.locator('#votes img').count(), 0);
    saved.title = '接下来先准备哪种物资？'; f.manager.store.put('vote', saved); f.manager.publish('vote', saved);
    await page.getByRole('heading', { name: saved.title, exact: true }).waitFor();
    await page.screenshot({ path: join(output, 'mc-audience-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 }); await page.screenshot({ path: join(output, 'mc-audience-mobile.png'), fullPage: true });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.equal(await page.locator('audio,video,iframe').count(), 0); assert.deepEqual(report.page_errors, []); assert.deepEqual(report.external_requests, []);
    writeFileSync(join(output, 'mc-audience-accessibility.txt'), await page.locator('main').ariaSnapshot());
    game.socket.terminate(); await until(() => !f.manager.state.connected); await page.reload();
    await page.getByRole('button', { name: '新建投票', exact: true }).waitFor(); assert.equal(await page.getByRole('button', { name: '新建投票', exact: true }).isDisabled(), true);
    assert.equal(await page.getByRole('button', { name: '采纳', exact: true }).isDisabled(), true);
    assert.deepEqual(report.page_errors, []); report.result = 'PASS'; report.checks = ['proposal merging', 'HTTP review retains PAUSED', 'preflight query then one linked task',
      'verified fixture task feedback explicitly not spoken', 'HTTP vote create and close', 'operator resolves tie', 'winner promotion does not execute',
      'untrusted label plain text', 'desktop1440/mobile390 no horizontal overflow', 'disconnect disables review/creation', 'no media player or external request'];
  } catch (error) { report.error = String(error.stack || error); try { const page = context?.pages()[0]; if (page) report.visible_form_errors = await page.locator('[id$="-error"]').allTextContents(); } catch {} throw error; }
  finally { if (context) await context.close(); if (browser) { await browser.close(); report.browser_closed = !browser.isConnected(); }
    await f.close(); report.recorded_at = new Date().toISOString(); writeFileSync(join(output, 'mc-audience-browser.json'), JSON.stringify(report, null, 2) + '\n');
    assert(report.browser_closed || !browser); }
});
