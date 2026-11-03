import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { terminalTask } from './game-narration-fixture.mjs';
import { until } from './game-fixture.mjs';
import { withPage, output, skip } from './mc-narration-browser-fixture.mjs';

test('the real response UI safely displays audience text, cancels through CAS and fits a phone', { skip }, async t => {
  await withPage(t, 'response-ui', async (f, page, report) => {
    const { item, key } = await f.comment('<img src=x onerror="window.inboxInjected=1">这条问题');
    await page.goto(f.base + '/mc-control');
    const card = page.locator('[data-narration="' + item.narration_id + '"]'); await card.waitFor();
    assert((await card.textContent()).includes('<img src=x')); assert.equal(await card.locator('img').count(), 0);
    assert.equal(await page.evaluate(() => window.inboxInjected), undefined);
    await page.screenshot({ path: join(output, 'fixture-response-desktop.png'), fullPage: true });
    await card.getByRole('button', { name: '取消回应', exact: true }).click();
    await until(() => f.manager.narration.get(item.narration_id).state === 'cancelled');
    await page.waitForFunction(id => document.querySelector('[data-narration="' + id + '"]')?.textContent.includes('导播已取消'), item.narration_id);
    assert.equal(f.room.store.message(key).answered, false);
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
    await page.screenshot({ path: join(output, 'fixture-response-phone.png'), fullPage: true });
    report.checks = ['plain_text_only', 'cas_cancel_actual_api', 'cancel_is_not_answered', 'desktop_and_phone'];
  });
});

test('a real revision conflict stays visible and does not report a response cancelled', { skip }, async t => {
  await withPage(t, 'response-conflict', async (f, page, report) => {
    const { item } = await f.comment('这条回应会在操作前更新。'); await page.goto(f.base + '/mc-control');
    const card = page.locator('[data-narration="' + item.narration_id + '"]'); await card.waitFor();
    await page.route('**/api/dsh/game/narration/' + item.narration_id + '/cancel', async route => {
      f.manager.narration.save(f.manager.narration.get(item.narration_id), { reason: 'FIXTURE_CONCURRENT_UPDATE' }); await route.continue();
    });
    await card.getByRole('button', { name: '取消回应', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('notice').textContent.includes('回应记录已更新'));
    assert.equal(f.manager.narration.get(item.narration_id).state, 'pending');
    assert(!(await page.locator('#notice').textContent()).includes('已取消该回应'));
    report.checks = ['actual_409_response', 'localized_conflict', 'no_false_cancel'];
  });
});

test('active responses remain visible beyond the first history page without duplicate cards', { skip }, async t => {
  await withPage(t, 'response-pagination', async (f, page, report) => {
    const first = await f.comment('仍在等候的早期问题');
    for (let i = 0; i < 25; i++) {
      const { item } = await f.comment('历史问题 ' + i);
      f.manager.narration.cancel(item.narration_id, { expected_revision: item.revision, reason: 'fixture_history' });
    }
    await page.goto(f.base + '/mc-control');
    await page.locator('[data-narration="' + first.item.narration_id + '"]').waitFor();
    assert((await page.locator('#narration-count').textContent()).includes('1 条处理中'));
    await page.locator('#more-narration').click();
    await page.waitForFunction(() => document.querySelectorAll('[data-narration]').length === 26);
    const ids = await page.locator('[data-narration]').evaluateAll(cards => cards.map(card => card.dataset.narration));
    assert.equal(new Set(ids).size, 26); report.checks = ['active_items_outside_first_page', 'history_pagination', 'deduplicated_cards'];
  });
});

test('task feedback changes to answered only after the actual formal completion receipt', { skip }, async t => {
  await withPage(t, 'response-task-feedback', async (f, page, report) => {
    const { key } = await f.comment('建议 采集 minecraft:oak_log 4');
    const suggestion = f.manager.suggestions.page().items.find(value => value.source_event_ids.includes(key));
    const approved = f.manager.suggestions.decision(suggestion.suggestion_id, { request_id: 'approve-ui-result', expected_revision: suggestion.revision, action: 'accept', reason: 'fixture_review' });
    const { item } = await terminalTask(f, { outcome: 'cancelled', requestPatch: { suggestion_ref: { suggestion_id: approved.suggestion_id, expected_revision: approved.revision } } });
    for (const other of f.manager.narration.open()) if (other.narration_id !== item.narration_id)
      f.manager.narration.cancel(other.narration_id, { expected_revision: other.revision, reason: 'fixture_select_result' });
    await page.goto(f.base + '/mc-control');
    await page.locator('#suggestion-filter').selectOption('all');
    const card = page.locator('[data-suggestion="' + approved.suggestion_id + '"]'); await card.waitFor();
    assert((await card.textContent()).includes('结果回应：等待安排'));
    await f.run(); await page.locator('#refresh').click();
    assert(!(await card.textContent()).includes('结果回应已播完')); assert.equal(f.room.store.message(key).answered, false);
    f.complete(); await new Promise(resolve => queueMicrotask(resolve));
    await page.waitForFunction(id => document.querySelector('[data-suggestion="' + id + '"]')?.textContent.includes('结果回应已播完'), approved.suggestion_id);
    assert.equal(f.room.store.message(key).answered, true);
    assert((await card.textContent()).includes('部分生效'));
    report.checks = ['real_game_api_feedback', 'partial_effect_preserved', 'not_answered_on_generation', 'formal_receipt_required'];
  });
});
