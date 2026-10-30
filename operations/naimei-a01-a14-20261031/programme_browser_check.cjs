'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/carzy/.codex/skills/binance-square/node_modules/playwright-core');
const out=path.resolve(__dirname,'../../output/review/naimei-live-v1/browser'),base='http://127.0.0.1:8952';
const result={native_windows:true,public_broadcast:false,checks:[],samples:[],started:new Date().toISOString()};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function api(route,body){const r=await fetch(base+route,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(20000)});const text=await r.text();if(!r.ok)throw Error(route+' '+r.status+': '+text);return JSON.parse(text);}
async function until(fn,limit=45000){const start=Date.now();while(Date.now()-start<limit){const v=await fn();if(v)return v;await wait(250)}throw Error('Timed out');}
const save=()=>fs.writeFileSync(path.join(out,'programme-check.json'),JSON.stringify(result,null,2));
function check(name,detail){result.checks.push({name,passed:true,detail});process.stdout.write(name+' OK\n');save()}
let browser,context,formal,timer;
(async()=>{try{
 browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--autoplay-policy=no-user-gesture-required','--disable-background-timer-throttling','--disable-renderer-backgrounding','--disable-backgrounding-occluded-windows']});
 context=await browser.newContext({viewport:{width:720,height:1280}});formal=await context.newPage();
 await formal.goto(base+'/output.html?renderer=livehime&codec=jpeg&buffer_ms=800',{waitUntil:'domcontentloaded'});
 let state=await until(async()=>{const s=await api('/api/dsh/status');return s.authority_ready?s:null;});
 if(state.broadcast.state!=='LIVE')await api('/api/dsh/broadcast/ready',{broadcast_id:state.broadcast.broadcast_id,expected_revision:state.broadcast.revision,mode:'echo'});
 await until(()=>formal.evaluate(()=>window.avatarTransport?.roomMixer?.audible===true));
 const metrics=()=>formal.evaluate(()=>({frames:window.avatarTransport?.frames,mixer:window.avatarTransport?.roomMixer?.metrics(),caption:document.getElementById('caption').textContent,title:document.getElementById('programme-title').textContent}));
 const initial=await api('/api/studio/status');
 await api('/api/naimei/cue',{cue_id:'closing',delay_seconds:4});
 assert.equal((await api('/api/studio/status')).scheduled_cue.cue_id,'closing');
 await api('/api/naimei/stop',{});await wait(5000);
 const cancelled=await api('/api/studio/status');assert.equal(cancelled.scheduled_cue,null);assert.deepEqual(cancelled.programme,initial.programme);
 check('delayed_cue_cancellation_prevents_execution',{});
 timer=setInterval(async()=>{try{result.samples.push({time:Date.now(),...await metrics()});save()}catch{}},150);
 const started=Date.now();await api('/api/naimei/cue',{cue_id:'transition',delay_seconds:2});
 await wait(700);assert.notEqual((await metrics()).title,'换个小话题');
 const event=await until(async()=>{const s=await api('/api/studio/status');return s.events.findLast(e=>e.type==='programme_cue'&&e.cue_id==='transition'&&e.time*1000>=started);},60000);
 result.cue_event=event;
 const completed=await until(async()=>{const r=await api('/api/dsh/requests/'+event.request_id);if(['FAILED','CANCELLED','UNKNOWN'].includes(r.status))throw Error(JSON.stringify(r));return r.status==='COMPLETED'?r:null;},90000);
 assert.ok(Date.now()-started>=2000);assert.equal((await metrics()).title,'换个小话题');check('delayed_programme_action_speech_completed',completed);
 assert.ok(result.samples.some(s=>s.caption&&s.mixer.ducked));check('sample_clock_captions_and_ducking_observed',{captions:result.samples.filter(s=>s.caption).length,ducked:result.samples.filter(s=>s.mixer.ducked).length});
 const before=await metrics();await wait(5000);const after=await metrics();const fps=(after.frames-before.frames)/5;assert.ok(fps>=24.5&&fps<=25.5);check('five_second_canvas_cadence',{frames:after.frames-before.frames,seconds:5,fps});
 await formal.screenshot({path:path.join(out,'programme-transition.png')});
 result.completed=true;
 }catch(error){result.failure=error.stack;process.stderr.write(error.stack+'\n');process.exitCode=1}finally{
 clearInterval(timer);for(const p of context?.pages()||[])await p.close().catch(()=>{});await context?.close().catch(()=>{});await browser?.close().catch(()=>{});result.created_browser_closed=true;result.finished=new Date().toISOString();save();
 }
})();
