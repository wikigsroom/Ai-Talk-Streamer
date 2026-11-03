// Native protocol/solver fixtures, not Minecraft gameplay or model acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { MindcraftNativePlanner, mindcraftThreatened } from '../backend/game/mindcraft/native-planner.mjs';
import { gameFixture, until } from './game-fixture.mjs';
import { validate } from '../backend/game/protocol.mjs';
import { canonical } from '../backend/dsh-bridge/channel.mjs';

const base = new URL('../backend/game/mindcraft/',import.meta.url);
const navigation = (position,targets) => ({source:'runtime_client',sampled_at:new Date().toISOString(),origin:position,
  radius:8,search_budget:256,frontiers:targets.map(position=>({position})),action_precondition_required:true,unknown_fields:['future_collisions']});
const runtimeDetails = environment => ({source:'runtime_client',selected_hotbar:0,inventory_slots:[],
  cursor:{slot:-1,item_id:'minecraft:air',count:0,damage:null,max_damage:null},
  gui:{kind:'gameplay',title:null,container_id:null,slots:[],truncated:false},
  hazards:{on_fire:false,in_water:false,in_lava:false,fall_distance:0,on_ground:true},
  environment:{biome:'minecraft:plains',day_time:1,raining:false,thundering:false,...environment},
  received_rules:{difficulty:'normal',game_mode:'survival',world_border_size:1000},
  nearby_hostiles:[],hostiles_truncated:false,unknown_fields:[]});
const lock = JSON.parse(readFileSync(new URL('upstream.lock.json',base)));
test('Mindcraft algorithm is a fixed MIT upstream module with import injection only', () => {
  for (const file of lock.files) assert.equal(createHash('sha256').update(readFileSync(new URL(file.file,base))).digest('hex'),file.sha256);
  const original = readFileSync(new URL('upstream/item_goal.js.txt',base),'utf8');
  const body = original.split(/\r?\n/).slice(4).join('\n').replace('export class ItemGoal','class ItemGoal').trim();
  const port = readFileSync(new URL('item-goal-native.mjs',base),'utf8').replaceAll('\r\n','\n');
  assert.ok(port.includes(body)); assert.match(lock.commit,/^[0-9a-f]{40}$/);
});

function fixture(inventory=[]) {
  let state={world_session_id:'world-session-1',bridge_boot_id:'boot-1',connection_generation:1,control_epoch:8,
    seq:1,freshness:'fresh',inventory,player:{position:{dimension:'minecraft:overworld',x:0,y:64,z:0}},active_task_id:null};
  const calls=[],events=[],tasks=new Map();
  const choices={ oak_planks:[4,['oak_log']],stick:[4,['oak_planks','oak_planks']],
    crafting_table:[1,['oak_planks','oak_planks','oak_planks','oak_planks']],
    wooden_pickaxe:[1,['oak_planks','oak_planks','oak_planks','stick','stick']],
    stone_pickaxe:[1,['cobblestone','cobblestone','cobblestone','stick','stick']],
    stone_axe:[1,['cobblestone','cobblestone','cobblestone','stick','stick']],
    furnace:[1,Array(8).fill('cobblestone')],bread:[1,['wheat','wheat','wheat']] };
  const manager={state:{requireFresh:()=>state},stateView:()=>state,clock:()=>100, publish:(...args)=>events.push(args),
    tasks:{get:id=>tasks.get(id)},tools:{invoke:async(name,args)=>{
      if (name==='game_check_action' || name==='game_start_task') validate('Goal',args.goal);
      calls.push({name,args});
      if(name==='game_get_recipe') {
        const value=choices[args.item_id.slice(10)];
        return {state:'succeeded',result:{recipes:value?[{recipe_id:args.item_id,recipe_type:'minecraft:crafting',ingredients_known:true,
          output_per_batch:value[0],slots:value[1].map(item=>({empty:false,truncated:false,alternatives:['minecraft:'+item]}))}]:[]}};
      }
      if(name==='game_check_action') return {state:'succeeded',result:{allowed:true}};
      if(name==='game_start_task') {const value={task_id:'task-'+tasks.size,state:'accepted',effect_status:'unknown'};tasks.set(value.task_id,value);return value;}
      throw Error('fixture unexpected tool');
    }}};
  const planner=new MindcraftNativePlanner(manager);
  return {planner,manager,calls,events,tasks,state,observe:patch=>{state={...state,seq:state.seq+1,...patch};return state;}};
}

function pitFixture() {
  const f=fixture([{item_id:'minecraft:dirt',count:3},{item_id:'minecraft:wooden_pickaxe',count:1},
    {item_id:'minecraft:cobblestone',count:6},{item_id:'minecraft:stick',count:2}]);
  f.manager.capabilities={features:{targeted_terrain_placement:true}};
  const p=f.state.player.position,target={...p,x:4,y:p.y+5};
  f.observe({player:{position:p,health:18,food:17},details:{hazards:{on_ground:true,in_water:false,in_lava:false,on_fire:false},
    nearby_hostiles:[],construction:{source:'runtime_client',sampled_at:new Date().toISOString(),workstations:[],
      placement_sites:[{position:{...p,x:-1}},{position:{...p,x:1}},{position:{...p,y:p.y-1,z:1}}]}}});
  f.planner.current(f.manager.stateView());f.planner.lastTable={...target,y:target.y-1};
  return {...f,target};
}

test('a completed return without an observed table cannot pull the next craft back to history',async()=>{
  for(const outcome of [{state:'succeeded',effect_status:'verified'},{state:'failed',effect_status:'unknown'}]) {
    const f=fixture([{item_id:'minecraft:oak_planks',count:5},{item_id:'minecraft:stone_pickaxe',count:1},
      {item_id:'minecraft:stone_axe',count:1}]);
    f.planner.current(f.manager.stateView());const table={...f.state.player.position,x:6};
    f.planner.lastTable=table;
    await f.planner.submit({skill:'navigate',target:{...table,y:table.y+1},radius:2},{},{stage:'return_to_known_workstation'});
    Object.assign(f.tasks.get('task-0'),outcome);
    assert.equal(f.planner.settle(f.manager.stateView()),false,'wait for later native facts');
    assert.deepEqual(f.planner.lastTable,table);
    f.observe({details:{construction:{workstations:[]}}});
    assert.equal(f.planner.settle(f.manager.stateView()),true);
    assert.equal(f.planner.lastTable,null);assert.equal(f.planner.tableCandidate(f.manager.stateView(),table),false);
    assert.equal(await f.planner.bootstrap({}),true);
    assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,
      {skill:'craft',item_id:'minecraft:crafting_table',count:1});
  }
});

test('a received usable table survives a completed return; ordinary exploration does not invalidate history',async()=>{
  for(const observed of [true,false]) {
    const f=fixture();f.planner.current(f.manager.stateView());const table={...f.state.player.position,x:6};f.planner.lastTable=table;
    await f.planner.submit({skill:'navigate',target:table,radius:2},{},{stage:observed?'return_to_known_workstation':'explore_observed_frontier'});
    Object.assign(f.tasks.get('task-0'),{state:'succeeded',effect_status:'verified'});
    f.planner.settle(f.manager.stateView());
    f.observe({details:{construction:{workstations:observed?[{block_id:'minecraft:crafting_table',position:table}]:[]}}});
    assert.equal(f.planner.settle(f.manager.stateView()),true);assert.deepEqual(f.planner.lastTable,table);
    assert.equal(f.planner.unconfirmedTables.size,0);
  }
});

test('a blocked historical workstation route can place one observed adjacent support before replanning',async()=>{
  const f=pitFixture(),invoke=f.manager.tools.invoke;
  f.manager.tools.invoke=async(name,args,...rest)=>{
    if(name==='game_check_action' && args.goal.skill==='navigate') {
      f.calls.push({name,args});return {state:'succeeded',result:{allowed:false,reason:'GAME_NAVIGATION_NO_ROUTE'}};
    }
    return invoke(name,args,...rest);
  };
  assert.equal(await f.planner.bootstrap({}),true);
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,
    {skill:'use_item',item_id:'minecraft:dirt',purpose:'activate',target:{...f.state.player.position,x:1}});
  assert.equal(f.planner.lastPlan.stage,'build_exit_support');assert.equal(f.planner.terrainPlacements,1);
  assert.equal(f.calls.some(row=>row.name==='game_get_recipe'),false);
  await f.planner.bootstrap({});
  assert.equal(f.calls.filter(row=>row.name==='game_start_task').length,1,'wait for terminal receipt and later observation');
});

test('terrain support refuses stale facts, missing capability, urgent hazards, invalid sites and exhausted budget',async t=>{
  for(const change of ['capability','stale','future','health','food','water','ground','hostile','gather_budget','site','budget','stance_budget','target'])
    await t.test(change,async()=>{
      const f=pitFixture(),state=structuredClone(f.manager.stateView()),target={...f.target};
      if(change==='capability')f.manager.capabilities.features.targeted_terrain_placement=false;
      if(change==='stale')state.details.construction.sampled_at=new Date(Date.now()-10000).toISOString();
      if(change==='future')state.details.construction.sampled_at=new Date(Date.now()+10000).toISOString();
      if(change==='health')state.player.health=11.9;
      if(change==='food')state.player.food=5;
      if(change==='water')state.details.hazards.in_water=true;
      if(change==='ground')state.details.hazards.on_ground=false;
      if(change==='hostile')state.details.nearby_hostiles=[{distance:2}];
      if(change==='gather_budget'){state.inventory=[];f.planner.terrainGatherings=2;}
      if(change==='site')state.details.construction.placement_sites=[{position:state.player.position}];
      if(change==='budget')f.planner.terrainPlacements=8;
      if(change==='stance_budget')f.planner.terrainAnchors.set(canonical(state.player.position),3);
      if(change==='target')target.y=state.player.position.y;
      assert.equal(await f.planner.buildExitStep({},state,target),false);
      assert.equal(f.calls.length,0);
    });
});

test('verified support waits for a later observation and checks its exact top before the distant workstation',async()=>{
  const f=pitFixture(),p=f.manager.stateView().player.position;
  const goal={skill:'use_item',item_id:'minecraft:dirt',purpose:'activate',target:{...p,x:1}};
  await f.planner.submit(goal,{},{});f.tasks.get('task-0').state='succeeded';f.tasks.get('task-0').effect_status='verified';
  await f.planner.bootstrap({});assert.equal(f.planner.exitStance,null);
  f.observe({inventory:[{item_id:'minecraft:dirt',count:2}]});await f.planner.bootstrap({});
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,
    {skill:'navigate',target:{...p,x:1,y:p.y+1},radius:0});
  assert.equal(f.planner.lastPlan.stage,'climb_verified_support');
});

test('an exact native waypoint crosses the real action query and dispatch contracts',async t=>{
  const f=await gameFixture();t.after(()=>f.close());const game=await f.connect();await game.auto();
  const state=f.manager.stateView(),goal={skill:'navigate',target:{...state.player.position,x:state.player.position.x+1},radius:0};
  const context={purpose:'game_plan',worldSessionId:state.world_session_id,controlEpoch:state.control_epoch};
  for(const name of ['game_check_action','game_start_task']) {
    const call=f.manager.tools.invoke(name,{goal},context);
    const query=await until(()=>game.messages.find(row=>row.type==='query' && !row.waypoint_test_handled));
    query.waypoint_test_handled=true;
    assert.equal(query.payload.request.kind,'check_action');assert.deepEqual(query.payload.request.params.goal,goal);
    const operation=f.manager.operation(query.payload.operation_id);
    game.send('query_result',{...operation,state:'succeeded',result:{world_session_id:state.world_session_id,kind:'check_action',allowed:true}});
    const result=await call;
    assert.equal(result.state,name==='game_start_task'?'accepted':'succeeded');
  }
  assert.deepEqual((await game.next('task_start')).payload.request.goal,goal);
});

test('exact waypoint admission retains radius, coordinate and control fences',async t=>{
  const goal={skill:'navigate',target:{dimension:'minecraft:overworld',x:1,y:64,z:0},radius:0};
  validate('Goal',goal);
  for(const invalid of [{...goal,radius:-.001},{...goal,radius:8.001},{...goal,radius:'0'},
    {...goal,target:{...goal.target,x:1.5}}]) assert.throws(()=>validate('Goal',invalid));
  const f=await gameFixture();t.after(()=>f.close());const game=await f.connect();
  const state=f.manager.stateView();
  await assert.rejects(f.manager.tools.invoke('game_start_task',{goal},{purpose:'game_plan',
    worldSessionId:state.world_session_id,controlEpoch:state.control_epoch+1}),error=>error.code==='GAME_CONTROL_CONFLICT');
  const paused=await f.api('/tasks',game.request(goal,'exact-waypoint-paused'));
  assert.equal(paused.value.error,'GAME_MODE_BLOCKED');
  assert.equal(game.messages.some(row=>row.type==='task_start'),false);
});

test('failed and unverified placements cannot schedule a climbing stance',async()=>{
  for(const outcome of [{state:'failed',effect_status:'unknown'},{state:'succeeded',effect_status:'unknown'}]) {
    const f=pitFixture(),p=f.manager.stateView().player.position;
    await f.planner.submit({skill:'use_item',item_id:'minecraft:dirt',purpose:'activate',target:{...p,x:1}},{},{});
    Object.assign(f.tasks.get('task-0'),outcome);assert.equal(f.planner.settle(f.manager.stateView()),false);
    f.observe({});assert.equal(f.planner.settle(f.manager.stateView()),true);assert.equal(f.planner.exitStance,null);
  }
});

test('a lower adjacent bridge has native admission and empty stock requests only bounded real dirt gathering',async()=>{
  const f=pitFixture(),state=structuredClone(f.manager.stateView()),p=state.player.position;
  state.details.construction.placement_sites=[{position:{...p,x:1,y:p.y-1}}];
  assert.equal(await f.planner.buildExitStep({},state,f.target),true);
  assert.equal(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal.target.y,p.y-1);
  const g=pitFixture(),empty=structuredClone(g.manager.stateView());empty.inventory=[];
  assert.equal(await g.planner.buildExitStep({},empty,g.target),true);
  assert.deepEqual(g.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,
    {skill:'gather',item_id:'minecraft:dirt',count:2});assert.equal(g.planner.terrainGatherings,1);
  g.planner.terrainGatherings=2;assert.equal(await g.planner.buildExitStep({},empty,g.target),false);
});

test('a new control scope discards old support waypoints and terrain budgets',()=>{
  const f=pitFixture();f.planner.exitStance=f.target;f.planner.terrainPlacements=8;f.planner.terrainGatherings=2;
  f.observe({control_epoch:9});f.planner.current(f.manager.stateView());
  assert.equal(f.planner.exitStance,null);assert.equal(f.planner.terrainPlacements,0);assert.equal(f.planner.terrainGatherings,0);
});

test('rejected terrain checks never dispatch and a verified support changes the inventory route signature',async()=>{
  const f=pitFixture();
  f.manager.tools.invoke=async(name,args)=>{f.calls.push({name,args});return {state:'succeeded',result:{allowed:false,reason:'GAME_ITEM_PLACEMENT_SITE_UNAVAILABLE'}};};
  assert.equal(await f.planner.buildExitStep({},f.manager.stateView(),f.target),false);
  assert.equal(f.planner.terrainPlacements,0);assert.equal(f.calls.some(row=>row.name==='game_start_task'),false);
  const goal={skill:'navigate',target:f.target,radius:2},before=f.planner.signature(f.manager.stateView(),goal);
  f.observe({inventory:[{item_id:'minecraft:dirt',count:2}]});
  assert.notEqual(before,f.planner.signature(f.manager.stateView(),goal));
});
test('Mindcraft expands sticks through received planks to logs, preserving additional native quantities',async()=>{
  const f=fixture();
  assert.deepEqual((await f.planner.plan('minecraft:stick',4,{})).next_goal,{skill:'gather',item_id:'minecraft:oak_log',count:1});
  f.observe({inventory:[{item_id:'minecraft:oak_log',count:2}]});
  assert.deepEqual((await f.planner.plan('minecraft:stick',4,{})).next_goal,{skill:'craft',item_id:'minecraft:oak_planks',count:2});
  f.observe({inventory:[{item_id:'minecraft:oak_planks',count:4}]});
  assert.deepEqual((await f.planner.plan('minecraft:stick',4,{})).next_goal,{skill:'craft',item_id:'minecraft:stick',count:4});
  f.observe({inventory:[{item_id:'minecraft:stick',count:4}]});
  assert.equal((await f.planner.plan('minecraft:stick',4,{})).state,'satisfied');
  assert.equal(f.calls.filter(row=>row.name==='game_start_task').length,0);
});
test('unsupported dependency and changed control context cannot create a native action',async()=>{
  const f=fixture();assert.equal((await f.planner.plan('minecraft:diamond',1,{})).state,'unsupported_dependency');
  const invoke=f.manager.tools.invoke;
  f.manager.tools.invoke=async(...args)=>{const value=await invoke(...args);f.observe({control_epoch:9});return value;};
  await assert.rejects(f.planner.plan('minecraft:stick',4,{}),{code:'GAME_PLAN_CANCELLED'});
  assert.equal(f.calls.some(row=>row.name==='game_start_task'),false);
});

test('truncated modded ingredient tags use explicit vanilla members and still require native action checks',async()=>{
  const f=fixture([{item_id:'minecraft:oak_planks',count:8}]);
  const invoke=f.manager.tools.invoke;
  f.manager.tools.invoke=async(name,...args)=>{
    const value=await invoke(name,...args);
    if(name==='game_get_recipe') for(const recipe of value.result.recipes) for(const slot of recipe.slots) {
      slot.alternatives=['chipped:oak_planks_mosaic',...slot.alternatives];
      slot.truncated=true;slot.alternatives_total=613;
    }
    return value;
  };
  assert.deepEqual((await f.planner.plan('minecraft:stick',4,{})).next_goal,
    {skill:'craft',item_id:'minecraft:stick',count:4});
  await f.planner.bootstrap({});
  assert.deepEqual(f.calls.filter(row=>row.name==='game_check_action').at(-1).args.goal,
    {skill:'craft',item_id:'minecraft:crafting_table',count:1});
  assert.equal(f.calls.filter(row=>row.name==='game_start_task').length,1);
});
test('autonomous bootstrap waits for terminal task and a later native observation; completed supplies are not restocked in a loop',async()=>{
  const f=fixture([{item_id:'minecraft:oak_log',count:2}]);
  await f.planner.bootstrap({});assert.equal(f.calls.filter(row=>row.name==='game_start_task').length,1);
  await f.planner.bootstrap({});assert.equal(f.calls.filter(row=>row.name==='game_start_task').length,1);
  f.tasks.get('task-0').state='succeeded';f.tasks.get('task-0').effect_status='verified';
  await f.planner.bootstrap({});assert.equal(f.calls.filter(row=>row.name==='game_start_task').length,1);
  f.observe({inventory:[{item_id:'minecraft:oak_planks',count:8}]});await f.planner.bootstrap({});
  assert.equal(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal.item_id,'minecraft:crafting_table');
  f.tasks.get('task-1').state='succeeded';f.tasks.get('task-1').effect_status='verified';await f.planner.bootstrap({});
  f.observe({inventory:[{item_id:'minecraft:oak_planks',count:4},{item_id:'minecraft:crafting_table',count:1}]});await f.planner.bootstrap({});
  assert.equal(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal.item_id,'minecraft:stick');
  f.tasks.get('task-2').state='succeeded';f.tasks.get('task-2').effect_status='verified';await f.planner.bootstrap({});
  f.observe({inventory:['wooden_pickaxe','stone_pickaxe','stone_axe','furnace','crafting_table','bread'].map(item=>({item_id:'minecraft:'+item,count:3}))});
  assert.equal(await f.planner.bootstrap({}),false);assert.equal(await f.planner.bootstrap({}),false);
  assert.equal(f.calls.filter(row=>row.name==='game_start_task').length,3);
});

test('held workstation is placed at an observed site before tool dependencies; no early plank stockpile',async()=>{
  const f=fixture([{item_id:'minecraft:crafting_table',count:1},{item_id:'minecraft:oak_planks',count:2},{item_id:'minecraft:stick',count:4}]);
  f.manager.capabilities={features:{targeted_block_placement:true}};
  const position={dimension:'minecraft:overworld',x:1,y:64,z:0};
  f.observe({details:{construction:{placement_sites:[{position}],workstations:[]}}});
  await f.planner.bootstrap({});
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,
    {skill:'use_item',item_id:'minecraft:crafting_table',purpose:'activate',target:position});
  assert.equal(f.calls.some(row=>row.name==='game_get_recipe'),false);
});

test('observed reachable workstation satisfies only dependencies without inventing held inventory',async()=>{
  const f=fixture([{item_id:'minecraft:oak_planks',count:3},{item_id:'minecraft:stick',count:2}]);
  f.observe({details:{construction:{workstations:[{block_id:'minecraft:crafting_table'}]}}});
  assert.deepEqual((await f.planner.plan('minecraft:wooden_pickaxe',1,{})).next_goal,
    {skill:'craft',item_id:'minecraft:wooden_pickaxe',count:1});
  assert.equal(f.manager.stateView().inventory.some(row=>row.item_id==='minecraft:crafting_table'),false);
  assert.notEqual((await f.planner.plan('minecraft:crafting_table',1,{})).state,'satisfied');
});

test('mining prepares a real portable table even when a placed table already satisfies the tool dependency',async()=>{
  const f=fixture([{item_id:'minecraft:wooden_pickaxe',count:1},{item_id:'minecraft:oak_planks',count:3},
    {item_id:'minecraft:stick',count:2}]);
  f.observe({details:{construction:{workstations:[{block_id:'minecraft:crafting_table'}]}}});
  await f.planner.bootstrap({});
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,
    {skill:'gather',item_id:'minecraft:oak_log',count:1});
  assert.equal(f.planner.lastPlan.stage,'prepare_portable_workstation');
  assert.equal(f.planner.lastPlan.for_item,'minecraft:stone_pickaxe');
  assert.equal(f.calls.some(row=>row.name==='game_start_task' && row.args.goal.item_id==='minecraft:cobblestone'),false);
  assert.equal(f.manager.stateView().inventory.some(row=>row.item_id==='minecraft:crafting_table'),false);
});

test('portable table is crafted from real planks and mining resumes only with carried stock',async()=>{
  for(const carried of [false,true]) {
    const inventory=[{item_id:'minecraft:wooden_pickaxe',count:1},{item_id:'minecraft:oak_planks',count:4},
      {item_id:'minecraft:stick',count:2},...(carried?[{item_id:'minecraft:crafting_table',count:1}]:[])];
    const f=fixture(inventory);f.observe({details:{construction:{workstations:[{block_id:'minecraft:crafting_table'}]}}});
    await f.planner.bootstrap({});
    assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,carried
      ? {skill:'gather',item_id:'minecraft:cobblestone',count:3}
      : {skill:'craft',item_id:'minecraft:crafting_table',count:1});
  }
});

test('denied portable-table preparation cannot fall through to unprepared mining',async()=>{
  const f=fixture([{item_id:'minecraft:wooden_pickaxe',count:1},{item_id:'minecraft:stick',count:2}]);
  f.observe({details:{construction:{workstations:[{block_id:'minecraft:crafting_table'}]}}});
  const invoke=f.manager.tools.invoke;
  f.manager.tools.invoke=async(name,args,...rest)=>{
    if(name==='game_check_action') {f.calls.push({name,args});return {state:'succeeded',result:{allowed:false,reason:'GAME_GATHER_RESOURCE_UNAVAILABLE'}};}
    return invoke(name,args,...rest);
  };
  await f.planner.bootstrap({});
  assert.equal(f.calls.some(row=>row.name==='game_start_task'),false);
  assert.equal(f.calls.some(row=>row.name==='game_check_action' && row.args.goal.item_id==='minecraft:cobblestone'),false);
});

test('a carried portable table stays in inventory while mining away from a workstation',async()=>{
  const f=fixture([{item_id:'minecraft:wooden_pickaxe',count:1},{item_id:'minecraft:crafting_table',count:1},
    {item_id:'minecraft:oak_planks',count:4},{item_id:'minecraft:stick',count:2}]);
  f.manager.capabilities={features:{targeted_block_placement:true}};
  f.observe({details:{construction:{placement_sites:[{position:{...f.state.player.position,x:1}}],workstations:[]}}});
  f.planner.current(f.manager.stateView());f.planner.lastTable={...f.state.player.position,x:6};
  await f.planner.bootstrap({});
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').map(row=>row.args.goal),
    [{skill:'gather',item_id:'minecraft:cobblestone',count:3}]);
  assert.equal(f.manager.stateView().inventory.find(row=>row.item_id==='minecraft:crafting_table').count,1);
});

test('portable placement follows a missing-workstation craft check and its receipt before stone tools',async()=>{
  const stock=[{item_id:'minecraft:wooden_pickaxe',count:1},{item_id:'minecraft:crafting_table',count:1},
    {item_id:'minecraft:cobblestone',count:3},{item_id:'minecraft:stick',count:2}];
  const f=fixture(stock),position={...f.state.player.position,x:1};
  f.manager.capabilities={features:{targeted_block_placement:true}};
  f.observe({details:{construction:{placement_sites:[{position}],workstations:[]}}});
  const invoke=f.manager.tools.invoke;
  f.manager.tools.invoke=async(name,args,...rest)=>{
    if(name==='game_check_action' && args.goal.skill==='craft' &&
        !f.manager.stateView().details.construction.workstations.length) {
      f.calls.push({name,args});return {state:'succeeded',result:{allowed:false,reason:'GAME_CRAFT_WORKSTATION_UNAVAILABLE'}};
    }
    return invoke(name,args,...rest);
  };
  await f.planner.bootstrap({});
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,
    {skill:'use_item',item_id:'minecraft:crafting_table',purpose:'activate',target:position});
  assert.equal(f.planner.lastPlan.for_item,'minecraft:stone_pickaxe');
  assert.equal(f.calls.some(row=>row.name==='game_start_task' && row.args.goal.skill==='craft'),false);
  Object.assign(f.tasks.get('task-0'),{state:'succeeded',effect_status:'verified'});
  f.observe({inventory:stock.filter(row=>row.item_id!=='minecraft:crafting_table'),
    details:{construction:{placement_sites:[],workstations:[{block_id:'minecraft:crafting_table',position}]}}});
  await f.planner.bootstrap({});assert.equal(f.calls.filter(row=>row.name==='game_start_task').length,1);
  f.observe({});await f.planner.bootstrap({});
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,
    {skill:'craft',item_id:'minecraft:stone_pickaxe',count:1});
});

test('multi-output targets request only a ready recipe batch and replan remaining material needs',async()=>{
  const f=fixture([{item_id:'minecraft:wheat',count:3}]);
  assert.deepEqual((await f.planner.plan('minecraft:bread',3,{})).next_goal,
    {skill:'craft',item_id:'minecraft:bread',count:1});
  f.observe({inventory:[{item_id:'minecraft:bread',count:1}]});
  assert.deepEqual((await f.planner.plan('minecraft:bread',3,{})).next_goal,
    {skill:'gather',item_id:'minecraft:wheat',count:3});
  f.observe({inventory:[{item_id:'minecraft:oak_log',count:1}]});
  assert.deepEqual((await f.planner.plan('minecraft:oak_planks',64,{})).next_goal,
    {skill:'craft',item_id:'minecraft:oak_planks',count:4});
});

test('missing resource explores only after a real native route admission and respects urgent survival',async()=>{
  const f=fixture();const invoke=f.manager.tools.invoke;
  f.observe({player:{health:20,food:20,position:{dimension:'minecraft:overworld',x:0,y:64,z:0}}});
  f.manager.tools.invoke=async(name,args,...rest)=>name==='game_check_action' && args.goal.skill==='gather'
    ? {state:'succeeded',result:{allowed:false,reason:'GAME_GATHER_RESOURCE_UNAVAILABLE'}} : invoke(name,args,...rest);
  await f.planner.bootstrap({});
  const goal=f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal;
  assert.equal(goal.skill,'navigate');assert.ok(f.calls.some(row=>row.name==='game_check_action' && row.args.goal===goal));
  const urgent=fixture();urgent.observe({player:{health:4,food:2,position:{dimension:'minecraft:overworld',x:0,y:64,z:0}}});
  assert.equal(await urgent.planner.explore({},'missing'),false);assert.equal(urgent.calls.length,0);
});

test('gather quantity changes cannot bypass a failed-source cooldown',async()=>{
  const f=fixture();const goal={skill:'gather',item_id:'minecraft:cobblestone',count:1};
  const signature=f.planner.signature(f.manager.stateView(),goal);
  f.planner.denied.set(signature,f.manager.clock());
  assert.equal(await f.planner.submit({...goal,count:4},{},{engine:'fixture'}),false);
  assert.equal(f.calls.length,0);
});

test('stone tool tags prefer a supported received source instead of an unsupported alphabetic alternative',async()=>{
  const f=fixture([{item_id:'minecraft:wooden_pickaxe',count:1},{item_id:'minecraft:stick',count:2}]);
  const invoke=f.manager.tools.invoke;
  f.manager.tools.invoke=async(name,...args)=>{
    const value=await invoke(name,...args);
    if(name==='game_get_recipe' && args[0].item_id==='minecraft:stone_pickaxe')
      for(const slot of value.result.recipes[0].slots)if(slot.alternatives.includes('minecraft:cobblestone'))
        slot.alternatives=['minecraft:blackstone','minecraft:cobbled_deepslate','minecraft:cobblestone'];
    return value;
  };
  assert.deepEqual((await f.planner.plan('minecraft:stone_pickaxe',1,{})).next_goal,
    {skill:'gather',item_id:'minecraft:cobblestone',count:3});
});

test('partially held dependency stock reduces only the missing gather increment',async()=>{
  const f=fixture([{item_id:'minecraft:wooden_pickaxe',count:1},{item_id:'minecraft:cobblestone',count:1},
    {item_id:'minecraft:stick',count:2}]);
  assert.deepEqual((await f.planner.plan('minecraft:stone_pickaxe',1,{})).next_goal,
    {skill:'gather',item_id:'minecraft:cobblestone',count:2});
  f.observe({inventory:[{item_id:'minecraft:wooden_pickaxe',count:1},{item_id:'minecraft:cobblestone',count:2},
    {item_id:'minecraft:stick',count:2}]});
  assert.equal((await f.planner.plan('minecraft:stone_pickaxe',1,{})).next_goal.count,1);
});

test('a root item deficit is not subtracted a second time',async()=>{
  const f=fixture([{item_id:'minecraft:wooden_pickaxe',count:1},{item_id:'minecraft:cobblestone',count:1}]);
  assert.deepEqual((await f.planner.plan('minecraft:cobblestone',4,{})).next_goal,
    {skill:'gather',item_id:'minecraft:cobblestone',count:3});
});

function stationHistory(f,items=[]) {
  const memory=new Map();
  f.manager.store={meta:(key,fallback)=>structuredClone(memory.get(key) ?? fallback),
    setMeta:(key,value)=>memory.set(key,structuredClone(value)),audit:()=>{}};
  f.manager.tasks.page=()=>({items,next_cursor:null});
  f.observe({world_id:'world-1',game_instance_id:'instance-1',observed_at:new Date().toISOString()});
  return memory;
}
const placedTable=(patch={})=>({task_id:'placed-table',world_id:'world-1',game_instance_id:'instance-1',
  state:'succeeded',effect_status:'verified',updated_at:new Date().toISOString(),
  goal:{skill:'use_item',item_id:'minecraft:crafting_table',purpose:'activate',
    target:{dimension:'minecraft:overworld',x:6,y:64,z:0}},...patch});

test('a verified placement in this world survives reconnect only as a checked route candidate',async()=>{
  const f=fixture();stationHistory(f,[placedTable()]);
  await f.planner.bootstrap({});
  const request=f.calls.filter(row=>row.name==='game_start_task').at(-1);
  assert.deepEqual(request.args.goal,{skill:'navigate',target:{dimension:'minecraft:overworld',x:6,y:65,z:0},radius:2});
  assert.ok(f.calls.some(row=>row.name==='game_check_action' && row.args.goal===request.args.goal));
  assert.equal(f.manager.stateView().inventory.length,0);
  assert.equal(f.events.at(-1)[1].historical_candidate,true);
});

test('fresh native table memory persists across planner instances without creating held stock',async()=>{
  const f=fixture();const memory=stationHistory(f);
  f.observe({details:{construction:{source:'runtime_client',sampled_at:new Date().toISOString(),
    workstations:[{block_id:'minecraft:crafting_table',position:{dimension:'minecraft:overworld',x:3,y:64,z:0}}]}}});
  await f.planner.bootstrap({});assert.equal(memory.get('mindcraft_workstations_v1').items.length,1);
  f.observe({world_session_id:'world-session-2',details:{}});f.calls.length=0;
  const resumed=new MindcraftNativePlanner(f.manager);await resumed.bootstrap({});
  assert.equal(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal.skill,'navigate');
  assert.equal(f.manager.stateView().inventory.length,0);
});

test('failed, stale, another-world or distant history cannot create a workstation route',async()=>{
  for(const patch of [{state:'failed'},{effect_status:'unknown'},{world_id:'world-other'},
    {game_instance_id:'instance-other'},{updated_at:new Date(Date.now()-8*86400000).toISOString()},
    {updated_at:'invalid'},{goal:{...placedTable().goal,target:{dimension:'minecraft:the_nether',x:6,y:64,z:0}}},
    {goal:{...placedTable().goal,target:{dimension:'minecraft:overworld',x:25,y:64,z:0}}}]) {
    const f=fixture();stationHistory(f,[placedTable(patch)]);await f.planner.bootstrap({});
    assert.equal(f.calls.some(row=>row.name==='game_start_task' && row.args.goal.skill==='navigate'),false);
  }
});

test('arriving at an unobserved historical table cannot satisfy crafting or loop a no-op return',async()=>{
  const f=fixture([{item_id:'minecraft:oak_planks',count:3},{item_id:'minecraft:stick',count:2}]);
  stationHistory(f,[placedTable()]);f.observe({player:{position:{dimension:'minecraft:overworld',x:6,y:64,z:0}}});
  await f.planner.bootstrap({});
  assert.equal(f.calls.some(row=>row.name==='game_start_task' && row.args.goal.skill==='navigate'),false);
  assert.notEqual((await f.planner.plan('minecraft:wooden_pickaxe',1,{})).next_goal.item_id,'minecraft:wooden_pickaxe');
});

test('a denied historical workstation route falls back without bypassing action checks',async()=>{
  const f=fixture();stationHistory(f,[placedTable()]);const invoke=f.manager.tools.invoke;
  f.manager.tools.invoke=async(name,args,...rest)=>{
    if(name==='game_check_action' && args.goal.skill==='navigate') {
      f.calls.push({name,args});return {state:'succeeded',result:{allowed:false,reason:'GAME_NAVIGATION_NO_ROUTE'}};
    }
    return invoke(name,args,...rest);
  };
  await f.planner.bootstrap({});
  assert.equal(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal.skill,'gather');
  assert.equal(f.calls.some(row=>row.name==='game_start_task' && row.args.goal.skill==='navigate'),false);
});
test('native observed reachable destinations are checked before blind exploratory offsets',async()=>{
  const f=fixture(),position=f.state.player.position,target={...position,x:6,y:63,z:2};
  f.observe({player:{position,health:20,food:20},details:{navigation:navigation(position,[target])}});
  assert.equal(await f.planner.explore({},'missing'),true);
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,{skill:'navigate',target,radius:0});
  assert.equal(f.calls.filter(row=>row.name==='game_check_action').length,1);
});

test('stale or another-position navigation observations cannot select an observed destination',async()=>{
  for(const stale of [true,false]) {
    const f=fixture(),position=f.state.player.position,target={...position,x:7,z:3};
    const sample=navigation(position,[target]);
    if(stale)sample.sampled_at=new Date(Date.now()-10000).toISOString();else sample.origin={...position,x:1};
    f.observe({player:{position,health:20,food:20},details:{navigation:sample}});
    await f.planner.explore({},'missing');
    assert.notDeepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal.target,target);
  }
});

test('an idle nearby threat selects checked retreat before starter crafting even at low health',async()=>{
  const f=fixture([{item_id:'minecraft:oak_planks',count:4}]),position=f.state.player.position;
  const farther={...position,x:-6},nearer={...position,x:3};
  f.observe({player:{position,health:8,food:20},details:{navigation:navigation(position,[nearer,farther]),
    nearby_hostiles:[{distance:1,position:{...position,x:1}}]}});
  assert.equal(await f.planner.bootstrap({}),true);
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,{skill:'navigate',target:farther,radius:1});
  assert.equal(f.calls.some(row=>row.name==='game_get_recipe'),false);
});

test('denied emergency routes never create a task or bypass native checks',async()=>{
  const f=fixture(),position=f.state.player.position;
  f.observe({player:{position,health:8,food:20},details:{navigation:navigation(position,[{...position,x:-6}]),
    nearby_hostiles:[{distance:1,position:{...position,x:1}}]}});
  f.manager.tools.invoke=async(name,args)=>{f.calls.push({name,args});return {state:'succeeded',result:{allowed:false,reason:'GAME_NAVIGATION_NO_ROUTE'}};};
  assert.equal(await f.planner.bootstrap({}),false);
  assert.equal(f.calls.some(row=>row.name==='game_start_task'),false);
  assert.equal(f.planner.lastPlan.state,'emergency_route_blocked');
});

test('retreat considers a farther creeper instead of escaping the nearest zombie into it',async()=>{
  const f=fixture(),position=f.state.player.position;
  const unsafe={...position,x:-6},safe={...position,z:6};
  f.observe({player:{position,health:8,food:20},details:{navigation:navigation(position,[unsafe,safe]),
    nearby_hostiles:[{distance:1,position:{...position,x:1}},{distance:9,position:{...position,x:-9}}]}});
  assert.equal(await f.planner.bootstrap({}),true);
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal.target,safe);
  assert.equal(f.calls.some(row=>row.name==='game_check_action' && row.args.goal.target===unsafe),false);
});

test('a hostile inside ten blocks preempts crafting before reaching melee distance',async()=>{
  const f=fixture([{item_id:'minecraft:oak_planks',count:4}]),position=f.state.player.position,safe={...position,x:-6};
  f.observe({player:{position,health:20,food:20},details:{navigation:navigation(position,[safe]),
    nearby_hostiles:[{distance:9,position:{...position,x:9}}]}});
  assert.equal(await f.planner.bootstrap({}),true);
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal.target,safe);
  assert.equal(f.calls.some(row=>row.name==='game_get_recipe'),false);
});

test('navigation observation contract keeps bounded native candidates and required action checks',()=>{
  const position={dimension:'minecraft:overworld',x:0,y:64,z:0},sample=navigation(position,[{...position,x:4}]);
  validate('NavigationObservation',sample);
  for(const bad of [{...sample,action_precondition_required:false},{...sample,frontiers:Array(9).fill(sample.frontiers[0])},
    {...sample,frontiers:[{position:{...position,x:1.5}}]},{...sample,search_budget:8192}])
    assert.throws(()=>validate('NavigationObservation',bad));
});

test('water escape checks the nearest fresh bank before food or tool dependencies',async()=>{
  const f=fixture(),position=f.manager.state.requireFresh().player.position;
  f.observe({player:{position,health:8,food:20},details:{hazards:{in_water:true},
    navigation:navigation(position,[{...position,x:4},{...position,x:-2}]),nearby_hostiles:[]}});
  assert.equal(await f.planner.bootstrap({}),true);
  const check=f.calls.find(row=>row.name==='game_check_action');
  assert.equal(check.args.goal.skill,'navigate');assert.equal(check.args.goal.target.x,-2);assert.equal(check.args.goal.radius,0);
  assert.equal(f.planner.lastPlan.reason,'water_escape');
});

test('water escape keeps a denied bank failed and does not submit a resource action',async()=>{
  const f=fixture(),position=f.manager.state.requireFresh().player.position;
  f.observe({player:{position,health:8,food:20},details:{hazards:{in_water:true},
    navigation:navigation(position,[{...position,x:2}]),nearby_hostiles:[]}});
  f.manager.tools.invoke=async(name,args)=>{f.calls.push({name,args});return {state:'succeeded',result:{allowed:false,reason:'GAME_NAVIGATION_NO_ROUTE'}};};
  assert.equal(await f.planner.bootstrap({}),false);
  assert.equal(f.calls.some(row=>row.name==='game_start_task'),false);
  assert.equal(f.planner.lastPlan.state,'emergency_route_blocked');
});

test('ordinary fire without a received hostile waits in the running world then resumes real dependencies',async()=>{
  const f=fixture([{item_id:'minecraft:oak_planks',count:4}]),position=f.state.player.position;
  f.observe({player:{position,health:15,food:20},details:{hazards:{on_fire:true,in_water:false},nearby_hostiles:[]}});
  assert.equal(mindcraftThreatened(f.manager.stateView()),true);
  assert.equal(await f.planner.bootstrap({}),true);
  assert.equal(f.calls.length,0,'no crafting, invented water, control change or task while waiting');
  assert.equal(f.planner.lastPlan.state,'waiting_for_fire_to_clear');
  assert.equal(f.planner.lastPlan.world_pause_requested,false);
  f.observe({details:{hazards:{on_fire:false,in_water:false},nearby_hostiles:[]}});
  assert.equal(mindcraftThreatened(f.manager.stateView()),false);
  assert.equal(await f.planner.bootstrap({}),true);
  assert.equal(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal.skill,'craft');
});

test('fire with a received hostile checks a dry retreat before production',async()=>{
  const f=fixture(),position=f.state.player.position,target={...position,x:-6};
  f.observe({player:{position,health:15,food:20},details:{hazards:{on_fire:true},navigation:navigation(position,[target]),
    nearby_hostiles:[{distance:1,position:{...position,x:1}}]}});
  assert.equal(await f.planner.bootstrap({}),true);
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,{skill:'navigate',target,radius:1});
  assert.equal(f.planner.lastPlan.reason,'fire_and_nearby_hostiles');
  assert.equal(f.calls.some(row=>row.name==='game_get_recipe'),false);
});

test('an interrupted work task keeps its real failure but can retry after a later fire-free observation',async()=>{
  const f=fixture([{item_id:'minecraft:oak_planks',count:4}]);
  assert.equal(await f.planner.bootstrap({}),true);
  const task=f.tasks.get('task-0');
  Object.assign(task,{state:'failed',effect_status:'unknown',reason:'GAME_DEFENSE_HAZARD_INTERRUPTED'});
  assert.equal(f.planner.settle(f.manager.stateView()),false);
  f.observe({});assert.equal(f.planner.settle(f.manager.stateView()),true);
  assert.equal(await f.planner.bootstrap({}),true);
  assert.equal(f.calls.filter(row=>row.name==='game_start_task').length,2);
  assert.equal(task.state,'failed');assert.equal(task.effect_status,'unknown');
});

test('a denied fire retreat stays failed and does not fall through into crafting or model work',async()=>{
  const f=fixture(),position=f.state.player.position,target={...position,x:-6};
  f.observe({player:{position,health:15,food:20},details:{hazards:{on_fire:true},navigation:navigation(position,[target]),
    nearby_hostiles:[{distance:1,position:{...position,x:1}}]}});
  f.manager.tools.invoke=async(name,args)=>{f.calls.push({name,args});return {state:'succeeded',result:{allowed:false,reason:'GAME_NAVIGATION_NO_ROUTE'}};};
  assert.equal(await f.planner.bootstrap({}),true);
  assert.equal(f.planner.lastPlan.state,'emergency_route_blocked');
  assert.equal(f.calls.length,1);assert.equal(f.calls[0].name,'game_check_action');
});

test('fire in water retains the existing checked bank escape rather than waiting or treating fire as permission',async()=>{
  const f=fixture(),position=f.state.player.position,target={...position,x:2};
  f.observe({player:{position,health:15,food:20},details:{hazards:{on_fire:true,in_water:true},navigation:navigation(position,[target]),nearby_hostiles:[]}});
  assert.equal(await f.planner.bootstrap({}),true);
  assert.equal(f.planner.lastPlan.reason,'water_escape');
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,{skill:'navigate',target,radius:0});
});

test('known transient native stops revoke the old lease and require a fresh delayed handshake',async t=>{
  for(const reason of ['LEASE_EXPIRED','GAME_CLIENT_TICK_STALLED'])await t.test(reason,async t=>{
    const f=await gameFixture({fakeClock:true});t.after(()=>f.close());
    const game=await f.connect({features:{autonomous_resume:true}});await game.auto();
    f.bridge.health=()=>({persona_injection_ready:true});
    Object.assign(f.manager.config.planner,{enabled:true,autostart:true,engine:'mindcraft_native'});
    game.snapshot({seq:game.observation.seq+1,details:runtimeDetails({singleplayer:true,local_server_published:false})});
    await until(()=>f.manager.state.value.seq===game.observation.seq);
    f.manager.planner.startSession(f.manager.stateView());
    game.send('control_result',{operation_id:'local-transient',request_id:'local-transient',
      world_session_id:game.observation.world_session_id,mode:'PAUSED',control_epoch:20,inputs_released:true,
      automation_ready:false,lease_id:null,heartbeat_seq:null,error:null,stop_reason:reason});
    await until(()=>f.manager.state.value.control_epoch===20);
    assert.equal(f.manager.lease,null);assert.equal(f.manager.planner.suspendedScope,null);
    game.snapshot({seq:game.observation.seq+1,mode:'PAUSED',control_epoch:20,automation_ready:false,lease_remaining_ms:null});
    await until(()=>f.manager.state.value.seq===game.observation.seq);
    f.manager.planner.startSession(f.manager.stateView());
    assert.equal(game.messages.filter(v=>v.type==='control_request').length,1);
    f.advance(3000);f.manager.planner.startSession(f.manager.stateView());
    assert.equal(game.messages.filter(v=>v.type==='control_request').length,1,'stale observation cannot restart');
    game.snapshot({seq:game.observation.seq+1,observed_at:new Date(f.manager.wall()).toISOString()});
    await until(()=>f.manager.state.value.seq===game.observation.seq);
    f.manager.planner.startSession(f.manager.stateView());
    const next=await game.next('control_request',v=>v.payload.reason==='AGENT_MINDCRAFT_SESSION_AUTOSTART');
    assert.equal(next.payload.expected_control_epoch,20);
  });
});

test('transient recovery cannot clear explicit stops or authorize published and old clients',async t=>{
  for(const row of [{priorStop:true},{published:true},{capability:false},{singleplayer:false},{reason:'GUI_BLOCKED'}])await t.test(JSON.stringify(row),async t=>{
    const f=await gameFixture({fakeClock:true});t.after(()=>f.close());
    const game=await f.connect({features:{autonomous_resume:row.capability!==false}});await game.auto();
    f.bridge.health=()=>({persona_injection_ready:true});
    Object.assign(f.manager.config.planner,{enabled:true,autostart:true,engine:'mindcraft_native'});
    game.snapshot({seq:game.observation.seq+1,details:runtimeDetails({singleplayer:row.singleplayer!==false,local_server_published:!!row.published})});
    await until(()=>f.manager.state.value.seq===game.observation.seq);
    if(row.priorStop)f.manager.planner.suspendAutostart();
    game.send('control_result',{operation_id:'local-transient',request_id:'local-transient',world_session_id:game.observation.world_session_id,
      mode:'PAUSED',control_epoch:20,inputs_released:true,automation_ready:false,lease_id:null,heartbeat_seq:null,error:null,
      stop_reason:row.reason || 'GAME_CLIENT_TICK_STALLED'});
    await until(()=>f.manager.state.value.control_epoch===20);
    game.snapshot({seq:game.observation.seq+1,mode:'PAUSED',control_epoch:20,automation_ready:false,lease_remaining_ms:null});
    await until(()=>f.manager.state.value.seq===game.observation.seq);f.manager.planner.startSession(f.manager.stateView());
    f.advance(4000);game.snapshot({seq:game.observation.seq+1,observed_at:new Date(f.manager.wall()).toISOString()});
    await until(()=>f.manager.state.value.seq===game.observation.seq);f.manager.planner.startSession(f.manager.stateView());
    assert.equal(game.messages.filter(v=>v.type==='control_request').length,1);assert.equal(f.manager.lease,null);
  });
});

test('a single reachable escape step uses an exact stance instead of an already-satisfied radius',async()=>{
  const f=fixture(),position=f.state.player.position,target={...position,x:-1};
  f.observe({player:{position,health:4,food:20},details:{navigation:navigation(position,[target]),
    nearby_hostiles:[{distance:1,position:{...position,x:1}}]}});
  assert.equal(await f.planner.bootstrap({}),true);
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,{skill:'navigate',target,radius:0});
});

test('dependency exploration preserves the observed descent first and requires its exact elevation',async()=>{
  const f=fixture(),position={...f.state.player.position,y:79},ground={...position,x:1,y:75};
  f.observe({player:{position,health:20,food:20},details:{navigation:navigation(position,[ground,{...position,x:7}])}});
  assert.equal(await f.planner.explore({},'GAME_NAVIGATION_NO_ROUTE'),true);
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,
    {skill:'navigate',target:ground,radius:0});
});

test('an adjacent exploration frontier requires movement instead of consuming a visit at the current stance',async()=>{
  const f=fixture(),position=f.state.player.position,target={...position,x:position.x+1};
  f.observe({player:{position,health:20,food:20},details:{navigation:navigation(position,[target])}});
  assert.equal(await f.planner.explore({},'GAME_NAVIGATION_NO_ROUTE'),true);
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,{skill:'navigate',target,radius:0});
});

test('autostart can request capability-gated normal respawn and explicit stop suppresses all life states',async t=>{
  const f=await gameFixture({fakeClock:true});t.after(()=>f.close());
  const game=await f.connect({features:{autonomous_respawn:true}});
  f.bridge.health=()=>({persona_injection_ready:true});
  Object.assign(f.manager.config.planner,{enabled:true,autostart:true,engine:'mindcraft_native'});
  game.snapshot({seq:game.observation.seq+1,screen:'death',player:{...game.observation.player,health:0}});
  await until(()=>f.manager.state.value.screen==='death');
  f.manager.planner.startSession(f.manager.stateView());
  f.advance(3000);
  game.snapshot({seq:game.observation.seq+1,observed_at:new Date(f.manager.wall()).toISOString()});
  await until(()=>f.manager.state.value.seq===game.observation.seq);
  f.manager.planner.startSession(f.manager.stateView());
  const request=await game.next('control_request');
  assert.equal(request.payload.reason,'AGENT_MINDCRAFT_NORMAL_RESPAWN');
  assert.equal(request.payload.target_mode,'AUTO');
  f.manager.planner.suspendAutostart();
  const attempts=f.manager.planner.respawnAttempts.length;
  game.snapshot({seq:game.observation.seq+1,screen:'gameplay',player:{...game.observation.player,health:20}});
  await until(()=>f.manager.state.value.screen==='gameplay');
  f.advance(4000);
  game.snapshot({seq:game.observation.seq+1,observed_at:new Date(f.manager.wall()).toISOString()});
  await until(()=>f.manager.state.value.seq===game.observation.seq);
  f.manager.planner.startSession(f.manager.stateView());
  assert.equal(f.manager.planner.respawnAttempts.length,attempts);
  assert.equal(game.messages.filter(row=>row.type==='control_request').length,1,'explicit stop survives a life-state change');
});

test('old clients cannot request AUTO on death without the explicit normal-respawn capability',async t=>{
  const f=await gameFixture({fakeClock:true});t.after(()=>f.close());const game=await f.connect();
  game.snapshot({seq:game.observation.seq+1,screen:'death',player:{...game.observation.player,health:0}});
  await until(()=>f.manager.state.value.screen==='death');
  assert.throws(()=>f.manager.control({request_id:'no-respawn-capability',target_mode:'AUTO',reason:'test capability fence',
    bridge_boot_id:game.identity.bridge_boot_id,world_session_id:game.observation.world_session_id,
    expected_control_epoch:game.observation.control_epoch}),{code:'GAME_PRECONDITION_FAILED'});
});

test('native death releases the active lease and the Agent requests a fresh normal respawn',async t=>{
  const f=await gameFixture({fakeClock:true});t.after(()=>f.close());
  const game=await f.connect({features:{autonomous_respawn:true}});await game.auto();
  f.bridge.health=()=>({persona_injection_ready:true});
  Object.assign(f.manager.config.planner,{enabled:true,autostart:true,engine:'mindcraft_native'});
  f.manager.planner.startSession(f.manager.stateView());
  // The native stop can arrive before the first death snapshot.
  game.send('control_result',{operation_id:'local-death',request_id:'local-death',
    world_session_id:game.observation.world_session_id,mode:'PAUSED',control_epoch:20,
    inputs_released:true,automation_ready:false,lease_id:null,heartbeat_seq:null,error:null,stop_reason:'PLAYER_DEATH'});
  await until(()=>f.manager.state.value.control_epoch===20);
  assert.equal(f.manager.lease,null);assert.equal(f.manager.planner.suspendedScope,null);
  game.snapshot({seq:game.observation.seq+1,mode:'PAUSED',control_epoch:20,automation_ready:false,
    lease_remaining_ms:null,screen:'death',player:{...game.observation.player,health:0}});
  await until(()=>f.manager.state.value.screen==='death');
  f.manager.planner.startSession(f.manager.stateView());f.advance(3000);
  game.snapshot({seq:game.observation.seq+1,observed_at:new Date(f.manager.wall()).toISOString()});
  await until(()=>f.manager.state.value.seq===game.observation.seq);
  f.manager.planner.startSession(f.manager.stateView());
  const request=await game.next('control_request',row=>row.payload.reason==='AGENT_MINDCRAFT_NORMAL_RESPAWN');
  assert.equal(request.payload.expected_control_epoch,20);
  assert.equal(f.manager.planner.respawnAttempts.length,1);
});

test('physical stops, old clients and earlier explicit stops cannot be cleared by a death notification',async t=>{
  for(const row of [
    {reason:'PHYSICAL_INPUT',capability:true},
    {reason:'GUI_BLOCKED',capability:true},
    {reason:'PLAYER_DEATH',capability:false},
    {reason:'PLAYER_DEATH',capability:true,priorStop:true}
  ]) await t.test(JSON.stringify(row),async t=>{
    const f=await gameFixture({fakeClock:true});t.after(()=>f.close());
    const game=await f.connect({features:{autonomous_respawn:row.capability}});await game.auto();
    f.bridge.health=()=>({persona_injection_ready:true});
    Object.assign(f.manager.config.planner,{enabled:true,autostart:true,engine:'mindcraft_native'});
    if(row.priorStop) f.manager.planner.suspendAutostart();
    game.send('control_result',{operation_id:'local-stop',request_id:'local-stop',
      world_session_id:game.observation.world_session_id,mode:'PAUSED',control_epoch:20,
      inputs_released:true,automation_ready:false,lease_id:null,heartbeat_seq:null,error:null,stop_reason:row.reason});
    await until(()=>f.manager.state.value.control_epoch===20);
    game.snapshot({seq:game.observation.seq+1,mode:'PAUSED',control_epoch:20,automation_ready:false,
      lease_remaining_ms:null,screen:'death',player:{...game.observation.player,health:0}});
    await until(()=>f.manager.state.value.screen==='death');
    f.manager.planner.startSession(f.manager.stateView());f.advance(4000);
    game.snapshot({seq:game.observation.seq+1,observed_at:new Date(f.manager.wall()).toISOString()});
    await until(()=>f.manager.state.value.seq===game.observation.seq);
    f.manager.planner.startSession(f.manager.stateView());
    assert.equal(f.manager.planner.respawnAttempts.length,0);
    assert.equal(game.messages.filter(value=>value.type==='control_request').length,1);
    assert.equal(f.manager.lease,null);
  });
});

test('a changed control lease rebuilds item milestones from post-death inventory instead of historical tools',async()=>{
  const f=fixture([{item_id:'minecraft:wooden_pickaxe',count:1}]);
  f.planner.current(f.state);f.planner.completed.add('crafting_table');f.planner.completed.add('wooden_pickaxe');
  f.planner.lastTable={...f.state.player.position,x:6};
  f.observe({control_epoch:10,inventory:[]});f.planner.current(f.manager.stateView());
  assert.equal(f.planner.completed.size,0);assert.equal(f.planner.lastTable,null);
  await f.planner.bootstrap({});
  assert.deepEqual(f.calls.filter(row=>row.name==='game_start_task').at(-1).args.goal,{skill:'gather',item_id:'minecraft:oak_log',count:1});
});

test('session autostart is bounded and an explicit pause suppresses it',async t=>{
  const f=await gameFixture({fakeClock:true});t.after(()=>f.close());const game=await f.connect({features:{autonomous_resume:true}});
  f.bridge.health=()=>({persona_injection_ready:true});
  Object.assign(f.manager.config.planner,{enabled:true,autostart:true});
  const planner=f.manager.planner;planner.startSession(f.manager.stateView());f.advance(3000);
  game.snapshot({seq:game.observation.seq+1,observed_at:new Date(f.manager.wall()).toISOString()});
  await until(()=>f.manager.state.value.seq===game.observation.seq);
  planner.startSession(f.manager.stateView());
  assert.equal(planner.autostart.attempts,1);assert.ok(planner.autostart.operation);
  planner.startSession(f.manager.stateView());assert.equal(planner.autostart.attempts,1);
  planner.suspendAutostart();assert.equal(planner.autostart.suspended,true);
});
