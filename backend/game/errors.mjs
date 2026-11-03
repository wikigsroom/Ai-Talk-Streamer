export class GameError extends Error {
  constructor(code, status = 409, details, retryable = false) {
    super(code); this.code = code; this.status = status; this.details = details; this.retryable = retryable;
  }
  public(requestId = null) {
    return { error: this.code, request_id: requestId, retryable: this.retryable,
      ...(this.details ? { details: this.details } : {}) };
  }
}
export function ensure(condition, code, status = 409, details) {
  if (!condition) throw new GameError(code, status, details);
}
export const utc = (now = Date.now()) => new Date(now).toISOString();
