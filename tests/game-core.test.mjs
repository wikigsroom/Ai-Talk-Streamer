import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { readFileSync } from 'node:fs';
import { validate } from '../backend/game/protocol.mjs';
import { GameStore } from '../backend/game/store.mjs';
import { GameState } from '../backend/game/state.mjs';
import { GameManager } from '../backend/game/manager.mjs';
import { DshHost } from '../backend/dsh-bridge/host.mjs';
import { gameFixture, samples, sourceRoot, until } from './game-fixture.mjs';

const throwsCode = (fn, code) => assert.throws(fn, error => error.code === code);
test('all documented examples validate with the runtime validator and arguments are not coerced', () => {
  for (const sample of Object.values(samples)) validate(sample.definition, sample.value);
  throwsCode(() => validate('Goal', { skill: 'gather', item_id: 'minecraft:oak_log', count: '4' }), 'GAME_REQUEST_INVALID');
  throwsCode(() => validate('Goal', { skill: 'gather', item_id: 'minecraft:oak_log', count: 4, shell: 'x' }), 'GAME_REQUEST_INVALID');
});

test('disabled mode exposes configuration only and cross-field changes are atomic', async t => {
  const f = await gameFixture({ enabled: false }); t.after(() => f.close());
  assert.equal((await f.api('/state')).value.error, 'GAME_DISABLED');
  const initial = (await f.api('/config')).value;
  const invalid = await f.api('/config', { expected_revision: initial.revision, patch: { control: { lease_ttl_ms: 2000 } } });
  assert.equal(invalid.status, 400); assert.equal(f.manager.configRevision, initial.revision);
  const good = await f.api('/config', { expected_revision: initial.revision, patch: { enabled: true } });
  assert.equal(good.status, 200); assert.equal((await f.api('/state')).value.freshness, 'unavailable');
  assert.equal((await f.api('/config', { expected_revision: initial.revision, patch: { enabled: false } })).status, 409);
});

test('hello and snapshot bind the same player and missing information stays unknown', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect();
  const state = (await f.api('/state')).value; validate('GameState', state);
  assert.equal(state.game_instance_id, game.identity.game_instance_id); assert.equal(state.mode, 'PAUSED');
  assert.equal(state.automation_ready, false); assert.ok(state.unknown_fields.includes('unopened_container_contents'));
  assert.equal((await f.api('/capabilities')).value.skills.length, 6);
});

test('duplicate observations and heartbeats cannot refresh old state; delta gaps require a full snapshot', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); const game = await f.connect();
  f.advance(2100); game.snapshot(); game.heartbeat(1); await new Promise(r => setTimeout(r, 20));
  assert.equal(f.manager.state.view().freshness, 'stale');
  game.send('delta', { world_session_id: game.observation.world_session_id, base_seq: 77, seq: 78,
    observed_at: game.observation.observed_at, changes: { inventory: [] } });
  await game.next('snapshot_request'); assert.equal(f.manager.state.view().freshness, 'stale');
  game.snapshot({ seq: 80 }); await until(() => f.manager.state.value.seq === 80);
  assert.equal(f.manager.state.view().freshness, 'fresh');
});

test('AUTO requires an explicit fenced request and two confirmations before a task can execute', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect();
  assert.equal((await f.api('/tasks', game.request())).value.error, 'GAME_MODE_BLOCKED');
  assert.equal((await f.api('/control', { request_id: 'bad-auto', target_mode: 'AUTO', reason: 'test' })).status, 400);
  const result = await game.auto();
  assert.equal(result.grant.payload.based_on_heartbeat_seq, 1);
  assert.equal(result.grant.payload.lease_id, result.result.lease_id);
  assert.equal(f.manager.state.view().automation_ready, true); validate('GameState', f.manager.state.view());
  assert.equal((await f.api('/config', { expected_revision: 0, patch: { control: { enabled_skills: [] } } })).value.error, 'GAME_CONTROL_CONFLICT');
});

test('task acceptance, evidence, terminal state and idempotency remain distinct', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect(); await game.auto();
  const request = game.request(), first = await f.api('/tasks', request);
  assert.equal(first.status, 202); assert.equal(first.value.state, 'accepted');
  const start = await game.next('task_start'); assert.equal(start.payload.task_id, first.value.task_id);
  const duplicate = await f.api('/tasks', request); assert.equal(duplicate.status, 200); assert.equal(duplicate.value.task_id, first.value.task_id);
  const conflicting = await f.api('/tasks', { ...request, goal: { ...request.goal, count: 5 } });
  assert.equal(conflicting.value.error, 'GAME_IDEMPOTENCY_CONFLICT');
  assert.equal(game.messages.filter(m => m.type === 'task_start').length, 1);
  const running = { ...first.value, version: 2, state: 'running' };
  game.send('task_update', { delivery_seq: 1, transition_seq: 2, task: running }); await game.next('ack', m => m.payload.through_seq === 1);
  const complete = { ...running, version: 3, state: 'succeeded', effect_status: 'verified', evidence: [{
    world_session_id: running.world_session_id, seq: 3, kind: 'inventory', summary: 'Protocol fixture only: verified inventory delta' }] };
  game.send('task_update', { delivery_seq: 2, transition_seq: 3, task: complete }); await until(() => f.manager.tasks.get(first.value.task_id).state === 'succeeded');
  assert.equal((await f.api('/tasks/' + first.value.task_id)).value.effect_status, 'verified');
  assert.equal((await f.api('/tasks', request)).value.state, 'succeeded');
});

test('cancellation waits for the local task transition and records partial effects', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect(); await game.auto();
  const task = (await f.api('/tasks', game.request())).value;
  const operation = (await f.api('/tasks/' + task.task_id + '/cancel', { request_id: 'cancel-test', reason: 'operator' })).value;
  assert.equal(operation.state, 'pending'); assert.equal(f.manager.tasks.get(task.task_id).state, 'accepted');
  await game.next('task_cancel');
  game.send('task_update', { delivery_seq: 1, transition_seq: 2, task: { ...task, state: 'cancelled', version: 2,
    effect_status: 'partial', reason: 'operator_cancelled' } });
  await until(() => f.manager.operation(operation.operation_id).state === 'succeeded');
  assert.equal(f.manager.operation(operation.operation_id).result.effect_status, 'partial');
});

test('local takeover revokes the lease and old snapshots cannot restore an earlier epoch', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect(); await game.auto();
  const old = game.request();
  game.send('control_result', { operation_id: 'local-takeover', request_id: 'local-key', world_session_id: game.observation.world_session_id,
    mode: 'MANUAL_COMMENTARY', control_epoch: 99, inputs_released: true, automation_ready: false, lease_id: null, heartbeat_seq: null, error: null });
  await until(() => f.manager.state.value.control_epoch === 99);
  assert.equal(f.manager.lease, null); assert.equal((await f.api('/tasks', old)).value.error, 'GAME_MODE_BLOCKED');
  game.snapshot({ seq: 4 }); await until(() => !f.manager.state.connected);
  assert.equal(f.manager.state.value.control_epoch, 99);
});

test('a late AUTO result after PAUSED is superseded cannot obtain a renewed lease', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect();
  const auto = (await f.api('/control', { request_id: 'auto-pending', target_mode: 'AUTO', reason: 'test',
    bridge_boot_id: game.identity.bridge_boot_id, world_session_id: game.observation.world_session_id, expected_control_epoch: 7 })).value;
  await f.api('/control', { request_id: 'stop-wins', target_mode: 'PAUSED', reason: 'operator' });
  assert.equal(f.manager.operation(auto.operation_id).error, 'SUPERSEDED_CONTROL');
  game.send('control_result', { operation_id: auto.operation_id, request_id: auto.request_id, world_session_id: game.observation.world_session_id,
    mode: 'AUTO', control_epoch: 8, inputs_released: true, automation_ready: false, lease_id: 'late-lease', heartbeat_seq: 1, error: null });
  await until(() => !f.manager.state.connected); assert.equal(f.manager.lease, null);
});

test('a different instance cannot replace the active player and reconnects do not replay task inputs', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect(); await game.auto();
  await f.api('/tasks', game.request()); await game.next('task_start');
  const other = await f.connect({ instance: 'another-player', helloOnly: true }); await until(() => other.socket.readyState >= 2);
  assert.equal(f.manager.state.value.game_instance_id, game.identity.game_instance_id);
  game.socket.close(); await until(() => !f.manager.state.connected);
  const next = await f.connect({ generation: 2 });
  assert.equal(f.manager.state.value.mode, 'PAUSED'); assert.equal(next.messages.filter(m => m.type === 'task_start').length, 0);
});

test('reliable event retransmission is deduplicated and acknowledged after storage', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect();
  const event = { event_id: 'event-once', delivery_seq: 1, world_session_id: game.observation.world_session_id, seq: 1,
    occurred_at: game.observation.observed_at, kind: 'inventory_changed', severity: 'important', task_id: null, data: { delta: 4 } };
  game.send('game_event', event); await game.next('ack'); game.send('game_event', event);
  await until(() => game.messages.filter(m => m.type === 'ack').length === 2);
  assert.equal(f.manager.store.get('SELECT COUNT(*) n FROM game_events').n, 1);
});

test('votes use stable identities, one vote per viewer, fixed options and explicit tie decisions', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect();
  const request = { ...samples['vote-create'].value, world_session_id: game.observation.world_session_id };
  const created = await f.api('/votes', request); assert.equal(created.status, 201); const vote = created.value;
  const event = { platform: 'bilibili', type: 'comment', room_id: '100', user_key: 'user-one', event_key: 'event-one', text: '#logs',
    occurred_at: f.manager.wall(), received_at: f.manager.wall() };
  assert.equal(f.manager.votes.cast(event), true); assert.equal(f.manager.votes.cast({ ...event, event_key: 'event-two' }), false);
  assert.equal(f.manager.votes.cast({ ...event, event_key: 'event-no-id', user_key: null }), false);
  assert.equal(f.manager.votes.cast({ ...event, event_key: 'event-hidden', user_key: 'other', hidden: true }), false);
  assert.equal(f.manager.votes.cast({ ...event, event_key: 'event-test', user_key: 'other', test: true }), false);
  assert.equal(f.manager.votes.cast({ ...event, event_key: 'event-tie', user_key: 'user-two', text: '#planks' }), true);
  const closed = (await f.api('/votes/' + vote.vote_id + '/close', { request_id: 'close-vote', expected_revision: 1, action: 'close', reason: 'operator' })).value;
  assert.equal(closed.tied, true); assert.equal(closed.winning_option_id, null);
  const chosen = await f.api('/votes/' + vote.vote_id + '/close', { request_id: 'choose-vote', expected_revision: closed.revision,
    action: 'close', reason: 'operator_tie_decision', selected_option_id: 'logs' });
  assert.equal(chosen.value.winning_option_id, 'logs'); assert.equal(chosen.value.task_id, null);
  assert.equal(f.manager.tasks.active(), null); assert.equal(f.manager.votes.cast({ ...event, event_key: 'late', user_key: 'late' }), false);
});

test('expired votes freeze counts and duplicate option identifiers are rejected', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); const game = await f.connect();
  const request = samples['vote-create'].value;
  assert.equal((await f.api('/votes', { ...request, options: [request.options[0], request.options[0]] })).value.error, 'GAME_VOTE_OPTIONS_NOT_UNIQUE');
  const vote = (await f.api('/votes', request)).value;
  f.advance(61000); f.manager.votes.tick(); assert.equal(f.manager.votes.get(vote.vote_id).state, 'closed');
  assert.equal(f.manager.votes.get(vote.vote_id).tied, true);
});

test('suggestion acceptance is a candidate, not execution; CAS and expiration are enforced', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); await f.connect();
  const suggestion = f.manager.suggestions.create({ skill: 'gather', item_id: 'minecraft:oak_log', count: 4 }, ['platform-source']);
  const decision = { request_id: 'accept-suggestion', expected_revision: 1, action: 'accept', reason: 'operator_accept' };
  assert.equal((await f.api('/suggestions/' + suggestion.suggestion_id + '/decision', decision)).value.state, 'accepted');
  assert.equal(f.manager.tasks.active(), null);
  assert.equal((await f.api('/suggestions/' + suggestion.suggestion_id + '/decision', { ...decision, request_id: 'other' })).value.error, 'GAME_SUGGESTION_CONFLICT');
  f.advance(121000); f.manager.suggestions.expire(); assert.equal(f.manager.suggestions.get(suggestion.suggestion_id).state, 'expired');
});

test('game tools reject forged arguments and public speech cannot execute a game task', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect();
  await assert.rejects(f.manager.tools.invoke('game_start_task', { goal: game.request().goal }, { purpose: 'speech' }), e => e.code === 'GAME_TOOL_PERMISSION');
  await assert.rejects(f.manager.tools.invoke('game_get_state', { expected_control_epoch: 8 }), e => e.code === 'GAME_UNKNOWN_FIELD');
  await assert.rejects(f.manager.tools.invoke('game_query_inventory', { item_ids: ['arbitrary shell'] }), e => e.code === 'GAME_REQUEST_INVALID');
  assert.ok(!f.manager.tools.catalogue('speech').some(t => t.name === 'game_start_task'));
  assert.equal((await f.manager.tools.invoke('game_query_inventory', {})).inventory[0].count, 3);
});

test('game start tool checks the current world and protocol bridge preflight before dispatch', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect(); await game.auto();
  const state = f.manager.state.view(), context = { purpose: 'game_plan', worldSessionId: state.world_session_id, controlEpoch: state.control_epoch };
  const call = f.manager.tools.invoke('game_start_task', { goal: game.request().goal }, context);
  const query = await game.next('query'); assert.equal(query.payload.request.kind, 'check_action');
  const operation = f.manager.operation(query.payload.operation_id);
  game.send('query_result', { ...operation, state: 'succeeded', result: { world_session_id: state.world_session_id, kind: 'check_action', allowed: true } });
  const task = await call; assert.equal(task.state, 'accepted'); await game.next('task_start');
});

test('autonomous navigation already inside the arrival radius creates no query or task', async t => {
  const f=await gameFixture();t.after(()=>f.close());const game=await f.connect();await game.auto();
  const state=f.manager.state.view(),position=state.player.position;
  const context={purpose:'game_plan',worldSessionId:state.world_session_id,controlEpoch:state.control_epoch};
  for(const [dx,radius] of [[0,0],[1,1],[2,8]]) {
    const before=game.messages.length;
    await assert.rejects(f.manager.tools.invoke('game_start_task',{goal:{skill:'navigate',target:{...position,x:position.x+dx},radius}},context),
      {code:'GAME_NAVIGATION_ALREADY_AT_DESTINATION'});
    assert.equal(game.messages.slice(before).some(row=>['query','task_start'].includes(row.type)),false);
    assert.equal(f.manager.tasks.active(),null);
  }
});

test('navigation arrival during a preflight query cannot create a redundant autonomous task', async t => {
  const f=await gameFixture();t.after(()=>f.close());const game=await f.connect();await game.auto();
  const state=f.manager.state.view(),target={...state.player.position,x:state.player.position.x+4};
  const context={purpose:'game_plan',worldSessionId:state.world_session_id,controlEpoch:state.control_epoch};
  const call=f.manager.tools.invoke('game_start_task',{goal:{skill:'navigate',target,radius:1}},context);
  const rejected=assert.rejects(call,{code:'GAME_NAVIGATION_ALREADY_AT_DESTINATION'});
  const query=await game.next('query');
  game.snapshot({seq:game.observation.seq+1,player:{...game.observation.player,position:target}});
  await until(()=>f.manager.state.value.player.position.x===target.x);
  const operation=f.manager.operation(query.payload.operation_id);
  game.send('query_result',{...operation,state:'succeeded',result:{world_session_id:state.world_session_id,kind:'check_action',allowed:true}});
  await rejected;assert.equal(game.messages.some(row=>row.type==='task_start'),false);assert.equal(f.manager.tasks.active(),null);
});

test('one database owner is enforced and host restart records uncertainty without replay', async () => {
  const f = await gameFixture();
  try {
    const game = await f.connect(); await game.auto();
    const task = (await f.api('/tasks', game.request())).value;
    assert.throws(() => new GameStore(join(f.folder, 'state/testing/game/game.sqlite3')), /GAME_STORE_OWNER_ACTIVE/);
    await f.manager.close(); const next = new GameManager(f.folder, f.bridge);
    try {
      const restored = next.tasks.get(task.task_id); assert.equal(restored.state, 'accepted'); assert.equal(restored.version, 1);
      assert.equal(restored.recovery.status, 'required'); assert.equal(restored.recovery.reason, 'INTERRUPTED_HOST_RESTART');
      assert.equal(restored.effect_status, 'unknown');
      assert.equal(next.state.value.mode, null); assert.equal(next.lease, undefined);
    } finally { await next.close(); }
  } finally { await f.close(); }
});

test('panic reports room success and disconnected game separately', async t => {
  const f = await gameFixture(); t.after(() => f.close());
  const result = (await f.api('/panic', { request_id: 'panic-disconnected', reason: 'operator' })).value;
  assert.equal(result.state, 'failed'); assert.equal(result.result.game.error, 'GAME_DISCONNECTED');
  assert.equal(result.result.room.audio.muted, true);
});

test('lost database ownership stops issuing leases and refuses task dispatch', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect(); await game.auto();
  f.manager.store.db.prepare("UPDATE game_owner SET owner_id='another-owner' WHERE singleton=1").run();
  const response = await f.api('/tasks', game.request());
  assert.equal(response.value.error, 'GAME_STORE_OWNER_LOST');
  assert.equal(f.manager.lease, null); assert.equal(f.manager.faulted, true);
  assert.equal(game.messages.filter(m => m.type === 'task_start').length, 0);
});

test('SSE reconnect starts with current data rather than replaying gifts or actions', async t => {
  const f = await gameFixture(); t.after(() => f.close()); await f.connect();
  const controller = new AbortController(); const response = await fetch(f.base + '/api/dsh/game/events', { signal: controller.signal });
  const reader = response.body.getReader(), first = await reader.read();
  const data = new TextDecoder().decode(first.value); assert.match(data, /event: snapshot/); assert.match(data, /"votes"/);
  await reader.cancel(); controller.abort();
});

test('the shared model queue serializes callers and public speech cancels game planning', async () => {
  let concurrent = 0, maximum = 0; const started = [];
  const host = { async generateInternal(options) {
    concurrent++; maximum = Math.max(maximum, concurrent); started.push(options.purpose);
    try { await new Promise((resolve, reject) => {
      const timer = setTimeout(resolve, options.purpose === 'game_plan' ? 500 : 15);
      options.signal.addEventListener('abort', () => { clearTimeout(timer); reject(new Error('aborted')); }, { once: true });
    }); return { text: 'fixture' }; } finally { concurrent--; }
  } };
  const planning = DshHost.prototype.generate.call(host, { purpose: 'game_plan' }).catch(e => e.message);
  await until(() => started.length === 1);
  const speech = DshHost.prototype.generate.call(host, { purpose: 'speech' });
  assert.equal(await planning, 'aborted'); await speech; assert.equal(maximum, 1);
  assert.deepEqual(started, ['game_plan', 'speech']);
});
