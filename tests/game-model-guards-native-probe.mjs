// Native pinned DSH/Humanity; provider replies are scripted loopback HTTP.
// Independent state and SQLite fixtures; no production channel, model or game.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { DshHost, MAX_MODEL_REPLAY_CHARACTERS } from '../backend/dsh-bridge/host.mjs';
import { loadPolicy } from '../backend/dsh-bridge/policy.mjs';
import { initialPersona } from '../backend/dsh-bridge/persona.mjs';
import { StreamBridge } from '../backend/dsh-bridge/server.mjs';
import { MaintenanceScheduler } from '../backend/memory/scheduler.mjs';
import { narrationFixture } from './game-narration-fixture.mjs';
import { gameFixture, until } from './game-fixture.mjs';

const root=resolve(process.argv[2]),runtime=resolve(process.argv[3]),output=resolve(process.env.MC_INTENT_EVIDENCE_ROOT);
assert(relative(root,output) && !relative(root,output).startsWith('..'));mkdirSync(output,{recursive:true});
const policy=structuredClone(loadPolicy(root));
policy.deployment.dsh_home_relative_path=relative(root,join(output,'isolated-dsh-home')).replaceAll('\\','/');
const report={result:'FAIL',classification:'ACTUAL_DSH_HUMANITY_LOCAL_GUARDS_AND_RECOVERY_WITH_SCRIPTED_PROVIDER',
 cases:[],requests:[],network:[],real_model:false,real_minecraft:false,official_client:false,public_broadcast:false};
let host,current='boot',mode='text';const sockets=new Set();let httpActive=0;
const secret='local-private-fixture-marker';
const server=createServer(async(req,res)=>{
 httpActive++;res.once('close',()=>httpActive--);
 try{
  assert(['/v1/chat/completions','/v1/responses'].includes(req.url));const chunks=[];for await(const chunk of req)chunks.push(chunk);
  const body=JSON.parse(Buffer.concat(chunks)),names=body.tools?.map(tool=>tool.function?.name||tool.name)||[];
  if(current==='G07-rate-limited-planner-recovers-with-one-new-task' && mode==='plan') {
   for(const name of ['game_check_action','game_start_task']) {
    const schema=body.tools.find(tool=>tool.function.name===name)?.function.parameters;
    assert.equal(schema.properties.data.type,'string');
    assert.match(schema.properties.data.description,/goal\.skill/);
    assert.match(schema.properties.data.description,/"goal":\{"skill"/);
   }
  }
  report.requests.push({case:current,mode,path:req.url,tool_names:names});
  if(req.url==='/v1/responses') {
   assert(['signed-plan','oversized-replay'].includes(mode));
   const prior=body.input.filter(item=>item.type==='function_call_output').length;
   const replays=body.input.filter(item=>item.type==='reasoning');
   const signature='opaque-local-fixture-'.repeat(mode==='oversized-replay'?4000:450).slice(0,mode==='oversized-replay'?MAX_MODEL_REPLAY_CHARACTERS+1:9000);
   assert.equal(body.max_output_tokens,512);
   for(const item of replays)assert.equal(item.encrypted_content,signature,'native adapter must receive unchanged encrypted replay');
   report.requests.at(-1).replayed_signatures=replays.length;
   const name=['game_get_state','game_check_action','game_start_task'][prior];assert(name);
   const args=name==='game_get_state'?{}:{goal:{skill:'gather',item_id:'minecraft:cobblestone',count:1}};
   const reasoning={type:'reasoning',id:'rs-native-'+prior,summary:[],encrypted_content:signature};
   const call={type:'function_call',id:'fc-native-'+prior,call_id:'call-native-'+prior,name,arguments:JSON.stringify({data:JSON.stringify(args)}),status:'completed'};
   res.writeHead(200,{'Content-Type':'text/event-stream'});
   const emit=value=>res.write('data: '+JSON.stringify(value)+'\n\n');
   emit({type:'response.created',response:{id:'resp-native-'+prior,status:'in_progress'}});
   emit({type:'response.output_item.added',output_index:0,item:{...reasoning,encrypted_content:null}});
   emit({type:'response.output_item.done',output_index:0,item:reasoning});
   emit({type:'response.output_item.added',output_index:1,item:{...call,arguments:'',status:'in_progress'}});
   emit({type:'response.function_call_arguments.delta',output_index:1,item_id:call.id,delta:call.arguments});
   emit({type:'response.function_call_arguments.done',output_index:1,item_id:call.id,arguments:call.arguments});
   emit({type:'response.output_item.done',output_index:1,item:call});
   emit({type:'response.completed',response:{id:'resp-native-'+prior,status:'completed',output:[reasoning,call],usage:{input_tokens:40,output_tokens:400,total_tokens:440}}});
   res.end();return;
  }
  if(['401','429'].includes(mode)){res.writeHead(Number(mode),{'Content-Type':'application/json'});res.end(JSON.stringify({error:{message:secret,type:'local_fixture'}}));return;}
  const call=mode==='loop'?['game_get_state',{}]:mode==='plan' && !body.messages.some(message=>message.role==='tool')?
   ['game_start_task',{goal:{skill:'gather',item_id:'minecraft:oak_log',count:4}}]:null;
  const delta=call?{role:'assistant',tool_calls:[{index:0,id:'call-'+report.requests.length,type:'function',function:{name:call[0],arguments:JSON.stringify({data:JSON.stringify(call[1])})}}]}:
   {role:'assistant',content:'我会继续根据游戏情况回应大家。'};
  res.writeHead(200,{'Content-Type':'text/event-stream'});
  for(const choice of [{delta,finish_reason:null},{delta:{},finish_reason:call?'tool_calls':'stop'}])res.write('data: '+JSON.stringify({id:'guard-fixture',object:'chat.completion.chunk',model:body.model,choices:[{index:0,...choice}],usage:{prompt_tokens:40,completion_tokens:8,total_tokens:48}})+'\n\n');
  res.end('data: [DONE]\n\n');
 }catch(error){report.server_error=String(error.stack||error);res.destroy(error);}
});
server.on('connection',socket=>{sockets.add(socket);socket.once('close',()=>sockets.delete(socket));});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const snapshot={revision:'native-guard-fixture',model:'scripted-fixture',protocol:'chat_completions',baseUrl:'http://127.0.0.1:'+server.address().port+'/v1',systemPrompt:'',getApiKey:()=>secret};
const originalFetch=globalThis.fetch;
globalThis.fetch=(input,options)=>{const url=new URL(typeof input==='string'||input instanceof URL?input:input.url);
 assert.equal(url.hostname,'127.0.0.1');assert.equal(url.protocol,'http:');report.network.push({case:current,path:url.pathname});return originalFetch(input,options);};
const generate=(extra={})=>host.generate({sessionId:'guard-'+randomUUID(),purpose:'operator_private',snapshot,input:'隔离检查',tools:async()=>({}),...extra});
async function check(id,action){current=id;mode='text';const began=Date.now(),fallback=AbortSignal.timeout(8000);
 console.log(JSON.stringify({event:'guard.case_start',id}));await action(fallback);
 assert.equal(fallback.aborted,false,'outer observation deadline cannot satisfy a guard');assert.equal(host.active.size,0);assert.equal(host.foregroundQueued||0,0);
 assert.equal(report.server_error,undefined);report.cases.push({id,result:'PASS',elapsed_ms:Date.now()-began,fallback_deadline_used:false});console.log(JSON.stringify({event:'guard.case_pass',id}));}
async function withLedger(action){let close;const f=await narrationFixture({after:fn=>close=fn});
 try{f.bridge.scheduler=new MaintenanceScheduler(f.db,f.state,f.bridge.memory,f.bridge.policy);const onCall=StreamBridge.prototype.onCall.call(f.bridge,{});await action(f,onCall);}
 finally{await close();}}
try{
 host=await new DshHost(root,runtime,policy).start();const persona=initialPersona(root);await host.publishCharacter(persona.document,persona.version);
 report.composition=JSON.parse(readFileSync(join(root,policy.deployment.dsh_home_relative_path,'composition-receipt.json'),'utf8'));
 report.versions={node:process.version,dsh:JSON.parse(readFileSync(join(runtime,'node_modules/@deepseek-ai/dsh-tools/package.json'),'utf8')).version,
  humanity:JSON.parse(readFileSync(join(runtime,'node_modules/deepseek-harness-humanity/package.json'),'utf8')).version};
 await check('G01-context-budget-before-http-and-queue-recovery',async signal=>{
  const before=report.requests.length;await assert.rejects(generate({input:'本地上下文'.repeat(5000),signal}),error=>error.code==='STREAM_CONTEXT_BUDGET');
  assert.equal(report.requests.length,before);assert((await generate({signal})).text);assert.equal(report.requests.length-before,1);
 });
 await check('G02-reservation-denial-before-http-and-queue-recovery',async signal=>{
  const before=report.requests.length,phases=[];await assert.rejects(generate({signal,onCall:call=>{phases.push(call.phase);throw Object.assign(new Error('MODEL_DAILY_BUDGET'),{code:'MODEL_DAILY_BUDGET',status:409});}}),error=>error.code==='MODEL_DAILY_BUDGET');
  assert.deepEqual(phases,['reserve']);assert.equal(report.requests.length,before);assert((await generate({signal})).text);
 });
 await check('G03-send-ledger-failure-is-failed-before-send',signal=>withLedger(async(f,onCall)=>{
  const before=report.requests.length,phases=[];await assert.rejects(generate({signal,onCall:call=>{
   phases.push({phase:call.phase,sent:call.sent});if(call.phase==='sent')throw Error(secret);return onCall(call);
  }}),error=>error.code==='DSH_GENERATION_FAILED' && error.message==='DSH_GENERATION_FAILED');
  assert.equal(report.requests.length,before);const rows=f.db.all('SELECT status FROM model_attempts');assert.equal(rows.length,1);
  report.before_send_ledger={status:rows[0].status,phases};assert.equal(rows[0].status,'FAILED_BEFORE_SEND');
  assert((await generate({signal,onCall})).text);assert.equal(f.db.all("SELECT status FROM model_attempts WHERE status='SETTLED'").length,1);
 }));
 await check('G04-abort-in-send-hook-never-enters-provider',signal=>withLedger(async(f,onCall)=>{
  const controller=new AbortController(),before=report.requests.length;
  await assert.rejects(generate({signal:AbortSignal.any([controller.signal,signal]),onCall:call=>{const value=onCall(call);if(call.phase==='sent')controller.abort();return value;}}),error=>error.code==='MODEL_CANCELLED');
  assert.equal(report.requests.length,before);assert.equal(f.db.get('SELECT status FROM model_attempts').status,'FAILED_BEFORE_SEND');
  assert((await generate({signal,onCall})).text);
 }));
 await check('G05-tool-loop-capped-at-six-http-attempts',async signal=>{
  mode='loop';let callbacks=0;const before=report.requests.length,probes=[];
  await assert.rejects(generate({purpose:'game_plan',signal,onProbe:probe=>probes.push(probe),toolCatalogue:[{name:'game_get_state',description:'read'}],tools:async()=>{callbacks++;return{state:'local_fixture'};}}),error=>error.code==='STREAM_TOOL_ROUND_LIMIT');
  assert.equal(report.requests.length-before,6);assert.equal(callbacks,6);mode='text';assert((await generate({signal})).text);
  assert.deepEqual(probes.map(probe=>probe.completed_tool_calls.game_get_state||0),[0,1,2,3,4,5]);
  assert(probes.every(probe=>Object.keys(probe.completed_tool_calls).every(name=>name==='game_get_state')));
 });
 await check('G06-failed-narration-never-submits-media-and-next-comment-recovers',async signal=>{
  let close;const f=await narrationFixture({after:fn=>close=fn});
  try{f.bridge.host=host;f.bridge.channel={snapshot:()=>snapshot};const first=await f.comment();mode='401';await f.run();
   assert.equal(signal.aborted,false);assert.equal(f.media.length,0);assert.equal(f.room.store.message(first.key).answered,false);assert.equal(f.bridge.controllers.size,0);
   assert.equal(report.requests.filter(row=>row.case===current).length,1);mode='text';const second=await f.comment('继续聊聊游戏吧');await f.run();
   assert.equal(f.media.length,1);assert.equal(f.room.store.message(second.key).answered,false);assert.equal(f.complete().result.accepted,true);
   await new Promise(resolve=>queueMicrotask(resolve));assert.equal(f.room.store.message(second.key).answered,true);assert.equal(f.room.store.message(first.key).answered,false);
  }finally{if(f.state.active())f.state.cancel(f.state.active().request_id);await close();}
 });
 await check('G07-rate-limited-planner-recovers-with-one-new-task',async signal=>{
  const f=await gameFixture({fakeClock:true});let pending;
  try{const game=await f.connect();await game.auto();f.bridge.host=host;f.bridge.channel={snapshot:()=>snapshot};f.bridge.health=()=>({persona_injection_ready:true});
   f.manager.config.planner.enabled=true;f.manager.config.planner.min_interval_ms=1000;mode='429';await f.manager.planner.tick();assert.equal(f.manager.tasks.active(),null);
   assert.equal(report.requests.filter(row=>row.case===current).length,1);mode='plan';f.advance(1000);pending=f.manager.planner.tick();
   const query=await until(()=>game.messages.find(frame=>frame.type==='query'),6000);
   game.send('query_result',{...f.manager.operation(query.payload.operation_id),state:'succeeded',result:{world_session_id:game.observation.world_session_id,kind:'check_action',allowed:true}});
   await pending;assert.equal(signal.aborted,false);assert.equal(f.manager.tasks.active().state,'accepted');assert.equal(f.manager.tasks.active().effect_status,'unknown');
   // One denied attempt plus one model-selected task; acceptance must end
   // this non-spoken planning turn before another HTTP/model budget charge.
   assert.equal(report.requests.filter(row=>row.case===current).length,2);
   await until(()=>game.messages.some(frame=>frame.type==='task_start'),1000);
   assert.equal(game.messages.filter(frame=>frame.type==='task_start').length,1);
  }finally{f.manager.planner.cancel();await pending;await f.close();}
 });
 await check('G08-native-responses-signed-replay-read-check-and-one-task',async signal=>{
  mode='signed-plan';const before=report.requests.length,probes=[],calls=[];
  const result=await generate({purpose:'game_plan',snapshot:{...snapshot,protocol:'responses'},maxTokens:512,signal,
   onProbe:probe=>probes.push(probe),toolCatalogue:['game_get_state','game_check_action','game_start_task'].map(name=>({name,description:'isolated fixture'})),
   tools:async(name,args)=>{calls.push(name);return name==='game_start_task'?{task_id:'task-native-signed-fixture',state:'accepted',effect_status:'unknown'}:
    name==='game_check_action'?{state:'succeeded',result:{allowed:true,unknown_fields:['future_drops']}}:{freshness:'fresh',seq:1,mode:'AUTO'};}});
  assert.equal(result.steps,3);assert.deepEqual(calls,['game_get_state','game_check_action','game_start_task']);
  assert.equal(report.requests.length-before,3);assert.deepEqual(report.requests.slice(before).map(r=>r.replayed_signatures),[0,1,2]);
  assert.equal(probes[0].replay_transport_characters,0);
  assert(probes[1].replay_transport_characters>=9000 && probes[1].replay_transport_characters<9300,
   'the pinned adapter may wrap encrypted content with its bounded replay envelope');
  assert.equal(probes[2].replay_transport_characters,2*probes[1].replay_transport_characters);
  assert.deepEqual(probes.map(p=>p.replay_token_reserve),[0,512,1024]);
  assert(probes.every(p=>p.budget_admitted && p.estimated_input_tokens<=policy.conversation.context_max_estimated_tokens));
 });
 await check('G09-native-responses-oversized-replay-denied-before-next-http',async signal=>{
  mode='oversized-replay';const before=report.requests.length,probes=[];let callbacks=0;
  await assert.rejects(generate({purpose:'game_plan',snapshot:{...snapshot,protocol:'responses'},maxTokens:512,signal,
   onProbe:probe=>probes.push(probe),toolCatalogue:[{name:'game_get_state',description:'isolated fixture'}],
   tools:async()=>{callbacks++;return{freshness:'fresh'};}}),error=>error.code==='STREAM_CONTEXT_BUDGET');
  assert.equal(callbacks,1);assert.equal(report.requests.length-before,1);
  assert.equal(probes.at(-1).replay_transport_within_limit,false);assert.equal(probes.at(-1).budget_admitted,false);
  mode='text';assert((await generate({signal})).text);assert.equal(report.requests.length-before,2);
 });
 await check('G10-bounded-mc-context-retains-tool-headroom',async signal=>{
  const before=report.requests.length,probes=[];
  const result=await generate({signal,context:JSON.stringify({data_only:true,mc_fixture:'中文事实'.repeat(3000)}),
   onProbe:probe=>probes.push(probe)});
  assert(result.text);assert.equal(report.requests.length-before,1);assert.equal(probes.length,1);
  assert(probes[0].estimated_input_tokens>6000);
  assert(probes[0].estimated_input_tokens<=policy.conversation.context_max_estimated_tokens);
  assert.equal(probes[0].budget_admitted,true);
 });
 report.result='PASS';
}catch(error){report.error=String(error.stack||error);throw error;}
finally{try{await host?.close();}finally{globalThis.fetch=originalFetch;server.closeAllConnections();for(const socket of sockets)socket.destroy();await new Promise(r=>server.close(r));
 await until(()=>sockets.size===0,2000);report.native_host_closed=!host?.ready;report.remaining_http_sockets=sockets.size;report.http_active_at_close=httpActive;
 report.recorded_at=new Date().toISOString();writeFileSync(join(output,'native-dsh-guard-probe.json'),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify({result:report.result,cases:report.cases.length,requests:report.requests.length}));}}
