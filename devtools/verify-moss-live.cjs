// Actual browser integration: MOSS identity, novel text, interruption and recovery.
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require('playwright-core');
const root=path.resolve(__dirname,'..'),base=process.env.VOICE_BASE_URL||'http://127.0.0.1:8010';
const temporary=path.join(root,'cache/moss-live-browser');fs.mkdirSync(temporary,{recursive:true});
const report={ok:false,engine:'MOSS-TTSD-v1.0',voice_id:'v04',cases:[],checks:{}};
let browser;
(async()=>{try{
 browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--no-proxy-server','--autoplay-policy=no-user-gesture-required'],env:{...process.env,TEMP:temporary,TMP:temporary}});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.addInitScript(()=>{
  window.mossQA={events:[],audio:[]};
  const Original=window.EventSource;
  window.EventSource=class extends Original{constructor(...args){super(...args);this.addEventListener('message',event=>{try{window.mossQA.events.push({...JSON.parse(event.data),at:performance.now()});}catch{}});}};
  const start=AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start=function(at,...args){if(this.buffer){const pcm=this.buffer.getChannelData(0);let sum=0;for(const value of pcm)sum+=value*value;window.mossQA.context=this.context;window.mossQA.audio.push({at,duration:this.buffer.duration,rms:Math.sqrt(sum/pcm.length),now:this.context.currentTime,received_at:performance.now()});}return start.call(this,at,...args);};
 });
 const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto(base+'/studio.html?v=moss04-1',{waitUntil:'load',timeout:30000});
 const state=await page.evaluate(async()=>{const s=await(await fetch('/api/studio/status')).json();return {ready:s.ready,profile:s.profile,voice:s.voice};});
 assert(state.ready);assert.equal(state.voice.engine,'MOSS-TTSD-v1.0');assert.equal(state.voice.voice_id,'v04');assert(state.profile.includes('MOSS 04'));report.checks.actual_engine_and_voice_selected=true;
 await page.locator('#connectBtn').click();
 await page.waitForFunction(()=>window.studio?.connected&&window.studio.transport.frames>25,null,{timeout:180000});
 report.checks.avatar_preview_connected=true;console.log(JSON.stringify({event:'preview_connected'}));
 async function submit(text,mode='echo'){
   const mark=await page.evaluate(()=>({at:performance.now(),events:window.mossQA.events.length,audio:window.mossQA.audio.length}));
   await page.locator(mode==='chat'?'#chatTab':'#echoTab').click();
   await page.locator('#scriptText').fill(text);await page.locator('#speakBtn').click();
   return mark;
 }
 async function completion(mark,name){
   await page.waitForFunction(mark=>window.mossQA.events.slice(mark.events).some(item=>item.status==='end'||item.status==='error'),mark,{timeout:240000});
   const result=await page.evaluate(mark=>({events:window.mossQA.events.slice(mark.events),audio:window.mossQA.audio.slice(mark.audio),elapsed:(performance.now()-mark.at)/1000,transport:window.studio.transport.metrics()}),mark);
   const failures=result.events.filter(item=>item.status==='error');assert.deepEqual(failures,[]);
   const start=result.events.find(item=>item.status==='start');assert(start,'No actual audio-start event');assert.equal(start.tts_engine,'MOSS');assert.equal(start.voice_id,'v04');
   assert(result.audio.some(item=>item.rms>.002),'No non-silent scheduled browser audio');
   const voiced=result.audio.filter(item=>item.rms>.002),first=voiced[0].at,last=voiced.at(-1).at;
   const allGaps=result.audio.slice(1).map((item,index)=>({at:item.at,gap:(item.at-result.audio[index].at-result.audio[index].duration)*1000}));
   const gaps=allGaps.filter(item=>item.at>first&&item.at<=last).map(item=>item.gap);
   report.diagnostics={name,gaps:gaps.filter(gap=>gap>1),idle_buffer_resets:allGaps.filter(item=>item.gap>1&&(item.at<=first||item.at>last)).length,transport:result.transport,events:result.events};
   fs.writeFileSync(path.join(temporary,'latest-playback.json'),JSON.stringify(result,null,2));
   assert.equal(gaps.filter(gap=>gap>1).length,0,'Browser audio schedule has gaps');
   const entry={name,ok:true,text:start.text,first_audio_event_seconds:(start.at-mark.at)/1000,first_voiced_playback_seconds:(voiced[0].received_at-mark.at)/1000+Math.max(0,voiced[0].at-voiced[0].now),total_seconds:result.elapsed,voiced_frames:voiced.length,audio_schedule_gap_count:0,idle_buffer_resets:report.diagnostics.idle_buffer_resets,transport_fps:result.transport.fps,missing_packets:result.transport.missing_packets};
   const playbackEnd=result.audio.at(-1).at+result.audio.at(-1).duration;
   await page.waitForFunction(end=>window.mossQA.context.currentTime>=end,playbackEnd,{timeout:15000});
   report.cases.push(entry);console.log(JSON.stringify(entry));await page.waitForTimeout(300);return entry;
 }
 let mark=await submit('你好，我是林知夏。欢迎来到直播间，今天过得怎么样？别着急，我们慢慢聊。');
 await page.waitForFunction(mark=>window.mossQA.events.slice(mark.events).some(item=>item.status==='start'||item.status==='error'),mark,{timeout:180000});
 const recording=await page.evaluate(()=>{
   const media=document.getElementById('preview').srcObject;
   window.mossChunks=[];window.mossRecorder=new MediaRecorder(media,{mimeType:'video/webm;codecs=vp8,opus',videoBitsPerSecond:2000000});
   window.mossRecorder.ondataavailable=event=>{if(event.data.size)window.mossChunks.push(event.data);};
   window.mossRecorder.start(300);return true;
 });assert(recording);
 await completion(mark,'shared audition text through the live avatar');
 await page.evaluate(()=>new Promise(resolve=>{window.mossRecorder.onstop=resolve;window.mossRecorder.stop();}));
 const recordingBytes=await page.evaluate(async()=>Array.from(new Uint8Array(await new Blob(window.mossChunks,{type:'video/webm'}).arrayBuffer())));
 fs.writeFileSync(path.join(temporary,'moss-04-live-demo.webm'),Buffer.from(recordingBytes));
 await page.screenshot({path:path.join(root,'docs/media/moss-04-live-studio.png'),fullPage:true});
 mark=await submit('今天的风很轻。我们先喝口水，再聊聊你最近最开心的一件事。');
 await completion(mark,'novel Mandarin text');
 mark=await submit('这是一条准备被打断的长消息。我会继续介绍今天的安排，现在先暂停，等你发来新的问题。');
 await page.waitForFunction(async()=>{const s=await(await fetch('/api/studio/status')).json();return s.voice?.busy===true;},null,{timeout:30000});
 await page.locator('#stopBtn').click();
 await page.waitForFunction(async()=>{const s=await(await fetch('/api/studio/status')).json();return s.voice?.busy===false;},null,{timeout:25000});
 const cancelled=await page.evaluate(mark=>window.mossQA.events.slice(mark.events),mark);
 assert(!cancelled.some(item=>item.status==='start'),'Interrupted old speech started playing');
 report.cases.push({name:'cancel actual generation before playback',ok:true,stale_audio_started:false});console.log(JSON.stringify({event:'actual_generation_cancelled'}));
 mark=await submit('刚才的播报已经停止。现在这句话，是重新生成的 MOSS 四号声音。');
 await completion(mark,'new speech after interruption');
 if(process.env.MOSS_TEST_CHAT==='1'){
   mark=await submit('请用三十个汉字左右、一个完整句子邀请我聊聊今天的大学生活，不要列举。','chat');
   await completion(mark,'configured cloud text reply spoken by local MOSS');
   report.checks.cloud_reply_uses_local_moss=true;
 }
 report.checks.complete_audio_playback_without_schedule_gaps=true;report.checks.cancellation_and_following_request=true;
 assert.deepEqual(errors,[]);report.checks.no_browser_script_errors=true;
 await page.locator('#disconnectBtn').click();assert(!await page.evaluate(()=>window.studio.connected));report.checks.preview_closed=true;
 report.ok=true;
}catch(error){report.error=error.stack||error.message;process.exitCode=1;}
finally{if(browser)await browser.close();report.browser_closed=true;report.checked_at=new Date().toISOString();fs.writeFileSync(path.join(root,'docs/evidence/moss-live-browser.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));}
})();
