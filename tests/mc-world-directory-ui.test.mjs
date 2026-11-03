import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { gameFixture, samples, sourceRoot, until } from './game-fixture.mjs';

const executablePath = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const playwright = join(sourceRoot, 'node_modules/playwright-core');
const options = { skip: !existsSync(executablePath) || !existsSync(playwright), timeout: 90000 };

async function browserCase(name, check) {
  const output = resolve(sourceRoot, process.env.MC_UI_EVIDENCE_ROOT || 'outputs/mc-validation/round-014', name);
  const temp = join(sourceRoot, 'cache', name); mkdirSync(output, { recursive: true }); mkdirSync(temp, { recursive: true });
  const f = await gameFixture({ fakeClock: true, ui: true });
  const report = { classification: 'LOCAL_BROWSER_WITH_PROTOCOL_FIXTURE_ONLY', result: 'FAIL', browser_closed: false,
    page_errors: [], external_requests: [], checks: [], real_minecraft: false, inference: false, public_broadcast: false };
  const releases = []; let browser, context;
  try {
    browser = await createRequire(import.meta.url)(playwright).chromium.launch({ executablePath, headless: true,
      env: { ...process.env, TEMP: temp, TMP: temp }, args: ['--disable-gpu', '--disable-background-networking'] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, reducedMotion: 'reduce' });
    context.setDefaultTimeout(6000);
    await context.route(/^https?:\/\//, async route => {
      if (route.request().url().startsWith(f.base + '/')) await route.continue();
      else { report.external_requests.push(route.request().url()); await route.abort(); }
    });
    const page = await context.newPage(); page.on('pageerror', error => report.page_errors.push(error.message));
    const game = await f.connect();
    await check({ f, game, page, report, output, releases });
    assert.equal(await page.locator('audio,video,iframe').count(), 0);
    assert.deepEqual(report.page_errors, []); assert.deepEqual(report.external_requests, []);
    assert.equal(game.messages.filter(frame => ['task_start', 'control_request'].includes(frame.type)).length, 0);
    report.result = 'PASS';
  } catch (error) { report.error = String(error.stack || error); throw error; }
  finally {
    for (const release of releases) release();
    try { if (context) await context.close(); }
    finally {
      try {
        if (browser) { report.remaining_contexts = browser.contexts().length; await browser.close(); report.browser_closed = !browser.isConnected(); }
      } finally {
        await f.close(); report.recorded_at = new Date().toISOString();
        writeFileSync(join(output, 'browser-report.json'), JSON.stringify(report, null, 2) + '\n');
      }
    }
    assert(report.browser_closed || !browser); assert.equal(report.remaining_contexts ?? 0, 0);
  }
}

const contextFor = f => ({ request_id: 'world-ui-' + crypto.randomUUID(), bridge_boot_id: f.manager.state.value.bridge_boot_id,
  world_session_id: f.manager.state.value.world_session_id });
async function addBase(f, id, label) {
  const result = await f.api('/worlds/' + id + '/bases', { ...contextFor(f), expected_world_revision: f.manager.worlds.get(id).revision, label, radius: 8 });
  assert.equal(result.status, 201); return result.value;
}
async function expectView(page, id, label) {
  await page.waitForFunction(({ id, label }) => document.getElementById('view-world-context').textContent.startsWith(id + ' ·') &&
    document.getElementById('view-world-label').textContent === label, { id, label });
}

test('world directory uses actual HTTP for names, observed bases, selection, archive, checkpoints, conflicts and offline history', options, async () => {
  await browserCase('world-directory-browser', async ({ f, game, page, report, output }) => {
    const id = game.observation.world_id;
    await page.goto(f.base + '/mc-control'); await expectView(page, id, f.manager.worlds.get(id).local_label);
    const label = '初夏世界 <img src=x onerror=alert(1)>';
    await page.locator('#rename-world').click(); await page.locator('#world-label-form [name=label]').fill(label);
    await page.getByRole('button', { name: '保存名称', exact: true }).click();
    await page.locator('#world-label-dialog').waitFor({ state: 'hidden' }); await expectView(page, id, label);
    assert.equal(await page.locator('#world-heading').textContent(), label); assert.equal(await page.locator('img').count(), 0);
    report.checks.push('world label CAS and untrusted label rendered as plain text');

    async function register(label) {
      await page.locator('#new-base').click(); await page.locator('#base-form [name=label]').fill(label);
      await page.locator('#base-form [name=radius]').fill('12'); await page.getByRole('button', { name: '登记基地', exact: true }).click();
      await page.locator('#base-dialog').waitFor({ state: 'hidden' });
      await page.locator('#bases').getByRole('heading', { name: label, exact: true }).waitFor();
      return f.manager.worlds.page('base', { worldId: id }).items.find(base => base.label === label);
    }
    const first = await register('河边营地'), second = await register('矿洞入口');
    assert.deepEqual(first.position, game.observation.player.position); assert.equal(first.radius, 12);
    const firstCard = page.locator(`[data-base="${first.base_id}"]`), secondCard = page.locator(`[data-base="${second.base_id}"]`);
    await firstCard.getByRole('button', { name: '设为活动基地', exact: true }).click();
    await page.locator('#base-decision-form').getByRole('button', { name: '确认记录', exact: true }).click();
    await firstCard.locator('.badge').getByText('活动基地', { exact: true }).waitFor();
    assert.equal(f.manager.worlds.get(id).active_base_id, first.base_id);
    await secondCard.getByRole('button', { name: '归档基地', exact: true }).click();
    await page.locator('#base-decision-form').getByRole('button', { name: '确认记录', exact: true }).click();
    await secondCard.getByText('已归档', { exact: true }).waitFor();
    assert.equal(f.manager.worlds.base(id, second.base_id).archived, true);
    report.checks.push('observed position only; base registration/selection/archive create no movement or control');

    await page.locator('#new-checkpoint').click(); await page.locator('#checkpoint-form [name=reason]').fill('下次开播核对物资');
    await page.getByRole('button', { name: '保存记录', exact: true }).click();
    await page.locator('#checkpoints').getByRole('button', { name: '查看检查点', exact: true }).click();
    await page.locator('#checkpoint-view-dialog').waitFor({ state: 'visible' });
    assert.match(await page.locator('#checkpoint-view-refs').textContent(), /关联 1 处基地、0 项历史任务/);
    assert.match(await page.locator('#checkpoint-view-dialog').textContent(), /保存时的历史观测/);
    assert.equal(await page.locator('#checkpoint-view-dialog button').count(), 1);
    await page.keyboard.press('Escape');
    report.checks.push('checkpoint read-only history and references; no restore or media controls');

    await page.locator('#rename-world').click(); await page.locator('#world-label-form [name=label]').fill('过时表单');
    const changed = await f.api('/worlds/' + id + '/label', { request_id: 'another-operator-label',
      expected_revision: f.manager.worlds.get(id).revision, local_label: '另一位导播已更新' }); assert.equal(changed.status, 200);
    await page.getByRole('button', { name: '保存名称', exact: true }).click();
    await page.locator('#world-label-error').getByText('世界或基地记录已更新，请刷新后再核对。', { exact: true }).waitFor();
    assert.equal(f.manager.worlds.get(id).local_label, '另一位导播已更新'); await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'rename-world');
    report.checks.push('stale open form cannot overwrite another operator; keyboard close returns focus');

    await page.screenshot({ path: join(output, 'desktop.png'), fullPage: true });
    writeFileSync(join(output, 'accessibility.txt'), await page.locator('main').ariaSnapshot());
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: join(output, 'mobile.png'), fullPage: true });
    game.socket.terminate(); await until(() => !f.manager.state.connected);
    await page.waitForFunction(() => document.getElementById('new-base').disabled && document.getElementById('new-checkpoint').disabled &&
      [...document.querySelectorAll('#bases button')].every(button => button.disabled));
    await page.locator('#rename-world').click(); await page.locator('#world-label-form [name=label]').fill('离线世界记录');
    await page.getByRole('button', { name: '保存名称', exact: true }).click(); await expectView(page, id, '离线世界记录');
    assert.equal(f.manager.state.connected, false);
    report.checks.push('desktop1440/mobile390 no overflow; disconnect disables every base action while permitting ledger rename');
  });
});

test('historical world selection persists across refresh/reload and discards a delayed old-world response', options, async () => {
  await browserCase('world-history-race-browser', async ({ f, game, page, report, releases }) => {
    const oldId = game.observation.world_id, oldLabel = f.manager.worlds.get(oldId).local_label;
    await addBase(f, oldId, '旧世界基地');
    assert.equal((await f.api('/worlds/' + oldId + '/checkpoints', { ...contextFor(f), reason: '旧世界检查点' })).status, 201);
    const create = structuredClone(samples['world-goal-create'].value);
    Object.assign(create, contextFor(f), { expected_world_revision: f.manager.worlds.get(oldId).revision, title: '旧世界目标' });
    assert.equal((await f.api('/worlds/' + oldId + '/goals', create)).status, 201);
    const newId = 'world-directory-current', newSession = 'session-directory-current';
    game.snapshot({ world_id: newId, world_session_id: newSession, seq: 1 }); await until(() => f.manager.state.value.world_id === newId);
    await addBase(f, newId, '当前世界基地');
    for (let i = 0; i < 30; i++) {
      const task = structuredClone(samples['task-complete'].value);
      Object.assign(task, { task_id: 'directory-ui-task-' + i, request_id: 'directory-ui-request-' + i,
        world_id: i < 25 ? oldId : newId, world_session_id: i < 25 ? create.world_session_id : newSession });
      f.manager.store.put('task', task);
    }
    // More than one world page: the two relevant records must still be discoverable.
    for (let i = 0; i < 22; i++) {
      const world_id = 'directory-archive-' + i;
      game.snapshot({ world_id, world_session_id: 'directory-session-' + i, seq: 1 });
      await until(() => f.manager.state.value.world_id === world_id);
    }
    game.snapshot({ world_id: newId, world_session_id: newSession + '-return', seq: 1 }); await until(() => f.manager.state.value.world_id === newId);
    const newLabel = f.manager.worlds.get(newId).local_label;
    await page.goto(f.base + '/mc-control'); await expectView(page, newId, newLabel);
    assert.equal(await page.locator('#tasks tr[data-task]').count(), 5);
    await page.locator('#more-worlds').click(); await page.locator(`#world-picker option[value="${oldId}"]`).waitFor({ state: 'attached' });
    await page.selectOption('#world-picker', oldId); await expectView(page, oldId, oldLabel);
    assert.equal(await page.locator('#world-heading').textContent(), newLabel);
    assert.equal(await page.locator('#view-kind').textContent(), '历史记录');
    await page.getByRole('heading', { name: '旧世界目标', exact: true }).waitFor();
    await page.locator('#checkpoints').getByRole('heading', { name: '旧世界检查点', exact: true }).waitFor();
    assert.equal(await page.locator('.audience').isVisible(), false);
    for (const selector of ['#new-base', '#new-checkpoint', '#new-goal', '[data-mode="AUTO"]']) assert(await page.locator(selector).isDisabled());
    assert(await page.locator('#bases button').first().isDisabled());
    assert.equal(await page.locator('#tasks tr[data-task]').count(), 20);
    await page.locator('#more-tasks').click(); await page.waitForFunction(() => document.querySelectorAll('#tasks tr[data-task]').length === 25);
    await page.locator('#refresh').click(); await expectView(page, oldId, oldLabel);
    assert.equal(await page.locator('#tasks tr[data-task]').count(), 25); assert.equal(await page.locator('#more-tasks').isVisible(), false);
    await page.reload(); await expectView(page, oldId, oldLabel); assert.equal(await page.locator('#world-picker').inputValue(), oldId);
    report.checks.push('paginated world directory; scoped tasks/goals/sessions/bases/checkpoints; historical control guards; selection persists');

    let held = false, release;
    const pending = new Promise(resolve => { release = resolve; }); releases.push(release);
    await page.route(f.base + '/api/dsh/game/worlds/' + oldId + '/goals', async route => {
      if (!held) { held = true; await pending; } await route.continue();
    });
    f.manager.publish('world', f.manager.worlds.get(oldId)); await until(() => held);
    await page.evaluate(() => {
      window.staleWorldRows = [];
      window.worldRowObserver = new MutationObserver(() => {
        if (document.getElementById('world-picker').value !== 'world-directory-current') return;
        for (const row of document.querySelectorAll('#tasks tr[data-task]'))
          if (!row.textContent.includes('world-directory-current')) window.staleWorldRows.push(row.dataset.task);
      });
      window.worldRowObserver.observe(document.getElementById('tasks'), { childList: true, subtree: true });
    });
    await page.selectOption('#world-picker', newId); release(); await expectView(page, newId, newLabel);
    await page.waitForFunction(() => document.querySelectorAll('#tasks tr[data-task]').length === 5);
    assert.deepEqual(await page.evaluate(() => window.staleWorldRows), []);
    assert.equal(await page.getByRole('heading', { name: '旧世界目标', exact: true }).count(), 0);
    assert.equal(await page.locator('#checkpoints .record-card').count(), 0);
    assert.equal(await page.locator('#new-base').isDisabled(), false);
    await page.evaluate(() => window.worldRowObserver.disconnect());
    report.checks.push('late old-world scoped response discarded without even transient foreign task rows; live controls restored');

    const oldPath = f.base + '/api/dsh/game/worlds/' + oldId + '/goals';
    await page.unroute(oldPath); let failedHeld = false, failRelease;
    const failedPending = new Promise(resolve => { failRelease = resolve; }); releases.push(failRelease);
    await page.route(oldPath, async route => {
      if (!failedHeld) { failedHeld = true; await failedPending;
        await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'GAME_WORLD_NOT_FOUND' }) });
      } else await route.continue();
    });
    // Pinning an older record after reload also exercises the selected-record option outside the first page.
    await page.locator('#more-worlds').click();
    await page.selectOption('#world-picker', oldId); await until(() => failedHeld);
    await page.locator('#follow-world').click(); failRelease(); await expectView(page, newId, newLabel);
    assert.equal(await page.locator('#notice').isVisible(), false);
    assert.equal(await page.locator('#new-base').isDisabled(), false);
    report.checks.push('a failed late response from the prior selection cannot clear live state or display an obsolete failure');

    await page.evaluate(() => sessionStorage.setItem('mc-control.world', 'world-absent'));
    await page.reload(); await page.locator('#notice').getByText('这份世界记录已不存在，请返回当前实况。', { exact: true }).waitFor();
    assert.equal(await page.locator('#world-heading').textContent(), newLabel);
    await page.locator('#follow-world').click(); await expectView(page, newId, newLabel);
    assert.equal(await page.locator('#world-picker').inputValue(), '');
    assert.equal(f.manager.state.value.world_id, newId);
    report.checks.push('missing saved world has an explicit recovery action; browsing never changes actual game world');
  });
});
