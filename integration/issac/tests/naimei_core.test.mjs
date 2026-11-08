import test from 'node:test';
import assert from 'node:assert/strict';
import {NaimeiGameCore,ISAAC_CORE_TOOLS} from '../../../backend/dsh-bridge/isaac-core.mjs';

const offered=()=>({pending:true,connected:true,id:'decision-A',context_id:'room-A',remaining_ms:7000,
  context:{inventory_revision:'inventory-A'},offers:[{id:'heart-A',op:'pickup'}]});
function fixture() {
  const core=Object.create(NaimeiGameCore.prototype),calls=[];
  Object.assign(core,{names:Object.keys(ISAAC_CORE_TOOLS),enabled:true,recent:[],record:()=>{},decision:async()=>offered(),
    api:async(port,path,body)=>{calls.push({port,path,body});return {plan_id:body?.plan_id,status:'accepted'};}});
  return {core,calls,turn:{decision_id:'decision-A',context_id:'room-A'},sessionId:'naimei-game-real-session'};
}

test('the same core binds actual actor and session to a fresh bounded choice',async()=>{
  const {core,calls,turn,sessionId}=fixture();
  const plan={plan_id:'plan-A',decision_id:'decision-A',context_id:'room-A',offer_id:'heart-A',budget:{},reason:'补血'};
  assert.equal((await core.tool('isaac_submit_plan',plan,{sessionId,turn})).status,'accepted');
  assert.equal(calls[0].port,9532);assert.equal(calls[0].body.actor_id,'naimei');
  assert.equal(calls[0].body.core_session_id,sessionId);assert.equal(turn.submitted.status,'accepted');
  await assert.rejects(core.tool('isaac_submit_plan',plan,{sessionId,turn}),/ONE_CORE_PLAN_PER_TURN/);
});

test('a delayed turn cannot submit to a replacement room or decision',async()=>{
  const {core,calls,turn,sessionId}=fixture();
  core.decision=async()=>({...offered(),id:'decision-B',context_id:'room-B'});
  await assert.rejects(core.tool('isaac_submit_plan',{decision_id:'decision-B',context_id:'room-B'},{sessionId,turn}),/CORE_DECISION_CHANGED/);
  assert.equal(calls.length,0);
});

test('wiki evidence uses server-owned current inventory context, not supplied context',async()=>{
  const {core,calls,turn,sessionId}=fixture(),query={operation:'item',query:'D6'};
  await core.tool('isaac_wiki_query',{query},{sessionId,turn});
  assert.deepEqual(calls[0].body.context,{decision_id:'decision-A',context_id:'room-A',inventory_revision:'inventory-A'});
  await assert.rejects(core.tool('isaac_wiki_query',{query,context:{context_id:'old'}},{sessionId,turn}),/CORE_WIKI_FIELDS/);
});

test('disabled, expired or extended plans never reach native execution',async()=>{
  const {core,calls,turn,sessionId}=fixture();
  core.enabled=false;
  await assert.rejects(core.tool('isaac_submit_plan',{}, {sessionId,turn}),/CORE_AUTOMATION_NOT_ARMED/);
  core.enabled=true;core.decision=async()=>({...offered(),remaining_ms:0});
  await assert.rejects(core.tool('isaac_submit_plan',{}, {sessionId,turn}),/FRESH_CORE_DECISION_REQUIRED/);
  core.decision=async()=>offered();
  await assert.rejects(core.tool('isaac_submit_plan',{decision_id:'decision-A',context_id:'room-A',arbitrary_input:'X'}, {sessionId,turn}),/CORE_PLAN_FIELDS/);
  assert.equal(calls.length,0);
});

test('an unavailable core model disarms rather than delegating choices to rules',async()=>{
  const {core}=fixture();let disarmed=0;
  Object.assign(core,{busy:false,attempts:new Map(),failures:0,turns:0,latencies:[],recent:[],
    generate:async()=>{throw Error('local model unavailable');},
    control:value=>{assert.equal(value,false);core.enabled=false;disarmed++;}});
  await core.runDecision(offered());
  assert.equal(disarmed,1);assert.equal(core.turns,0);assert.equal(core.failures,1);assert.equal(core.busy,false);
});
test('a failed spontaneous reaction also disarms the same core and abandons its reserved fact',async()=>{
  const {core}=fixture();let disarmed=0,abandoned=0;
  Object.assign(core,{busy:false,failures:0,current:async()=>true,
    api:async()=>({event:{event_id:'observed-fact'},nonce:'reserved-fact'}),
    generate:async()=>{throw Error('local model unavailable');},
    abandon:async()=>{abandoned++;},control:value=>{assert.equal(value,false);core.enabled=false;disarmed++;}});
  await core.runFact();
  assert.equal(disarmed,1);assert.equal(abandoned,1);assert.equal(core.failures,1);assert.equal(core.busy,false);
});
test('a choice intentionally interrupting self-talk does not falsely disarm gameplay',async()=>{
  const {core}=fixture();let abandoned=0;
  Object.assign(core,{busy:false,failures:0,current:async()=>true,
    api:async()=>({event:{event_id:'observed-fact'},nonce:'reserved-fact'}),
    generate:async()=>{core.activeAbort=new AbortController();core.activeAbort.abort();throw Error('new decision preemption');},
    abandon:async()=>{abandoned++;},control:()=>{throw Error('unexpected disarm');}});
  await core.runFact();
  assert.equal(core.enabled,true);assert.equal(abandoned,1);assert.equal(core.failures,0);
});

test('accepted model commentary is separated from the native plan and rejected choices have none',async()=>{
  const {core,calls,turn,sessionId}=fixture();
  const plan={plan_id:'plan-A',decision_id:'decision-A',context_id:'room-A',offer_id:'heart-A',budget:{},reason:'补血',commentary:'血量不满，这颗红心我先拿上。'};
  await core.tool('isaac_submit_plan',plan,{sessionId,turn});
  assert.equal(turn.narration,plan.commentary);assert.equal(calls[0].body.commentary,undefined);
  const next={decision_id:'decision-A',context_id:'room-A'};
  core.api=async()=>({plan_id:'plan-A',status:'rejected'});
  await assert.rejects(core.tool('isaac_submit_plan',plan,{sessionId,turn:next}),/CORE_PLAN_NOT_ACCEPTED/);
  assert.equal(next.narration,undefined);assert.equal(next.submitted,undefined);
});

test('normal pause and rearm fence a late model turn without disarming the new revision',async()=>{
  const {core}=fixture();let release,entered;
  const started=new Promise(resolve=>entered=resolve),waiting=new Promise(resolve=>release=resolve);
  Object.assign(core,{busy:false,attempts:new Map(),failures:0,turns:0,latencies:[],recent:[],pending:new Map(),backlog:[],
    status:()=>({ready:true}),controlRevision:4,
    generate:async()=>{core.activeAbort=new AbortController();entered();await waiting;throw Error('cancelled old request');}});
  const pending=core.runDecision(offered());await started;
  core.control(false);core.control(true);release();await pending;
  assert.equal(core.enabled,true);assert.equal(core.controlRevision,6);assert.equal(core.failures,0);
  assert.equal(core.turns,0);assert.equal(core.busy,false);
});

test('a delayed plan cannot cross a disarm/rearm during the freshness read',async()=>{
  const {core,calls,turn,sessionId}=fixture();core.controlRevision=1;turn.control_revision=1;
  core.decision=async()=>{core.controlRevision=3;return offered();};
  await assert.rejects(core.tool('isaac_submit_plan',{decision_id:'decision-A',context_id:'room-A'},{sessionId,turn}),/CORE_TURN_CANCELLED/);
  assert.equal(calls.length,0);
});
