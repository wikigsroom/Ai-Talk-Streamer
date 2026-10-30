import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { initialPersona } from '../backend/dsh-bridge/persona.mjs';
import { loadPolicy } from '../backend/dsh-bridge/policy.mjs';

const root = resolve(import.meta.dirname, '..');
test('naimei persona contains only published naimei identity facts', () => {
  const value = initialPersona(root, 'naimei');
  const identity = JSON.stringify(value.document.identityCard);
  assert.match(identity, /奶妹/);
  assert.doesNotMatch(identity, /林知夏|大学生|22岁|日光宿舍/);
  assert.equal(value.character.age, null);
  assert.match(value.version, /^naimei-v1-/);
});
test('female-a remains independently addressable', () => {
  const value = initialPersona(root, 'female-a');
  assert.equal(value.character.name, '林知夏');
  assert.match(value.version, /^female-a-v1-/);
  assert.match(JSON.stringify(value.document), /22岁/);
});
test('naimei policy uses its own state root and explicit identity source', () => {
  const policy = loadPolicy(root, 'configs/naimei/bridge-policy.json');
  assert.equal(policy.identity.character_id, 'naimei');
  assert.equal(policy.deployment.state_relative_path, 'state/naimei');
});
test('persona selection rejects a path instead of loading it', () => {
  assert.throws(() => initialPersona(root, '../female-a'), /CHARACTER_ID_INVALID/);
});
