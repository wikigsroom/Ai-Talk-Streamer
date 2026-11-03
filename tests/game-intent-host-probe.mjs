import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { DshHost } from '../backend/dsh-bridge/host.mjs';
import { initialPersona } from '../backend/dsh-bridge/persona.mjs';
import { loadPolicy } from '../backend/dsh-bridge/policy.mjs';

const root = resolve(process.argv[2]), runtime = resolve(process.argv[3]), output = resolve(process.env.MC_INTENT_EVIDENCE_ROOT);
mkdirSync(output, { recursive: true });
const policy = structuredClone(loadPolicy(root));
policy.deployment.dsh_home_relative_path = 'outputs/mc-validation/round-034/dsh-probe-' + randomUUID();
const requests = [], probes = [], sessions = [], calls = [];
const tools = ['game_get_state','game_query_inventory','game_get_recipe','game_check_action'];
const answer = { kind: 'goal', goal: { skill: 'gather', item_id: 'minecraft:oak_log', count: 8 }, question: null };
let host, hold, release, began, active = 0, maxActive = 0;
const sockets = new Set();
const server = createServer(async (req, res) => {
  active++; maxActive = Math.max(maxActive, active); res.once('close', () => active--);
  const chunks = []; for await (const chunk of req) chunks.push(chunk); const body = JSON.parse(Buffer.concat(chunks));
  requests.push({ names: body.tools?.map(tool => tool.function.name) || [], has_source: JSON.stringify(body).includes('ephemeral-source-sentinel') });
  if(hold){hold=false;began();await new Promise(resolve => release=resolve);}
  if(res.destroyed)return;
  const intent = body.tools?.some(tool => tool.function.name === 'stream_audience_intent_result');
  const delta = intent ? { role: 'assistant', tool_calls: [{ index: 0, id: 'intent-result', type: 'function', function: {
    name: 'stream_audience_intent_result', arguments: JSON.stringify({ data: JSON.stringify(answer) }) } }] } : { role: 'assistant', content: '先听听观众怎么说。' };
  res.writeHead(200, { 'Content-Type': 'text/event-stream' });
  for(const choice of [{ delta, finish_reason: null }, { delta: {}, finish_reason: intent?'tool_calls':'stop' }])
    res.write('data: '+JSON.stringify({ id:'local-intent-probe', object:'chat.completion.chunk', model:'local-fixture', choices:[{ index:0,...choice }] })+'\n\n');
  res.end('data: [DONE]\n\n');
});
server.on('connection', socket => { sockets.add(socket); socket.once('close', () => sockets.delete(socket)); });
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const report = { classification: 'NATIVE_DSH_HUMANITY_WITH_LOCAL_CONTROLLED_HTTP_MODEL_ONLY', result: 'FAIL', tests: [], real_model: false, real_minecraft: false, public_broadcast: false };
try {
  host = await new DshHost(root, runtime, policy).start(); const persona = initialPersona(root); await host.publishCharacter(persona.document, persona.version);
  let memoryReads=0; host.port.requestMemorySnapshot=()=>{memoryReads++;throw Error('intent must not request memory');};
  const snapshot={revision:'local-fixture',model:'local-fixture',protocol:'chat_completions',baseUrl:'http://127.0.0.1:'+server.address().port+'/v1',systemPrompt:'',getApiKey:()=> 'local-test-key'};
  const options=()=>{const sessionId='mc-intent-'+randomUUID();sessions.push(sessionId);return {sessionId,snapshot,purpose:'audience_intent',input:'ephemeral-source-sentinel',context:'{}',maxTokens:512,
    toolCatalogue:[...tools,'game_start_task','game_cancel_task','stream_memory_recall','shell'].map(name=>({name,description:name})),
    tools:async(name,args)=>{calls.push(name);assert.equal(name,'stream_audience_intent_result');assert.deepEqual(args,answer);return {received:true};},onProbe:probe=>probes.push(probe)};};
  const response=await host.generate(options());assert.equal(response.text,'');assert.equal(calls.length,1);
  assert.deepEqual(requests[0].names.sort(),['stream_audience_intent_result',...tools].sort());assert.equal(requests[0].has_source,true);assert.equal(memoryReads,0);
  assert(!(await host.ctx.sessionPersistence.list()).some(row=>sessions.includes(row.header.id)));assert.equal(host.active.size,0);
  report.tests.push('native tool catalogue, concludeTurn, no memory snapshot and actual JSONL deletion');
  host.purgeAudienceIntentSessions=async()=>{};
  await host.generate(options());
  assert((await host.ctx.sessionPersistence.list()).some(row=>sessions.includes(row.header.id)), 'crash-residue fixture really exists before restart');
  await host.close();host=await new DshHost(root,runtime,policy).start();
  host.port.requestMemorySnapshot=()=>{memoryReads++;throw Error('intent must not request memory');};
  assert(!(await host.ctx.sessionPersistence.list()).some(row=>sessions.includes(row.header.id)));
  report.tests.push('native host restart discovers and deletes a deliberately retained temporary session');
  hold=true;const started=new Promise(resolve=>began=resolve), controller=new AbortController();
  const pending=host.generate({...options(),signal:controller.signal});const rejected=assert.rejects(pending);await started;controller.abort();release();await rejected;
  assert(!(await host.ctx.sessionPersistence.list()).some(row=>sessions.includes(row.header.id)));report.tests.push('cancelled native request deletes temporary session before returning');
  const original=host.purgeAudienceIntentSessions.bind(host);host.purgeAudienceIntentSessions=async ids=>{await original(ids);throw Error('LOCAL_FIXTURE_CLEANUP_FAILURE');};
  await assert.rejects(host.generate(options()),/LOCAL_FIXTURE_CLEANUP_FAILURE/);assert.equal(host.audienceIntentCleanupFailed,true);
  await assert.rejects(host.generate(options()),/STREAM_INTENT_SESSION_UNAVAILABLE/);host.purgeAudienceIntentSessions=original;
  report.tests.push('cleanup failure rejects result and blocks later interpretation');
  for(const project of readdirSync(join(root,policy.deployment.dsh_home_relative_path,'sessions'),{withFileTypes:true}).filter(row=>row.isDirectory()))
    for(const session of readdirSync(join(root,policy.deployment.dsh_home_relative_path,'sessions',project.name)))assert(!sessions.includes(session));
  report.result='PASS';report.memory_reads=memoryReads;report.model_requests=requests.length;report.probes=probes;report.tools_called=calls;report.global_model_concurrency_max=maxActive;
}catch(error){report.error=String(error.stack||error);throw error;}
finally{release?.();try{await host?.close();}finally{server.closeAllConnections();for(const socket of sockets)socket.destroy();await new Promise(resolve=>server.close(resolve));
  report.native_host_closed=!host?.ready;report.recorded_at=new Date().toISOString();writeFileSync(join(output,'native-dsh-intent-probe.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));}}
