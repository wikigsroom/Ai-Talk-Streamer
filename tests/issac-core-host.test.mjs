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
  assert.equal(current.conversation.game_reasoning_effort,'off');
  assert.equal(loadPolicy(root).conversation.game_reasoning_effort,undefined);
  assert.equal(loadPolicy(root,'configs/naimei/bridge-policy.json').conversation.game_reasoning_effort,undefined);
  mkdirSync(join(root,'state'),{recursive:true});const folder=mkdtempSync(join(root,'state/issac-policy-test-'));
  const path=join(folder,'policy.json');
  try{
    for(const mutate of [p=>{p.conversation.game_reasoning_effort='high';},p=>{p.conversation.game_reasoning_effort='low';},p=>{p.deployment.state_relative_path='state/naimei/stream';}]){
      const policy=structuredClone(current);mutate(policy);writeFileSync(path,JSON.stringify(policy));
      assert.throws(()=>loadPolicy(root,path),/CONFIG_GAME_REASONING_SCOPE/);
    }
    const invalid=structuredClone(current);invalid.conversation.game_reasoning_effort=null;writeFileSync(path,JSON.stringify(invalid));
    assert.throws(()=>loadPolicy(root,path),/CONFIG_TYPE:policy.conversation.game_reasoning_effort/);
  }finally{rmSync(folder,{recursive:true,force:true});}
});

// Controlled HTTP responses exercise the installed DSH loop, not a production
// channel. In particular its concludeTurn must retain the successful tool result.
for(const choice of [{op:'pickup',status:'accepted'},{op:'wait',status:'succeeded',effect:'wait'},{op:'pickup',status:'accepted',wiki:true}]){
test('real DSH Responses concludes '+choice.op+(choice.wiki?' after current-context wiki':'')+' with none effort and keeps all wiki text',async()=>{
  const root=process.cwd(),policy=structuredClone(loadPolicy(root,'configs/issac/bridge-policy.json'));
  mkdirSync(join(root,'state'),{recursive:true});
  const folder=mkdtempSync(join(root,'state/issac-core-host-test-'));
  policy.deployment.dsh_home_relative_path=folder;
  const plan={plan_id:'controlled-plan',decision_id:'decision-A',context_id:'room-A',offer_id:'heart-A',budget:{},reason:'补血',commentary:'血量还没满，这颗红心我先拿上。'};
  let requests=0,received;const payloads=[];
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);
    received=JSON.parse(Buffer.concat(chunks));requests++;payloads.push(received);
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    const emit=value=>res.write('data: '+JSON.stringify(value)+'\n\n');
    const wiki=choice.wiki&&requests===1;
    const item={type:'function_call',id:'fc-controlled-'+requests,call_id:'call-controlled-'+requests,
      name:wiki?'isaac_wiki_query':'isaac_submit_plan',
      arguments:JSON.stringify({data:JSON.stringify(wiki?{query:{operation:'item',query:'The Sad Onion',kind:'item'}}:plan)}),status:'completed'};
    emit({type:'response.created',response:{id:'response-controlled',status:'in_progress'}});
    emit({type:'response.output_item.added',output_index:0,item:{...item,arguments:'',status:'in_progress'}});
    emit({type:'response.function_call_arguments.delta',output_index:0,item_id:item.id,delta:item.arguments});
    emit({type:'response.function_call_arguments.done',output_index:0,item_id:item.id,arguments:item.arguments});
    emit({type:'response.output_item.done',output_index:0,item});
    emit({type:'response.completed',response:{id:'response-controlled',status:'completed',output:[item],usage:{input_tokens:100,output_tokens:80,total_tokens:180}}});
    res.end();
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let host;
  try{
    host=await new DshHost(root,join(root,'tools/dsh'),policy).start();
    const persona=initialPersona(root,'naimei');await host.publishCharacter(persona.document,persona.version);
    const core=Object.create(NaimeiGameCore.prototype);
    Object.assign(core,{names:Object.keys(ISAAC_CORE_TOOLS),enabled:true,controlRevision:1,recent:[],record:()=>{},
      prompt:completePrompt(root,readFileSync(join(root,'configs/issac/core-persona-gameplay.md'),'utf8')),
      decision:async()=>({pending:true,connected:true,id:'decision-A',context_id:'room-A',context:{inventory_revision:'inventory-A'},remaining_ms:10000,offers:[{id:'heart-A',op:choice.op}]}),
      api:async(_port,path,body)=>{
        if(path==='/wiki'){
          assert.deepEqual(body.context,{decision_id:'decision-A',context_id:'room-A',inventory_revision:'inventory-A'});
          return {requested_edition:'rep',result:{edition:'rep',name:'The Sad Onion',effect:'Tears up',source:'controlled-local-wiki'}};
        }
        assert.equal(body.commentary,undefined);return {plan_id:body.plan_id,
        decision_id:body.decision_id,offer_id:body.offer_id,status:choice.status,...(choice.effect?{effect:choice.effect}:{})};}});
    host.gameplay=core;const turn={decision_id:'decision-A',context_id:'room-A',control_revision:1},probes=[];
    const result=await host.generate({sessionId:'controlled-native-plan',snapshot:{revision:'controlled',model:'controlled',protocol:'responses',
      baseUrl:'http://127.0.0.1:'+server.address().port+'/v1',systemPrompt:'',getApiKey:()=> 'controlled-key'},
      context:JSON.stringify({game_decision:{id:'decision-A',context_id:'room-A'}}),input:'提交当前选择与打算。',gameplayTurn:turn,
      tools:async()=>{throw Error('unexpected viewer tool');},onProbe:probe=>probes.push(probe),signal:AbortSignal.timeout(15000)});
    assert.equal(requests,choice.wiki?2:1);assert.equal(result.text,plan.commentary);assert.equal(result.steps,requests);
    for(const payload of payloads)assert.equal(payload.reasoning.effort,'none');
    for(const probe of probes){assert.equal(probe.game_reasoning_effort,'off');assert.ok(probe.elapsed_ms>=0);
      assert.ok(['completed','iterator_closed'].includes(probe.phase));}
    assert.equal(result.final_reason.kind,'completed');assert.equal(turn.submitted.status,choice.status);
    assert.deepEqual([...probes[0].tools].sort(),core.names.toSorted());
    assert.ok(probes[0].has_issac_wiki);assert.ok(probes[0].has_persona);
    for(const payload of payloads){const sent=JSON.stringify(payload);
      for(const pin of core.prompt.receipt.skill_sources)assert.ok(sent.includes(pin.sha256));}
  }finally{await host?.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));rmSync(folder,{recursive:true,force:true});}
});
}
