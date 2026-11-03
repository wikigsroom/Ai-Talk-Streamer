import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import taskFailures from '../web/mc-task-failures.js';

test('all fixed native material and crafting failure codes have operator wording', () => {
  const source = readFileSync(new URL('../game-adapters/minecraft/fabric/src/main/java/dev/aitalkstreamer/mc/core/LocalTaskFailure.java', import.meta.url), 'utf8');
  const names = source.split('public enum Reason {')[1].split('}')[0].match(/\b(?:CRAFT|MATERIAL|RESOURCE|COOKING|STORAGE)_[A-Z_]+\b/g);
  const folder = '../game-adapters/minecraft/survival/src/main/java/dev/aitalkstreamer/mc/survival/';
  const localSources = ['MaterialAllocation', 'MaterialTargets', 'ResourceMaterialsPlan', 'MaterialReservations', 'ResourceMaterials', 'ResourceAcquisitionPlan', 'ResourceBranchRecovery',
    'ControlledMaterialUse', 'ControlledRecipeResourcesTask', 'ControlledResourceCraftTask', 'ResourceRecipePlan', 'CraftSpec', 'CraftPlan', 'CraftClicks', 'ConfirmedCraftTask', 'ControlledSmeltingTask', 'SmeltingPlan', 'CookingWorkstation', 'ControlledCookingTask', 'ControlledFoodCookingTask', 'CookingExchange', 'ControlledStorage', 'StorageExchange', 'StorageLedger', 'StorageObservers'];
  const nativeSources = ['../game-adapters/minecraft/neoforge/src/main/java/dev/aitalkstreamer/mc/neoforge/NativeCraft.java',
    '../game-adapters/minecraft/neoforge/src/main/java/dev/aitalkstreamer/mc/neoforge/NativeCraftPlan.java',
    '../game-adapters/minecraft/neoforge/src/main/java/dev/aitalkstreamer/mc/neoforge/NativeSmelt.java',
    '../game-adapters/minecraft/neoforge/src/main/java/dev/aitalkstreamer/mc/neoforge/NativeSmeltPlan.java',
    '../game-adapters/minecraft/fabric/src/main/java/dev/aitalkstreamer/mc/core/CookingExchange.java',
    '../game-adapters/minecraft/fabric/src/main/java/dev/aitalkstreamer/mc/core/CraftExchange.java'];
  const sources = [...localSources.map(name => folder + name + '.java'), ...nativeSources];
  const required = new Set(sources.flatMap(path => readFileSync(new URL(path, import.meta.url), 'utf8').match(/\b(?:GAME_)?(?:CRAFT|MATERIAL|RESOURCE|COOKING|STORAGE)_[A-Z_]+\b/g)?.map(code => code.startsWith('GAME_') ? code : 'GAME_' + code) || []));
  assert.equal(required.size, 97);assert.equal(names.length, required.size);
  assert.deepEqual(new Set(names.map(name => 'GAME_' + name)), required);
  for (const name of names) {
    const code = 'GAME_' + name, value = taskFailures.describe(code);
    assert(value, code);assert.equal(value.code, code);assert.match(value.label, /[\u4e00-\u9fff]/u);
    assert(value.detail.length > 10);assert(value.action.length > 10);assert(Object.isFrozen(value));
  }
});

test('unknown, inherited and nearly matching names have no invented explanation', () => {
  for (const value of ['__proto__', 'constructor', 'toString', 'GAME_CRAFT_UNKNOWN', 'GAME_CRAFT_SERVER_TIMEOUT private', null, 42, {}, ''])
    assert.equal(taskFailures.describe(value), null);
});

test('reserved building and disposal failures retain the actual partial effects and original task', () => {
  const task = { task_id: 'original-task', state: 'failed', reason: 'GAME_RESOURCE_MATERIAL_RESERVED', effect_status: 'partial', evidence: [{ kind: 'inventory', summary: 'earlier confirmed work' }] };
  const before = structuredClone(task), facts = taskFailures.facts(task);
  assert.equal(facts.execution_failure.label, '物品正由当前任务保留');
  assert.equal(facts.execution_failure.category, 'materials');
  assert.equal(facts.task_id, task.task_id);assert.equal(facts.effect_status, 'partial');
  assert.deepEqual(facts.evidence, before.evidence);assert.deepEqual(task, before);
});

test('read-only failure facts retain the actual partial effect and evidence without rewriting the task', () => {
  const task = { state: 'failed', reason: 'GAME_CRAFT_SERVER_DIVERGED', effect_status: 'partial', evidence: [{ kind: 'craft_result', summary: 'one confirmed batch' }] };
  const original = structuredClone(task), result = taskFailures.facts(task);
  assert.deepEqual(task, original);assert.equal(result.effect_status, 'partial');assert.deepEqual(result.evidence, task.evidence);
  assert.equal(result.execution_failure.label, '合成结果尚未确认');assert.equal(result.execution_failure.code, task.reason);
  result.execution_failure.label = 'changed copy';assert.equal(taskFailures.describe(task.reason).label, '合成结果尚未确认');
});

test('accepted, running and successful records never gain a failure fact', () => {
  for (const state of ['accepted', 'running', 'succeeded']) {
    const task = { state, reason: 'GAME_CRAFT_MATERIALS_MISSING', effect_status: 'unknown' };
    assert.strictEqual(taskFailures.facts(task), task);assert.equal(task.execution_failure, undefined);
  }
});

test('an unknown terminal reason stays unknown and cancelled partial effects remain partial', () => {
  const unknown = { state: 'failed', reason: 'UNSUPPORTED_OLD_REASON', effect_status: 'unknown' };
  assert.strictEqual(taskFailures.facts(unknown), unknown);
  const result = taskFailures.facts({ state: 'cancelled', reason: 'GAME_CRAFT_CONTEXT_CHANGED', effect_status: 'partial' });
  assert.equal(result.state, 'cancelled');assert.equal(result.effect_status, 'partial');assert.equal(result.execution_failure.category, 'context');
});


test('material cycles and exhausted sources describe actual bounded checks without promising no effects', () => {
  const cycle = taskFailures.describe('GAME_RESOURCE_MATERIAL_CYCLE');
  assert.equal(cycle.label, '材料依赖出现循环');assert.match(cycle.detail, /祖先任务链/);assert.match(cycle.detail, /库存数量未变化/);
  const exhausted = taskFailures.describe('GAME_RESOURCE_MATERIAL_NO_PROGRESS');
  assert.match(exhausted.detail, /所需材料数量没有增加/);assert.match(exhausted.detail, /可用来源已尝试/);
  assert.equal(taskFailures.facts({state:'failed',reason:cycle.code,effect_status:'partial'}).effect_status,'partial');
});


test('smelting and cooking explanations retain partial effects and cover missing fuel and server timeout', () => {
  for(const [code,label] of [['GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE','熔炼燃料尚未备齐'],['GAME_COOKING_SERVER_TIMEOUT','炉内转换确认超时']]) {
    const task={state:'failed',reason:code,effect_status:'partial',evidence:[{kind:'inventory',summary:'existing output'}]};
    const before=structuredClone(task),facts=taskFailures.facts(task);assert.equal(facts.execution_failure.label,label);
    assert.equal(facts.effect_status,'partial');assert.deepEqual(facts.evidence,task.evidence);assert.deepEqual(task,before);
  }
});
