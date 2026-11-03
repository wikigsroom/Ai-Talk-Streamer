import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { withPage, output, skip } from './mc-narration-browser-fixture.mjs';
import { until } from './game-fixture.mjs';

async function settings(page) {
  await page.locator('.narration-settings > summary').click();
  await page.locator('#narration-settings-form input[name=merge_window_ms]').waitFor({ state: 'visible' });
  await page.waitForFunction(() => /^\d+$/.test(document.getElementById('narration-settings-form').dataset.revision || ''));
  return page.locator('#narration-settings-form');
}

test('scheduling settings save through the real CAS endpoint, survive page reload and fit an open phone form', { skip }, async t => {
  await withPage(t, 'scheduler-settings', async (f, page, report) => {
    await page.goto(f.base + '/mc-control'); const form = await settings(page);
    await form.locator('[name=critical_interrupt]').uncheck();
    for (const [name, value] of Object.entries({ merge_window_ms: '0.5', aging_step_ms: '1', topic_cooldown_ms: '4', interrupt_fresh_ms: '1', interrupt_cooldown_ms: '5' }))
      await form.locator('[name=' + name + ']').fill(value);
    await page.locator('#save-narration-settings').click();
    await page.waitForFunction(() => document.getElementById('notice').textContent === '回应调度设置已应用。');
    assert.deepEqual(f.manager.config.narration, { enabled: true, merge_window_ms: 500, aging_step_ms: 1000,
      topic_cooldown_ms: 4000, critical_interrupt: false, interrupt_fresh_ms: 1000, interrupt_cooldown_ms: 5000 });
    await page.reload(); await settings(page);
    assert.equal(await form.locator('[name=merge_window_ms]').inputValue(), '0.5');
    assert.equal(await form.locator('[name=critical_interrupt]').isChecked(), false);
    await page.locator('.narration-settings').scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(output, 'scheduler-settings-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.locator('#save-narration-settings').isVisible());
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: join(output, 'scheduler-settings-phone.png'), fullPage: true });
    report.checks = ['real_config_cas', 'seconds_to_milliseconds', 'reload_persistence', 'phone_open_form_no_overflow'];
  });
});

test('unsaved scheduling edits survive SSE refresh and a conflicting save preserves both the draft and the other operator settings', { skip }, async t => {
  await withPage(t, 'scheduler-settings-conflict', async (f, page, report) => {
    await page.goto(f.base + '/mc-control'); const form = await settings(page);
    const originalRevision = await form.getAttribute('data-revision');
    await form.locator('[name=merge_window_ms]').fill('1');
    await Promise.all([
      page.waitForResponse(response => response.url() === f.base + '/api/dsh/game/config' && response.request().method() === 'GET'),
      Promise.resolve().then(() => f.manager.configure({ expected_revision: f.manager.configRevision, patch: { narration: { critical_interrupt: false } } }))
    ]);
    assert.equal(await form.locator('[name=merge_window_ms]').inputValue(), '1');
    assert.equal(await form.getAttribute('data-revision'), originalRevision);
    await Promise.all([
      page.waitForResponse(response => response.url() === f.base + '/api/dsh/game/config' && response.status() === 409),
      page.locator('#save-narration-settings').click()
    ]);
    await page.waitForFunction(() => document.getElementById('notice').textContent.includes('设置已被其他操作更新'));
    assert.equal(f.manager.config.narration.merge_window_ms, 3000); assert.equal(f.manager.config.narration.critical_interrupt, false);
    assert.equal(await form.locator('[name=merge_window_ms]').inputValue(), '1');
    await page.locator('#reset-narration-settings').click();
    assert.equal(await form.locator('[name=merge_window_ms]').inputValue(), '3');
    assert.equal(await form.locator('[name=critical_interrupt]').isChecked(), false);
    report.checks = ['sse_does_not_overwrite_draft', 'captured_revision_cas', 'actual_409', 'explicit_reload_current'];
  });
});

test('merged sources render once as plain text and cancelling the shared candidate answers neither source', { skip }, async t => {
  await withPage(t, 'scheduler-merged-sources', async (f, page, report) => {
    const a = await f.comment('<img src=x onerror="window.mergedInjected=1">现在有多少木头？'), b = await f.comment('<img src=x onerror="window.mergedInjected=1">现在有多少木头？');
    await page.goto(f.base + '/mc-control'); const card = page.locator('[data-narration="' + a.item.narration_id + '"]');
    await card.waitFor(); assert.equal(await page.locator('[data-narration]').count(), 1);
    assert((await card.textContent()).includes('已合并 2 条相同主题记录'));
    assert((await card.textContent()).includes('<img src=x')); assert.equal(await card.locator('img').count(), 0);
    assert.equal(await page.evaluate(() => window.mergedInjected), undefined);
    await card.getByRole('button', { name: '取消回应' }).click();
    await until(() => f.manager.narration.get(a.item.narration_id).state === 'cancelled');
    assert.equal(f.room.store.message(a.key).answered, false); assert.equal(f.room.store.message(b.key).answered, false);
    report.checks = ['one_shared_card', 'all_sources_linked', 'plain_text_only', 'shared_cas_cancel_not_answered'];
  });
});

test('critical interruption has localized status and does not change game control or manufacture completion', { skip }, async t => {
  await withPage(t, 'scheduler-critical-status', async (f, page, report) => {
    const first = await f.comment(); await f.run(); const mode = f.manager.state.value.mode;
    await page.goto(f.base + '/mc-control');
    f.game.send('game_event', { event_id: 'ui-critical', delivery_seq: 1, world_session_id: f.game.observation.world_session_id,
      seq: 1, occurred_at: new Date(f.manager.wall()).toISOString(), kind: 'damage', severity: 'critical', task_id: null, data: { health: 2 } });
    await until(() => f.manager.narration.open().some(item => item.kind === 'game_event')); f.manager.narration.tick();
    const card = page.locator('[data-narration="' + first.item.narration_id + '"]');
    await page.waitForFunction(id => document.querySelector('[data-narration="' + id + '"]')?.textContent.includes('因严重游戏危险'), first.item.narration_id);
    assert((await page.locator('#narration-scheduling').textContent()).includes('已请求中断普通回应'));
    assert((await card.textContent()).includes('已取消')); assert.equal(f.room.store.message(first.key).answered, false);
    assert.equal(f.manager.state.value.mode, mode); assert.equal(f.manager.tasks.active(), null);
    report.checks = ['localized_preemption_reason', 'actual_cancel_state', 'no_game_mode_change', 'no_false_answer'];
  });
});

test('turning automatic replies off from the page cancels the existing reply and displays the applied state', { skip }, async t => {
  await withPage(t, 'scheduler-disable', async (f, page, report) => {
    const first = await f.comment(); await f.run(); await page.goto(f.base + '/mc-control'); const form = await settings(page);
    await form.locator('[name=enabled]').uncheck(); await page.locator('#save-narration-settings').click();
    await page.waitForFunction(() => document.getElementById('narration-scheduling').textContent.includes('自动回应已关闭'));
    assert.equal(f.manager.config.narration.enabled, false); assert.equal(f.state.active(), undefined);
    assert.equal(f.room.store.message(first.key).answered, false);
    assert.equal(f.manager.narration.get(first.item.narration_id).reason, 'GAME_NARRATION_DISABLED');
    report.checks = ['real_disable_config', 'inflight_cancelled', 'visible_applied_state', 'not_marked_answered'];
  });
});
