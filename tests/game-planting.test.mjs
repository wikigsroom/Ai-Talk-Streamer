import test from 'node:test';
import assert from 'node:assert/strict';
import { gameFixture as fixture } from './game-fixture.mjs';
import { validate } from '../backend/game/protocol.mjs';

const target={dimension:'minecraft:overworld',x:1361,y:75,z:-152};
const goal={skill:'use_item',item_id:'minecraft:wheat_seeds',purpose:'activate',target};

test('planting requires an explicit crop cell and cannot repurpose eating or block activation',()=>{
  for(const item_id of ['wheat_seeds','carrot','potato','beetroot_seeds'])
    validate('Goal',{...goal,item_id:'minecraft:'+item_id});
  for(const rejected of [{...goal,target:undefined},{...goal,purpose:'eat'},
    {...goal,item_id:'minecraft:stone'},{...goal,item_id:'mod:wheat_seeds'},
    {...goal,target:{...target,x:1.25}},{...goal,target:{...target,command:'invalid'}}])
    assert.throws(()=>validate('Goal',JSON.parse(JSON.stringify(rejected))));
  validate('Goal',{skill:'use_item',item_id:'minecraft:carrot',purpose:'eat'});
  validate('Goal',{skill:'use_item',item_id:'minecraft:crafting_table',purpose:'activate'});
});

test('an adapter without planting capability cannot receive planting checks or tasks',async t=>{
  const f=await fixture();t.after(()=>f.close());const game=await f.connect({itemUses:['eat','equip','activate']});
  await game.auto('plant-legacy-auto');
  const state=f.manager.state.view();
  const query=await f.api('/queries',{request_id:'plant-legacy-query',bridge_boot_id:state.bridge_boot_id,
    world_session_id:state.world_session_id,kind:'check_action',params:{goal}});
  assert.equal(query.status,503);assert.equal(query.value.error,'GAME_CAPABILITY_UNAVAILABLE');
  const started=await f.api('/tasks',game.request(goal,'plant-legacy-task'));
  assert.equal(started.status,503);assert.equal(started.value.error,'GAME_CAPABILITY_UNAVAILABLE');
  assert.equal(game.messages.some(m=>m.type==='task_start'),false);
  assert.equal(game.messages.some(m=>m.type==='query' && m.payload.request?.request_id==='plant-legacy-query'),false);
});

test('supported planting preserves the exact cell on the wire and rejects another dimension',async t=>{
  const f=await fixture();t.after(()=>f.close());const game=await f.connect({features:{targeted_planting:true},itemUses:['eat','equip','activate']});
  await game.auto('plant-native-auto');
  const position=f.manager.state.view().player.position;
  const same={...goal,target:{...target,dimension:position.dimension}};
  const wrong={...goal,target:{...target,dimension:position.dimension==='minecraft:the_nether'?'minecraft:overworld':'minecraft:the_nether'}};
  const state=f.manager.state.view();
  const rejected=await f.api('/queries',{request_id:'plant-other-dimension',bridge_boot_id:state.bridge_boot_id,
    world_session_id:state.world_session_id,kind:'check_action',params:{goal:wrong}});
  assert.equal(rejected.status,409);assert.equal(rejected.value.error,'GAME_PRECONDITION_FAILED');
  const started=await f.api('/tasks',game.request(same,'plant-native-task'));
  assert.equal(started.status,202,JSON.stringify(started));
  const sent=await game.next('task_start');assert.deepEqual(sent.payload.request.goal,same);
  assert.deepEqual(started.value.goal,same);assert.notEqual(started.value.state,'succeeded');
});
