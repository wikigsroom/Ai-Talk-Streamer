/* Two actual Chrome players, including the local OBS source page. No LLM substitute. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(process.argv[2]||path.join(__dirname,'..'));
const {chromium}=require(path.join(root,'tools/dsh-browser/node_modules/playwright-core'));
const output=path.join(root,'outputs/dsh-humanity/public');fs.mkdirSync(output,{recursive:true});
const origin=process.env.DSH_TEST_BASE_URL||'http://127.0.0.1:8010';
const record=(event,data={})=>{const row={at:new Date().toISOString(),event,...data};fs.appendFileSync(path.join(root,'outputs/dsh-humanity/authority-smoke.progress.jsonl'),JSON.stringify(row)+'\n');console.log(JSON.stringify(row));};
(async()=>{
 let context,started=false;const errors=[];
 try{
  context=await chromium.launchPersistentContext(path.join(root,'cache/dsh-browser/authority'),{executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,
   viewport:{width:1380,height:1000},env:{...process.env,TEMP:path.join(root,'cache/tmp'),TMP:path.join(root,'cache/tmp')},args:['--no-proxy-server','--disable-gpu','--autoplay-policy=no-user-gesture-required']});
  const api=async(route,body)=>{const r=body===undefined?await context.request.get(origin+'/api/dsh/'+route):await context.request.post(origin+'/api/dsh/'+route,{data:body});const value=await r.json();if(!r.ok())throw Error(route+':'+value.error);return value;};
  await api('login',{token:fs.readFileSync(path.join(root,'configs/dsh-operator.token'),'utf8').trim()});
  assert.equal((await api('status')).broadcast,null,'Run this test only when off air');
  const page=context.pages()[0]||await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  await page.goto(origin+'/',{waitUntil:'domcontentloaded'});await page.click('#connectBtn');
  await page.waitForFunction(()=>window.avatarTransport?.frames>25,null,{timeout:120000});
  const obs=await context.newPage();obs.on('pageerror',error=>errors.push(error.message));
  await obs.goto('http://127.0.0.1:8010/obs.html',{waitUntil:'domcontentloaded'});
  await obs.waitForFunction(()=>window.avatarTransport?.frames>25,null,{timeout:120000});
  const broadcast=await api('broadcast/start',{});started=true;
  await obs.waitForFunction(()=>!!window.avatarTransport?.dsh.lease,null,{timeout:20000});
  await api('broadcast/ready',{broadcast_id:broadcast.broadcast_id,mode:'echo'});
  assert.equal(await page.evaluate(()=>window.avatarTransport.dsh.metrics().authority),false,'Preview must not acquire authority');
  const refusal=await page.evaluate(async id=>{try{await window.avatarTransport.dsh.claim(id,false);return null}catch(error){return error.message}},broadcast.broadcast_id);
  assert.equal(refusal,'AUTHORITY_ALREADY_HELD');
  const scope=await obs.evaluate(async()=>{const p=window.avatarTransport.dsh;const headers={'Content-Type':'application/json',Authorization:'Bearer '+p.credential};const r=await fetch('/api/dsh/requests',{method:'POST',headers,body:JSON.stringify({text:'must not run',mode:'echo',idempotency_key:window.streamUUID()})});return {status:r.status,error:(await r.json()).error};});
  assert.equal(scope.status,403);record('obs_authority_and_scope',{preview_refusal:refusal,obs_chat_status:scope.status});
  const first=await api('requests',{text:'现在由本机浏览器中的 OBS 画面确认播放。稍后会切换到演播台。被打断的句子不能被登记为完整说过，新的句子需要单独确认。',mode:'echo',idempotency_key:crypto.randomUUID()});
  let playing;
  for(let i=0;i<900;i++){
   const row=await api('requests/'+first.request_id);
   if(row.status==='PLAYING'){
    const metric=await obs.evaluate(()=>window.avatarTransport.dsh.metrics());
    if(metric.utterances.some(u=>u.played_samples>=16000&&u.played_samples<u.valid_sample_count)){playing=metric;break;}
   }
   assert.ok(!['FAILED','CANCELLED','UNKNOWN','COMPLETED'].includes(row.status),'First request must still be playing');await page.waitForTimeout(200);
  }
  assert.ok(playing,'Expected a real partial playout prefix');record('obs_partial_playback',{request_id:first.request_id,utterances:playing.utterances});
  await page.screenshot({path:path.join(output,'authority-before-takeover.png'),fullPage:true});
  await page.evaluate(id=>window.avatarTransport.dsh.claim(id,true),broadcast.broadcast_id);
  const interrupted=await api('requests/'+first.request_id);
  assert.ok(['UNKNOWN','INTERRUPTED'].includes(interrupted.status),'Takeover cannot complete the old request; a late cancel acknowledgement may verify its partial prefix');
  await obs.waitForFunction(()=>!window.avatarTransport.dsh.lease,null,{timeout:12000});
  const browserAuthority=await page.evaluate(()=>window.avatarTransport.dsh.metrics());
  assert.equal(browserAuthority.authority,true);record('takeover',{request_id:first.request_id,status:interrupted.status,old_authority_revoked:true});
  const second=await api('requests',{text:'现在由演播台确认播放。上一句话已中断，这条新请求会独立完成。',mode:'echo',idempotency_key:crypto.randomUUID()});
  let completed;
  for(let i=0;i<180;i++){const row=await api('requests/'+second.request_id);if(row.status==='COMPLETED'){completed=row;break;}assert.ok(!['FAILED','CANCELLED','UNKNOWN'].includes(row.status));await page.waitForTimeout(1000);}
  assert.ok(completed,'Recovery must receive natural-end completion');
  await page.screenshot({path:path.join(output,'authority-after-takeover.png'),fullPage:true});
  await api('broadcast/end',{});for(let i=0;i<45&&(await api('status')).broadcast;i++)await page.waitForTimeout(1000);started=false;
  assert.deepEqual(errors,[]);
  const report={schema_version:1,checked_at:new Date().toISOString(),passed:true,kind:'real_two_chrome_players_with_obs_source_page',cloud_llm_exercised:false,
   obs_application_exercised:false,preview_cannot_claim:true,obs_chat_forbidden:true,old_authority_revoked:true,
   partial_played_samples:playing.utterances.find(u=>u.played_samples>0).played_samples,
   requests:[interrupted,completed].map(row=>({request_id:row.request_id,status:row.status})),browser_errors:errors};
  fs.writeFileSync(path.join(output,'authority-smoke.json'),JSON.stringify(report,null,2));record('finished',{passed:true});
 }finally{
  if(started&&context){try{await context.request.post(origin+'/api/dsh/broadcast/end',{data:{}})}catch{}}
  await context?.close();
 }
})().catch(error=>{record('failed',{name:error.name,message:error.message.split('\n')[0],actual:error.actual,expected:error.expected});process.exitCode=1});
