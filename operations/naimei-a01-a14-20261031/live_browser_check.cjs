'use strict';
// Native Chrome rehearsal; always closes every page and browser it creates.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/carzy/.codex/skills/binance-square/node_modules/playwright-core');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'output/review/naimei-live-v1/browser');fs.mkdirSync(out,{recursive:true});
const base='http://127.0.0.1:8952',result={started:new Date().toISOString(),native_windows:true,public_broadcast:false,checks:[],errors:[],requests:[],samples:[]};
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function api(route,body){const response=await fetch(base+route,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(70000)});const value=await response.json();if(!response.ok)throw Error(route+': '+JSON.stringify(value));return value;}
async function until(fn,limit=45000){const start=Date.now();while(Date.now()-start<limit){const value=await fn();if(value)return value;await wait(500);}throw Error('Condition timed out');}
let browser,context,control,formal,second,recording=false,sampler;let frameCount=0,pcmSamples=0;
const video=fs.createWriteStream(path.join(out,'actual-stream.mjpeg')),audio=fs.createWriteStream(path.join(out,'actual-stream.s16le')),metadata=fs.createWriteStream(path.join(out,'actual-stream-metadata.jsonl'));
function save(){fs.writeFileSync(path.join(out,'browser-check.json'),JSON.stringify({...result,frame_count:frameCount,pcm_samples:pcmSamples,finished:new Date().toISOString()},null,2));}
function check(name,detail){result.checks.push({name,passed:true,detail});process.stdout.write(name+' OK\n');save();}
async function metrics(page){return page.evaluate(()=>({transport:window.avatarTransport?.metrics(),dsh:window.avatarTransport?.dsh?.metrics(),mixer:window.avatarTransport?.roomMixer?.metrics(),audible:window.avatarTransport?.roomMixer?.audible,caption:document.getElementById('caption')?.textContent,sfx:window.naimeiSfxCount||0,context:window.avatarAudioContext?.state}));}
async function speak(text,label,{interrupt=false}={}){
 const start=Date.now(),request=await api('/api/dsh/requests',{text,mode:'echo',idempotency_key:'naimei-browser-'+crypto.randomUUID()});
 const record={label,text,accepted:request,started:new Date().toISOString()};result.requests.push(record);save();
 const id=request.request_id||request.request?.request_id;assert.ok(id,'request_id');
 await until(async()=>{const value=await api('/api/dsh/requests/'+id);record.latest=value;save();if(['FAILED','CANCELLED','UNKNOWN'].includes(value.status))throw Error(JSON.stringify(value));return ['SPEAKING','PLAYING','COMPLETED'].includes(value.status);},150000);
 if(interrupt){await wait(1200);record.stop=await api('/api/naimei/stop',{});record.final=await until(async()=>{const value=await api('/api/dsh/requests/'+id);return ['CANCELLED','INTERRUPTED'].includes(value.status)?value:null;},20000);check('interruption_fenced',record.final);}
 else{await formal.screenshot({path:path.join(out,label+'-playing.png')});record.final=await until(async()=>{const value=await api('/api/dsh/requests/'+id);record.latest=value;save();if(['FAILED','CANCELLED','UNKNOWN'].includes(value.status))throw Error(JSON.stringify(value));return value.status==='COMPLETED'?value:null;},150000);record.elapsed_seconds=(Date.now()-start)/1000;record.playback=await metrics(formal);assert.ok(record.playback.dsh.utterances.some(u=>u.natural_end&&u.played_samples===u.valid_sample_count));check(label+'_natural_audio_completion',record.playback.dsh);}
 save();return record;
}
(async()=>{try{
 browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--autoplay-policy=no-user-gesture-required','--disable-background-timer-throttling','--disable-renderer-backgrounding','--disable-backgrounding-occluded-windows']});
 context=await browser.newContext({viewport:{width:1440,height:1000}});context.on('page',page=>page.on('pageerror',error=>{result.errors.push({page:page.url(),error:error.message});save();}));
 control=await context.newPage();await control.goto(base+'/',{waitUntil:'domcontentloaded'});await control.locator('#ready').click();
 await until(async()=>['STARTING','LIVE','PAUSED','RECOVERING'].includes((await api('/api/dsh/status')).broadcast?.state));
 formal=await context.newPage();await formal.setViewportSize({width:720,height:1280});
 formal.on('websocket',ws=>{if(!ws.url().includes('/api/studio/stream'))return;ws.on('framereceived',({payload})=>{if(!recording)return;if(typeof payload==='string'){metadata.write(JSON.stringify({time:Date.now(),message:JSON.parse(payload)})+'\n');return;}if(payload.length<12)return;const length=payload.readUInt32LE(4);if(length+12>payload.length)return;video.write(payload.subarray(12,12+length));audio.write(payload.subarray(12+length));frameCount++;pcmSamples+=(payload.length-12-length)/2;});});
 await formal.goto(base+'/output.html?renderer=livehime&codec=jpeg&buffer_ms=800&layout=portrait',{waitUntil:'domcontentloaded'});
 await until(async()=>(await api('/api/dsh/status')).broadcast?.state==='LIVE');
 await until(async()=>{const state=await api('/api/dsh/status');return formal.evaluate(epoch=>window.avatarTransport?.dsh?.lease?.runtime_epoch===epoch&&window.avatarTransport?.roomMixer?.audible===true,state.room.runtime_epoch);});check('formal_player_claims_real_authority',await metrics(formal));
 const preview=control.frames().find(frame=>frame.url().includes('renderer=preview'));assert.ok(preview);assert.equal(await preview.evaluate(()=>window.avatarTransport?.roomMixer?.audible),false);assert.equal(await preview.evaluate(()=>!!window.avatarTransport?.dsh?.lease),false);check('preview_is_silent_without_authority',{});
 second=await context.newPage();await second.goto(base+'/output.html?renderer=livehime&codec=jpeg&buffer_ms=800&layout=landscape',{waitUntil:'domcontentloaded'});await wait(2500);assert.equal((await metrics(second)).audible,false);assert.equal((await metrics(second)).dsh.authority,false);check('second_formal_player_stays_silent',await metrics(second));await second.close();second=null;
 recording=true;result.recording_started=new Date().toISOString();
 sampler=setInterval(async()=>{try{result.samples.push({time:Date.now(),...await metrics(formal)});save();}catch{}},250);
 await formal.screenshot({path:path.join(out,'idle-portrait.png')});await control.screenshot({path:path.join(out,'director.png'),fullPage:true});
 await control.locator('#bgm-play').click();await until(async()=>(await metrics(formal)).mixer?.music_playing);check('formal_bgm_started',await metrics(formal));
 await speak('大家好，我是奶妹。今天也一起待一会儿吧。','intro');
 await speak('爸爸抱着宝宝，慢慢把苹果搬过来。啊，哦，咿，呜。','phonetics');
 await speak('我们先停一下。然后慢慢说，今天下午三点十五分，房间里有二十五位朋友。','pause-numbers');
 await speak('这是一次打断测试。奶妹会一直说这段话，直到导播按下停止按钮，然后安静地回到待机状态。','interrupt',{interrupt:true});
 await speak('已经停好了，我们可以继续聊天啦。','recovery');
 await api('/api/naimei/action',{action_id:'NM-LIVE-react-thanks-r2'});await wait(1500);await formal.screenshot({path:path.join(out,'thanks-action.png')});await wait(6500);check('silent_action_returns_to_idle',(await api('/api/studio/status')).state);
 await api('/api/naimei/sfx',{id:'gentle-arrival'});await until(async()=>(await metrics(formal)).sfx>0);check('sfx_only_on_formal_source',await metrics(formal));
 await api('/api/naimei/voice',{voice_id:'NMV02'});await speak('大家好，我是奶妹。我们换一套清亮的声音。','voice-nmv02');await api('/api/naimei/voice',{voice_id:'NMV01'});
 await control.locator('#bgm-stop').click();await until(async()=>!(await metrics(formal)).mixer.music_playing);check('formal_bgm_stopped',await metrics(formal));await formal.setViewportSize({width:1280,height:720});await formal.evaluate(()=>{document.body.dataset.layout='landscape';});await formal.screenshot({path:path.join(out,'idle-landscape.png')});
 result.final_metrics=await metrics(formal);result.studio=await api('/api/studio/status');result.completed=true;check('rehearsal_completed_no_public_broadcast',{});
 }catch(error){result.failure=error.stack;process.exitCode=1;process.stderr.write(error.stack+'\n');}finally{
  recording=false;clearInterval(sampler);save();for(const page of context?.pages()||[])await page.close().catch(()=>{});await context?.close().catch(()=>{});await browser?.close().catch(()=>{});video.end();audio.end();metadata.end();result.created_browser_closed=true;save();
 }
})();
