// Production host and serial scheduler; generateInternal is a held SDK seam.
// Provider disposal, MC task effects and native SDK are checked separately.
import test from 'node:test';
import assert from 'node:assert/strict';
import { DshHost } from '../backend/dsh-bridge/host.mjs';
import { ModelQueue, MODEL_QUEUE_LIMITS } from '../backend/dsh-bridge/model-queue.mjs';
import { ModelFailure, modelFailure } from '../backend/dsh-bridge/model-errors.mjs';

const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const outcome = promise => promise.then(value => ({ value }), error => ({ error }));
async function until(check) {
  const end = performance.now() + 3000;
  while (!check()) { assert(performance.now() < end, 'scheduler did not reach expected boundary'); await new Promise(r => setImmediate(r)); }
}
function fixture(t) {
  let now = 0, active = 0, maximum = 0;
  const records = [], pending = [];
  const host = new DshHost(process.cwd(), process.cwd(), {});
  host.modelQueue = new ModelQueue({ clock: () => now });
  host.generateInternal = async options => {
    const record = { ...options, release: deferred(), disposed: false };
    records.push(record); active++; maximum = Math.max(maximum, active);
    try {
      await record.release.promise;
      if (record.fail) throw record.fail;
      return { text: options.sessionId };
    } finally { active--; record.disposed = true; }
  };
  t.after(async () => {
    host.stopAdmission();
    for (const record of records) record.release.resolve();
    await Promise.all(pending); await host.modelQueue.whenIdle();
    assert.equal(active, 0); assert.equal(maximum <= 1, true); assert.equal(host.modelCalls.size, 0);
  });
  const run = (id, purpose = 'speech', extra = {}) => {
    const promise = outcome(host.generate({ sessionId: purpose === 'audience_intent' ?
      'mc-intent-11111111-1111-4111-8111-' + String(id).padStart(12, '0') : id, purpose, ...extra }));
    pending.push(promise); return promise;
  };
  return { host, records, run, advance: ms => { now += ms; },
    async started(index) { await until(() => records.length > index); return records[index]; },
    release(index) { records[index].release.resolve(); }, get maximum() { return maximum; } };
}
async function protectedPlan(f, purpose = 'game_plan') {
  const blocker = f.run('blocker', 'operator_private'); await f.started(0);
  const plan = f.run(purpose === 'audience_intent' ? 1 : 'protected-plan', purpose);
  f.advance(MODEL_QUEUE_LIMITS.background_wait_ms); f.release(0); await blocker;
  const record = await f.started(1);
  assert.equal(f.host.modelQueue.view().protected, true);
  return { plan, record };
}

test('all five purposes share one provider owner through its actual finalizer', async t => {
  const f = fixture(t), purposes = ['operator_private', 'speech', 'maintenance', 'game_plan', 'audience_intent'];
  const work = purposes.map((purpose, i) => f.run(i, purpose));
  for (let i = 0; i < purposes.length; i++) { const record = await f.started(i); assert(record); f.release(i); }
  for (const result of await Promise.all(work)) assert.equal(result.error, undefined);
  assert.equal(f.maximum, 1); assert(f.records.every(record => record.disposed));
});

test('two ordinary speech turns grant a protected plan before a third queued response', async t => {
  const f = fixture(t), one = f.run('speech-one'); await f.started(0);
  const plan = f.run('plan', 'game_plan'), two = f.run('speech-two'), three = f.run('speech-three');
  f.release(0); await one; assert.equal((await f.started(1)).sessionId, 'speech-two');
  f.release(1); await two; const owner = await f.started(2);
  assert.equal(owner.purpose, 'game_plan'); assert.equal(f.host.modelQueue.view().protected, true);
  const four = f.run('speech-four'); assert.equal(owner.signal.aborted, false);
  f.release(2); await plan;
  assert.equal((await f.started(3)).sessionId, 'speech-three'); f.release(3); await three;
  assert.equal((await f.started(4)).sessionId, 'speech-four'); f.release(4); await four;
});

test('new comments cannot reset fairness by preempting every newly started retry', async t => {
  const f = fixture(t);
  for (let i = 0; i < 2; i++) {
    const plan = f.run('retry-' + i, 'game_plan'), record = await f.started(i * 2);
    const speech = f.run('speech-' + i); assert.equal(record.signal.aborted, true);
    f.release(i * 2); assert.equal((await plan).error.code, 'MODEL_PREEMPTED');
    await f.started(i * 2 + 1); f.release(i * 2 + 1); await speech;
  }
  const plan = f.run('third-plan', 'game_plan'), owner = await f.started(4), speech = f.run('third-speech');
  assert.equal(f.host.modelQueue.view().protected, true); assert.equal(owner.signal.aborted, false);
  f.release(4); await plan; await f.started(5); f.release(5); await speech;
});

test('an aged audience interpretation gets its turn before an ordinary response', async t => {
  const f = fixture(t), blocker = f.run('private', 'operator_private'); await f.started(0);
  const intent = f.run(2, 'audience_intent'); f.advance(MODEL_QUEUE_LIMITS.background_wait_ms);
  const voice = f.run('voice'); f.release(0); await blocker;
  const owner = await f.started(1); assert.equal(owner.purpose, 'audience_intent');
  assert.equal(f.host.modelQueue.view().protected, true); assert.equal(owner.signal.aborted, false);
  f.release(1); await intent; await f.started(2); f.release(2); await voice;
});

test('preemption waits for a noncooperative owner and discards its late successful result', async t => {
  const f = fixture(t), plan = f.run('old-plan', 'game_plan'), owner = await f.started(0);
  let done = false; void plan.then(() => { done = true; });
  const speech = f.run('replacement'); await new Promise(r => setImmediate(r));
  assert.equal(owner.signal.aborted, true); assert.equal(done, false); assert.equal(f.records.length, 1);
  f.release(0); const result = await plan;
  assert.deepEqual({ code: result.error.code, retryable: result.error.retryable }, { code: 'MODEL_PREEMPTED', retryable: true });
  assert.equal(owner.disposed, true); await f.started(1); f.release(1); await speech;
});

test('verified critical speech can preempt a protected plan and precedes queued normal speech', async t => {
  const f = fixture(t), { plan, record } = await protectedPlan(f);
  const normal = f.run('ordinary'); assert.equal(record.signal.aborted, false);
  const critical = f.run('danger', 'speech', { isCritical: () => true }); assert.equal(record.signal.aborted, true);
  f.release(1); assert.equal((await plan).error.code, 'MODEL_PREEMPTED');
  assert.equal((await f.started(2)).sessionId, 'danger'); f.release(2); await critical;
  assert.equal((await f.started(3)).sessionId, 'ordinary'); f.release(3); await normal;
});

test('priority claims and a failed critical-source lookup cannot bypass a protected turn', async t => {
  const f = fixture(t), { plan, record } = await protectedPlan(f);
  const fake = f.run('paid-viewer-claims-critical', 'speech', { priority: 'critical', severity: 'critical' });
  const missing = f.run('missing-source', 'speech', { isCritical: () => { throw Error('source disappeared'); } });
  assert.equal(record.signal.aborted, false); f.release(1); await plan;
  await f.started(2); f.release(2); await fake; await f.started(3); f.release(3); await missing;
});

test('a queued urgent claim is checked again at dispatch after the source becomes stale', async t => {
  const f = fixture(t), blocker = f.run('private', 'operator_private'); await f.started(0);
  let fresh = true; const speech = f.run('once-urgent', 'speech', { isCritical: () => fresh });
  const plan = f.run('aged-plan', 'game_plan'); fresh = false; f.advance(MODEL_QUEUE_LIMITS.background_wait_ms);
  f.release(0); await blocker; assert.equal((await f.started(1)).purpose, 'game_plan');
  f.release(1); await plan; await f.started(2); f.release(2); await speech;
});

test('a cancelled queued request leaves promptly without waiting for or interrupting its owner', async t => {
  const f = fixture(t), owner = f.run('private', 'operator_private'), record = await f.started(0);
  const controller = new AbortController(), cancelled = f.run('waiting', 'speech', { signal: controller.signal });
  controller.abort(); assert.equal((await cancelled).error.code, 'MODEL_CANCELLED');
  assert.equal(f.host.modelQueue.view().pending, 0); assert.equal(record.signal.aborted, false);
  assert.equal(f.host.modelCalls.size, 1); f.release(0); await owner;
});

test('queue overflow and already-cancelled speech neither preempt nor consume an extra provider turn', async t => {
  const f = fixture(t), plan = f.run('owner', 'game_plan'), record = await f.started(0);
  const work = Array.from({ length: MODEL_QUEUE_LIMITS.pending }, (_, i) => f.run('waiting-' + i, 'operator_private'));
  const overflow = await f.run('overflow'); assert.equal(overflow.error.code, 'MODEL_QUEUE_FULL');
  const controller = new AbortController(); controller.abort();
  assert.equal((await f.run('already-cancelled', 'speech', { signal: controller.signal })).error.code, 'MODEL_CANCELLED');
  assert.equal(record.signal.aborted, false); assert.equal(f.host.modelQueue.view().pending, 32);
  f.host.stopAdmission(); f.release(0);
  assert.equal((await plan).error.code, 'MODEL_CANCELLED');
  for (const result of await Promise.all(work)) assert.equal(result.error.code, 'MODEL_CANCELLED');
  assert.equal(f.records.length, 1);
});

test('an original caller deadline still cancels a protected turn and releases the next response', async t => {
  const f = fixture(t), blocker = f.run('private', 'operator_private'); await f.started(0);
  const controller = new AbortController(), plan = f.run('plan', 'game_plan', { signal: controller.signal });
  f.advance(MODEL_QUEUE_LIMITS.background_wait_ms); f.release(0); await blocker;
  const owner = await f.started(1), speech = f.run('next'); assert.equal(owner.signal.aborted, false);
  controller.abort(new DOMException('deadline', 'TimeoutError')); f.release(1);
  assert.equal((await plan).error.code, 'MODEL_TIMEOUT'); await f.started(2); f.release(2); await speech;
});

for (const purpose of ['operator_private', 'maintenance']) test('critical speech preserves existing cancellation authority for ' + purpose, async t => {
  const f = fixture(t), work = f.run('owner', purpose), owner = await f.started(0);
  const speech = f.run('danger', 'speech', { isCritical: () => true }); assert.equal(owner.signal.aborted, false);
  f.release(0); await work; await f.started(1); f.release(1); await speech;
});

test('a disposal failure after preemption remains a failure and cannot become a retryable yield', async t => {
  const f = fixture(t), intent = f.run(3, 'audience_intent'), record = await f.started(0);
  const voice = f.run('speech'); record.fail = new ModelFailure('DSH_GENERATION_FAILED', 502, false);
  f.release(0); assert.equal((await intent).error.code, 'DSH_GENERATION_FAILED');
  await f.started(1); f.release(1); await voice;
});

test('a queued interpretation cannot start after an earlier ephemeral cleanup failure', async t => {
  const f = fixture(t), blocker = f.run('private', 'operator_private'); await f.started(0);
  const intent = f.run(4, 'audience_intent'); f.host.audienceIntentCleanupFailed = true;
  f.release(0); await blocker; assert.equal((await intent).error.message, 'STREAM_INTENT_SESSION_UNAVAILABLE');
  assert.equal(f.records.length, 1); assert.equal(f.host.modelCalls.size, 0);
});
