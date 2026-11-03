import test from 'node:test';
import assert from 'node:assert/strict';
import { validate } from '../backend/game/protocol.mjs';
import { planningState, planningStateRead } from '../backend/game/model-state.mjs';

const position = { dimension: 'minecraft:overworld', x: 1, y: 70, z: 2 };
const sources = () => ({ source: 'runtime_client', sampled_at: '2026-11-02T00:00:00Z', radius: 6, vertical_radius: 3,
  items: [{ kind: 'mature_crop', item_id: 'minecraft:carrot', block_id: 'minecraft:carrots', distance: 2,
    line_of_sight: true, position }], truncated: false, action_precondition_required: true,
  unknown_fields: ['unloaded_chunks', 'occluded_sources', 'outside_scan_volume', 'future_drops', 'safe_reachability', 'unlisted_food_sources'] });
const details = () => ({ source: 'runtime_client', selected_hotbar: 0, inventory_slots: [],
  cursor: { slot: -1, item_id: 'minecraft:air', count: 0, damage: null, max_damage: null },
  gui: { kind: 'gameplay', title: null, container_id: null, slots: [], truncated: false },
  hazards: { on_fire: false, in_water: false, in_lava: false, fall_distance: 0, on_ground: true },
  environment: { biome: 'minecraft:plains', day_time: 1, raining: false, thundering: false },
  received_rules: { difficulty: 'normal', game_mode: 'survival', world_border_size: 1000 },
  nearby_hostiles: [], hostiles_truncated: false, unknown_fields: [] });

test('old observations remain valid and bounded food observations keep their own authority limits', () => {
  const old = details(); validate('RuntimeDetails', old);
  const current = { ...old, nearby_food: sources() }; validate('RuntimeDetails', current);
  current.nearby_food.items = [{ ...current.nearby_food.items[0], kind: 'loose_item', block_id: null, item_id: 'minecraft:bread' }];
  validate('RuntimeDetails', current);
});

for (const [name, change] of Object.entries({
  'oversized list': f => f.items = Array.from({ length: 9 }, () => f.items[0]),
  'unbounded radius': f => f.radius = 100,
  'missing height bound': f => delete f.vertical_radius,
  'false line of sight': f => f.items[0].line_of_sight = false,
  'dangerous food': f => f.items[0].item_id = 'minecraft:poisonous_potato',
  'modded crop': f => f.items[0].block_id = 'mod:carrots',
  'imagined inventory count': f => f.items[0].count = 64,
  'unconfirmed action permission': f => f.action_precondition_required = false,
  'loose crop block': f => f.items[0].kind = 'loose_item',
})) test('food contract rejects ' + name, () => {
  const current = details(); current.nearby_food = sources(); change(current.nearby_food);
  assert.throws(() => validate('RuntimeDetails', current));
});

test('planning receives food sources without converting them into inventory or action permission', () => {
  const source = { freshness: 'fresh', mode: 'PAUSED', inventory: [], details: { ...details(), nearby_food: sources() } };
  const original = structuredClone(source), projected = planningState(source);
  assert.deepEqual(projected.details.nearby_food, source.details.nearby_food);
  assert.deepEqual(projected.inventory, []);
  assert.equal(projected.mode, 'PAUSED');
  assert.equal(projected.automation_ready, undefined);
  assert.deepEqual(source, original);
  const changed = structuredClone(source); changed.details.nearby_food.items = [];
  assert.equal(planningStateRead(projected, changed).model_projection.kind, 'bounded_planning_summary');
  const missing = structuredClone(source); delete missing.details.nearby_food;
  assert.equal(planningState(missing).details.nearby_food, undefined);
});

test('expanded food search binds sixteen blocks and six vertical blocks to an explicit scan origin',()=>{
  const food=sources();Object.assign(food,{radius:16,vertical_radius:6,scan_origin:position});
  Object.assign(food.items[0],{distance:14,position:{...position,x:position.x+14}});
  validate('RuntimeDetails',{...details(),nearby_food:food});
  for(const change of [f=>delete f.scan_origin,f=>f.vertical_radius=3,f=>f.items[0].distance=16.1]){
    const bad=structuredClone(food);change(bad);assert.throws(()=>validate('RuntimeDetails',{...details(),nearby_food:bad}));
  }
  const old=sources();old.items[0].distance=7;
  assert.throws(()=>validate('RuntimeDetails',{...details(),nearby_food:old}),'legacy six-block contract stays bounded');
});

test('hay is a visible bread material or loose drop and cannot masquerade as a mature crop or edible carrot',()=>{
  const food=sources();Object.assign(food.items[0],{kind:'food_material',item_id:'minecraft:hay_block',block_id:'minecraft:hay_block'});
  validate('RuntimeDetails',{...details(),nearby_food:food});
  for(const change of [f=>f.items[0].kind='mature_crop',f=>f.items[0].item_id='minecraft:carrot',f=>f.items[0].block_id=null]){
    const bad=structuredClone(food);change(bad);assert.throws(()=>validate('RuntimeDetails',{...details(),nearby_food:bad}));
  }
  Object.assign(food.items[0],{kind:'loose_item',block_id:null});
  validate('RuntimeDetails',{...details(),nearby_food:food});
});

test('livestock observations bind one adult entity kind to its raw material without inventing edible stock',()=>{
  for(const [entity,raw] of [['sheep','mutton'],['cow','beef'],['pig','porkchop']]) {
    const food=sources();Object.assign(food.items[0],{kind:'livestock',item_id:'minecraft:'+raw,block_id:null,
      entity_type:'minecraft:'+entity,entity_uuid:'12345678-1234-1234-1234-123456789abc'});
    validate('RuntimeDetails',{...details(),nearby_food:food});
    for(const change of [f=>delete f.items[0].entity_uuid,f=>f.items[0].entity_uuid='not-an-entity',
      f=>f.items[0].entity_type='minecraft:wolf',f=>f.items[0].item_id='minecraft:bread',
      f=>f.items[0].block_id='minecraft:hay_block',f=>f.items[0].count=3]) {
      const bad=structuredClone(food);change(bad);assert.throws(()=>validate('RuntimeDetails',{...details(),nearby_food:bad}));
    }
    Object.assign(food.items[0],{kind:'loose_item'});delete food.items[0].entity_uuid;delete food.items[0].entity_type;
    validate('RuntimeDetails',{...details(),nearby_food:food});
    food.items[0].kind='mature_crop';food.items[0].block_id='minecraft:carrots';
    assert.throws(()=>validate('RuntimeDetails',{...details(),nearby_food:food}));
  }
  const ordinary=sources();ordinary.items[0].entity_uuid='12345678-1234-1234-1234-123456789abc';
  assert.throws(()=>validate('RuntimeDetails',{...details(),nearby_food:ordinary}));
});
