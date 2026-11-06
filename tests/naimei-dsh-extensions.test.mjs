import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { resolve, join } from 'node:path';
import { writeFileSync, mkdirSync } from 'node:fs';
import { DshHost } from '../backend/dsh-bridge/host.mjs';
import { initialPersona } from '../backend/dsh-bridge/persona.mjs';
import { loadPolicy } from '../backend/dsh-bridge/policy.mjs';
import { requireLocalModel } from '../backend/dsh-bridge/extensions.mjs';
import { StateStore } from '../backend/memory/store.mjs';
import { StreamState } from '../backend/dsh-bridge/state.mjs';
import { StreamBridge } from '../backend/dsh-bridge/server.mjs';
import { MemoryService } from '../backend/memory/service.mjs';
import { MaintenanceScheduler } from '../backend/memory/scheduler.mjs';
import { Auth } from '../backend/dsh-bridge/auth.mjs';
import { digest } from '../backend/dsh-bridge/channel.mjs';
import { NaimeiLocalChannel } from '../backend/dsh-bridge/local-model.mjs';

const root = resolve(import.meta.dirname, '..'), runtime = join(root, 'tools/dsh');
const policy = structuredClone(loadPolicy(root, 'configs/naimei/bridge-policy.json'));
policy.deployment.dsh_home_relative_path = 'state/naimei-extension-test-' + Date.now();
const requests = [], probes = [];
let registeredChecks = 0, passedChecks = 0;
function verifiedTest(title, run) {
  registeredChecks++;
  return test(title, async context => { await run(context); passedChecks++; });
}
let server, host, db, snapshot;
before(async () => {
  server = createServer(async (req, res) => {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks)); requests.push(body);
    const system = body.messages.filter(m => m.role === 'system').map(m => m.content).join('\n');
    const mood = system.includes('moodDelta');
    const first = !body.messages.some(m => m.role === 'tool');
    const delta = mood ? { role: 'assistant', content: JSON.stringify({ moodDelta: 6, dims: { happy: 6 }, reason: '观众夸了奶妹刚才的回应，奶妹当时挺开心', confidence: 90 }) }
      : first ? { role: 'assistant', tool_calls: [{ index: 0, id: 'call_meme', type: 'function', function: { name: 'search_meme_wiki', arguments: JSON.stringify({ data: JSON.stringify({ query: '杂鱼' }) }) } }] }
      : { role: 'assistant', content: '我是奶妹，今天想聊什么？' };
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    for (const data of [{ choices: [{ index: 0, delta, finish_reason: null }] },
      { choices: [{ index: 0, delta: {}, finish_reason: !mood && first ? 'tool_calls' : 'stop' }], usage: { prompt_tokens: 100, completion_tokens: 20, total_tokens: 120 } }]) {
      res.write('data: ' + JSON.stringify({ id: 'naimei-local-probe', object: 'chat.completion.chunk', created: 1, model: 'probe', ...data }) + '\n\n');
    }
    res.end('data: [DONE]\n\n');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  host = await new DshHost(root, runtime, policy).start();
  const persona = initialPersona(root, 'naimei'); await host.publishCharacter(persona.document, persona.version);
  snapshot = { revision: 'test', model: 'probe', protocol: 'chat_completions', baseUrl: 'http://127.0.0.1:' + server.address().port + '/v1', systemPrompt: '', getApiKey: () => 'test' };
  db = new StateStore(join(root, policy.deployment.dsh_home_relative_path, 'extensions-test.sqlite3'));
}, { timeout: 60000 });
after(async () => {
  const evidence = { passed: registeredChecks === passedChecks, checks: { passed: passedChecks, total: registeredChecks },
    kind: 'native_dsh_with_controlled_local_http_model', sources: host?.extensions?.status().sources,
    probes, request_count: requests.length, cloud_inference_exercised: false, model_weights_added_bytes: 0 };
  const folder = join(root, 'outputs/naimei/dsh-extensions'); mkdirSync(folder, { recursive: true });
  writeFileSync(join(folder, 'native-probe.json'), JSON.stringify(evidence, null, 2));
  await host?.close(); db?.close(); if (server) await new Promise(resolve => server.close(resolve));
});

verifiedTest('all seven pinned sources load with actual native DSH and locked Naimei identity', () => {
  assert.equal(host.extensions.status().sources.length, 7);
  assert.ok(host.extensions.status().sources.every(s => s.applied));
  assert.equal(host.port.readPersona().publication.character_id, 'naimei');
  assert.ok(host.extensions.humanizerSkill.includes('绝不编造事实'));
});
verifiedTest('both real dictionaries answer through a single tool without network access', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = () => { throw new Error('unexpected network'); };
  try {
    const value = await host.extensions.lookup('杂鱼健身');
    assert.equal(value.found, true);
    assert.equal(value.results.length, 1, 'overlapping titles must not duplicate live context');
    assert.deepEqual(new Set(value.results.flatMap(r => r.sources)), new Set(['memewiki-thawline', 'memewiki-liujelly']));
    assert.equal((await host.extensions.lookup('没有收录的测试词xyz781234')).found, false);
    await assert.rejects(host.extensions.tool('soul_update', {}, {}), /EXTENSION_TOOL_DENIED/);
  } finally { globalThis.fetch = original; }
});
verifiedTest('actual DSH prompt contains soul and humanizer; only reviewed tools reach the local model', async () => {
  const result = await host.generate({ sessionId: 'naimei-extension-probe-' + Date.now(), snapshot,
    input: '杂鱼是什么梗？', tools: async () => ({ public: [], viewer: [] }), onProbe: p => probes.push(p) });
  assert.equal(result.text, '我是奶妹，今天想聊什么？');
  assert.ok(probes.every(p => p.has_persona && p.has_soul && p.has_humanizer));
  assert.deepEqual(probes[0].tools.sort(), ['search_meme_wiki', 'soul_read', 'stream_memory_propose', 'stream_memory_recall']);
  assert.ok(!JSON.stringify(requests).includes('林知夏'));
});
verifiedTest('cloud model addresses are rejected before any request is made', async () => {
  for (const baseUrl of ['https://api.deepseek.com/v1', 'https://example.com', 'http://127.0.0.1.evil.test', 'http://192.168.evil.test', 'file:///tmp/model']) {
    assert.throws(() => requireLocalModel({ baseUrl }), /NAIMEI_LOCAL_MODEL_REQUIRED/);
  }
  for (const baseUrl of ['http://127.0.0.1:8080/v1', 'http://192.168.196.209:1234/v1', 'http://localhost:11434/v1']) assert.doesNotThrow(() => requireLocalModel({ baseUrl }));
  const count = requests.length;
  await assert.rejects(host.generate({ sessionId: 'bad-cloud', snapshot: { ...snapshot, baseUrl: 'https://example.com' }, input: '你好', tools: async () => ({}) }), /NAIMEI_LOCAL_MODEL_REQUIRED/);
  assert.equal(requests.length, count);
});
verifiedTest('upstream fish ranking selects relevant approved records without writing a second store', () => {
  const now = Date.now();
  const rows = [{ memory_id: 'tea', content: '观众喜欢喝绿茶和乌龙茶', fact_key: 'preference.drink', pinned: 1, updated_at: new Date(now).toISOString() },
    { memory_id: 'coffee', content: '观众不喝咖啡', fact_key: 'preference.coffee', pinned: 0, updated_at: new Date(now - 90 * 86400000).toISOString() }];
  const ranked = host.extensions.rankMemory(rows, '喝绿茶还是乌龙茶', now);
  assert.ok(ranked.some(r => r.memory_id === 'tea'));
  assert.ok(ranked.every(r => rows.includes(r)));
});
verifiedTest('upstream proactive scheduler respects bridge readiness and only emits queued requests', async () => {
  let ready = false; const queued = [];
  host.extensions.attachBridge({ db, canSpeak: () => ready, enqueue: async message => queued.push(message), loadHistory: async () => [] });
  await host.extensions.scheduler.掷一次('测试', '真发'); assert.equal(queued.length, 0);
  ready = true; await host.extensions.scheduler.掷一次('测试', '真发'); assert.equal(queued.length, 1);
  assert.equal(queued[0].source.kind, 'speak-up');
  assert.equal(queued[0].role, 'user');
});
verifiedTest('upstream mood applies confident changes, rejects uncertainty and persists within the canonical store', () => {
  const initial = host.extensions.publicMood().mood;
  const uncertain = host.extensions.mood.parseDelta(JSON.stringify({ moodDelta: 10, dims: { happy: 10 }, confidence: 20 }), '观众');
  assert.equal(host.extensions.applyMood(uncertain), false); assert.equal(host.extensions.publicMood().mood, initial);
  const clear = host.extensions.mood.parseDelta(JSON.stringify({ moodDelta: 6, dims: { happy: 6 }, confidence: 90 }), '观众');
  assert.equal(host.extensions.applyMood(clear), true); assert.ok(host.extensions.publicMood().mood > initial);
  assert.ok(db.get("SELECT value_json FROM runtime_meta WHERE key='naimei.extensions.mood.public'"));
});
verifiedTest('the original feiyu judge runs through the pinned DSH adapter and accounts for its local call', async () => {
  const calls = [];
  const delta = await host.judgeMood({ snapshot, input: '奶妹刚才接梗挺有意思', reply: '嘿嘿，这句我接住了。',
    signal: AbortSignal.timeout(10000), onCall: call => { calls.push(call); return 'mood-attempt'; } });
  assert.equal(delta?.confidence, 90);
  assert.equal(delta?.moodDelta, 6);
  assert.deepEqual(calls.map(call => call.phase), ['reserve', 'sent', 'settle']);
});
verifiedTest('local model settings stay separate and never expose saved keys', () => {
  const local = new NaimeiLocalChannel(join(root, policy.deployment.dsh_home_relative_path, 'settings-test'));
  const value = local.save({ base_url: snapshot.baseUrl, model: 'probe', api_key: 'private-test-key' });
  assert.equal(value.local_only, true);
  assert.ok(!JSON.stringify([value, local.publicInfo()]).includes('private-test-key'));
  assert.ok(!local.file.endsWith('configs/channel.env'));
  assert.throws(() => local.save({ base_url: 'https://example.com', model: 'probe' }), /NAIMEI_LOCAL_MODEL_REQUIRED/);
});
verifiedTest('proactive speech uses the real queue and mood waits for complete playback receipts', async () => {
  const state = new StreamState(db, policy, initialPersona(root, 'naimei').version);
  const auth = new Auth(root, db, state), op = auth.resolve(), delivered = [];
  const memory = new MemoryService(db, state, policy, host.port);
  const bridge = Object.assign(Object.create(StreamBridge.prototype), { root, runtime, policy, db, state, auth, host, memory,
    ready: true, closed: false, administration: { locked: false }, controllers: new Map(),
    compatibility: { passed: true, provider_revision: snapshot.revision }, probes: [],
    channel: { snapshot: () => snapshot, publicInfo: () => ({ revision: snapshot.revision }) },
    mediaHealth: { tts_ready: true, avatar_ready: true, natural_state: 'idle', character_speaking: false }, mediaCheckedAt: Date.now(),
    mediaCommand: async (action, value) => { if (action === 'speak') delivered.push(value); } });
  bridge.scheduler = new MaintenanceScheduler(db, state, memory, policy, async () => {});
  bridge.attachExtensions();
  const broadcast = state.createBroadcast(op);
  const lease = state.claimAuthority(op, broadcast.broadcast_id, 'native-test-playback');
  state.readyBroadcast(broadcast.broadcast_id, true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(bridge.canSpeakUp(), false);
  bridge.automaticSpeechEnabled = true;
  assert.equal(bridge.canSpeakUp(), true);
  await host.extensions.scheduler.掷一次('原生队列测试', '真发');
  const deadline = Date.now() + 10000;
  while (!delivered.length && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 25));
  assert.equal(delivered.length, 1);
  const utterance = delivered[0], request = state.request(utterance.request_id);
  assert.equal(request.mode, 'chat'); assert.equal(state.input(request).source.collector, 'dsh-speak-up');
  assert.equal(memory.eligibleEvents(broadcast.broadcast_id, 'public').length, 0);
  assert.equal(bridge.canSpeakUp(), false);
  assert.ok(!bridge.pendingMood);
  state.audioReady({ ...utterance, valid_sample_count: 640, audio_sha256: digest('controlled-audio') });
  state.mediaMap({ ...utterance, valid_sample_count: 640, transport_instance_id: 'extension-test',
    ranges: [{ packet_seq: 1, packet_offset: 0, sample_start: 0, sample_count: 640 }], final: true });
  const receipt = { ...utterance, consumer_id: lease.consumer_id, lease_id: lease.lease_id, authority_epoch: lease.authority_epoch,
    transport_instance_id: 'extension-test' };
  state.receipt(op, { ...receipt, contiguous_played_samples: 320, natural_end: false, receipt_sequence: 1 });
  await new Promise(resolve => setImmediate(resolve)); assert.ok(!bridge.pendingMood);
  state.receipt(op, { ...receipt, contiguous_played_samples: 640, natural_end: true, receipt_sequence: 2 });
  await new Promise(resolve => setImmediate(resolve)); assert.equal(bridge.pendingMood.event.request_id, request.request_id);
  const before = host.extensions.publicMood().mood;
  await bridge.updateExtensionMood();
  assert.ok(host.extensions.publicMood().mood > before);
  assert.equal(memory.eligibleEvents(broadcast.broadcast_id, 'public').filter(e => e.event_type === 'input.accepted').length, 0);
  const count = db.get('SELECT COUNT(*) n FROM requests').n;
  await host.extensions.scheduler.掷一次('原生队列测试', '自动');
  assert.equal(db.get('SELECT COUNT(*) n FROM requests').n, count, 'natural completion starts proactive cooldown');
  state.pause(op); assert.equal(bridge.canSpeakUp(), false);
  bridge.closed = true; bridge.scheduler.close(); db.off('event', bridge.extensionListener);
});
