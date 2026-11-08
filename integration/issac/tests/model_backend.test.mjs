import test from 'node:test';
import assert from 'node:assert/strict';
import {execute,measuredEstimate,selectRetainedModel,verifyEcho} from '../model_backend.mjs';

const retained='SC117/existing/retained-00001-of-00002.gguf';
const local={type:'llm',deviceIdentifier:null,path:retained,modelKey:'retained-exact-key'};
const policy={context_length:16384,load_config:{flashAttention:true,evalBatchSize:64,
  physicalBatchSize:64,maxParallelPredictions:1,contextCheckpoints:0,keepModelInMemory:false,
  tryMmap:true,useFp16ForKVCache:true,llamaKCacheQuantizationType:false,
  llamaVCacheQuantizationType:false,engineConfigFileContents:''}};
const request={action:'estimate',retained_path:retained,identifier:'issac-swift-local',ratio:.375};
const estimate={memory:{confidence:'high',totalVramBytes:100,totalBytes:200},passesGuardrails:true};

test('the exact shard on another device or a fuzzy path cannot select a model',()=>{
  assert.equal(selectRetainedModel([{...local,deviceIdentifier:'foreign-device'},local],retained),local);
  for(const rows of [[{...local,deviceIdentifier:'foreign-device'}],[{...local,path:retained+'x'}],[local,local]])
    assert.throws(()=>selectRetainedModel(rows,retained),/EXACT_LOCAL/);
});
test('catalogue presence does not turn into loaded-model evidence',async()=>{
  const client={system:{listDownloadedModels:async()=>[local]},llm:{listLoaded:async()=>[]}};
  assert.deepEqual((await execute(client,{...request,action:'loaded'},policy)).models,[]);
});
test('a real estimate uses the same complete configuration and explicit local device',async()=>{
  let called;
  const client={system:{listDownloadedModels:async()=>[local]},llm:{listLoaded:async()=>[],
    estimateResourcesUsage:async(...args)=>{called=args;return estimate;}}};
  const result=await execute(client,request,policy);
  assert.equal(called[0],local.modelKey);assert.equal(called[1].contextLength,16384);
  assert.deepEqual(called[1].gpu,{ratio:.375});assert.equal(called[1].evalBatchSize,64);
  assert.deepEqual(called[2],{deviceIdentifier:null});assert.equal(result.estimate.gpu_bytes,100);
});
test('an existing model is preserved before any load or estimate is attempted',async()=>{
  let changed=false;
  const handle={getModelInfo:async()=>({identifier:'someone-else',path:retained,deviceIdentifier:null}),
    getLoadConfig:async()=>({})};
  const client={system:{listDownloadedModels:async()=>[local]},llm:{listLoaded:async()=>[handle],
    load:async()=>{changed=true;},estimateResourcesUsage:async()=>{changed=true;}}};
  await assert.rejects(execute(client,request,policy),/EXISTING_LOADED_MODELS_PRESERVED/);
  assert.equal(changed,false);
});
test('missing, low-confidence and malformed memory numbers are never estimates',()=>{
  for(const value of [{},{...estimate,memory:{...estimate.memory,confidence:'low'}},
    {...estimate,memory:{...estimate.memory,totalVramBytes:300}},
    {...estimate,memory:{...estimate.memory,totalBytes:NaN}}])assert.throws(()=>measuredEstimate(value));
  assert.equal(measuredEstimate({...estimate,passesGuardrails:false}).passes_guardrails,false);
});
test('a successfully loaded model still fails if the backend ignored a required parameter',()=>{
  const requested={...policy.load_config,contextLength:16384,gpu:{ratio:.375}};
  assert.doesNotThrow(()=>verifyEcho({...requested},requested));
  for(const changed of [{evalBatchSize:512},{flashAttention:false},{contextLength:4096},
    {physicalBatchSize:512},{llamaKCacheQuantizationType:'q8_0'},{gpu:{ratio:.45}}])
    assert.throws(()=>verifyEcho({...requested,...changed},requested));
});
