import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';

const { chromium } = createRequire(import.meta.url)(resolve('node_modules/playwright-core'));
async function fixture(t,label,mode='normal') {
  const output=resolve(process.env.MC_UI_EVIDENCE_ROOT||'outputs/mc-runtime-ui');mkdirSync(output,{recursive:true});
  const proof=join(output,label+'-proof.json'),errors=[],external=[],stderr=[];
  const child=spawn(process.env.MC_TEST_PYTHON||'C:/Python313/python.exe',['-X','utf8','-B','tests/mc-runtime-console-fixture.py'],{
    cwd:resolve('.'),env:{...process.env,MC_RUNTIME_BROWSER_PROOF:proof,MC_RUNTIME_BROWSER_MODE:mode},stdio:['pipe','pipe','pipe'],windowsHide:true
  });
  child.stderr.on('data',chunk=>stderr.push(String(chunk)));
  const lines=createInterface({input:child.stdout});
  const ready=new Promise((yes,no)=>{const timer=setTimeout(()=>no(new Error('Owned runtime fixture did not open')),20000);
    lines.once('line',line=>{clearTimeout(timer);try{const info=JSON.parse(line);assert.equal(info.ready,true);yes(info);}catch(error){no(error);}});
    child.once('exit',code=>{clearTimeout(timer);no(new Error('Fixture exited before readiness: '+code+' '+stderr.join('')));});
  });
  let browser,context,page;
  t.after(async()=>{
    try {if(page&&!page.isClosed())await page.screenshot({path:join(output,label+'-final.png'),fullPage:true});}
    finally {try{await context?.close();}finally{try{await browser?.close();}finally{
      child.stdin.end('\n');
      const code=await new Promise((yes,no)=>{if(child.exitCode!==null)return yes(child.exitCode);const timer=setTimeout(()=>{child.kill();no(new Error('Owned fixture did not close'));},20000);child.once('exit',code=>{clearTimeout(timer);yes(code);});});
      lines.close();writeFileSync(join(output,label+'-cleanup.json'),JSON.stringify({browser_closed:!browser?.isConnected(),fixture_exit:code,page_errors:errors,external_requests:external,stderr:stderr.join('')},null,2)+'\n');
      assert.equal(code,0,stderr.join(''));assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    }}}
  });
  const info=await ready;
  browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu','--disable-background-networking']});
  context=await browser.newContext({viewport:{width:1440,height:1120},reducedMotion:'reduce'});
  await context.route(/^https?:\/\//,route=>{if(route.request().url().startsWith(info.base+'/'))return route.continue();external.push(route.request().url());return route.abort();});
  context.on('page',page=>page.on('pageerror',error=>errors.push(error.message)));
  page=await context.newPage();await page.goto(info.base+'/mc-runtime');await page.getByText('管理台已连接',{exact:true}).waitFor();
  return {page,context,info,output,proof,application:async()=> (await (await page.request.get(info.base+'/api/mc-runtime/jobs')).json()).items};
}

test('runtime operator starts services, keeps business gaps visible, checks environment and stops without stale ready badges',async t=>{
  const f=await fixture(t,'runtime-operations'),{page}=f;
  await page.getByRole('button',{name:'启动直播服务',exact:true}).click();
  await page.getByText('后台已就绪 · 直播待核对',{exact:true}).waitFor();
  assert.equal(await page.locator('.service-sequence [data-ready="true"]').count(),4);
  await page.getByText('正式画面采集尚未验证。',{exact:true}).waitFor();
  assert(!((await page.locator('body').innerText()).includes('fixture-secret-must-not-project')));
  await page.screenshot({path:join(f.output,'runtime-desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'检查运行环境',exact:true}).click();
  await page.getByText('未找到符合配置的3080设备。',{exact:true}).waitFor();
  await page.getByRole('button',{name:'停止直播服务',exact:true}).click();
  await page.locator('.service-sequence strong').filter({hasText:'已停止'}).first().waitFor();
  assert.equal(await page.locator('.service-sequence [data-ready="stopped"]').count(),4);
  const records=await f.application();assert.equal(records.filter(x=>x.action==='start').length,1);assert.equal(records.find(x=>x.action==='stop').state,'succeeded');
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.keyboard.press('Tab');assert(await page.evaluate(()=>document.activeElement!==document.body));
});

test('lost start response is recovered by the original request after reload and never posted automatically again',async t=>{
  const f=await fixture(t,'runtime-lost-response'),{page,context,info}=f;let starts=0;
  await context.route(info.base+'/api/mc-runtime/jobs',async route=>{
    if(route.request().method()==='POST'&&route.request().postDataJSON().action==='start'){
      starts++;await route.fetch();return route.abort('failed');
    }
    return route.fallback();
  });
  await page.getByRole('button',{name:'启动直播服务',exact:true}).click();
  await page.getByText('暂未确认请求是否受理，请查询原请求；不会自动重新提交。',{exact:true}).waitFor();
  await page.reload();await page.getByText('管理台已连接',{exact:true}).waitFor();
  await page.getByText('后台已就绪 · 直播待核对',{exact:true}).waitFor();
  assert.equal(starts,1);assert.equal((await f.application()).filter(x=>x.action==='start').length,1);
});

test('broadcast stop refusal remains visible and does not replace running service facts with stopped badges',async t=>{
  const f=await fixture(t,'runtime-stop-refusal','broadcast'),{page}=f;
  await page.getByRole('button',{name:'检查当前状态',exact:true}).click();await page.getByText('后台已就绪 · 直播待核对',{exact:true}).waitFor();
  await page.getByRole('button',{name:'停止直播服务',exact:true}).click();
  await page.getByText('请先结束本场直播，再停止直播服务。',{exact:true}).waitFor();
  assert.equal(await page.locator('.service-sequence [data-ready="stopped"]').count(),0);
  assert.equal((await f.application()).find(x=>x.action==='stop').state,'failed');
});

test('queued stop can be cancelled while startup is running and all browser resources close',async t=>{
  const f=await fixture(t,'runtime-queued-cancel','slow-start'),{page}=f;
  await page.getByRole('button',{name:'启动直播服务',exact:true}).click();
  await page.getByRole('button',{name:'停止直播服务',exact:true}).click();
  await page.getByRole('button',{name:'取消排队',exact:true}).click();
  await page.getByRole('heading',{name:'停止直播服务 · 已取消',exact:true}).waitFor();
  await page.getByText('后台已就绪 · 直播待核对',{exact:true}).waitFor();
  assert.equal((await f.application()).find(x=>x.action==='stop').state,'cancelled');
});
