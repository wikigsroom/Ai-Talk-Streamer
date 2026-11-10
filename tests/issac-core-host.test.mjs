import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtempSync,mkdirSync,rmSync,readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {DshHost} from '../backend/dsh-bridge/host.mjs';
import {loadPolicy} from '../backend/dsh-bridge/policy.mjs';
import {initialPersona} from '../backend/dsh-bridge/persona.mjs';
import {NaimeiGameCore,ISAAC_CORE_TOOLS} from '../backend/dsh-bridge/isaac-core.mjs';
import {completePrompt} from '../integration/isaac-agent/dsh-host/isaac-plugin/stream-policy.mjs';

test('game reasoning setting is admitted only for the frozen Isaac scope; inherited defaults remain independent',()=>{
  const root=process.cwd(),current=loadPolicy(root,'configs/issac/bridge-policy.json');
  assert.equal(current.conversation.game_reasoning_effort,'low');
  assert.equal(loadPolicy(root).conversation.game_reasoning_effort,undefined);
  assert.equal(loadPolicy(root,'configs/naimei/bridge-policy.json').conversation.game_reasoning_effort,undefined);
  mkdirSync(join(root,'state'),{recursive:true});const folder=mkdtempSync(join(root,'state/issac-policy-test-'));
  const path=join(folder,'policy.json');
  try{
    for(const mutate of [p=>{p.conversation.game_reasoning_effort='high';},p=>{p.conversation.game_reasoning_effort='off';},p=>{p.deployment.state_relative_path='state/naimei/stream';}]){
      const policy=structuredClone(current);mutate(policy);writeFileSync(path,JSON.stringify(policy));
      assert.throws(()=>loadPolicy(root,path),/CONFIG_GAME_REASONING_SCOPE/);
    }
    const invalid=structuredClone(current);invalid.conversation.game_reasoning_effort=null;writeFileSync(path,JSON.stringify(invalid));
    assert.throws(()=>loadPolicy(root,path),/CONFIG_TYPE:policy.conversation.game_reasoning_effort/);
  }finally{rmSync(folder,{recursive:true,force:true});}
});

// Controlled HTTP responses exercise the installed DSH loop, not a production
// channel. In particular its concludeTurn must retain the successful tool result.
for(const choice of [{op:'pickup',status:'accepted'},{op:'wait',status:'succeeded',effect:'wait'},{op:'pickup',status:'accepted',wiki:true},
  {op:'pickup',status:'accepted',prose:true},{op:'pickup',status:'accepted',prose:true,expired:true},
  {op:'pickup',status:'accepted',prose:true,alwaysProse:true},
  {op:'pickup',status:'accepted',assessmentRepair:true},{op:'pickup',status:'accepted',assessmentRepair:true,largeReplay:true},
  {op:'pickup',status:'accepted',previousContextLimit:true},{op:'pickup',status:'accepted',oversizedContext:true}]){
test('real DSH Responses concludes '+choice.op+(choice.wiki?' after current-context wiki':'')+(choice.prose?' after prose'+(choice.expired?' with expired decision':choice.alwaysProse?' with bounded non-completion':''):'')+(choice.assessmentRepair?' after repairing an oversized assessment with opaque replay':choice.oversizedContext?' rejects oversized visible context':'')+(choice.largeReplay?' over the former byte cap':choice.previousContextLimit?' over the former token cap':'')+' with low effort and keeps all wiki text',async()=>{
  const root=process.cwd(),policy=structuredClone(loadPolicy(root,'configs/issac/bridge-policy.json'));
  mkdirSync(join(root,'state'),{recursive:true});
  const folder=mkdtempSync(join(root,'state/issac-core-host-test-'));
  policy.deployment.dsh_home_relative_path=folder;
  const plan={plan_id:'controlled-plan',decision_id:'decision-A',context_id:'room-A',offer_id:'heart-A',budget:{},reason:'补血',commentary:'血量还没满，这颗红心我先拿上。'};
  if(choice.assessmentRepair)plan.assessment={growth:'当前没有核心道具，沿开放门继续。',key_recovery:'没有钥匙或已知可回收钥匙。'};
  let requests=0,received;const payloads=[];
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);
    received=JSON.parse(Buffer.concat(chunks));requests++;payloads.push(received);
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    const emit=value=>res.write('data: '+JSON.stringify(value)+'\n\n');
    if(choice.prose&&(requests===1||choice.alwaysProse)){
      const part={type:'output_text',text:'这颗红心我想先看看。',annotations:[]};
      const item={id:'msg-prose-'+requests,type:'message',status:'completed',role:'assistant',content:[part]};
      emit({type:'response.created',response:{id:'resp-prose-'+requests,status:'in_progress'}});
      emit({type:'response.output_item.added',output_index:0,item:{...item,status:'in_progress',content:[]}});
      emit({type:'response.content_part.added',output_index:0,content_index:0,item_id:item.id,part:{...part,text:''}});
      emit({type:'response.output_text.delta',output_index:0,content_index:0,item_id:item.id,delta:part.text});
      emit({type:'response.output_text.done',output_index:0,content_index:0,item_id:item.id,text:part.text});
      emit({type:'response.content_part.done',output_index:0,content_index:0,item_id:item.id,part});
      emit({type:'response.output_item.done',output_index:0,item});
      emit({type:'response.completed',response:{id:'resp-prose-'+requests,status:'completed',output:[item],usage:{input_tokens:100,output_tokens:20,total_tokens:120}}});
      res.end();return;
    }
    const wiki=choice.wiki&&requests===1;
    const submitted=choice.assessmentRepair&&requests===1?{...plan,assessment:{...plan.assessment,growth:'评'.repeat(161)}}:plan;
    const item={type:'function_call',id:'fc-controlled-'+requests,call_id:'call-controlled-'+requests,
      name:wiki?'isaac_wiki_query':'isaac_submit_plan',
      arguments:JSON.stringify({data:JSON.stringify(wiki?{query:{operation:'item',query:'The Sad Onion',kind:'item'}}:submitted)}),status:'completed'};
    emit({type:'response.created',response:{id:'response-controlled',status:'in_progress'}});
    const replay=choice.assessmentRepair&&requests===1?{type:'reasoning',id:'rs-controlled',encrypted_content:'opaque-test-'.repeat(choice.largeReplay?60000:8000),summary:[{type:'summary_text',text:'Controlled replay placeholder'}]}:null;
    if(replay){
      emit({type:'response.output_item.added',output_index:0,item:{...replay,summary:[]}});
      emit({type:'response.reasoning_summary_part.added',output_index:0,summary_index:0,item_id:replay.id,part:{type:'summary_text',text:''}});
      emit({type:'response.reasoning_summary_text.delta',output_index:0,summary_index:0,item_id:replay.id,delta:replay.summary[0].text});
      emit({type:'response.output_item.done',output_index:0,item:replay});
    }
    const index=replay?1:0;
    emit({type:'response.output_item.added',output_index:index,item:{...item,arguments:'',status:'in_progress'}});
    emit({type:'response.function_call_arguments.delta',output_index:index,item_id:item.id,delta:item.arguments});
    emit({type:'response.function_call_arguments.done',output_index:index,item_id:item.id,arguments:item.arguments});
    emit({type:'response.output_item.done',output_index:index,item});
    emit({type:'response.completed',response:{id:'response-controlled',status:'completed',output:[...(replay?[replay]:[]),item],usage:{input_tokens:100,output_tokens:80,total_tokens:180}}});
    res.end();
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let host;
  try{
    host=await new DshHost(root,join(root,'tools/dsh'),policy).start();
    const persona=initialPersona(root,'naimei');await host.publishCharacter(persona.document,persona.version);
    const core=Object.create(NaimeiGameCore.prototype);core.augment=context=>context;
    Object.assign(core,{names:Object.keys(ISAAC_CORE_TOOLS),enabled:true,controlRevision:1,recent:[],record:()=>{},
      prompt:completePrompt(root,readFileSync(join(root,'configs/issac/core-persona-gameplay.md'),'utf8')),
      decision:async()=>({pending:!choice.expired,connected:true,id:'decision-A',context_id:'room-A',context:{inventory_revision:'inventory-A',...(choice.assessmentRepair?{required_assessment:{}}:{})},remaining_ms:choice.expired?0:10000,offers:[{id:'heart-A',op:choice.op}]}),
      api:async(_port,path,body)=>{
        if(path==='/wiki'){
          assert.deepEqual(body.context,{decision_id:'decision-A',context_id:'room-A',inventory_revision:'inventory-A'});
          return {receipt_sha256:'controlled-wiki',known:true,requested_edition:'rep',result:{edition:'rep',name:'The Sad Onion',effect:'Tears up',source:'controlled-local-wiki'}};
        }
        assert.equal(body.commentary,undefined);return {plan_id:body.plan_id,
        decision_id:body.decision_id,offer_id:body.offer_id,status:choice.status,...(choice.effect?{effect:choice.effect}:{})};}});
    host.gameplay=core;const turn={decision_id:'decision-A',context_id:'room-A',control_revision:1},probes=[];
    const generation=host.generate({sessionId:'controlled-native-plan',snapshot:{revision:'controlled',model:'controlled',protocol:'responses',
      baseUrl:'http://127.0.0.1:'+server.address().port+'/v1',systemPrompt:'',getApiKey:()=> 'controlled-key'},
      context:JSON.stringify({game_decision:{id:'decision-A',context_id:'room-A'},...(choice.oversizedContext||choice.previousContextLimit?{current_game:{unbounded:'x'.repeat(choice.oversizedContext?2000000:60000)}}:{})}),input:'提交当前选择与打算。',gameplayTurn:turn,
      tools:async()=>{throw Error('unexpected viewer tool');},onProbe:probe=>probes.push(probe),signal:AbortSignal.timeout(15000)});
    if(choice.expired){await assert.rejects(generation);assert.equal(requests,1);assert.equal(turn.submitted,undefined);return;}
    if(choice.oversizedContext){
      await assert.rejects(generation,error=>error.code==='STREAM_CONTEXT_BUDGET');assert.equal(requests,0);
      assert.equal(probes.length,1);assert.equal(probes[0].phase,'rejected_budget');
      assert.equal(probes[0].input_budget_estimated_tokens,989760);
      assert.equal(probes[0].budget_reason,'estimated_input_tokens');return;
    }
    const result=await generation;
    assert.equal(requests,choice.wiki||choice.prose||choice.assessmentRepair?2:1);assert.equal(result.steps,requests);
    if(choice.assessmentRepair){
      assert.ok(JSON.stringify(payloads[1]).includes('CORE_ASSESSMENT_MAX_160_CHARS'));
      assert.ok(JSON.stringify(payloads[1]).includes('opaque-test-'.repeat(8000)),'original replay remains intact');
      assert.ok(probes.at(-1).serialized_message_bytes>90000);
    }
    if(choice.previousContextLimit)assert.ok(probes[0].estimated_input_tokens>28000);
    if(choice.largeReplay)assert.ok(probes.at(-1).serialized_message_bytes>512*1024);
    assert.equal(result.choice_completion_followups,choice.prose?1:0);
    if(choice.alwaysProse){assert.equal(result.text,'这颗红心我想先看看。');assert.equal(turn.submitted,undefined);return;}
    assert.equal(result.text,plan.commentary);
    for(const payload of payloads){assert.equal(payload.reasoning.effort,'low');assert.equal(payload.max_output_tokens,2048);}
    for(const probe of probes){assert.equal(probe.game_reasoning_effort,'low');assert.ok(probe.elapsed_ms>=0);
      assert.equal(probe.context_window_tokens,1000000);assert.equal(probe.serialized_message_limit_bytes,32*1024*1024);
      assert.ok(['completed','iterator_closed'].includes(probe.phase));}
    assert.equal(result.final_reason.kind,'completed');assert.equal(turn.submitted.status,choice.status);
    assert.deepEqual([...probes[0].tools].sort(),core.names.toSorted());
    assert.ok(probes[0].has_issac_wiki);assert.ok(probes[0].has_persona);
    for(const payload of payloads){const sent=JSON.stringify(payload);
      for(const pin of core.prompt.receipt.skill_sources)assert.ok(sent.includes(pin.sha256));}
  }finally{await host?.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));rmSync(folder,{recursive:true,force:true});}
});
}

test('real DSH owns provider registrations through disposal and cancels queued turns without network calls', {timeout:20000}, async()=>{
  const root=process.cwd(),policy=structuredClone(loadPolicy(root,'configs/issac/bridge-policy.json'));
  mkdirSync(join(root,'state'),{recursive:true});
  const folder=mkdtempSync(join(root,'state/issac-concurrent-channel-test-'));
  policy.deployment.dsh_home_relative_path=folder;
  const seen=[];let startedC;
  const cStarted=new Promise(resolve=>{startedC=resolve;});
  const server=createServer(async(req,res)=>{
    for await(const chunk of req){}
    const id=req.url.split('/')[1];
    assert.equal(req.headers.authorization,'Bearer controlled-'+id);
    seen.push(id);if(id==='c')startedC();
    await new Promise(resolve=>setTimeout(resolve,250));
    if(res.destroyed)return;
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    const emit=v=>res.write('data: '+JSON.stringify(v)+'\n\n');
    const part={type:'output_text',text:'这间清完了，我接着走。',annotations:[]};
    const item={id:'msg-'+id,type:'message',status:'completed',role:'assistant',content:[part]};
    emit({type:'response.created',response:{id:'response-'+id,status:'in_progress'}});
    emit({type:'response.output_item.added',output_index:0,item:{...item,status:'in_progress',content:[]}});
    emit({type:'response.content_part.added',output_index:0,content_index:0,item_id:item.id,part:{...part,text:''}});
    emit({type:'response.output_text.delta',output_index:0,content_index:0,item_id:item.id,delta:part.text});
    emit({type:'response.output_text.done',output_index:0,content_index:0,item_id:item.id,text:part.text});
    emit({type:'response.content_part.done',output_index:0,content_index:0,item_id:item.id,part});
    emit({type:'response.output_item.done',output_index:0,item});
    emit({type:'response.completed',response:{id:'response-'+id,status:'completed',output:[item],usage:{input_tokens:1,output_tokens:10,total_tokens:11}}});
    res.end();
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let host;
  try{
    host=await new DshHost(root,join(root,'tools/dsh'),policy).start();
    const persona=initialPersona(root,'naimei');await host.publishCharacter(persona.document,persona.version);
    const generate=(id,signal=AbortSignal.timeout(10000))=>host.generate({sessionId:'controlled-channel-'+id,
      snapshot:{revision:'controlled-'+id,model:'controlled',protocol:'responses',
        baseUrl:'http://127.0.0.1:'+server.address().port+'/'+id+'/v1',systemPrompt:'',getApiKey:()=> 'controlled-'+id},
      input:'根据清房事实自然回应。',tools:async()=>{},signal});
    const first=await Promise.all([generate('a'),generate('b')]);
    assert.ok(first.every(r=>r.text==='这间清完了，我接着走。'));
    assert.equal(host.active.size,0);
    const abort=new AbortController(),cancelled=generate('c',abort.signal);
    // Observe the first rejection immediately so cancellation is never an
    // unhandled rejection while its successor is being created.
    const cancellation=cancelled.then(()=>assert.fail('cancelled turn completed'),e=>assert.equal(e.code,'MODEL_CANCELLED'));
    await cStarted;
    const queuedAbort=new AbortController(),queued=generate('never',queuedAbort.signal);
    const queuedCancellation=queued.then(()=>assert.fail('queued cancelled turn completed'),e=>assert.equal(e.code,'MODEL_CANCELLED'));
    queuedAbort.abort();abort.abort();
    const resumed=generate('d');
    await Promise.all([cancellation,queuedCancellation]);assert.equal((await resumed).text,'这间清完了，我接着走。');
    assert.deepEqual(seen.toSorted(),['a','b','c','d']);assert.equal(host.active.size,0);
  }finally{
    await host?.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
    rmSync(folder,{recursive:true,force:true});
  }
});

test('one real DSH agent retains three turns with durable compaction and fresh full game state', {timeout:30000}, async()=>{
  const root=process.cwd(),policy=structuredClone(loadPolicy(root,'configs/issac/bridge-policy.json'));
  const folder=mkdtempSync(join(root,'state/issac-continuous-test-'));policy.deployment.dsh_home_relative_path=folder;
  const payloads=[];
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);payloads.push(JSON.parse(Buffer.concat(chunks)));
    // The pinned low-effort request must never silently fall back to `none`.
    if(payloads.at(-1).reasoning?.effort==='none'){
      res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({error:{code:'unsupported_value',param:'reasoning.effort'}}));return;
    }
    res.writeHead(200,{'Content-Type':'text/event-stream'});const emit=v=>res.write('data: '+JSON.stringify(v)+'\n\n');
    const n=payloads.length,part={type:'output_text',text:['先补血。','钥匙收好了。','这首领冲得真快。'][(n-1)%3],annotations:[]};
    const item={id:'msg-continuous-'+n,type:'message',status:'completed',role:'assistant',content:[part]};
    emit({type:'response.created',response:{id:'response-continuous-'+n,status:'in_progress'}});
    emit({type:'response.output_item.added',output_index:0,item:{...item,status:'in_progress',content:[]}});
    emit({type:'response.content_part.added',output_index:0,content_index:0,item_id:item.id,part:{...part,text:''}});
    emit({type:'response.output_text.delta',output_index:0,content_index:0,item_id:item.id,delta:part.text});
    emit({type:'response.output_text.done',output_index:0,content_index:0,item_id:item.id,text:part.text});
    emit({type:'response.content_part.done',output_index:0,content_index:0,item_id:item.id,part});
    emit({type:'response.output_item.done',output_index:0,item});
    emit({type:'response.completed',response:{id:'response-continuous-'+n,status:'completed',output:[item],usage:{input_tokens:100,output_tokens:10,total_tokens:110}}});res.end();
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let host;
  try{
    host=await new DshHost(root,join(root,'tools/dsh'),policy).start();
    const persona=initialPersona(root,'naimei');await host.publishCharacter(persona.document,persona.version);
    const results=[];
    for(let i=0;i<3;i++)results.push(await host.generate({sessionId:'continuous-request-'+i,
      snapshot:{revision:'same-channel',model:'controlled',protocol:'responses',baseUrl:'http://127.0.0.1:'+server.address().port+'/v1',systemPrompt:'',getApiKey:()=> 'controlled-key'},
      input:'当前第'+i+'回合',context:JSON.stringify({partition_key:'public',current_game:{data:{room:{index:100+i},inventory:[{id:26}],resources:{keys:i}},connected:true,pending:false},speech_history:{last_spoken:i?'先补血。':null}}),
      tools:async()=>({}),signal:AbortSignal.timeout(15000)}));
    assert.equal(new Set(results.map(r=>r.continuous_session_id)).size,1);
    // DSH may also replace its own system header as fresh sections change.
    assert.ok(host.continuous.handle.agent.session.surface.replaceGeneration>=2);
    const native=host.continuous.handle.agent.session;
    assert.ok(native.deriveMessages().some(m=>JSON.stringify(m).includes('当前第2回合')));
    for(let i=0;i<3;i++){
      assert.equal(payloads[i].reasoning.effort,'low');
      assert.equal(payloads[i].max_output_tokens,2048);
      const text=JSON.stringify(payloads[i]);assert.ok(text.includes('当前第'+i+'回合'));
      assert.ok(text.includes('奶妹'));assert.ok(text.includes('resources'));assert.ok(text.includes('inventory'));
    }
    assert.ok(JSON.stringify(payloads[2]).includes('先补血。'));
    const channel={revision:'same-channel',model:'controlled',protocol:'responses',baseUrl:'http://127.0.0.1:'+server.address().port+'/v1',systemPrompt:'',getApiKey:()=> 'controlled-key'};
    const nativeId=host.continuous.id;
    const privateReply=await host.generate({sessionId:'isolated-private',snapshot:channel,input:'私人观众回合',
      context:JSON.stringify({partition_key:'viewer-isolated'}),tools:async()=>({}),signal:AbortSignal.timeout(15000)});
    assert.equal(privateReply.continuous_session_id,null);
    assert.equal(host.continuous.id,nativeId);
    assert.ok(!JSON.stringify(payloads[3]).includes('当前第2回合'));
    const resumed=await host.generate({sessionId:'public-resumed',snapshot:channel,input:'公开长会话继续',
      context:JSON.stringify({partition_key:'public'}),tools:async()=>({}),signal:AbortSignal.timeout(15000)});
    assert.equal(resumed.continuous_session_id,nativeId);
    assert.equal(payloads[4].reasoning.effort,'low');
    host.gameplay={augment:async()=>{throw Error('diagnostic must not require an attached game');}};
    const diagnostic=await host.generate({sessionId:'controlled-diagnostic',snapshot:channel,input:'仅测试渠道，不播出',
      diagnostic:true,tools:async()=>({}),signal:AbortSignal.timeout(15000)});
    assert.equal(diagnostic.continuous_session_id,null);
    assert.equal(host.continuous.id,nativeId);
    assert.equal(host.active.size,0);
  }finally{await host?.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));rmSync(folder,{recursive:true,force:true});}
});
