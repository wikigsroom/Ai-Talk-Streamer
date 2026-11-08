import { readFileSync, appendFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { StreamBridge } from './server.mjs';
import { NaimeiGameCore } from './isaac-core.mjs';
import { OriginalIsaacChannel, digest, canonical } from './channel.mjs';
import { requireValue } from './state.mjs';

export class GameNarrator {
  constructor(bridge){this.bridge=bridge;this.root=bridge.root;this.pending=new Map();this.busy=false;this.closed=false;this.last=0;this.cursor=0;
    this.token=readFileSync(join(this.root,'private/issac/bridge-token.txt'),'utf8').trim();
    this.audit=join(this.root,'state/issac-stream/game-narrator.jsonl');mkdirSync(join(this.root,'state/issac-stream'),{recursive:true});}
  record(kind,value={}){appendFileSync(this.audit,canonical({at:Date.now(),kind,...value})+'\n');}
  async api(path,body){const response=await fetch('http://127.0.0.1:9534'+path,{method:body===undefined?'GET':'POST',
    headers:{'Content-Type':'application/json','X-Isaac-Token':this.token},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(2200)});
    if(!response.ok)throw Error('NATIVE_GAME_FACT_SERVICE_UNAVAILABLE');return response.json();}
  async current(event){
    if(this.closed||Date.now()/1000>=event.expires_at)return false;
    const response=await fetch('http://127.0.0.1:9532/query?topic=state',{signal:AbortSignal.timeout(1200)});
    if(!response.ok)return false;
    const value=await response.json(),identity=value.identity||value.data?.identity;
    return value.connected===true&&value.age_ms<1500&&identity?.bridge===event.bridge_instance
      &&value.data?.identity?.seed!==undefined&&digest({controller:identity.controller,seed:identity.seed,restart:identity.restart,bridge:identity.bridge})===event.run_id
      &&digest({room:identity.room,stage:identity.stage,stage_type:identity.stage_type,dimension:identity.dimension,visit:identity.visit})===event.room_id;
  }
  async validate(request){const item=this.pending.get(request.request_id);if(item)requireValue(await this.current(item.event),'GAME_EVENT_EXPIRED',409);}
  contextFor(request){const item=this.pending.get(request.request_id);if(!item)return null;
    return canonical({partition_key:'ephemeral_game_not_viewer',game_event:item.event,
      humanity_public_snapshot:this.bridge.host.port.requestMemorySnapshot([]),
      rules:'以下为当前原生观察事实，只可围绕facts自然陪玩解说。不要声称计划已成功，不推测未提供物品和原因，不创建观众记忆。'});}
  async tick(){
    if(this.closed||this.busy||Date.now()-this.last<4500||!this.bridge.ready)return;
    const bridge=this.bridge,broadcast=bridge.state.current();
    if(broadcast?.state!=='LIVE'||!bridge.state.authorityReady(broadcast.broadcast_id)||bridge.state.active()
      ||bridge.db.get("SELECT 1 FROM requests WHERE status='QUEUED'"))return;
    this.busy=true;let reservation;
    try{
      reservation=await this.api('/narration/reserve',{});if(!reservation.event)return;
      requireValue(await this.current(reservation.event),'GAME_EVENT_EXPIRED');
      const event=reservation.event;
      const request=bridge.state.accept(bridge.auth.resolve(),{text:'请依据随附的已验证游戏上下文，自然说一句简短陪玩解说。事件类型：'+event.type,
        mode:'chat',idempotency_key:'game-'+event.event_id,public_input:true,
        source:{collector:'issac-native-game',event_id:event.event_id,identity_quality:'native_observed_fact',nickname:'游戏状态'}});
      this.pending.set(request.request_id,reservation);
      await this.api('/narration/accepted',{nonce:reservation.nonce,request_id:request.request_id});
      this.last=Date.now();this.record('event_queued',{event_id:event.event_id,request_id:request.request_id});
      void bridge.tick();
    }catch{if(reservation?.nonce)await this.api('/narration/abandon',{nonce:reservation.nonce}).catch(()=>{});}
    finally{this.busy=false;}
  }
  async checkPending(){for(const [id,item] of this.pending){
    const request=this.bridge.state.request(id);
    if(!request||['FAILED','CANCELLED','INTERRUPTED','EXPIRED'].includes(request.status)){
      this.pending.delete(id);await this.api('/narration/abandon',{nonce:item.nonce}).catch(()=>{});continue;
    }
    if(request.status!=='COMPLETED'&&!await this.current(item.event))this.bridge.state.cancel(id,'game_fact_context_changed');
  }}
  async completed(event){const item=this.pending.get(event.request_id);if(!item)return;
    const payload=this.bridge.db.payload(event.event_seq);
    const utterance=this.bridge.db.get('SELECT * FROM utterances WHERE request_id=?',event.request_id);
    if(!utterance||utterance.contiguous_played_samples!==utterance.valid_sample_count||utterance.valid_sample_count<=0)return;
    await this.api('/narration/receipt',{request_id:event.request_id,receipt:{authority:'official_source',request_id:event.request_id,
      actual_pcm_samples:utterance.contiguous_played_samples,completed:true,lease_id:payload.lease_id}});
    this.pending.delete(event.request_id);this.record('actual_official_playback_completed',{event_id:item.event.event_id,request_id:event.request_id,samples:utterance.contiguous_played_samples});
  }
  close(){this.closed=true;}
}

export class IsaacBridge extends StreamBridge {
  constructor(root,runtime,options={}){
    super(root,runtime,{policyFile:'configs/issac/bridge-policy.json',avatarUrl:'http://127.0.0.1:8062',...options});
    this.channel=new OriginalIsaacChannel(root);
  }
  async start(){await super.start();this.gameNarrator=new NaimeiGameCore(this);this.host.gameplay=this.gameNarrator;
    this.gameListener=event=>{if(event.event_type==='playback.completed')void this.gameNarrator.completed(event).catch(()=>{});};this.db.on('event',this.gameListener);
    this.gameTimer=setInterval(()=>{void this.gameNarrator.tick();void this.gameNarrator.checkPending().catch(()=>{});void this.gameAudio().catch(()=>{});},500);
    return this;
  }
  async handle(req,res){
    const path=(req.url||'').split('?')[0];
    if(path==='/api/dsh/issac/core/status'&&req.method==='GET'){
      res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(this.gameNarrator.status()));return;
    }
    if(path==='/api/dsh/issac/core/control'&&req.method==='POST'){
      try{
        requireValue(!req.headers.origin&&digest(req.headers['x-isaac-token']||'')===digest(this.gameNarrator.token),'LOCAL_CORE_CONTROL_REQUIRED',403);
        const body=await this.body(req);requireValue(Object.keys(body).length===1&&typeof body.automatic==='boolean','BOOLEAN_CORE_CONTROL_REQUIRED');
        const result=this.gameNarrator.control(body.automatic);
        res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(result));
      }catch(error){res.writeHead(error.status||409,{'Content-Type':'application/json'});res.end(JSON.stringify({error:error.code||'CORE_CONTROL_REJECTED'}));}
      return;
    }
    if(path==='/api/dsh/issac/rehearsal/start'&&req.method==='POST'){
      try{
        if(!this.health().persona_injection_ready)await this.probe();
        const id=await this.platforms.ensureSession('bilibili',{resume:true});
        res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({broadcast_id:id,local_rehearsal:true,public_broadcast_started:false}));
      }catch(error){res.writeHead(409,{'Content-Type':'application/json'});res.end(JSON.stringify({error:error.code||'LOCAL_REHEARSAL_NOT_READY'}));}
      return;
    }
    if(req.method==='POST'&&/^\/api\/dsh\/platforms\/[^/]+\/(?:start|resume|stream|broadcast|confirm-live)$/.test(path)){
      res.writeHead(403,{'Content-Type':'application/json'});res.end('{"error":"PUBLIC_BROADCAST_NOT_AUTHORIZED"}');return;
    }
    return super.handle(req,res);
  }
  async gameAudio(){
    const p=this.platforms?.player,f=this.room?.player,b=this.state?.current(),a=this.room?.store.settings.audio,now=Date.now();
    if(!p||!f||!a||now-p.at>3000||now-f.at>2000||p.programme!=='issac'||p.consumer_id!==f.consumer_id
      ||b?.state!=='LIVE'||!this.state.authorityReady(b.broadcast_id)||this.state.lease(b.broadcast_id)?.consumer_id!==p.consumer_id)return;
    const speaking=f.speech_audible&&f.audio_state==='running'&&f.speaking_request_id===this.state.active()?.request_id;
    const gain=a.muted?0:a.game_volume*(speaking&&a.game_ducking?a.game_duck_level:1);
    await this.gameNarrator.api(9534,'/game-audio',{gain,ttl_ms:2200,attack_ms:a.attack_ms,release_ms:a.release_ms});
  }
  async restartHostForPrivacy(){this.gameNarrator?.control(false);await super.restartHostForPrivacy();if(this.gameNarrator)this.host.gameplay=this.gameNarrator;}
  async close(){clearInterval(this.stopTimer);clearInterval(this.gameTimer);this.gameNarrator?.close();if(this.gameListener)this.db?.off('event',this.gameListener);await super.close();}
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const root=resolve(process.argv[2]||'');const bridge=new IsaacBridge(root,'tools/dsh');
  const stopFile=process.env.ISSAC_STOP_FILE;
  let closing=false;
  const closeOwned=async()=>{
    if(closing)return;closing=true;
    const deadline=setTimeout(()=>{console.error(JSON.stringify({event:'issac_narrator_cleanup_deadline',clean:false}));process.exit(1);},25000);
    try{await bridge.close();clearTimeout(deadline);process.exitCode=0;}
    catch{clearTimeout(deadline);console.error(JSON.stringify({event:'issac_narrator_cleanup_failed',clean:false}));process.exitCode=1;}
  };
  const timer=stopFile?setInterval(()=>{if(existsSync(stopFile)){clearInterval(timer);void closeOwned();}},200):null;
  bridge.stopTimer=timer;
  process.on('SIGINT',()=>void closeOwned());process.on('SIGTERM',()=>void closeOwned());
  try{await bridge.start();}catch(error){clearInterval(timer);console.error(JSON.stringify({event:'issac_narrator_failed',code:error.code||'NARRATOR_START_REJECTED'}));await bridge.close();process.exitCode=1;}
}
