// Use the already installed SDK against the independently verified owned server.
import {createHash} from 'node:crypto';
import {readFileSync,realpathSync} from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {isDeepStrictEqual} from 'node:util';

export function selectRetainedModel(models,retainedPath){
  const selected=models.filter(m=>m.type==='llm' && m.deviceIdentifier===null && m.path===retainedPath);
  if(selected.length!==1)throw new Error('ONE_EXACT_LOCAL_RETAINED_VARIANT_REQUIRED');
  return selected[0];
}

export function verifyEcho(actual,requested){
  for(const [key,value] of Object.entries(requested)){
    if(key==='engineConfigFileContents'){
      if(actual[key]!==undefined && actual[key]!=='')throw new Error('ENGINE_CONFIG_OVERRIDE_NOT_DISABLED');
    }else if(key==='promptTemplate'){
      if(!isDeepStrictEqual(actual[key],value))throw new Error('ACTUAL_PROMPT_TEMPLATE_NOT_ECHOED');
    }else if(key==='gpu'){
      if(actual.gpu?.ratio!==value.ratio)throw new Error('ACTUAL_GPU_ALLOCATION_NOT_ECHOED');
    }else if(key==='llamaKCacheQuantizationType' || key==='llamaVCacheQuantizationType'){
      if(actual[key]!==false && actual[key]!=='f16')throw new Error('ACTUAL_FP16_KV_CONFIGURATION_NOT_ECHOED');
    }else if(actual[key]!==value)throw new Error('ACTUAL_LOAD_CONFIGURATION_NOT_ECHOED_'+key);
  }
}

export function measuredEstimate(row){
  const m=row?.memory;
  if(m?.confidence!=='high' || !Number.isFinite(m.totalVramBytes) ||
    !Number.isFinite(m.totalBytes) || m.totalVramBytes<0 || m.totalBytes<m.totalVramBytes ||
    m.totalBytes>Number.MAX_SAFE_INTEGER ||
    typeof row.passesGuardrails!=='boolean')throw new Error('ACTUAL_SDK_RESOURCE_ESTIMATE_REQUIRED');
  return {gpu_bytes:Math.ceil(m.totalVramBytes),total_bytes:Math.ceil(m.totalBytes),confidence:m.confidence,
    passes_guardrails:row.passesGuardrails};
}

export async function execute(client,request,policy){
  const maximum=policy.maximum_gpu_ratio??.6;
  const identifier=policy.model_identifier??'issac-swift-local';
  if(![.6,1].includes(maximum)||request.identifier!==identifier)throw new Error('PINNED_MODEL_PROFILE_REQUIRED');
  const selected=selectRetainedModel(await client.system.listDownloadedModels(),request.retained_path);
  const loaded=await client.llm.listLoaded();
  const models=[];
  for(const handle of loaded){
    const info=await handle.getModelInfo();
    const config=await handle.getLoadConfig();
    let verified=false;
    if(info.identifier===request.identifier){
      if(info.path!==selected.path || (info.deviceIdentifier??null)!==null ||
        !Number.isFinite(config.gpu?.ratio) || config.gpu.ratio<=0 || config.gpu.ratio>maximum)
        throw new Error('ACTUAL_LOADED_RETAINED_MODEL_IDENTITY_CHANGED');
      verifyEcho(config,{...policy.load_config,contextLength:16384,gpu:{ratio:config.gpu.ratio}});
      verified=true;
    }
    models.push({id:info.identifier,path:info.path,device_identifier:info.deviceIdentifier??null,
      configuration_verified:verified,
      config:Object.fromEntries(['contextLength','gpu',...Object.keys(policy.load_config)]
        .filter(k=>config[k]!==undefined).map(k=>[k,config[k]]))});
  }
  if(request.action==='loaded')return {models,catalogue_is_loaded_evidence:false};
  if(models.length)throw new Error('EXISTING_LOADED_MODELS_PRESERVED_NO_REPLACEMENT');
  if(!Number.isFinite(request.ratio) || request.ratio<=0 || request.ratio>maximum ||
     policy.context_length!==16384)throw new Error('FROZEN_SWIFT_CONTEXT_AND_BOUNDED_ALLOCATION_REQUIRED');
  const config={...policy.load_config,contextLength:16384,gpu:{ratio:request.ratio}};
  if(request.action==='estimate'){
    const estimate=measuredEstimate(await client.llm.estimateResourcesUsage(selected.modelKey,config,{deviceIdentifier:null}));
    return {estimate,requested_config:config,retained_path:selected.path};
  }
  if(request.action!=='load')throw new Error('BOUNDED_NATIVE_MODEL_ACTION_REQUIRED');
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),890000);
  try{
    const handle=await client.llm.load(selected.modelKey,{config,identifier:request.identifier,
      deviceIdentifier:null,verbose:false,signal:controller.signal});
    const info=await handle.getModelInfo();
    if(info.identifier!==request.identifier || info.path!==selected.path || (info.deviceIdentifier??null)!==null)
      throw new Error('ACTUAL_RETAINED_MODEL_IDENTITY_CHANGED');
    const actual=await handle.getLoadConfig();
    verifyEcho(actual,config);
    return {model:{id:info.identifier,path:info.path,device_identifier:info.deviceIdentifier??null},
      requested_config:config,actual_config:Object.fromEntries(Object.keys(config).map(k=>[k,actual[k]])),
      configuration_verified:true};
  }finally{clearTimeout(timer);}
}

async function main(){
  const root=realpathSync(process.argv[2]);
  let raw='';for await(const chunk of process.stdin){raw+=chunk;if(raw.length>65536)throw new Error('BOUNDED_MODEL_REQUEST_REQUIRED');}
  const request=JSON.parse(raw);
  const url=new URL(request.base_url);
  if(url.protocol!=='ws:' || url.hostname!=='127.0.0.1' || !url.port || url.pathname!=='/' ||
    url.search || url.hash || url.username || url.password)throw new Error('OWNED_LOOPBACK_SDK_URL_REQUIRED');
  const policy=JSON.parse(readFileSync(path.join(root,'configs/issac/model-loading.json'),'utf8'));
  if(policy.model_identifier==='issac-naimei-local'){
    const existing=JSON.parse(readFileSync(path.join(root,'configs/issac/existing-model-backend.json'),'utf8'));
    if(existing.policy_id!=='NM-ISSAC-EXISTING-QWEN27B-20261109-v1' ||
       request.retained_path!==existing.catalogue_path || request.identifier!==existing.model_identifier ||
       policy.maximum_gpu_ratio!==1 || existing.context_length!==16384 || existing.gpu_offload!==1 ||
       existing.model_downloads_allowed!==false || existing.cloud_fallback!==false)
      throw new Error('EXACT_EXISTING_LOCAL_BACKEND_PROFILE_REQUIRED');
  }
  const entry=realpathSync(path.join(root,policy.sdk.entry));
  const relative=path.relative(root,entry);
  if(relative.startsWith('..') || path.isAbsolute(relative) ||
    createHash('sha256').update(readFileSync(entry)).digest('hex')!==policy.sdk.sha256)
    throw new Error('PINNED_EXISTING_BUNDLED_SDK_REQUIRED');
  const {LMStudioClient}=createRequire(import.meta.url)(entry);
  const logger={debug(){},info(){},warn(){},error(){},log(){}};
  const client=new LMStudioClient({baseUrl:request.base_url,logger,
    ...(request.api_token?{apiToken:request.api_token}:{})});
  try{process.stdout.write(JSON.stringify(await execute(client,request,policy))+'\n');}
  finally{await client[Symbol.asyncDispose]();}
}

if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  main().catch(error=>{process.stderr.write(String(error?.message||'NATIVE_SDK_FAILED')+'\n');process.exitCode=1;});
}
