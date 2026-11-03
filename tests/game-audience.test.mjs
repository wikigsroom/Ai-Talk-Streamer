import test from 'node:test';
import assert from 'node:assert/strict';
import { gameFixture, samples, until } from './game-fixture.mjs';
import { validate } from '../backend/game/protocol.mjs';
import { RoomManager } from '../backend/room/manager.mjs';
import { normalizeEvent } from '../backend/platforms/events.mjs';
import { EventEmitter } from 'node:events';

const goal = { skill: 'gather', item_id: 'minecraft:oak_log', count: 4 };
const command = '建议 采集 minecraft:oak_log 4';
const accepted = (f, suggestion) => f.manager.suggestions.decision(suggestion.suggestion_id, {
  request_id: 'approve-' + suggestion.suggestion_id, expected_revision: suggestion.revision, action: 'accept', reason: 'fixture_operator_review' });
const proposal = f => { const event = f.platformEvent({ text: command });
  return f.manager.suggestions.page().items.find(value => value.source_event_ids.includes(event.event_key)); };
const dispatchRequest = (f, value, id = 'dispatch-fixture') => ({ request_id: id, bridge_boot_id: f.manager.state.value.bridge_boot_id,
  world_session_id: f.manager.state.value.world_session_id, expected_control_epoch: f.manager.state.value.control_epoch, expected_revision: value.revision });
async function replyCheck(f, game, allowed = true) {
  const frame = await game.next('query', frame => frame.payload.request.kind === 'check_action' && f.manager.pending.has(frame.payload.operation_id));
  const operation = f.manager.operation(frame.payload.operation_id);
  game.send('query_result', { ...operation, state: 'succeeded', result: { kind: 'check_action', world_session_id: game.observation.world_session_id, allowed } });
  return frame;
}

test('only fresh filtered Bilibili commands produce bounded deduplicated proposals in the configured platform room', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); await f.connect();
  assert.notEqual(f.manager.roomId(), f.bridge.state.characterRoom[1]);
  for (const patch of [{ hidden: true }, { test: true }, { room_id: 'other' }, { platform: 'douyin' },
    { occurred_at: f.manager.wall() - 30001 }, { occurred_at: f.manager.wall() + 2001 }, { received_at: f.manager.wall() - 30001 },
    { text: command + '; shell' }, { text: '<script>建议 采集 minecraft:oak_log 4</script>' }, { text: '建议 采集 minecraft:oak_log 0' },
    { text: '建议 采集 minecraft:oak_log 4097' }, { text: '建议 回基地' }]) f.platformEvent({ text: command, ...patch });
  assert.equal(f.manager.suggestions.page().items.length, 0); assert.equal(f.manager.faulted, undefined);
  const first = f.platformEvent({ event_key: 'same-event', text: command }), value = f.manager.suggestions.page().items[0];
  f.manager.acceptPlatformEvent(first); f.platformEvent({ text: command });
  let merged = f.manager.suggestions.get(value.suggestion_id); assert.equal(merged.support_count, 2); assert.equal(merged.revision, 2);
  for (let i = 0; i < 35; i++) f.platformEvent({ event_key: 'merge-' + i, text: command });
  merged = f.manager.suggestions.get(value.suggestion_id); assert.equal(merged.source_event_ids.length, 32); assert.equal(merged.support_count, 37);
  assert.equal(merged.expires_at, value.expires_at); assert.equal(f.manager.tasks.active(), null);
  const current = accepted(f, merged); f.platformEvent({ text: command });
  assert.equal(f.manager.suggestions.get(current.suggestion_id).revision, current.revision, 'approved source/goal is frozen');
  assert.equal(f.manager.suggestions.page().items.length, 2); validate('AudienceSummary', f.manager.suggestions.summary());
  const persisted = f.manager.store.all("SELECT value FROM objects WHERE kind IN ('suggestion','audience_receipt')").map(row => row.value).join('');
  assert(!persisted.includes('fixture-viewer')); assert(!persisted.includes(command), 'no raw chat copied into the game database');
});

test('candidate pressure stays at 64 pending goals and duplicate topic merge remains possible at capacity', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); await f.connect();
  for (let i = 1; i <= 65; i++) f.platformEvent({ text: `建议 采集 minecraft:oak_log ${i}` });
  assert.equal(f.manager.suggestions.page({ limit: 100 }).items.length, 64);
  f.platformEvent({ text: '建议 采集 minecraft:oak_log 1' });
  assert.equal(f.manager.suggestions.page({ limit: 100 }).items.find(value => value.goal.count === 1).support_count, 2);
  f.advance(121000); f.manager.suggestions.expire(); assert(f.manager.suggestions.page({ limit: 100 }).items.every(value => value.state === 'expired'));
});

test('review cannot execute in PAUSED; dispatch preflights and persists the suggestion-task link before sending, with idempotent operation retries', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); const game = await f.connect(); const value = accepted(f, proposal(f));
  assert.equal((await f.api('/suggestions/' + value.suggestion_id + '/dispatch', dispatchRequest(f, value))).value.error, 'GAME_MODE_BLOCKED');
  await game.auto(); const request = dispatchRequest(f, value);
  const operation = (await f.api('/suggestions/' + value.suggestion_id + '/dispatch', request)).value;
  assert.equal(operation.kind, 'audience'); assert.equal(f.manager.tasks.active(), null);
  assert.equal((await f.api('/suggestions/' + value.suggestion_id + '/dispatch', request)).value.operation_id, operation.operation_id);
  assert.equal((await f.api('/suggestions/' + value.suggestion_id + '/dispatch', { ...request, expected_revision: request.expected_revision + 1 })).value.error, 'GAME_IDEMPOTENCY_CONFLICT');
  const send = f.manager.send.bind(f.manager); let observedDurableLink = false;
  f.manager.send = (type, payload) => { if (type === 'task_start') observedDurableLink = f.manager.suggestions.get(value.suggestion_id).task_id === payload.task_id && !!f.manager.tasks.raw(payload.task_id); return send(type, payload); };
  await replyCheck(f, game); await until(() => f.manager.operation(operation.operation_id).state === 'succeeded');
  const taskId = f.manager.operation(operation.operation_id).result.task_id, task = f.manager.tasks.raw(taskId);
  assert(observedDurableLink); assert.equal(task.state, 'accepted'); assert.equal(task.effect_status, 'unknown');
  const frame = await game.next('task_start'); assert.equal(frame.payload.request.suggestion_ref.suggestion_id, value.suggestion_id);
  assert.equal(f.manager.suggestions.get(value.suggestion_id).state, 'converted');
  const duplicate = await f.api('/suggestions/' + value.suggestion_id + '/dispatch', request); assert.equal(duplicate.value.result.task_id, taskId);
  assert.equal(game.messages.filter(frame => frame.type === 'task_start').length, 1);
  const feedback = (await f.api('/audience')).value.feedback[0]; assert.equal(feedback.state, 'accepted'); assert.equal(feedback.speech_status, 'not_scheduled');
});

test('preflight denial, source hiding and an operator rejection during the check cannot dispatch', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); const game = await f.connect(); await game.auto();
  for (const kind of ['denied', 'hidden', 'rejected']) {
    const value = accepted(f, proposal(f)), operation = f.manager.suggestions.dispatch(value.suggestion_id, dispatchRequest(f, value, 'dispatch-' + kind));
    const query = await game.next('query', frame => f.manager.pending.has(frame.payload.operation_id));
    if (kind === 'hidden') f.bridge.room.store.message(value.source_event_ids[0]).hidden = true;
    if (kind === 'rejected') f.manager.suggestions.decision(value.suggestion_id, { request_id: 'cancel-reviewed', expected_revision: value.revision, action: 'cancel', reason: 'operator_changed_mind' });
    const check = f.manager.operation(query.payload.operation_id);
    game.send('query_result', { ...check, state: 'succeeded', result: { kind: 'check_action', world_session_id: game.observation.world_session_id, allowed: kind !== 'denied' } });
    await until(() => f.manager.operation(operation.operation_id).state === 'failed'); await until(() => f.manager.suggestions.dispatching.size === 0);
  }
  assert.equal(f.manager.tasks.active(), null); assert.equal(game.messages.filter(frame => frame.type === 'task_start').length, 0);
});

test('takeover during preflight cancels only the read query and discards a late allowed result', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); const game = await f.connect(); await game.auto();
  const value = accepted(f, proposal(f)), operation = f.manager.suggestions.dispatch(value.suggestion_id, dispatchRequest(f, value));
  const query = await game.next('query'), old = f.manager.operation(query.payload.operation_id);
  game.send('control_result', { operation_id: 'takeover', request_id: 'takeover', world_session_id: game.observation.world_session_id,
    mode: 'MANUAL_COMMENTARY', control_epoch: 9, inputs_released: true, automation_ready: false, lease_id: null, heartbeat_seq: null, error: null });
  await until(() => f.manager.operation(operation.operation_id).state === 'failed');
  game.send('query_result', { ...old, state: 'succeeded', result: { kind: 'check_action', world_session_id: game.observation.world_session_id, allowed: true } });
  await until(() => f.manager.suggestions.dispatching.size === 0); assert.equal(f.manager.tasks.active(), null);
  assert.equal(f.manager.operation(old.operation_id).error, 'GAME_QUERY_CANCELLED');
  assert.equal(game.messages.filter(frame => ['task_start', 'task_cancel'].includes(frame.type)).length, 0);
});

test('vote ballots require stable identities, current event age, platform and room; a tied vote needs explicit selection before creating a review candidate', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); await f.connect();
  const vote = f.manager.votes.create(samples['vote-create'].value).value;
  for (const patch of [{ platform: 'douyin' }, { user_key: null }, { occurred_at: f.manager.wall() - 1 }, { occurred_at: f.manager.wall() + 2001 }, { hidden: true }, { test: true }]) f.platformEvent({ text: '#logs', ...patch });
  assert.equal(f.manager.votes.get(vote.vote_id).tally_version, 0);
  f.platformEvent({ text: '#logs', user_key: 'one' }); f.platformEvent({ text: '#planks', user_key: 'one' }); f.platformEvent({ text: '#planks', user_key: 'two' });
  let closed = f.manager.votes.close(vote.vote_id, { request_id: 'close-tie', expected_revision: 1, action: 'close', reason: 'fixture_close' });
  const request = { request_id: 'promote', bridge_boot_id: f.manager.state.value.bridge_boot_id, world_session_id: vote.world_session_id, expected_revision: closed.revision };
  assert.equal((await f.api('/votes/' + vote.vote_id + '/suggestion', request)).value.error, 'GAME_VOTE_WINNER_REQUIRED');
  closed = f.manager.votes.close(vote.vote_id, { request_id: 'resolve-tie', expected_revision: closed.revision, action: 'close', selected_option_id: 'logs', reason: 'operator_explicit_tie_choice' });
  const promoted = await f.api('/votes/' + vote.vote_id + '/suggestion', { ...request, expected_revision: closed.revision });
  assert.equal(promoted.status, 201); assert.equal(promoted.value.state, 'proposed'); assert.equal(promoted.value.origin.kind, 'vote');
  assert.equal((await f.api('/votes/' + vote.vote_id + '/suggestion', { ...request, expected_revision: closed.revision })).value.suggestion_id, promoted.value.suggestion_id);
  assert.equal(f.manager.tasks.active(), null); validate('Suggestion', promoted.value); validate('Vote', f.manager.votes.get(vote.vote_id));
});

test('winning vote, reviewed suggestion and task are durably linked and result feedback keeps partial effects and playback separate', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); const game = await f.connect();
  const vote = f.manager.votes.create(samples['vote-create'].value).value; f.platformEvent({ text: '#logs' });
  const closed = f.manager.votes.close(vote.vote_id, { request_id: 'close-winner', expected_revision: 1, action: 'close', reason: 'operator_close' });
  const value = accepted(f, f.manager.votes.promote(vote.vote_id, { request_id: 'promote-winner', bridge_boot_id: game.identity.bridge_boot_id,
    world_session_id: vote.world_session_id, expected_revision: closed.revision }).value);
  await game.auto(); const operation = f.manager.suggestions.dispatch(value.suggestion_id, dispatchRequest(f, value)); await replyCheck(f, game);
  await until(() => f.manager.operation(operation.operation_id).state === 'succeeded'); const task = f.manager.tasks.active();
  assert.equal(f.manager.votes.get(vote.vote_id).task_id, task.task_id);
  game.send('task_update', { delivery_seq: 1, transition_seq: 2, task: { ...task, version: 2, state: 'failed', effect_status: 'partial', reason: 'FIXTURE_PARTIAL',
    evidence: [{ world_session_id: task.world_session_id, seq: f.manager.state.value.seq, kind: 'inventory', summary: 'TEST_FIXTURE_ONLY partial items' }] } });
  await until(() => f.manager.tasks.raw(task.task_id).version === 2);
  const summary = (await f.api('/audience')).value; validate('AudienceSummary', summary);
  assert.equal(summary.feedback[0].vote_id, vote.vote_id); assert.equal(summary.feedback[0].effect_status, 'partial');
  assert.equal(summary.feedback[0].state, 'failed'); assert.equal(summary.feedback[0].speech_status, 'not_scheduled'); assert.equal(summary.feedback[0].evidence.length, 1);
});

test('a dispatch send failure preserves links, one accepted task and unknown recovery across host restart without replay', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); const game = await f.connect(); await game.auto();
  const value = accepted(f, proposal(f)), request = dispatchRequest(f, value), operation = f.manager.suggestions.dispatch(value.suggestion_id, request);
  const send = f.manager.send.bind(f.manager); let attempts = 0;
  f.manager.send = (type, payload) => { if (type === 'task_start') { attempts++; throw new Error('fixture_send_failed_after_commit'); } return send(type, payload); };
  await replyCheck(f, game); await until(() => f.manager.operation(operation.operation_id).state === 'failed');
  const linked = f.manager.suggestions.get(value.suggestion_id); assert.equal(linked.state, 'converted'); assert(linked.task_id); assert.equal(attempts, 1);
  await f.restartHost(); assert.equal(f.manager.tasks.get(linked.task_id).state, 'accepted'); assert.equal(f.manager.tasks.get(linked.task_id).effect_status, 'unknown');
  assert.equal(f.manager.tasks.get(linked.task_id).recovery.status, 'required');
  const replay = f.manager.suggestions.dispatch(value.suggestion_id, request); assert.equal(replay.operation_id, operation.operation_id);
  assert.equal(replay.result.task_id, linked.task_id); assert.equal(f.manager.store.list('task').items.length, 1);
});

test('changing the selected Bilibili room expires suggestions, cancels the active vote and hides the old-room summaries', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); await f.connect(); const value = proposal(f);
  const vote = f.manager.votes.create(samples['vote-create'].value).value;
  f.bridge.platforms.config.value.platforms.bilibili.room_id = 'other'; f.manager.suggestions.expire(); f.manager.votes.tick();
  assert.equal(f.manager.suggestions.get(value.suggestion_id).reason, 'ROOM_CHANGED'); assert.equal(f.manager.votes.get(vote.vote_id).state, 'cancelled');
  assert.equal((await f.api('/audience')).value.suggestions.length, 0); assert.equal((await f.api('/votes')).value.items.length, 0);
});

test('DSH speech tools can read audience facts but only a fenced planning call can execute the exact accepted suggestion', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); const game = await f.connect(); const value = accepted(f, proposal(f)); await game.auto();
  assert(f.manager.tools.catalogue('speech').some(tool => tool.name === 'game_get_audience'));
  const summary = await f.manager.tools.invoke('game_get_audience', {}, { purpose: 'speech' }); assert.equal(summary.suggestions[0].suggestion_id, value.suggestion_id);
  await assert.rejects(f.manager.tools.invoke('game_start_task', { goal, suggestion_id: value.suggestion_id }, { purpose: 'speech' }), error => error.code === 'GAME_TOOL_PERMISSION');
  const context = { purpose: 'game_plan', worldSessionId: f.manager.state.value.world_session_id, controlEpoch: f.manager.state.value.control_epoch };
  await assert.rejects(f.manager.tools.invoke('game_start_task', { goal: { ...goal, count: 5 }, suggestion_id: value.suggestion_id }, context), error => error.code === 'GAME_SUGGESTION_GOAL_CHANGED');
  const pending = f.manager.tools.invoke('game_start_task', { goal, suggestion_id: value.suggestion_id }, context); await replyCheck(f, game);
  const task = await pending; assert.equal(f.manager.suggestions.get(value.suggestion_id).task_id, task.task_id);
  assert.equal(task.state, 'accepted'); assert.equal(f.manager.tools.catalogue('operator_private').some(tool => tool.name === 'game_start_task'), false);
});

test('actual normalizer and Room persistence filter and deduplicate before forwarding; source hiding invalidates an approved suggestion', async t => {
  const f = await gameFixture({ fakeClock: true }); let room;
  t.after(async () => { if (room) await room.close(); await f.close(); });
  await f.connect(); f.bridge.db = new EventEmitter(); f.bridge.state.current = () => null;
  room = new RoomManager(f.folder, f.bridge, { now: () => f.manager.wall() }); f.bridge.room = room;
  room.store.settings.moderation.blocked_words = ['forbidden'];
  const event = (id, text = command, uid = 'stable-platform-user') => normalizeEvent('bilibili', {
    type: 'comment', event_id: id, room_id: '100', user_id: uid, nickname: '同名观众', text, timestamp: f.manager.wall()
  }, { now: f.manager.wall(), source: 'blivedm' });
  room.acceptPlatformEvent(event('blocked', command + ' forbidden'));
  room.acceptPlatformEvent(event('good')); room.acceptPlatformEvent(event('good'));
  const value = f.manager.suggestions.page().items[0]; assert.equal(value.support_count, 1); assert.equal(f.manager.suggestions.page().items.length, 1);
  const message = room.store.message(value.source_event_ids[0]); assert.equal(message.user_key.length, 64); assert.equal(message.platform, 'bilibili');
  const reviewed = accepted(f, value); room.store.run('UPDATE messages SET hidden=1 WHERE id=?', message.id);
  assert.throws(() => f.manager.suggestions.reference(reviewed.suggestion_id, reviewed.revision, goal), error => error.code === 'GAME_SUGGESTION_CONFLICT');
  const current = f.manager.suggestions.get(reviewed.suggestion_id);
  assert.throws(() => f.manager.suggestions.reference(current.suggestion_id, current.revision, goal), error => error.code === 'GAME_SUGGESTION_SOURCE_UNAVAILABLE');
  const vote = f.manager.votes.create(samples['vote-create'].value).value;
  room.acceptPlatformEvent(event('ballot-one', '#logs', 'uid1')); room.acceptPlatformEvent(event('ballot-one-again', '#planks', 'uid1'));
  room.acceptPlatformEvent(event('ballot-two', '#planks', 'uid2')); room.acceptPlatformEvent(event('anonymous', '#logs', ''));
  assert.deepEqual(f.manager.votes.get(vote.vote_id).options.map(option => option.votes), [1, 1]);
  assert.equal(f.manager.faulted, undefined); assert.equal(f.manager.tasks.active(), null);
});

test('invalid suggestion association rolls back task and idempotency atomically, and a new request cannot convert an already linked suggestion', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); const game = await f.connect(); const value = accepted(f, proposal(f)); await game.auto();
  const reference = { suggestion_id: value.suggestion_id, expected_revision: value.revision };
  const bad = await f.api('/tasks', { ...game.request({ ...goal, count: 5 }, 'bad-ref'), suggestion_ref: reference });
  assert.equal(bad.value.error, 'GAME_SUGGESTION_GOAL_CHANGED'); assert.equal(f.manager.store.list('task').items.length, 0);
  assert.equal(f.manager.store.get("SELECT count(*) n FROM idempotency WHERE request_id='bad-ref'").n, 0);
  const task = (await f.api('/tasks', { ...game.request(goal, 'valid-ref'), suggestion_ref: reference })).value;
  assert.equal(f.manager.suggestions.get(value.suggestion_id).task_id, task.task_id);
  game.send('task_update', { delivery_seq: 1, transition_seq: 2, task: { ...task, version: 2, state: 'cancelled', effect_status: 'unknown', reason: 'FIXTURE_CANCEL' } });
  await until(() => f.manager.tasks.raw(task.task_id).state === 'cancelled');
  const second = await f.api('/tasks', { ...game.request(goal, 'new-attempt'), suggestion_ref: { ...reference, expected_revision: f.manager.suggestions.get(value.suggestion_id).revision } });
  assert.equal(second.value.error, 'GAME_SUGGESTION_NOT_ACCEPTED'); assert.equal(f.manager.store.list('task').items.length, 1);
});

test('bounded audience summaries and capacity use live candidates rather than the most recent closed-history page', async t => {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); await f.connect(); const original = proposal(f);
  for (let index = 0; index < 105; index++) {
    const value = f.manager.suggestions.create({ ...goal, count: index + 10 }, ['fixture-history-' + index], {
      origin: { kind: 'audience', platform: 'bilibili', room_id: '100', vote_id: null } });
    f.manager.suggestions.decision(value.suggestion_id, { request_id: 'history-reject-' + index, expected_revision: value.revision, action: 'reject', reason: 'fixture_closed_history' });
  }
  assert(!f.manager.suggestions.page({ limit: 100 }).items.some(value => value.suggestion_id === original.suggestion_id));
  assert.equal(f.manager.suggestions.summary().suggestions[0].suggestion_id, original.suggestion_id);
  f.platformEvent({ text: command }); assert.equal(f.manager.suggestions.get(original.suggestion_id).support_count, 2);
});
