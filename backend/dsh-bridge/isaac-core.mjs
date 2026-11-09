// Naimei owns strategic choices; the native controller only offers and executes.
import {appendFileSync, readFileSync, mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {canonical, digest} from './channel.mjs';
import {requireValue} from './state.mjs';
import {completePrompt} from '../../integration/isaac-agent/dsh-host/isaac-plugin/stream-policy.mjs';

export const ISAAC_CORE_TOOLS = Object.freeze({
  isaac_get_state: '直接读取奶妹当前游戏状态；data为{"topic":"state"}，或health/inventory/room/pickups/resources/actives/pockets/map/enemies/history。',
  isaac_get_decision: '直接读取当前待决策状态、context_id及合法offers。data为空对象。',
  isaac_lookup: '只读机制速查。data含kind为collectible/card/domain和id。',
  isaac_wiki_query: '直接查本地issac-wiki，固定rep。data为{"query":{"operation":"item","query":"名称或编号","kind":"item"}}；决策上下文由宿主绑定。',
  isaac_submit_plan: '由奶妹本人选择当前offer：data只需{"offer_id":"当前候选id","commentary":"15至40字自然口语的打算"}。宿主仅绑定本回合身份和该候选的确切成本，不替你选择。不能声称已完成；真实接受后结束本回合并播报该句，无需追加回复。',
});
const TOPICS = new Set(['state','health','inventory','effects','history','actives','pockets','map','room','enemies','bosses','pickups','resources']);
const identityOf = value => value?.identity || value?.data?.identity;
export const coreChoiceConcluded = turn => turn?.submitted?.status==='accepted'
  || turn?.submitted?.status==='succeeded'&&turn.submitted.op==='wait'&&turn.submitted.effect==='wait';
function eventIdentity(identity) {
  return {run_id:digest({controller:identity.controller,seed:identity.seed,restart:identity.restart,bridge:identity.bridge}),
    room_id:digest({room:identity.room,stage:identity.stage,stage_type:identity.stage_type,dimension:identity.dimension,visit:identity.visit}),bridge_instance:identity.bridge};
}

export class NaimeiGameCore {
  constructor(bridge) {
    this.bridge=bridge;this.root=bridge.root;this.token=readFileSync(join(this.root,'private/issac/bridge-token.txt'),'utf8').trim();
    this.prompt=completePrompt(this.root,readFileSync(join(this.root,'configs/issac/core-persona-gameplay.md'),'utf8'));
    this.names=Object.keys(ISAAC_CORE_TOOLS);this.enabled=false;this.closed=false;this.busy=false;this.polling=false;
    this.pending=new Map();this.backlog=[];this.attempts=new Map();this.latest=null;this.recent=[];this.activeAbort=null;this.activeDecisionTurn=null;
    this.turns=0;this.failures=0;this.lastError=null;this.lastFact=0;this.latencies=[];this.controlRevision=0;this.completedSpeech=0;
    mkdirSync(join(this.root,'state/issac-stream'),{recursive:true});
    this.audit=join(this.root,'state/issac-stream/naimei-game-core.jsonl');
  }
  record(kind,body={}) {appendFileSync(this.audit,canonical({at:Date.now(),actor_id:'naimei',kind,...body})+'\n');}
  description(name) {return ISAAC_CORE_TOOLS[name];}
  status() {
    const times=[...this.latencies].sort((a,b)=>a-b);
    const channel=this.bridge.channel.publicInfo();
    let candidateId=null;
    try { candidateId=JSON.parse(readFileSync(join(this.root,'.setup/candidate.json'),'utf8')).id; } catch {}
    return {ready:!!this.bridge.host?.ready&&!!this.bridge.health().persona_injection_ready,actor_id:'naimei',
      strategic_owner:'naimei_core_dsh',automatic:this.enabled,busy:this.busy,turns:this.turns,failures:this.failures,
      last_error:this.lastError,dshVersion:this.bridge.policy.versions.dsh_candidate,model:channel.model,
      protocol:channel.protocol,channel_source:channel.source,candidate_id:candidateId,
      process_id:process.pid,registeredTools:this.names,prompt:this.prompt.receipt,independent_strategy_host:false,
      actual_completed_game_utterances:this.completedSpeech,
      decision_latency_p95_ms:times.length?times[Math.min(times.length-1,Math.ceil(times.length*.95)-1)]:null};
  }
  control(enabled) {
    requireValue(typeof enabled==='boolean','BOOLEAN_CORE_CONTROL_REQUIRED');
    if(enabled)requireValue(this.status().ready&&!this.closed,'NAIMEI_CORE_NOT_READY',409);
    this.controlRevision=(this.controlRevision||0)+1;this.enabled=enabled;
    if(!enabled){this.activeAbort?.abort();for(const item of this.backlog)void this.abandon(item);this.backlog=[];
      for(const [id,item] of this.pending){this.bridge.state.cancel(id,'game_automation_disarmed');void this.abandon(item);}
      this.pending.clear();this.latest=null;this.recent=[];this.attempts.clear();}
    this.record('core_control',{automatic:enabled,revision:this.controlRevision});return this.status();
  }
  assertTurnCurrent(turn) {
    requireValue(!turn?.stale_reason,'CORE_TURN_CANCELLED',409);
    if(turn?.control_revision!==undefined)requireValue(this.enabled&&!this.closed&&turn.control_revision===(this.controlRevision||0)
      &&!turn.abort?.signal.aborted,'CORE_TURN_CANCELLED',409);
  }
  turnCancelled(turn) {
    return !!turn.stale_reason||!!turn.abort?.signal.aborted||turn.control_revision!==(this.controlRevision||0)||this.closed||!this.enabled;
  }
  cancelObsoleteDecision(turn,decision) {
    // A pending choice disappears normally while its own POST is being accepted.
    // Defer this check until that response is known, without weakening native guards.
    if(!turn?.decision_id||turn.submitted||turn.submitting)return null;
    const code=decision.connected!==true?'CORE_NATIVE_STATE_NOT_FRESH'
      :!decision.pending||decision.remaining_ms<=0?'FRESH_CORE_DECISION_REQUIRED'
      :decision.id!==turn.decision_id||decision.context_id!==turn.context_id?'CORE_DECISION_CHANGED':null;
    if(code&&!turn.stale_reason){turn.stale_reason=code;turn.abort?.abort();
      if(code==='CORE_NATIVE_STATE_NOT_FRESH')turn.native_fault=true;
      this.record('core_decision_superseded',{session_id:turn.session_id,decision_id:turn.decision_id,
        replacement_decision_id:decision.pending?decision.id:null,code});}
    return code;
  }
  assertDecisionCurrent(turn,decision) {
    this.assertTurnCurrent(turn);
    const obsolete=this.cancelObsoleteDecision(turn,decision);
    requireValue(!obsolete,obsolete||'CORE_DECISION_CHANGED',409);
    requireValue(decision.pending&&decision.connected&&decision.remaining_ms>0,'FRESH_CORE_DECISION_REQUIRED',409);
  }
  async api(port,path,body) {
    const response=await fetch('http://127.0.0.1:'+port+path,{method:body===undefined?'GET':'POST',
      headers:{'Content-Type':'application/json','X-Isaac-Token':this.token},body:body===undefined?undefined:JSON.stringify(body),
      signal:AbortSignal.timeout(2500)});
    const value=await response.json();requireValue(response.ok,'CORE_GAME_TOOL_REJECTED',409);return value;
  }
  async decision() {return this.api(9532,'/decision');}
  augment(context) {
    if(context?.game_decision)return context;
    return {...(context||{}),...(this.latest?{current_game:{observation_at:this.latest.at,decision:this.latest.decision},
      recent_naimei_game_decisions:this.recent.slice(-4)}:{})};
  }
  async current(event) {
    if(this.closed||Date.now()/1000>=event.expires_at)return false;
    const state=await this.api(9532,'/query?topic=state'),identity=identityOf(state);
    if(state.connected!==true||state.age_ms>=1500||!identity)return false;
    const actual=eventIdentity(identity);
    return ['run_id','room_id','bridge_instance'].every(key=>actual[key]===event[key]);
  }
  async tool(name,value,{sessionId,turn}={}) {
    requireValue(this.names.includes(name)&&value&&typeof value==='object'&&!Array.isArray(value),'CORE_TOOL_ARGUMENTS');
    this.assertTurnCurrent(turn);
    const started=Date.now();let result;
    if(name==='isaac_get_state') {
      requireValue(Object.keys(value).every(key=>key==='topic'),'CORE_STATE_FIELDS');
      const topic=value.topic||'state';requireValue(TOPICS.has(topic),'CORE_STATE_TOPIC');
      result=await this.api(9532,'/query?topic='+encodeURIComponent(topic));
    } else if(name==='isaac_get_decision') {
      requireValue(!Object.keys(value).length,'CORE_DECISION_FIELDS');result=await this.decision();
      if(turn?.decision_id)this.assertDecisionCurrent(turn,result);
    } else if(name==='isaac_lookup') {
      requireValue(Object.keys(value).every(key=>['kind','id'].includes(key))&&['collectible','card','domain'].includes(value.kind)
        &&['string','number'].includes(typeof value.id)&&String(value.id).length<=100,'CORE_LOOKUP_FIELDS');
      result=await this.api(9532,'/lookup?kind='+encodeURIComponent(value.kind)+'&id='+encodeURIComponent(String(value.id)));
    } else {
      requireValue(this.enabled,'CORE_AUTOMATION_NOT_ARMED',409);
      const decision=await this.decision();
      this.assertDecisionCurrent(turn,decision);
      if(name==='isaac_wiki_query') {
        requireValue(Object.keys(value).length===1&&value.query&&typeof value.query==='object','CORE_WIKI_FIELDS');
        result=await this.api(9532,'/wiki',{query:value.query,context:{decision_id:decision.id,context_id:decision.context_id,
          inventory_revision:decision.context.inventory_revision}});
      } else {
        requireValue(Object.keys(value).every(key=>['plan_id','decision_id','context_id','offer_id','budget','reason','commentary'].includes(key)),'CORE_PLAN_FIELDS');
        const compact=Object.keys(value).every(key=>['offer_id','commentary'].includes(key));
        if(!compact)requireValue(value.decision_id===decision.id&&value.context_id===decision.context_id,'CORE_PLAN_CONTEXT_CHANGED',409);
        requireValue(!turn?.submitted,'ONE_CORE_PLAN_PER_TURN',409);
        const {commentary,...supplied}=value;
        if(commentary!==undefined)requireValue(typeof commentary==='string'&&commentary.trim().length>0&&commentary.trim().length<=40
          &&!/[\r\n{}<>]/.test(commentary),'CORE_COMMENTARY_INVALID');
        const offer=decision.offers?.find(item=>item.id===value.offer_id);
        requireValue(offer,'CORE_PLAN_OFFER_REQUIRED',409);
        let plan=supplied;
        if(compact) {
          requireValue(turn?.session_id===sessionId&&sessionId?.startsWith('naimei-game-')
            &&turn.decision_id===decision.id&&turn.context_id===decision.context_id,'CORE_COMPACT_BOUND_TURN_REQUIRED',409);
          requireValue(typeof commentary==='string'&&commentary.trim().length>=15,'CORE_COMMENTARY_INVALID');
          const keys=['coins','keys','bombs','health_half_hearts'];
          requireValue(offer.cost&&Object.keys(offer.cost).length===keys.length
            &&keys.every(key=>Number.isSafeInteger(offer.cost[key])&&offer.cost[key]>=0),'CORE_OFFER_EXACT_COST_REQUIRED',409);
          plan={plan_id:'nm-'+digest({session:sessionId,decision:decision.id,offer:offer.id}).slice(0,32),
            decision_id:turn.decision_id,context_id:turn.context_id,offer_id:offer.id,
            budget:Object.fromEntries(keys.map(key=>[key,offer.cost[key]])),reason:commentary.trim()};
        }
        requireValue(plan.decision_id===decision.id&&plan.context_id===decision.context_id,'CORE_PLAN_CONTEXT_CHANGED',409);
        if(turn)turn.submitting=true;
        try {
          result=await this.api(9532,'/plan',{...plan,actor_id:'naimei',core_session_id:sessionId});
        } catch(error) {
          if(turn)turn.submitting=false;
          if(error.code==='CORE_GAME_TOOL_REJECTED')this.assertDecisionCurrent(turn,await this.decision());
          throw error;
        } finally {if(turn)turn.submitting=false;}
        this.assertTurnCurrent(turn);
        const accepted=result.status==='accepted'||offer.op==='wait'&&result.status==='succeeded'&&result.effect==='wait';
        requireValue(accepted&&result.plan_id===plan.plan_id&&result.decision_id===plan.decision_id
          &&result.offer_id===value.offer_id,'CORE_PLAN_NOT_ACCEPTED',409);
        if(turn){turn.submitted={plan_id:result.plan_id,status:result.status,offer_id:value.offer_id,op:offer.op,
          origin_room:decision.identity?.room,action_id:offer.action_id,route:offer.route||null,
          ...(result.effect?{effect:result.effect}:{})};
          if(commentary!==undefined)turn.narration=commentary.trim();}
      }
    }
    this.record('core_tool',{session_id:sessionId,tool:name,decision_id:turn?.decision_id,elapsed_ms:Date.now()-started,
      ...(name==='isaac_submit_plan'?{plan_id:result.plan_id,status:result.status,offer_id:value.offer_id}:{})});
    return result;
  }
  async tick() {
    if(this.closed||!this.enabled||!this.bridge.ready||this.bridge.administration?.locked||this.polling)return;
    this.polling=true;
    try {
      const decision=await this.decision();this.latest={at:Date.now(),decision};
      if(this.busy&&this.activeKind==='decision')this.cancelObsoleteDecision(this.activeDecisionTurn,decision);
      await this.drain();
      if(decision.pending&&this.busy&&this.activeKind==='fact')this.activeAbort?.abort();
      if(!this.busy&&decision.pending&&decision.connected&&decision.remaining_ms>1200) {
        const prior=this.attempts.get(decision.id);
        if(!prior||prior.count<2&&Date.now()-prior.at>1500)void this.runDecision(decision);
      } else if(!this.busy&&!decision.pending&&!this.pending.size&&!this.backlog.length
        &&!this.bridge.state.active()&&Date.now()-this.lastFact>=3000)void this.runFact();
    } catch {this.lastError='CURRENT_GAME_UNAVAILABLE';}
    finally {this.polling=false;}
  }
  async generate(context,turn,input,timeout=18000) {
    const bridge=this.bridge,base=bridge.channel.snapshot();
    const snapshot={...base,provider:'issac-naimei-core',
      revision:digest({base:base.revision,prompt:this.prompt.receipt.sha256})};
    this.activeAbort=new AbortController();turn.abort=this.activeAbort;
    const signal=AbortSignal.any([this.activeAbort.signal,AbortSignal.timeout(timeout)]);
    return bridge.host.generate({sessionId:turn.session_id,snapshot,input,signal,gameplayTurn:turn,maxTokens:512,
      context:canonical({...context,partition_key:'ephemeral_game_not_viewer',humanity_public_snapshot:bridge.host.port.requestMemorySnapshot([])}),
      tools:async()=>{throw Error('GAME_TURN_VIEWER_MEMORY_WRITE_DENIED');},onProbe:probe=>bridge.recordProbe(probe)});
  }
  async runDecision(decision) {
    if(this.busy||!this.enabled)return;
    this.busy=true;this.activeKind='decision';const started=Date.now(),sessionId='naimei-game-'+decision.id+'-'+(this.attempts.get(decision.id)?.count||0);
    this.attempts.set(decision.id,{count:(this.attempts.get(decision.id)?.count||0)+1,at:started});
    if(this.attempts.size>128)this.attempts.delete(this.attempts.keys().next().value);
    const turn={session_id:sessionId,decision_id:decision.id,context_id:decision.context_id,submitted:null,control_revision:this.controlRevision||0};
    this.activeDecisionTurn=turn;
    this.record('core_turn_started',{session_id:sessionId,decision_id:decision.id,context_id:decision.context_id,remaining_ms:decision.remaining_ms});
    try {
      const result=await this.generate({game_decision:decision,recent_naimei_game_decisions:this.recent.slice(-4)},turn,
        '以奶妹本人身份直接判断新鲜game_decision；结合context.route_progress中的持续目标、原生已访房间、跨房间跳过及失败结果，优先持续推进有实际收益的路线。回访不叫首次探索，不反复去刚放弃的资源分支。新道具直接查wiki，不重复刷新。用isaac_submit_plan仅提交offer_id和commentary：15至24字自然打算，不称已经完成；成功即结束。',Math.min(18000,Math.max(1000,decision.remaining_ms-500)));
      this.assertTurnCurrent(turn);
      requireValue(turn.submitted,'CORE_TURN_DID_NOT_SUBMIT_A_CHOICE',409);
      this.turns++;this.lastError=null;this.latencies.push(Date.now()-started);if(this.latencies.length>200)this.latencies.shift();
      const summary={decision_id:decision.id,...turn.submitted,text:result.text.slice(0,80)};
      this.recent.push(summary);if(this.recent.length>8)this.recent.shift();
      this.record('core_choice_completed',{session_id:sessionId,...summary,elapsed_ms:Date.now()-started});
      const event={event_id:'naimei-core-'+decision.id,type:'core_decision',...eventIdentity(decision.identity),
        observed_at:Date.now()/1000,expires_at:Date.now()/1000+30,facts:{decision_id:decision.id,...turn.submitted}};
      this.offerSpeech({text:summary.text,event});
    } catch(error) {
      if(turn.native_fault&&turn.control_revision===(this.controlRevision||0)&&this.enabled&&!this.closed){
        this.failures++;this.lastError=turn.stale_reason;this.control(false);
        this.record('core_failure_disarmed',{session_id:sessionId,decision_id:decision.id,code:this.lastError,
          elapsed_ms:Date.now()-started,turn_kind:'native_state_loss'});return;}
      if(this.turnCancelled(turn)){this.record('core_turn_cancelled',{session_id:sessionId,decision_id:decision.id,
        reason:turn.stale_reason||'control_cancelled',elapsed_ms:Date.now()-started});return;}
      this.failures++;this.lastError=error.code||'CORE_TURN_FAILED';this.record('core_turn_failed',{session_id:sessionId,decision_id:decision.id,code:this.lastError,elapsed_ms:Date.now()-started});
      if(!['CORE_DECISION_CHANGED','CORE_PLAN_CONTEXT_CHANGED','FRESH_CORE_DECISION_REQUIRED'].includes(this.lastError)
        ||(this.attempts.get(decision.id)?.count||0)>=2){this.control(false);this.record('core_failure_disarmed',{decision_id:decision.id});}}
    finally {if(this.activeDecisionTurn===turn)this.activeDecisionTurn=null;this.activeAbort=null;this.activeKind=null;this.busy=false;}
  }
  async runFact() {
    if(this.busy||!this.enabled)return;
    this.busy=true;this.activeKind='fact';this.lastFact=Date.now();let reservation;
    const turn={submitted:null,control_revision:this.controlRevision||0};
    try {
      reservation=await this.api(9534,'/narration/reserve',{});if(!reservation.event)return;
      requireValue(await this.current(reservation.event),'GAME_EVENT_EXPIRED',409);
      turn.session_id='naimei-fact-'+reservation.event.event_id;
      const result=await this.generate({game_event:reservation.event,recent_naimei_game_decisions:this.recent.slice(-4)},turn,
        '你是正在游玩的奶妹。game_event是刚刚核验的同房间真实观察，直接依据其中facts作自然反应或自言自语，不重复调用工具刷新，不作新决定。优先15至24字一句口语；使用刚才发生的事实，不推测原因，不把计划接受说成已成功，不提后台状态。',12000);
      this.assertTurnCurrent(turn);
      this.offerSpeech({text:result.text.slice(0,80),...reservation});reservation=null;
    } catch(error) {
      if(reservation?.nonce)await this.abandon(reservation);
      // New decisions and an operator disarm intentionally interrupt speech.
      // An actual model failure must not leave automatic gameplay armed.
      if(!this.turnCancelled(turn)&&!this.activeAbort?.signal.aborted&&error.code!=='GAME_EVENT_EXPIRED') {
        this.failures++;this.lastError=error.code||'CORE_FACT_FAILED';this.control(false);
        this.record('core_failure_disarmed',{code:this.lastError,turn_kind:'fact'});
      }
    }
    finally {this.activeAbort=null;this.activeKind=null;this.busy=false;}
  }
  offerSpeech(item) {
    if(!item.text?.trim()||this.closed){void this.abandon(item);return;}
    while(this.backlog.length>=2)void this.abandon(this.backlog.shift());
    this.backlog.push(item);
  }
  async abandon(item) {if(item?.nonce)await this.api(9534,'/narration/abandon',{nonce:item.nonce}).catch(()=>{});}
  async drain() {
    const bridge=this.bridge,broadcast=bridge.state.current();
    while(this.backlog.length&&!await this.current(this.backlog[0].event)){await this.abandon(this.backlog.shift());}
    if(!this.backlog.length||broadcast?.state!=='LIVE'||!bridge.state.authorityReady(broadcast.broadcast_id)||bridge.state.active()
      ||bridge.db.get("SELECT 1 FROM requests WHERE status='QUEUED'"))return;
    const item=this.backlog.shift();
    try {
      const request=bridge.state.accept(bridge.auth.resolve(),{text:item.text,mode:'echo',public_input:true,
        idempotency_key:'naimei-'+item.event.event_id,source:{collector:'issac-naimei-core',event_id:item.event.event_id,
          identity_quality:'native_observed_fact',nickname:'游戏状态'}});
      this.pending.set(request.request_id,item);
      if(item.nonce)await this.api(9534,'/narration/accepted',{nonce:item.nonce,request_id:request.request_id});
      this.record('core_speech_queued',{request_id:request.request_id,event_id:item.event.event_id});void bridge.tick();
    } catch {await this.abandon(item);}
  }
  async validate(request) {const item=this.pending.get(request.request_id);if(item)requireValue(await this.current(item.event),'GAME_EVENT_EXPIRED',409);}
  contextFor(request) {
    const item=this.pending.get(request.request_id);return item?canonical({partition_key:'ephemeral_game_not_viewer',game_event:item.event}):null;
  }
  async checkPending() {
    for(const [id,item] of this.pending) {
      const request=this.bridge.state.request(id);
      if(!request||['FAILED','CANCELLED','INTERRUPTED','EXPIRED'].includes(request.status)){this.pending.delete(id);await this.abandon(item);continue;}
      if(request.status!=='COMPLETED'&&!await this.current(item.event)){
        const expired=Date.now()/1000>=item.event.expires_at;
        this.record('core_speech_cancelled',{request_id:id,event_id:item.event.event_id,event_type:item.event.type,
          reason:expired?'expired':'native_context_changed',observed_at:item.event.observed_at,
          expires_at:item.event.expires_at});
        this.bridge.state.cancel(id,expired?'game_fact_expired':'game_fact_context_changed');
      }
    }
  }
  async completed(event) {
    const item=this.pending.get(event.request_id);if(!item)return;
    const utterance=this.bridge.db.get('SELECT * FROM utterances WHERE request_id=?',event.request_id);
    if(!utterance||utterance.contiguous_played_samples!==utterance.valid_sample_count||utterance.valid_sample_count<=0)return;
    if(item.nonce){const payload=this.bridge.db.payload(event.event_seq);await this.api(9534,'/narration/receipt',{request_id:event.request_id,
      receipt:{authority:'official_source',request_id:event.request_id,actual_pcm_samples:utterance.contiguous_played_samples,
        completed:true,lease_id:payload.lease_id}});}
    this.completedSpeech=(this.completedSpeech||0)+1;
    this.record('actual_core_speech_completed',{request_id:event.request_id,event_id:item.event.event_id,samples:utterance.contiguous_played_samples});
    this.pending.delete(event.request_id);
  }
  close() {this.closed=true;this.enabled=false;this.controlRevision=(this.controlRevision||0)+1;this.activeAbort?.abort();for(const item of this.backlog)void this.abandon(item);this.backlog=[];}
}
