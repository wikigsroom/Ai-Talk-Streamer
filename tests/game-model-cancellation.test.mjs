// Execute the production DSH registration, model queue, planner and game tools.
// Agent/provider seams and the MC peer are explicit local doubles: no model,
// native DSH boot, Minecraft, GPU, browser or public broadcast is started.
import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { DshHost } from '../backend/dsh-bridge/host.mjs';
import { policyTemplate } from '../backend/dsh-bridge/policy.mjs';
import { gameFixture, until } from './game-fixture.mjs';
import { narrationFixture } from './game-narration-fixture.mjs';

const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const goal = { skill: 'gather', item_id: 'minecraft:oak_log', count: 4 };
const snapshot = { revision: 'LOCAL_ADAPTER_FIXTURE', model: 'LOCAL_ADAPTER_FIXTURE', protocol: 'chat_completions',
  baseUrl: 'http://127.0.0.1:1', systemPrompt: '', getApiKey: () => 'local-unused-fixture' };

function adapter(root, run) {
  const host = new DshHost(root, join(root, 'unused-runtime'), policyTemplate);
  const sessions = [], executions = [];
  host.ready = true; host.renderPersona = () => '林知夏'; host.defineTool = definition => definition;
  host.port = { readPersona: () => ({ document: {} }), requestMemorySnapshot: () => ({ text: 'public fixture' }), flush: async () => {} };
  host.environment = { createLaunchEnvironmentSnapshot: value => value };
  host.pi = {}; host.llm = { createUserMessage: value => value };
  host.purgeAudienceIntentSessions = async () => {};
  host.ctx = { fiber: { dispose: async () => {} }, agentPresets: { mount: async () => {} }, agents: { create: async specification => {
    const tools = new Map(), events = new Map(), execution = new AbortController(); let work;
    const record = { session_id: specification.sessionId, execution, disposed: false, concluded: 0 };
    const agent = { session: { deriveMessages: () => [{ role: 'assistant', content: [{ type: 'text', text: '本地接口检查' }] }] },
      followup() {
        work = Promise.resolve().then(async () => {
          await run({ sessionId: specification.sessionId, tools, execution, record });
          events.get('session/event')?.({ id: specification.sessionId }, { type: 'assistant/message' });
          events.get('session/event')?.({ id: specification.sessionId }, { type: 'turn/end', data: { reason: { kind: 'completed' } } });
        });
      }, whenIdle: async () => work, cancel() {} };
    const context = { provide() {}, plugin: async () => {}, on: (name, handler) => events.set(name, handler),
      systemPrompt: { section() {} }, tools: { register: definition => tools.set(definition.name, {
        execute: data => definition.execute({ data: JSON.stringify(data) }, {
          signal: execution.signal, concludeTurn() { record.concluded++; }
        }) }), guard() {} } };
    await specification.setup(context, agent); sessions.push(record); executions.push(execution);
    return { agent, dispose: async () => { record.disposed = true; } };
  } } };
  return { host, sessions, executions };
}

const options = (extra = {}) => ({ sessionId: 'registered-tool-fixture', purpose: 'game_plan', snapshot,
  input: 'local interface check', toolCatalogue: [{ name: 'game_get_state', description: 'read' }], ...extra });

async function planning(t, { run, ready } = {}) {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close());
  const game = await f.connect(); await game.auto();
  const h = adapter(f.folder, run || (async value => {
    if (value.sessionId.startsWith('mc-plan-')) await value.tools.get('game_start_task').execute({ goal });
  }));
  f.bridge.host = h.host; f.bridge.channel = { snapshot: () => snapshot };
  f.bridge.health = () => ({ persona_injection_ready: true }); f.manager.config.planner.enabled = true;
  const events = []; f.manager.on('planner', value => events.push(value));
  const pending = f.manager.planner.tick();
  // Register a cleanup before asserting, including against the old broken code.
  t.after(async () => { f.manager.planner.cancel(); await pending; });
  const query = await game.next('query');
  const reply = () => game.send('query_result', { ...f.manager.operation(query.payload.operation_id), state: 'succeeded',
    result: { world_session_id: game.observation.world_session_id, kind: 'check_action', allowed: true } });
  await ready?.(h);
  return { f, game, h, pending, query, reply, events };
}

test('registered DSH tool receives SDK cancellation and discards an ignored late result', async t => {
  const f = await gameFixture(); t.after(() => f.close());
  const entered = deferred(), release = deferred(); let received;
  const h = adapter(f.folder, async ({ tools, execution }) => {
    const pending = tools.get('game_get_state').execute({});
    await entered.promise; execution.abort(); release.resolve(); await pending;
  });
  const result = h.host.generate(options({ tools: async (_name, _args, execution) => {
    received = execution?.signal; entered.resolve(); await release.promise; return { late: true };
  } }));
  await assert.rejects(result, error => error.code === 'MODEL_CANCELLED');
  assert.equal(received.aborted, true); assert.equal(h.host.active.size, 0);
  assert.equal(h.sessions[0].disposed, true);
});

test('a tool cancelled by the SDK before entry cannot invoke its registered application callback', async t => {
  const f = await gameFixture(); t.after(() => f.close()); let calls = 0;
  const h = adapter(f.folder, async ({ tools, execution }) => { execution.abort(); await tools.get('game_get_state').execute({}); });
  await assert.rejects(h.host.generate(options({ tools: async () => { calls++; return {}; } })), error => error.code === 'MODEL_CANCELLED');
  assert.equal(calls, 0);
});

test('public speech preemption cannot dispatch a game task from a late positive preflight', async t => {
  const { f, game, h, pending, query, reply } = await planning(t);
  const speech = h.host.generate({ sessionId: 'foreground-response', purpose: 'speech', snapshot, input: '回应弹幕', tools: async () => ({}) });
  reply(); await Promise.all([pending, speech]);
  assert.equal(f.manager.tasks.active(), null);
  assert.equal(game.messages.filter(message => message.type === 'task_start').length, 0);
  assert.equal(f.manager.operation(query.payload.operation_id).error, 'GAME_QUERY_CANCELLED');
  assert.equal(f.manager.pending.has(query.payload.operation_id), false);
  assert.equal(h.host.active.size, 0); assert.equal(h.host.foregroundQueued, 0);
});

test('host shutdown cancels a registered live game preflight and drains before a late allowed result', async t => {
  const { f, game, h, pending, query, reply } = await planning(t);
  await h.host.close(); await pending;
  assert.equal(f.manager.pending.has(query.payload.operation_id), false);
  assert.equal(f.manager.operation(query.payload.operation_id).error, 'GAME_QUERY_CANCELLED');
  assert.equal(h.host.active.size, 0); assert.equal(h.host.modelCalls.size, 0);
  reply(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(game.messages.filter(message => message.type === 'task_start').length, 0);
  assert.equal(f.manager.tasks.active(), null);
});

test('an SDK tool timeout reaches the pending game check before a late allowed reply', async t => {
  const { f, game, h, pending, query, reply } = await planning(t);
  h.executions[0].abort(new DOMException('local tool deadline', 'TimeoutError'));
  reply(); await pending;
  assert.equal(f.manager.tasks.active(), null);
  assert.equal(game.messages.filter(message => message.type === 'task_start').length, 0);
  assert.equal(f.manager.operation(query.payload.operation_id).error, 'GAME_QUERY_CANCELLED');
  assert.equal(f.manager.pending.has(query.payload.operation_id), false);
});

test('a fresh AUTO snapshot with a new control epoch cancels the original planning context', async t => {
  const { f, game, pending, query } = await planning(t);
  const controller = f.manager.planner.running;
  game.snapshot({ seq: game.observation.seq + 1, control_epoch: game.observation.control_epoch + 1 });
  await until(() => f.manager.state.value.control_epoch === game.observation.control_epoch);
  assert.equal(controller.signal.aborted, true);
  await pending;
  assert.equal(f.manager.planner.running, null); assert.equal(f.manager.planner.scope, null);
  assert.equal(f.manager.operation(query.payload.operation_id).error, 'GAME_QUERY_CANCELLED');
  assert.equal(f.manager.tasks.active(), null);
});

test('foreground speech can start without waiting for a cancelled game query to reply', async t => {
  const { f, game, h, pending, query } = await planning(t);
  await Promise.all([pending, h.host.generate({ sessionId: 'foreground-without-query-reply', purpose: 'speech', snapshot,
    input: '先回应观众', tools: async () => ({}) })]);
  assert.equal(f.manager.operation(query.payload.operation_id).error, 'GAME_QUERY_CANCELLED');
  assert.equal(f.manager.pending.size, 0); assert.equal(f.manager.planner.running, null);
  assert.equal(game.messages.filter(message => message.type === 'task_start').length, 0);
  assert.equal(h.sessions.length, 2); assert(h.sessions.every(session => session.disposed));
});

test('an already cancelled speech request cannot interrupt a valid game preflight', async t => {
  const { f, game, h, pending, query, reply } = await planning(t);
  const planningController = h.host.gamePlanAbort, cancelled = new AbortController(); cancelled.abort();
  await assert.rejects(h.host.generate({ sessionId: 'already-cancelled-foreground', purpose: 'speech', snapshot,
    input: '已撤销的回应', signal: cancelled.signal, tools: async () => ({}) }), error => error.code === 'MODEL_CANCELLED');
  assert.equal(planningController.signal.aborted, false);
  assert.equal(f.manager.operation(query.payload.operation_id).state, 'pending');
  assert.equal(h.host.foregroundQueued || 0, 0); assert.equal(h.sessions.length, 1);
  reply(); await pending; await game.next('task_start'); assert.equal(f.manager.tasks.active().state, 'accepted');
});

test('uncancelled planning still dispatches one accepted task without inventing its outcome', async t => {
  const { f, game, h, pending, reply, events } = await planning(t); reply(); await pending;
  const task = f.manager.tasks.active(); assert(task); assert.deepEqual(task.goal, goal);
  assert.equal(task.state, 'accepted'); assert.equal(task.effect_status, 'unknown'); assert.deepEqual(task.evidence, []);
  await game.next('task_start');
  assert.equal(game.messages.filter(message => message.type === 'task_start').length, 1);
  assert.equal(events.at(-1).state, 'idle'); assert.equal(events.at(-1).action_task_id, task.task_id);
  assert.equal(f.manager.pending.size, 0); assert.equal(h.host.active.size, 0);
});

test('speech preemption preserves an already accepted game task for explicit task reconciliation', async t => {
  const accepted = deferred(), release = deferred(); t.after(() => release.resolve());
  const { f, game, h, pending, reply } = await planning(t, { run: async value => {
    if (!value.sessionId.startsWith('mc-plan-')) return;
    await value.tools.get('game_start_task').execute({ goal }); accepted.resolve(); await release.promise;
  } });
  reply(); await accepted.promise; const task = structuredClone(f.manager.tasks.active());
  const speech = h.host.generate({ sessionId: 'foreground-after-task-accepted', purpose: 'speech', snapshot, input: '回应观众', tools: async () => ({}) });
  release.resolve(); await Promise.all([pending, speech]); await game.next('task_start');
  assert.deepEqual(f.manager.tasks.active(), task);
  assert.equal(game.messages.some(message => message.type === 'task_cancel'), false);
  assert.equal(f.manager.planner.running, null); assert.equal(h.host.active.size, 0);
});

test('caller cancellation remains effective when the SDK tool has not been cancelled', async t => {
  const { f, game, h, pending, query } = await planning(t); f.manager.planner.cancel(); await pending;
  assert.equal(h.executions[0].signal.aborted, false);
  assert.equal(f.manager.operation(query.payload.operation_id).error, 'GAME_QUERY_CANCELLED');
  assert.equal(f.manager.tasks.active(), null); assert.equal(f.manager.pending.size, 0);
  assert.equal(game.messages.some(message => message.type === 'task_start'), false);
});

async function interpreting(t) {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close());
  const game = await f.connect();
  f.manager.configure({ expected_revision: 0, patch: { audience_intents: { enabled: true } } });
  const h = adapter(f.folder, async ({ sessionId, tools }) => {
    if (!sessionId.startsWith('mc-intent-')) return;
    await tools.get('game_check_action').execute({ goal });
    await tools.get('stream_audience_intent_result').execute({ kind: 'goal', goal, question: null });
  });
  f.bridge.host = h.host; f.bridge.channel = { snapshot: () => snapshot }; f.bridge.health = () => ({ persona_injection_ready: true });
  f.platformEvent({ text: '再采四个橡木原木吧' }); const intent = f.manager.intents.rows().at(-1);
  const pending = f.manager.intents.tick();
  t.after(async () => { f.manager.intents.running?.controller.abort(); await pending; });
  const query = await game.next('query');
  const reply = () => game.send('query_result', { ...f.manager.operation(query.payload.operation_id), state: 'succeeded',
    result: { world_session_id: game.observation.world_session_id, kind: 'check_action', allowed: true } });
  return { f, game, h, pending, query, reply, intent };
}

for (const cause of ['public speech', 'SDK timeout']) {
  test(cause + (cause === 'public speech' ? ' yields' : ' cancels') + ' an in-flight audience interpretation without creating a proposal', async t => {
    const { f, game, h, pending, query, reply, intent } = await interpreting(t);
    let speech;
    if (cause === 'public speech') speech = h.host.generate({ sessionId: 'foreground-during-intent', purpose: 'speech', snapshot,
      input: '回应观众', tools: async () => ({}) });
    else h.executions[0].abort(new DOMException('local tool deadline', 'TimeoutError'));
    reply(); await Promise.all([pending, speech]);
    const current = f.manager.intents.get(intent.audience_intent_id);
    assert.equal(current.state, cause === 'public speech' ? 'pending' : 'cancelled');
    assert.equal(current.reason, cause === 'public speech' ? 'MODEL_PREEMPTED' : 'GAME_INTENT_CANCELLED');
    assert.equal(current.expires_at, intent.expires_at);
    assert.equal(current.suggestion_id, null); assert.equal(f.manager.suggestions.pending().length, 0);
    assert.equal(f.manager.operation(query.payload.operation_id).error, 'GAME_QUERY_CANCELLED');
    assert.equal(f.manager.pending.size, 0); assert.equal(f.manager.intents.running, null);
    assert.equal(f.manager.tasks.active(), null); assert.equal(f.manager.state.value.mode, 'PAUSED');
    assert.equal(game.messages.some(message => ['task_start', 'control_request'].includes(message.type)), false);
    assert.equal(h.sessions[0].concluded, 0); assert.equal(h.host.active.size, 0);
  });
}

test('an uncancelled audience interpretation remains a reviewed proposal and concludes once', async t => {
  const { f, game, h, pending, reply, intent } = await interpreting(t); reply(); await pending;
  const current = f.manager.intents.get(intent.audience_intent_id), suggestion = f.manager.suggestions.get(current.suggestion_id);
  assert.equal(current.state, 'proposed'); assert.equal(suggestion.state, 'proposed'); assert.deepEqual(suggestion.goal, goal);
  assert.equal(h.sessions[0].concluded, 1); assert.equal(f.manager.tasks.active(), null);
  assert.equal(game.messages.some(message => ['task_start', 'control_request'].includes(message.type)), false);
});

test('an SDK-cancelled structured result cannot conclude a turn after its callback returns late', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const entered = deferred(), release = deferred();
  const h = adapter(f.folder, async ({ tools, execution }) => {
    const pending = tools.get('stream_audience_intent_result').execute({ kind: 'none', goal: null, question: null });
    await entered.promise; execution.abort(); release.resolve(); await pending;
  });
  await assert.rejects(h.host.generate(options({ sessionId: 'mc-intent-11111111-1111-4111-8111-111111111111', purpose: 'audience_intent', tools: async () => {
    entered.resolve(); await release.promise; return { received: true };
  } })), error => error.code === 'MODEL_CANCELLED');
  assert.equal(h.sessions[0].concluded, 0); assert.equal(h.sessions[0].disposed, true);
});

test('SDK cancellation of a narrated game read stops the query, media and answered marker', async t => {
  const f = await narrationFixture(t), h = adapter(f.folder, async ({ tools }) => {
    await tools.get('game_check_action').execute({ goal });
  });
  f.bridge.host = h.host; f.bridge.channel = { snapshot: () => snapshot };
  const { key, item } = await f.comment('能不能再采四个橡木原木？'), pending = f.run();
  const query = await f.game.next('query'); h.executions[0].abort(new DOMException('local tool deadline', 'TimeoutError'));
  f.game.send('query_result', { ...f.manager.operation(query.payload.operation_id), state: 'succeeded',
    result: { world_session_id: f.game.observation.world_session_id, kind: 'check_action', allowed: true } });
  const request = await pending;
  assert.equal(f.manager.operation(query.payload.operation_id).error, 'GAME_QUERY_CANCELLED');
  assert.equal(f.manager.pending.size, 0); assert.equal(f.media.length, 0);
  assert.equal(f.room.store.message(key).answered, false); assert.equal(f.state.request(request.request_id).status, 'CANCELLED');
  assert.equal(f.manager.narration.get(item.narration_id).state, 'failed');
  assert.equal(f.bridge.controllers.size, 0); assert.equal(h.host.active.size, 0);
});
