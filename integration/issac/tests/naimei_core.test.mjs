import test from 'node:test';
import assert from 'node:assert/strict';
import {NaimeiGameCore,ISAAC_CORE_TOOLS} from '../../../backend/dsh-bridge/isaac-core.mjs';
import {digest} from '../../../backend/dsh-bridge/channel.mjs';

const offered=()=>({pending:true,connected:true,id:'decision-A',context_id:'room-A',remaining_ms:7000,
  identity:{controller:'controller-A',seed:100,restart:0,bridge:'bridge-A',room:84,stage:1,stage_type:0,dimension:0,visit:1},
  context:{inventory_revision:'inventory-A'},offers:[{id:'heart-A',op:'pickup'}]});
const exactCost=()=>({coins:2,keys:0,bombs:0,health_half_hearts:0});
function fixture() {
  const core=Object.create(NaimeiGameCore.prototype),calls=[];
  Object.assign(core,{names:Object.keys(ISAAC_CORE_TOOLS),enabled:true,recent:[],record:()=>{},decision:async()=>offered(),
    api:async(port,path,body)=>{calls.push({port,path,body});return {plan_id:body?.plan_id,
      decision_id:body?.decision_id,offer_id:body?.offer_id,status:'accepted'};}});
  return {core,calls,turn:{decision_id:'decision-A',context_id:'room-A'},sessionId:'naimei-game-real-session'};
}

test('compact choice binds only its own current turn and exact chosen offer cost',async()=>{
  const {core,calls,turn,sessionId}=fixture();turn.session_id=sessionId;
  core.decision=async()=>({...offered(),offers:[{id:'heart-A',op:'pickup',cost:exactCost()}]});
  const choice={offer_id:'heart-A',commentary:'这颗红心能补得更多，先把生命补起来再往前走。'};
  await core.tool('isaac_submit_plan',choice,{sessionId,turn});
  assert.deepEqual(calls[0].body.budget,exactCost());
  assert.equal(calls[0].body.decision_id,turn.decision_id);assert.equal(calls[0].body.context_id,turn.context_id);
  assert.match(calls[0].body.plan_id,/^nm-[a-f0-9]{32}$/);assert.equal(calls[0].body.reason,choice.commentary);
  assert.equal(calls[0].body.commentary,undefined);assert.equal(turn.narration,choice.commentary);
  await assert.rejects(core.tool('isaac_submit_plan',choice,{sessionId,turn}),/ONE_CORE_PLAN_PER_TURN/);
});

test('compact choice cannot choose an unknown offer, rebind a turn, infer costs or escape a viewer session',async()=>{
  for(const defect of ['unknown','context','session','missing-cost','negative-cost','extra-cost']){
    const {core,calls,turn,sessionId}=fixture();turn.session_id=sessionId;
    const cost=exactCost();if(defect==='negative-cost')cost.coins=-1;if(defect==='extra-cost')cost.arbitrary=0;
    core.decision=async()=>({...offered(),offers:[{id:'heart-A',op:'pickup',...(defect==='missing-cost'?{}:{cost})}]});
    if(defect==='context')turn.context_id='old-room';if(defect==='session')turn.session_id='viewer-session';
    await assert.rejects(core.tool('isaac_submit_plan',{offer_id:defect==='unknown'?'invented':'heart-A',
      commentary:'这颗红心能补得更多，先把生命补起来再往前走。'},{sessionId,turn}));
    assert.equal(calls.length,0,defect);assert.equal(turn.narration,undefined,defect);
  }
});

test('compact native rejection cannot publish narration or acquire a submitted choice',async()=>{
  const {core,turn,sessionId}=fixture();turn.session_id=sessionId;
  core.decision=async()=>({...offered(),offers:[{id:'heart-A',op:'pickup',cost:exactCost()}]});
  core.api=async()=>({status:'rejected'});
  await assert.rejects(core.tool('isaac_submit_plan',{offer_id:'heart-A',
    commentary:'这颗红心能补得更多，先把生命补起来再往前走。'},{sessionId,turn}),/CORE_PLAN_NOT_ACCEPTED/);
  assert.equal(turn.narration,undefined);assert.equal(turn.submitted,undefined);
});

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
  await assert.rejects(core.tool('isaac_submit_plan',{decision_id:'decision-A',context_id:'room-A',arbitrary_input:'X'},
    {sessionId,turn:{decision_id:'decision-A',context_id:'room-A'}}),/CORE_PLAN_FIELDS/);
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

test('a native fault from a cancelled revision cannot disarm a later explicit recovery',async()=>{
  const {core}=fixture();let entered,release;
  const started=new Promise(resolve=>entered=resolve),waiting=new Promise(resolve=>release=resolve);
  Object.assign(core,{busy:false,attempts:new Map(),failures:0,turns:0,latencies:[],pending:new Map(),backlog:[],
    status:()=>({ready:true}),controlRevision:1,
    generate:async(_context,turn)=>{core.activeAbort=new AbortController();turn.abort=core.activeAbort;
      turn.native_fault=true;turn.stale_reason='CORE_NATIVE_STATE_NOT_FRESH';entered();await waiting;throw Error('old fault');}});
  const old=core.runDecision(offered());await started;
  core.control(false);core.control(true);release();await old;
  assert.equal(core.enabled,true);assert.equal(core.controlRevision,3);assert.equal(core.failures,0);
});

test('a replaced same-room choice aborts its bound model turn and a fresh turn can proceed',async()=>{
  const {core}=fixture();let entered,decision=offered();
  const started=new Promise(resolve=>entered=resolve),seen=[];
  Object.assign(core,{bridge:{ready:true},busy:false,attempts:new Map(),failures:0,turns:0,latencies:[],
    controlRevision:1,polling:false,drain:async()=>{},offerSpeech:()=>{},decision:async()=>decision,
    generate:async(_context,turn)=>{
      seen.push(turn.decision_id);core.activeAbort=new AbortController();turn.abort=core.activeAbort;
      if(turn.decision_id==='decision-A'){
        entered();await new Promise((_,reject)=>turn.abort.signal.addEventListener('abort',()=>reject(Error('cancelled')),{once:true}));
      }
      await core.tool('isaac_submit_plan',{plan_id:'new-plan',decision_id:decision.id,context_id:decision.context_id,
        offer_id:'heart-A',budget:{},reason:'current choice'},{sessionId:turn.session_id,turn});
      return {text:'这颗红心我先拿上。'};
    }});
  const old=core.runDecision(decision);await started;
  decision={...offered(),id:'decision-B'};await core.tick();await old;
  if(!core.busy&&core.turns===0)await core.runDecision(decision);
  while(core.busy)await new Promise(resolve=>setImmediate(resolve));
  assert.equal(core.enabled,true);assert.equal(core.failures,0);assert.equal(core.activeDecisionTurn,null);
  assert.deepEqual(seen,['decision-A','decision-B']);assert.equal(core.turns,1);assert.equal(core.failures,0);
});

test('a stale get-decision cannot rebind the old turn to the new decision',async()=>{
  const {core,turn,sessionId,calls}=fixture();turn.abort=new AbortController();
  core.decision=async()=>({...offered(),id:'decision-B'});
  await assert.rejects(core.tool('isaac_get_decision',{}, {sessionId,turn}),/CORE_DECISION_CHANGED/);
  assert.equal(turn.abort.signal.aborted,true);
  await assert.rejects(core.tool('isaac_submit_plan',{decision_id:'decision-B',context_id:'room-A'}, {sessionId,turn}),/CORE_TURN_CANCELLED/);
  assert.equal(calls.length,0);
});

test('native state loss immediately aborts the bound turn as a distinct fault',async()=>{
  const {core,turn}=fixture();turn.abort=new AbortController();
  assert.equal(core.cancelObsoleteDecision(turn,{pending:false,connected:false}),'CORE_NATIVE_STATE_NOT_FRESH');
  assert.equal(turn.abort.signal.aborted,true);assert.equal(turn.native_fault,true);
});

test('loss of a fresh pending decision remains an ordinary cancellation',async()=>{
  const {core,turn}=fixture();turn.abort=new AbortController();
  assert.equal(core.cancelObsoleteDecision(turn,{pending:false,connected:true}),'FRESH_CORE_DECISION_REQUIRED');
  assert.equal(turn.abort.signal.aborted,true);
});

test('freshness rejection cannot become a no-choice model failure or publish the rejected intention',async()=>{
  const {core}=fixture();const speeches=[],events=[];let disabled=0;
  Object.assign(core,{busy:false,attempts:new Map(),failures:0,turns:0,latencies:[],controlRevision:1,
    record:(kind,body)=>events.push({kind,...body}),offerSpeech:item=>speeches.push(item),
    control:enabled=>{assert.equal(enabled,false);core.enabled=false;disabled++;},
    generate:async(_context,turn)=>{
      turn.abort=new AbortController();core.activeAbort=turn.abort;
      core.decision=async()=>({...offered(),connected:false});
      await core.tool('isaac_submit_plan',{},{sessionId:turn.session_id,turn});
      throw Error('A rejected tool cannot finish as model-authored speech');
    }});
  await core.runDecision(offered());
  assert.equal(disabled,1);assert.equal(core.failures,1);assert.equal(core.turns,0);
  assert.equal(core.lastError,'CORE_NATIVE_STATE_NOT_FRESH');assert.deepEqual(speeches,[]);
  assert.equal(events.some(r=>r.code==='CORE_TURN_DID_NOT_SUBMIT_A_CHOICE'),false);
  assert.equal(events.at(-1).turn_kind,'native_state_loss');
});

test('an in-flight accepted plan is not cancelled when its pending decision disappears',async()=>{
  const {core,turn,sessionId}=fixture();let entered,release;
  const started=new Promise(resolve=>entered=resolve),waiting=new Promise(resolve=>release=resolve);
  turn.abort=new AbortController();core.api=async(_port,_path,body)=>{entered();await waiting;
    return {plan_id:body.plan_id,decision_id:body.decision_id,offer_id:body.offer_id,status:'accepted'};};
  const request=core.tool('isaac_submit_plan',{plan_id:'race',decision_id:'decision-A',context_id:'room-A',offer_id:'heart-A',budget:{}},{sessionId,turn});
  await started;assert.equal(core.cancelObsoleteDecision(turn,{pending:false,connected:true}),null);
  release();await request;assert.equal(turn.submitted.status,'accepted');assert.equal(turn.abort.signal.aborted,false);
});

test('a native rejection caused by a replacement decision cancels the obsolete turn',async()=>{
  const {core,turn,sessionId}=fixture();let reads=0;turn.abort=new AbortController();
  core.decision=async()=>++reads===1?offered():({...offered(),id:'decision-B'});
  core.api=async()=>{const error=Error('native refused');error.code='CORE_GAME_TOOL_REJECTED';throw error;};
  await assert.rejects(core.tool('isaac_submit_plan',{plan_id:'race',decision_id:'decision-A',context_id:'room-A',offer_id:'heart-A',budget:{}},{sessionId,turn}),/CORE_DECISION_CHANGED/);
  assert.equal(turn.abort.signal.aborted,true);assert.equal(turn.submitted,undefined);
});

test('only an actual matching completed wait is a valid immediate success',async()=>{
  for(const [op,status,effect,expected] of [['wait','succeeded','wait',true],['pickup','succeeded','wait',false],
    ['wait','succeeded','pickup',false],['wait','rejected','wait',false]]){
    const {core,turn,sessionId}=fixture();
    core.decision=async()=>({...offered(),offers:[{id:'heart-A',op}]});
    core.api=async(_port,_path,body)=>({plan_id:body.plan_id,decision_id:body.decision_id,offer_id:body.offer_id,status,effect});
    const plan={plan_id:'defer',decision_id:'decision-A',context_id:'room-A',offer_id:'heart-A',budget:{},commentary:'先把这件留着，我去下一间看看。'};
    if(expected){await core.tool('isaac_submit_plan',plan,{sessionId,turn});assert.equal(turn.submitted.status,'succeeded');assert.equal(turn.narration,plan.commentary);}
    else{await assert.rejects(core.tool('isaac_submit_plan',plan,{sessionId,turn}),/CORE_PLAN_NOT_ACCEPTED/);assert.equal(turn.narration,undefined);}
  }
});

test('speech remains bounded but can finish preparation and playback after ten seconds in the same room',async()=>{
  const {core}=fixture(),identity=offered().identity;
  const event={run_id:digest({controller:identity.controller,seed:identity.seed,restart:identity.restart,bridge:identity.bridge}),
    room_id:digest({room:identity.room,stage:identity.stage,stage_type:identity.stage_type,dimension:identity.dimension,visit:identity.visit}),
    bridge_instance:identity.bridge,observed_at:Date.now()/1000-12,expires_at:Date.now()/1000+18};
  let actual={...identity};core.api=async()=>({connected:true,age_ms:10,identity:actual});
  assert.equal(await core.current(event),true);
  actual.visit++;assert.equal(await core.current(event),false);
  actual={...identity,bridge:'restarted'};assert.equal(await core.current(event),false);
  actual={...identity};assert.equal(await core.current({...event,expires_at:Date.now()/1000-1}),false);
  core.api=async()=>({connected:true,age_ms:1500,identity});assert.equal(await core.current(event),false);
});

test('a pending real utterance suppresses redundant fact generation without delaying fresh choices',async()=>{
  const {core}=fixture();let facts=0,choices=0,decision={pending:false,connected:true};
  Object.assign(core,{bridge:{ready:true,state:{active:()=>null}},polling:false,busy:false,
    pending:new Map([['playing',{}]]),backlog:[],lastFact:0,attempts:new Map(),
    drain:async()=>{},decision:async()=>decision,runFact:()=>{facts++;},runDecision:()=>{choices++;}});
  await core.tick();assert.equal(facts,0);
  decision=offered();await core.tick();assert.equal(choices,1);assert.equal(facts,0);
  decision={pending:false,connected:true};core.pending.clear();await core.tick();assert.equal(facts,1);
});

test('expiry and a room change produce distinct real speech cancellation reasons',async()=>{
  const {core}=fixture(),cancelled=[],records=[];
  core.pending=new Map([['expired',{event:{event_id:'a',expires_at:Date.now()/1000-1}}],
    ['changed',{event:{event_id:'b',expires_at:Date.now()/1000+30}}]]);
  core.bridge={state:{request:()=>({status:'SPEAKING'}),cancel:(id,reason)=>cancelled.push({id,reason})}};
  core.current=async()=>false;core.record=(kind,body)=>records.push({kind,...body});
  await core.checkPending();
  assert.deepEqual(cancelled,[{id:'expired',reason:'game_fact_expired'},{id:'changed',reason:'game_fact_context_changed'}]);
  assert.deepEqual(records.map(r=>r.reason),['expired','native_context_changed']);
});

test('the completion counter requires all actual PCM samples, never partial or missing playback',async()=>{
  const {core}=fixture();let utterance={valid_sample_count:16000,contiguous_played_samples:8000};
  core.pending=new Map([['real',{event:{event_id:'verified-choice'}}]]);
  core.bridge={db:{get:()=>utterance}};core.completedSpeech=0;
  await core.completed({request_id:'real'});assert.equal(core.completedSpeech,0);assert.equal(core.pending.size,1);
  utterance={valid_sample_count:0,contiguous_played_samples:0};await core.completed({request_id:'real'});
  assert.equal(core.completedSpeech,0);
  utterance={valid_sample_count:16000,contiguous_played_samples:16000};await core.completed({request_id:'real'});
  assert.equal(core.completedSpeech,1);assert.equal(core.pending.size,0);
  await core.completed({request_id:'real'});assert.equal(core.completedSpeech,1);
});
