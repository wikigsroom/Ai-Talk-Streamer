import test from 'node:test';
import assert from 'node:assert/strict';
import { physicalTakeoverConfirmed as confirmed } from './mc-neoforge-proof.mjs';
const before = { bridge_boot_id: 'boot-current', world_session_id: 'world-current', control_epoch: 5 };
function sample() {
  return { after: { ...before, control_epoch: 6, mode: 'PAUSED', inputs_released: true,
    freshness: 'fresh', screen: 'gameplay', player: { health: 20 } },
  facts: { in_world: true, alive: true, health: 20, screen: 'gameplay', control_mode: 'PAUSED',
    control_proof: { ...before, control_epoch: 6, last_stop: { epoch: 6, reason: 'LOCAL_PANIC_KEY' } } } };
}
test('a released local panic with the same live world and exact stop epoch is a physical witness', () => {
  const { after, facts } = sample(); assert.equal(confirmed(before, after, facts, 'PAUSED', 'LOCAL_PANIC_KEY'), true);
});
test('the actual death-stop shape cannot pass as F10 even though mode epoch and release match', () => {
  const { after, facts } = sample(); after.screen = 'death'; after.player.health = 0;
  facts.alive = false; facts.health = 0; facts.control_proof.last_stop.reason = 'GUI_BLOCKED';
  assert.equal(confirmed(before, after, facts, 'PAUSED', 'LOCAL_PANIC_KEY'), false);
});
test('a GUI pause or other physical cause does not establish the requested panic cause', () => {
  for (const reason of ['GUI_BLOCKED', 'LEASE_EXPIRED', 'PHYSICAL_MOUSE_INPUT']) {
    const { after, facts } = sample(); facts.control_proof.last_stop.reason = reason;
    assert.equal(confirmed(before, after, facts, 'PAUSED', 'LOCAL_PANIC_KEY'), false);
  }
});
test('missing delayed or previous-world facts cannot corroborate a current control receipt', () => {
  for (const mutate of [f => f.control_proof.bridge_boot_id = 'boot-old', f => f.control_proof.world_session_id = 'world-old',
    f => f.control_proof.last_stop.epoch = 4, f => f.control_proof.control_epoch = 4]) {
    const { after, facts } = sample(); mutate(facts);
    assert.equal(confirmed(before, after, facts, 'PAUSED', 'LOCAL_PANIC_KEY'), false);
  }
  const { after } = sample(); assert.equal(confirmed(before, after, null, 'PAUSED', 'LOCAL_PANIC_KEY'), false);
});
