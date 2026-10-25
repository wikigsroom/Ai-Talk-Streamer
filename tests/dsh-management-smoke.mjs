// Real pinned DSH/Humanity + HTTP + native Chrome, in an isolated fixture ledger.
// No cloud call, real media inference, or production-memory mutation is performed.
import {createServer,request as httpRequest} from 'node:http';
import {mkdirSync,mkdtempSync,copyFileSync,writeFileSync,readFileSync,symlinkSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {StreamBridge} from '../backend/dsh-bridge/server.mjs';
import {loadPolicy} from '../backend/dsh-bridge/policy.mjs';
import {validateExtraction} from '../backend/memory/service.mjs';

const project=resolve(process.argv[2]||'.'),runtime=resolve(project,process.argv[3]||'tools/dsh');
const output=join(project,'outputs/dsh-humanity/management');mkdirSync(output,{recursive:true});
const root=mkdtempSync(join(output,'fixture-'));mkdirSync(join(root,'configs/characters'),{recursive:true});
copyFileSync(join(project,'configs/characters/female-a.json'),join(root,'configs/characters/female-a.json'));
writeFileSync(join(root,'configs/channel.env'),'AVATAR_LLM_MODEL=management-test-unused\nAVATAR_LLM_BASE_URL=http://127.0.0.1:1/v1\nAVATAR_LLM_API_KEY=unused-test-credential\n');
mkdirSync(join(root,'tools'),{recursive:true});symlinkSync(runtime,join(root,'tools/dsh'),'junction');
const policy=structuredClone(loadPolicy(root));policy.deployment.bridge_port=0;policy.deployment.management_port=0;
writeFileSync(join(root,'configs/test-policy.json'),JSON.stringify(policy));
let bridge,context,bridgeOrigin,requests=0;const errors=[],checks={};
const ui=createServer((req,res)=>{
 if(req.url.startsWith('/api/dsh/')){const proxy=httpRequest(bridgeOrigin+req.url,{method:req.method,headers:{...req.headers,'x-stream-original-host':req.headers.host}},up=>{res.writeHead(up.statusCode,up.headers);up.pipe(res);res.on('close',()=>up.destroy());});proxy.on('error',()=>{if(!res.headersSent)res.writeHead(502);res.end();});req.pipe(proxy);return;}
 if(req.url==='/api/studio/status'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({tts_ready:true,avatar_ready:true}));return;}
 if(req.url.startsWith('/internal/dsh/')){requests++;res.setHeader('Content-Type','application/json');res.end('{}');return;}
 const file=req.url.split('?')[0]==='/memory'?'memory.html':req.url.split('?')[0].slice(1);
 if(!['memory.html','memory.js','memory.css','browser-id.js'].includes(file)){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');res.end(readFileSync(join(project,'web',file)));
});
try{
 await new Promise(resolve=>ui.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+ui.address().port;
 bridge=await new StreamBridge(root,join(root,'tools/dsh'),{policyFile:'configs/test-policy.json',avatarUrl:origin}).start();clearInterval(bridge.timer);clearInterval(bridge.maintenanceTimer);
 bridgeOrigin='http://127.0.0.1:'+bridge.server.address().port;
 const call=async(path,body,expected=200)=>{const response=await fetch(bridgeOrigin+'/api/dsh/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(5000)});const value=await response.json();assert.equal(response.status,expected,JSON.stringify({path,value}));return value;};
 const viewer=bridge.auth.ensure('viewer-test-credential-'.padEnd(48,'x'),'viewer','观众','test-viewer');
 await call('memory');checks.management_without_authentication=true;
 const broadcast=await call('broadcast/start',{});await call('playback/claim',{broadcast_id:broadcast.broadcast_id,consumer_id:'fixture-browser'});
 await call('broadcast/ready',{broadcast_id:broadcast.broadcast_id,expected_revision:broadcast.revision,mode:'echo'});
 const op={role:'operator',principal_id:'fixture-operator',viewer_id:'operator-local'};
 const seed=(factKey='preference.drink',state='active')=>{
  const request=bridge.state.accept(op,{text:'我喜欢茶。',mode:'echo',public_input:true,idempotency_key:crypto.randomUUID()});bridge.state.cancel(request.request_id);
  const source=bridge.memory.eligibleEvents(request.broadcast_id,'public').at(-1);
  const extraction={schema_version:1,summary:'测试来源',open_questions:[],candidate_facts:[{fact_key:'preference.drink',value:'tea',polarity:'positive',evidence_kind:'viewer_statement',validity:'persistent_candidate',source_refs:[{event_id:source.event_id,quote:source.text}]}]};
  const candidate={...validateExtraction(extraction,[source],'public')[0],fact_key:factKey,state};
  const result=bridge.db.tx(()=>bridge.memory.mergeInTransaction(candidate,'management-fixture',0));return bridge.db.get('SELECT * FROM memory_entries WHERE memory_id=?',result.memory_id);
 };
 const first=seed(),second=seed('preference.drink','proposed');for(let i=0;i<53;i++)seed('fixture.fact.'+i,'proposed');await bridge.memory.project();
 const source=await call('memory/source?memory_id='+encodeURIComponent(first.memory_id));assert.equal(source.sources.length,1);checks.source_http=true;
 const archive={operation_id:crypto.randomUUID(),memory_id:first.memory_id,expected_revision:1,reason:'接口归档验证'};const a=await call('memory/archive',archive);assert.deepEqual(await call('memory/archive',archive),a);
  for(let i=0;i<50&&bridge.host.port.inspectProjection(first.memory_id)?.entry?.status==='active';i++){await bridge.memory.project();await new Promise(resolve=>setTimeout(resolve,20));}
  assert.notEqual(bridge.host.port.inspectProjection(first.memory_id)?.entry?.status,'active');assert.equal(bridge.memory.recall('public').public.length,0);
 await call('memory/undo',{operation_id:archive.operation_id});checks.archive_and_compensating_undo=true;
 const merged=await call('memory/merge',{operation_id:crypto.randomUUID(),target_memory_id:first.memory_id,inputs:[{memory_id:first.memory_id,expected_revision:3},{memory_id:second.memory_id,expected_revision:1}],reason:'接口等值合并验证'});
 const undone=await call('memory/undo',{operation_id:merged.merge_id});assert.equal(undone.restored.length,2);checks.merge_and_group_undo=true;
 const live=(await call('status')).broadcast;await call('broadcast/pause',{broadcast_id:live.broadcast_id,expected_revision:0},409);assert.equal(bridge.state.current().state,'LIVE');checks.stale_control_refused=true;
 await call('broadcast/end',{broadcast_id:live.broadcast_id,expected_revision:live.revision});bridge.state.tick();
 const closed=(await call('broadcasts')).broadcasts[0];const rebuild=await call('jobs/rebuild',{operation_id:crypto.randomUUID(),broadcast_id:closed.broadcast_id,expected_source_revision:closed.source_revision,partition_key:'public',source_start_seq:closed.source_start_seq,source_end_seq:closed.ended_event_seq,reason:'接口范围重建验证'},202);
 assert.equal(rebuild.source_end_seq,closed.ended_event_seq);checks.frozen_rebuild_http=true;
 const require=createRequire(join(project,'tools/dsh-browser/package.json'));const {chromium}=require('playwright-core');
 mkdirSync(join(root,'cache/tmp'),{recursive:true});context=await chromium.launchPersistentContext(join(root,'cache/chrome-management'),{executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,viewport:{width:1440,height:1120},env:{...process.env,TEMP:join(root,'cache/tmp'),TMP:join(root,'cache/tmp')},args:['--no-proxy-server','--disable-gpu']});
 const page=context.pages()[0]||await context.newPage();page.on('pageerror',error=>errors.push(error.message));await page.goto(origin+'/memory',{waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>document.querySelector('#pageInfo').textContent.includes('本页 50 条'));
 await page.click('#nextPage');await page.waitForFunction(()=>document.querySelector('#pageInfo').textContent.includes('第 2 页'));await page.click('#previousPage');await page.waitForFunction(()=>document.querySelector('#pageInfo').textContent.includes('第 1 页'));checks.browser_keyset_pagination=true;
 await page.fill('#filterFact','preference.drink');await page.click('#memoryFilters button');await page.waitForFunction(()=>document.querySelectorAll('#memoryRows tr').length===2);
 const row=page.locator('#memoryRows tr').filter({has:page.locator('td', {hasText:'active / r5'})});await row.getByRole('button',{name:'归档',exact:true}).click();await page.fill('#archiveReason','浏览器归档验证');await page.click('#archiveForm button[type=submit], #archiveForm button:not([type])');await page.waitForFunction(()=>document.querySelector('#feedback').textContent.includes('操作已保存'));
 await page.click('#undoForm button');await page.waitForFunction(()=>document.querySelector('#feedback').textContent.includes('补偿修订已保存'));checks.browser_archive_undo=true;
 await page.locator('#memoryRows input[type=checkbox]').nth(0).check();await page.locator('#memoryRows input[type=checkbox]').nth(1).check();await page.click('#mergeSelected');await page.fill('#mergeReason','浏览器等值合并验证');await page.locator('#mergeForm button').first().click();await page.waitForFunction(()=>document.querySelector('#feedback').textContent.includes('操作已保存'));checks.browser_merge=true;
 await page.screenshot({path:join(output,'management-fixture.png'),fullPage:true});
 await page.click('[data-tab=jobs]');await page.waitForFunction(()=>document.querySelector('#rebuildBroadcast').options.length===1);await page.fill('#rebuildReason','浏览器范围重建验证');await page.locator('#rebuildForm button').click();await page.waitForFunction(()=>document.querySelector('#feedback').textContent.includes('已创建 job-'));checks.browser_rebuild=true;
 await page.waitForFunction(()=>!!document.querySelector('#memoryRevision').textContent.includes('主账本 r'));assert.ok(bridge.events.clients.size>0);checks.browser_event_subscription=true;
 assert.deepEqual(errors,[]);assert.equal(requests,0,'Fixture inputs must never invoke TTS');
 const report={schema_version:1,checked_at:new Date().toISOString(),passed:true,kind:'isolated_native_dsh_humanity_http_chrome_management',fixture_facts:true,production_memory_mutated:false,cloud_llm_exercised:false,media_inference_exercised:false,checks,browser_errors:errors};
 writeFileSync(join(output,'management-smoke.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{
 await context?.close();await bridge?.close();const closing=new Promise(resolve=>ui.close(resolve));ui.closeAllConnections();await closing;
}
