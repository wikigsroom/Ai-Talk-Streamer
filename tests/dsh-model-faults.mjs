import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {DshHost} from '../backend/dsh-bridge/host.mjs';
import {loadPolicy} from '../backend/dsh-bridge/policy.mjs';
import {initialPersona} from '../backend/dsh-bridge/persona.mjs';

// Real pinned Harness + Humanity + HTTP; no cloud credentials, TTS or GPU.
// The endpoint is deliberately adversarial and is never installed in channel.env.
const root=resolve(process.argv[2]),runtime=resolve(process.argv[3]),stamp=Date.now();
const policy=structuredClone(loadPolicy(root));
policy.deployment.dsh_home_relative_path='state/dsh-model-faults-'+stamp;
policy.conversation.model_timeout_ms=30000;
const wire=[],rows=[],logs=[],originalError=console.error;
const secret='fixture-key-do-not-log',input='private-input-do-not-log';
let scenario='success',currentAbort;
const server=createServer(async(req,res)=>{
  let body='';for await(const chunk of req)body+=chunk;
  const value=JSON.parse(body);wire.push({model:value.model,path:req.url,scenario});
  if(['401','429','500'].includes(scenario)){
    res.writeHead(Number(scenario),{'Content-Type':'application/json','Retry-After':'1'});
    res.end(JSON.stringify({error:{message:secret+' '+input,type:'fixture_failure'}}));return;
  }
  res.writeHead(200,{'Content-Type':'text/event-stream'});res.flushHeaders();
  if(scenario==='stall'||scenario==='manual_abort'){
    if(scenario==='manual_abort')setTimeout(()=>currentAbort.abort(),300);
    return;
  }
  if(scenario==='disconnect'){res.write(': connected\n\n');setTimeout(()=>res.destroy(),30);return;}
  if(scenario==='invalid_json'){res.end('data: {this is not json}\n\n');return;}
  const emit=data=>res.write('data: '+JSON.stringify(data)+'\n\n');
  const text=scenario==='empty'?'':'故障后恢复正常。';
  if(req.url.endsWith('/responses')){
    const item={id:'msg-fixture',type:'message',role:'assistant',status:'completed',content:[{type:'output_text',text,annotations:[]}]};
    emit({type:'response.created',response:{id:'resp-fixture',status:'in_progress'}});
    if(text){emit({type:'response.output_item.added',output_index:0,item:{...item,status:'in_progress',content:[]}});emit({type:'response.output_text.delta',output_index:0,content_index:0,delta:text});emit({type:'response.output_item.done',output_index:0,item});}
    emit({type:'response.completed',response:{id:'resp-fixture',status:'completed',output:text?[item]:[],usage:{input_tokens:40,output_tokens:8,total_tokens:48}}});
    res.end();
  }else{
    if(text)emit({id:'chat-fixture',object:'chat.completion.chunk',model:value.model,choices:[{index:0,delta:{role:'assistant',content:text},finish_reason:null}]});
    emit({id:'chat-fixture',object:'chat.completion.chunk',model:value.model,choices:[{index:0,delta:{},finish_reason:'stop'}],usage:{prompt_tokens:40,completion_tokens:8,total_tokens:48}});
    res.end('data: [DONE]\n\n');
  }
});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
let host;
try{
  console.log(JSON.stringify({event:'fault_matrix.boot',node:process.version}));
  host=await new DshHost(root,runtime,policy).start();const persona=initialPersona(root);await host.publishCharacter(persona.document,persona.version);
  console.error=(...args)=>{const line=args.map(String).join(' ');if(line.startsWith('{')){try{const event=JSON.parse(line);if(event.event==='dsh.request_failed')logs.push(event)}catch{}}else originalError(...args);};
  const cases=[['success',null],['401','MODEL_AUTH_FAILED'],['429','MODEL_RATE_LIMIT'],['500','MODEL_UPSTREAM_UNAVAILABLE'],['invalid_json','MODEL_RESPONSE_INVALID'],['disconnect','MODEL_TRANSPORT_FAILED'],['stall','MODEL_TIMEOUT'],['manual_abort','MODEL_CANCELLED'],['empty','MODEL_RESPONSE_INVALID'],['success',null]];
  for(const protocol of ['chat_completions','responses'])for(const [fault,expected]of cases){
    scenario=fault;const sessionId='fault-'+protocol+'-'+rows.length+'-'+stamp,phases=[],start=Date.now(),before=wire.length;
    console.log(JSON.stringify({event:'fault_matrix.case',protocol,scenario:fault}));
    policy.conversation.model_timeout_ms=fault==='stall'?1000:30000;
    const snapshot={revision:'fixture-fault-matrix',model:'fault-fixture',protocol,baseUrl:'http://127.0.0.1:'+server.address().port+'/v1',systemPrompt:'',getApiKey:()=>secret};
    const abort=currentAbort=new AbortController();
    const signal=AbortSignal.any([abort.signal,AbortSignal.timeout(45000)]);let outcome;
    try{
      const result=await host.generate({sessionId,snapshot,input,signal,tools:async()=>{throw Error('UNEXPECTED_TOOL')},onCall:event=>{phases.push(event.phase);return 'fixture-attempt'}});
      assert.equal(expected,null);assert.equal(result.text,'故障后恢复正常。');outcome={passed:true,text_verified:true};
    }catch(error){
      assert.equal(error.code,expected,protocol+'/'+fault+': '+error.code);assert.equal(error.message,expected);
      outcome={passed:true,error:error.code,http_status:error.status,retryable:error.retryable};
      assert.equal(error.status,fault==='429'?429:fault==='stall'?504:fault==='manual_abort'?409:502);
      assert.equal(error.retryable,['429','500','disconnect','stall'].includes(fault));
    }finally{currentAbort=null}
    assert.equal(wire.length-before,1,'no hidden SDK/Harness retry for '+protocol+'/'+fault);
    assert.equal(phases.filter(phase=>phase==='reserve').length,1);assert.equal(phases.filter(phase=>phase==='sent').length,1);
    assert.equal(phases.filter(phase=>phase==='settle'||phase==='failed').length,1);assert.equal(host.active.size,0);
    rows.push({protocol,scenario:fault,...outcome,wire_requests:wire.length-before,call_phases:phases,elapsed_ms:Date.now()-start});
  }
  assert.equal(logs.length,16);assert.ok(!JSON.stringify(logs).includes(secret));assert.ok(!JSON.stringify(logs).includes(input));
  const result={passed:true,kind:'real_pinned_dsh_humanity_controlled_http_fault_matrix',cloud_channel_exercised:false,gpu_or_tts_exercised:false,automatic_provider_substitution:false,wire_requests:wire.length,cases:rows,structured_bridge_logs_redacted:true,recovery_verified_for_both_protocols:true};
  const folder=join(root,'outputs/dsh-humanity');mkdirSync(folder,{recursive:true});writeFileSync(join(folder,'model-faults.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
}finally{console.error=originalError;await host?.close();server.closeAllConnections();await new Promise(done=>server.close(done))}
