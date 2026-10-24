// Native Chrome: real MOSS / SoulX audio, model switching and shortlist exports.
const fs=require('fs'),path=require('path'),assert=require('assert');
const {pathToFileURL}=require('url'),{chromium}=require('playwright-core');
const root=path.resolve(__dirname,'..'),temporary=path.join(root,'cache/voice-capture');
fs.mkdirSync(temporary,{recursive:true});fs.mkdirSync(path.join(root,'docs/media'),{recursive:true});fs.mkdirSync(path.join(root,'docs/evidence'),{recursive:true});
const report={ok:false,revision:'female-a-voices-v2',source:process.env.VOICE_BASE_URL?'deployed studio page':'offline file page',checks:{},audio:[],screenshots:[]};
let browser;
(async()=>{try{
 browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--autoplay-policy=no-user-gesture-required'],env:{...process.env,TEMP:temporary,TMP:temporary}});
 const context=await browser.newContext({viewport:{width:1440,height:1150},acceptDownloads:true});
 const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
 const target=process.env.VOICE_BASE_URL?process.env.VOICE_BASE_URL.replace(/\/$/,'')+'/voices.html?v=2':pathToFileURL(path.join(root,'web/voices.html')).href;
 await page.goto(target,{waitUntil:'load',timeout:30000});
 const catalog=await page.locator('#voiceCatalog').evaluate(element=>JSON.parse(element.textContent));
 assert.equal(catalog.revision,'female-a-voices-v2');assert.equal(catalog.voices.length,20);
 assert.equal(new Set(catalog.voices.map(item=>item.reference)).size,10);
 assert.equal(await page.locator('.voice-card').count(),10);assert.equal(await page.locator('[data-engine="MOSS"]').getAttribute('aria-pressed'),'true');
 assert.equal(await page.locator('.voice-card .casting strong').first().innerText(),'MOSS');report.checks.default_shows_ten_moss_voices=true;
 async function verifyPlay(item,button){
   await button.click();
   await page.waitForFunction(()=>{const audio=document.getElementById('player');return !audio.paused&&audio.readyState>=2&&audio.currentTime>.12;},null,{timeout:20000});
   const actual=await page.locator('#player').evaluate(audio=>({duration:audio.duration,src:audio.currentSrc,error:audio.error?.message||null}));
   assert(Math.abs(actual.duration-item.seconds)<.03);assert(actual.src.includes(path.basename(item.url)));assert.equal(actual.error,null);
   assert((await page.locator('#nowTitle').innerText()).includes(item.engine));report.audio.push({id:item.id,engine:item.engine,seconds:actual.duration,played:true});
   await page.locator('#transportPlay').click();assert.equal(await page.locator('#player').evaluate(audio=>audio.paused),true);
 }
 for(const engine of ['MOSS','SoulX']){
   await page.locator('[data-engine="'+engine+'"]').click();assert.equal(await page.locator('.voice-card').count(),10);
   for(const item of catalog.voices.filter(item=>item.engine===engine))await verifyPlay(item,page.locator('#voiceGrid .card-controls [data-play="'+item.id+'"]'));
 }
 const fire=catalog.benchmarks.find(item=>item.engine==='FireRed');await verifyPlay(fire,page.locator('#engineRows [data-play="'+fire.id+'"]'));
 assert.equal(report.audio.length,21);assert.equal(await page.locator('audio').count(),1);report.checks.all_twenty_one_real_files_decode_and_play=true;
 report.checks.ten_moss_and_ten_soulx_tabs=true;report.checks.single_player_preserves_model_name=true;
 await page.locator('[data-engine="MOSS"]').click();
 const moss=catalog.voices.find(item=>item.voice_id==='v02'&&item.engine==='MOSS');
 const soul=catalog.voices.find(item=>item.voice_id==='v02'&&item.engine==='SoulX');
 await page.locator('#voiceGrid .compare-play[data-play="'+soul.id+'"]').click();
 await page.waitForFunction(()=>document.getElementById('player').currentTime>.12);
 assert((await page.locator('#nowTitle').innerText()).includes('SoulX'));assert.equal(await page.locator('[data-engine="MOSS"]').getAttribute('aria-pressed'),'true');
 await page.locator('#transportPlay').click();report.checks.same_reference_cross_model_button=true;
 await page.locator('#clearSelection').click();await page.locator('[data-pick="'+moss.id+'"]').click();
 await page.locator('[data-engine="SoulX"]').click();await page.locator('[data-pick="'+soul.id+'"]').click();
 assert((await page.locator('#shortlistCount').innerText()).includes('已选 2'));await page.reload();
 assert((await page.locator('#shortlistCount').innerText()).includes('已选 2'));report.checks.cross_model_shortlist_survives_reload=true;
 const pending=page.waitForEvent('download');await page.locator('#exportSelection').click();const download=await pending;
 const output=path.join(temporary,'shortlist.json');await download.saveAs(output);const selected=JSON.parse(fs.readFileSync(output,'utf8'));
 assert.deepEqual(selected.selected.map(item=>item.id),[moss.id,soul.id]);assert.deepEqual(selected.selected.map(item=>item.engine),['MOSS','SoulX']);
 assert(selected.selected.every(item=>item.voice_id==='v02'&&item.reference_text&&item.workflow&&item.sha256));report.checks.export_distinguishes_same_voice_with_two_models=true;
 await page.locator('#compareVoice').selectOption('v09');assert.equal(await page.locator('#engineRows tr').count(),2);
 const nine=catalog.voices.find(item=>item.voice_id==='v09'&&item.engine==='MOSS');
 assert.equal(await page.locator('#engineRows [data-play="'+nine.id+'"]').count(),1);
 await page.locator('#compareVoice').selectOption('v01');assert.equal(await page.locator('#engineRows tr').count(),3);report.checks.comparison_dropdown_has_matching_actual_models=true;
 await page.locator('#voiceGrid .card-controls [data-play="'+moss.id+'"]').click();await page.waitForFunction(()=>document.getElementById('player').currentTime>.15);
 await page.locator('#rate').selectOption('1.15');assert.equal(await page.locator('#player').evaluate(audio=>audio.playbackRate),1.15);assert.equal(await page.locator('#player').evaluate(audio=>audio.preservesPitch),true);
 await page.locator('#volume').evaluate(input=>{input.value='0.5';input.dispatchEvent(new Event('input',{bubbles:true}));});assert.equal(await page.locator('#player').evaluate(audio=>audio.volume),.5);
 await page.locator('#seek').evaluate(input=>{input.value='500';input.dispatchEvent(new Event('input',{bubbles:true}));});assert((await page.locator('#player').evaluate(audio=>audio.currentTime/audio.duration))>.45);
 await page.locator('#rate').selectOption('1');report.checks.rate_volume_seek_preserve_pitch=true;
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);report.checks.desktop_no_horizontal_overflow=true;
 await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(root,'docs/media/voice-selection-desktop.png'),fullPage:true});report.screenshots.push('docs/media/voice-selection-desktop.png');
 await page.locator('#transportPlay').click();await page.setViewportSize({width:390,height:844});await page.evaluate(()=>scrollTo(0,0));
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);report.checks.mobile_no_horizontal_overflow=true;
 await page.screenshot({path:path.join(root,'docs/media/voice-selection-mobile.png'),fullPage:false});report.screenshots.push('docs/media/voice-selection-mobile.png');
 await page.locator('#clearSelection').click();assert.equal(await page.locator('.voice-card.selected').count(),0);assert.equal(await page.locator('#exportSelection').isDisabled(),true);report.checks.reset_clears_both_models=true;
 assert.deepEqual(errors,[]);report.checks.no_page_script_errors=true;report.ok=true;
}catch(error){report.error=error.message;process.exitCode=1;}
finally{if(browser)await browser.close();report.browser_closed=true;report.captured_at=new Date().toISOString();fs.writeFileSync(path.join(root,'docs/evidence/voice-selection-browser.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));}
})();
