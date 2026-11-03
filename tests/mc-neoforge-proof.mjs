/** Engineering witness: a GUI/death stop cannot stand in for an actual physical-input cause. */
export function physicalTakeoverConfirmed(before, after, facts, mode, reason) {
  const proof = facts?.control_proof;
  return !!(after.freshness === 'fresh' && after.screen === 'gameplay' && after.player?.health > 0
    && after.mode === mode && after.control_epoch > before.control_epoch && after.inputs_released
    && before.bridge_boot_id === after.bridge_boot_id && before.world_session_id === after.world_session_id
    && facts?.in_world && facts.alive && facts.health > 0 && facts.screen === 'gameplay'
    && proof?.bridge_boot_id === before.bridge_boot_id && proof.world_session_id === before.world_session_id
    && proof.control_epoch === after.control_epoch && proof.last_stop?.epoch === after.control_epoch
    && proof.last_stop.reason === reason && facts.control_mode === mode);
}
