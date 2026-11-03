// Only IDs/counts from validated native slots enter model context; never item names or NBT text.
export function nativeHands(state) {
  const details=state?.details,selected=details?.selected_hotbar;
  if(details?.source!=='runtime_client'||!Number.isInteger(selected)||selected<0||selected>8||!Array.isArray(details.inventory_slots))return null;
  const at=slot=>{
    const rows=details.inventory_slots.filter(row=>row.slot===slot);
    if(rows.length!==1)return null;
    const row=rows[0];
    if(!/^[a-z0-9_.-]+:[a-z0-9_./-]{1,180}$/.test(row.item_id)||!Number.isSafeInteger(row.count)||row.count<0)return null;
    return {item_id:row.count===0?'minecraft:air':row.item_id,count:row.count};
  };
  return {source:'runtime_client',selected_hotbar:selected,mainhand:at(selected),offhand:at(40)};
}

// This deliberately checks the observed regression, not every possible visual hallucination.
export function heldShieldConflict(description,grounding) {
  const hands=grounding?.hands;
  if(!hands?.mainhand||!hands?.offhand)return false;
  const knownNonShield=hand=>hand.item_id==='gravestone:obituary'||hand.item_id.startsWith('minecraft:')&&hand.item_id!=='minecraft:shield';
  if(!knownNonShield(hands.mainhand)||!knownNonShield(hands.offhand))return false;
  return /(?:手持|持有|拿着|举着|举起|手握|手中|手上|右下|左下|右手|左手)[^。；，,.!?！？;]{0,18}(?:盾牌|shield\b)/iu
    .test([description.caption,...description.visible_text].join('；'));
}
