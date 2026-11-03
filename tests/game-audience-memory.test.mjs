import test from 'node:test';
import assert from 'node:assert/strict';
import { narrationFixture } from './game-narration-fixture.mjs';
import { MemoryService, validateExtraction } from '../backend/memory/service.mjs';
import { eventPrincipal } from '../backend/platforms/events.mjs';

async function fixture(t, generate) {
  const f = await narrationFixture(t, generate);
  const port = { requestMemorySnapshot: () => null, setNativeMemoryInjection() {}, setVerifiedMirrorRevision() {}, inspectProjection: () => null };
  f.memory = new MemoryService(f.db, f.state, f.bridge.policy, port, { audienceSources: request => f.manager.narration.memorySources(request) });
  f.bridge.memory = f.memory;
  return f;
}
async function add(f, user = 'viewer-a', text = '还记得我喜欢喝什么吗？') {
  const { key } = await f.comment(text, { user_id: user, nickname: '同名观众' });
  return { key, original: f.platforms.store.get('SELECT * FROM events WHERE event_key=?', key) };
}
function seed(f, source, value) {
  const principal = eventPrincipal(source.original), text = value === 'tea' ? '我喜欢茶。' : '我喜欢咖啡。';
  f.db.tx(() => f.db.event(f.state.scope({ broadcast_id: f.state.current().broadcast_id }, { actor_kind: 'viewer', actor_id: principal.principal_id }), 'input.accepted', { text, partition_key: principal.viewer_id }));
  const sources = f.memory.eligibleEvents(f.state.current().broadcast_id, principal.viewer_id).filter(event => event.text === text);
  const candidate = validateExtraction({ schema_version: 1, summary: '', open_questions: [], candidate_facts: [{ fact_key: 'preference.drink', value, polarity: 'positive', evidence_kind: 'viewer_statement', source_refs: [{ event_id: sources.at(-1).event_id, quote: text }], validity: 'persistent_candidate' }] }, sources, principal.viewer_id)[0];
  f.db.tx(() => f.memory.mergeInTransaction(candidate, 'fixture', 0));
  return principal.viewer_id;
}
const context = f => JSON.parse(f.calls.at(-1).context);
const own = (value, key) => value.audience_memory.participants.find(participant => participant.platform_event_keys.includes(key));
const countInputs = f => f.db.get("SELECT COUNT(*) n FROM stream_events e JOIN event_payloads p USING(event_seq) WHERE e.event_type='input.accepted' AND json_extract(p.payload_json,'$.audience_source') IS NOT NULL").n;

test('an actual narration retry reuses both accepted personal sources and binds the new request without duplicating them', async t => {
  const f = await fixture(t); await add(f); await add(f, 'viewer-b');
  f.manager.narration.tick(); const first = f.state.activate(); assert(first);
  f.manager.narration.generationFailed(first.request_id, 'GAME_NARRATION_FACTS_CHANGED');
  const second = await f.run(); assert(second && second.request_id !== first.request_id);
  assert.equal(countInputs(f), 2); assert.equal(f.memory.audience.scope(second).sources.length, 2);
  assert.equal(f.state.request(first.request_id).status, 'CANCELLED');
});

test('both real merged personal statements remain separately eligible for extraction and produce no public preference', async t => {
  const f = await fixture(t), a = await add(f, 'viewer-a', '我喜欢茶。'), b = await add(f, 'viewer-b', '我喜欢茶。');
  const request = await f.run();
  for (const source of [a, b]) {
    const partition = eventPrincipal(source.original).viewer_id, events = f.memory.eligibleEvents(request.broadcast_id, partition);
    assert.equal(events.length, 1);
    const candidate = validateExtraction({ schema_version: 1, summary: '', open_questions: [], candidate_facts: [{ fact_key: 'preference.drink', value: 'tea', polarity: 'positive', evidence_kind: 'viewer_statement', source_refs: [{ event_id: events[0].event_id, quote: '我喜欢茶。' }], validity: 'persistent_candidate' }] }, events, partition)[0];
    f.db.tx(() => f.memory.mergeInTransaction(candidate, 'actual-source-fixture', 0));
    assert.equal(f.memory.recall(partition).viewer[0].value, 'tea');
  }
  assert.equal(f.memory.eligibleEvents(request.broadcast_id, 'public').length, 0);
  assert.equal(f.memory.recall('public').public.length, 0);
});

test('32 real personal sources fit the existing canonical context budget without expanding it', async t => {
  const f = await fixture(t);
  for (let n = 0; n < 32; n++) await add(f, 'budget-viewer-' + n);
  const request = await f.run(); assert(request);
  assert.equal(f.memory.audience.scope(request).sources.length, 32);
  assert.equal(f.calls.length, 1, 'the actual request must reach the model');
  const saved = f.db.get('SELECT context_json FROM request_contexts WHERE request_id=?', request.request_id);
  assert(saved.context_json.length <= 7800);
  assert(JSON.stringify(context(f).narration.source).length <= 16384);
  assert.equal(context(f).audience_memory.participants.length, 32);
});

test('a real merged reply binds both stable accounts despite identical nicknames and keeps the shared request public', async t => {
  const f = await fixture(t), a = await add(f), b = await add(f, 'viewer-b'); const request = await f.run(); assert(request);
  assert.equal(request.viewer_id, null);
  const scope = f.memory.audience.scope(request); assert.equal(scope.sources.length, 2);
  assert.deepEqual(new Set(scope.sources.map(source => source.partition_key)), new Set([eventPrincipal(a.original).viewer_id, eventPrincipal(b.original).viewer_id]));
  assert.equal(context(f).audience_memory.participants.length, 2);
  const payloads = f.db.all("SELECT payload_json FROM stream_events e JOIN event_payloads p USING(event_seq) WHERE e.request_id=? AND e.event_type='input.accepted'", request.request_id).map(row => JSON.parse(row.payload_json));
  assert(payloads.filter(payload => payload.audience_source).every(payload => !Object.hasOwn(payload, 'user_id') && !Object.hasOwn(payload, 'nickname')));
});

test('merged model context labels each account memory with its actual source and excludes an unrelated account', async t => {
  const f = await fixture(t), a = await add(f), b = await add(f, 'viewer-b');
  seed(f, a, 'tea'); seed(f, b, 'coffee');
  const other = { original: { ...a.original, user_id: 'unrelated' } }; seed(f, other, 'coffee');
  await f.run(); const value = context(f);
  assert.equal(own(value, a.key).confirmed_memory[0].value, 'tea'); assert.equal(own(value, b.key).confirmed_memory[0].value, 'coffee');
  assert.equal(value.confirmed_memory.viewer.length, 0); assert.equal(value.audience_memory.participants.length, 2);
  assert(!JSON.stringify(value).includes(eventPrincipal(other.original).viewer_id));
});

test('memory recall selects only the server-owned source account, defaults shared replies to public and rejects caller identities', async t => {
  const f = await fixture(t), a = await add(f), b = await add(f, 'viewer-b'); seed(f, a, 'tea'); seed(f, b, 'coffee');
  const request = await f.run(), value = context(f);
  assert.equal(f.memory.recallForRequest(request, {}).viewer.length, 0);
  assert.deepEqual(f.memory.recallForRequest(request, { source_event_id: own(value, a.key).source_event_ids[0] }).viewer.map(entry => entry.value), ['tea']);
  assert.deepEqual(f.memory.recallForRequest(request, { source_event_id: own(value, b.key).source_event_ids[0] }).viewer.map(entry => entry.value), ['coffee']);
  assert.throws(() => f.memory.recallForRequest(request, { viewer_id: eventPrincipal(b.original).viewer_id }), { code: 'RECALL_SCHEMA' });
  assert.throws(() => f.memory.recallForRequest(request, { source_event_id: 'evt-not-in-this-request' }), { code: 'MEMORY_SOURCE_OUT_OF_SCOPE' });
});

test('a proposal for the second actual source belongs to that account and remains pending rather than becoming active memory', async t => {
  const f = await fixture(t), a = await add(f, 'viewer-a', '我喜欢茶。'), b = await add(f, 'viewer-b', '我喜欢茶。');
  const request = await f.run(), ref = own(context(f), b.key).source_event_ids[0];
  const result = f.memory.propose(request, { fact_key: 'preference.drink', value: 'tea', polarity: 'positive', source_event_id: ref, quote: '我喜欢茶。' });
  const proposal = f.db.get('SELECT * FROM memory_proposals WHERE proposal_id=?', result.proposal_id);
  assert.equal(proposal.subject_key, eventPrincipal(b.original).viewer_id); assert.notEqual(proposal.subject_key, eventPrincipal(a.original).viewer_id);
  assert.equal(proposal.state, 'PENDING'); assert.equal(f.db.get('SELECT COUNT(*) n FROM memory_entries').n, 0);
  assert.throws(() => f.memory.propose(request, { fact_key: 'preference.drink', value: 'tea', source_event_id: ref, quote: '茶', subject_key: eventPrincipal(a.original).viewer_id }), { code: 'PROPOSAL_SCHEMA' });
});

test('an unknown identity remains public input and cannot create a personal or global preference from a self statement', async t => {
  const f = await fixture(t); await add(f, null, '我喜欢茶。'); const request = await f.run();
  assert.equal(request.viewer_id, null); assert.equal(context(f).audience_memory.participants.length, 0); assert.equal(context(f).audience_memory.unidentified_events, 1);
  assert.equal(f.memory.eligibleEvents(request.broadcast_id, 'public').filter(source => source.event_type === 'input.accepted').length, 0);
  const source = f.memory.audience.scope(request).sources[0];
  assert.throws(() => f.memory.propose(request, { fact_key: 'preference.drink', value: 'tea', source_event_id: source.event_id, quote: '茶' }), { code: 'MEMORY_SOURCE_OUT_OF_SCOPE' });
});

test('a relay UID claim cannot read the official collector account memory', async t => {
  const f = await fixture(t), a = await add(f); seed(f, a, 'tea');
  for (const item of f.manager.narration.open()) f.manager.narration.finish(item, 'cancelled', 'FIXTURE_CLEAR');
  f.platforms.ingest('bilibili', { type: 'comment', room_id: '100', event_id: 'relay-a', user_id: a.original.user_id, nickname: '同名观众', text: '还记得我喜欢喝什么吗？', occurred_at: f.manager.wall() }, { source: 'local_relay' });
  await f.platforms.dispatch(); const request = await f.run(); assert(request);
  assert.equal(request.viewer_id, null); assert.equal(context(f).audience_memory.participants.length, 0); assert.equal(f.memory.recallForRequest(request, {}).viewer.length, 0);
});

test('shared formal completion stays one public playback fact while each original input retains its own partition', async t => {
  const f = await fixture(t), a = await add(f), b = await add(f, 'viewer-b'); const request = await f.run();
  assert.equal(countInputs(f), 2); assert.equal(f.complete().result.accepted, true); await new Promise(resolve => queueMicrotask(resolve));
  for (const item of [a, b]) {
    const events = f.memory.eligibleEvents(request.broadcast_id, eventPrincipal(item.original).viewer_id);
    assert.equal(events.filter(source => source.event_type === 'input.accepted').length, 1);
    assert.equal(events.filter(source => source.event_type === 'playback.completed').length, 0);
  }
  assert.equal(f.memory.eligibleEvents(request.broadcast_id, 'public').filter(source => source.event_type === 'playback.completed').length, 1);
});

test('multiple actual events from one account retain event evidence without inventing a second viewer', async t => {
  const f = await fixture(t), a = await add(f); await add(f); const request = await f.run();
  assert.equal(request.viewer_id, eventPrincipal(a.original).viewer_id); assert.equal(context(f).audience_memory.participants.length, 1);
  assert.equal(own(context(f), a.key).source_event_ids.length, 2); assert.equal(countInputs(f), 2);
});

test('binding an already queued request again is idempotent and does not duplicate accepted input evidence', async t => {
  const f = await fixture(t); await add(f); await add(f, 'viewer-b'); f.manager.narration.tick();
  const request = f.state.status().queued[0]; assert(request);
  const before = countInputs(f); f.memory.bindAudience(request); f.memory.bindAudience(request);
  assert.equal(countInputs(f), before); assert.equal(f.db.get("SELECT COUNT(*) n FROM stream_events WHERE request_id=? AND event_type='audience.bound'", request.request_id).n, 1);
});

test('a source change during model work refuses memory tools and prevents stale media', async t => {
  let refusal;
  const f = await fixture(t, async (options, active) => {
    const value = JSON.parse(options.context), source = value.audience_memory.participants[0], request = active.state.active();
    active.room.messageControl({ action: 'hide', id: source.platform_event_keys[0] });
    try { active.memory.recallForRequest(request, { source_event_id: source.source_event_ids[0] }); } catch (error) { refusal = error.code; }
    return { text: '这段旧回应不能播出。' };
  });
  await add(f); await add(f, 'viewer-b'); await f.run(); assert.equal(refusal, 'GAME_NARRATION_FACTS_CHANGED'); assert.equal(f.media.filter(value => value.action === 'speak').length, 0);
});

test('a real binding storage failure rolls back source events and cancels the unbound queued request', async t => {
  const f = await fixture(t); await add(f); const event = f.db.event.bind(f.db);
  f.db.event = (scope, type, payload) => { if (type === 'audience.bound') throw new Error('fixture source binding unavailable'); return event(scope, type, payload); };
  try { f.manager.narration.tick(); } finally { f.db.event = event; }
  assert.equal(countInputs(f), 0); assert.equal(f.state.status().queued.length, 0);
  assert.equal(f.db.get("SELECT COUNT(*) n FROM requests WHERE status='CANCELLED'").n, 1); assert.equal(f.calls.length, 0); assert.equal(f.media.length, 0);
});

test('an unbound MC-marked request cannot fall back to the anchor viewer memory', async t => {
  const f = await fixture(t), a = await add(f); seed(f, a, 'tea');
  const request = f.state.accept(eventPrincipal(a.original), { text: '伪造合并来源', idempotency_key: 'fixture-unbound', source: { collector: 'mc-narration' } });
  assert.throws(() => f.memory.context(request, { revision: 'fixture' }), { code: 'AUDIENCE_SCOPE_UNBOUND' });
});

test('the actual processRequest tool callback uses source-scoped recall rather than the legacy viewer shortcut', async t => {
  const f = await fixture(t, async options => {
    const value = JSON.parse(options.context), b = own(value, f.b.key);
    assert.equal((await options.tools('stream_memory_recall', {})).viewer.length, 0);
    assert.deepEqual((await options.tools('stream_memory_recall', { source_event_id: b.source_event_ids[0] })).viewer.map(entry => entry.value), ['coffee']);
    return { text: '我分别记得你们的偏好。' };
  });
  const a = await add(f); f.b = await add(f, 'viewer-b'); seed(f, a, 'tea'); seed(f, f.b, 'coffee');
  await f.run(); assert.equal(f.media.filter(value => value.action === 'speak').length, 1);
});
