const fs=require('fs'),path=require('path');
const roots=[process.env.AI_TALK_STREAMER_REPO,path.resolve(__dirname,'../../Ai-Talk-Streamer'),path.resolve(__dirname,'../..'),path.resolve(__dirname,'../../..')].filter(Boolean);
const repo=roots.find(p=>fs.existsSync(path.join(p,'node_modules/playwright-core')));
if(!repo)throw new Error('Set AI_TALK_STREAMER_REPO to the checkout with native playwright-core installed.');
const {chromium}=require(path.join(repo,'node_modules/playwright-core'));
const out=process.env.AI_TALK_BENCHMARK_OUTPUT||path.join(path.dirname(repo),'outputs/lipsync-k01-k05-60s-20261028');fs.mkdirSync(out,{recursive:true});
(async()=>{let browser;const errors=[];const checks={};try{
 browser=await chromium.launch({executablePath:process.env.AI_TALK_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu']});
 const context=await browser.newContext({viewport:{width:1320,height:1100}});await context.addInitScript(()=>{window.__benchmarkPageTest=true});const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.argv[2]||'http://127.0.0.1:8037/');await page.waitForSelector('#rows tr');
 checks.five_rows=(await page.locator('#rows tr').count())===5;
 const available=await page.evaluate(()=>items.slice(0,2).every(x=>x.ok));
 checks.playback_matches_availability=(await page.locator('#play').isDisabled())!==available;
 checks.status_matches_results=await page.evaluate(()=>items.every(x=>{const row=[...document.querySelectorAll('#rows tr')].find(r=>r.querySelector('strong').textContent===x.id);return row.textContent.includes(x.ok?(x.verified?'验证通过':'待验证'):(x.error?'运行失败':'待测试'))}));
 if(available){
  await page.locator('#play').click();
  try{await page.waitForFunction(()=>document.getElementById('master').currentTime>.4&&!document.getElementById('master').paused,{},{timeout:10000})}catch{}
  checks.common_audio_advances=await page.evaluate(()=>document.getElementById('master').currentTime>.4&&!document.getElementById('master').paused);
  checks.videos_in_sync=await page.evaluate(()=>Math.max(...[document.getElementById('va'),document.getElementById('vb')].map(v=>Math.abs(v.currentTime-document.getElementById('master').currentTime)))<.25);
  await page.locator('#pause').click();
  await page.evaluate(()=>{const s=document.getElementById('seek');s.value=30;s.dispatchEvent(new Event('input'))});
  try{await page.waitForFunction(()=>[document.getElementById('va'),document.getElementById('vb'),document.getElementById('master')].every(v=>Math.abs(v.currentTime-30)<.1&&!v.seeking),{},{timeout:8000})}catch{}
  checks.seek_is_synchronized=await page.evaluate(()=>[document.getElementById('va'),document.getElementById('vb'),document.getElementById('master')].every(v=>Math.abs(v.currentTime-30)<.1));
  await page.locator('#checkpoints [data-seek="7.83"]').click();
  checks.phoneme_checkpoint_seeks=await page.evaluate(()=>[document.getElementById('va'),document.getElementById('vb'),document.getElementById('master')].every(v=>Math.abs(v.currentTime-7.83)<.1));
 }
 checks.actual_speech_timeline=(await page.locator('#speech-timeline tr').count())===16;
 const playbackModels=await page.evaluate(()=>items.filter(x=>x.ok&&x.video).map(x=>x.id));
 const modelPlayback={},playbackObservations={};
 for(const id of playbackModels){
  await page.locator('#right').selectOption(id);const before=await page.evaluate(()=>document.getElementById('master').currentTime);await page.locator('#play').click();
  try{await page.waitForFunction(start=>{const a=document.getElementById('master'),v=document.getElementById('vb');return a.currentTime>start+.4&&!a.paused&&!v.paused&&!v.seeking&&Math.abs(v.currentTime-a.currentTime)<.25},before,{timeout:10000})}catch{}
  playbackObservations[id]=await page.evaluate(start=>{const v=document.getElementById('vb'),a=document.getElementById('master');return{start_seconds:start,end_seconds:a.currentTime,clock_advance_seconds:a.currentTime-start,audio_paused:a.paused,video_paused:v.paused,drift_seconds:Math.abs(v.currentTime-a.currentTime)}},before);
  modelPlayback[id]=await page.evaluate(start=>{const v=document.getElementById('vb'),a=document.getElementById('master');return v.videoWidth===720&&v.videoHeight===1280&&Math.abs(v.duration-60)<.05&&a.currentTime>start+.4&&!a.paused&&!v.paused&&Math.abs(v.currentTime-a.currentTime)<.25&&!v.error},before);
  await page.locator('#pause').click();
 }
 checks.every_available_model_plays=Object.values(modelPlayback).every(Boolean);
 // Temporary browser-memory fixture verifies numerical sorting, never saved as results.
 await page.evaluate(()=>{items.forEach((x,i)=>x.render_wall_seconds=500+i);items[0].render_wall_seconds=120;items[1].render_wall_seconds=30});
 await page.locator('[data-sort="render_wall_seconds"]').click();checks.duration_sort=(await page.locator('#rows tr').first().innerText()).includes('K02');
 await page.reload();await page.waitForSelector('#rows tr');
 await page.locator('#zoom').click();checks.zoom_toggles=(await page.locator('.screen.zoom').count())===2;await page.locator('#zoom').click();
 await page.locator('#save-rating').click();checks.reject_invalid_rating=(await page.locator('#rating-status').innerText()).includes('1—5');
 for(const id of ['rating-lip','rating-natural','rating-stable'])await page.locator('#'+id).fill('4');await page.locator('#save-rating').click();await page.reload();await page.waitForSelector('#rows tr');
 checks.rating_persists=(await page.locator('#rating-lip').inputValue())==='4';
 await page.evaluate(()=>localStorage.removeItem('female-a-lipsync-k01-k05-ratings'));await page.reload();await page.waitForSelector('#rows tr');
 checks.actual_first_frame_posters=await page.evaluate(async()=>{const ready=items.filter(x=>x.ok&&x.video);const loaded=await Promise.all(ready.map(x=>new Promise(resolve=>{const im=new Image();im.onload=()=>resolve(im.naturalWidth===720&&im.naturalHeight===1280);im.onerror=()=>resolve(false);im.src=x.id+'/stills/0000.jpg'})));return loaded.every(Boolean)});
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 const tag=process.argv[2]?'-remote':'';
 await page.screenshot({path:out+'/page-review-desktop'+tag+'.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:out+'/page-review-mobile'+tag+'.png',fullPage:true});
 checks.mobile_no_document_overflow=await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth);
 const report=await context.newPage();await report.goto(new URL('report.html',page.url()).href);await report.waitForSelector('main h1');
 checks.full_html_report_readable=await report.evaluate(()=>document.querySelector('main h1').textContent.includes('K01')&&document.querySelectorAll('main h2').length>=10&&[...document.querySelectorAll('main tbody:first-of-type tr')].slice(0,5).map(r=>r.querySelector('td').textContent).join(',')==='K01,K02,K03,K04,K05');
 await report.screenshot({path:out+'/full-report-first-page'+tag+'.png'});await report.close();
 checks.no_javascript_errors=errors.length===0;
 const result={ok:Object.values(checks).every(Boolean),checks,model_playback:modelPlayback,playback_observations:playbackObservations,errors,url:process.argv[2]||'http://127.0.0.1:8037/',note:'Actual clock advancement with unpaused audio/video is required for every model. Full-file/frame/audio verification is recorded separately, not inferred from this browser check. Sorting fixture remained browser-memory-only; final screenshots were taken after reload and personal ratings were cleared.'};fs.writeFileSync(out+'/page-review'+tag+'.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));if(!result.ok)process.exitCode=1;
 await context.close();
}finally{if(browser)await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
