import { createServer } from 'node:http';
import { readFileSync, mkdirSync, appendFileSync, writeFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { randomUUID, createHash } from 'node:crypto';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { createUserMessage } from '@deepseek-ai/dsh-llm';
import { installModelSelection } from '@deepseek-ai/dsh-agent';
import { DecisionBinding } from './decision_binding.mjs';
import { completePrompt } from './stream-policy.mjs';

export const name = 'isaac-strategy';
export const inject = ['agents', 'agentLoop', 'tools', 'systemPrompt', 'sessions'];
export function apply(ctx, config = {}) {
  const endpoint = config.endpoint ?? 'http://127.0.0.1:9532';
  if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(endpoint)) throw new Error('Isaac bridge must use IPv4 loopback');
  const token = process.env.ISAAC_BRIDGE_TOKEN;
  if (!token) throw new Error('ISAAC_BRIDGE_TOKEN required');
  const originalInstructions = readFileSync(fileURLToPath(new URL('./instructions.md', import.meta.url)), 'utf8');
  const prompt = completePrompt(process.env.ISAAC_PROJECT_ROOT, originalInstructions);
  const instructions = prompt.text;
  const provider = config.provider ?? 'isaac-local';
  const model = config.model;
  if(typeof model!=='string'||!model.trim())throw Error('ISAAC_LOCAL_MODEL_ID_REQUIRED');
  const logs = config.logs;
  const pluginFiles=['package.json','index.mjs','decision_binding.mjs','stream-policy.mjs','instructions.md','cordis.patch.yml','README.md'];
  const pluginReceipt={version:'0.1.1',files:pluginFiles.map(name=>({name,sha256:createHash('sha256').update(readFileSync(new URL(name,import.meta.url))).digest('hex')}))};
  if (logs) mkdirSync(logs, {recursive: true});
  const metrics = {ready: false, dshVersion: '0.2.2-rc.1', provider, model, prompt:prompt.receipt,plugin:pluginReceipt,
    completePromptRegistered:false,restrictedTools:[],
    turns: 0, toolCalls: 0, failures: 0, lastDecision: null, latencyMs: [], toolNames: [], lastError: null};
  let handle, agent, busy = false, timer, server, disposed = false, automatic = false;
  let lastDecision = null, turnSubmitted = false, turnInitializing = false, turnSubmitting = false;
  let turnsInSession = 0, stopTimer, stopping = false;
  const binding = new DecisionBinding();
  const record = (kind, data = {}) => {
    if (logs) appendFileSync(`${logs}/dsh-events.jsonl`, JSON.stringify({at: new Date().toISOString(), kind, ...data})+'\n');
  };
  record('mounting',{pid:process.pid});
  async function bridge(path, body, signal) {
    const timeout=path==='/wiki'?2600:1800;
    const combined = signal ? AbortSignal.any([signal, AbortSignal.timeout(timeout)]) : AbortSignal.timeout(timeout);
    const response = await fetch(endpoint+path, {method: body === undefined ? 'GET' : 'POST', signal: combined,
      headers: {'Content-Type': 'application/json', 'X-Isaac-Token': token},
      body: body === undefined ? undefined : JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error ?? `Local bridge ${response.status}`);
    return result;
  }
  const tools = [
    ['isaac_get_state', '实时查询角色生命、完整背包、房间、已发现地图、层级、敌人与 boss。含新鲜度，未知不猜测。',
      {topic:{type:'string',enum:['state','health','inventory','effects','history','actives','pockets','map','room','enemies','bosses','pickups','resources']}},
      (a,e)=>bridge('/query?topic='+encodeURIComponent(a.topic??'state'), undefined, e.signal)],
    ['isaac_get_decision', '读取或刷新待判断集合、可选 offer、上下文身份和剩余时间；事件已附决策时无需重复查询。', {},
      async(a,e)=>binding.bind(await bridge('/decision', undefined, e.signal))],
    ['isaac_lookup', '查询本地版本化道具/卡牌机制和 12 类策略规则；unknown 表示不能凭空推断。',
      {kind:{type:'string',required:true,enum:['collectible','card','domain']},id:{type:'string',required:true}},
      (a,e)=>bridge('/lookup?kind='+encodeURIComponent(a.kind)+'&id='+encodeURIComponent(a.id), undefined, e.signal)],
    ['isaac_wiki_query', '查询已固定的离线完整Wiki；强制rep、每决策最多三次。保留修订与版本前提，不推断未知解锁。',
      {operation:{type:'string',required:true,enum:['item','show','pool','unlock','synergy','spindown']},
       query:{type:'string'},kind:{type:'string',enum:['item','trinket','card','pill','character','pool','entity','obstacle','floor','transformation','challenge','achievement','version']},
       section:{type:'string'},items:{type:'array',items:{type:'string'}},limit:{type:'integer'},steps:{type:'integer'}},
      (a,e)=>bridge('/wiki',binding.wiki(a),e.signal)],
    ['isaac_submit_plan', '从有效 offer 选择一个有期限的意图；本地会复核资源、身份、价格与安全。成功提交即结束本轮。',
      {offer_ref:{type:'string',required:true},reason:{type:'string',required:true},execution_seconds:{type:'number'},
       budget:{type:'object',required:true,additionalProperties:false,properties:{
         coins:{type:'integer',required:true},keys:{type:'integer',required:true},bombs:{type:'integer',required:true},
         health_half_hearts:{type:'integer',required:true}}}},
      async(a,e)=>{ turnSubmitting=true; try {const result=await bridge('/plan',binding.plan(a),e.signal); turnSubmitted=true; e.concludeTurn(); return result;} finally {turnSubmitting=false;} }],
  ];
  for (const [toolName, description, parameters, execute] of tools) {
    ctx.tools.register(defineTool({name:toolName,description,parameters,
      output:{schema:{type:'json'},render:(_a,value)=>[{type:'text',text:JSON.stringify(value)}]},
      async execute(args, exec) {
        const start=performance.now(); metrics.toolCalls++; metrics.toolNames.push(toolName);
        try { const result=await execute(args,exec); record('tool',{name:toolName,elapsedMs:performance.now()-start,
          ...(toolName==='isaac_submit_plan'?{receipt:result}:{})}); return result; }
        catch(error) { record('tool_error',{name:toolName,message:String(error.message).slice(0,300)}); throw error; }
      }}));
  }
  metrics.registeredTools=tools.map(t=>t[0]);
  async function drive(prompt, deadlineMs = 25000) {
    if (busy) throw new Error('One strategic turn is already running');
    busy=true; turnInitializing=true; turnSubmitted=false; binding.reset(); const start=performance.now(); let timedOut=false;
    const timeout=setTimeout(()=>{timedOut=true;agent.cancel({kind:'user'});},Math.min(60000,deadlineMs));
    try {
      if(turnsInSession>=4) {
        await handle.dispose();
        await createAgent();
        record('session_rotated',{reason:'bounded_context',sessionId:agent.id});
      }
      turnsInSession++;
      metrics.turns++;
      // Bind the authoritative event before inference. The model can submit in
      // one round trip and still query live state or refresh the decision.
      const decision=await bridge('/decision');
      const view=binding.bind(decision);
      turnInitializing=false;
      if(!view.pending||!view.connected)throw new Error('No fresh pending decision');
      record('decision_prefetched',{decisionId:decision.id,remainingMs:decision.remaining_ms});
      const eventPrompt=prompt+'\n\n插件已读取并绑定以下当前决策；无需再次调用 isaac_get_decision，信息充分时直接 isaac_submit_plan。需要更新时仍可查询。\n'+JSON.stringify(view);
      agent.followup(createUserMessage({content:[{type:'text',text:eventPrompt}],source:{kind:'user'}}));
      await agent.whenIdle();
      const elapsed=performance.now()-start; metrics.latencyMs.push(elapsed);
      metrics.latencyMs=metrics.latencyMs.slice(-200);
      if(timedOut) throw new Error('Strategic model turn deadline exceeded');
      metrics.lastError=null;
      record('turn_complete',{elapsedMs:elapsed,status:agent.status,sessionId:agent.id});
      return {elapsed_ms:elapsed,status:agent.status,session_id:agent.id,tool_calls:metrics.toolCalls};
    } catch(error) {metrics.failures++;metrics.lastError=String(error.message).slice(0,300);record('turn_error',{message:metrics.lastError});throw error;}
    finally {clearTimeout(timeout);busy=false;turnInitializing=false;turnSubmitting=false;}
  }
  async function tick() {
    if(disposed||!agent)return;
    if(busy&&!turnSubmitted&&!turnInitializing&&!turnSubmitting){
      try {const decision=await bridge('/decision');if(!binding.isCurrent(decision)){
        agent.cancel({kind:'user'});record('context_cancelled',{decisionId:decision.id??null});
      }} catch {agent.cancel({kind:'user'});}
      return;
    }
    if(!automatic||busy)return;
    try {
      const d=await bridge('/decision');
      if(!d.pending||!d.connected||d.id===lastDecision||d.remaining_ms<1500)return;
      lastDecision=d.id;metrics.lastDecision=d.id;
      await drive(`当前待判断事件 ${d.id}。使用插件附上的当前候选，按收益与生存选择一个 offer 并提交。请在 ${d.remaining_ms} ms 内完成。`,d.remaining_ms);
    } catch(error) {metrics.lastError=String(error.message).slice(0,300);}
  }
  ctx.on('agent/error', ({agent:subject,error})=>{
    if(subject===agent){metrics.failures++;metrics.lastError=String(error.message??error).slice(0,300);record('agent_error',{message:metrics.lastError});}
  });
  async function createAgent() {
    record('agent_creation_started');
    handle=await ctx.agents.create({sessionId:'isaac-'+randomUUID(),meta:{cwd:config.cwd??process.cwd()},
      agentOptions:{provider,model,maxTokens:1400},
      setup(agentCtx,newAgent) {
        installModelSelection(agentCtx);
        agentCtx.systemPrompt.section({name:'isaac-complete',order:0,text:instructions,complete:true});
        agentCtx.tools.restrict({allow:tools.map(t=>t[0])});
        metrics.completePromptRegistered=true;metrics.restrictedTools=tools.map(t=>t[0]);
        record('complete_prompt_registered',{...prompt.receipt,tool_allowlist:tools.map(t=>t[0])});
      }});
    agent=handle.agent;
    record('agent_creation_finished',{sessionId:agent.id});
    turnsInSession=0;
  }
  async function start() {
    await createAgent();
    server=createServer(async(req,res)=>{
      res.setHeader('Content-Type','application/json; charset=utf-8');res.setHeader('Cache-Control','no-store');
      try {
        if(req.method==='GET'&&req.url==='/status') {res.end(JSON.stringify({...metrics,pid:process.pid,busy,automatic,agentStatus:agent.status,sessionId:agent.id}));return;}
        if(req.method!=='POST'||req.headers.origin||req.headers['x-isaac-token']!==token) {res.statusCode=403;res.end('{"error":"local authorization required"}');return;}
        let input='';for await(const chunk of req){input+=chunk;if(input.length>16384)throw new Error('body too large');}
        const body=JSON.parse(input||'{}');
        if(req.url==='/control') {automatic=body.automatic===true;res.end(JSON.stringify({automatic}));return;}
        if(req.url==='/run') {const result=await drive(body.prompt??'先查询当前决策，再按规则选择并提交。',body.deadline_ms??25000);res.end(JSON.stringify(result));return;}
        if(req.url==='/cancel') {agent.cancel({kind:'user'});automatic=false;res.end('{"cancelled":true}');return;}
        res.statusCode=404;res.end('{"error":"not found"}');
      } catch(error){res.statusCode=400;res.end(JSON.stringify({error:String(error.message).slice(0,300)}));}
    });
    await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(config.port??9533,'127.0.0.1',resolve);});
    timer=setInterval(tick,250);
    metrics.ready=true;record('ready',{pid:process.pid,profile:'isaac',model:metrics.model,provider:metrics.provider,plugin:pluginReceipt,prompt:prompt.receipt});
    if(logs)writeFileSync(`${logs}/host-ready.json`,JSON.stringify({pid:process.pid,port:config.port??9533,...metrics}));
    console.error('Isaac DSH strategic host ready on loopback '+(config.port??9533));
  }
  // Install owned shutdown before asynchronous agent initialization, including
  // its startup failure path.
  if(process.env.ISSAC_STOP_FILE)stopTimer=setInterval(()=>{
      if(stopping||!existsSync(process.env.ISSAC_STOP_FILE))return;
      stopping=true;disposed=true;automatic=false;clearInterval(timer);clearInterval(stopTimer);
      const deadline=setTimeout(()=>{record('owned_shutdown_deadline',{pid:process.pid,clean:false});process.exit(1);},20000);
      void (async()=>{
        agent?.cancel({kind:'user'});
        // Stop new requests and close our own keep-alive sockets before
        // disposing the DSH handle. A pending dispose cannot hold the entire
        // application owner forever; timeout is explicitly an unclean stop.
        const closed=new Promise(done=>{if(!server)return done();server.close(done);server.closeAllConnections?.();});
        await closed;await handle?.dispose();clearTimeout(deadline);
        record('owned_shutdown_complete',{pid:process.pid,clean:true});process.exit(0);
      })().catch(()=>{clearTimeout(deadline);record('owned_shutdown_failed',{clean:false});process.exit(1);});
    },200);
  start().catch(error=>{metrics.lastError=String(error.message).slice(0,300);record('startup_error',{message:metrics.lastError});console.error('Isaac DSH startup failed: '+metrics.lastError);});
  ctx.on('dispose',()=>{disposed=true;automatic=false;clearInterval(timer);clearInterval(stopTimer);server?.close();handle?.dispose();});
}
