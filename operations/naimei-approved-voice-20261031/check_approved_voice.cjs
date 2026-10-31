'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/carzy/.codex/skills/binance-square/node_modules/playwright-core');
const base='http://127.0.0.1:8952',folder=path.resolve(__dirname,'../../output/review/naimei-approved-voice-20261031');
const reference='310c5d326dfabf0701eb255ca28e9e08f5626795d8b81d4e3b641bbac6b573a8';
const result={native_windows:true,cloud_inference:false,public_broadcast:false,checks:[],page_errors:[],utterances:[]};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function api(route,body){const r=await fetch(base+route,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(15000)});const text=await r.text();if(!r.ok)throw Error(route+': '+text);return JSON.parse(text)}
async function until(fn,limit=60000){const start=Date.now();while(Date.now()-start<limit){const v=await fn();if(v)return v;await wait(350)}throw Error('Timed out waiting for verified playback')}
let browser,context,formal;
(async()=>{try{
 result.before=await api('/api/studio/status');
 assert.equal(result.before.voice_reference_sha256,reference);assert.equal(result.before.voice_contract_ready,true);
 const profile=await api('/naimei-assets/voice/profile.json');assert.equal(profile.default_voice_id,'O07');assert.deepEqual(profile.voices.map(v=>v.id),['O07','F07']);
 browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--autoplay-policy=no-user-gesture-required','--disable-background-timer-throttling','--disable-renderer-backgrounding','--disable-backgrounding-occluded-windows']});
 context=await browser.newContext({viewport:{width:1440,height:1100}});context.on('page',p=>p.on('pageerror',e=>result.page_errors.push(e.message)));
 const director=await context.newPage();await director.goto(base+'/',{waitUntil:'domcontentloaded'});
 await director.waitForFunction(()=>document.querySelectorAll('#voices audio').length===2);
 assert.equal(await director.locator('#voices button').count(),2);assert.ok((await director.locator('#voice-selection').innerText()).includes('O07'));
 result.auditions=await director.locator('#voices audio').evaluateAll(async elements=>{
  const records=[];for(const audio of elements){audio.load();await new Promise((resolve,reject)=>{if(audio.readyState>=1)return resolve();audio.onloadedmetadata=resolve;audio.onerror=()=>reject(Error('Audition could not load: '+audio.src));setTimeout(()=>reject(Error('Audition metadata timed out')),10000)});records.push({src:audio.src,duration:audio.duration})}return records;
 });
 assert.ok(result.auditions.every(a=>a.duration>1&&a.duration<20&&!a.src.includes('reference')));
 const rejected=await fetch(base+'/api/naimei/voice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voice_id:'NMV01'})});assert.equal(rejected.status,400);
 result.checks.push('Only O07/F07 are selectable; both Naimei auditions load; NMV is rejected');
 await director.screenshot({path:path.join(folder,'director-approved-voice.png'),fullPage:true});
 formal=await context.newPage();await formal.goto(base+'/output.html?renderer=livehime&codec=jpeg&buffer_ms=800&layout=portrait',{waitUntil:'domcontentloaded'});
 let status=await until(async()=>{const s=await api('/api/dsh/status');return s.authority_ready||s.health?.authority_ready?s:null});
 if(status.broadcast.state!=='LIVE')await api('/api/dsh/broadcast/ready',{broadcast_id:status.broadcast.broadcast_id,expected_revision:status.broadcast.revision,mode:'echo'});
 await until(()=>formal.evaluate(()=>window.avatarTransport?.roomMixer?.audible===true));
 for(const [voice,text] of [['O07','你好，我是奶妹。这次沿用你原来选定的声音。'],['F07','奶妹的备用声音，也使用原来选定的同一份参考。']]){
  await api('/api/naimei/voice',{voice_id:voice});
  const queued=await api('/api/dsh/requests',{text,mode:'echo',idempotency_key:'approved-voice-'+crypto.randomUUID()});
  const final=await until(async()=>{const r=await api('/api/dsh/requests/'+queued.request_id);if(['FAILED','CANCELLED','UNKNOWN'].includes(r.status))throw Error(JSON.stringify(r));return r.status==='COMPLETED'?r:null},120000);
  const natural=await formal.evaluate(id=>[...avatarTransport.dsh.utterances.values()].some(u=>u.request_id===id&&u.naturalEnded&&u.played===u.valid_sample_count),queued.request_id);
  assert.equal(natural,true);
  const studio=await api('/api/studio/status');
  const event=studio.events.find(e=>e.type==='speech_input_ready'&&e.request_id===queued.request_id);
  assert.equal(event.voice_id,voice);assert.equal(event.reference_sha256,reference);assert.equal(event.engine,voice==='O07'?'OmniVoice':'F5-TTS-v1');
  result.utterances.push({request_id:queued.request_id,status:final.status,natural_end:natural,event});
 }
 await api('/api/naimei/voice',{voice_id:'O07'});
 result.checks.push('Actual O07 and F07 speech completes through the formal player with exact original reference binding');
 result.final=await api('/api/studio/status');assert.equal(result.final.voice_id,'O07');assert.equal(result.final.character_quality_accepted,false);assert.equal(result.final.public_broadcast_allowed,false);
 assert.deepEqual(result.page_errors,[]);result.passed=true;
 }catch(e){result.failure=e.stack;process.exitCode=1}finally{
  await api('/api/naimei/voice',{voice_id:'O07'}).catch(()=>{});
  for(const page of context?.pages()||[])await page.close().catch(()=>{});
  await context?.close().catch(()=>{});await browser?.close().catch(()=>{});
  result.created_browser_closed=true;result.finished=new Date().toISOString();
  fs.writeFileSync(path.join(folder,'browser-voice-check.json'),JSON.stringify(result,null,2));
  process.stdout.write(JSON.stringify({passed:result.passed,checks:result.checks,speech:result.utterances,closed:true,failure:result.failure})+'\n');
 }
})();
