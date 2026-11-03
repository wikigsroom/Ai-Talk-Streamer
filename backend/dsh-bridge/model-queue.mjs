import { ModelFailure, modelFailure } from './model-errors.mjs';

export const MODEL_QUEUE_LIMITS = Object.freeze({ pending: 32, speech_burst: 2, background_wait_ms: 3000 });
const PREEMPTIBLE = new Set(['game_plan', 'audience_intent', 'vision']);

// One provider owner, including cancellation and SDK disposal. A rejected or
// cancelled waiter never consumes a turn or interrupts the current owner.
export class ModelQueue {
  constructor({ clock = () => performance.now() } = {}) {
    this.clock = clock; this.pending = []; this.active = null; this.speechStarts = 0;
    this.idle = Promise.resolve(); this.resolveIdle = null; this.closed = false;
  }
  critical(entry) {
    if (entry.purpose !== 'speech' || typeof entry.isCritical !== 'function') return false;
    try { return entry.isCritical() === true; } catch { return false; }
  }
  enqueue({ purpose, signal, isCritical, run }) {
    if (signal?.aborted) return Promise.reject(modelFailure(null, { signal }));
    if (this.closed) return Promise.reject(new ModelFailure('DSH_HOST_CLOSING', 503, false));
    if (this.pending.length >= MODEL_QUEUE_LIMITS.pending)
      return Promise.reject(new ModelFailure('MODEL_QUEUE_FULL', 429, true));
    if (!this.resolveIdle) this.idle = new Promise(resolve => { this.resolveIdle = resolve; });
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    const entry = { purpose, signal, isCritical, run, resolve, reject, admitted: this.clock(),
      controller: new AbortController(), preempted: false, protected: false };
    entry.abort = () => {
      if (this.active === entry) entry.controller.abort(signal.reason);
      else {
        const index = this.pending.indexOf(entry);
        if (index < 0) return;
        this.pending.splice(index, 1); signal.removeEventListener('abort', entry.abort);
        reject(modelFailure(null, { signal })); this.finishIdle();
      }
    };
    this.pending.push(entry);
    signal?.addEventListener('abort', entry.abort, { once: true });
    const owner = this.active;
    if (purpose === 'speech' && owner && PREEMPTIBLE.has(owner.purpose) &&
        (!owner.protected || this.critical(entry)) && !owner.controller.signal.aborted) {
      owner.preempted = true; owner.controller.abort();
    }
    this.pump(); return promise;
  }
  pump() {
    if (this.active || !this.pending.length) { this.finishIdle(); return; }
    const critical = this.pending.find(entry => this.critical(entry));
    const background = this.pending.find(entry => entry.purpose !== 'speech');
    const protectedTurn = background && (this.speechStarts >= MODEL_QUEUE_LIMITS.speech_burst ||
      this.clock() - background.admitted >= MODEL_QUEUE_LIMITS.background_wait_ms);
    const entry = critical || (protectedTurn ? background :
      this.pending.find(entry => entry.purpose === 'speech') || background);
    entry.protected = entry === background && !!protectedTurn;
    this.pending.splice(this.pending.indexOf(entry), 1); this.active = entry;
    if (entry.purpose === 'speech') this.speechStarts = Math.min(MODEL_QUEUE_LIMITS.speech_burst, this.speechStarts + 1);
    // Keep speech debt across preempted background attempts. Resetting it when
    // a plan merely starts would let one new comment starve every retry.
    void this.execute(entry);
  }
  async execute(entry) {
    try {
      const value = await entry.run(entry.controller.signal);
      if (entry.controller.signal.aborted) throw modelFailure(null, { signal: entry.controller.signal });
      entry.resolve(value);
    } catch (error) {
      entry.reject(entry.preempted && !entry.signal?.aborted && error?.code === 'MODEL_CANCELLED'
        ? new ModelFailure('MODEL_PREEMPTED', 409, true) : error);
    } finally {
      entry.signal?.removeEventListener('abort', entry.abort);
      if (entry.purpose !== 'speech' && !entry.preempted && !entry.controller.signal.aborted) this.speechStarts = 0;
      this.active = null; this.pump();
    }
  }
  finishIdle() {
    if (this.active || this.pending.length || !this.resolveIdle) return;
    const resolve = this.resolveIdle; this.resolveIdle = null; resolve();
  }
  whenIdle() { return this.idle; }
  close() {
    this.closed = true;
    for (const entry of this.pending.splice(0)) {
      entry.signal?.removeEventListener('abort', entry.abort);
      entry.reject(new ModelFailure('MODEL_CANCELLED', 409, false));
    }
    this.active?.controller.abort(); this.finishIdle();
  }
  view() {
    return { pending: this.pending.length, limit: MODEL_QUEUE_LIMITS.pending,
      active_purpose: this.active?.purpose || null, protected: this.active?.protected || false };
  }
}
