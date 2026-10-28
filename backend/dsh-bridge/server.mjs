import { createServer } from 'node:http';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { StateStore, utc, id } from '../memory/store.mjs';
import { loadPolicy, inside } from './policy.mjs';
import { ChannelConfig, canonical, digest } from './channel.mjs';
import { DshHost } from './host.mjs';
import { initialPersona } from './persona.mjs';
import { StreamState, StreamError, requireValue } from './state.mjs';
import { Auth } from './auth.mjs';
import { MemoryService } from '../memory/service.mjs';
import { MaintenanceScheduler } from '../memory/scheduler.mjs';
import { MemoryAdministration, purgeSessionBodies } from '../memory/administration.mjs';
import { memoryPage } from '../memory/query.mjs';
import { EventSubscriptions } from './events.mjs';
import { PlatformManager } from '../platforms/manager.mjs';
import { RoomManager } from '../room/manager.mjs';

export class StreamBridge {
  constructor(root, runtime, { policyFile, avatarUrl = 'http://127.0.0.1:8010' } = {}) {
    this.root=resolve(root);this.runtime=inside(this.root,runtime);this.policy=loadPolicy(this.root,policyFile);this.avatarUrl=avatarUrl;
    this.channel=new ChannelConfig(this.root);this.controllers=new Map();this.closed=false;this.probes=[];this.mediaHealth={};this.ready=false;this.mediaChain=Promise.resolve();
  }
  async start() {
    this.db=new StateStore(inside(this.root,join(this.policy.deployment.state_relative_path,'stream.sqlite3')));
    this.db.on('owner-lost',()=>{this.ready=false;void this.close();});
    this.db.on('storage-fault',()=>{this.ready=false;this.scheduler?.close();for(const controller of this.controllers.values())controller.abort();});
    const initial=initialPersona(this.root);
    const saved=this.db.get("SELECT * FROM personas WHERE publication_state='PUBLISHED' ORDER BY published_at DESC LIMIT 1");
    const persona=saved?{document:JSON.parse(saved.document_json),version:saved.persona_version}:initial;
    this.state=new StreamState(this.db,this.policy,persona.version);this.auth=new Auth(this.root,this.db,this.state);
    this.events=new EventSubscriptions(this.db,this.state,this.auth);
    this.host=await new DshHost(this.root,this.runtime,this.policy).start();await this.host.publishCharacter(persona.document,persona.version);
    this.db.tx(()=>this.db.run("INSERT INTO personas VALUES (?,?,?,'PUBLISHED',?,?) ON CONFLICT(persona_version) DO UPDATE SET publication_state='PUBLISHED',published_at=excluded.published_at",persona.version,canonical(persona.document),digest(persona.document),utc(this.db.now()),utc(this.db.now())));
    this.memory=new MemoryService(this.db,this.state,this.policy,this.host.port);
    this.scheduler=new MaintenanceScheduler(this.db,this.state,this.memory,this.policy,options=>this.maintenanceModel(options));
    this.db.on('event',event=>{if(['broadcast.created','broadcast.live'].includes(event.event_type))this.scheduler.runningAbort?.abort();});
    this.administration=new MemoryAdministration(this.root,this.db,this.state,this.memory,this.host,async()=>this.restartHostForPrivacy());
    if(this.db.get("SELECT 1 FROM runtime_meta WHERE key='privacy_redaction_pending'")) {
      await this.restartHostForPrivacy();this.db.tx(()=>this.db.run("DELETE FROM runtime_meta WHERE key='privacy_redaction_pending'"));
    }
    this.state.on('cancel',barrier=>{
      this.controllers.get(barrier.request_id)?.abort();
      void this.mediaCommand('cancel',barrier).catch(()=>{});
    });
    await this.memory.project();
    this.room = new RoomManager(this.root, this).start();
    this.platforms = new PlatformManager(this.root, this).start();
    this.server=createServer((req,res)=>{void this.handle(req,res);});
    await new Promise((resolve,reject)=>{this.server.once('error',reject);this.server.listen(this.policy.deployment.bridge_port,this.policy.deployment.bridge_host,resolve);});
    this.managementServer=createServer((_req,res)=>{res.writeHead(302,{Location:this.avatarUrl+'/memory','Cache-Control':'no-store'});res.end();});
    await new Promise((resolve,reject)=>{this.managementServer.once('error',reject);this.managementServer.listen(this.policy.deployment.management_port,this.policy.deployment.management_host,resolve);});
    this.timer=setInterval(()=>{void this.tick();},1000);this.timer.unref();
    this.maintenanceTimer=setInterval(()=>{void this.scheduler.tick().catch(()=>{});void this.memory.project().catch(()=>{});},this.policy.maintenance.poll_interval_ms);this.maintenanceTimer.unref();
    this.ready=true;
    console.log(JSON.stringify({event:'bridge.ready',port:this.policy.deployment.bridge_port,model:this.channel.publicInfo().model,channel_source:'studio_channel_env'}));
    return this;
  }
  async restartHostForPrivacy() {
    this.ready=false;
    for(const controller of this.controllers.values())controller.abort();
    for(let attempt=0;attempt<100&&this.host.active.size;attempt++)await new Promise(resolve=>setTimeout(resolve,50));
    const ids=(await this.host.ctx.sessionPersistence.list()).map(row=>row.header.id);
    await this.host.close();
    purgeSessionBodies(this.root,inside(this.root,this.policy.deployment.dsh_home_relative_path),ids);
    this.host=await new DshHost(this.root,this.runtime,this.policy).start();this.memory.port=this.host.port;this.administration.host=this.host;
    this.ready=true;
  }
  async mediaCommand(action,body) {
    const command=this.mediaChain.then(async()=>{
      if(action==='speak')requireValue(this.state.matches(body.request_id,body.runtime_epoch,body.generation),'STALE_GENERATION');
      const response=await fetch(this.avatarUrl+'/internal/dsh/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:canonical(body),signal:AbortSignal.timeout(8000)});
      requireValue(response.ok,'MEDIA_COMMAND_FAILED',503);return response.json();
    });
    this.mediaChain=command.catch(()=>{});return command;
  }
  async refreshMedia() {
    if(this.mediaCheckedAt&&Date.now()-this.mediaCheckedAt<3000)return this.mediaHealth;
    this.mediaCheckedAt=Date.now();
    try { const response=await fetch(this.avatarUrl+'/api/studio/status',{signal:AbortSignal.timeout(2500)});const health=await response.json();this.mediaHealth={tts_ready:!!health.tts_ready,avatar_ready:!!health.avatar_ready,viewers:health.viewers||0}; }
    catch {this.mediaHealth={tts_ready:false,avatar_ready:false,viewers:0};}
    return this.mediaHealth;
  }
  health() {
    const projectionLag=this.db.get("SELECT COUNT(*) n FROM mirror_outbox WHERE state NOT IN ('APPLIED','SUPERSEDED')").n;
    return {process_alive:true,state_store_ready:!this.db.faulted,dsh_ready:this.ready&&this.host.ready,
      persona_injection_ready:!!this.compatibility?.passed&&this.compatibility.provider_revision===this.channel.publicInfo().revision,memory_ready:!this.administration?.locked,
      projection_synced:projectionLag===0&&this.host.port.injectionEnabled,projection_lag:projectionLag,
      ...this.mediaHealth,authority_ready:this.state.current()?this.state.authorityReady(this.state.current().broadcast_id):false,
      channel:this.channel.publicInfo(),persona_version:this.state.personaVersion,node:process.version,
      native_humanity_tools:false,versions:{dsh:'0.2.0-rc.2',humanity:'0.1.17',connector:'stream-humanity-v1'},
      rss_bytes:process.memoryUsage().rss};
  }
  onCall({requestId=null,jobId=null,job=null,foreground=true,maxTokens=256}) {
    return call=>{
      if(call.phase==='reserve'){if(job)this.scheduler.assertLease(job);return this.scheduler.reserveModel({requestId,jobId,inputHash:call.input_sha256,providerRevision:call.provider_revision,maxTokens,foreground});}
      if(call.phase==='sent')this.db.tx(()=>this.db.run("UPDATE model_attempts SET status='SENT' WHERE attempt_id=?",call.attempt));
      if(['settle','failed'].includes(call.phase))this.scheduler.settleModel(call.attempt,call.usage,call.sent,call.phase==='failed');
    };
  }
  recordProbe(probe) {
    this.probes.push(probe);if(this.probes.length>30)this.probes.shift();
    const folder=inside(this.root,'outputs/dsh-humanity');mkdirSync(folder,{recursive:true});
    writeFileSync(join(folder,'latest-prompt-probes.json'),JSON.stringify(this.probes,null,2));
  }
  async probe() {
    requireValue(this.ready&&!this.administration.locked,'BRIDGE_NOT_READY',503);
    requireValue(!this.probeRunning,'PROBE_IN_PROGRESS');
    const snapshot=this.channel.snapshot(),sessionId=id('compat'),started=Date.now();let recalls=0;
    this.probeRunning=true;
    const receipt={passed:false,model:snapshot.model,protocol:snapshot.protocol,provider_revision:snapshot.revision,checked_at:utc(started)};
    this.compatibility=receipt;
    try {
      const result=await this.host.generate({sessionId,snapshot,input:'请先调用 stream_memory_recall 查询记忆，然后用一句话介绍你的姓名和虚拟角色身份。',
        signal:AbortSignal.timeout(this.policy.conversation.model_timeout_ms),tools:async(name)=>{if(name==='stream_memory_recall')recalls++;return {public:[],viewer:[]};},
        onProbe:probe=>this.recordProbe(probe),onCall:this.onCall({})});
      const prompt=this.probes.findLast(probe=>probe.session_id===sessionId);
      Object.assign(receipt,{passed:recalls>0&&!!prompt?.has_persona,tool_calls:recalls,result:result.text,tools:prompt?.tools});
      return receipt;
    } catch(error) {Object.assign(receipt,{error:error.code||'INTERNAL_ERROR',retryable:!!error.retryable});throw error;}
    finally {this.probeRunning=false;receipt.elapsed_ms=Date.now()-started;writeFileSync(inside(this.root,'outputs/dsh-humanity/channel-compatibility.json'),canonical(receipt));}
  }
  async maintenanceModel({job,chunk,schema,signal}) {
    requireValue(this.health().persona_injection_ready,'CHANNEL_COMPATIBILITY_REQUIRED',503);
    const snapshot=this.channel.snapshot();let extraction;
    const sessionId=id('maint');
    await this.host.generate({sessionId,snapshot,input:canonical({task:'按照给定schema整理当前分区。引用必须是完整来源中的连续文本；不要猜测、改写人物身份或跨观众归属。只有persistent_candidate格式合法。只读重叠不能作为唯一新增证据。通过 stream_maintenance_result 工具提交。',partition_key:job.partition_key,schema,sources:chunk.sources}),
      maintenance:true,maxTokens:this.policy.maintenance.max_output_tokens_per_call,signal,
      tools:async(name,value)=>{requireValue(name==='stream_maintenance_result'&&!extraction,'MAINTENANCE_RESULT_DUPLICATE');extraction=value;return {received:true};},
      onCall:this.onCall({jobId:job.job_id,job,foreground:false,maxTokens:this.policy.maintenance.max_output_tokens_per_call})});
    requireValue(extraction,'MAINTENANCE_STRUCTURED_RESULT_MISSING',422);return extraction;
  }
  async processRequest(request) {
    const controller=new AbortController();this.controllers.set(request.request_id,controller);
    const signal=AbortSignal.any([controller.signal,AbortSignal.timeout(this.policy.conversation.model_timeout_ms)]);
    try {
      const snapshot=this.channel.snapshot(),context=this.memory.context(request,snapshot),input=this.state.input(request).text;
      let speech=input;
      if(request.mode==='chat') {
        const result=await this.host.generate({sessionId:request.dsh_session_id,snapshot,input,context,signal,
          tools:async(name,value)=>name==='stream_memory_recall'?this.memory.recall(request.viewer_id||'public',typeof value.query==='string'?value.query:input):this.memory.propose(request,value),
          onCall:this.onCall({requestId:request.request_id}),onProbe:probe=>this.recordProbe(probe)});
        speech=result.text;
      }
      requireValue(!controller.signal.aborted&&this.state.matches(request.request_id,request.runtime_epoch,request.generation),'STALE_GENERATION');
      if(speech.length>this.policy.conversation.final_speech_max_chars) {
        const limit=this.policy.conversation.final_speech_max_chars,head=speech.slice(0,limit),stop=Math.max(head.lastIndexOf('。'),head.lastIndexOf('！'),head.lastIndexOf('？'));
        speech=stop>=limit/2?head.slice(0,stop+1):head;
      }
      const utterance=this.state.textReady(request.request_id,speech,request.runtime_epoch,request.generation);
      await this.mediaCommand('speak',utterance);
    } catch(error) {
      if(this.state.matches(request.request_id,request.runtime_epoch,request.generation))this.state.fail(request.request_id,controller.signal.aborted?'cancelled':error.code||'generation_or_media_failed');
    } finally {this.controllers.delete(request.request_id);}
  }
  async tick() {
    if(this.closed||!this.ready||this.administration.locked)return;
    this.state.tick();
    const active=this.state.active();
    if(active?.status==='SYNTHESIZING') {
      const event=this.db.get("SELECT received_at FROM stream_events WHERE request_id=? AND event_type='utterance.text_ready'",active.request_id);
      if(event&&this.db.now()-Date.parse(event.received_at)>this.policy.conversation.tts_timeout_ms)this.state.fail(active.request_id,'TTS_TIMEOUT');
    }
    const request=this.state.activate();if(request)void this.processRequest(request);
  }
  async publishPersona(principal,body) {
    requireValue(!this.administration.locked,'MEMORY_ADMINISTRATION_BUSY',409);
    const current=this.host.port.readPersona();requireValue(body.expected_version===this.state.personaVersion,'PERSONA_VERSION_CONFLICT');
    requireValue(canonical(body.document?.identityCard)===canonical(current.document.identityCard),'IDENTITY_CARD_IMMUTABLE');
    const version='female-a-'+digest(body.document).slice(0,16),now=utc(this.db.now());
    this.db.tx(()=>this.db.run("INSERT OR IGNORE INTO personas VALUES (?,?,?,'PENDING',?,NULL)",version,canonical(body.document),digest(body.document),now));
    await this.host.publishCharacter(body.document,version);
    this.db.tx(()=>{this.db.run("UPDATE personas SET publication_state='PUBLISHED',published_at=? WHERE persona_version=?",utc(this.db.now()),version);this.db.event(this.state.scope({}, {actor_kind:'operator',actor_id:principal.principal_id}),'persona.published',{persona_version:version});});
    this.state.personaVersion=version;return {persona_version:version};
  }
  publicStatus(principal) {
    const value=this.state.status();
    return {...value,health:this.health()};
  }
  async body(req) {
    let length=0;const chunks=[];
    for await(const chunk of req){length+=chunk.length;requireValue(length<=131072,'BODY_TOO_LARGE',413);chunks.push(chunk);}
    try{return chunks.length?JSON.parse(Buffer.concat(chunks).toString('utf8')):{};}catch{throw new StreamError('JSON_INVALID',400);}
  }
  async handle(req,res) {
    const send=(data,status=200,headers={})=>{if(res.writableEnded)return;res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type, Authorization, Last-Event-ID',...headers});res.end(status===204?undefined:JSON.stringify(data));};
    try {
      const url=new URL(req.url,'http://127.0.0.1'),path=url.pathname;
      if(req.method==='OPTIONS')return send({},204);
      if(path.startsWith('/api/dsh/room/'))return await this.room.handle(req,res,url,send);
      if(path.startsWith('/api/dsh/platforms'))return await this.platforms.handle(req,res,url,send);
      if(path==='/health'&&req.method==='GET'){await this.refreshMedia();return send(this.health());}
      if(path==='/api/dsh/session'&&req.method==='POST')return send({...this.auth.anonymous(),access_mode:'open',authentication_required:false,studio:{auto_start:true}});
      if(path==='/api/dsh/login'&&req.method==='POST')return send({...this.auth.login(),access_mode:'open',authentication_required:false});
      if(path==='/api/dsh/logout'&&req.method==='POST')return send({ok:true,authentication_required:false});
      const principal=this.auth.resolve(req.headers);
      if(path==='/api/dsh/events'&&req.method==='GET')return this.events.subscribe(req,res,this.auth.require(req.headers),url.searchParams);
      if(path==='/api/dsh/whoami'&&req.method==='GET')return send(this.auth.require(req.headers));
      if(path==='/api/dsh/status'&&req.method==='GET'){await this.refreshMedia();return send(this.publicStatus(principal));}
      if(path==='/api/dsh/requests'&&req.method==='POST'){const p=this.auth.resolve();requireValue(this.ready&&!this.administration.locked,'BRIDGE_NOT_READY',503);const body=await this.body(req);if((body.mode||'chat')==='chat')requireValue(this.health().persona_injection_ready,'CHANNEL_COMPATIBILITY_REQUIRED',503);const result=this.state.accept(p,body);void this.tick();return send(result,result.duplicate?200:202);}
      if(path.startsWith('/api/dsh/requests/')&&req.method==='GET'){const row=this.state.request(path.split('/').at(-1));requireValue(row,'REQUEST_NOT_FOUND',404);return send(row);}
      if(path.startsWith('/internal/')) {
        const body=await this.body(req);
        if(path==='/internal/obs-session')return send(this.auth.playbackCredential());
        if(path==='/internal/audio-ready')return send(this.state.audioReady(body));
        if(path==='/internal/media-map')return send(this.state.mediaMap(body));
        if(path==='/internal/failed'){this.state.fail(body.request_id,'media_or_tts_failed');return send({ok:true});}
        throw new StreamError('NOT_FOUND',404);
      }
      const p=this.auth.resolve(),body=req.method==='GET'?{}:await this.body(req);
      if(req.method==='POST'&&['/api/dsh/broadcast/ready','/api/dsh/broadcast/pause','/api/dsh/broadcast/end'].includes(path))requireValue(typeof body.broadcast_id==='string'&&Number.isSafeInteger(body.expected_revision),'BROADCAST_CONTROL_REVISION_REQUIRED',400);
      if(path==='/api/dsh/probe'&&req.method==='POST')return send(await this.probe());
      if(path==='/api/dsh/broadcast/start'&&req.method==='POST')return send(this.state.createBroadcast(p));
      if(path==='/api/dsh/broadcast/ready'&&req.method==='POST'){const media=await this.refreshMedia();requireValue(['echo','chat'].includes(body.mode||'chat'),'BROADCAST_MODE');const result=this.state.readyBroadcast(body.broadcast_id,this.host.ready&&media.tts_ready&&media.avatar_ready&&(body.mode==='echo'||this.health().persona_injection_ready),body);this.db.tx(()=>this.db.run('INSERT INTO runtime_meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json','broadcast_mode:'+body.broadcast_id,canonical({mode:body.mode||'chat'})));return send({...result,mode:body.mode||'chat'});}
      if(path==='/api/dsh/broadcast/pause'&&req.method==='POST')return send(this.state.pause(p,body));
      if(path==='/api/dsh/broadcast/end'&&req.method==='POST'){const value=this.state.end(p,body);void this.tick();return send(value);}
      if(path==='/api/dsh/cancel'&&req.method==='POST')return send(this.state.cancel(body.request_id||this.state.active()?.request_id));
      if(path==='/api/dsh/playback/claim'&&req.method==='POST')return send(this.state.claimAuthority(p,body.broadcast_id,body.consumer_id,!!body.replace));
      if(path==='/api/dsh/playback/heartbeat'&&req.method==='POST')return send(this.state.heartbeat(body.lease_id,body.consumer_id));
      if(path==='/api/dsh/playback/receipt'&&req.method==='POST')return send(this.state.receipt(p,body));
      if(path==='/api/dsh/playback/cancel-ack'&&req.method==='POST')return send(this.state.cancelAck(p,body));
      if(path==='/api/dsh/persona'&&req.method==='GET')return send(this.host.port.readPersona());
      if(path==='/api/dsh/persona'&&req.method==='POST')return send(await this.publishPersona(p,body));
      if(path==='/api/dsh/memory'&&req.method==='GET')return send(memoryPage(this.db,this.state,url.searchParams));
      if(path==='/api/dsh/memory/source'&&req.method==='GET'){const memoryId=url.searchParams.get('memory_id');return send({revisions:this.db.all('SELECT * FROM memory_revisions WHERE memory_id=? ORDER BY revision',memoryId),sources:this.db.all('SELECT * FROM memory_sources WHERE memory_id=? ORDER BY memory_revision,event_seq',memoryId)});}
      if(path==='/api/dsh/memory/correct'&&req.method==='POST'){const value=this.administration.correct(p,body);void this.memory.project();return send(value);}
      if(path==='/api/dsh/memory/archive'&&req.method==='POST'){const value=this.administration.archive(p,body);void this.memory.project();return send(value);}
      if(path==='/api/dsh/memory/merge'&&req.method==='POST'){const value=this.administration.merge(p,body);void this.memory.project();return send(value);}
      if(path==='/api/dsh/memory/undo'&&req.method==='POST'){const value=this.administration.undo(p,body);void this.memory.project();return send(value);}
      if(path==='/api/dsh/memory/delete'&&req.method==='POST')return send(await this.administration.delete(p,body));
      if(path==='/api/dsh/viewers'&&req.method==='POST')return send(this.auth.invite(body.label));
      if(path==='/api/dsh/jobs'&&req.method==='GET')return send({jobs:this.db.all('SELECT j.*,r.statistics_json,r.model_call_count FROM compaction_jobs j JOIN job_runtime r USING(job_id) ORDER BY created_at DESC LIMIT 100'),attempts:this.db.all('SELECT * FROM model_attempts ORDER BY created_at DESC LIMIT 100'),occurrences:this.db.all('SELECT * FROM schedule_occurrences ORDER BY created_at DESC LIMIT 20')});
      if(path==='/api/dsh/jobs/rebuild'&&req.method==='POST')return send(this.administration.rebuild(p,body),202);
      if(path==='/api/dsh/broadcasts'&&req.method==='GET')return send({broadcasts:this.db.all("SELECT broadcast_id,state,revision,source_revision,ended_event_seq,consolidation_not_before,created_at,ended_at,(SELECT MIN(event_seq) FROM stream_events e WHERE e.broadcast_id=b.broadcast_id) source_start_seq FROM broadcasts b WHERE character_id=? AND room_id=? ORDER BY created_at DESC LIMIT 50",...this.state.characterRoom)});
      if(path==='/api/dsh/jobs/resume'&&req.method==='POST'){this.db.tx(()=>{const job=this.db.get('SELECT * FROM compaction_jobs WHERE job_id=?',body.job_id);requireValue(job&&job.state!=='RUNNING'&&job.state!=='COMPLETED','JOB_NOT_RESUMABLE');requireValue(job.source_revision===this.db.get('SELECT source_revision FROM broadcasts WHERE broadcast_id=?',job.broadcast_id).source_revision,'JOB_SOURCE_CHANGED');this.db.run("UPDATE compaction_jobs SET state='PENDING',not_before=?,reason=NULL WHERE job_id=?",utc(this.db.now()),job.job_id);});return send({ok:true});}
      if(path==='/api/dsh/jobs/cancel'&&req.method==='POST'){this.db.tx(()=>this.db.run("UPDATE compaction_jobs SET state='CANCELLED',lease_generation=lease_generation+1,owner_id=NULL,reason='operator_cancel' WHERE job_id=? AND state!='COMPLETED'",body.job_id));return send({ok:true});}
      if(path==='/api/dsh/backup'&&req.method==='POST')return send(await this.administration.backup());
      if(path==='/api/dsh/shutdown'&&req.method==='POST'){requireValue(!this.state.current(),'SHUTDOWN_REQUIRES_OFFAIR');send({stopping:true});setTimeout(()=>{void this.close();},20);return;}
      if(path==='/api/dsh/probes'&&req.method==='GET')return send({probes:this.probes});
      throw new StreamError('NOT_FOUND',404);
    } catch(error) {
      if(!res.headersSent)send({error:error.code||'INTERNAL_ERROR',...(typeof error.retryable==='boolean'?{retryable:error.retryable}:{})},error.status||500);else res.end();
      if(!error.status)console.error(JSON.stringify({event:'bridge.error',code:error.code||'INTERNAL_ERROR'}));
    }
  }
  async close() {
    if(this.closed)return;this.closed=true;this.ready=false;clearInterval(this.timer);clearInterval(this.maintenanceTimer);this.scheduler?.close();
    this.events?.close();
    await this.room?.close();
    await this.platforms?.close();
    for(const controller of this.controllers.values())controller.abort();
    if(this.state?.active())this.state.cancel(this.state.active().request_id,'bridge_shutdown');
    await this.host?.close();await new Promise(resolve=>this.server?this.server.close(resolve):resolve());await new Promise(resolve=>this.managementServer?this.managementServer.close(resolve):resolve());this.db?.close();
  }
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const root=resolve(process.argv[2]||''),runtime=resolve(root,process.argv[3]||'tools/dsh');
  const bridge=new StreamBridge(root,runtime,{policyFile:process.argv[4]||undefined});
  process.on('SIGTERM',()=>{void bridge.close();});process.on('SIGINT',()=>{void bridge.close();});
  try{await bridge.start();}catch(error){console.error(JSON.stringify({event:'bridge.start_failed',code:error.code||error.message}));await bridge.close();process.exitCode=1;}
}
