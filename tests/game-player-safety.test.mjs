import test from 'node:test';
import assert from 'node:assert/strict';
import { playerSafety } from '../web/mc-player-safety.mjs';

const live = (patch={}) => ({connected:true,freshness:'fresh',screen:'gameplay',mode:'PAUSED',player:{health:20,food:20,oxygen:300},...patch});
test('paused automation does not claim a running multiplayer server, healthy AUTO clears the warning',()=>{
  const state=live(),before=structuredClone(state);
  assert.match(playerSafety(state).copy,/不等于暂停游戏/);
  assert.doesNotMatch(playerSafety(state).copy,/仍在服务器/);
  assert.match(playerSafety(state).action,/明确停止后保持暂停/);
  assert.deepEqual(state,before);
  assert.equal(playerSafety(live({mode:'AUTO'})),null);
});
test('death supersedes paused warning; fresh life alone never proves recovered inventory',()=>{
  const death=playerSafety(live({screen:'death',player:{health:0}}));
  assert.equal(death.severity,'critical');assert.match(death.copy,/不代表已取回/);
  assert.match(death.action,/Agent.*普通重生.*未明确停止/);assert.match(death.action,/生命、位置、背包和任务回执/);
  assert.match(playerSafety(live()).title,/自动游玩已暂停/);
  assert.match(playerSafety(live({player:{health:0}})).title,/已死亡/);
});
test('disconnected, stale and unsynchronized observations never present historical death or vitals as current',()=>{
  for(const state of [live({connected:false,screen:'death'}),live({freshness:'stale',player:{health:0}})]){
    assert.equal(playerSafety(state).severity,'unknown');assert.doesNotMatch(playerSafety(state).title,/已死亡/);
  }
  assert.equal(playerSafety(live(),{synchronized:false}).severity,'unknown');
});
test('danger stays actionable during AUTO and PAUSED; unknown vitals are not coerced to zero',()=>{
  for(const player of [{health:8},{food:6},{oxygen:39}])assert.equal(playerSafety(live({player})).severity,'critical');
  for(const details of [{hazards:{on_fire:true}},{hazards:{in_lava:true}},{nearby_hostiles:[{}]}])assert.equal(playerSafety(live({details})).severity,'critical');
  assert.match(playerSafety(live({mode:'AUTO',player:{health:8}})).action,/实际防御/);
  assert.match(playerSafety(live({player:{health:8}})).action,/游戏内实际状态/);
  assert.equal(playerSafety(live({mode:'AUTO',player:{health:null,food:null,oxygen:null}})),null);
});
test('only fresh, explicit native singleplayer pause facts confirm the world is paused',()=>{
  const environment={singleplayer:true,game_paused:true,local_server_published:false};
  const safe=live({screen:'menu',details:{environment}}),before=structuredClone(safe);
  assert.equal(playerSafety(safe).title,'单人世界已暂停');
  assert.deepEqual(safe,before);
  for(const patch of [{singleplayer:false},{game_paused:false},{local_server_published:true},
    {local_server_published:null},{singleplayer:null},{game_paused:'true'}]){
    assert.notEqual(playerSafety(live({details:{environment:{...environment,...patch}}})).title,'单人世界已暂停');
  }
  assert.notEqual(playerSafety(live({details:{environment:{singleplayer:true,game_paused:true}}})).title,'单人世界已暂停');
  for(const patch of [{connected:false},{freshness:'stale'}])assert.equal(playerSafety({...safe,...patch}).severity,'unknown');
  assert.equal(playerSafety(safe,{synchronized:false}).severity,'unknown');
  assert.match(playerSafety({...safe,screen:'death'}).title,/角色已死亡/);
  const danger=playerSafety({...safe,player:{health:5,food:4},details:{environment,hazards:{on_fire:true}}});
  assert.equal(danger.title,'单人世界已暂停');assert.equal(danger.severity,'critical');
  assert.match(danger.copy,/生命偏低.*饱食偏低.*正在燃烧.*恢复后处理/);
});
