// Actual pinned DSH/Humanity, isolated homes, scripted loopback provider only.
// No real model inference, Minecraft, GPU, avatars, official client or broadcast.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { DshHost } from '../backend/dsh-bridge/host.mjs';
import { initialPersona } from '../backend/dsh-bridge/persona.mjs';
import { loadPolicy } from '../backend/dsh-bridge/policy.mjs';

const root = resolve(process.argv[2]), runtime = resolve(process.argv[3]), output = resolve(process.env.MC_INTENT_EVIDENCE_ROOT);
assert(relative(root, output) && !relative(root, output).startsWith('..')); mkdirSync(output, { recursive: true });
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const outcome = promise => promise.then(value => ({ value }), error => ({ error }));
const plans = new Map(), work = [], sockets = new Set(); let active = 0, maximumActive = 0, host, boots = 0;
const report = { result: 'FAIL', classification: 'ACTUAL_PINNED_DSH_HUMANITY_FAIR_QUEUE_WITH_SCRIPTED_LOOPBACK_PROVIDER',
  cases: [], requests: [], real_model: false, real_minecraft: false, official_client: false, public_broadcast: false };
const save = () => writeFileSync(join(output, 'native-dsh-model-queue-probe.json'), JSON.stringify(report, null, 2) + '\n');
const hardDeadline = setTimeout(() => { report.error = 'NATIVE_QUEUE_PROBE_DEADLINE'; save(); process.exit(1); }, 55000);
const server = createServer(async (req, res) => {
  active++; maximumActive = Math.max(maximumActive, active); let plan;
  res.once('close', () => { active--; plan?.release.resolve(); });
  try {
    assert.equal(req.url, '/v1/chat/completions'); const chunks = []; for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks)), source = JSON.stringify(body.messages);
    plan = [...plans.values()].find(value => source.includes(value.id)); assert(plan, 'unknown scripted request');
    report.requests.push({ id: plan.id, purpose: plan.purpose, tools: body.tools?.map(t => t.function.name) || [] });
    plan.entered.resolve(); if (plan.held) await plan.release.promise;
    if (res.destroyed) return;
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    for (const choice of [{ delta: { role: 'assistant', content: '本地协议检查完成。' }, finish_reason: null }, { delta: {}, finish_reason: 'stop' }])
      res.write('data: ' + JSON.stringify({ id: plan.id, object: 'chat.completion.chunk', model: 'local-scripted-fixture', choices: [{ index: 0, ...choice }] }) + '\n\n');
    res.end('data: [DONE]\n\n');
  } catch (error) { report.server_error = error.code || error.message; res.destroy(); }
});
server.on('connection', socket => { sockets.add(socket); socket.once('close', () => sockets.delete(socket)); });
await new Promise(r => server.listen(0, '127.0.0.1', r));
const origin = 'http://127.0.0.1:' + server.address().port;
const snapshot = { revision: 'native-queue-fixture', model: 'local-scripted-fixture', protocol: 'chat_completions',
  baseUrl: origin + '/v1', systemPrompt: '', getApiKey: () => 'unused-local-fixture' };
const originalFetch = globalThis.fetch;
globalThis.fetch = (input, options) => {
  const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
  assert.equal(url.origin, origin); assert.equal(url.pathname, '/v1/chat/completions'); return originalFetch(input, options);
};
async function waitFor(promise) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(Error('LOCAL_PROVIDER_ENTRY_DEADLINE')), 10000); })]); }
  finally { clearTimeout(timer); }
}
async function startHost() {
  const policy = structuredClone(loadPolicy(root));
  policy.deployment.dsh_home_relative_path = relative(root, join(output, 'isolated-dsh-' + (++boots))).replaceAll('\\', '/');
  host = await new DshHost(root, runtime, policy).start();
  const persona = initialPersona(root); await host.publishCharacter(persona.document, persona.version);
}
function generate(purpose, { held = false, ...extra } = {}) {
  const id = randomUUID(), plan = { id, purpose, held, entered: deferred(), release: deferred() };
  plans.set(id, plan);
  const sessionId = (purpose === 'audience_intent' ? 'mc-intent-' : 'native-queue-') + id;
  const result = outcome(host.generate({ purpose, sessionId, snapshot, input: 'isolated-queue-source-' + id,
    maxTokens: 64, tools: async () => ({}), ...extra }));
  work.push(result); return { ...plan, sessionId, result };
}
function empty() {
  assert.equal(host.active.size, 0); assert.equal(host.modelCalls.size, 0);
  assert.equal(host.foregroundQueued || 0, 0); assert.equal(host.modelQueue.view().pending, 0);
}
async function speech() { const value = generate('speech'); assert.equal((await value.result).error, undefined); return value; }
try {
  await startHost();
  await speech(); await speech();
  const plan = generate('game_plan', { held: true }); await waitFor(plan.entered.promise);
  assert.equal(host.modelQueue.view().protected, true); const owner = host.gamePlanAbort;
  const ordinary = generate('speech'); assert.equal(owner.signal.aborted, false);
  const danger = generate('speech', { isCritical: () => true }); assert.equal(owner.signal.aborted, true);
  assert.equal((await plan.result).error?.code, 'MODEL_PREEMPTED');
  assert.equal((await danger.result).error, undefined); assert.equal((await ordinary.result).error, undefined);
  assert.deepEqual(report.requests.slice(-2).map(row => row.id), [danger.id, ordinary.id]); empty(); await host.close();
  report.cases.push({ id: 'native_protected_planner_ordinary_wait_and_critical_preemption', result: 'PASS' });

  await startHost();
  const intent = generate('audience_intent', { held: true }); await waitFor(intent.entered.promise);
  assert.equal(host.modelQueue.view().protected, false); const response = generate('speech');
  assert.equal((await intent.result).error?.code, 'MODEL_PREEMPTED'); assert.equal((await response.result).error, undefined);
  assert(!(await host.ctx.sessionPersistence.list()).some(row => row.header.id === intent.sessionId));
  const request = report.requests.find(row => row.id === intent.id);
  assert.deepEqual(request.tools, ['stream_audience_intent_result']); empty(); await host.close();
  report.cases.push({ id: 'native_intent_preemption_disposes_and_purges_before_next_speech', result: 'PASS' });

  await startHost(); await speech(); await speech();
  const protectedWork = generate('game_plan', { held: true }); await waitFor(protectedWork.entered.promise);
  assert.equal(host.modelQueue.view().protected, true);
  const controller = new AbortController(), waiting = generate('operator_private', { signal: controller.signal });
  controller.abort(new DOMException('original deadline', 'TimeoutError'));
  assert.equal((await waiting.result).error?.code, 'MODEL_TIMEOUT');
  const normal = generate('speech'), beforeClose = report.requests.length;
  await host.close(); assert.equal((await protectedWork.result).error?.code, 'MODEL_CANCELLED');
  assert.equal((await normal.result).error?.code, 'MODEL_CANCELLED'); empty();
  assert.equal(report.requests.length, beforeClose); assert(!report.requests.some(row => row.id === waiting.id || row.id === normal.id));
  report.cases.push({ id: 'native_waiter_deadline_and_protected_shutdown_drain', result: 'PASS' });
  assert.equal(report.requests.length, 10); assert.equal(maximumActive, 1); assert.equal(report.server_error, undefined);
  report.result = 'PASS';
} catch (error) { report.error = String(error.stack || error); throw error; }
finally {
  host?.stopAdmission(); for (const plan of plans.values()) plan.release.resolve();
  try { await Promise.all(work); await host?.close(); }
  finally {
    globalThis.fetch = originalFetch; server.closeAllConnections(); for (const socket of sockets) socket.destroy();
    await new Promise(r => server.close(r)); clearTimeout(hardDeadline);
    report.native_boots = boots; report.maximum_concurrent_provider_requests = maximumActive;
    report.native_host_closed = !host?.ready; report.remaining_http_sockets = sockets.size;
    report.recorded_at = new Date().toISOString(); save();
    console.log(JSON.stringify({ result: report.result, cases: report.cases.length, requests: report.requests.length, evidence: join(output, 'native-dsh-model-queue-probe.json') }));
  }
}
