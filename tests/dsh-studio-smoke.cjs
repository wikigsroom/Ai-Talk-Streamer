/* Native browser test of the operator flow against the actual media/LLM services.
 * Refuses to touch an existing broadcast; closes only its own browser context. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {DatabaseSync}=require('node:sqlite');
const root=path.resolve(process.argv[2]||path.join(__dirname,'..'));
const {chromium}=require(path.join(root,'tools/dsh-browser/node_modules/playwright-core'));
const origin=process.env.DSH_TEST_BASE_URL||'http://127.0.0.1:8010';
const out=path.join(root,'outputs/dsh-humanity/public');fs.mkdirSync(out,{recursive:true});
const report={schema_version:1,kind:'native_studio_session_flow',started_at:new Date().toISOString(),passed:false,cloud_llm_exercised:false,checks:{}};
const save=()=>fs.writeFileSync(path.join(out,'studio-session-flow.json'),JSON.stringify(report,null,2)+'\n');
const progress=event=>console.log(JSON.stringify({at:new Date().toISOString(),event}));
let context,page,db,createdBroadcast;
(async()=>{
 try{
  context=await chromium.launchPersistentContext(path.join(root,'cache/dsh-browser','studio-flow-'+process.pid+'-'+Date.now()),{
   executablePath:process.env.DSH_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,acceptDownloads:true,
   viewport:{width:1380,height:1000},env:{...process.env,TEMP:path.join(root,'cache/tmp'),TMP:path.join(root,'cache/tmp')},
   args:['--no-proxy-server','--disable-gpu','--autoplay-policy=no-user-gesture-required']});
  const api=async(route,body)=>{const r=body===undefined?await context.request.get(origin+'/api/dsh/'+route):await context.request.post(origin+'/api/dsh/'+route,{data:body});const v=await r.json();assert.ok(r.ok(),route+':'+v.error);return v;};
  assert.equal((await api('status')).broadcast,null,'Refuse an existing user broadcast');
  page=context.pages()[0]||await context.newPage();const browserErrors=[],sends=[];
  await page.addInitScript(()=>{
   window.dshAudioStarts=[];const start=AudioBufferSourceNode.prototype.start;
   AudioBufferSourceNode.prototype.start=function(at,...args){window.dshAudioStarts.push({at,duration:this.buffer?.duration||0,voiced:this.buffer?.getChannelData(0).some(v=>Math.abs(v)>.001)||false});return start.call(this,at,...args);};
  });
  page.on('pageerror',error=>browserErrors.push(error.message));
  page.on('request',request=>{if(request.url()===origin+'/api/studio/speak'&&request.method()==='POST')sends.push(request);});
  await page.goto(origin+'/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('#dshIdentity').textContent==='观众模式');
  assert.ok(await page.isDisabled('#speakBtn'));assert.ok(await page.isDisabled('#dshStart'));
  await page.click('#chatTab');await page.click('#connectBtn');
  await page.waitForFunction(()=>window.studio?.connected&&window.avatarTransport?.frames>25,null,{timeout:120000});
  assert.ok(await page.isDisabled('#speakBtn'),'Preview must not enable sending while off air');
  await page.locator('#scriptText').press('Control+Enter');
  await page.waitForFunction(()=>document.querySelector('#feedback').textContent.includes('尚未开始会话'));
  assert.equal(sends.length,0);report.checks.offair_preview_and_shortcut_guard=true;
  await page.click('#dshStart');
  await page.waitForFunction(()=>document.querySelector('#dshLogin').open&&document.querySelector('#dshFeedback').textContent.includes('管理员登录'));
  assert.equal((await api('status')).broadcast,null);report.checks.anonymous_start_requires_login=true;
  await page.fill('#dshLoginToken','invalid-test-token');await page.click('#dshLoginForm button');
  await page.waitForFunction(()=>document.querySelector('#dshFeedback').textContent.includes('令牌不正确'));
  assert.equal(await page.inputValue('#dshLoginToken'),'');report.checks.invalid_login_explained_and_cleared=true;
  await page.fill('#dshLoginToken',fs.readFileSync(path.join(root,'configs/dsh-operator.token'),'utf8').trim());
  await page.click('#dshLoginForm button');
  await page.waitForFunction(()=>document.querySelector('#dshIdentity').textContent==='管理员已登录');
  assert.equal(await page.inputValue('#dshLoginToken'),'');
  await page.screenshot({path:path.join(out,'studio-session-offair.png'),fullPage:true});
  report.checks.inline_operator_login=true;progress('preview_and_login_passed');
  await page.click('#dshStart');
  await page.waitForFunction(()=>document.querySelector('#dshLiveState').dataset.state==='LIVE'&&!document.querySelector('#speakBtn').disabled,null,{timeout:20000});
  const live=await api('status');createdBroadcast=live.broadcast.broadcast_id;report.broadcast_id=createdBroadcast;report.channel=live.health.channel;
  assert.ok(live.health.persona_injection_ready);assert.ok(live.health.authority_ready);
  report.checks.explicit_start_enables_send=true;
  // Controlled race: the session can end after preflight and before POST reaches the server.
  await page.route('**/api/studio/speak',route=>route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:'BROADCAST_NOT_LIVE'})}),{times:1});
  await page.click('#speakBtn');
  await page.waitForFunction(()=>document.querySelector('#feedback').textContent.includes('当前会话尚未开始或已暂停'));
  assert.ok(!(await page.textContent('#activityLog')).includes('BROADCAST_NOT_LIVE'));
  report.checks.controlled_late_409_has_actionable_message=true;
  await page.waitForFunction(()=>!document.querySelector('#speakBtn').disabled);
  await page.click('#recordBtn');
  await page.fill('#scriptText','你叫什么名字？请用一句不超过25字的话介绍你的虚拟角色身份。');
  const responsePromise=page.waitForResponse(r=>r.url()===origin+'/api/studio/speak'&&r.request().method()==='POST');
  await page.click('#speakBtn');const response=await responsePromise;assert.ok(response.ok());const accepted=await response.json();
  report.request_id=accepted.request_id;report.cloud_llm_exercised=true;progress('real_ai_request_accepted');
  let terminal;const started=Date.now();
  for(let i=0;i<240;i++){
   const row=await api('requests/'+accepted.request_id);
   if(['COMPLETED','FAILED','CANCELLED','INTERRUPTED','UNKNOWN','EXPIRED'].includes(row.status)){terminal=row;break;}
   if(i%20===0)progress('real_ai_'+row.status);await page.waitForTimeout(1000);
  }
  assert.equal(terminal?.status,'COMPLETED');report.request_status=terminal.status;report.elapsed_seconds=(Date.now()-started)/1000;
  db=new DatabaseSync(path.join(root,'state/female-a/stream.sqlite3'),{readOnly:true});db.exec('PRAGMA busy_timeout=5000');
  const text=db.prepare("SELECT p.payload_json FROM stream_events e JOIN event_payloads p USING(event_seq) WHERE e.request_id=? AND e.event_type='utterance.text_ready'").get(accepted.request_id);
  report.reply=JSON.parse(text.payload_json).text;assert.ok(report.reply.includes('林知夏'));
  report.utterances=db.prepare('SELECT status,valid_sample_count,contiguous_played_samples,completion_event_seq FROM utterances WHERE request_id=?').all(accepted.request_id);
  assert.equal(report.utterances.length,1);assert.equal(report.utterances[0].valid_sample_count,report.utterances[0].contiguous_played_samples);assert.ok(report.utterances[0].completion_event_seq);
  report.playback_metrics=await page.evaluate(()=>window.avatarTransport.metrics());
  const audio=await page.evaluate(()=>window.dshAudioStarts),first=audio.findIndex(v=>v.voiced),last=audio.findLastIndex(v=>v.voiced);
  assert.ok(first>=0,'Expected real non-silent PCM');const voiced=audio.slice(first,last+1),gaps=voiced.slice(1).map((v,i)=>(v.at-voiced[i].at-voiced[i].duration)*1000);
  report.voiced_interval={chunks:voiced.length,audio_gap_max_ms:Math.max(0,...gaps),audio_resets:gaps.filter(v=>v>1).length};
  assert.equal(report.voiced_interval.audio_resets,0,'No scheduling discontinuity inside spoken audio');
  assert.equal(report.playback_metrics.missing_packets,0);assert.equal(report.playback_metrics.decode_errors,0);
  report.checks.real_ai_natural_playback_completed=true;
  await page.screenshot({path:path.join(out,'studio-session-live.png'),fullPage:true});
  const downloadPromise=page.waitForEvent('download');await page.click('#recordBtn');await (await downloadPromise).saveAs(path.join(out,'studio-session-playback.webm'));
  await page.click('#dshPause');await page.waitForFunction(()=>document.querySelector('#dshLiveState').dataset.state==='PAUSED');
  assert.ok(await page.isDisabled('#speakBtn'));const before=sends.length;
  await page.locator('#scriptText').press('Control+Enter');
  await page.waitForFunction(()=>document.querySelector('#feedback').textContent.includes('会话已暂停'));
  assert.equal(sends.length,before);report.checks.pause_and_shortcut_guard=true;
  await page.click('#dshStart');
  await page.waitForFunction(()=>document.querySelector('#dshLiveState').dataset.state==='LIVE'&&!document.querySelector('#speakBtn').disabled);
  const resumed=await api('status');assert.equal(resumed.broadcast.broadcast_id,createdBroadcast);assert.ok(resumed.broadcast.runtime_epoch>live.broadcast.runtime_epoch);assert.ok(resumed.health.authority_ready);
  report.checks.resume_same_broadcast_reclaims_playback=true;
  report.metrics=await page.evaluate(()=>window.avatarTransport.metrics());
  assert.equal(report.metrics.missing_packets,0);assert.equal(report.metrics.decode_errors,0);
  await page.click('#dshEnd');await page.waitForFunction(()=>document.querySelector('#dshLiveState').dataset.state==='OFFAIR');
  assert.equal((await api('status')).broadcast,null);createdBroadcast=null;assert.ok(await page.isDisabled('#speakBtn'));report.checks.end_disables_send=true;
  assert.deepEqual(browserErrors,[]);report.browser_errors=browserErrors;report.passed=true;report.finished_at=new Date().toISOString();save();progress('all_session_flow_checks_passed');
 }catch(error){report.error={type:error.name,message:error.message.split('\n')[0],...(error.code==='ERR_ASSERTION'?{actual:error.actual,expected:error.expected}:{})};save();throw error;}
 finally{
  if(createdBroadcast&&context){try{const b=(await (await context.request.get(origin+'/api/dsh/status')).json()).broadcast;if(b?.broadcast_id===createdBroadcast)await context.request.post(origin+'/api/dsh/broadcast/end',{data:{broadcast_id:b.broadcast_id,expected_revision:b.revision}});}catch{}}
  db?.close();await context?.close();
 }
})().catch(error=>{console.error(error.message.split('\n')[0]);process.exitCode=1;});
