import { readFileSync, writeFileSync, appendFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, resolve, relative, isAbsolute } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { randomUUID, createHash } from 'node:crypto';
import { CANDIDATE_READ, CANDIDATE_ACTION } from './dsh-candidate-tools.mjs';
import { startDshViewer } from './dsh-viewer.mjs';

const CONFIG='configs/mc-dsh-candidate.private.json';
const hash=b=>createHash('sha256').update(b).digest('hex');
const textOf=r=>r?.content?.filter(x=>x.type==='text').map(x=>x.text).join('\n') || '';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function briefSchema(v){if(Array.isArray(v))return v.map(briefSchema);if(v&&typeof v==='object')return Object.fromEntries(Object.entries(v).map(([k,x])=>[k,k==='description'?String(x).slice(0,160):briefSchema(x)]));return v}
function check(ok,code){if(!ok)throw new Error(code)}
function under(root,name){const p=resolve(root,name),rel=relative(root,p);check(rel&&!rel.startsWith('..')&&!isAbsolute(rel),'MC_CANDIDATE_PATH');return p}
export function candidateEnabled(root){const p=join(root,CONFIG);return existsSync(p)&&JSON.parse(readFileSync(p,'utf8')).enabled===true}
// Keep the complete upstream result in the evidence ledger, not in every model
// turn. Maps/observations repeat their text in deeply nested value payloads.
export function candidateModelResult(result,after){
 const blocked=['blocked','failed','cancelled','timeout'].includes(result.value?.status);
 const failed=blocked||result.isError||/❌ 动作失败/.test(result.text);
 return {isError:!!failed,text:result.text.slice(0,1800),truncated:result.text.length>1800,
   current_state:{position:after.position,health:after.health,food:after.food,inventory:after.inventory},
   ...(blocked?{outcome:result.value.status}:{})};
}

// This adapter mounts the real upstream Cordis plugin. Its persistent session
// owns the only Mineflayer body; the existing DSH host owns all model requests.
export class DshMcCandidate {
 constructor(bridge){
  this.bridge=bridge;this.root=bridge.root;this.host=bridge.host;
  this.config=JSON.parse(readFileSync(join(this.root,CONFIG),'utf8'));
  this.mode='PAUSED';this.history=[];this.calls=[];this.visions=[];this.controller=new AbortController();
  this.generation=0;this.lastVisionAt=0;this.lastNarrationAt=0;
 }
 log(type,data={}){const row={at:new Date().toISOString(),type,...data};appendFileSync(join(this.output,'candidate-events.jsonl'),JSON.stringify(row)+'\n');return row}
 async mount(){
  const c=this.config;check(c.schema_version===1&&c.candidate==='dsh-mc-agent'&&c.server.username==='NAIMEI'&&c.server.auth==='offline'&&c.server.version==='1.21.1'&&c.automatic_start===false,'MC_CANDIDATE_CONFIG');
  check(c.commit==='a518f79e77e168aa5158dacc58e0c25d562a42b8','MC_CANDIDATE_COMMIT');
  this.package=under(this.root,c.package_relative_path);this.compat=under(this.root,c.compat_relative_path);this.extras=under(this.root,c.extras_relative_path);
  this.workspace=under(this.root,c.workspace_relative_path);this.stateDir=under(this.root,c.state_relative_path);this.output=join(this.root,'outputs/mc-validation/round-088');
  for(const p of [this.workspace,this.stateDir,this.output])mkdirSync(p,{recursive:true});
  const receipt=JSON.parse(readFileSync(join(this.root,'.setup/mc-candidate-088-installed.json'),'utf8'));
  check(receipt.commit===c.commit&&receipt.upstream_archive_sha256===c.upstream_archive_sha256&&receipt.compat_archive_sha256===c.compat_archive_sha256,'MC_CANDIDATE_SOURCE_RECEIPT');
  for(const [name,sha] of Object.entries(receipt.files))check(hash(readFileSync(under(this.root,name)))===sha,'MC_CANDIDATE_SOURCE_CHANGED');
  process.env.DSH_MC_AGENT_STATE_DIR=this.stateDir;
  process.env.DSH_MC_AGENT_MC_DEPS=this.extras;
  process.env.DSH_MC_AGENT_ACTION_SCHEDULER='enforce';
  process.env.STREAM_MC_COMPAT_CLIENT=join(this.compat,'client.js');
  const {AccountStore}=await import(pathToFileURL(join(this.package,'src/accounts.mjs')).href);
  const accounts=new AccountStore({dir:this.stateDir});accounts.load();
  check(!accounts.loadFailed,'MC_CANDIDATE_ACCOUNT_STORE');
  let account=accounts.data.accounts.find(a=>a.type==='offline'&&a.name==='NAIMEI');
  if(!account){const added=accounts.add({type:'offline',name:'NAIMEI'});account=accounts.data.accounts.find(a=>a.innerID===added.innerID)}
  this.account=account.innerID;
  const cfgFile=join(this.stateDir,'config.json');
  const previous=existsSync(cfgFile)?JSON.parse(readFileSync(cfgFile,'utf8')):{};
  writeFileSync(cfgFile,JSON.stringify({...previous,commandWhitelist:[],allowAllCommands:false,ensureMcPreset:false,
    mcModePresets:['streamer-minecraft-088'],mcPlusPresets:[],memoryScope:'session'},null,2));
  const ctx=this.host.ctx;this.routes=[];
  if(!ctx.get('webServer'))ctx.provide('webServer',{register:route=>{this.routes.push(route);return()=>{this.routes=this.routes.filter(x=>x!==route)}}});
  if(!ctx.get('attachments'))ctx.provide('attachments',{saveImage:async({data,mediaType})=>{
    check(mediaType==='image/png'&&data.byteLength<=4*1024*1024,'MC_CANDIDATE_IMAGE');
    this.latestPng=Buffer.from(data);this.latestPngAt=Date.now();
    return {id:'mc-088-'+hash(data),mediaType:'image/png'};
  }});
  const plugin=await import(pathToFileURL(join(this.package,'index.js')).href);
  this.fiber=await ctx.plugin(plugin,{mentions:[]});
  for(let i=0;i<100&&!ctx.tools.get('mc_observe');i++)await sleep(100);
  check(ctx.tools.get('mc_observe')&&ctx.get('streamMcCandidateRuntime088'),'MC_CANDIDATE_PLUGIN_NOT_MOUNTED');
  this.host.mcCandidateGlobalTools=ctx.tools.view().restrictableNames ? [...ctx.tools.view().restrictableNames].filter(x=>x.startsWith('mc_')) : [];
  this.handle=await ctx.agents.create({sessionId:'mc-candidate-088-'+randomUUID(),meta:{cwd:this.workspace,agentPreset:'streamer-minecraft-088'},
    setup:async agentCtx=>{await ctx.agentPresets.mount(agentCtx,'streamer-minecraft-088')}});
  this.agent=this.handle.agent;
  this.registry=ctx.get('streamMcCandidateRuntime088').registry;
  this.ready=true;this.timer=setInterval(()=>{void this.tick()},400);this.timer.unref();
  this.log('candidate.mounted',{commit:c.commit,compat_sha256:c.compat_archive_sha256,model:this.bridge.channel.publicInfo().model});
  return this;
 }
 get session(){return this.agent&&this.registry.peek(this.agent.id)}
 get core(){return this.session?.bot}
 get bot(){return this.core?.bot}
 recentActions(limit=4){return this.history.slice(-limit).map(row=>({at:row.at,name:row.name,args:row.args,elapsed_ms:row.elapsed_ms,
   isError:candidateModelResult(row.result,row.after).isError,result:row.result.text.slice(0,500),inventory_after:row.after.inventory}));}
 modelView(){
  const v=this.view(),vision=v.vision;
  return {candidate:v.candidate,mode:v.mode,connected:v.connected,world_session_id:v.world_session_id,
   username:v.username,position:v.position,health:v.health,food:v.food,gamemode:v.gamemode,
   inventory:v.inventory,held_item:v.held_item,goal:v.goal,actions:v.actions,
   vision:vision?{description:vision.description,captured_at:vision.captured_at,source:vision.source}:null};
 }
 view(){
  const b=this.bot,p=b?.entity?.position;
  return {candidate:'dsh-mc-agent',commit:this.config.commit,model:'gpt-6-luna',ready:!!this.ready,mode:this.mode,
    connected:!!this.core?.online,world_session_id:this.worldSession||null,username:b?.username||'NAIMEI',
    position:p?{x:p.x,y:p.y,z:p.z}:null,health:b?.health??null,food:b?.food??null,gamemode:b?.game?.gameMode??null,
    inventory:b?.inventory?.items().map(x=>({name:x.name,count:x.count}))||[],held_item:b?.heldItem?.name||null,
    goal:this.config.goal,actions:this.recentActions(3),vision:this.lastVision||null,
    viewer:{ready:!!this.viewerReady,port:this.config.viewer_port,source:'live_server_world_reconstruction',mod_textures_complete:false,...this.viewer?.status()},
    human_takeover:false,server_commands_enabled:false};
 }
 catalogue(){return [...CANDIDATE_READ,...CANDIDATE_ACTION].flatMap(name=>{
   const t=this.host.ctx.tools.get(name,this.agent);if(!t)return[];
   return [{name:'game_'+name,description:t.description.slice(0,400),argument_description:JSON.stringify(briefSchema(t.parameters))}];
 })}
 async execute(name,args,{signal,operator=false}={}){
  check(this.ready&&!this.stopping,'MC_CANDIDATE_NOT_READY');
  check(operator?['mc_connect','mc_disconnect'].includes(name):CANDIDATE_READ.has(name)||CANDIDATE_ACTION.has(name),'MC_CANDIDATE_TOOL_DENIED');
  if(CANDIDATE_ACTION.has(name))check(this.mode==='AUTO','MC_CANDIDATE_PAUSED');
  // Nested command/sequence tools are deliberately not admitted by the model.
  check(!['mc_sequence','mc_task'].includes(name),'MC_CANDIDATE_NESTED_ACTION_DENIED');
  const before=this.view(),at=Date.now();
  const combined=signal?AbortSignal.any([signal,this.controller.signal]):this.controller.signal;
  const r=await this.host.ctx.tools.execute({name,arguments:args,agent:this.agent,callId:'mc088-'+randomUUID(),signal:combined});
  const result={isError:!!r.isError,text:textOf(r),value:r.value??r.data??null};
  const after=this.view();
  const row=this.log('tool.result',{name,args,elapsed_ms:Date.now()-at,result,before:{position:before.position,health:before.health,inventory:before.inventory},after:{position:after.position,health:after.health,inventory:after.inventory}});
  if(CANDIDATE_ACTION.has(name)){this.history.push(row);this.history=this.history.slice(-40)}
  return candidateModelResult(result,after);
 }
 async connect(){
  check(this.mode==='PAUSED'&&!this.bot,'MC_CANDIDATE_ALREADY_CONNECTED');
  const {host,port,version}=this.config.server;
  const result=await this.execute('mc_connect',{host,port,version,account:this.account},{operator:true,signal:AbortSignal.timeout(45000)});
  check(!result.isError&&this.core?.online&&this.bot.username==='NAIMEI','MC_CANDIDATE_CONNECT_FAILED');
  this.core.autoReconnect=false;this.worldSession=randomUUID();
  this.session.watchdog?.disarm('直播决策由唯一宿主循环调度');
  this.initial=this.view();this.log('candidate.connected',{state:this.initial});
  await this.startViewer();return this.view();
 }
 async startViewer(){
  this.viewer=await startDshViewer(this.bot,this.extras,this.config.viewer_port,(type,data)=>this.log(type,data));
  this.viewerReady=true;this.log('viewer.started',{port:this.config.viewer_port,source:'live_server_world_reconstruction'});
 }
 async setMode(mode){
  check(['AUTO','PAUSED'].includes(mode),'MC_CANDIDATE_MODE');
  if(mode==='AUTO'){
   check(this.ready&&this.core?.online&&this.bot?.username==='NAIMEI'&&this.bot.game.gameMode==='survival','MC_CANDIDATE_SURVIVAL_REQUIRED');
   check(this.bridge.state.current()?.state==='LIVE','MC_CANDIDATE_LOCAL_PROGRAMME_REQUIRED');
  }
  this.generation++;this.mode=mode;
  if(mode==='PAUSED'){this.turnController?.abort();this.bot?.clearControlStates();this.bot?.pathfinder?.setGoal(null);try{this.bot?.stopDigging()}catch{}}
  this.log('candidate.mode',{mode,generation:this.generation});return this.view();
 }
 async observe(){
  const at=Date.now();this.lastVisionAt=at;
  await this.execute('mc_observe',{width:320,height:180,image:true,verbose:false},{signal:AbortSignal.timeout(14000)});
  check(this.latestPngAt>=at&&this.latestPng,'MC_CANDIDATE_FRESH_IMAGE_REQUIRED');
  const require=createRequire(join(this.extras,'package.json'));const jpeg=await require('sharp')(this.latestPng).jpeg({quality:90}).toBuffer();
  const result=await this.host.generate({purpose:'vision',snapshot:this.bridge.channel.snapshot(),image:jpeg,
    input:'这是dsh-mc-agent从当前服务器区块重建的第一人称图，未知模组方块可能使用替代外观。仅描述实际可见内容；库存、生命等以实时协议数据为准。',
    signal:AbortSignal.any([this.controller.signal,AbortSignal.timeout(12000)]),
    onCall:row=>{this.log('model.vision.attempt',row);return this.bridge.onCall({foreground:true,maxTokens:512})(row)}});
  this.lastVision={...result,captured_at:new Date(at).toISOString(),elapsed_ms:Date.now()-at,source:'dsh_mc_observe_reconstruction'};
  this.visions.push(this.lastVision);this.visions=this.visions.slice(-32);
  writeFileSync(join(this.output,'vision-'+String(this.visions.length).padStart(2,'0')+'.jpg'),jpeg);
  this.log('vision.result',this.lastVision);
 }
 async plan(){
  const generation=this.generation;this.turnController=new AbortController();
  const result=await this.host.generate({purpose:'game_plan',sessionId:'mc088-plan-'+randomUUID(),snapshot:this.bridge.channel.snapshot(),
    input:'自主推进接下来的一个生存动作。查询需要的信息后尽快行动，别只反复看状态。若采木，要真实捡到掉落物再合成。',
    context:JSON.stringify({candidate_game:{...this.modelView(),actions:undefined},recent_actions:this.recentActions(4),goal:this.config.goal,
      constraints:{ordinary_survival:true,no_server_commands:true,no_human_takeover:true,stay_within_48_blocks_of_start:this.initial.position}}),
    signal:AbortSignal.any([this.controller.signal,this.turnController.signal,AbortSignal.timeout(35000)]),
    toolCatalogue:this.catalogue().filter(x=>!['game_mc_task','game_mc_sequence'].includes(x.name)),
    tools:async(name,args,{signal})=>{check(generation===this.generation&&this.mode==='AUTO','MC_CANDIDATE_STALE_PLAN');return this.execute(name.replace(/^game_/,''),args,{signal})},
    onCall:row=>{this.log('model.plan.attempt',row);return this.bridge.onCall({foreground:true,maxTokens:this.bridge.policy.conversation.max_output_tokens})(row)}});
  this.log('model.plan.completed',{steps:result.steps,calls:result.calls,text:result.text});
 }
 narrate(){
  const now=Date.now();if(now-this.lastNarrationAt<14000||this.bridge.state.active()||this.bridge.state.current()?.state!=='LIVE')return;
  this.lastNarrationAt=now;
  const r=this.bridge.state.accept(this.bridge.auth.resolve(),{mode:'chat',public_input:false,idempotency_key:'mc088-narration-'+randomUUID(),
    text:'这是主播主动开口，不是观众留言。结合candidate_game当前真实状态和最近一个动作，自然说一两句自己的发现、进展、失误或下一步想法。每句有具体游戏内容，不报后台、测试、工具名或模型名，不编观众和收获，不把计划说成完成。避免连续重复上一句；一到两句，最多65个汉字。'});
  this.log('narration.request',{request_id:r.request_id});void this.bridge.tick();
 }
 async tick(){
  if(this.busy||this.mode!=='AUTO'||this.stopping)return;
  this.busy=true;
  try{
   if(!this.core?.online){await this.setMode('PAUSED');return}
   if(Date.now()-this.lastVisionAt>=20000)await this.observe();
   if(this.mode==='AUTO')await this.plan();
   this.narrate();
  }catch(e){this.log('candidate.iteration_failed',{code:e.code||e.message});this.lastError=e.code||e.message;await sleep(800)}
  finally{this.busy=false;if(this.mode==='AUTO')this.narrate()}
 }
 async stop(){
  if(this.stopping)return;this.stopping=true;clearInterval(this.timer);this.mode='PAUSED';this.generation++;
  this.controller.abort();this.turnController?.abort();this.bot?.clearControlStates();this.bot?.pathfinder?.setGoal(null);
  for(let i=0;i<160&&this.busy;i++)await sleep(100);
  check(!this.busy,'MC_CANDIDATE_DRAIN_TIMEOUT');
  const last=this.view();await this.viewer?.close();await this.core?.disconnect('用户要求的样片会话结束');
  await this.handle?.dispose();await this.fiber?.dispose?.();this.ready=false;this.viewerReady=false;this.log('candidate.closed',{last});
 }
 async handleHttp(req,res,url,send,body){
  if(req.method==='GET'&&url.pathname.endsWith('/status'))return send(this.view());
  if(req.method==='GET'&&url.pathname.endsWith('/evidence'))return send({state:this.view(),initial:this.initial||null,visions:this.visions,history:this.history});
  if(req.method==='POST'&&url.pathname.endsWith('/connect'))return send(await this.connect());
  if(req.method==='POST'&&url.pathname.endsWith('/observe')){check(this.mode==='PAUSED'&&!this.busy,'MC_CANDIDATE_OBSERVATION_BUSY');await this.observe();return send(this.view())}
  if(req.method==='POST'&&url.pathname.endsWith('/control'))return send(await this.setMode(body.mode));
  return send({error:'MC_CANDIDATE_NOT_FOUND'},404);
 }
}
