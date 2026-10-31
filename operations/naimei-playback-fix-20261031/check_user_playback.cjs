'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/carzy/.codex/skills/binance-square/node_modules/playwright-core');
const base='http://127.0.0.1:8952';
const out=path.resolve(process.env.NAIMEI_PLAYBACK_REVIEW_DIR||path.join(__dirname,'../../output/review/naimei-playback-fix-20261031'));
fs.mkdirSync(out,{recursive:true});
const result={native_windows:true,public_broadcast:false,autoplay_policy:'document-user-activation-required',checks:[],page_errors:[],requests:[]};
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function api(route,body,expected=200){
 const r=await fetch(base+route,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(15000)});
 const data=await r.json();assert.equal(r.status,expected,route+': '+JSON.stringify(data));return data;
}
async function until(fn,limit=60000){const started=Date.now();while(Date.now()-started<limit){const data=await fn();if(data)return data;await wait(150);}throw Error('Playback condition timed out');}
function check(name,data){result.checks.push({name,passed:true,...(data?{data}: {})});fs.writeFileSync(path.join(out,'browser-check.json'),JSON.stringify(result,null,2));process.stdout.write(name+' OK\n');}
let browser,context,director,formal;
async function captionRecorder(page){await page.evaluate(()=>{window.observedCaptions=[];window.captionTimer=setInterval(()=>{const text=document.getElementById('caption')?.textContent;if(text&&!observedCaptions.includes(text))observedCaptions.push(text);},40);});}
async function enable(page){
 await page.waitForLoadState('domcontentloaded');
 await page.waitForFunction(()=>!!window.avatarAudioContext);
 if(await page.evaluate(()=>avatarAudioContext.state!=='running')){
  await page.locator('#notice').click();
 }
 await until(()=>page.evaluate(()=>window.avatarTransport?.roomMixer?.audible===true));
}
async function completed(requestId,label){
 const final=await until(async()=>{
  const row=await api('/api/dsh/requests/'+requestId);
  if(['FAILED','UNKNOWN','CANCELLED','INTERRUPTED','EXPIRED','REJECTED'].includes(row.status))throw Error(JSON.stringify(row));
  return row.status==='COMPLETED'?row:null;
 },90000);
 await until(async()=>(await director.locator('#playback-state').innerText()).includes(label+'：已播完'));
 const natural=await formal.evaluate(id=>[...avatarTransport.dsh.utterances.values()].some(u=>u.request_id===id&&u.naturalEnded&&u.played===u.valid_sample_count),requestId);
 assert.equal(natural,true);return final;
}
(async()=>{try{
 const queue=await fetch('http://192.168.196.209:8188/queue').then(r=>r.json());
 assert.equal(queue.queue_running.length+queue.queue_pending.length,0,'Preserve unrelated GPU work before rehearsal');
 result.before=await api('/api/dsh/status');assert.equal(result.before.health.authority_ready,false,'A pre-existing user player must not be replaced');
 if(process.env.NAIMEI_PLAYBACK_START_PAUSED==='1'&&result.before.broadcast.state==='LIVE'){
  assert.equal(result.before.active_request,null);
  await api('/api/dsh/broadcast/pause',{broadcast_id:result.before.broadcast.broadcast_id,expected_revision:result.before.broadcast.revision});
  result.paused_start_verified=(await api('/api/dsh/status')).broadcast.state==='PAUSED';
  assert.equal(result.paused_start_verified,true);
 }
 const rejectedSpeech=await api('/api/dsh/requests',{text:'这是一条播放连接检查。',mode:'echo',idempotency_key:crypto.randomUUID()},409);
 const rejectedCue=await api('/api/naimei/cue',{cue_id:'resume',delay_seconds:0},409);
 assert.equal(rejectedSpeech.error,'NAIMEI_PLAYBACK_SOURCE_REQUIRED');assert.equal(rejectedCue.error,'NAIMEI_PLAYBACK_SOURCE_REQUIRED');
 assert.equal((await api('/api/dsh/status')).queued.length,result.before.queued.length);
 check('speech_and_programme_require_a_real_playback_source');
 browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--autoplay-policy=document-user-activation-required','--disable-background-timer-throttling','--disable-renderer-backgrounding','--disable-backgrounding-occluded-windows']});
 context=await browser.newContext({viewport:{width:1440,height:1100}});
 context.on('page',page=>page.on('pageerror',error=>result.page_errors.push({url:page.url(),error:error.message})));
 const blocked=await context.newPage();await blocked.goto(base+'/output.html?renderer=livehime&codec=jpeg&buffer_ms=800');
 await blocked.waitForFunction(()=>window.avatarAudioContext?.state==='suspended'&&document.getElementById('notice').textContent.includes('启用画面与声音'));
 assert.equal(await blocked.locator('#notice').isVisible(),true);
 await blocked.screenshot({path:path.join(out,'first-use-enable-audio.png')});await blocked.close();
 check('first_use_audio_prompt_is_visible_under_real_autoplay_restrictions');
 director=await context.newPage();await director.goto(base+'/',{waitUntil:'domcontentloaded'});
 await director.waitForFunction(()=>document.querySelectorAll('#cues button').length===5&&!document.getElementById('speak').disabled);
 assert.equal(await director.locator('#health').innerText(),'等待启用有声播放');
 await director.locator('#speech').fill('你好，我是奶妹。现在点击播报，就能看到台词和字幕了。');
 let accepted;
 director.on('response',async response=>{
  if(response.request().method()==='POST'&&new URL(response.url()).pathname==='/api/dsh/requests'&&response.status()===202){const row=await response.json();result.requests.push(row);accepted=row.request_id;}
 });
 const popup=director.waitForEvent('popup');await director.locator('#speak').click();formal=await popup;
 await captionRecorderAfterLoad(formal);
 await enable(formal);
 const requestId=await until(()=>accepted);
 await completed(requestId,'本次播报');
 assert.equal(await director.locator('#current-line').innerText(),'你好，我是奶妹。现在点击播报，就能看到台词和字幕了。');
 const spokenCaptions=await formal.evaluate(()=>observedCaptions);
 assert.ok(spokenCaptions.some(text=>text.includes('奶妹')));
 await director.screenshot({path:path.join(out,'manual-speech-completed.png'),fullPage:true});
 const preview=director.frames().find(frame=>frame.url().includes('renderer=preview'));
 assert.equal(await preview.evaluate(()=>avatarTransport.roomMixer.audible),false);
 assert.equal(await preview.evaluate(()=>!!avatarTransport.dsh.lease),false);
 check('one_manual_click_opens_player_then_real_speech_and_captions_complete',{request_id:requestId,captions:spokenCaptions});
 const cueResponse=director.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/naimei/cue');
 await director.locator('#cues button').filter({hasText:'恢复'}).click();const cue=await (await cueResponse).json();assert.ok(cue.cue_run_id);
 await until(async()=>(await director.locator('#current-line').innerText())===cue.cue.text);
 const event=await until(async()=>{const s=await api('/api/studio/status');return s.events.find(e=>e.cue_run_id===cue.cue_run_id&&e.request_id);});
 await completed(event.request_id,'恢复');
 assert.ok((await formal.evaluate(()=>observedCaptions)).some(text=>text.includes('我回来啦')));
 check('programme_button_displays_its_line_and_finishes_real_audio_and_captions',{request_id:event.request_id});
 await director.locator('#cue-delay').fill('8');
 const delayedResponse=director.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/naimei/cue');
 await director.locator('#cues button').filter({hasText:'转场'}).click();const delayed=await (await delayedResponse).json();
 const count=(await api('/api/dsh/status')).queued.length;await formal.close();
 await until(async()=>!(await api('/api/dsh/status')).health.authority_ready,15000);
 await until(async()=>(await director.locator('#playback-state').innerText()).includes('未播出'),20000);
 const failed=(await api('/api/studio/status')).events.find(e=>e.cue_run_id===delayed.cue_run_id&&e.type==='programme_cue_failed');
 assert.equal(failed.error,'NAIMEI_PLAYBACK_SOURCE_REQUIRED');assert.equal((await api('/api/dsh/status')).queued.length,count);
 await until(async()=>(await director.locator('#health').innerText())==='等待启用有声播放');
 check('closing_player_clears_ready_status_and_delayed_cue_does_not_strand_a_request');
 await director.evaluate(()=>{window.originalOpen=window.open;window.testPopup={closed:false,focus(){}};window.open=()=>window.testPopup;});
 const acceptedCount=result.requests.length;
 await director.locator('#speech').fill('这句话应在等待启用声音时被取消。');await director.locator('#speak').click();
 await until(async()=>(await director.locator('#feedback').innerText()).includes('有声播放页已打开'));
 await director.locator('#cancel').click();await wait(1500);
 assert.equal(result.requests.length,acceptedCount);
 await director.evaluate(()=>{window.testPopup.closed=true;window.open=()=>null;});
 await director.locator('#speak').click();
 await until(async()=>(await director.locator('#feedback').innerText()).includes('浏览器拦截'));
 assert.equal(result.requests.length,acceptedCount);await director.evaluate(()=>{window.open=window.originalOpen;});
 check('cancelled_preparation_and_simulated_popup_block_never_submit_old_speech');
 result.final=await api('/api/studio/status');assert.equal(result.final.voice_id,'O07');assert.equal(result.final.public_broadcast_allowed,false);
 assert.equal(result.final.voice_reference_sha256,'310c5d326dfabf0701eb255ca28e9e08f5626795d8b81d4e3b641bbac6b573a8');
 assert.deepEqual(result.page_errors,[]);result.passed=true;
 }catch(error){
  result.failure=error.stack;process.exitCode=1;
  if(director&&!director.isClosed())result.director_failure=await director.evaluate(()=>({feedback:document.getElementById('feedback')?.textContent,health:document.getElementById('health')?.textContent,playback:document.getElementById('playback-state')?.textContent})).catch(()=>null);
 }finally{
  for(const page of context?.pages()||[])await page.close().catch(()=>{});
  await context?.close().catch(()=>{});await browser?.close().catch(()=>{});
  result.created_browser_closed=true;result.finished=new Date().toISOString();
  fs.writeFileSync(path.join(out,'browser-check.json'),JSON.stringify(result,null,2));
  process.stdout.write(JSON.stringify({passed:result.passed,checks:result.checks.length,closed:true,failure:result.failure})+'\n');
 }
})();
async function captionRecorderAfterLoad(page){await page.waitForLoadState('domcontentloaded');await captionRecorder(page);}
