import test from 'node:test';
import assert from 'node:assert/strict';
import { gameFixture, samples, until } from './game-fixture.mjs';

async function setup(t) {
  const f = await gameFixture({ fakeClock: true }); t.after(() => f.close()); const game = await f.connect();
  const state = f.manager.state.view(), id = state.world_id;
  const context = () => ({ request_id: 'directory-' + crypto.randomUUID(), bridge_boot_id: f.manager.state.value.bridge_boot_id,
    world_session_id: f.manager.state.value.world_session_id });
  const base = async label => (await f.api('/worlds/' + id + '/bases', { ...context(),
    expected_world_revision: f.manager.worlds.get(id).revision, label, radius: 8 })).value;
  return { f, game, id, context, base, select: b => ({ ...context(), expected_revision: b.revision,
    expected_world_revision: f.manager.worlds.get(id).revision }) };
}
test('selecting an observed base updates only the world ledger and is idempotent', async t => {
  const { f, game, id, base, select } = await setup(t), first = await base('原基地'), second = await base('新基地');
  assert.equal(f.manager.worlds.get(id).active_base_id, second.base_id);
  const request = select(first), path = '/worlds/' + id + '/bases/' + first.base_id + '/select';
  const result = await f.api(path, request); assert.equal(result.status, 200); assert.equal(result.value.active_base_id, first.base_id);
  assert.deepEqual((await f.api(path, request)).value, result.value);
  assert.equal(f.manager.state.value.mode, 'PAUSED'); assert.equal(f.manager.lease, null);
  assert.equal(game.messages.filter(frame => ['task_start','control_request'].includes(frame.type)).length, 0);
});
test('base selection rejects stale world/base revisions and changed idempotent bodies', async t => {
  const { f, id, base, select } = await setup(t), target = await base('基地');
  const path = '/worlds/' + id + '/bases/' + target.base_id + '/select', request = select(target);
  assert.equal((await f.api(path, { ...request, expected_world_revision: request.expected_world_revision + 1 })).status, 409);
  assert.equal((await f.api(path, request)).status, 200);
  assert.equal((await f.api(path, { ...request, expected_revision: 2 })).value.error, 'GAME_IDEMPOTENCY_CONFLICT');
});
test('archived bases cannot become active again through selection', async t => {
  const { f, id, context, base, select } = await setup(t), target = await base('旧基地');
  const archived = await f.api('/worlds/' + id + '/bases/' + target.base_id + '/archive', {
    request_id: context().request_id, expected_revision: target.revision, expected_world_revision: f.manager.worlds.get(id).revision });
  assert.equal(archived.status, 200);
  assert.equal((await f.api('/worlds/' + id + '/bases/' + target.base_id + '/select', select(archived.value))).value.error, 'GAME_BASE_ARCHIVED');
  assert.equal(f.manager.worlds.get(id).active_base_id, null);
});
test('base selection waits for stopped control and released inputs', async t => {
  const { f, game, id, base, select } = await setup(t), target = await base('基地');
  await game.auto();
  assert.equal((await f.api('/worlds/' + id + '/bases/' + target.base_id + '/select', select(target))).value.error, 'GAME_MODE_BLOCKED');
  assert.equal(f.manager.worlds.get(id).active_base_id, target.base_id);
});
test('browsing an old world does not allow selecting its base in the current world', async t => {
  const { f, game, id, base, select } = await setup(t), target = await base('旧世界基地');
  game.snapshot({ world_id: 'world-directory-second', world_session_id: 'session-directory-second', seq: 1 });
  await until(() => f.manager.state.value.world_id === 'world-directory-second');
  const result = await f.api('/worlds/' + id + '/bases/' + target.base_id + '/select', select(target));
  assert.equal(result.value.error, 'GAME_WORLD_CHANGED');
  assert.equal((await f.api('/worlds/' + id + '/bases')).value.items[0].base_id, target.base_id);
});
test('task pagination filters by stable world across sessions and preserves the global list', async t => {
  const { f, game, id } = await setup(t);
  game.snapshot({ world_id: 'world-directory-second', world_session_id: 'session-directory-second', seq: 1 });
  await until(() => f.manager.state.value.world_id === 'world-directory-second');
  for (let i = 0; i < 7; i++) {
    const task = structuredClone(samples['task-complete'].value); task.task_id = 'directory-task-' + i;
    task.request_id = 'directory-request-' + i; task.world_id = i % 2 ? id : 'world-directory-second';
    f.manager.store.put('task', task);
  }
  const first = (await f.api('/tasks?world_id=' + id + '&limit=2')).value;
  assert.equal(first.items.length, 2); assert.ok(first.items.every(task => task.world_id === id)); assert.ok(first.next_cursor);
  const next = (await f.api('/tasks?world_id=' + id + '&limit=2&cursor=' + first.next_cursor)).value;
  assert.equal(next.items.length, 1); assert.equal(next.next_cursor, null);
  assert.equal(new Set([...first.items,...next.items].map(task => task.task_id)).size, 3);
  assert.equal((await f.api('/tasks')).value.items.length, 7);
});
test('unknown or malformed world filters fail explicitly rather than returning another world', async t => {
  const { f } = await setup(t);
  assert.equal((await f.api('/tasks?world_id=world-absent')).status, 404);
  assert.equal((await f.api('/tasks?world_id=')).status, 400);
  assert.equal((await f.api('/tasks?world_id=%27%20OR%201%3D1')).status, 400);
});
test('selected base survives a host restart without granting control or repeating the selection', async t => {
  const { f, id, base, select } = await setup(t), first = await base('保留基地'); await base('暂用基地');
  const request = select(first), path = '/worlds/' + id + '/bases/' + first.base_id + '/select';
  const selected = await f.api(path, request); await f.restartHost();
  assert.deepEqual((await f.api(path, request)).value, selected.value);
  assert.equal(f.manager.worlds.get(id).active_base_id, first.base_id); assert.ok(!f.manager.lease);
});
