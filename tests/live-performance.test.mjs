import test from 'node:test';
import assert from 'node:assert/strict';
import { LivePerformance } from '../backend/game/performance.mjs';
import { speechState } from '../backend/game/model-state.mjs';
import { fishScore } from '../backend/dsh-bridge/community/fish/rank.mjs';
import { createMood,decay,applyDelta } from '../backend/dsh-bridge/community/mood/core.mjs';
import { lookupMeme,closeMemeDictionary } from '../backend/dsh-bridge/community/memewiki/index.mjs';
import { narrationFixture,terminalTask } from './game-narration-fixture.mjs';
import { validate } from '../backend/game/protocol.mjs';

test('native navigation failure without an item id keeps the bridge and narration alive',async t=>{
  const f=await narrationFixture(t);
  const goal={skill:'navigate',target:{dimension:'minecraft:overworld',x:33,y:64,z:48},radius:2};
  const {item}=await terminalTask(f,{outcome:'failed',reason:'GAME_NAVIGATION_NO_ROUTE',requestPatch:{goal}});
  assert.equal(f.manager.faulted,undefined);
  assert.equal(f.manager.state.connected,true);
  assert.equal(item.kind,'task_result');
  assert.equal(f.manager.narration.rawSource(item.kind,item.source_id).reason,'GAME_NAVIGATION_NO_ROUTE');
  assert.doesNotThrow(()=>f.manager.narration.scheduler.metadata(item.kind,item.source_id));
});

test('autonomous intermediate arrivals cannot fill speech with the same next-step promise',async t=>{
  const f=await narrationFixture(t),q=f.manager.narration;
  for(const x of [33,37,41]) {
    const {item}=await terminalTask(f,{requestPatch:{goal:{skill:'navigate',target:{dimension:'minecraft:overworld',x,y:64,z:48},radius:2}}});
    assert.equal(item.state,'discarded');assert.equal(item.reason,'INTERMEDIATE_NAVIGATION_SUPPRESSED');
  }
  assert.equal(q.open().length,0);assert.equal(f.calls.length,0);
  assert.equal(f.manager.store.meta('live_mood_v1',null),null,'routine arrival is not repeated emotional success');
  const {item}=await terminalTask(f);assert.equal(item.state,'pending','productive task result retains its turn');
});

test('autonomous speech enters the existing queue only in the live fresh AUTO world, without viewer fabrication',async t=>{
  const f=await narrationFixture(t),q=f.manager.narration;
  const original=f.manager.state.view.bind(f.manager.state);
  f.manager.config.planner.enabled=true;
  f.manager.state.view=()=>({...original(),mode:'AUTO',screen:'gameplay',freshness:'fresh'});
  try {
  q.performance=new LivePerformance(q,{random:()=>0});q.performance.tick();
  f.advanceClock(19000);q.performance.tick();
  const item=q.open().find(x=>x.kind==='programme_beat');assert(item);validate('Narration',item);
  assert.equal(item.group,'status');assert.deepEqual(item.source_event_ids,[]);
  const source=q.rawSource(item.kind,item.source_id);assert.equal(source.producer,'autonomous_programme');
  assert.equal(source.world_session_id,original().world_session_id);
  assert.equal(f.calls.length,0,'pacing cannot create an independent LLM');
  f.advanceClock(60000);q.performance.tick();assert.equal(q.open().filter(x=>x.kind==='programme_beat').length,1,'busy queue is not flooded');
  q.finish(item,'cancelled','fixture');f.manager.state.view=()=>({...original(),mode:'PAUSED'});
  f.advanceClock(60000);q.performance.tick();assert.equal(q.open().length,0);
  } finally { f.manager.state.view=original; }
});

test('speech context excludes growing route geometry and preserves actual health, identity and uncertainty',()=>{
  const input={world_id:'w',world_session_id:'s',freshness:'fresh',player:{health:9,food:10},inventory:[{item_id:'minecraft:stone',count:2}],
    unknown_fields:['unloaded_chunks'],details:{navigation:{frontiers:Array(500).fill({x:30,y:70,z:30})},environment:{day_time:14000},nearby_hostiles:[{entity_id:7}]}};
  const copy=structuredClone(input),value=speechState(input);
  assert(JSON.stringify(value).length<1300);assert.deepEqual(value.player,input.player);assert.deepEqual(value.unknown_fields,input.unknown_fields);
  assert.equal(value.inventory,undefined);assert.equal(value.details.navigation,undefined);assert.deepEqual(input,copy);
});

test('fish ranking matches Chinese phrases without decaying stable preferences or editing memory',()=>{
  const now=Date.now(),old=new Date(now-120*86400000).toISOString();
  const stable={content:'喜欢喝茶',fact_key:'preference.drink',updated_at:old,pinned:0};
  const event={...stable,fact_key:'event.drink'};
  assert(fishScore(stable,'你喜欢喝茶吗',now).relevance>0);
  assert.equal(fishScore(stable,'喜欢喝茶',now).activation,1);
  assert(fishScore(event,'喜欢喝茶',now).activation<1);
  assert.equal(fishScore(stable,'铁镐',now).relevance,0);
  assert.deepEqual(stable,{content:'喜欢喝茶',fact_key:'preference.drink',updated_at:old,pinned:0});
});

test('game mood records source once, decays naturally and stays bounded after repeated failures',()=>{
  const s=createMood(0);applyDelta(s,{moodDelta:9,dims:{happy:12},reason:'made a pickaxe',confidence:100,source_id:'actual-task'},0);
  assert.equal(s.mood,73);assert.equal(s.dims.happy,12);decay(s,3*3600000);
  assert.equal(s.mood,71.5);assert.equal(s.dims.happy,3);
  for(let i=0;i<100;i++)applyDelta(s,{moodDelta:-10,dims:{worry:5},reason:'failed',source_id:'t'+i},i);
  assert(s.mood>=0&&s.mood<=100);assert.equal(s.timeline.length,32);
});

test('actual pinned meme dictionary opens read-only, handles a real query and closes',t=>{
  t.after(closeMemeDictionary);
  const found=lookupMeme('yyds');assert(found);assert.equal(typeof found.title,'string');
  assert.equal(lookupMeme('不存在的梗-4839204820'),null);
});
