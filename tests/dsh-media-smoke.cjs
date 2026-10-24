/* Native Chrome and real MOSS/MuseTalk. This test never substitutes an LLM. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(process.argv[2]||path.join(__dirname,'..'));
const {chromium}=require(path.join(root,'tools/dsh-browser/node_modules/playwright-core'));
const output=path.join(root,'outputs/dsh-humanity/public');fs.mkdirSync(output,{recursive:true});
const record=(event,data={})=>{const value={at:new Date().toISOString(),event,...data};fs.appendFileSync(path.join(root,'outputs/dsh-humanity/media-smoke.progress.jsonl'),JSON.stringify(value)+'\n');console.log(JSON.stringify(value));};
const origin=process.env.DSH_TEST_BASE_URL||'http://127.0.0.1:8010';
(async()=>{
 let context,page,started=false;const errors=[];
 try{
  context=await chromium.launchPersistentContext(path.join(root,'cache/dsh-browser/smoke'),{executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,acceptDownloads:true,
   viewport:{width:1380,height:1000},env:{...process.env,TEMP:path.join(root,'cache/tmp'),TMP:path.join(root,'cache/tmp')},args:['--no-proxy-server','--disable-gpu','--autoplay-policy=no-user-gesture-required']});
  for(let i=0;i<240;i++){try{const ready=await context.request.get(origin+'/api/studio/status',{timeout:2000});if(ready.ok())break;}catch{}if(i===239)throw Error('AVATAR_HTTP_NOT_READY');await new Promise(resolve=>setTimeout(resolve,1000));}
  const api=async(route,body)=>{const r=body===undefined?await context.request.get(origin+'/api/dsh/'+route):await context.request.post(origin+'/api/dsh/'+route,{data:body});const value=await r.json();if(!r.ok())throw Error(route+':'+value.error);return value;};
  await api('login',{token:fs.readFileSync(path.join(root,'configs/dsh-operator.token'),'utf8').trim()});
  page=context.pages()[0]||await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{window.dshAudioStarts=[];const start=AudioBufferSourceNode.prototype.start;AudioBufferSourceNode.prototype.start=function(at,...args){window.dshAudioStarts.push({at,duration:this.buffer?.duration||0,clock:this.context.currentTime,voiced:this.buffer?.getChannelData(0).some(v=>Math.abs(v)>.001)||false});return start.call(this,at,...args)};});
  await page.goto(origin+'/',{waitUntil:'domcontentloaded'});await page.click('#connectBtn');
  await page.waitForFunction(()=>window.avatarTransport?.frames>25,null,{timeout:180000});record('preview_ready');
  for(let i=0;i<240;i++){const h=(await api('status')).health;if(h.tts_ready&&h.avatar_ready)break;if(i===239)throw Error('MEDIA_NOT_READY');await page.waitForTimeout(1000)}record('media_ready');
  let status=await api('status');if(status.broadcast){await api('broadcast/end',{});for(let i=0;i<45&&(await api('status')).broadcast;i++)await page.waitForTimeout(1000);}
  await page.click('#dshStart');await page.waitForFunction(()=>document.querySelector('#dshLiveState').textContent.includes('LIVE'),null,{timeout:20000});started=true;
  record('echo_live',{channel_ai_ready:(await api('status')).health.persona_injection_ready});
  await page.screenshot({path:path.join(output,'studio-dsh.png'),fullPage:true});
  const wait=async(id)=>{for(let i=0;i<180;i++){const row=await api('requests/'+id);if(['COMPLETED','FAILED','CANCELLED','INTERRUPTED','UNKNOWN'].includes(row.status))return row;if(i%10===0)record('playing_progress',{request_id:id,status:row.status,metrics:await page.evaluate(()=>({transport:window.avatarTransport.metrics(),playback:window.avatarTransport.dsh.metrics()}))});await page.waitForTimeout(1000)}throw Error('REQUEST_TIMEOUT');};
  await page.click('#recordBtn');const before=await page.evaluate(()=>({metrics:window.avatarTransport.metrics(),audio:window.dshAudioStarts.length}));
  const a=await api('requests',{text:'你好，我是林知夏。这是加入人格与记忆管理后的本地播报验证。',mode:'echo',idempotency_key:crypto.randomUUID()});record('echo_submitted',{request_id:a.request_id});
  const result=await wait(a.request_id);record('echo_terminal',{request_id:a.request_id,status:result.status});assert.equal(result.status,'COMPLETED');
  await page.waitForTimeout(1000);const downloadPromise=page.waitForEvent('download');await page.click('#recordBtn');const download=await downloadPromise;await download.saveAs(path.join(output,'echo-playback.webm'));
  const metrics=await page.evaluate(()=>({transport:window.avatarTransport.metrics(),playback:window.avatarTransport.dsh.metrics(),audio:window.dshAudioStarts}));
  const recorded=metrics.audio.slice(before.audio),firstVoice=recorded.findIndex(v=>v.voiced),lastVoice=recorded.findLastIndex(v=>v.voiced),voicedInterval=recorded.slice(firstVoice,lastVoice+1);
  assert.ok(firstVoice>=0,'Expected actual non-silent PCM');
  const gaps=voicedInterval.slice(1).map((v,i)=>(v.at-voicedInterval[i].at-voicedInterval[i].duration)*1000);
  record('continuity',{audio_gap_max_ms:Math.max(0,...gaps),audio_resets:gaps.filter(n=>n>1).length,transport:metrics.transport,playback:metrics.playback});
  const b=await api('requests',{text:'这段播报用于检查缓冲阶段停止。停止后旧音频应清空，重新输入可以继续。',mode:'echo',idempotency_key:crypto.randomUUID()});
  let buffered=false;for(let i=0;i<750;i++){const row=await api('requests/'+b.request_id);if(['AUDIO_READY','BUFFERING'].includes(row.status)){buffered=true;break;}if(row.status==='FAILED')throw Error('TTS_FAILED');await page.waitForTimeout(200)}assert.ok(buffered,'Expected real audio buffering before cancel');
  await api('cancel',{request_id:b.request_id});record('buffer_cancel',{request_id:b.request_id,status:(await api('requests/'+b.request_id)).status});
  const c=await api('requests',{text:'旧音频已停止。现在这句话属于新的请求，播放完成后才会进入已播上下文。',mode:'echo',idempotency_key:crypto.randomUUID()});
  const recovered=await wait(c.request_id);record('recovery_terminal',{status:recovered.status});assert.equal(recovered.status,'COMPLETED');
  const memoryPage=await context.newPage();await memoryPage.goto(origin+'/memory',{waitUntil:'networkidle'});await memoryPage.screenshot({path:path.join(output,'memory-dsh.png'),fullPage:true});await memoryPage.close();
  await api('broadcast/end',{});for(let i=0;i<45&&(await api('status')).broadcast;i++)await page.waitForTimeout(1000);started=false;
  const report={schema_version:1,passed:errors.length===0&&gaps.every(n=>n<=1)&&metrics.transport.missing_packets===0,kind:'real_media_echo_smoke',cloud_llm_exercised:false,requests:[result,recovered].map(r=>({request_id:r.request_id,status:r.status})),metrics:metrics.transport,audio_gap_max_ms:Math.max(0,...gaps),audio_resets:gaps.filter(n=>n>1).length,browser_errors:errors};
  fs.writeFileSync(path.join(output,'media-smoke.json'),JSON.stringify(report,null,2));record('finished',{passed:report.passed});assert.equal(report.passed,true,'Media continuity acceptance failed');
 }finally{
  if(started&&context){try{await context.request.post(origin+'/api/dsh/broadcast/end',{data:{}})}catch{}}
  await context?.close();
 }
})().catch(error=>{record('failed',{name:error.name,message:error.message.split('\n')[0]});process.exitCode=1});
