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
  // Preserve server policy/budget errors, which already carry a safe code/status.
  if (error?.code && Number.isInteger(error.status)) return error;
  const code = [finish?.reason?.failure?.code, error?.code, error?.failure?.code, error?.cause?.code].find(value => Object.hasOwn(failures, value));
  if (code) return new ModelFailure(...failures[code], code);
  if (localGuards.has(error?.code || error?.message)) return new ModelFailure(error.code || error.message, 502, false);
  return new ModelFailure('DSH_GENERATION_FAILED', 502, false);
}
