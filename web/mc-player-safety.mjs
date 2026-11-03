/** Presentation of current observations only; never issues a game command. */
export function playerSafety(state,{synchronized=true}={}) {
  if(!state)return null;
  if(!synchronized || !state.connected || state.freshness!=='fresh')return {
    severity:'unknown',title:'当前生存状态待确认',
    copy:'连接或观测已中断，页面保留的数据可能已经变化。',
    action:'Agent等待新的现场观测；观测恢复后按当前自动游玩设置重新规划。明确停止会继续保持。'};
  const p=state.player, d=state.details;
  if(state.screen==='death' || (typeof p?.health==='number' && p.health<=0))return {
    severity:'critical',title:'角色已死亡',
    copy:'死亡前的位置与库存不能作为当前可用物资；重生也不代表已取回掉落物。',
    action:'Agent仅在已启用普通重生、现场条件满足且未明确停止时重生；取得新的生命、位置、背包和任务回执后重新规划。'};
  const danger=[];
  if(typeof p?.health==='number' && p.health<=8)danger.push('生命偏低');
  if(typeof p?.food==='number' && p.food<=6)danger.push('饱食偏低');
  if(typeof p?.oxygen==='number' && p.oxygen<40)danger.push('氧气不足');
  if(d?.hazards?.on_fire)danger.push('正在燃烧');
  if(d?.hazards?.in_lava)danger.push('位于熔岩中');
  if((d?.nearby_hostiles?.length||0)>0)danger.push('附近有敌对生物');
  const e=d?.environment;
  if(e?.singleplayer===true && e.game_paused===true && e.local_server_published===false)return {
    severity:danger.length?'critical':'notice',title:'单人世界已暂停',
    copy:danger.length?danger.join('、')+'；这些危险仍需在恢复后处理。':'已收到当前单人世界的实际暂停观测。',
    action:'世界处于暂停保护。已启用自动开始时，由Agent核对现场并恢复；明确停止会保持暂停。'};
  if(danger.length)return {severity:'critical',title:'当前需要生存处理',copy:danger.join('、')+'。',
    action:state.mode==='AUTO'?'Agent优先处理实际防御、进食和撤离；结果以任务回执为准。':'自动操作已停止，游戏是否暂停以游戏内实际状态为准。符合自动恢复条件后由Agent继续处理危险；明确停止会保持。'};
  if(state.mode!=='AUTO')return {severity:'notice',title:'自动游玩已暂停',
    copy:'暂停自动操作不等于暂停游戏，请留意游戏内的暂停状态。',
    action:'Agent按已启用的自动恢复规则重新取得现场观测和控制；明确停止后保持暂停。'};
  return null;
}
