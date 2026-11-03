import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { narrationFixture } from './game-narration-fixture.mjs';
import { until } from './game-fixture.mjs';
import { MemoryService, validateExtraction } from '../backend/memory/service.mjs';
import { MemoryAdministration } from '../backend/memory/administration.mjs';
import { PlatformPrivacy } from '../backend/platforms/privacy.mjs';
import { PlatformStore } from '../backend/platforms/store.mjs';
import { eventPrincipal } from '../backend/platforms/events.mjs';
import { digest } from '../backend/dsh-bridge/channel.mjs';

async function fixture(t, generate) {
  const f = await narrationFixture(t, generate), projection = new Map();
  const port = { mirrorRevision: 0, requestMemorySnapshot: () => null, setNativeMemoryInjection() {}, setVerifiedMirrorRevision() {},
    inspectProjection: id => projection.get(id), async applyPublicProjection(p) { projection.set(p.memory_id, { memory_revision: p.memory_revision, entry: p.action === 'UPSERT' ? { content: p.content, status: 'active' } : null }); return { entry_id: p.memory_id }; } };
  f.memory = new MemoryService(f.db, f.state, f.bridge.policy, port, { audienceSources: request => f.manager.narration.memorySources(request) });
  f.bridge.memory = f.memory; f.bridge.root = f.folder; f.privacy = new PlatformPrivacy(f.bridge);
  f.restarts = 0;
  f.makeAdmin = () => new MemoryAdministration(f.folder, f.db, f.state, f.memory, f.bridge.host, async () => { f.restarts++; }, {
    planProjection: input => f.privacy.prepare(input), applyProjection: plan => f.privacy.apply(plan), onPrivacyState: () => f.room.emit('snapshot', f.room.snapshot()),
  });
  f.admin = f.makeAdmin(); f.bridge.administration = f.admin;
  f.add = async (uid = 'private-uid-A-20261030', text = '还记得我喜欢喝什么吗？') => {
    const { key } = await f.comment(text, { user_id: uid, nickname: '同名观众' });
    const row = f.platforms.store.get('SELECT * FROM events WHERE event_key=?', key);
    return { key, row, subject: eventPrincipal(row).viewer_id };
  };
  f.seed = (subject, value = 'tea', source) => {
    if (!source) {
      const text = value === 'tea' ? '我喜欢茶。' : '我喜欢咖啡。';
      f.db.tx(() => f.db.event(f.state.scope({ broadcast_id: f.state.current().broadcast_id }), 'input.accepted', { text, partition_key: subject }));
      source = f.memory.eligibleEvents(f.state.current().broadcast_id, subject).at(-1);
    }
    const candidate = validateExtraction({ schema_version: 1, summary: '', open_questions: [], candidate_facts: [{ fact_key: 'preference.drink', value, polarity: 'positive', evidence_kind: 'viewer_statement', source_refs: [{ event_id: source.event_id, quote: source.text }], validity: 'persistent_candidate' }] }, [source], subject)[0];
    return f.db.tx(() => f.memory.mergeInTransaction(candidate, 'privacy-fixture', 0));
  };
  f.remove = (source, extra = {}) => f.admin.delete(f.bridge.auth.resolve(), { operation_id: 'privacy-delete-' + source.key.slice(0, 20), subject_key: source.subject, ...extra });
  return f;
}

test('deleting one merged viewer erases dependent shared content but retains the other actual input, memory and truthful completed status', async t => {
  const f = await fixture(t), a = await f.add(), b = await f.add('private-uid-B-20261030');
  f.seed(a.subject); f.seed(b.subject, 'coffee'); const request = await f.run(), scope = f.memory.audience.scope(request);
  f.complete(); await new Promise(setImmediate);
  assert.equal(f.state.request(request.request_id).status, 'COMPLETED');
  await f.remove(a);
  assert.equal(f.memory.recall(a.subject).viewer.length, 0); assert.equal(f.memory.recall(b.subject).viewer[0].value, 'coffee');
  for (const source of scope.sources) assert.equal(!!f.db.payload(source.event_seq)?.redacted, source.partition_key === a.subject);
  assert.equal(f.db.payload(request.input_event_seq).redacted, true);
  assert.equal(f.db.get('SELECT context_json FROM request_contexts WHERE request_id=?', request.request_id).context_json, null);
  assert.equal(f.state.request(request.request_id).status, 'COMPLETED');
  assert.equal(f.room.store.message(a.key), null); assert(f.room.store.message(b.key));
  const erased = f.platforms.store.get('SELECT * FROM events WHERE event_key=?', a.key);
  assert.equal(erased.text, ''); assert.equal(erased.user_id, null); assert.equal(erased.detail, '{}');
  assert.equal(f.admin.locked, false); assert.equal(f.restarts, 1);
});

test('deletion while the real model request is awaiting a result prevents its late text from entering media', async t => {
  let enter, release; const entered = new Promise(r => enter = r), held = new Promise(r => release = r);
  const f = await fixture(t, async () => { enter(); await held; return { text: '这是删除前生成的旧回答。' }; });
  const a = await f.add(), b = await f.add('private-uid-B-20261030');
  const running = f.run(); await entered; const request = f.state.active();
  await f.remove(a); release(); await running;
  assert(['CANCELLED', 'INTERRUPTED'].includes(f.state.request(request.request_id).status));
  assert.equal(f.media.filter(item => item.action === 'speak').length, 0); assert(f.room.store.message(b.key));
});

test('a merged request is cancelled before activation when one bound owner is deleted', async t => {
  const f = await fixture(t), a = await f.add(); await f.add('private-uid-B-20261030');
  f.manager.narration.tick(); const request = f.state.status().queued[0]; assert(request);
  await f.remove(a); assert.equal(f.state.request(request.request_id).status, 'CANCELLED'); assert.equal(f.state.activate(), null);
});

test('selected-memory deletion removes its original event without deleting a later message from that same account', async t => {
  const f = await fixture(t), a = await f.add(undefined, '我喜欢茶。'); const request = await f.run();
  const source = f.memory.eligibleEvents(request.broadcast_id, a.subject).find(event => event.text === '我喜欢茶。');
  const memory = f.seed(a.subject, 'tea', source); f.complete(); f.advanceClock(1);
  const later = await f.add(undefined, '现在背包里有什么？');
  await f.remove(a, { memory_id: memory.memory_id });
  assert.equal(f.room.store.message(a.key), null); assert(f.room.store.message(later.key));
  assert.equal(f.platforms.store.get('SELECT COUNT(*) n FROM privacy_fences').n, 0);
  assert.equal(f.platforms.store.isPrivacyDeleted(a.row), true); assert.equal(f.platforms.store.isPrivacyDeleted(later.row), false);
});

test('a partial Room failure leaves a durable privacy barrier and the same operation can repair it without a second deletion generation', async t => {
  const f = await fixture(t), a = await f.add(), b = await f.add('private-uid-B-20261030'); await f.run();
  const original = f.room.eraseSources.bind(f.room); f.room.eraseSources = () => { throw Object.assign(new Error('fixture storage fault'), { code: 'FIXTURE_ROOM_IO' }); };
  await assert.rejects(f.remove(a), { code: 'FIXTURE_ROOM_IO' });
  assert(f.admin.locked && f.admin.privacyPending); assert.equal(f.room.snapshot().messages.length, 0);
  assert(f.db.get("SELECT 1 FROM runtime_meta WHERE key='privacy_redaction_pending'")); const generation = f.state.room().deletion_generation;
  assert.throws(() => f.platforms.ingest('bilibili', {}), { code: 'MEMORY_PRIVACY_PENDING' });
  f.room.eraseSources = original; await f.remove(a);
  assert.equal(f.state.room().deletion_generation, generation); assert.equal(f.admin.locked, false);
  assert.equal(f.room.store.message(a.key), null); assert(f.room.snapshot().messages.some(item => item.id === b.key));
});

test('a reconstructed administration resumes a committed deletion after an interrupted projection', async t => {
  const f = await fixture(t), a = await f.add(); await f.run();
  const original = f.room.eraseSources.bind(f.room); f.room.eraseSources = () => { throw new Error('fixture interrupted projection'); };
  await assert.rejects(f.remove(a)); f.room.eraseSources = original;
  f.admin = f.makeAdmin(); f.bridge.administration = f.admin; assert(f.admin.locked && f.admin.privacyPending);
  await f.admin.resumePrivacy({ all: true }); assert.equal(f.admin.locked, false); assert.equal(f.room.store.message(a.key), null);
});

test('old platform and Room rows restored after a completed deletion are redacted before readiness', async t => {
  const f = await fixture(t), a = await f.add(), b = await f.add('private-uid-B-20261030'); await f.run();
  const rows = f.platforms.store.all('SELECT * FROM events'), roomRow = f.room.store.one('SELECT * FROM messages WHERE id=?', a.key);
  const old = new PlatformStore(join(f.folder, 'restored-platforms.sqlite3'), () => f.manager.wall());
  for (const row of rows) { const columns = Object.keys(row); old.run(`INSERT INTO events(${columns.join(',')}) VALUES(${columns.map(() => '?').join(',')})`, ...Object.values(row)); }
  await f.remove(a); f.platforms.store.close(); f.platforms.store = old;
  f.room.store.run('INSERT INTO messages VALUES (?,?,?,?,?,?)', ...Object.values(roomRow));
  await f.admin.resumePrivacy({ all: true });
  assert.equal(old.get('SELECT user_id FROM events WHERE event_key=?', a.key).user_id, null);
  assert.equal(f.room.store.message(a.key), null); assert(f.room.store.message(b.key));
});

test('a durable event tombstone blocks replay after row pruning, while fresh input from the same account is allowed', async t => {
  const f = await fixture(t), a = await f.add(); await f.run(); await f.remove(a);
  f.platforms.store.run('DELETE FROM events WHERE event_key=?', a.key);
  const replay = f.platforms.ingest('bilibili', { ...a.row }, { source: 'blivedm' });
  assert.equal(replay.results[0].status, 'DROPPED'); assert.equal(f.room.store.message(a.key), null);
  f.advanceClock(1); const fresh = await f.add(undefined, '这是删除之后的新消息。'); assert(f.room.store.message(fresh.key));
  const plans = f.privacy.plans(); assert.equal(plans.length, 1);
  const ledger = JSON.stringify(plans); assert(!ledger.includes(a.row.user_id) && !ledger.includes(a.row.nickname) && !ledger.includes(a.row.text));
});

test('unmapped historical account rows keep full deletion explicitly incomplete until ownership coverage is resolved', async t => {
  const f = await fixture(t), a = await f.add(); await f.run();
  const value = { ...f.room.store.message(a.key), id: digest('legacy-row'), event_key: digest('legacy-row'), user_key: digest('unmapped-owner') };
  f.room.store.run('INSERT INTO messages VALUES (?,?,?,?,0,0)', value.id, value.event_key, value.received_at, JSON.stringify(value));
  await assert.rejects(f.remove(a), { code: 'MEMORY_PRIVACY_COVERAGE_INCOMPLETE' });
  assert(f.admin.privacyPending); assert.equal(f.room.snapshot().messages.length, 0);
  assert(f.room.store.message(value.id), 'unknown ownership is not guessed from a nickname');
  f.room.store.run('DELETE FROM messages WHERE id=?', value.id); await f.remove(a); assert.equal(f.admin.locked, false);
});

test('platform schema upgrades cannot silently downgrade a newer persisted database', async t => {
  const f = await fixture(t), file = join(f.folder, 'future-platform.sqlite3'), db = new DatabaseSync(file);
  db.exec('PRAGMA user_version=4');
  assert.throws(() => new PlatformStore(file), { code: 'PLATFORM_SCHEMA_UNSUPPORTED' });
  assert.equal(db.prepare('PRAGMA user_version').get().user_version, 4); db.close();
});

test('privacy withdrawal removes only the erased account ballots and suggestion support, including an older game projection replay', async t => {
  const f = await fixture(t), state = f.manager.state.value;
  const vote = f.manager.votes.create({ request_id: 'privacy-vote-create', bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id, title: '采什么', duration_seconds: 60,
    options: [{ option_id: 'wood', label: '木头', goal: { skill: 'gather', item_id: 'minecraft:oak_log', count: 2 } }, { option_id: 'stone', label: '石头', goal: { skill: 'gather', item_id: 'minecraft:cobblestone', count: 2 } }] }).value;
  const a = await f.add(undefined, '投票 wood'); await f.add('private-uid-B-20261030', '投票 stone');
  const saved = f.manager.store.get('SELECT * FROM vote_ballots WHERE event_id=?', a.key);
  const sa = await f.add(undefined, '建议 采集 minecraft:oak_log 4'), sb = await f.add('private-uid-B-20261030', '建议 采集 minecraft:oak_log 4');
  const suggestion = f.manager.suggestions.page().items.find(value => value.source_event_ids.includes(sa.key)); assert(suggestion);
  await f.remove(a);
  const current = f.manager.votes.get(vote.vote_id); assert.deepEqual(current.options.map(option => option.votes), [0, 1]);
  const after = f.manager.suggestions.get(suggestion.suggestion_id);
  assert.equal(after.state, 'proposed'); assert(!after.source_event_ids.includes(sa.key) && after.source_event_ids.includes(sb.key));
  assert.equal(f.manager.audienceSources.rows(after.suggestion_id).some(row => row.event_id === sa.key), false);
  f.manager.store.run('INSERT INTO vote_ballots VALUES(?,?,?,?)', ...Object.values(saved));
  f.privacy.applyGameHistory(f.manager); assert.equal(f.manager.store.get('SELECT COUNT(*) n FROM vote_ballots WHERE event_id=?', a.key).n, 0);
});

test('failed Humanity removal stays pending until the real mirror outbox acknowledges that removal', async t => {
  const f = await fixture(t); f.seed('public'); await f.memory.project();
  const apply = f.memory.port.applyPublicProjection; f.memory.port.applyPublicProjection = async () => { throw new Error('fixture Humanity unavailable'); };
  const target = { key: digest('public-memory-deletion'), subject: 'public' };
  await assert.rejects(f.remove(target), { code: 'MEMORY_PRIVACY_MIRROR_PENDING' }); assert(f.admin.locked && f.admin.privacyPending);
  assert(f.db.get("SELECT COUNT(*) n FROM mirror_outbox WHERE action='REMOVE' AND state='RETRY_WAIT'").n);
  f.memory.port.applyPublicProjection = apply; f.advanceClock(5001); await f.remove(target);
  assert.equal(f.admin.locked, false); assert.equal(f.db.get("SELECT COUNT(*) n FROM mirror_outbox WHERE action='REMOVE' AND state!='APPLIED'").n, 0);
});

test('pending privacy snapshots remove previously visible text from the actual Room SSE packet', async t => {
  const f = await fixture(t), a = await f.add(); await f.run(); const packets = [];
  const client = { writableLength: 0, write: packet => { packets.push(packet); return true; }, end() {} };
  f.room.clients.add(client);
  const original = f.room.eraseSources.bind(f.room); f.room.eraseSources = () => { throw new Error('fixture Room unavailable'); };
  await assert.rejects(f.remove(a)); assert(packets.some(packet => packet.includes('event: snapshot') && packet.includes('"messages":[]')));
  assert(!packets.join('').includes(a.row.text));
  await assert.rejects(f.room.handle({ method: 'POST' }, {}, new URL('http://localhost/api/dsh/room/messages'), () => {}), { code: 'MEMORY_PRIVACY_PENDING' });
  f.room.eraseSources = original; await f.remove(a); f.room.clients.delete(client);
});

test('deleting an older personal memory invalidates later merged contexts that actually recalled it without erasing newer independent inputs', async t => {
  const f = await fixture(t), old = await f.add(undefined, '我喜欢茶。'); const first = await f.run();
  const source = f.memory.eligibleEvents(first.broadcast_id, old.subject)[0], memory = f.seed(old.subject, 'tea', source);
  f.complete(); f.advanceClock(3001);
  const seq = f.manager.state.value.seq + 1;
  f.game.snapshot({ seq, observed_at: new Date(f.manager.wall()).toISOString() });
  await until(() => f.manager.state.value.seq === seq);
  f.state.heartbeat(f.lease.lease_id, f.lease.consumer_id);
  const a = await f.add(), b = await f.add('private-uid-B-20261030'); const current = await f.run();
  assert(current, JSON.stringify({ requests: f.state.status(), candidates: f.manager.narration.all() }));
  const before = f.db.get('SELECT * FROM request_contexts WHERE request_id=?', current.request_id);
  assert(JSON.parse(before.source_manifest_json).some(ref => ref.event_seq === source.event_seq));
  assert(JSON.parse(before.context_json).audience_memory.participants.some(person => person.confirmed_memory.some(entry => entry.memory_id === memory.memory_id)));
  await f.remove(old, { memory_id: memory.memory_id });
  assert.equal(f.db.get('SELECT context_json FROM request_contexts WHERE request_id=?', current.request_id).context_json, null);
  assert(f.room.store.message(a.key) && f.room.store.message(b.key)); assert.equal(f.room.store.message(old.key), null);
});

test('selected-memory removal also resolves a normal pre-MC platform request by its persisted request association', async t => {
  const f = await fixture(t); f.manager.config.enabled = false;
  const a = await f.add(undefined, '我喜欢茶。'); assert(a.row.request_id);
  const request = await f.run(), source = f.memory.eligibleEvents(request.broadcast_id, a.subject)[0];
  const memory = f.seed(a.subject, 'tea', source); await f.remove(a, { memory_id: memory.memory_id });
  assert.equal(f.room.store.message(a.key), null); assert.equal(f.platforms.store.get('SELECT text FROM events WHERE event_key=?', a.key).text, '');
});

test('invalid deletion subject bounds are refused before creating an unrecoverable persisted privacy plan', async t => {
  const f = await fixture(t), a = await f.add(); await f.run();
  const generation = f.state.room().deletion_generation;
  for (const subject_key of ['', 'x'.repeat(301)])
    await assert.rejects(f.admin.delete(f.bridge.auth.resolve(), { operation_id: 'invalid-privacy-subject', subject_key }), { code: 'DELETION_INPUT_OR_LOCK' });
  assert.equal(f.state.room().deletion_generation, generation);
  assert.equal(f.db.get("SELECT 1 FROM runtime_meta WHERE key='privacy_redaction_pending'"), undefined);
  assert.equal(f.privacy.plans().length, 0); assert(f.room.store.message(a.key)); assert.equal(f.admin.locked, false);
});

test('a failed final privacy notification keeps its durable marker so restart or retry cannot lose the repair', async t => {
  const f = await fixture(t), a = await f.add(); await f.run();
  const notify = f.admin.onPrivacyState; let fail = true;
  f.admin.onPrivacyState = () => { if (!f.admin.privacyPending && fail) throw new Error('fixture final notification failed'); notify(); };
  await assert.rejects(f.remove(a), /fixture final notification failed/);
  assert(f.admin.privacyPending && f.admin.locked);
  assert(f.db.get("SELECT 1 FROM runtime_meta WHERE key='privacy_redaction_pending'"));
  assert.equal(f.room.store.message(a.key), null);
  const generation = f.state.room().deletion_generation; fail = false; await f.remove(a);
  assert.equal(f.state.room().deletion_generation, generation); assert.equal(f.admin.locked, false);
  assert.equal(f.db.get("SELECT 1 FROM runtime_meta WHERE key='privacy_redaction_pending'"), undefined);
});
