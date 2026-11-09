import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtempSync,mkdirSync,rmSync,readFileSync} from 'node:fs';
import {join} from 'node:path';
import {DshHost} from '../backend/dsh-bridge/host.mjs';
import {loadPolicy} from '../backend/dsh-bridge/policy.mjs';
import {initialPersona} from '../backend/dsh-bridge/persona.mjs';
import {NaimeiGameCore,ISAAC_CORE_TOOLS} from '../backend/dsh-bridge/isaac-core.mjs';
import {completePrompt} from '../integration/isaac-agent/dsh-host/isaac-plugin/stream-policy.mjs';

// Controlled HTTP responses exercise the installed DSH loop, not a production
// channel. In particular its concludeTurn must retain the successful tool result.
for(const choice of [{op:'pickup',status:'accepted'},{op:'wait',status:'succeeded',effect:'wait'}]){
test('real DSH Responses concludes '+choice.op+' without an extra request and keeps all wiki text',async()=>{
  const root=process.cwd(),policy=structuredClone(loadPolicy(root,'configs/issac/bridge-policy.json'));
  mkdirSync(join(root,'state'),{recursive:true});
  const folder=mkdtempSync(join(root,'state/issac-core-host-test-'));
  policy.deployment.dsh_home_relative_path=folder;
  const plan={plan_id:'controlled-plan',decision_id:'decision-A',context_id:'room-A',offer_id:'heart-A',budget:{},reason:'补血',commentary:'血量还没满，这颗红心我先拿上。'};
  let requests=0,received;
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);
    received=JSON.parse(Buffer.concat(chunks));requests++;
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    const emit=value=>res.write('data: '+JSON.stringify(value)+'\n\n');
    const item={type:'function_call',id:'fc-controlled',call_id:'call-controlled',name:'isaac_submit_plan',arguments:JSON.stringify({data:JSON.stringify(plan)}),status:'completed'};
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
      decision:async()=>({pending:true,connected:true,id:'decision-A',context_id:'room-A',remaining_ms:10000,offers:[{id:'heart-A',op:choice.op}]}),
      api:async(_port,_path,body)=>{assert.equal(body.commentary,undefined);return {plan_id:body.plan_id,
        decision_id:body.decision_id,offer_id:body.offer_id,status:choice.status,...(choice.effect?{effect:choice.effect}:{})};}});
    host.gameplay=core;const turn={decision_id:'decision-A',context_id:'room-A',control_revision:1},probes=[];
    const result=await host.generate({sessionId:'controlled-native-plan',snapshot:{revision:'controlled',model:'controlled',protocol:'responses',
      baseUrl:'http://127.0.0.1:'+server.address().port+'/v1',systemPrompt:'',getApiKey:()=> 'controlled-key'},
      context:JSON.stringify({game_decision:{id:'decision-A',context_id:'room-A'}}),input:'提交当前选择与打算。',gameplayTurn:turn,
      tools:async()=>{throw Error('unexpected viewer tool');},onProbe:probe=>probes.push(probe),signal:AbortSignal.timeout(15000)});
    assert.equal(requests,1);assert.equal(result.text,plan.commentary);assert.equal(result.steps,1);
    assert.equal(received.reasoning.effort,'low');
    assert.equal(probes[0].game_reasoning_effort,'low');
    assert.equal(result.final_reason.kind,'completed');assert.equal(turn.submitted.status,choice.status);
    assert.deepEqual([...probes[0].tools].sort(),core.names.toSorted());
    assert.ok(probes[0].has_issac_wiki);assert.ok(probes[0].has_persona);
    const sent=JSON.stringify(received);
    for(const pin of core.prompt.receipt.skill_sources)assert.ok(sent.includes(pin.sha256));
  }finally{await host?.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));rmSync(folder,{recursive:true,force:true});}
});
}
