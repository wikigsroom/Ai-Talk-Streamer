import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { gameFixture, sourceRoot, until } from './game-fixture.mjs';

const executablePath='C:/Program Files/Google/Chrome/Application/chrome.exe', playwright=process.env.PLATFORM_PLAYWRIGHT_MODULE||join(sourceRoot,'node_modules/playwright-core');
test('death and lost connection warnings are current, accessible, mobile-safe and never authorize AUTO',
  {skip:!existsSync(executablePath)||!existsSync(playwright)},async()=>{
  const output=resolve(sourceRoot,process.env.MC_UI_EVIDENCE_ROOT||'outputs/mc-validation/round-083','player-safety');mkdirSync(output,{recursive:true});
  const f=await gameFixture({fakeClock:true,ui:true}), report={classification:'REMOTE_BROWSER_PROTOCOL_FIXTURE_NOT_REAL_GAME',ok:false,page_errors:[],external_requests:[],browser_closed:false};let browser,context;
  try {
    const game=await f.connect(),temp=join(sourceRoot,'cache/mc-player-safety-browser');mkdirSync(temp,{recursive:true});
    browser=await createRequire(import.meta.url)(playwright).chromium.launch({executablePath,headless:true,env:{...process.env,TEMP:temp,TMP:temp},args:['--disable-gpu','--disable-background-networking']});
    context=await browser.newContext({viewport:{width:1440,height:1080},reducedMotion:'reduce'});
    await context.route(/^https?:\/\//,async route=>{if(route.request().url().startsWith(f.base+'/'))await route.continue();else{report.external_requests.push(route.request().url());await route.abort();}});
    const page=await context.newPage();page.on('pageerror',error=>report.page_errors.push(error.message));await page.goto(f.base+'/mc-control');
    await page.getByText('自动游玩已暂停',{exact:true}).waitFor();
    assert.match(await page.locator('#player-safety-action').textContent(),/明确停止后保持暂停/);
    const player={...game.observation.player,health:0};game.snapshot({seq:2,screen:'death',player});await until(()=>f.manager.state.value.seq===2);
    await page.getByText('角色已死亡',{exact:true}).waitFor();
    assert(await page.getByRole('button',{name:'允许自动游玩',exact:true}).isDisabled());
    assert.match(await page.locator('#player-safety-copy').textContent(),/不代表已取回掉落物/);
    await page.screenshot({path:join(output,'death-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:join(output,'death-mobile.png'),fullPage:true});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    game.snapshot({seq:3,screen:'gameplay',player:{...player,health:20}});
    await page.getByText('自动游玩已暂停',{exact:true}).waitFor();
    game.socket.terminate();await until(()=>!f.manager.state.connected);
    await page.getByText('当前生存状态待确认',{exact:true}).waitFor();
    assert(await page.getByRole('button',{name:'允许自动游玩',exact:true}).isDisabled());
    await page.reload();await page.getByText('当前生存状态待确认',{exact:true}).waitFor();
    assert.equal(game.messages.filter(m=>m.type==='control_request'||m.type==='task_start').length,0);
    assert.equal(await page.locator('audio,video,iframe').count(),0);assert.deepEqual(report.external_requests,[]);assert.deepEqual(report.page_errors,[]);
    report.ok=true;
  } finally {if(context)await context.close();if(browser){await browser.close();report.browser_closed=!browser.isConnected();}await f.close();writeFileSync(join(output,'browser.json'),JSON.stringify(report,null,2)+'\n');assert(report.browser_closed||!browser);}
});
