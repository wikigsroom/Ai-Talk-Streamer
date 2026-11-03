// Existing pinned native DSH/Humanity; loopback held provider responses only.
// No real model, Minecraft, avatar, audio, official client or production state.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { DshHost } from '../backend/dsh-bridge/host.mjs';
import { initialPersona } from '../backend/dsh-bridge/persona.mjs';
import { loadPolicy } from '../backend/dsh-bridge/policy.mjs';

const root=resolve(process.argv[2]),runtime=resolve(process.argv[3]),output=resolve(process.env.MC_INTENT_EVIDENCE_ROOT);
assert(relative(root,output)&&!relative(root,output).startsWith('..'));mkdirSync(output,{recursive:true});
const policy=structuredClone(loadPolicy(root));
policy.deployment.dsh_home_relative_path=relative(root,join(output,'isolated-dsh-home')).replaceAll('\\','/');
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
const outcome=promise=>promise.then(value=>({value}),error=>({error}));
const report={result:'FAIL',classification:'ACTUAL_PINNED_DSH_HUMANITY_SHUTDOWN_WITH_HELD_LOOPBACK_PROVIDER',
 cases:[],requests:[],real_model:false,real_minecraft:false,official_client:false,public_broadcast:false};
const sockets=new Set();let host,gate,active=0,maximumActive=0;
const save=()=>writeFileSync(join(output,'native-dsh-lifecycle-probe.json'),JSON.stringify(report,null,2)+'\n');
const hardDeadline=setTimeout(()=>{report.error='NATIVE_LIFECYCLE_PROBE_DEADLINE';save();process.exit(1);},55000);
const server=createServer(async(req,res)=>{
 active++;maximumActive=Math.max(maximumActive,active);const current=gate;
 res.once('close',()=>{active--;current?.release.resolve();});
 try{
  assert.equal(req.url,'/v1/chat/completions');const chunks=[];for await(const chunk of req)chunks.push(chunk);
  const body=JSON.parse(Buffer.concat(chunks));report.requests.push({purpose:current.purpose,tools:body.tools?.map(t=>t.function.name)||[]});
  current.entered.resolve();await current.release.promise;
  if(!res.destroyed)res.destroy();
 }catch(error){report.server_error=error.code||'NATIVE_PROVIDER_FIXTURE_FAILED';res.destroy();}
});
server.on('connection',socket=>{sockets.add(socket);socket.once('close',()=>sockets.delete(socket));});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin='http://127.0.0.1:'+server.address().port;
const snapshot={revision:'native-lifecycle-fixture',model:'local-held-fixture',protocol:'chat_completions',
 baseUrl:origin+'/v1',systemPrompt:'',getApiKey:()=>'unused-local-fixture'};
const originalFetch=globalThis.fetch;
globalThis.fetch=(input,options)=>{
 const url=new URL(typeof input==='string'||input instanceof URL?input:input.url);
 assert.equal(url.origin,origin);assert.equal(url.pathname,'/v1/chat/completions');return originalFetch(input,options);
};
async function waitFor(promise){let timer;try{await Promise.race([promise,new Promise((_,reject)=>{
 timer=setTimeout(()=>reject(Error('LOCAL_PROVIDER_ENTRY_DEADLINE')),10000);
})]);}finally{clearTimeout(timer);}}
try{
 for(const purpose of ['operator_private','speech','game_plan','maintenance','audience_intent']){
  console.log(JSON.stringify({event:'native.lifecycle.case_start',purpose}));
  host=await new DshHost(root,runtime,policy).start();const persona=initialPersona(root);await host.publishCharacter(persona.document,persona.version);
  gate={purpose,entered:deferred(),release:deferred()};
  const sessionId=(purpose==='audience_intent'?'mc-intent-':'native-stop-')+randomUUID();
  const running=outcome(host.generate({sessionId,purpose,snapshot,input:'isolated-lifecycle-source-'+sessionId,
   maxTokens:64,tools:async()=>({})}));
  await waitFor(gate.entered.promise);
  const queued=[];
  if(purpose==='operator_private')for(const next of ['speech','game_plan','audience_intent','maintenance','operator_private'])
   queued.push(outcome(host.generate({sessionId:(next==='audience_intent'?'mc-intent-':'native-queued-')+randomUUID(),
    purpose:next,snapshot,input:'must never reach provider',maxTokens:64,tools:async()=>({})})));
  const before=report.requests.length,started=Date.now();
  if(purpose==='audience_intent'){
   await host.quiesce();
   assert(!(await host.ctx.sessionPersistence.list()).some(row=>row.header.id===sessionId));
  }
  await host.close();
  const result=await running;assert.equal(result.error?.code,'MODEL_CANCELLED');
  for(const pending of queued)assert.equal((await pending).error?.code,'MODEL_CANCELLED');
  assert.equal(host.active.size,0);assert.equal(host.modelCalls.size,0);assert.equal(host.foregroundQueued||0,0);
  assert.equal(host.ready,false);assert.equal(report.requests.length,before);
  await assert.rejects(host.generate({sessionId:'late',purpose:'speech',snapshot,input:'late'}),{code:'DSH_HOST_CLOSING'});
  assert.equal(report.server_error,undefined);
  report.cases.push({id:'native_shutdown_'+purpose,result:'PASS',queued_cancelled:queued.length,elapsed_ms:Date.now()-started,
   active_sessions_after_close:host.active.size,model_calls_after_close:host.modelCalls.size,
   intent_session_removed_before_fiber_disposal:purpose==='audience_intent'});
 }
 assert.equal(maximumActive,1);assert.equal(report.requests.length,5);report.result='PASS';
}catch(error){report.error=String(error.stack||error);throw error;}
finally{
 gate?.release.resolve();
 try{await host?.close();}finally{
  globalThis.fetch=originalFetch;server.closeAllConnections();for(const socket of sockets)socket.destroy();
  await new Promise(resolve=>server.close(resolve));clearTimeout(hardDeadline);
  report.maximum_concurrent_provider_requests=maximumActive;report.native_host_closed=!host?.ready;
  report.remaining_http_sockets=sockets.size;report.recorded_at=new Date().toISOString();save();
  console.log(JSON.stringify({result:report.result,cases:report.cases.length,requests:report.requests.length,evidence:join(output,'native-dsh-lifecycle-probe.json')}));
 }
}
