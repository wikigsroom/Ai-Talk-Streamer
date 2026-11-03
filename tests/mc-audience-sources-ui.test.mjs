import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { withPage, output, skip } from './mc-narration-browser-fixture.mjs';

const command='建议 采集 minecraft:oak_log 4';
async function add(f,user,extra={}){const {key}=await f.comment(command,{user_id:user,nickname:user,...extra});return f.manager.suggestions.page().items.find(v=>v.source_event_ids.includes(key));}
const configure=(f,moderation)=>f.room.configure({expected_revision:f.room.store.revision,patch:{moderation}});

test('audience page shows current events and distinct accounts, preserves stale approval for a real409 and fits a phone',{skip},async t=>withPage(t,'audience-current-support',async(f,page,report)=>{
  await add(f,'viewer-a');await add(f,'viewer-a');const value=await add(f,'viewer-b');await page.goto(f.base+'/mc-control');
  const card=page.locator('[data-suggestion="'+value.suggestion_id+'"]');await card.waitFor();
  await page.waitForFunction(id=>document.querySelector('[data-suggestion="'+id+'"]')?.textContent.includes('当前有效 3 条 · 可识别账号 2 个'),value.suggestion_id);
  await card.getByRole('button',{name:'采纳',exact:true}).click();await page.locator('#suggestion-form textarea').fill('核对当前有效来源');
  configure(f,{blocked_names:['viewer-a']});await page.waitForFunction(id=>document.querySelector('[data-suggestion="'+id+'"]')?.textContent.includes('当前有效 1 条 · 可识别账号 1 个'),value.suggestion_id);
  await page.locator('#suggestion-form button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('#suggestion-error').textContent.includes('建议已更新'));
  assert.equal(f.manager.suggestions.get(value.suggestion_id).state,'proposed');assert.equal(f.manager.tasks.active(),null);
  await page.locator('#suggestion-dialog button[data-close]').first().click();await page.screenshot({path:join(output,'audience-current-support-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
  await page.screenshot({path:join(output,'audience-current-support-phone.png'),fullPage:true});
  assert.match(await card.textContent(),/累计 3 条来源合并/);report.checks=['actual_room_filter_and_sse','events_vs_accounts','historical_count_preserved','actual_stale409','phone_no_overflow'];
}));

test('audience page distinguishes unknown identity and incomplete legacy coverage without rendering source text as HTML',{skip},async t=>withPage(t,'audience-legacy-support',async(f,page,report)=>{
  const value=await add(f,null,{nickname:'<img src=x onerror=BAD()>'}), prefix=value.suggestion_id+':';
  f.manager.store.run("DELETE FROM objects WHERE kind='audience_support_manifest' AND id=?",value.suggestion_id);
  const old={...value,support_count:50};delete old.support;f.manager.store.put('suggestion',old);
  await page.goto(f.base+'/mc-control');const card=page.locator('[data-suggestion="'+value.suggestion_id+'"]');await card.waitFor();
  assert.match(await card.textContent(),/当前有效 1 条 · 可识别账号 0 个 · 身份未知 1 条/);assert.match(await card.textContent(),/历史来源不完整/);assert.match(await card.textContent(),/累计 50 条来源合并/);
  assert.equal(await card.locator('img,script').count(),0);assert.equal(await page.evaluate(()=>window.BAD),undefined);
  configure(f,{blocked_words:['minecraft:oak_log']});await page.waitForFunction(id=>!document.querySelector('[data-suggestion="'+id+'"]'),value.suggestion_id);
  assert.equal(f.manager.suggestions.get(value.suggestion_id).state,'cancelled');report.checks=['unknown_identity_not_a_person','legacy_coverage_explicit','no_html_execution','last_source_filter_removes_active_card'];
}));

test('audience page marks temporary source unavailability as pending verification and recovers through actual SSE',{skip},async t=>withPage(t,'audience-source-unavailable',async(f,page,report)=>{
  const value=await add(f,'viewer-a');await page.goto(f.base+'/mc-control');const card=page.locator('[data-suggestion="'+value.suggestion_id+'"]');await card.waitFor();
  f.bridge.room=null;f.manager.suggestions.get(value.suggestion_id);await page.waitForFunction(id=>document.querySelector('[data-suggestion="'+id+'"]')?.textContent.includes('当前支持待核对'),value.suggestion_id);
  assert.equal(f.manager.suggestions.get(value.suggestion_id).state,'proposed');
  f.bridge.room=f.room;f.manager.reconcileAudienceSources();await page.waitForFunction(id=>document.querySelector('[data-suggestion="'+id+'"]')?.textContent.includes('当前有效 1 条'),value.suggestion_id);
  report.checks=['unavailable_is_unknown','no_cancel_on_temporary_unavailability','actual_sse_recovery'];
}));
