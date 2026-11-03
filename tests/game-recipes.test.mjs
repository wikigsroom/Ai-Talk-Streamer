import test from 'node:test';
import assert from 'node:assert/strict';
import { recipeResult } from '../backend/game/recipes.mjs';
import { gameFixture, samples, until } from './game-fixture.mjs';

const pending = { recipeParams: { item_id: 'minecraft:iron_pickaxe', count: 1 }, admittedSeq: 1 };
const example = () => structuredClone(samples['recipe-result'].value);
const incomplete = () => {
  const result = example(); result.truncated = true;
  result.unknown_fields.push('unprojectable_received_recipe_outputs', 'candidate_count', 'ambiguous');
  return result;
};

test('known static recipes from an incomplete modded catalogue retain their explicit unknowns', () => {
  const result = incomplete(); assert.equal(recipeResult(result, pending), result);
  assert.equal(result.inventory_checked, false); assert.equal(result.candidate_count, 1);
});

test('incomplete catalogue cannot hide its uncertainty or claim there is no recipe', () => {
  for (const field of ['unprojectable_received_recipe_outputs', 'candidate_count', 'ambiguous']) {
    const result = incomplete(); result.unknown_fields = result.unknown_fields.filter(value => value !== field);
    assert.throws(() => recipeResult(result, pending), { code: 'GAME_RECIPE_RESULT_INVALID' });
  }
  const result = incomplete(); Object.assign(result, { recipe_known: false, candidate_count: 0, ambiguous: false, recipes: [] });
  assert.throws(() => recipeResult(result, pending), { code: 'GAME_RECIPE_RESULT_INVALID' });
  const unmarked = incomplete(); unmarked.truncated = false;
  assert.throws(() => recipeResult(unmarked, pending), { code: 'GAME_RECIPE_RESULT_INVALID' });
});

test('modded candidate counts can exceed the old scan limit while returned choices remain bounded', () => {
  const result = example(); Object.assign(result, { candidate_count: 9000, ambiguous: true, truncated: true });
  assert.doesNotThrow(() => recipeResult(result, pending));
  result.candidate_count = 65537; assert.throws(() => recipeResult(result, pending));
});

test('DSH recipe query accepts an incomplete live projection without dropping its connection', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect();
  const request = f.manager.tools.invoke('game_get_recipe', pending.recipeParams, { worldSessionId: game.observation.world_session_id });
  const query = await game.next('query'); const result = incomplete();
  Object.assign(result, { world_session_id: game.observation.world_session_id, based_on_seq: game.observation.seq });
  const operation = f.manager.operation(query.payload.operation_id);
  game.send('query_result', { ...operation, state: 'succeeded', result, error: null });
  const response = await request; assert.equal(response.state, 'succeeded');
  assert.equal(response.result.truncated, true); assert.equal(f.manager.state.view().connected, true);
  assert.ok(response.result.unknown_fields.includes('candidate_count')); assert.equal(f.manager.tasks.active(), null);
});
test('recipe projection retains components and inventory unknowns and has no success evidence', () => {
  const result = example(); recipeResult(result, pending);
  assert.equal(result.inventory_checked, false); assert.equal(result.effect_status, undefined);
  assert.ok(result.unknown_fields.includes('inventory_allocation'));
});
test('recipe response correlates the requested item, quantity and admitted observation without requiring a not-yet-sent snapshot', () => {
  for (const patch of [{ item_id: 'minecraft:diamond' }, { requested_count: 2 }, { based_on_seq: 0 }]) {
    assert.throws(() => recipeResult({ ...example(), ...patch }, pending));
  }
  assert.doesNotThrow(() => recipeResult({ ...example(), based_on_seq: 1044 }, pending));
});
test('nominal batch arithmetic and shape must agree with the returned recipe', () => {
  for (const patch of [{ batches: 2 }, { output_for_batches: 2 }, { width: 2 }, { layout: 'shapeless' }]) {
    const result = example(); Object.assign(result.recipes[0], patch); assert.throws(() => recipeResult(result, pending));
  }
});
test('ambiguity, truncation and ingredient alternatives cannot silently disappear', () => {
  for (const mutate of [r => { r.candidate_count = 2; }, r => { r.truncated = true; },
    r => { r.recipes[0].slots[0].alternatives_total = 2; }, r => { r.recipes[0].slots[0].empty = true; }]) {
    const result = example(); mutate(result); assert.throws(() => recipeResult(result, pending));
  }
});
test('missing recipes stay unknown and unknown fields are mandatory', () => {
  const absent = { ...example(), recipe_known: false, candidate_count: 0, ambiguous: false, recipes: [] };
  recipeResult(absent, pending);
  const hidden = example(); hidden.unknown_fields = ['inventory_allocation'];
  assert.throws(() => recipeResult(hidden, pending), { code: 'GAME_RECIPE_UNKNOWNS_MISSING' });
});
test('duplicate recipe identities and duplicate alternatives are rejected', () => {
  const duplicate = example(); duplicate.recipes.push(structuredClone(duplicate.recipes[0]));
  duplicate.candidate_count = 2; duplicate.ambiguous = true;
  assert.throws(() => recipeResult(duplicate, pending));
  const alternatives = example(); alternatives.recipes[0].slots[0].alternatives.push('minecraft:iron_ingot');
  assert.throws(() => recipeResult(alternatives, pending));
});
test('DSH recipe tool consumes one validated response from the correlated live protocol query', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect();
  const tool = f.manager.tools.invoke('game_get_recipe', pending.recipeParams, { worldSessionId: game.observation.world_session_id });
  const query = await game.next('query');
  const result = { ...example(), world_session_id: game.observation.world_session_id, based_on_seq: game.observation.seq };
  const operation = f.manager.operation(query.payload.operation_id);
  game.send('query_result', { ...operation, state: 'succeeded', result, error: null });
  const response = await tool; assert.equal(response.state, 'succeeded');
  assert.equal(response.result.source, 'TEST_FIXTURE_ONLY'); assert.equal(response.result.inventory_checked, false);
  assert.equal(f.manager.tasks.active(), null); assert.equal(f.manager.state.value.mode, 'PAUSED');
});
test('recipe capability is required and an invalid response is not exposed as a successful tool result', async t => {
  const f = await gameFixture(); t.after(() => f.close()); const game = await f.connect();
  const state = f.manager.state.view();
  const op = f.manager.query({ request_id: 'invalid-recipe', bridge_boot_id: state.bridge_boot_id,
    world_session_id: state.world_session_id, kind: 'recipe', params: pending.recipeParams });
  await game.next('query'); const result = { ...example(), world_session_id: state.world_session_id, based_on_seq: state.seq };
  result.recipes[0].batches = 7;
  game.send('query_result', { ...op, state: 'succeeded', result, error: null });
  await game.next('protocol_error', m => m.payload.error === 'GAME_RECIPE_RESULT_INVALID');
  await until(() => f.manager.operation(op.operation_id).state === 'failed');
  const next = await f.connect({ generation: 2, features: { recipes: false } });
  await assert.rejects(() => f.manager.tools.invoke('game_get_recipe', pending.recipeParams,
    { worldSessionId: next.observation.world_session_id }), { code: 'GAME_CAPABILITY_UNAVAILABLE' });
});
