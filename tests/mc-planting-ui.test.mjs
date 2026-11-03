import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync,mkdirSync,writeFileSync } from 'node:fs';
import { join,resolve } from 'node:path';
import { gameFixture,sourceRoot,until } from './game-fixture.mjs';

const chrome='C:/Program Files/Google/Chrome/Application/chrome.exe';
const playwright=process.env.PLATFORM_PLAYWRIGHT_MODULE||join(sourceRoot,'node_modules/playwright-core');
test('operator chooses an observed planting cell and saves a verified-task goal without starting play',
 {skip:!existsSync(chrome)||!existsSync(playwright)},async()=>{
  const output=resolve(sourceRoot,process.env.MC_UI_EVIDENCE_ROOT||'outputs/mc-validation/round-083','planting-control');mkdirSync(output,{recursive:true});
  const f=await gameFixture({fakeClock:true,ui:true});let browser,context;
  const report={ok:false,classification:'BROWSER_AND_PROTOCOL_FIXTURE_NOT_REAL_PLANTING',game_started:false,models_started:false,external_requests:[],page_errors:[],browser_closed:false};
  try {
    const game=await f.connect({features:{targeted_planting:true}});
    const target={dimension:'minecraft:overworld',x:1361,y:75,z:-152};
    const details={source:'runtime_client',selected_hotbar:0,inventory_slots:[],
      cursor:{slot:-1,item_id:'minecraft:air',count:0,damage:null,max_damage:null},
      gui:{kind:'gameplay',title:null,container_id:null,slots:[],truncated:false},
      hazards:{on_fire:false,in_water:false,in_lava:false,fall_distance:0,on_ground:true},
      environment:{biome:'minecraft:plains',day_time:1,raining:false,thundering:false},
      received_rules:{difficulty:'normal',game_mode:'survival',world_border_size:1000},
      nearby_hostiles:[],hostiles_truncated:false,unknown_fields:[],
      nearby_food:{source:'runtime_client',sampled_at:new Date(f.manager.wall()).toISOString(),radius:6,vertical_radius:3,
        items:[],truncated:false,action_precondition_required:true,unknown_fields:[],
        planting_sites:[{position:target,soil_id:'minecraft:farmland',line_of_sight:true,distance:2}],planting_sites_truncated:false}};
    game.snapshot({seq:2,details});await until(()=>f.manager.state.value.seq===2);
    const temp=join(sourceRoot,'cache/mc-planting-browser');mkdirSync(temp,{recursive:true});
    browser=await createRequire(import.meta.url)(playwright).chromium.launch({executablePath:chrome,headless:true,env:{...process.env,TEMP:temp,TMP:temp},args:['--disable-gpu','--disable-background-networking']});
    context=await browser.newContext({viewport:{width:1440,height:1080},reducedMotion:'reduce'});
    await context.route(/^https?:\/\//,async route=>{if(route.request().url().startsWith(f.base+'/'))await route.continue();else{report.external_requests.push(route.request().url());await route.abort();}});
    const page=await context.newPage();page.on('pageerror',error=>report.page_errors.push(error.message));await page.goto(f.base+'/mc-control');
    const open=page.getByRole('button',{name:'新建目标',exact:true});await open.waitFor();await until(()=>f.manager.state.view().freshness==='fresh');
    await open.click();await page.getByRole('textbox',{name:'目标名称',exact:true}).fill('补种已采收的小麦');
    await page.getByRole('textbox',{name:'步骤名称',exact:true}).fill('在空耕地补种一粒小麦');
    await page.getByLabel('执行技能',{exact:true}).selectOption('use_item');
    await page.getByLabel('用途',{exact:true}).selectOption('plant');
    assert.equal(await page.getByLabel('完成条件',{exact:true}).inputValue(),'task_verified');
    assert.equal(await page.getByLabel('选择作物',{exact:true}).inputValue(),'minecraft:wheat_seeds');
    await page.getByLabel('补种位置',{exact:true}).selectOption(JSON.stringify(target));
    await page.screenshot({path:join(output,'planting-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:join(output,'planting-mobile.png'),fullPage:true});
    await page.getByRole('button',{name:'保存草稿',exact:true}).click();await page.locator('#goal-dialog').waitFor({state:'hidden'});
    const saved=(await f.api('/worlds/'+f.manager.state.value.world_id+'/goals')).value.items[0];
    assert.deepEqual(saved.steps[0].goal,{skill:'use_item',item_id:'minecraft:wheat_seeds',purpose:'activate',target});
    assert.equal(saved.steps[0].condition.kind,'task_verified');
    assert.equal(f.manager.state.value.mode,'PAUSED');assert.equal(f.manager.lease,null);
    assert.equal(game.messages.filter(m=>m.type==='task_start').length,0);
    await open.click();await page.getByLabel('执行技能',{exact:true}).selectOption('use_item');await page.getByLabel('用途',{exact:true}).selectOption('plant');
    // A new observation removes the site. A new editor must offer no invented fallback.
    game.snapshot({seq:3,details:{...details,nearby_food:{...details.nearby_food,planting_sites:[]}}});
    await until(()=>f.manager.state.value.seq===3);await page.reload();await open.waitFor();await open.click();
    await page.getByLabel('执行技能',{exact:true}).selectOption('use_item');await page.getByLabel('用途',{exact:true}).selectOption('plant');
    assert.equal(await page.getByLabel('补种位置',{exact:true}).locator('option').count(),1);
    assert.equal(await page.getByLabel('补种位置',{exact:true}).inputValue(),'');
    assert.deepEqual(report.external_requests,[]);assert.deepEqual(report.page_errors,[]);
    report.saved_goal=saved.steps[0];report.ok=true;
  } catch(error) {report.error=String(error.stack||error);throw error;}
  finally {
    if(context)await context.close();if(browser){await browser.close();report.browser_closed=!browser.isConnected();}
    await f.close();writeFileSync(join(output,'planting-browser.json'),JSON.stringify(report,null,2)+'\n');assert(report.browser_closed||!browser);
  }
});
