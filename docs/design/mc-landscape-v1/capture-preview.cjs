'use strict';
// Offline layout QA only. This context never visits production or claims playback.
const fs=require('node:fs'),path=require('node:path'),{pathToFileURL}=require('node:url');
const assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const {chromium}=require('playwright-core'),here=__dirname,root=path.resolve(here,'../../..');
const report={classification:'FROZEN_DESIGN_PREVIEW_ONLY',design_version:'1.0.0',application_runtime_tested:false,new_avatar_materials_generated:false,upstream_plugin_installed:false,public_broadcast_started:false,remote_devices_accessed:false,virtualization_used:false,screenshots:[],page_errors:[],external_requests:[],checks:[],browser_closed:false};
let browser,context;
(async()=>{
  try{
    assert.equal(execFileSync('git',['branch','--show-current'],{cwd:root,encoding:'utf8'}).trim(),'mc');
    const temp=path.join(root,'cache','mc-landscape-preview');fs.mkdirSync(temp,{recursive:true});
    browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,env:{...process.env,TEMP:temp,TMP:temp},args:['--disable-background-networking','--disable-component-update','--no-first-run']});
    context=await browser.newContext({viewport:{width:1984,height:1510},deviceScaleFactor:1,reducedMotion:'no-preference'});
    await context.route(/^https?:\/\//,async route=>{report.external_requests.push(route.request().url());await route.abort();});
    const page=await context.newPage();page.on('pageerror',error=>report.page_errors.push(error.message));
    await page.goto(pathToFileURL(path.join(here,'preview.html')).href,{waitUntil:'load',timeout:25000});
    await page.evaluate(()=>document.fonts.ready);
    assert(await page.evaluate(()=>[...document.images].every(im=>im.complete&&im.naturalWidth>0)));
    const spec=JSON.parse(fs.readFileSync(path.join(here,'layout-spec.json'),'utf8'));
    assert.equal(spec.status,'DESIGN_FROZEN');assert.equal(spec.version,'1.0.0');
    assert.deepEqual(spec,JSON.parse(fs.readFileSync(path.join(root,spec.canonical_source),'utf8')));
    const geometry=await page.evaluate(()=>{
      const stage=document.querySelector('#programme').getBoundingClientRect();
      return {canvas:{width:stage.width,height:stage.height},regions:Object.fromEntries([...document.querySelectorAll('[data-region]')].map(el=>{const r=el.getBoundingClientRect();return [el.dataset.region,el.getClientRects().length?{x:r.x-stage.x,y:r.y-stage.y,width:r.width,height:r.height}:{hidden:true}];})),mediaElements:document.querySelectorAll('audio,video,iframe').length};
    });
    assert.deepEqual(geometry.canvas,{width:1920,height:1080});assert.equal(geometry.mediaElements,0);
    for(const [key,r]of Object.entries(spec.regions))if(!geometry.regions[key].hidden)assert.deepEqual(geometry.regions[key],r);
    for(const key of ['game','chat','avatar','caption'])assert(!geometry.regions[key].hidden);
    assert.equal(await page.locator('.comment,#comment-text,.room-board').count(),0);
    assert.equal(await page.locator('.chat-list>*').count(),4);
    assert.equal(await page.locator('.danmaku').isVisible(),false);
    report.geometry=geometry;report.checks.push('full-canvas game; four chronological chat rows; no selected-comment card, nested player or media consumer');
    const tracked=await page.locator('.chat-list>*').nth(1).evaluate(el=>({id:el.dataset.message,y:el.getBoundingClientRect().y}));
    await page.evaluate(()=>window.mcDesign.enqueue('预览观众','新增留言向上滚动',{id:'qa-movement'}));
    await page.waitForFunction(({id,y})=>{const el=document.querySelector('[data-message="'+id+'"]');return el&&el.getBoundingClientRect().y<y-60;},tracked,{timeout:4000});
    report.checks.push('incoming chat produces actual upward movement and evicts oldest row');
    await page.locator('#motion-toggle').click();assert((await page.evaluate(()=>window.mcDesign.inspectChat())).paused);
    await page.locator('#motion-toggle').click();assert.equal((await page.evaluate(()=>window.mcDesign.inspectChat())).paused,false);
    await page.emulateMedia({reducedMotion:'reduce'});await page.waitForFunction(()=>document.querySelector('#motion-toggle').disabled);
    assert((await page.evaluate(()=>window.mcDesign.inspectChat())).paused);
    await page.emulateMedia({reducedMotion:'no-preference'});await page.waitForFunction(()=>!document.querySelector('#motion-toggle').disabled);
    report.checks.push('manual and reduced-motion pause suspend queue consumption and active animations');
    await page.locator('#demo-text').fill('<img src=x>这是一条本地留言');
    await page.locator('#demo-form button').click();
    await page.waitForFunction(()=>document.querySelector('.chat-list').textContent.includes('<img src=x>'),{},{timeout:4000});
    assert.equal(await page.locator('.chat-list img').count(),0);
    await page.locator('#demo-kind').selectOption('superchat');await page.locator('#demo-text').fill('这是醒目留言示意，不是真实付费');
    await page.locator('#demo-form button').click();await page.waitForFunction(()=>!!document.querySelector('.chat-list [data-kind="superchat"]'),{},{timeout:4000});
    await page.locator('#demo-kind').selectOption('gift');await page.locator('#demo-form button').click();
    await page.waitForFunction(()=>document.querySelector('#gift-text').textContent.includes('预览观众'),{},{timeout:3000});
    await page.evaluate(()=>window.mcDesign.freezeForCapture());
    const bounds=await page.evaluate(()=>{
      const first=window.mcDesign.enqueue('测试观众','普通身份',{id:'same',verifiedRole:'moderator'});
      const repeated=window.mcDesign.enqueue('测试观众','重复身份',{id:'same'});
      for(let i=0;i<40;i++)window.mcDesign.enqueue('压力样例','队列上限样例'+i);
      return {first,repeated,state:window.mcDesign.inspectChat()};
    });
    assert(bounds.first&&!bounds.repeated);assert.equal(bounds.state.pending,24);assert(bounds.state.visible<=4);
    report.checks.push('plain-text rendering; local SC and gift previews; bounded 24-item queue and repeated-ID rejection');
    await page.evaluate(()=>window.mcDesign.selectChat('feed'));
    const chatBox=await page.locator('.chat-viewport').boundingBox(),rows=await page.locator('.chat-list>*').evaluateAll(nodes=>nodes.map(el=>{const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height};}));
    for(const r of rows){assert(r.top>=chatBox.y-.1&&r.bottom<=chatBox.y+chatBox.height+.1);assert.equal(r.height,100);}
    report.chat={state:await page.evaluate(()=>window.mcDesign.inspectChat()),rows_fit_viewport:true,row_height:100};
    const capture=async name=>{await page.locator('#frame-holder').screenshot({path:path.join(here,name)});report.screenshots.push(name);};
    for(const scene of ['play','interact','break','recover']){
      await page.locator('button[data-scene="'+scene+'"]').click();
      if(scene==='recover'){assert(await page.locator('#game-cover').isVisible());assert(await page.locator('#caption').isHidden());}
      await capture('preview-'+scene+'-1080.png');
    }
    await page.locator('button[data-scene="play"]').click();
    assert.equal(await page.locator('.avatar-window').evaluate(el=>getComputedStyle(el).borderRadius),'50%');
    const variants={circle:await page.locator('.avatar').boundingBox()};
    await page.locator('#avatar-mode').selectOption('landscape');
    const landscape=await page.locator('.avatar').boundingBox();assert.equal(landscape.width,320);assert.equal(landscape.height,180);
    assert.equal(await page.locator('.avatar-window').evaluate(el=>getComputedStyle(el).borderRadius),'13px');
    variants.landscape=landscape;report.avatar_variants=variants;
    await capture('preview-landscape-1080.png');
    await page.locator('#avatar-mode').selectOption('circle');
    const positionState=await page.evaluate(()=>({ids:[...document.querySelector('#chat-list').children].map(el=>el.dataset.message),queue:mcDesign.inspectChat().pending}));
    await page.locator('#chat-side').selectOption('left');
    assert.deepEqual(await page.evaluate(()=>({ids:[...document.querySelector('#chat-list').children].map(el=>el.dataset.message),queue:mcDesign.inspectChat().pending})),positionState);
    const sidePosition=await page.evaluate(()=>Object.fromEntries(['chat','gift'].map(name=>{const el=document.querySelector('[data-region='+name+']');return [name,{x:el.offsetLeft,y:el.offsetTop,width:el.offsetWidth,height:el.offsetHeight}];})));
    assert.deepEqual(sidePosition,spec.chat.side_presets.left);
    const overlaps=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
    for(const preset of Object.values(spec.chat.side_presets))for(const r of Object.values(preset))for(const protectedRegion of Object.values(spec.protected_game_regions))assert(!overlaps(r,protectedRegion));
    report.chat_positions={left:spec.chat.side_presets.left,right:spec.chat.side_presets.right,nodes_and_queue_preserved:true,protected_regions_clear:true};
    await capture('preview-left-1080.png');
    await page.locator('#chat-side').selectOption('right');
    report.checks.push('left/right switch moves only chat and gift; preserves message nodes, queue and protected game regions');
    await page.locator('#safe-toggle').check();
    await capture('preview-protected-1080.png');await page.locator('#safe-toggle').uncheck();
    report.checks.push('circle mask and 16:9 landscape crop switch; both preserve full game; four scenes and recovery caption clearing');
    await page.locator('#chat-mode').selectOption('fly');await page.evaluate(()=>window.mcDesign.resumeAfterCapture());
    assert.equal(await page.locator('.chat-shell').isVisible(),false);assert(await page.locator('.danmaku').isVisible());
    const flying=await page.locator('.danmaku-item').first().evaluate(el=>({id:el.dataset.message,x:el.getBoundingClientRect().x}));
    assert.deepEqual(await page.locator('.danmaku').evaluate(el=>({width:el.offsetWidth,height:el.offsetHeight})),{width:1856,height:104});
    await page.waitForFunction(({id,x})=>{const el=document.querySelector('[data-message="'+id+'"]');return el&&el.getBoundingClientRect().x<x-15;},flying,{timeout:3000});
    await page.evaluate(()=>window.mcDesign.freezeForCapture());
    const gaps=await page.evaluate(()=>[...document.querySelectorAll('.danmaku-lane')].flatMap(lane=>{
      const rects=[...lane.children].map(el=>el.getBoundingClientRect()).sort((a,b)=>a.left-b.left);
      return rects.slice(1).map((r,i)=>r.left-rects[i].right);
    }));for(const gap of gaps)assert(gap>=51);
    report.flying={movement_observed:true,minimum_measured_gaps:gaps};
    await capture('preview-flying-1080.png');
    report.checks.push('alternative flying mode moves right to left, preserves spacing and replaces feed instead of duplicating it');
    await page.locator('#chat-mode').selectOption('feed');
    await page.locator('#resolution-toggle').check();await page.waitForFunction(()=>Math.abs(document.querySelector('#programme').getBoundingClientRect().width-1280)<.1);
    const small=await page.locator('#frame-holder').boundingBox();assert.equal(small.width,1280);assert.equal(small.height,720);
    await capture('preview-play-720.png');
    await page.locator('#chat-side').selectOption('left');await capture('preview-left-720.png');
    await page.locator('#chat-side').selectOption('right');await page.locator('#resolution-toggle').uncheck();
    await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>document.querySelector('#frame-holder').clientWidth===358);
    const mobile=await page.locator('#programme').boundingBox();assert(Math.abs(mobile.width/mobile.height-16/9)<.001);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:path.join(here,'preview-review-mobile.png'),fullPage:true});report.screenshots.push('preview-review-mobile.png');
    await page.locator('#clean-toggle').click();assert(await page.locator('.review-toolbar').isHidden());await page.keyboard.press('Escape');assert(await page.locator('.review-toolbar').isVisible());
    report.checks.push('720P and mobile review preserve canvas ratio without page overflow; clean view and Escape return work');
    assert.equal(report.external_requests.length,0);assert.equal(report.page_errors.length,0);report.result='PASS';
  }catch(error){report.result='FAIL';report.error=String(error.stack||error);process.exitCode=1;}
  finally{
    if(context)await context.close().catch(error=>{report.close_error=error.message;});
    if(browser){await browser.close().catch(error=>{report.close_error=error.message;});report.browser_closed=!browser.isConnected();}
    if(!report.browser_closed){report.result='FAIL';process.exitCode=1;}
    report.captured_at=new Date().toISOString();fs.writeFileSync(path.join(here,'preview-verification.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify({result:report.result,classification:report.classification,screenshots:report.screenshots.length,browser_closed:report.browser_closed,error:report.error||null}));
  }
})();
