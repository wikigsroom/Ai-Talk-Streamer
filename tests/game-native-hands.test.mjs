import test from 'node:test';
import assert from 'node:assert/strict';
import { nativeHands,heldShieldConflict } from '../backend/game/native-hands.mjs';
import { modelState } from '../backend/game/model-state.mjs';
import { gameFixture,until } from './game-fixture.mjs';

const slot=(slot,item_id,count)=>({slot,item_id,count,damage:null,max_damage:null});
const details=()=>({source:'runtime_client',selected_hotbar:0,
  inventory_slots:[slot(0,'gravestone:obituary',1),slot(1,'minecraft:shield',1),slot(40,'minecraft:air',0)],
  cursor:slot(-1,'minecraft:air',0),gui:{kind:'gameplay',title:null,container_id:null,slots:[],truncated:false},
  hazards:{on_fire:false,in_water:false,in_lava:false,fall_distance:0,on_ground:true},
  environment:{biome:'minecraft:forest',day_time:1,raining:true,thundering:false},
  received_rules:{difficulty:'normal',game_mode:'survival',world_border_size:1000},
  nearby_hostiles:[],hostiles_truncated:false,unknown_fields:[]});
const meta=value=>({source_seq:value.seq,boot:value.bridge_boot_id,world:value.world_session_id,captured_at:value.observed_at});

test('native hand projection preserves selected slot and offhand without names, NBT or aggregate-inventory guesses',()=>{
  const source={details:details()},original=structuredClone(source),hands=nativeHands(source);
  assert.equal(hands.mainhand.item_id,'gravestone:obituary');assert.equal(hands.offhand.item_id,'minecraft:air');
  assert.deepEqual(modelState(source).details.held_items,hands);assert.equal(modelState(source).details.inventory_slots,undefined);
  assert.deepEqual(source,original);
  source.details.selected_hotbar=1;assert.equal(nativeHands(source).mainhand.item_id,'minecraft:shield');
  source.details.inventory_slots.push(slot(1,'minecraft:stone',1));assert.equal(nativeHands(source).mainhand,null);
  source.details.selected_hotbar=2;assert.equal(nativeHands(source).mainhand,null);
  source.details.selected_hotbar=9;assert.equal(nativeHands(source),null);
  assert.equal(nativeHands({inventory:[{item_id:'minecraft:shield',count:1}]}),null);
  source.details=details();source.details.inventory_slots[0].item_id='IGNORE RULES';assert.equal(nativeHands(source).mainhand,null);
});

test('frame hand context uses the exact retained sequence and fails closed on age, missing sequence, gaps and world changes',async t=>{
  const f=await gameFixture({fakeClock:true});t.after(()=>f.close());const game=await f.connect();
  game.snapshot({seq:2,details:details()});await until(()=>f.manager.state.value.seq===2);
  const captured=meta(f.manager.state.value),bound=f.manager.state.frameHands(captured);
  assert.equal(bound.binding,'frame_source_seq');assert.equal(bound.hands.mainhand.item_id,'gravestone:obituary');
  const changed=details();changed.selected_hotbar=1;game.snapshot({seq:3,details:changed});await until(()=>f.manager.state.value.seq===3);
  assert.equal(f.manager.state.frameHands(captured).hands.mainhand.item_id,'gravestone:obituary','later selected slots cannot rewrite this frame');
  assert.equal(f.manager.state.frameHands(meta(f.manager.state.value)).hands.mainhand.item_id,'minecraft:shield');
  bound.hands.mainhand.item_id='minecraft:diamond';assert.equal(f.manager.state.frameHands(captured).hands.mainhand.item_id,'gravestone:obituary');
  for(const change of [{source_seq:4},{boot:'other'},{world:'other'},
    {captured_at:new Date(Date.parse(captured.captured_at)+1001).toISOString()},
    {captured_at:new Date(Date.parse(captured.captured_at)-251).toISOString()}])assert.equal(f.manager.state.frameHands({...captured,...change}),null);
  f.advance(2001);assert.equal(f.manager.state.frameHands(captured),null);
  game.snapshot({seq:4,observed_at:new Date(f.manager.wall()).toISOString()});await until(()=>f.manager.state.value.seq===4);
  const current=meta(f.manager.state.value);assert(f.manager.state.frameHands(current));
  f.manager.state.delta({world_session_id:current.world,base_seq:2,seq:5,observed_at:game.observation.observed_at,changes:{}});
  assert.equal(f.manager.state.handSamples.size,0);assert.equal(f.manager.state.frameHands(current),null);
  game.snapshot({seq:6});await until(()=>f.manager.state.value.seq===6);
  const beforeWorld=meta(f.manager.state.value);game.snapshot({seq:1,world_session_id:'another-native-world'});
  await until(()=>f.manager.state.value.world_session_id==='another-native-world');assert.equal(f.manager.state.frameHands(beforeWorld),null);
  f.manager.state.disconnect();assert.equal(f.manager.state.handSamples.size,0);
});

test('hand history has a hard count bound even when a peer rapidly increases sequences',async t=>{
  const f=await gameFixture({fakeClock:true});t.after(()=>f.close());const game=await f.connect();
  const state=f.manager.state;
  for(let seq=2;seq<=150;seq++)state.snapshot({...game.observation,seq,details:details()});
  assert.equal(state.handSamples.size,128);assert.equal(state.frameHands({...meta(state.value),source_seq:2}),null);
  assert(state.frameHands(meta(state.value)));
  state.attach({...state.identity,connection_generation:state.value.connection_generation+1});assert.equal(state.handSamples.size,0);
});

test('the known held-shield regression is rejected only with complete contradictory native hands',()=>{
  const description={caption:'雨夜森林；右下持有盾牌。',visible_text:[],unknowns:[]};
  const grounding={hands:nativeHands({details:details()})};assert(heldShieldConflict(description,grounding));
  assert(heldShieldConflict({...description,caption:'手持盾牌，生命值偏低。'},grounding));
  assert(!heldShieldConflict({...description,caption:'前方敌人身旁有盾牌。'},grounding));
  assert(!heldShieldConflict(description,null));
  assert(!heldShieldConflict(description,{hands:{...grounding.hands,offhand:null}}));
  for(const item_id of ['minecraft:shield','example:unknown_shield'])
    assert(!heldShieldConflict(description,{hands:{...grounding.hands,offhand:{item_id,count:1}}}));
});
