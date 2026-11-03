import test from 'node:test';
import assert from 'node:assert/strict';
import { gameFixture } from './game-fixture.mjs';
import { validate } from '../backend/game/protocol.mjs';
const target={dimension:'minecraft:overworld',x:1361,y:75,z:-152};
const goal={skill:'use_item',item_id:'minecraft:crafting_table',purpose:'activate',target};

test('targeted workstations cannot widen ordinary item activation or consume actions',()=>{
  validate('Goal',goal);validate('Goal',{...goal,item_id:'minecraft:furnace'});
  validate('Goal',{...goal,item_id:'minecraft:dirt'});
  for (const bad of [{...goal,purpose:'eat'},{...goal,purpose:'equip'},{...goal,item_id:'minecraft:stone'},
    {...goal,item_id:'mod:crafting_table'},{...goal,target:{...target,x:1.5}}]) assert.throws(()=>validate('Goal',bad));
});

test('terrain placement has an independent check and dispatch capability, not planting or workstation permission',async t=>{
  for(const supported of [false,true]) {
    const f=await gameFixture();t.after(()=>f.close());
    const game=await f.connect({features:{targeted_planting:true,targeted_block_placement:true,
      targeted_terrain_placement:supported},itemUses:['activate']});await game.auto('terrain-auto-'+supported);
    const state=f.manager.state.view(),same={...goal,item_id:'minecraft:dirt',target:{...target,dimension:state.player.position.dimension}};
    const check=await f.api('/queries',{request_id:'terrain-check-'+supported,bridge_boot_id:state.bridge_boot_id,
      world_session_id:state.world_session_id,kind:'check_action',params:{goal:same}});
    assert.equal(check.status,supported?202:503,JSON.stringify(check));
    const start=await f.api('/tasks',game.request(same,'terrain-start-'+supported));
    assert.equal(start.status,supported?202:503,JSON.stringify(start));
    if(supported)assert.deepEqual((await game.next('task_start')).payload.request.goal,same);
    else assert.equal(game.messages.some(row=>row.type==='task_start' || row.type==='query_request'),false);
  }
});
test('construction requires its own native feature, preserves target, and rejects other dimensions',async t=>{
  for (const supported of [false,true]) {
    const f=await gameFixture();t.after(()=>f.close());
    const game=await f.connect({features:{targeted_planting:true,targeted_block_placement:supported},itemUses:['activate']});
    await game.auto('construction-auto-'+supported);
    const position=f.manager.state.view().player.position,same={...goal,target:{...target,dimension:position.dimension}};
    if (supported) {
      const state=f.manager.state.view();
      const bad=await f.api('/queries',{request_id:'construction-wrong-dimension',bridge_boot_id:state.bridge_boot_id,
        world_session_id:state.world_session_id,kind:'check_action',params:{goal:{...same,target:{...target,
          dimension:position.dimension==='minecraft:the_nether'?'minecraft:overworld':'minecraft:the_nether'}}}});
      assert.equal(bad.status,409);assert.equal(bad.value.error,'GAME_PRECONDITION_FAILED');
    }
    const start=await f.api('/tasks',game.request(same,'construction-start-'+supported));
    assert.equal(start.status,supported?202:503,JSON.stringify(start));
    if(supported) assert.deepEqual((await game.next('task_start')).payload.request.goal,same);
    else assert.equal(game.messages.some(row=>row.type==='task_start'),false);
  }
});
