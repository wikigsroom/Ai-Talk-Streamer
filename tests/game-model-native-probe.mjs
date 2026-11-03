// Actual pinned DSH/Humanity, registration, agent loop and HTTP adapter.
// All model responses are scripted loopback SSE; MC is a protocol fixture.
// Uses a separate DSH_HOME, never production state, credentials or inference.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { DshHost } from '../backend/dsh-bridge/host.mjs';
import { initialPersona } from '../backend/dsh-bridge/persona.mjs';
import { loadPolicy } from '../backend/dsh-bridge/policy.mjs';
import { gameFixture, until } from './game-fixture.mjs';
import { narrationFixture } from './game-narration-fixture.mjs';

const root=resolve(process.argv[2]), runtime=resolve(process.argv[3]), output=resolve(process.env.MC_INTENT_EVIDENCE_ROOT);
assert(!relative(root,output).startsWith('..') && relative(root,output)); mkdirSync(output,{recursive:true});
const policy=structuredClone(loadPolicy(root));
policy.deployment.dsh_home_relative_path=relative(root,join(output,'isolated-dsh-home')).replaceAll('\\','/');
const goal={skill:'gather',item_id:'minecraft:oak_log',count:4};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
const report={classification:'ACTUAL_PINNED_DSH_AND_HUMANITY_WITH_SCRIPTED_LOOPBACK_PROVIDER_AND_MC_PROTOCOL_FIXTURE',
 result:'FAIL',cases:[],requests:[],network_requests:[],real_model:false,real_minecraft:false,official_client:false,public_broadcast:false};
let host, current='initial', privateGate, mode='plan', callbacks=0;
const sockets=new Set(); let httpActive=0;
const server=createServer(async(req,res)=>{
  httpActive++;res.once('close',()=>httpActive--);
  try{
    assert.equal(req.url,'/v1/chat/completions');
    const chunks=[];for await(const chunk of req)chunks.push(chunk);const body=JSON.parse(Buffer.concat(chunks));
    const names=body.tools?.map(tool=>tool.function.name)||[], toolReplies=body.messages.filter(message=>message.role==='tool').length;
    report.requests.push({case:current,tool_names:names,tool_replies:toolReplies,
      late_callback_result_seen:body.messages.some(message=>message.role==='tool' && JSON.stringify(message.content).includes('ignored_late_result')),
      tool_timeout_reported:body.messages.some(message=>message.role==='tool' && JSON.stringify(message.content).includes('tool call timed out after 10000ms'))});
    if(privateGate && names.length===0){privateGate.entered.resolve();await privateGate.release.promise;}
    if(res.destroyed)return;
    let call;
    if(names.includes('game_start_task') && toolReplies===0)call=['game_start_task',{goal}];
    else if(names.includes('stream_audience_intent_result'))call=toolReplies===0?['game_check_action',{goal}]:
      toolReplies===1?['stream_audience_intent_result',{kind:'goal',goal,question:null}]:undefined;
    else if(mode==='sdk-timeout' && names.includes('game_get_state') && toolReplies===0)call=['game_get_state',{}];
    else if(mode==='narration-cancel' && names.includes('game_check_action') && toolReplies===0)call=['game_check_action',{goal}];
    const delta=call?{role:'assistant',tool_calls:[{index:0,id:'call-'+report.requests.length,type:'function',function:{
      name:call[0],arguments:JSON.stringify({data:JSON.stringify(call[1])})}}]}:{role:'assistant',content:'我会根据当前游戏情况继续回应。'};
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    for(const choice of [{delta,finish_reason:null},{delta:{},finish_reason:call?'tool_calls':'stop'}])
      res.write('data: '+JSON.stringify({id:'local-native-'+report.requests.length,object:'chat.completion.chunk',model:'local-scripted-fixture',choices:[{index:0,...choice}]})+'\n\n');
    res.end('data: [DONE]\n\n');
  }catch(error){report.server_error=String(error.stack||error);res.destroy(error);}
});
server.on('connection',socket=>{sockets.add(socket);socket.once('close',()=>sockets.delete(socket));});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const snapshot={revision:'native-local-fixture',model:'local-scripted-fixture',protocol:'chat_completions',
 baseUrl:'http://127.0.0.1:'+server.address().port+'/v1',systemPrompt:'',getApiKey:()=> 'local-unused-native-fixture'};
const originalFetch=globalThis.fetch;
globalThis.fetch=(input,options)=>{
 const url=new URL(typeof input==='string'||input instanceof URL?input:input.url);
 assert.equal(url.hostname,'127.0.0.1');assert.equal(url.protocol,'http:');
 report.network_requests.push({case:current,path:url.pathname,kind:url.port===String(server.address().port)?'model':'game-fixture'});
 return originalFetch(input,options);
};
const next=(game,type,predicate=()=>true)=>until(()=>game.messages.find(frame=>frame.type===type&&predicate(frame)),15000);
function speech(id,signal){return host.generate({sessionId:id+'-'+randomUUID(),purpose:'speech',snapshot,input:'回应观众',context:'{}',signal,tools:async()=>({})});}
function attach(f){f.bridge.host=host;f.bridge.channel={snapshot:()=>snapshot};f.bridge.health=()=>({persona_injection_ready:true});
 f.manager.config.planner.enabled=true;f.manager.config.planner.min_interval_ms=1000;}
function allowed(f,game,query){game.send('query_result',{...f.manager.operation(query.payload.operation_id),state:'succeeded',
 result:{world_session_id:game.observation.world_session_id,kind:'check_action',allowed:true}});}
async function fixture(action){const f=await gameFixture({fakeClock:true});let pending;
 try{const game=await f.connect();await game.auto();attach(f);return await action(f,game,value=>pending=value);}
 finally{f.manager.planner.cancel();f.manager.intents.running?.controller.abort();await pending;await f.close();}}
async function check(name,action){current=name;const started=Date.now();console.log(JSON.stringify({event:'native.case_start',id:name}));
 await action();assert.equal(host.active.size,0);assert.equal(host.foregroundQueued||0,0);
 assert.equal(report.server_error,undefined);report.cases.push({id:name,result:'PASS',elapsed_ms:Date.now()-started});
 console.log(JSON.stringify({event:'native.case_pass',id:name}));}
try{
 host=await new DshHost(root,runtime,policy).start();const persona=initialPersona(root);await host.publishCharacter(persona.document,persona.version);
 report.composition=JSON.parse(readFileSync(join(root,policy.deployment.dsh_home_relative_path,'composition-receipt.json'),'utf8'));
 assert(report.composition.rows.includes('timeout-policy'));assert.equal(report.composition.tool_timeout_ms,10000);
 report.versions={node:process.version,dsh:JSON.parse(readFileSync(join(runtime,'node_modules/@deepseek-ai/dsh-tools/package.json'),'utf8')).version,
 humanity:JSON.parse(readFileSync(join(runtime,'node_modules/deepseek-harness-humanity/package.json'),'utf8')).version};
 await check('N01-normal-plan-accepted-not-completed',()=>fixture(async(f,game,remember)=>{
   const pending=f.manager.planner.tick();remember(pending);const query=await next(game,'query');allowed(f,game,query);await pending;await next(game,'task_start');
   const task=f.manager.tasks.active();assert.equal(task.state,'accepted');assert.equal(task.effect_status,'unknown');assert.deepEqual(task.evidence,[]);
   assert.equal(game.messages.filter(frame=>frame.type==='task_start').length,1);
 }));
 await check('N02-preaborted-speech-preserves-native-plan',()=>fixture(async(f,game,remember)=>{
   const pending=f.manager.planner.tick();remember(pending);const query=await next(game,'query'), original=host.gamePlanAbort;
   const cancelled=new AbortController();cancelled.abort();const before=report.requests.length;
   await assert.rejects(speech('preaborted',cancelled.signal),error=>error.code==='MODEL_CANCELLED');
   assert.equal(original.signal.aborted,false);assert.equal(report.requests.length,before);
   assert.equal(f.manager.operation(query.payload.operation_id).state,'pending');allowed(f,game,query);await pending;await next(game,'task_start');
   assert.equal(f.manager.tasks.active().state,'accepted');
 }));
 await check('N03-native-preemption-cleans-query-and-replans',()=>fixture(async(f,game,remember)=>{
   const pending=f.manager.planner.tick();remember(pending);const query=await next(game,'query');
   await speech('interrupt-native-plan');await pending;
   assert.equal(f.manager.operation(query.payload.operation_id).error,'GAME_QUERY_CANCELLED');assert.equal(f.manager.pending.size,0);
   allowed(f,game,query);assert.equal(f.manager.tasks.active(),null);
   f.advance(f.manager.config.planner.min_interval_ms);
   const resumed=f.manager.planner.tick();remember(resumed);const fresh=await next(game,'query',frame=>frame.payload.operation_id!==query.payload.operation_id);
   allowed(f,game,fresh);await resumed;await next(game,'task_start');assert.equal(f.manager.tasks.active().state,'accepted');
   assert.equal(game.messages.filter(frame=>frame.type==='task_start').length,1);
 }));
 await check('N04-native-intent-preemption-purges-session',async()=>{
   const f=await gameFixture({fakeClock:true});let pending;
   try{const game=await f.connect();attach(f);f.manager.configure({expected_revision:0,patch:{audience_intents:{enabled:true}}});
     f.platformEvent({text:'再采四个橡木原木'});const intent=f.manager.intents.rows().at(-1);pending=f.manager.intents.tick();const query=await next(game,'query');
     await speech('interrupt-native-intent');await pending;allowed(f,game,query);
     assert.equal(f.manager.intents.get(intent.audience_intent_id).state,'cancelled');assert.equal(f.manager.suggestions.pending().length,0);
     assert.equal(f.manager.tasks.active(),null);assert.equal(f.manager.pending.size,0);
     assert(!(await host.ctx.sessionPersistence.list()).some(row=>row.header.id.startsWith('mc-intent-')));
   }finally{f.manager.intents.running?.controller.abort();await pending;await f.close();}
 });
 await check('N05-native-narration-cancel-does-not-submit-media',async()=>{
   mode='narration-cancel';let close;const f=await narrationFixture({after:fn=>close=fn});let pending;
   try{attach(f);const{key,item}=await f.comment('可以再采四个橡木原木吗？');pending=f.run();const query=await next(f.game,'query');
     const request=f.state.active();f.state.cancel(request.request_id,'native-fixture-cancel');await pending;allowed(f,f.game,query);
     assert.equal(f.manager.operation(query.payload.operation_id).error,'GAME_QUERY_CANCELLED');assert.equal(f.manager.pending.size,0);
     assert.equal(f.media.length,0);assert.equal(f.room.store.message(key).answered,false);
     assert.equal(f.state.request(request.request_id).status,'CANCELLED');assert(['failed','cancelled'].includes(f.manager.narration.get(item.narration_id).state));
     assert.equal(f.bridge.controllers.size,0);
   }finally{if(f.state.active())f.state.cancel(f.state.active().request_id);await pending;await close();mode='plan';}
 });
 await check('N06-queued-cancellation-does-not-bypass-active-native-agent',async()=>{
   privateGate={entered:deferred(),release:deferred()};const controller=new AbortController();let one,two,three;
   try{
     one=host.generate({sessionId:'private-hold-'+randomUUID(),purpose:'operator_private',snapshot,input:'隔离队列检查',tools:async()=>({})});
     await privateGate.entered.promise;
     two=assert.rejects(speech('cancel-queued',controller.signal),error=>error.code==='MODEL_CANCELLED');controller.abort();await two;
     const count=report.requests.length;three=speech('after-cancelled-queue');
     await new Promise(r=>setTimeout(r,40));assert.equal(report.requests.length,count);assert.equal(host.active.size,1);
     privateGate.release.resolve();await Promise.all([one,three]);
   }finally{privateGate.release.resolve();await Promise.allSettled([one,two,three]);privateGate=null;}
 });
 await check('N07-real-sdk-tool-deadline-aborts-application-signal',async()=>{
   mode='sdk-timeout';let received, reason, failure, timedOut=false;const began=Date.now(), fallback=AbortSignal.timeout(16000);
   try{await host.generate({sessionId:'sdk-deadline-'+randomUUID(),purpose:'game_plan',snapshot,input:'查询当前状态',signal:fallback,
     toolCatalogue:[{name:'game_get_state',description:'read local state'}],tools:async(name,args,execution)=>{
       callbacks++;assert.equal(name,'game_get_state');received=execution.signal;
       await new Promise(resolve=>{if(received.aborted)resolve();else received.addEventListener('abort',resolve,{once:true});});
       timedOut=true;reason=received.reason?.name||null;return{ignored_late_result:true};
     }});}catch(error){failure=error.code||error.message;}
   assert.equal(callbacks,1);assert.equal(received.aborted,true);assert.equal(timedOut,true);assert.equal(fallback.aborted,false);
   assert(report.requests.filter(request=>request.case===current).every(request=>!request.late_callback_result_seen));
   assert(report.requests.some(request=>request.case===current&&request.tool_timeout_reported));
   report.sdk_deadline={aborted:true,reason,elapsed_ms:Date.now()-began,host_outcome:failure||'completed',callback_result_not_accepted:true};mode='plan';
 });
 report.result='PASS';report.all_tests_have_native_host=true;
}catch(error){report.error=String(error.stack||error);throw error;}
finally{
 privateGate?.release.resolve();try{await host?.close();}finally{
   globalThis.fetch=originalFetch;
   server.closeAllConnections();for(const socket of sockets)socket.destroy();await new Promise(r=>server.close(r));
   await until(()=>sockets.size===0,2000);
   report.native_host_closed=!host?.ready;report.remaining_http_sockets=sockets.size;report.http_active_at_close=httpActive;
   report.recorded_at=new Date().toISOString();writeFileSync(join(output,'native-dsh-model-probe.json'),JSON.stringify(report,null,2)+'\n');
   console.log(JSON.stringify({result:report.result,cases:report.cases.length,requests:report.requests.length,native_host_closed:report.native_host_closed,
     evidence:join(output,'native-dsh-model-probe.json')}));
 }
}
