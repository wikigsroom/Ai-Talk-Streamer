import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { gameFixture, sourceRoot, until } from './game-fixture.mjs';

const executablePath='C:/Program Files/Google/Chrome/Application/chrome.exe', playwright=process.env.PLATFORM_PLAYWRIGHT_MODULE||join(sourceRoot,'node_modules/playwright-core');
test('operator page creates and reviews goals, handles unknown effects and fits desktop/mobile without media or external calls',
  {skip:!existsSync(executablePath)||!existsSync(playwright)},async()=>{
  const output=resolve(sourceRoot,process.env.MC_UI_EVIDENCE_ROOT||'outputs/mc-validation/round-007','world-control-regression');mkdirSync(output,{recursive:true});
  const f=await gameFixture({fakeClock:true,ui:true});
  const report={classification:'LOCAL_BROWSER_WITH_PROTOCOL_FIXTURE_ONLY',result:'FAIL',browser_closed:false,page_errors:[],external_requests:[],real_minecraft:false,inference:false};let browser,context;
  try{
    const game=await f.connect({features:{task_ledger:true}}),temp=join(sourceRoot,'cache/mc-control-browser');mkdirSync(temp,{recursive:true});
    browser=await createRequire(import.meta.url)(playwright).chromium.launch({executablePath,headless:true,env:{...process.env,TEMP:temp,TMP:temp},args:['--disable-gpu','--disable-background-networking']});
    context=await browser.newContext({viewport:{width:1440,height:1080},reducedMotion:'reduce'});
    await context.route(/^https?:\/\//,async route=>{if(route.request().url().startsWith(f.base+'/'))await route.continue();else{report.external_requests.push(route.request().url());await route.abort();}});
    const page=await context.newPage();page.on('pageerror',error=>report.page_errors.push(error.message));await page.goto(f.base+'/mc-control');
    await page.getByRole('button',{name:'新建目标',exact:true}).waitFor();await until(()=>f.manager.state.view().freshness==='fresh');
    const settingsRevision=f.manager.configRevision;
    await page.waitForFunction(revision=>document.getElementById('play-settings-form').dataset.revision===String(revision),settingsRevision);
    assert.equal(await page.locator('#play-settings-fields').isEnabled(),true);
    await page.locator('#play-settings-form [name=avatar_variant]').selectOption('landscape');
    await page.locator('#play-settings-form [name=comment_mode]').selectOption('fly');
    await page.getByRole('button',{name:'保存游玩设置',exact:true}).click();
    await until(()=>f.manager.configRevision===settingsRevision+1);
    assert.equal(f.manager.config.programme.avatar_variant,'landscape');assert.equal(f.manager.config.programme.comment_mode,'fly');
    assert.equal(f.manager.state.view().mode,'PAUSED');assert.equal(game.messages.filter(frame=>frame.type==='task_start').length,0);
    const conflict=await f.api('/config',{expected_revision:settingsRevision,patch:{planner:{enabled:true}}});
    assert.equal(conflict.status,409);assert.equal(conflict.value.error,'GAME_CONFIG_CONFLICT');assert.equal(f.manager.config.planner.enabled,false);
    await page.locator('#play-settings-form [name=avatar_variant]').selectOption('circle');
    await page.getByRole('button',{name:'恢复已保存设置',exact:true}).click();
    assert.equal(await page.locator('#play-settings-form [name=avatar_variant]').inputValue(),'landscape');
    await page.getByRole('button',{name:'新建目标',exact:true}).click();await page.getByRole('textbox',{name:'目标名称',exact:true}).fill('准备第一晚的生存物资');
    assert.equal(await page.getByLabel('额外采集数量',{exact:true}).inputValue(),'4');
    await page.getByLabel('执行技能',{exact:true}).selectOption('craft');
    assert.equal(await page.getByLabel('新增产物数量',{exact:true}).inputValue(),'4');
    await page.getByLabel('执行技能',{exact:true}).selectOption('gather');
    await page.getByRole('textbox',{name:'步骤名称',exact:true}).fill('备好木材');await page.getByRole('button',{name:'保存草稿',exact:true}).click();
    await page.locator('#goal-dialog').waitFor({state:'hidden'});await page.getByRole('button',{name:'复核并批准',exact:true}).click();
    await page.locator('#decision-form [name=reason]').fill('已核对当前世界与物资，可开始准备。');await page.getByRole('button',{name:'确认记录',exact:true}).click();
    await page.locator('#decision-dialog').waitFor({state:'hidden'});const goal=(await f.api('/worlds/'+f.manager.state.value.world_id+'/goals')).value.items[0];
    assert.equal(goal.status,'active');assert.equal(goal.steps[0].goal.count,4);assert.equal(f.manager.state.value.mode,'PAUSED');assert.equal(f.manager.lease,null);
    await game.auto();const task=(await f.api('/tasks',{...game.request(),world_goal_ref:f.manager.continuity.referenceFor({skill:'gather',item_id:'minecraft:oak_log',count:4})})).value;
    game.send('task_update',{task:{...task,version:2,state:'failed',effect_status:'unknown',reason:'GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE'},transition_seq:2,delivery_seq:1});await until(()=>f.manager.tasks.raw(task.task_id).version===2);
    const taskRow=page.locator('[data-task="'+task.task_id+'"]');await taskRow.getByText('熔炼燃料尚未备齐',{exact:true}).waitFor();
    assert.match(await taskRow.textContent(),/燃烧时长/);assert.match(await taskRow.textContent(),/GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE/);
    game.send('control_result',{operation_id:'local-stop-ui',request_id:'local-stop-ui',world_session_id:game.observation.world_session_id,mode:'PAUSED',control_epoch:9,inputs_released:true,automation_ready:false,lease_id:null,heartbeat_seq:null,error:null});
    game.snapshot({seq:3,mode:'PAUSED',control_epoch:9,inputs_released:true,automation_ready:false,lease_remaining_ms:null,active_task_id:null});await until(()=>f.manager.state.value.seq===3);
    await page.getByRole('button',{name:'记录未知结果',exact:true}).click();await page.locator('#disposition-form [name=reason]').fill('已在游戏内核对现况，按未知结果记录，重新规划前复核库存。');
    await page.locator('#disposition-form [name=acknowledge]').check();await page.getByRole('button',{name:'记录人工确认',exact:true}).click();
    await page.locator('#disposition-dialog').waitFor({state:'hidden'});assert.equal(f.manager.tasks.get(task.task_id).disposition.status,'closed_unknown');assert.equal(f.manager.tasks.raw(task.task_id).effect_status,'unknown');
    // The preceding server decision can finish before the SSE-driven goal refresh.
    // Review the rendered current revision before opening the next CAS decision.
    await page.waitForFunction(({id,revision})=>document.querySelector('[data-goal="'+id+'"]')?.textContent.includes('修订 '+revision),
      {id:goal.goal_id,revision:f.manager.continuity.goal(goal.goal_id).revision});
    await page.getByRole('button',{name:'允许重新规划',exact:true}).click();await page.locator('#decision-form [name=reason]').fill('未知结果已记录，允许按最新库存重新规划。');await page.getByRole('button',{name:'确认记录',exact:true}).click();await page.locator('#decision-dialog').waitFor({state:'hidden'});
    assert.equal(f.manager.continuity.goal(goal.goal_id).status,'needs_review');assert.equal(game.messages.filter(frame=>frame.type==='task_start').length,1);
    await page.screenshot({path:join(output,'mc-control-desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:join(output,'mc-control-mobile.png'),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.equal(await page.locator('audio,video,iframe').count(),0);assert.deepEqual(report.external_requests,[]);assert.deepEqual(report.page_errors,[]);
    const ax=await page.locator('main').ariaSnapshot();writeFileSync(join(output,'mc-control-accessibility.txt'),ax);
    game.socket.terminate();await until(()=>!f.manager.state.connected);await page.reload();
    await page.getByRole('button',{name:'复核并批准',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'复核并批准',exact:true}).isDisabled(),true);
    assert.equal(await page.getByRole('button',{name:'新建目标',exact:true}).isDisabled(),true);assert.equal(await page.locator('#connection').textContent(),'游戏未连接');
    assert.deepEqual(report.page_errors,[]);assert.deepEqual(report.external_requests,[]);report.result='PASS';
    report.checks=['actual HTTP goal create and CAS decision','goal approval never grants AUTO','classified task failure has Chinese meaning and retained raw code','unknown disposition retains B state and effect','explicit retry retains no replay','desktop 1440/mobile390 layouts','disconnect and reload preserve history while disabling writes','no media player','no external requests'];
  }catch(error){report.error=String(error.stack||error);try{const page=context?.pages()[0];if(page){report.visible_form_errors=await page.locator('[id$="-error"]').allTextContents();report.settings_diagnostic=await page.evaluate(()=>({notice:document.getElementById('notice').textContent,revision:document.getElementById('play-settings-form').dataset.revision,disabled:document.getElementById('play-settings-fields').disabled}));}}catch{}throw error;}
  finally{if(context)await context.close();if(browser){await browser.close();report.browser_closed=!browser.isConnected();}await f.close();report.recorded_at=new Date().toISOString();writeFileSync(join(output,'mc-control-browser.json'),JSON.stringify(report,null,2)+'\n');assert(report.browser_closed||!browser);}
});
