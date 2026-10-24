// Native Chrome: actual audio decode/playback, interactions and responsive captures.
const fs=require('fs'),path=require('path'),assert=require('assert');
const {pathToFileURL}=require('url'),{chromium}=require('playwright-core');
const root=path.resolve(__dirname,'..'),temporary=path.join(root,'cache/voice-capture');
fs.mkdirSync(temporary,{recursive:true});fs.mkdirSync(path.join(root,'docs/media'),{recursive:true});fs.mkdirSync(path.join(root,'docs/evidence'),{recursive:true});
const report={ok:false,source:process.env.VOICE_BASE_URL?'deployed studio page':'offline file page',checks:{},audio:[],screenshots:[]};
let browser;
(async()=>{try{
 browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--autoplay-policy=no-user-gesture-required'],env:{...process.env,TEMP:temporary,TMP:temporary}});
 const context=await browser.newContext({viewport:{width:1440,height:1150},acceptDownloads:true});
 const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
 const target=process.env.VOICE_BASE_URL?process.env.VOICE_BASE_URL.replace(/\/$/,'')+'/voices.html':pathToFileURL(path.join(root,'web/voices.html')).href;
 await page.goto(target,{waitUntil:'load',timeout:30000});
 assert.equal(await page.locator('.voice-card').count(),10);assert.equal(await page.locator('#engineRows tr').count(),3);report.checks.ten_voices_three_models=true;
 const catalog=await page.locator('#voiceCatalog').evaluate(element=>JSON.parse(element.textContent));
 assert.equal(new Set(catalog.voices.map(item=>item.reference)).size,10);report.checks.ten_independent_references=true;
 for(const item of [...catalog.voices,...catalog.benchmarks].filter((item,index,all)=>all.findIndex(other=>other.id===item.id)===index)){
   await page.locator('[data-play="'+item.id+'"]').first().click();
   await page.waitForFunction(()=>{const audio=document.getElementById('player');return !audio.paused&&audio.readyState>=2&&audio.currentTime>.12;},null,{timeout:20000});
   const actual=await page.locator('#player').evaluate(audio=>({duration:audio.duration,current_time:audio.currentTime,paused:audio.paused,error:audio.error?.message||null}));
   assert(Math.abs(actual.duration-item.seconds)<.03);assert.equal(actual.error,null);report.audio.push({id:item.id,seconds:actual.duration,played:true});
   await page.locator('#transportPlay').click();assert.equal(await page.locator('#player').evaluate(audio=>audio.paused),true);
 }
 assert.equal(report.audio.length,12);assert.equal(await page.locator('audio').count(),1);report.checks.all_twelve_real_audio_files_decode_and_play=true;report.checks.single_shared_player_and_pause=true;
 await page.locator('#clearSelection').click();
 const ids=[catalog.voices[1].id,catalog.voices[7].id];
 for(const id of ids)await page.locator('[data-pick="'+id+'"]').click();
 assert.equal(await page.locator('.voice-card.selected').count(),2);await page.reload();assert.equal(await page.locator('.voice-card.selected').count(),2);report.checks.shortlist_survives_reload=true;
 const pending=page.waitForEvent('download');await page.locator('#exportSelection').click();const download=await pending;
 const output=path.join(temporary,'shortlist.json');await download.saveAs(output);const selected=JSON.parse(fs.readFileSync(output,'utf8'));
 assert.deepEqual(selected.selected.map(item=>item.id),ids);assert(selected.selected.every(item=>item.reference_text&&item.workflow&&item.sha256));report.checks.export_retains_reference_transcript_workflow_and_hash=true;
 await page.locator('[data-play="'+catalog.voices[7].id+'"]').click();
 await page.waitForFunction(()=>document.getElementById('player').currentTime>.15);
 await page.locator('#rate').selectOption('1.15');assert.equal(await page.locator('#player').evaluate(audio=>audio.playbackRate),1.15);assert.equal(await page.locator('#player').evaluate(audio=>audio.preservesPitch),true);
 await page.locator('#volume').evaluate(input=>{input.value='0.5';input.dispatchEvent(new Event('input',{bubbles:true}));});assert.equal(await page.locator('#player').evaluate(audio=>audio.volume),.5);
 await page.locator('#seek').evaluate(input=>{input.value='500';input.dispatchEvent(new Event('input',{bubbles:true}));});assert((await page.locator('#player').evaluate(audio=>audio.currentTime/audio.duration))>.45);
 await page.locator('#rate').selectOption('1');report.checks.rate_pitch_preservation_volume_and_seeking=true;
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);report.checks.desktop_no_horizontal_overflow=true;
 await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(root,'docs/media/voice-selection-desktop.png'),fullPage:true});report.screenshots.push('docs/media/voice-selection-desktop.png');
 await page.locator('#transportPlay').click();
 await page.setViewportSize({width:390,height:844});await page.evaluate(()=>scrollTo(0,0));
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);report.checks.mobile_no_horizontal_overflow=true;
 await page.screenshot({path:path.join(root,'docs/media/voice-selection-mobile.png'),fullPage:false});report.screenshots.push('docs/media/voice-selection-mobile.png');
 await page.locator('#clearSelection').click();assert.equal(await page.locator('.voice-card.selected').count(),0);assert.equal(await page.locator('#exportSelection').isDisabled(),true);report.checks.reset_and_disabled_empty_export=true;
 assert.deepEqual(errors,[]);report.checks.no_page_script_errors=true;report.ok=true;
}catch(error){report.error=error.message;process.exitCode=1;}
finally{if(browser)await browser.close();report.browser_closed=true;report.captured_at=new Date().toISOString();fs.writeFileSync(path.join(root,'docs/evidence/voice-selection-browser.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));}
})();
