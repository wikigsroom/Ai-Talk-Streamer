import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdirSync,writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { generateChannelVision,readVisionResponse } from '../backend/dsh-bridge/channel-vision.mjs';
import { ChannelVisionProvider } from '../backend/game/vision.mjs';
import { DshHost } from '../backend/dsh-bridge/host.mjs';
import { ModelQueue } from '../backend/dsh-bridge/model-queue.mjs';
import { gameFixture,until } from './game-fixture.mjs';

const description={caption:'SYNTHETIC_FIXTURE_ONLY',visible_text:[],unknowns:['仅为协议测试']};
const image=Buffer.from('SYNTHETIC_IMAGE_BYTES_TRANSPORT_ONLY');
function completed(model='gpt-6-luna') {return {model,status:'completed',output:[{type:'message',content:[{type:'output_text',text:JSON.stringify(description)}]}],usage:{input_tokens:120,output_tokens:30}};}
async function fixture(t,{chat=false}={}) {
  let body,mode='ok';const calls=[];
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);body=JSON.parse(Buffer.concat(chunks));
    assert.equal(req.headers.authorization,'Bearer FIXTURE_NOT_A_CREDENTIAL');
    if(mode==='401'){res.writeHead(401);res.end('PRIVATE_ERROR_BODY_NOT_TO_BE_LOGGED');return;}
    if(mode==='hold'){res.writeHead(200,{'Content-Type':'text/event-stream'});res.flushHeaders();return;}
    const output=completed(mode==='wrong_model'?'another-model':'gpt-6-luna');
    if(chat){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({model:output.model,choices:[{finish_reason:'stop',message:{content:JSON.stringify(description)}}],usage:output.usage}));return;}
    res.setHeader('Content-Type','text/event-stream');
    res.write('event: response.created\r\ndata: {"type":"response.created"}\r\n\r\n');
    const event=JSON.stringify({type:'response.completed',response:output});
    // Split UTF-8 and event boundaries across actual socket writes.
    const bytes=Buffer.from('data: '+event+'\r\n\r\n');res.write(bytes.subarray(0,bytes.length-7));res.end(bytes.subarray(bytes.length-7));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>{server.closeAllConnections();server.close();});
  const snapshot={model:'gpt-6-luna',revision:'a'.repeat(64),protocol:chat?'chat_completions':'responses',
    baseUrl:'http://127.0.0.1:'+server.address().port+'/v1',getApiKey:()=> 'FIXTURE_NOT_A_CREDENTIAL'};
  const run=(extra={})=>generateChannelVision({snapshot,image,input:'FIXTURE_ONLY',signal:AbortSignal.timeout(3000),
    onCall:call=>{calls.push(call);return call.phase==='reserve'?'fixture-attempt':undefined;},...extra});
  return {run,snapshot,calls,get body(){return body;},setMode:value=>{mode=value;}};
}
test('Responses sends real image bytes, detail and bound Luna identity; accounts one call without persisting pixels',async t=>{
  const f=await fixture(t),result=await f.run();assert.deepEqual(result.description,description);
  assert.equal(f.body.input[0].content[1].image_url,'data:image/jpeg;base64,'+image.toString('base64'));
  assert.equal(f.body.input[0].content[1].detail,'high');assert.equal(f.body.store,false);
  assert.equal(f.body.reasoning.effort,'none');assert.equal(f.body.tools,undefined);
  assert.deepEqual(f.calls.map(x=>x.phase),['reserve','sent','settle']);
  assert(!JSON.stringify(f.calls).includes(image.toString('base64')));assert.equal(result.model,'gpt-6-luna');
});
test('Chat Completions uses image_url and no reasoning/tool dependency',async t=>{
  const f=await fixture(t,{chat:true});assert.deepEqual((await f.run()).description,description);
  assert.equal(f.body.messages[1].content[1].image_url.detail,'high');assert.equal(f.body.reasoning_effort,'none');
});
test('wrong model and upstream authentication errors fail closed and settle the attempt',async t=>{
  const f=await fixture(t);f.setMode('wrong_model');await assert.rejects(f.run(),{code:'MODEL_VISION_MODEL_MISMATCH'});
  f.setMode('401');await assert.rejects(f.run(),{code:'MODEL_AUTH_FAILED'});
  assert.equal(f.calls.filter(x=>x.phase==='failed').length,2);assert(!JSON.stringify(f.calls).includes('PRIVATE_ERROR'));
});
test('cancelling a stalled image stream returns its queue slot and settles sent usage as unknown',async t=>{
  const f=await fixture(t);f.setMode('hold');const controller=new AbortController();const pending=f.run({signal:controller.signal});
  await until(()=>f.body);controller.abort();await assert.rejects(pending,{code:'MODEL_CANCELLED'});
  assert.equal(f.calls.at(-1).phase,'failed');assert.equal(f.calls.at(-1).sent,true);
});
test('oversized and incomplete response streams never yield a successful observation',async()=>{
  const signal=AbortSignal.timeout(3000);
  await assert.rejects(readVisionResponse(new Response('x'.repeat(524289)),signal),{code:'MODEL_RESPONSE_TOO_LARGE'});
  const data='data: '+JSON.stringify({type:'response.incomplete',response:completed()})+'\n\n';
  await assert.rejects(readVisionResponse(new Response(data,{headers:{'content-type':'text/event-stream'}}),signal),{code:'MODEL_RESPONSE_INVALID'});
});
test('vision shares the DSH host queue and shutdown cancellation, without SDK sessions',async t=>{
  const f=await fixture(t),host=new DshHost(process.cwd(),process.cwd(),{});host.ready=true;
  host.modelQueue=new ModelQueue();f.setMode('hold');
  const pending=host.generate({purpose:'vision',snapshot:f.snapshot,image,input:'FIXTURE_ONLY'});
  await until(()=>f.body);assert.equal(host.modelQueue.view().active_purpose,'vision');
  host.stopAdmission();await assert.rejects(pending,{code:'MODEL_CANCELLED'});await host.modelQueue.whenIdle();
  assert.equal(host.modelCalls.size,0);assert.equal(host.active.size,0);
});
test('channel provider rejects channel changes, preserves native scope and reports sanitized timing',async t=>{
  const f=await gameFixture();t.after(()=>f.close());mkdirSync(join(f.folder,'configs'),{recursive:true});
  writeFileSync(join(f.folder,'configs/mc-vision.json'),JSON.stringify({schema_version:2,provider:'studio_channel',model:'gpt-6-luna',observe_interval_ms:20000}));
  let revision='b'.repeat(64);f.bridge.channel={publicInfo:()=>({configured:true,model:'gpt-6-luna',protocol:'responses',revision}),snapshot:()=>({model:'gpt-6-luna',revision})};
  f.bridge.host={ready:true,generate:async()=>({description,model:'gpt-6-luna',usage:null})};
  const provider=new ChannelVisionProvider(f.manager);assert.equal(provider.available(),true);
  const entry={bytes:image,meta:{frame_id:'fixture-frame',source_seq:1,captured_at:new Date().toISOString(),width:32,height:18}};
  const value=await provider.analyze(entry,'screen',AbortSignal.timeout(3000));assert.equal(value.model_id,'gpt-6-luna');
  assert.equal(provider.status().last_result.state,'succeeded');assert(!JSON.stringify(provider.status()).includes(image.toString('base64')));
  f.bridge.host.generate=async()=>{revision='c'.repeat(64);return {description,model:'gpt-6-luna'};};
  await assert.rejects(provider.analyze(entry,'screen',AbortSignal.timeout(3000)),{code:'GAME_VISION_CHANNEL_CHANGED'});
  provider.close();assert.equal(provider.available(),false);
});

test('channel vision includes only frame-bound hands and rejects a contradictory held-shield caption',async t=>{
  const f=await gameFixture();t.after(()=>f.close());mkdirSync(join(f.folder,'configs'),{recursive:true});
  writeFileSync(join(f.folder,'configs/mc-vision.json'),JSON.stringify({schema_version:2,provider:'studio_channel',model:'gpt-6-luna',observe_interval_ms:20000}));
  const revision='d'.repeat(64);f.bridge.channel={publicInfo:()=>({configured:true,model:'gpt-6-luna',protocol:'responses',revision}),snapshot:()=>({model:'gpt-6-luna',revision})};
  let input;f.bridge.host={ready:true,generate:async value=>{input=value.input;return {description:{caption:'右下持有盾牌。',visible_text:[],unknowns:[]},model:'gpt-6-luna'};}};
  const provider=new ChannelVisionProvider(f.manager);t.after(()=>provider.close());
  const entry={bytes:image,meta:{frame_id:'fixture-grounded-frame',source_seq:7,captured_at:new Date().toISOString(),width:32,height:18},
    nativeHands:{binding:'frame_source_seq',source_seq:7,hands:{selected_hotbar:0,mainhand:{item_id:'gravestone:obituary',count:1},offhand:{item_id:'minecraft:air',count:0}}}};
  await assert.rejects(provider.analyze(entry,'screen',AbortSignal.timeout(3000)),{code:'GAME_VISION_HELD_ITEM_CONFLICT'});
  assert(input.includes('gravestone:obituary'));assert.equal(provider.status().last_result.state,'failed');
  assert.equal(provider.status().last_result.caption,undefined,'a false caption cannot enter the completed observation');
  assert.equal(provider.status().last_result.held_item_grounding.source_seq,7);
  delete entry.nativeHands;f.bridge.host.generate=async value=>{input=value.input;return {description,model:'gpt-6-luna'};};
  await provider.analyze(entry,'screen',AbortSignal.timeout(3000));assert(input.includes('不判断玩家手持物'));
  assert.equal(provider.status().last_result.held_item_grounding.binding,'unavailable');
});
