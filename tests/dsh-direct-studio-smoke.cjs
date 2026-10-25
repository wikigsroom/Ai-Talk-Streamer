/* Real open-access workstation test: fresh Chrome, no credentials or initial start.
 * No device allowlist or authentication. Never touches an existing broadcast. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(process.argv[2]||path.join(__dirname,'..'));
const {chromium}=require(process.env.DSH_PLAYWRIGHT_MODULE||path.join(root,'tools/dsh-browser/node_modules/playwright-core'));
const origin=process.env.DSH_TEST_BASE_URL||'http://127.0.0.1:8010';
const out=path.resolve(process.env.DSH_TEST_OUTPUT||path.join(root,'outputs/dsh-humanity/direct-studio'));
fs.mkdirSync(out,{recursive:true});fs.mkdirSync(path.join(root,'cache/tmp'),{recursive:true});
const report={schema_version:1,kind:'native_open_access_studio',started_at:new Date().toISOString(),passed:false,cloud_llm_exercised:false,checks:{},turns:[]};
const save=()=>fs.writeFileSync(path.join(out,'direct-studio-flow.json'),JSON.stringify(report,null,2)+'\n');
const progress=event=>console.log(JSON.stringify({at:new Date().toISOString(),event}));
let context,page,createdBroadcast;
(async()=>{
 try{
  context=await chromium.launchPersistentContext(path.join(root,'cache/dsh-browser','direct-studio-'+process.pid+'-'+Date.now()),{
   executablePath:process.env.DSH_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,acceptDownloads:true,
   viewport:{width:1380,height:1000},env:{...process.env,TEMP:path.join(root,'cache/tmp'),TMP:path.join(root,'cache/tmp')},
   args:['--no-proxy-server','--disable-gpu','--autoplay-policy=no-user-gesture-required']});
  const api=async(route,body)=>{const r=body===undefined?await context.request.get(origin+'/api/dsh/'+route):await context.request.post(origin+'/api/dsh/'+route,{data:body});const v=await r.json();assert.ok(r.ok(),route+':'+v.error);return v;};
  assert.equal((await api('status')).broadcast,null,'Refuse an existing user broadcast');
  page=context.pages()[0]||await context.newPage();const errors=[],manualLogins=[],sends=[];
  await page.addInitScript(()=>{
   window.dshAudioStarts=[];window.dshManualStarts=0;
   document.addEventListener('click',event=>{if(event.target.id==='dshStart')window.dshManualStarts++;});
   const start=AudioBufferSourceNode.prototype.start;
   AudioBufferSourceNode.prototype.start=function(at,...args){window.dshAudioStarts.push({at,duration:this.buffer?.duration||0,voiced:this.buffer?.getChannelData(0).some(v=>Math.abs(v)>.001)||false});return start.call(this,at,...args);};
  });
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{
   if(request.url()===origin+'/api/dsh/login')manualLogins.push(true);
   if(request.url()===origin+'/api/studio/speak'&&request.method()==='POST')sends.push(true);
  });
  const live=async()=>{
   await page.waitForFunction(()=>window.studio?.connected&&window.avatarTransport?.frames>25&&document.querySelector('#dshLiveState').dataset.state==='LIVE'&&!document.querySelector('#speakBtn').disabled,null,{timeout:120000});
   const s=await api('status');createdBroadcast=s.broadcast.broadcast_id;assert.ok(s.health.authority_ready);return s;
  };
  const end=async()=>{
   await page.click('#dshEnd');await page.waitForFunction(()=>document.querySelector('#dshLiveState').dataset.state==='OFFAIR',null,{timeout:20000});
   assert.equal((await api('status')).broadcast,null);createdBroadcast=null;
  };
  const submit=async(mode,text)=>{
   await page.click(mode==='chat'?'#chatTab':'#echoTab');await page.fill('#scriptText',text);
   await page.waitForFunction(()=>!document.querySelector('#speakBtn').disabled);
   const started=Date.now();
   const responsePromise=page.waitForResponse(r=>r.url()===origin+'/api/studio/speak'&&r.request().method()==='POST');
   await page.click('#speakBtn');const response=await responsePromise,accepted=await response.json();
   assert.ok(response.ok(),'Actual UI send: '+JSON.stringify(accepted));
   createdBroadcast=(await api('status')).broadcast.broadcast_id;
   progress('accepted_'+mode);let terminal;
   for(let i=0;i<180;i++){
    const row=await api('requests/'+accepted.request_id);
    if(['COMPLETED','FAILED','CANCELLED','INTERRUPTED','UNKNOWN','EXPIRED'].includes(row.status)){terminal=row;break;}
    if(i%20===0)progress(mode+'_'+row.status);await page.waitForTimeout(1000);
   }
   assert.equal(terminal?.status,'COMPLETED');
   const playback=await page.evaluate(id=>{
    const p=window.avatarTransport.dsh;
    return [...p.utterances.values()].filter(u=>u.request_id===id).map(u=>({played_samples:u.played,valid_sample_count:u.valid_sample_count,natural_end:u.naturalEnded,cancelled:u.cancelled,lost:u.lost}));
   },accepted.request_id);
   assert.equal(playback.length,1);assert.ok(playback[0].natural_end&&!playback[0].cancelled&&!playback[0].lost);
   assert.ok(playback[0].played_samples>0);assert.equal(playback[0].played_samples,playback[0].valid_sample_count);
   const audio=await page.evaluate(id=>[...window.avatarTransport.dsh.utterances.values()].find(u=>u.request_id===id).spans.map(span=>({at:span.start,duration:span.count/span.rate,voiced:span.source.buffer.getChannelData(0).some(v=>Math.abs(v)>.001)})),accepted.request_id);
   const first=audio.findIndex(v=>v.voiced),last=audio.findLastIndex(v=>v.voiced);
   assert.ok(first>=0,'Require audible PCM');const voiced=audio.slice(first,last+1),gaps=voiced.slice(1).map((v,i)=>(v.at-voiced[i].at-voiced[i].duration)*1000);
   const turn={mode,request_id:accepted.request_id,broadcast_id:createdBroadcast,status:terminal.status,elapsed_seconds:(Date.now()-started)/1000,playback,voiced_interval:{chunks:voiced.length,audio_gap_max_ms:Math.max(0,...gaps),audio_resets:gaps.filter(v=>v>1).length}};
   turn.voiced_interval.scope='Mapped samples of this request only; excludes deliberate pause/end fences and idle packets';
   report.turns.push(turn);save();assert.equal(turn.voiced_interval.audio_resets,0);return turn;
  };
  await page.goto(origin+'/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('#dshIdentity').textContent==='直接使用',null,{timeout:20000});
  const who=await api('whoami');assert.equal(who.authentication_required,false);assert.equal(await page.locator('#dshLogin').count(),0);
  assert.equal((await context.cookies(origin)).filter(c=>c.name==='dsh_session').length,0);
  const openSession=await context.request.post(origin+'/api/dsh/session',{data:{},headers:{Origin:'http://different.example',Authorization:'Bearer invalid'}});
  assert.ok(openSession.ok());assert.equal((await openSession.json()).authentication_required,false);
  const channel=await (await context.request.get(origin+'/api/studio/channel')).json();
  const write=await context.request.post(origin+'/api/studio/channel',{data:channel});assert.ok(write.ok(),'Channel settings must be writable without credentials');
  report.checks.settings_write_without_credentials=true;
  const memory=await context.newPage();await memory.goto(origin+'/memory',{waitUntil:'domcontentloaded'});
  await memory.waitForFunction(()=>document.querySelector('#pageInfo').textContent.includes('本页'));
  assert.equal(await memory.locator('#loginForm').count(),0);
  await memory.screenshot({path:path.join(out,'direct-studio-memory.png'),fullPage:true});await memory.close();report.checks.memory_management_without_login=true;
  report.checks.fresh_browser_no_authentication=true;
  await page.screenshot({path:path.join(out,'direct-studio-connected.png'),fullPage:true});
  await page.click('#chatTab');await page.click('#connectBtn');const initial=await live();
  assert.equal(await page.evaluate(()=>window.dshManualStarts),0);
  assert.ok(initial.health.persona_injection_ready);report.channel=initial.health.channel;
  report.checks.preview_automatically_starts_session=true;progress('fresh_workstation_ready');
  await page.click('#recordBtn');
  await submit('chat','你叫什么名字？请用一句不超过25字的话介绍你的虚拟角色身份。');
  report.cloud_llm_exercised=true;
  report.reply=await page.evaluate(()=>[...document.querySelectorAll('#activityLog p')].map(p=>p.textContent).find(t=>t.includes('发送语音：')&&t.includes('林知夏'))||'');
  assert.ok(report.reply.includes('林知夏'),'Actual voice text must match the configured persona');
  report.checks.actual_ai_reply_and_natural_audio=true;
  report.playback_metrics=await page.evaluate(()=>window.avatarTransport.metrics());
  await page.screenshot({path:path.join(out,'direct-studio-live.png'),fullPage:true});
  const download=page.waitForEvent('download');await page.click('#recordBtn');await (await download).saveAs(path.join(out,'direct-studio-playback.webm'));
  await page.click('#dshPause');await page.waitForFunction(()=>document.querySelector('#dshLiveState').dataset.state==='PAUSED');
  assert.ok(await page.isDisabled('#speakBtn'));const before=sends.length;
  await page.locator('#scriptText').press('Control+Enter');await page.waitForFunction(()=>document.querySelector('#feedback').textContent.includes('会话已暂停'));
  assert.equal(sends.length,before);report.checks.explicit_pause_blocks_send=true;
  await page.click('#dshStart');const resumed=await live();assert.equal(resumed.broadcast.broadcast_id,initial.broadcast.broadcast_id);
  assert.ok(resumed.broadcast.runtime_epoch>initial.broadcast.runtime_epoch);report.checks.explicit_resume_keeps_context=true;
  await end();assert.ok(!await page.isDisabled('#speakBtn'));
  const restarted=await submit('echo','会话已经恢复，现在可以直接使用了。');assert.notEqual(restarted.broadcast_id,initial.broadcast.broadcast_id);
  report.checks.send_after_end_automatically_starts_new_session=true;
  await end();await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('#dshIdentity').textContent==='直接使用');
  report.checks.reload_requires_no_authentication=true;
  await page.click('#connectBtn');await live();assert.equal(await page.evaluate(()=>window.dshManualStarts),0);
  await submit('echo','刷新网页后，画面和声音也可以正常使用。');
  report.checks.reload_reconnect_and_audio_work=true;
  report.manual_login_requests=manualLogins.length;assert.equal(manualLogins.length,0);report.checks.no_manual_token_or_login=true;
  report.browser_errors=errors;assert.deepEqual(errors,[]);report.checks.no_browser_exceptions=true;
  await end();report.checks.cleanup_offair=true;report.passed=true;report.finished_at=new Date().toISOString();save();progress('all_direct_workstation_checks_passed');
 }catch(error){report.error={type:error.name,message:error.message.split('\n')[0],...(error.code==='ERR_ASSERTION'?{actual:error.actual,expected:error.expected}:{})};save();throw error;}
 finally{
  if(createdBroadcast&&context){try{const b=(await (await context.request.get(origin+'/api/dsh/status')).json()).broadcast;if(b?.broadcast_id===createdBroadcast)await context.request.post(origin+'/api/dsh/broadcast/end',{data:{broadcast_id:b.broadcast_id,expected_revision:b.revision}});}catch{}}
  await context?.close();
 }
})().catch(error=>{console.error(error.message.split('\n')[0]);process.exitCode=1;});
