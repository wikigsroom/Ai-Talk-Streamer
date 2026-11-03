import { mindcraftItemGoal } from './item-goal-native.mjs';
import { canonical } from '../../dsh-bridge/channel.mjs';
import { ensure } from '../errors.mjs';

const LEAVES = new Set(['oak_log','spruce_log','birch_log','jungle_log','acacia_log','dark_oak_log','mangrove_log','cherry_log',
  'dirt','cobblestone','coal','wheat','carrot','potato','beetroot','apple','sweet_berries']);
const STARTER = [['crafting_table',1],['wooden_pickaxe',1],['stone_pickaxe',1],['stone_axe',1],['furnace',1],['bread',3]];
const count = (state, item) => state.inventory?.find(row => row.item_id === 'minecraft:' + item)?.count || 0;
const short = id => id?.startsWith('minecraft:') ? id.slice(10) : null;
const station = (state, item) => state.details?.construction?.workstations?.some(row => row.block_id === 'minecraft:' + item) === true;
const unsupported = () => { throw new Error('GAME_MINDCRAFT_DIRECT_EXECUTION_DISABLED'); };

// Include threats beyond the immediate attack radius when choosing an exit;
// escaping a pursuer must not lead straight into another received hostile.
export const mindcraftThreats = state => (state.details?.nearby_hostiles || []).filter(row =>
  Number.isFinite(row.distance) && row.distance >= 0 && row.distance <= 16 && row.health !== 0
  && row.position?.dimension === state.player?.position?.dimension
  && ['x','y','z'].every(axis => Number.isFinite(row.position[axis])));
export const mindcraftThreatened = state => state.details?.hazards?.in_water === true
  || state.details?.hazards?.on_fire === true
  || mindcraftThreats(state).some(row => row.distance <= 10);

/** Mindcraft's actual ItemWrapper dependency solver, with received native recipes.
 * This port produces fixed native goals. It never opens a second player, runs
 * generated code, changes control mode, or substitutes predictions for receipts. */
export class MindcraftNativePlanner {
  constructor(manager) { this.manager = manager; this.reset(null); }
  reset(scope) { this.scope = scope; this.completed = new Set(); this.pending = null; this.denied = new Map(); this.lastPlan = null;
    this.explored = new Set(); this.exploreIndex = 0; this.exploreOrigin = null; this.lastTable = null;
    this.stationHistoryChecked = false; this.unconfirmedTables = new Set(); this.terrainPlacements = 0;
    this.terrainAnchors = new Map(); this.terrainGatherings = 0; this.exitStance = null; }
  report(value) {
    this.manager.publish('mindcraft',value);
    this.manager.store?.audit('mindcraft_native',value);
  }
  current(state) {
    const scope = canonical([state.bridge_boot_id, state.world_session_id, state.connection_generation, state.control_epoch]);
    if (scope !== this.scope) this.reset(scope);
  }
  signature(state, goal) { const p=state.player?.position;
    // A few metres of unsuccessful walking must not erase the same failure.
    const region=p&&{dimension:p.dimension,x:Math.floor(p.x/16),y:Math.floor(p.y/8),z:Math.floor(p.z/16)};
    return canonical([state.world_session_id, state.control_epoch, region, state.inventory,
    goal.skill==='gather' ? {...goal,count:1} : goal]); }
  tableCandidate(state, position) {
    const p=state.player?.position;
    return p && position?.dimension===p.dimension && ['x','y','z'].every(axis=>Number.isInteger(position[axis]))
      && Math.hypot(position.x-p.x,position.z-p.z)<=24 && Math.abs(position.y-p.y)<=12
      && !this.unconfirmedTables.has(canonical(position));
  }
  rememberTable(state, position, seenAt, source) {
    if(!this.tableCandidate(state,position))return;
    this.lastTable=structuredClone(position);
    if(!state.world_id || !state.game_instance_id || !this.manager.store?.setMeta)return;
    const old=this.manager.store.meta('mindcraft_workstations_v1',{schema_version:1,items:[]});
    const items=old?.schema_version===1 && Array.isArray(old.items)?old.items.slice(0,16).filter(row=>row && typeof row==='object'):[];
    const previous=items.find(row=>row.world_id===state.world_id && row.game_instance_id===state.game_instance_id);
    if(previous && canonical(previous.position)===canonical(position) && Date.parse(seenAt)-Date.parse(previous.seen_at)<60000)return;
    this.manager.store.setMeta('mindcraft_workstations_v1',{schema_version:1,items:[{
      world_id:state.world_id,game_instance_id:state.game_instance_id,position:structuredClone(position),
      world_session_id:state.world_session_id,seen_at:seenAt,source,
    },...items.filter(row=>row.world_id!==state.world_id || row.game_instance_id!==state.game_instance_id)].slice(0,16)});
  }
  restoreTable(state) {
    if(this.lastTable || this.stationHistoryChecked)return;
    this.stationHistoryChecked=true;
    if(!state.world_id || !state.game_instance_id)return;
    const now=this.manager.wall?.() ?? Date.now();
    const usable=row=>row?.world_id===state.world_id && row.game_instance_id===state.game_instance_id
      && Number.isFinite(Date.parse(row.seen_at)) && now-Date.parse(row.seen_at)>=-1000
      && now-Date.parse(row.seen_at)<=7*86400000 && this.tableCandidate(state,row.position);
    const memory=this.manager.store?.meta?.('mindcraft_workstations_v1',{schema_version:1,items:[]});
    if(memory?.schema_version===1 && Array.isArray(memory.items)) {
      const known=memory.items.slice(0,16).find(usable);
      if(known){this.lastTable=structuredClone(known.position);return;}
    }
    // Bootstrap older installations only from a verified placement receipt.
    // Historical coordinates are route candidates, never a present workstation.
    if(!this.manager.tasks.page)return;
    let cursor;
    for(let page=0;page<2;page++) {
      const history=this.manager.tasks.page({worldId:state.world_id,limit:100,...(cursor?{cursor}:{})});
      for(const task of history.items) {
        const goal=task.goal;
        const row={world_id:task.world_id,game_instance_id:task.game_instance_id,position:goal?.target,seen_at:task.updated_at};
        if(task.state==='succeeded' && task.effect_status==='verified' && goal?.skill==='use_item'
            && goal.item_id==='minecraft:crafting_table' && goal.purpose==='activate' && usable(row)) {
          this.rememberTable(state,row.position,row.seen_at,{kind:'verified_placement',task_id:task.task_id});return;
        }
      }
      if(!history.next_cursor)break;cursor=history.next_cursor;
    }
  }
  async plan(itemId, total, context) {
    const m = this.manager, initial = m.state.requireFresh(); this.current(initial);
    ensure(/^minecraft:[a-z0-9_]+$/.test(itemId) && Number.isInteger(total) && total >= 1 && total <= 64,
      'GAME_MINDCRAFT_GOAL_INVALID', 400);
    const name = short(itemId);
    if (count(initial,name) >= total) return { engine:'mindcraft_item_goal_native', item_id:itemId, target_total:total,
      state:'satisfied', based_on_seq:initial.seq, next_goal:null };
    const recipes = new Map(), visited = new Set();
    const load = async (item, depth = 0) => {
      if (visited.has(item) || depth > 5 || visited.size >= 18) return;
      visited.add(item);
      if (LEAVES.has(item)) {
        recipes.set(item,[]);
        if (['cobblestone','coal'].includes(item)) await load('wooden_pickaxe',depth+1);
        return;
      }
      const operation = await m.tools.invoke('game_get_recipe', { item_id:'minecraft:' + item, count:1 }, context);
      ensure(operation.state === 'succeeded', 'GAME_MINDCRAFT_RECIPE_UNAVAILABLE');
      const choices = [];
      const received = operation.result?.recipes || [];
      const exact = received.filter(recipe => recipe.recipe_id === 'minecraft:' + item);
      for (const recipe of (exact.length ? exact : received.filter(recipe => recipe.recipe_id.startsWith('minecraft:'))).slice(0,4)) {
        // A bounded tag projection can omit choices, but each returned member
        // is known. Use only those explicit members; native checks still decide
        // stock allocation, workstation access and actual craft feasibility.
        if (recipe.recipe_type !== 'minecraft:crafting' || !recipe.ingredients_known) continue;
        const ingredients = {};
        for (const slot of recipe.slots.filter(slot => !slot.empty)) {
          const options = slot.alternatives.map(short).filter(Boolean).sort((a,b) =>
            (count(initial,b)>0) - (count(initial,a)>0) || (b==='oak_log'||b==='oak_planks')-(a==='oak_log'||a==='oak_planks') ||
            LEAVES.has(b)-LEAVES.has(a) || a.localeCompare(b));
          if (!options.length) { ingredients.invalid = true; break; }
          ingredients[options[0]] = (ingredients[options[0]] || 0) + 1;
        }
        if (ingredients.invalid || !Object.keys(ingredients).length) continue;
        choices.push([ingredients, recipe.output_per_batch]);
      }
      recipes.set(item,choices);
      for (const [ingredients] of choices) for (const child of Object.keys(ingredients)) await load(child,depth+1);
      if (choices.some(([ingredients]) => Object.values(ingredients).reduce((a,b) => a+b,0)>4)) await load('crafting_table',depth+1);
    };
    await load(name);
    const now = m.state.requireFresh();
    ensure(now.world_session_id === initial.world_session_id && now.bridge_boot_id === initial.bridge_boot_id &&
      now.control_epoch === initial.control_epoch && !context.signal?.aborted, 'GAME_PLAN_CANCELLED');
    const inventory = Object.fromEntries(now.inventory.filter(row => short(row.item_id)).map(row => [short(row.item_id),row.count]));
    const { ItemGoal, ItemWrapper } = mindcraftItemGoal({
      skills:{ collectBlock:unsupported, craftRecipe:unsupported, smeltItem:unsupported, attackNearest:unsupported, moveAway:unsupported },
      world:{ getInventoryCounts:() => inventory },
      mc:{ getItemCraftingRecipes:item => recipes.get(item) || [], getItemBlockSources:item => LEAVES.has(item) ? [item] : [],
        getBlockTool:item => ['cobblestone','coal'].includes(item) && !['wooden_pickaxe','stone_pickaxe','iron_pickaxe','diamond_pickaxe','netherite_pickaxe'].some(tool => inventory[tool]>0)
          ? 'wooden_pickaxe' : null, getItemSmeltingIngredient:() => null, getItemAnimalSource:() => null },
      // A visible, reachable table satisfies the solver's workstation dependency;
      // it is never inserted into held inventory or counted as a root item result.
      itemSatisfied:(_bot,item,quantity=1) => (inventory[item] || 0) >= quantity || item==='crafting_table' && quantity===1 && station(now,item),
    });
    const solver = new ItemGoal({bot:{}});
    solver.goal = solver.nodes[name] = new ItemWrapper(solver,null,name);
    const next = solver.goal.getNext(total - (inventory[name] || 0));
    let goal = null;
    if (next) {
      const skill = next.node.type === 'craft' ? 'craft' : next.node.type === 'block' ? 'gather' : null;
      if (skill) {
        // Upstream's dependency readiness covers one recipe batch. The native
        // count is additional output units, so requesting the entire root
        // deficit here could demand materials the solver has not acquired.
        // Produce at most one received batch, then replan from real stock.
        const batch = skill === 'craft' ? Math.min(...(recipes.get(next.node.name) || []).map(row => row[1])) : 4;
        // Dependency quantities are total requirements; a root request above
        // already carries its remaining deficit. Do not gather that stock twice.
        const deficit=next.node.name===name?next.quantity:next.quantity-(inventory[next.node.name] || 0);
        if(deficit>0)goal = { skill, item_id:'minecraft:' + next.node.name, count:Math.min(4,batch,deficit) };
      }
    }
    return this.lastPlan = { engine:'mindcraft_item_goal_native', item_id:itemId, target_total:total,
      world_session_id:now.world_session_id, observed_at:now.observed_at,
      state:goal ? 'planned' : 'unsupported_dependency', based_on_seq:now.seq,
      recipe_items:visited.size, next_goal:goal, execution_verified:false };
  }
  settle(state) {
    if (!this.pending) return true;
    const task = this.manager.tasks.get(this.pending.task_id);
    if (!['succeeded','failed','cancelled','expired','rejected','interrupted'].includes(task.state) || state.active_task_id) return false;
    if (this.pending.terminal_seq === undefined) { this.pending.terminal_seq = state.seq; return false; }
    if (state.seq <= this.pending.terminal_seq) return false;
    this.report({ state:'observed_result', task_id:task.task_id, task_state:task.state,
      effect_status:task.effect_status, inventory:state.inventory, based_on_seq:state.seq });
    if (task.state !== 'succeeded' || task.effect_status !== 'verified') {
      if(!['GAME_DEFENSE_HAZARD_INTERRUPTED','GAME_DEFENSE_RETREAT_COMPLETE'].includes(task.reason))
        this.denied.set(this.signature(state,this.pending.goal),this.manager.clock());
    }
    else if(this.pending.goal.skill==='use_item' && this.pending.goal.item_id==='minecraft:dirt' && this.pending.goal.target)
      this.exitStance={...this.pending.goal.target,y:this.pending.goal.target.y+1};
    if(this.pending.returningTable && !station(state,'crafting_table')) {
      // Reaching a historical coordinate is not finding a usable workstation.
      // One completed attempt without a received table must not pull every
      // later resource/craft step back to the same unconfirmed location.
      const key=canonical(this.pending.returningTable);
      this.unconfirmedTables.add(key);
      if(this.lastTable && canonical(this.lastTable)===key)this.lastTable=null;
      this.report({state:'historical_workstation_unconfirmed',task_id:task.task_id,
        task_state:task.state,based_on_seq:state.seq,prepare_portable_workstation:true});
    }
    this.pending = null; return true;
  }
  async bootstrap(context) {
    const m = this.manager, state = m.state.requireFresh(); this.current(state);
    if (!this.settle(state)) return true;
    if (mindcraftThreatened(state)) return this.retreat(context,state);
    const table=state.details?.construction?.workstations?.find(row => row.block_id==='minecraft:crafting_table');
    const construction=state.details?.construction,age=(m.wall?.() ?? Date.now())-Date.parse(construction?.sampled_at);
    if(table?.position && construction.source==='runtime_client' && Number.isFinite(age) && age>=-1000 && age<=4000)
      this.rememberTable(state,table.position,construction.sampled_at,{kind:'native_observation',seq:state.seq});
    this.restoreTable(state);
    if (state.player?.food<=16) for (const item of ['bread','cooked_beef','cooked_porkchop','cooked_chicken','baked_potato','carrot','apple']) {
      if (count(state,item)>0 && await this.submit({skill:'use_item',item_id:'minecraft:'+item,purpose:'eat'},context,
        {engine:'mindcraft_item_goal_native',stage:'restore_food'})) return true;
    }
    if(this.exitStance) {
      const target=this.exitStance;this.exitStance=null;
      if(canonical(target)!==canonical(state.player.position) && await this.submit({skill:'navigate',target,radius:0},context,
          {engine:'mindcraft_item_goal_native',stage:'climb_verified_support'}))return true;
    }
    // Reconstruct milestones from real held tools and visible stations after a
    // reconnect. Consuming materials is not a reason to restock early milestones.
    if (count(state,'crafting_table') || station(state,'crafting_table') || count(state,'wooden_pickaxe') || count(state,'stone_pickaxe')) this.completed.add('crafting_table');
    if (count(state,'stone_pickaxe')) this.completed.add('wooden_pickaxe');
    if (!station(state,'crafting_table') && count(state,'crafting_table')>0 && m.capabilities?.features?.targeted_block_placement) {
      for (const site of state.details?.construction?.placement_sites || []) {
        const goal={skill:'use_item',item_id:'minecraft:crafting_table',purpose:'activate',target:site.position};
        if (await this.submit(goal,context,{engine:'mindcraft_item_goal_native',stage:'place_workstation',item_id:goal.item_id})) return true;
      }
      return this.explore(context,'workstation_site_unavailable');
    }
    if(!station(state,'crafting_table') && this.lastTable) {
      const target={...this.lastTable,y:this.lastTable.y+1},p=state.player.position;
      if(Math.hypot(target.x-p.x,target.y-p.y,target.z-p.z)>2) {
        if(await this.submit({skill:'navigate',target,radius:2},context,
          {engine:'mindcraft_item_goal_native',stage:'return_to_known_workstation',historical_candidate:true}))return true;
        if(this.lastPlan?.reason==='GAME_NAVIGATION_NO_ROUTE' && await this.buildExitStep(context,state,target))return true;
      } else {
        this.unconfirmedTables.add(canonical(this.lastTable));this.lastTable=null;
      }
    }
    for (const [item,total] of STARTER) {
      if (count(state,item) >= total) this.completed.add(item);
      if (this.completed.has(item)) continue;
      const plan = await this.plan('minecraft:' + item,total,context), goal = plan.next_goal;
      if (!goal) return false;
      // Mining can lead below the placed surface table. Prepare a real carried
      // table while wood remains reachable, then place it near the later craft.
      if(goal.skill==='gather' && ['minecraft:cobblestone','minecraft:coal'].includes(goal.item_id)
          && count(state,'crafting_table')<1) {
        const portable=await this.plan('minecraft:crafting_table',1,context);
        if(portable.next_goal && await this.submit(portable.next_goal,context,
            {...portable,stage:'prepare_portable_workstation',for_item:'minecraft:'+item}))return true;
        return this.explore(context,this.lastPlan?.reason || 'portable_workstation_not_ready');
      }
      if (await this.submit(goal,context,plan)) return true;
      if (this.lastPlan?.reason==='GAME_CRAFT_WORKSTATION_UNAVAILABLE' && this.lastTable &&
          this.lastTable.dimension===state.player.position.dimension &&
          Math.hypot(this.lastTable.x-state.player.position.x,this.lastTable.z-state.player.position.z)<=24) {
        const target={...this.lastTable,y:this.lastTable.y+1};
        if (await this.submit({skill:'navigate',target,radius:2},context,
          {engine:'mindcraft_item_goal_native',stage:'return_to_observed_workstation'})) return true;
      }
      return this.explore(context,this.lastPlan?.reason || 'resource_or_route_unavailable');
    }
    return false;
  }
  async buildExitStep(context,state,target) {
    const m=this.manager,p=state.player?.position,c=state.details?.construction;
    const age=(m.wall?.() ?? Date.now())-Date.parse(c?.sampled_at),h=state.details?.hazards;
    const anchor=canonical(p);
    if(!m.capabilities?.features?.targeted_terrain_placement || this.terrainPlacements>=8 || (this.terrainAnchors.get(anchor)||0)>=3
        || !p || target?.dimension!==p.dimension || target.y-p.y<1 || target.y-p.y>8
        || Math.hypot(target.x-p.x,target.z-p.z)>24 || !Number.isFinite(state.player.health) || state.player.health<12
        || !Number.isFinite(state.player.food) || state.player.food<6 || h?.on_ground!==true
        || h.in_water || h.in_lava || h.on_fire || state.details?.nearby_hostiles?.some(row=>row.distance<=6)
        || c?.source!=='runtime_client' || !Number.isFinite(age) || age< -1000 || age>4000)return false;
    const sites=(c.placement_sites || []).slice(0,8).map(row=>row.position).filter(at=>at?.dimension===p.dimension
      && ['x','y','z'].every(axis=>Number.isInteger(at[axis])) && [p.y,p.y-1].includes(at.y) && Math.abs(at.x-p.x)+Math.abs(at.z-p.z)===1)
      .sort((a,b)=>b.y-a.y || Math.hypot(a.x-target.x,a.z-target.z)-Math.hypot(b.x-target.x,b.z-target.z));
    if(!sites.length)return false;
    if(count(state,'dirt')<1) {
      if(this.terrainGatherings>=2)return false;
      if(await this.submit({skill:'gather',item_id:'minecraft:dirt',count:2},context,
          {engine:'mindcraft_item_goal_native',stage:'gather_exit_support',maximum_per_control_scope:2})) {
        this.terrainGatherings++;return true;
      }
      return false;
    }
    for(const at of sites) {
      if(await this.submit({skill:'use_item',item_id:'minecraft:dirt',purpose:'activate',target:at},context,
          {engine:'mindcraft_item_goal_native',stage:'build_exit_support',route_target:target,
            placement_number:this.terrainPlacements+1,maximum_per_control_scope:8,maximum_per_stance:3})) {
        this.terrainPlacements++;this.terrainAnchors.set(anchor,(this.terrainAnchors.get(anchor)||0)+1);return true;
      }
    }
    return false;
  }
  async submit(goal,context,plan) {
    const m=this.manager,state=m.state.requireFresh(),signature=this.signature(state,goal);
    const denied=this.denied.get(signature);
    if (denied!==undefined && m.clock()-denied<60000) return false;
    const check=await m.tools.invoke('game_check_action',{goal},context);
    if (check.state!=='succeeded' || check.result?.allowed!==true) {
      this.denied.set(signature,m.clock());
      while (this.denied.size>64) this.denied.delete(this.denied.keys().next().value);
      this.lastPlan={...plan,state:'route_blocked',reason:check.result?.reason || check.error};this.report(this.lastPlan);return false;
    }
    const task=await m.tools.invoke('game_start_task',{goal},context);
    this.pending={task_id:task.task_id,goal,emergencyRetreat:plan.stage==='emergency_retreat',
      returningTable:goal.skill==='navigate' && ['return_to_known_workstation','return_to_observed_workstation'].includes(plan.stage)
        && this.lastTable ? structuredClone(this.lastTable) : null};
    this.lastPlan={...plan,state:'task_submitted',task_id:task.task_id,next_goal:goal};this.report(this.lastPlan);return true;
  }
  async explore(context,reason) {
    const state=this.manager.state.requireFresh(),p=state.player?.position,h=state.details?.hazards;
    // Coordinates below are candidate route queries, never observed safe cells.
    // Only the real native route check can admit a move. Stop bounded exploration
    // when survival is urgent, or this connection's 16 destinations are exhausted.
    if (!p || state.player.health<12 || state.player.food<6 || h?.in_lava || h?.on_fire || h?.in_water ||
      state.details?.nearby_hostiles?.some(row => row.distance<=6) || this.explored.size>=16) return false;
    this.exploreOrigin ||= p;
    let attempted=0;
    for(const target of this.frontiers(state)) {
      const key=canonical(target);
      if(this.explored.has(key) || Math.hypot(target.x-this.exploreOrigin.x,target.z-this.exploreOrigin.z)>24)continue;
      if(attempted++>=4)break;
      if(await this.submit({skill:'navigate',target,radius:0},context,
        {engine:'mindcraft_item_goal_native',stage:'explore_observed_frontier',reason})) {
        this.explored.add(key);return true;
      }
    }
    const offsets=[[4,0,0],[0,0,4],[-4,0,0],[0,0,-4],[4,-2,0],[0,-2,4],[-4,-2,0],[0,-2,-4],
      [4,-4,0],[0,-4,4],[-4,-4,0],[0,-4,-4]];
    for (let trial=attempted;trial<4;trial++) {
      const [dx,dy,dz]=offsets[this.exploreIndex++ % offsets.length];
      const target={dimension:p.dimension,x:p.x+dx,y:p.y+dy,z:p.z+dz},key=canonical(target);
      if (this.explored.has(key) || Math.hypot(target.x-this.exploreOrigin.x,target.z-this.exploreOrigin.z)>24) continue;
      const goal={skill:'navigate',target,radius:1};
      if (await this.submit(goal,context,{engine:'mindcraft_item_goal_native',stage:'explore_for_dependency',reason})) {
        this.explored.add(key);return true;
      }
    }
    return false;
  }
  frontiers(state) {
    const value=state.details?.navigation,p=state.player?.position;
    const age=(this.manager.wall?.() ?? Date.now())-Date.parse(value?.sampled_at);
    if(!p || !value || canonical(value.origin)!==canonical(p) || !Number.isFinite(age) || age< -1000 || age>4000)return [];
    return (value.frontiers || []).slice(0,8).map(row=>row.position).filter(target=>target?.dimension===p.dimension
      && ['x','y','z'].every(axis=>Number.isInteger(target[axis])) && Math.abs(target.y-p.y)<=4
      && Math.hypot(target.x-p.x,target.z-p.z)<=12);
  }
  async retreat(context,state) {
    const swimming=state.details?.hazards?.in_water === true;
    const burning=state.details?.hazards?.on_fire === true;
    const threats=mindcraftThreats(state);
    // A dry player can burn after contact has ended. Keep the world running so
    // vanilla fire/health can progress; do not craft, invent water or freeze it.
    if(burning && !swimming && !threats.length) {
      this.lastPlan={engine:'mindcraft_item_goal_native',state:'waiting_for_fire_to_clear',based_on_seq:state.seq,
        reason:'ordinary_fire',world_pause_requested:false};
      this.report(this.lastPlan);return true;
    }
    const distance=target=>Math.min(...threats.map(row=>Math.hypot(target.x-row.position.x,target.y-row.position.y,target.z-row.position.z)));
    const current=Math.min(...threats.map(row=>row.distance));
    const avoidsOtherThreats=target=>threats.every(row=>
      Math.hypot(target.x-row.position.x,target.y-row.position.y,target.z-row.position.z)>=Math.min(4,row.distance));
    const targets=this.frontiers(state).filter(target=>swimming || avoidsOtherThreats(target) && distance(target)>current+.25)
      .sort((a,b)=>swimming ? Math.hypot(a.x-state.player.position.x,a.z-state.player.position.z)-Math.hypot(b.x-state.player.position.x,b.z-state.player.position.z) : distance(b)-distance(a));
    for(const target of targets.slice(0,4))
      if(await this.submit({skill:'navigate',target,radius:swimming || Math.hypot(target.x-state.player.position.x,target.z-state.player.position.z)<=2 ? 0 : 1},context,
        {engine:'mindcraft_item_goal_native',stage:'emergency_retreat',reason:swimming ? 'water_escape' : burning ? 'fire_and_nearby_hostiles' : 'nearby_hostiles'}))return true;
    this.lastPlan={engine:'mindcraft_item_goal_native',state:'emergency_route_blocked',based_on_seq:state.seq};
    this.report(this.lastPlan);return burning;
  }
}
