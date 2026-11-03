import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';

const { chromium } = createRequire(import.meta.url)(resolve('node_modules/playwright-core'));
async function fixture(t, label) {
  const output = resolve(process.env.MC_UI_EVIDENCE_ROOT || 'outputs/mc-maintenance-ui'); mkdirSync(output,{recursive:true});
  const proof = join(output,label+'-native-proof.json'), stderr = [], errors = [], external = [];
  const child = spawn(process.env.MC_TEST_PYTHON || 'C:/Python313/python.exe',['-X','utf8','-B','tests/mc-maintenance-console-fixture.py'],{
    cwd:resolve('.'),env:{...process.env,MC_MAINTENANCE_BROWSER_PROOF:proof},stdio:['pipe','pipe','pipe'],windowsHide:true
  });
  child.stderr.on('data',chunk => stderr.push(String(chunk)));
  const lines = createInterface({input:child.stdout});
  const ready = new Promise((yes,no) => { const timer = setTimeout(() => no(new Error('Native console did not become ready: '+stderr.join(''))),25000);
    lines.once('line',line => { clearTimeout(timer); try { const v=JSON.parse(line); assert.equal(v.ready,true); yes(v); } catch(e) { no(e); } });
    child.once('exit',code => { clearTimeout(timer); no(new Error(`Fixture exited before ready (${code}): ${stderr.join('')}`)); }); });
  let browser, context, page;
  t.after(async () => {
    try {
      if (page && !page.isClosed()) {
        writeFileSync(join(output,label+'-final-page.json'),JSON.stringify(await page.evaluate(() => ({notice:document.querySelector('#notice')?.textContent,
          jobs:document.querySelector('#jobs')?.textContent,selected_plan:document.querySelector('#plan-picker')?.value})),null,2)+'\n');
        await page.screenshot({path:join(output,label+'-final-page.png'),fullPage:true});
      }
    } finally { try { await context?.close(); } finally { try { await browser?.close(); } finally {
      child.stdin.end('\n');
      const code=await new Promise((yes,no) => { if(child.exitCode!==null) return yes(child.exitCode); const timer=setTimeout(() => { child.kill(); no(new Error('Owned fixture did not close gracefully')); },50000); child.once('exit',value => {clearTimeout(timer);yes(value);}); });
      lines.close();
      writeFileSync(join(output,label+'-cleanup.json'),JSON.stringify({browser_closed:!browser?.isConnected(),console_fixture_exit:code,page_errors:errors,external_requests:external,stderr:stderr.join(''),real_minecraft:false},null,2)+'\n');
      assert.equal(code,0,stderr.join('')); assert.deepEqual(errors,[]); assert.deepEqual(external,[]);
    } } }
  });
  const info = await ready;
  browser = await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu','--disable-background-networking']});
  context = await browser.newContext({viewport:{width:1440,height:1100},reducedMotion:'reduce'});
  await context.route(/^https?:\/\//,route => { if(route.request().url().startsWith(info.base+'/')) return route.continue(); external.push(route.request().url()); return route.abort(); });
  context.on('page',page => page.on('pageerror',error => errors.push(error.message)));
  page=await context.newPage(); await page.goto(info.base+'/mc-maintenance'); await page.getByText('维护台已连接',{exact:true}).waitFor();
  return {page,context,info,output,proof};
}
async function preview(page) {
  await page.locator('#preview').click(); await page.locator('#plan-review:visible').waitFor();
  await page.getByText('1 个任务',{exact:true}).waitFor();
  assert.equal(await page.locator('#review-apply').isEnabled(),true);
}
async function apply(page) {
  await page.locator('#review-apply').click(); await page.locator('#apply-dialog:visible').waitFor();
  assert.equal(await page.locator('#confirm-apply').isDisabled(),true);
  await page.locator('#confirm-checked').check(); await page.locator('#confirm-apply').click();
  await page.getByText('当前游戏账本已确认提交',{exact:true}).first().waitFor();
}

test('maintenance console uses actual native preview, reviewed execution, durable receipts, mobile layout and keyboard focus',async t => {
  const {page,info,output}=await fixture(t,'maintenance-complete');
  await preview(page);
  assert.equal(await page.locator('#retention-counts dd').nth(1).textContent(),'1');
  await page.screenshot({path:join(output,'maintenance-review-desktop.png'),fullPage:true});
  await apply(page);
  await page.reload(); await page.getByText('当前游戏账本已确认提交',{exact:true}).first().waitFor();
  await page.locator('.job-row').filter({hasText:'执行维护计划'}).getByRole('button',{name:'查看记录',exact:true}).click();
  await page.locator('#job-dialog:visible').waitFor();
  const text=await page.locator('#job-facts').textContent(); assert.ok(text.includes('confirmed_in_current_b_ledger')); assert.ok(!text.includes(info.installation));
  await page.locator('#close-job').click();
  const inspect=page.locator('#inspect'); await inspect.focus(); await page.waitForTimeout(1700); assert.equal(await inspect.evaluate(node => node===document.activeElement),true);
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:join(output,'maintenance-review-mobile.png'),fullPage:true});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth),true);
  assert.equal(await page.locator('audio,video,iframe').count(),0);
  const records=await (await page.request.get(info.base+'/api/mc-maintenance/jobs')).json();
  assert.equal(records.items.filter(job => job.action==='apply').length,1);
  writeFileSync(join(output,'maintenance-complete-observations.json'),JSON.stringify({jobs:records.items,viewport:390,overflow:false,no_media_elements:true},null,2)+'\n');
});

test('lost apply response is found by original request after reload and never posted again automatically',async t => {
  const {page,context,info,output}=await fixture(t,'maintenance-lost-response');
  await preview(page); let posts=0;
  await context.route(info.base+'/api/mc-maintenance/jobs',async route => {
    const value=route.request().postDataJSON();
    if(value?.action==='apply') { posts++; await route.fetch(); await route.abort('connectionreset'); }
    else await route.continue();
  });
  await page.locator('#review-apply').click(); await page.locator('#confirm-checked').check(); await page.locator('#confirm-apply').click();
  await page.getByText('当前游戏账本已确认提交',{exact:true}).first().waitFor();
  await page.reload(); await page.getByText('当前游戏账本已确认提交',{exact:true}).first().waitFor();
  assert.equal(posts,1);
  const records=await (await page.request.get(info.base+'/api/mc-maintenance/jobs')).json();
  assert.equal(records.items.filter(job => job.action==='apply').length,1);
  writeFileSync(join(output,'maintenance-lost-response-observations.json'),JSON.stringify({apply_posts:posts,jobs:records.items,reload_did_not_replay:true},null,2)+'\n');
});

test('expired preview remains queryable and cannot be approved from the browser',async t => {
  const {page,context,info,output}=await fixture(t,'maintenance-expired');
  await preview(page);
  await context.route(info.base+'/api/mc-maintenance/plans',async route => {const response=await route.fetch(),value=await response.json(); for(const plan of value.items) plan.expires_at_ms=Date.now()-1000; await route.fulfill({response,json:value});});
  await page.locator('#refresh').click(); await page.getByText('计划已过期。仍可查证当前账本；执行前请重新生成预览。',{exact:true}).waitFor();
  assert.equal(await page.locator('#review-apply').isDisabled(),true);
  await page.locator('#reconcile').click();
  await page.getByText('当前账本未找到；不代表历史上从未执行',{exact:true}).first().waitFor();
  const records=await (await page.request.get(info.base+'/api/mc-maintenance/jobs')).json();
  assert.equal(records.items.filter(job=>job.action==='apply').length,0);
  writeFileSync(join(output,'maintenance-expired-observations.json'),JSON.stringify({ui_expiry_injected:true,native_reconcile:true,apply_jobs:0,jobs:records.items},null,2)+'\n');
});

test('plan polling may lag job completion and confirmation stays bound to the reviewed plan',async t => {
  const {page,context,info,output}=await fixture(t,'maintenance-plan-binding'); let withheld=2;
  await context.route(info.base+'/api/mc-maintenance/plans',async route => {
    const response=await route.fetch(),value=await response.json();
    if(value.items.length && withheld>0) { withheld--; value.items=[]; }
    await route.fulfill({response,json:value});
  });
  await preview(page); assert.equal(withheld,0);
  const reviewed=await page.locator('#plan-id').textContent();
  await page.locator('#review-apply').click();
  const receipt=await (await page.request.post(info.base+'/api/mc-maintenance/jobs',{data:{request_id:'browser-second-preview',action:'preview'}})).json();
  await page.waitForFunction(old => { const select=document.querySelector('#plan-picker'); return select.value && select.value!==old; },reviewed);
  const newlySelected=await page.locator('#plan-picker').inputValue(); assert.notEqual(newlySelected,reviewed);
  await page.locator('#confirm-checked').check(); await page.locator('#confirm-apply').click();
  await page.getByText('当前游戏账本已确认提交',{exact:true}).first().waitFor();
  const records=await (await page.request.get(info.base+'/api/mc-maintenance/jobs')).json(), applied=records.items.find(job=>job.action==='apply');
  assert.equal(applied.plan_file,reviewed);
  writeFileSync(join(output,'maintenance-plan-binding-observations.json'),JSON.stringify({delayed_plan_polls:2,reviewed,newly_selected:newlySelected,applied_plan:applied.plan_file,second_preview_job:receipt.job.job_id,jobs:records.items},null,2)+'\n');
});
