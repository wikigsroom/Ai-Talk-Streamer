/** A real A->VPN->B browser acceptance run. This never starts public streaming. */
import { chromium } from 'playwright-core';
import { mkdirSync, writeFileSync, appendFileSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { randomUUID } from 'node:crypto';

const origin=process.env.RECEIVER_ORIGIN||'http://127.0.0.1:8020';
const folder=resolve(process.env.SPLIT_EVIDENCE_DIR||'outputs/split-device/validation-'+Date.now());mkdirSync(folder,{recursive:true});
const runId='split-'+randomUUID(),report={run_id:runId,started_at:new Date().toISOString(),scope:'A inference over virtual LAN to B native Chromium; real MOSS04/MuseTalk/DSH; local injected comments',public_broadcast_started:false,official_client_capture:false,steps:[],metrics:[],errors:[],ok:false};
const wait=ms=>new Promise(r=>setTimeout(r,ms)),check=(condition,reason)=>{if(!condition)throw Error(reason)};
const save=()=>writeFileSync(join(folder,'result.json'),JSON.stringify(report,null,2));
async function api(path,body){const r=await fetch(origin+'/api/dsh'+path,{...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),signal:AbortSignal.timeout(100000)});const d=await r.json();if(!r.ok)throw Error(d.error||'HTTP_'+r.status);return d}
async function until(fn,timeout=150000){const due=Date.now()+timeout;while(Date.now()<due){const value=await fn();if(value)return value;await wait(300)}throw Error('ACCEPTANCE_TIMEOUT')}
let browser,page,timer,ownedOutput=false,original;
async function message(id,text,mode){
 if(mode)await api('/platforms/config',{interaction:{mode}});
 const before=Date.now(),event={type:'comment',event_id:runId+':'+id,room_id:'595139',user_id:runId+':viewer',nickname:'分机验收观众',text,timestamp:before};
 const ack=await api('/platforms/events',{platform:'bilibili',event});
 const row=await until(async()=>{const value=(await api('/platforms/status')).events.find(x=>x.event_key===ack.results[0].event_key);if(value&&['FAILED','EXPIRED','DROPPED','IGNORED','UNKNOWN','CANCELLED','INTERRUPTED','REJECTED'].includes(value.status))throw Error('EVENT_'+value.status+'_'+(value.reason||''));return value?.status==='COMPLETED'?value:null});
 const request=await api('/requests/'+row.request_id);check(request.status==='COMPLETED','PLAYBACK_NOT_COMPLETED');
 report.steps.push({id,text,request_id:row.request_id,status:request.status,elapsed_ms:Date.now()-before,started_at:new Date(before).toISOString(),completed_at:new Date().toISOString()});save();return {event,row,request};
}
try{
 save();const status=await api('/status'),platforms=await api('/platforms/status');
 check(!status.broadcast,'EXISTING_A_SESSION_LEFT_UNCHANGED');
 check(platforms.config.platforms.bilibili.client_location==='receiver','SPLIT_MODE_NOT_SELECTED');
 original=platforms.config.interaction;
 const executablePath=[process.env.SPLIT_CHROME,'C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].filter(Boolean).find(existsSync);check(executablePath,'NATIVE_CHROME_REQUIRED');
 const temporary=resolve('cache/split-browser/tmp');mkdirSync(temporary,{recursive:true});
 browser=await chromium.launchPersistentContext(resolve('cache/split-browser/profile'),{executablePath,headless:true,viewport:{width:720,height:1280},deviceScaleFactor:1,env:{...process.env,TEMP:temporary,TMP:temporary},args:['--autoplay-policy=no-user-gesture-required','--disable-background-timer-throttling','--disable-renderer-backgrounding']});
 page=browser.pages()[0]||await browser.newPage();for(const unused of browser.pages())if(unused!==page)await unused.close();page.on('pageerror',e=>report.errors.push(e.message));
 await page.addInitScript(()=>{window.splitSocketEvents=[];const NativeSocket=window.WebSocket;window.WebSocket=class extends NativeSocket{constructor(...args){super(...args);this.addEventListener('close',event=>window.splitSocketEvents.push({at:new Date().toISOString(),code:event.code,reason:event.reason,metrics:window.avatarTransport?.metrics(),queued:window.avatarTransport?.avcFrames?.size,decoder_queue:window.avatarTransport?.avcDecoder?.decodeQueueSize}))}}});
 await page.exposeFunction('saveMediaChunk',base64=>appendFileSync(join(folder,'receiver.webm'),Buffer.from(base64,'base64')));
 await page.goto(origin+'/output.html?output=platform&renderer=livehime',{waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>window.avatarTransport?.metrics().frames>50,null,{timeout:180000});
 check((await page.evaluate(()=>window.avatarTransport.metrics())).codec==='h264_nvenc','H264_NOT_SELECTED');
 await page.evaluate(()=>{
  const pending=[];window.splitRecordingPending=pending;
  const stream=document.querySelector('video').srcObject;
  window.splitRecorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8,opus',videoBitsPerSecond:2500000});
  // The MIME type itself contains a comma (vp8,opus), so split(',')[1]
  // corrupts the file. The payload starts after the final comma of the URL.
  window.splitRecorder.ondataavailable=e=>{if(e.data.size){const job=new Promise((done,fail)=>{const reader=new FileReader();reader.onload=()=>window.saveMediaChunk(reader.result.slice(reader.result.lastIndexOf(',')+1)).then(done,fail);reader.onerror=fail;reader.readAsDataURL(e.data)});pending.push(job)}};
  window.splitRecorder.start(2000);
 });
 let sampling=false;
 timer=setInterval(async()=>{if(sampling||page.isClosed())return;sampling=true;try{const value=await page.evaluate(()=>({...window.avatarTransport.metrics(),playback:window.avatarTransport.dsh?.metrics()}));report.metrics.push({at:new Date().toISOString(),...value});save()}catch{}finally{sampling=false}},1000);
 await api('/platforms/config',{interaction:{enabled:true,mode:'echo',minimum_interval_ms:1000,viewer_cooldown_ms:0,ttl_ms:180000}});
 const output=await api('/platforms/bilibili/start',{});ownedOutput=true;check(output.state==='COMPANION_READY','A_SESSION_NOT_READY');
 report.broadcast_id=output.broadcast_id;report.preflight=await api('/platforms/bilibili/preflight');
 await page.screenshot({path:join(folder,'portrait.png')});
 const greeting=await message('s01_greeting','大家好，我是林知夏。人物和声音在远端生成，你现在看到的是本机接收的直播画面。');
 const duplicate=await api('/platforms/events',{platform:'bilibili',event:greeting.event});check(duplicate.results[0].duplicate,'DUPLICATE_SPOKEN_TWICE');report.duplicate_rejected=true;
 await message('s02_explanation','现在测试稍长的一段话。背景保持原来的日光宿舍，声音使用第四款音色。希望你能清楚听见每一句话。');
 const current=(await api('/status')).broadcast;
 await api('/broadcast/pause',{broadcast_id:current.broadcast_id,expected_revision:current.revision});await wait(1500);
 await api('/platforms/bilibili/resume',{});check((await api('/status')).broadcast.broadcast_id===current.broadcast_id,'RESUME_CHANGED_BROADCAST');
 await message('s03_resume','刚才暂停了一下，现在继续聊天。画面恢复以后，声音也会按顺序播放。');
 await message('s04_expression','收到你的留言啦，谢谢你来陪我。放松一点，我们慢慢聊。');
 if(!(await api('/status')).health.persona_injection_ready)check((await api('/probe',{})).passed,'CHANNEL_PROBE_FAILED');
 await message('s05_cloud_memory','请用一句简短的话介绍自己的名字，并说出刚才我们测试的是哪种直播方式。','chat');report.cloud_llm_exercised=true;
 await wait(3000);report.final_player=(await api('/platforms/status')).output_player;
 const metrics=await page.evaluate(()=>window.avatarTransport.metrics());report.final_metrics=metrics;
 check(metrics.audio_underruns===0&&metrics.missing_packets===0&&metrics.decode_errors===0,'MEDIA_CONTINUITY_FAILED');
 check(metrics.fps>=22,'FRAME_RATE_BELOW_22');check(report.final_player?.receiver_id,'B_RECEIVER_NOT_IDENTIFIED');
 // Reconnect the actual media socket and verify a new keyframe is rendered.
 const oldConsumer=await page.evaluate(()=>window.avatarTransport.dsh.consumerId);
 await page.evaluate(()=>window.avatarTransport.ws.close());
 await page.waitForFunction(old=>window.avatarTransport?.dsh.consumerId!==old&&window.avatarTransport?.metrics().frames>50,oldConsumer,{timeout:30000});
 report.reconnect={new_consumer:true,metrics:await page.evaluate(()=>window.avatarTransport.metrics())};
 await page.screenshot({path:join(folder,'after-reconnect.png')});report.ok=true;
}catch(error){report.error=error.message;process.exitCode=1}
finally{
 clearInterval(timer);
 if(page&&!page.isClosed())try{await page.evaluate(async()=>{if(window.splitRecorder?.state==='recording'){await new Promise(done=>{window.splitRecorder.onstop=done;window.splitRecorder.stop()})}await Promise.all(window.splitRecordingPending||[])})}catch(e){report.recording_error=e.message;report.ok=false}
 if(ownedOutput)try{await api('/platforms/bilibili/stop',{})}catch(e){report.cleanup_error=e.message;report.ok=false}
 if(original)try{await api('/platforms/config',{interaction:original})}catch(e){report.restore_error=e.message;report.ok=false}
 if(page&&!page.isClosed())report.socket_events=await page.evaluate(()=>window.splitSocketEvents).catch(()=>[]);
 if(browser)await browser.close();
 report.receiver=await fetch(origin+'/receiver/status').then(r=>r.json()).catch(()=>null);report.finished_at=new Date().toISOString();save();console.log(JSON.stringify({ok:report.ok,error:report.error,steps:report.steps.length,folder}));
}
