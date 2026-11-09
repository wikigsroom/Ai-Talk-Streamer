import {createHash} from 'node:crypto';

// The pinned adapter reports upstream failures as finish chunks as well as throws.
// Classify only its finite codes. Provider messages can contain prompt text or keys.
const failures = {
  AUTH: ['MODEL_AUTH_FAILED', 502, false],
  INVALID_CREDENTIAL: ['MODEL_AUTH_FAILED', 502, false],
  MISSING_CREDENTIAL: ['MODEL_AUTH_FAILED', 502, false],
  RATE_LIMIT: ['MODEL_RATE_LIMIT', 429, true],
  QUOTA: ['MODEL_QUOTA_EXHAUSTED', 502, false],
  ACCOUNT_QUOTA: ['MODEL_QUOTA_EXHAUSTED', 502, false],
  TIMEOUT: ['MODEL_TIMEOUT', 504, true],
  TRANSPORT: ['MODEL_TRANSPORT_FAILED', 502, true],
  STREAM_CLOSED: ['MODEL_TRANSPORT_FAILED', 502, true],
  SERVER: ['MODEL_UPSTREAM_UNAVAILABLE', 502, true],
  EMPTY_RESPONSE: ['MODEL_RESPONSE_INVALID', 502, false],
  PI_AI_ERROR: ['MODEL_RESPONSE_INVALID', 502, false],
  INVALID_REQUEST: ['MODEL_REQUEST_REJECTED', 502, false],
  CONTEXT_WINDOW_EXCEEDED: ['MODEL_CONTEXT_EXCEEDED', 502, false],
  ABORTED: ['MODEL_CANCELLED', 409, false],
};
const localGuards = new Set(['STREAM_TOOL_ROUND_LIMIT','PERSONA_INJECTION_MISSING','STREAM_TOOL_CATALOG_ESCAPE','STREAM_CONTEXT_BUDGET','DSH_NOT_READY_OR_DUPLICATE']);

// Retain a location for local lifecycle failures without leaking messages,
// provider addresses, prompts, keys or absolute machine paths.
export function generationDiagnostic(error, depth=0) {
  const names=new Set(['Error','TypeError','RangeError','ReferenceError','AbortError','AggregateError','SuppressedError','SessionAlreadyExistsError']);
  const codes=new Set(['ENOENT','EEXIST','EBUSY','EPERM','EACCES','ENOTDIR','EMFILE','ENFILE']);
  const guards=new Set([...localGuards,'SOUL_CARD_NOT_INJECTED','CORE_TURN_CANCELLED']);
  const sources=[];
  for(const line of String(error?.stack||'').split('\n')) {
    if(!/^\s+at /.test(line))continue;
    const dependency=/node_modules\/@deepseek-ai\/([\w-]+)\/(?:lib\/)?([\w/.-]+\.m?js):(\d+):(\d+)/.exec(line);
    const bridge=/backend\/dsh-bridge\/([\w.-]+\.mjs):(\d+):(\d+)/.exec(line);
    if(dependency)sources.push({package:dependency[1],file:dependency[2],line:Number(dependency[3]),column:Number(dependency[4])});
    else if(bridge)sources.push({package:'stream-bridge',file:bridge[1],line:Number(bridge[2]),column:Number(bridge[3])});
    if(sources.length===4)break;
  }
  return {name:names.has(error?.name)?error.name:'OtherError',code:codes.has(error?.code)?error.code:null,
    guard:guards.has(error?.message)?error.message:null,
    message_sha256:createHash('sha256').update(String(error?.message||'')).digest('hex'),sources,
    ...(depth<2?{related:['cause','error','suppressed'].filter(key=>error?.[key]&&typeof error[key]==='object'&&error[key]!==error)
      .map(key=>({relation:key,...generationDiagnostic(error[key],depth+1)}))}:{})};
}

export class ModelFailure extends Error {
  constructor(code, status, retryable, upstreamCode = null) {
    super(code); this.code = code; this.status = status; this.retryable = retryable; this.upstreamCode = upstreamCode;
  }
}
export function modelFailure(error, { signal, finish } = {}) {
  if (error instanceof ModelFailure) return error;
  if (signal?.aborted) return signal.reason?.name === 'TimeoutError'
    ? new ModelFailure('MODEL_TIMEOUT', 504, true)
    : new ModelFailure('MODEL_CANCELLED', 409, false);
  // This is a local DSH persistence conflict, before any provider request.
  // Keep diagnostics finite; never publish the upstream exception message.
  if (error?.name === 'SessionAlreadyExistsError') return new ModelFailure('DSH_SESSION_ID_COLLISION', 502, false);
  // Preserve server policy/budget errors, which already carry a safe code/status.
  if (error?.code && Number.isInteger(error.status)) return error;
  const code = [finish?.reason?.failure?.code, error?.code, error?.failure?.code, error?.cause?.code].find(value => Object.hasOwn(failures, value));
  if (code) return new ModelFailure(...failures[code], code);
  if (localGuards.has(error?.code || error?.message)) return new ModelFailure(error.code || error.message, 502, false);
  return new ModelFailure('DSH_GENERATION_FAILED', 502, false);
}
