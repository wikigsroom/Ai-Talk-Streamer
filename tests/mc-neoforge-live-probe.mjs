/** Engineering host for the real native player and production GameManager.
 * The DSH/persona context is explicitly inert; this is not full streamer acceptance.
 * Run only on the user's remote3080. --execute-items explicitly exercises real owned inputs.
 */
import assert from 'node:assert/strict';
import { hostname, platform } from 'node:os';
import { createServer } from 'node:http';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { GameManager } from '../backend/game/manager.mjs';
import { DEFAULT_CONFIG } from '../backend/game/config.mjs';
import { physicalTakeoverConfirmed } from './mc-neoforge-proof.mjs';

assert.equal(platform(), 'win32'); assert.equal(hostname().toLowerCase(), 'desktop-2qqpn1h');
const output = resolve(process.argv[2]); mkdirSync(output, { recursive: true });
const executeTravel = process.argv.includes('--execute-travel');
const executeCraft = process.argv.includes('--execute-craft');
const executeSmelt = process.argv.includes('--execute-smelt');
const executeTools = process.argv.includes('--execute-tools');
const executeExit = process.argv.includes('--execute-exit');
assert.ok([executeCraft,executeTravel,executeSmelt,executeTools,executeExit].filter(Boolean).length<=1, 'SELECT_ONE_ENGINEERING_ACTION_PROBE');
const executeItems = process.argv.includes('--execute-items') || executeTravel || executeCraft || executeSmelt || executeTools || executeExit;
const report = { ok: false, classification: 'ACTUAL_NEOFORGE_AND_PRODUCTION_GAME_MANAGER_WITH_INERT_DSH_CONTEXT',
  host: hostname(), automatic_input_authorized: false, models_loaded: false, public_broadcast_started: false,
  formal_acceptance_passed: 0, probe_run_id: randomUUID(), operations: [] };
const persist = (name, value) => writeFileSync(join(output, name), JSON.stringify(value, null, 2) + '\n');
const config = structuredClone(DEFAULT_CONFIG); config.enabled = true; config.vision.enabled = true;
if (executeItems) config.control.enabled_skills = ['use_item'];
if (executeTravel) config.control.enabled_skills = ['use_item', 'navigate', 'gather', 'return_base'];
if (executeCraft) config.control.enabled_skills = ['use_item', 'craft', 'gather'];
if (executeSmelt) config.control.enabled_skills = ['use_item','craft','gather','navigate','return_base'];
if (executeTools) config.control.enabled_skills = ['use_item','craft','gather','navigate','return_base'];
if (executeExit) config.control.enabled_skills = ['use_item','craft','navigate','return_base'];
const context = { policy: { deployment: { state_relative_path: 'state/engineering-inert' } },
  state: { characterRoom: ['female-a', 'engineering-inert-not-platform'] },
  platforms: { config: { value: { platforms: { bilibili: { room_id: '' } } } } },
  health: () => ({ persona_injection_ready: false }),
  room: { store: { message: () => null }, blocked: () => true,
    panic: () => ({ audio: { muted: true }, public_broadcast_started: false }) } };
const manager = new GameManager(join(output, 'manager-ledger'), context, { config }); context.game = manager;
const sockets = new Set(), server = createServer((req, res) => {
  void manager.handle(req, res, new URL(req.url, 'http://localhost'), (value, status = 200) => {
    if (!res.headersSent) { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(value)); }
  });
});
server.on('connection', socket => { sockets.add(socket); socket.once('close', () => sockets.delete(socket)); });
server.on('upgrade', (req, socket, head) => manager.upgrade(req, socket, head));
const until = async (fn, timeout = 10000) => {
  const deadline = performance.now() + timeout;
  while (performance.now() < deadline) { const value = fn(); if (value) return value; await new Promise(r => setTimeout(r, 50)); }
  throw Error('Native integration deadline exceeded');
};
let base;
const api = async (path, body) => {
  const response = await fetch(base + '/api/dsh/game' + path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return { status: response.status, value: await response.json() };
};
async function operation(kind, params) {
  const state = manager.state.view();
  const response = await api('/queries', { request_id: 'native-' + kind + '-' + report.operations.length,
    bridge_boot_id: state.bridge_boot_id, world_session_id: state.world_session_id, kind, params });
  assert.equal(response.status, 202, JSON.stringify(response));
  await until(() => manager.operation(response.value.operation_id).state !== 'pending');
  const completed = manager.operation(response.value.operation_id); report.operations.push(completed);
  return completed;
}
async function control(target_mode) {
  const state = manager.state.view();
  const response = await api('/control', { request_id: 'native-control-' + target_mode + '-' + report.operations.length + '-' + state.control_epoch,
    target_mode, reason: 'actual_native_bridge_engineering_probe', bridge_boot_id: state.bridge_boot_id,
    world_session_id: state.world_session_id, expected_control_epoch: state.control_epoch });
  if (response.status !== 202) return response;
  await until(() => manager.operation(response.value.operation_id).state !== 'pending');
  return manager.operation(response.value.operation_id);
}
async function task(id, goal, duration = 15000) {
  const state = manager.state.view();
  const response = await api('/tasks', { request_id: id + '-' + report.probe_run_id, bridge_boot_id: state.bridge_boot_id,
    world_session_id: state.world_session_id, expected_control_epoch: state.control_epoch, based_on_seq: state.seq,
    accept_within_ms: 1500, max_duration_ms: duration, goal });
  assert.equal(response.status, 202, JSON.stringify(response)); return response.value.task_id;
}
async function terminal(id, timeout = 20000) {
  await until(() => ['succeeded', 'failed', 'cancelled'].includes(manager.tasks.get(id)?.state), timeout);
  const completed=structuredClone(manager.tasks.get(id));
  // Native task results can reach the host before the snapshot sampled by their evidence.
  // Do not make the next inventory decision from an older projection.
  const seq=Math.max(0,...(completed.evidence??[]).filter(e=>e.world_session_id===completed.world_session_id).map(e=>e.seq));
  if(seq>0)await until(()=>manager.state.view().world_session_id===completed.world_session_id && manager.state.view().seq>=seq,5000);
  return completed;
}
async function auto() {
  await until(() => manager.state.value.screen === 'gameplay' && manager.state.value.inputs_released, 120000);
  const result = await control('AUTO'); assert.equal(result.state, 'succeeded', JSON.stringify(result));
  await until(() => manager.state.view().automation_ready);
  report.automatic_input_authorized = true; return result;
}
async function physicalGate(name, expectedMode, reason) {
  await new Promise(resolve => setTimeout(resolve, 400)); // Let the preceding physical key-up reach vanilla.
  await auto(); const before = manager.state.view();
  persist('physical-input-needed.json', { phase: name, expected_mode: expectedMode, before });
  const factsPath = resolve(import.meta.dirname, '../runtime/minecraft/mc-friends-s1-neoforge-21.1.248/work/logs/ai-talk-streamer-native.json');
  let facts;
  await until(() => {
    const state = manager.state.view();
    if (state.screen === 'death') throw Error('ACTUAL_PLAYER_DIED_DURING_PHYSICAL_CHECK');
    try { facts = JSON.parse(readFileSync(factsPath, 'utf8')); } catch { return false; }
    return physicalTakeoverConfirmed(before, state, facts, expectedMode, reason);
  }, 60000);
  const after = manager.state.view();
  persist('physical-input-confirmed-' + name + '.json', { before, after, client_control_proof: facts.control_proof }); return after;
}
const factsPath = resolve(import.meta.dirname,
  '../runtime/minecraft/mc-friends-s1-neoforge-21.1.248/work/logs/ai-talk-streamer-native.json');
const facts = () => JSON.parse(readFileSync(factsPath, 'utf8'));
async function walkingGoal(distance) {
  const origin = manager.state.view().player.position;
  for (const dy of [0, -1, 1, -2, 2, -3, 3, -4, 4])
  for (const [dx, dz] of [[distance, 0], [0, distance], [-distance, 0], [0, -distance]]) {
    const goal = { skill: 'navigate', target: { ...origin, x: origin.x + dx, y: origin.y + dy, z: origin.z + dz }, radius: .75 };
    const checked = await operation('check_action', { goal });
    report.walk_checks ??= []; report.walk_checks.push({ goal, checked });
    if (checked.state === 'succeeded' && checked.result.allowed) return goal;
  }
  throw Error('NO_ACTUAL_LOADED_WALK_ROUTE_FOR_PROBE');
}
async function travelProbe() {
  const home = manager.state.view();
  const registered = await api('/worlds/' + home.world_id + '/bases', {
    request_id: 'native-observed-home-' + report.probe_run_id,
    bridge_boot_id: home.bridge_boot_id, world_session_id: home.world_session_id,
    expected_world_revision: manager.worlds.get(home.world_id).revision,
    label: '实际工程测试起点', radius: 1 });
  assert.equal(registered.status, 201, JSON.stringify(registered)); report.observed_base = registered.value;
  const goal = await walkingGoal(5); report.navigation_goal = goal;
  await auto(); report.navigation_task = await terminal(await task('native-real-walk', goal, 90000), 95000);
  assert.equal(report.navigation_task.state, 'succeeded', JSON.stringify(report.navigation_task));
  assert.equal(report.navigation_task.effect_status, 'verified');
  report.navigation_state = manager.state.view();
  report.return_base_task = await terminal(await task('native-real-return', { skill: 'return_base', base_id: registered.value.base_id }, 90000), 95000);
  assert.equal(report.return_base_task.state, 'succeeded', JSON.stringify(report.return_base_task));
  assert.equal(report.return_base_task.effect_status, 'verified');
  let collect;
  for (const item_id of ['minecraft:birch_log', 'minecraft:oak_log', 'minecraft:spruce_log', 'minecraft:dirt', 'minecraft:cobblestone']) {
    const goal = { skill: 'gather', item_id, count: 1 }, check = await operation('check_action', { goal });
    if (check.state === 'succeeded' && check.result.allowed) { collect = goal; break; }
  }
  assert.ok(collect, 'NO_ACTUAL_COLLECTABLE_RESOURCE_FOR_PROBE'); report.gather_goal = collect;
  report.gather_task = await terminal(await task('native-real-collect', collect, 90000), 95000);
  assert.equal(report.gather_task.state, 'succeeded', JSON.stringify(report.gather_task));
  assert.equal(report.gather_task.effect_status, 'verified');
  await until(() => facts().control_proof.native_input.all_owned_inputs_clear, 4000);
  report.gather_client_proof = facts();
  assert.ok(report.gather_client_proof.control_proof.native_travel.server_inventory_packets > 0);
  report.pause_after_travel = await control('PAUSED'); assert.equal(report.pause_after_travel.state, 'succeeded');
  report.running_task_takeovers = [];
  for (let index = 0; index < 20; index++) {
    await new Promise(resolve => setTimeout(resolve, 400));
    const goal = await walkingGoal(32), startFacts = facts();
    await auto(); const id = await task('native-running-takeover-' + index, goal, 90000);
    await until(() => manager.tasks.get(id)?.state === 'running' && manager.state.value.active_task_id === id);
    await until(() => {
      const actual = facts(), proof = actual.control_proof;
      return proof.native_travel.task_id === id && proof.native_travel.active && proof.native_travel.ticks >= 2
        && proof.native_input.synthetic_motion_attached && !proof.native_input.all_owned_inputs_clear
        && Math.hypot(actual.x - startFacts.x, actual.z - startFacts.z) > .05;
    }, 6000);
    assert.equal(manager.tasks.get(id).state, 'running');
    const before = manager.state.view(), [inputKey, name, expectedMode, reason] = [
      ['F10', 'F10', 'PAUSED', 'LOCAL_PANIC_KEY'],
      ['LSHIFT', 'KEYBOARD_SHIFT', 'MANUAL_COMMENTARY', 'PHYSICAL_KEYBOARD_INPUT'],
      ['MOUSE_MOVE', 'MOUSE_MOVE', 'MANUAL_COMMENTARY', 'PHYSICAL_MOUSE_INPUT']
    ][index % 3];
    const phase = 'RUNNING_TASK_' + String(index + 1).padStart(2, '0');
    persist('physical-input-needed.json', { phase, input_key: inputKey, expected_mode: expectedMode, before, task_id: id });
    let afterFacts;
    await until(() => {
      if (manager.state.value.screen === 'death') throw Error('ACTUAL_PLAYER_DIED_DURING_RUNNING_TASK_CHECK');
      afterFacts = facts();
      return physicalTakeoverConfirmed(before, manager.state.view(), afterFacts, expectedMode, reason)
        && afterFacts.control_proof.native_input.all_owned_inputs_clear;
    }, 60000);
    const stopped = await terminal(id);
    assert.equal(stopped.state, 'cancelled', JSON.stringify(stopped)); assert.equal(stopped.reason, reason);
    assert.equal(afterFacts.control_proof.native_travel.active, false);
    const moved = Math.hypot(afterFacts.x - startFacts.x, afterFacts.z - startFacts.z);
    assert.ok(moved > .05, 'RUNNING_TASK_HAS_NO_ACTUAL_POSITION_CHANGE');
    const proof = { before, after: manager.state.view(), client_control_proof: afterFacts.control_proof,
      task_id: id, cancelled_task: stopped, actual_position_change: moved,
      classification: 'ACTUAL_RUNNING_TASK_OS_INPUT_TAKEOVER_NOT_REAL_HARDWARE_OR_LATENCY_ACCEPTANCE' };
    persist('physical-input-confirmed-' + phase + '.json', proof);
    report.running_task_takeovers.push(proof);
    if (index < 3) {
      persist('physical-input-confirmed-' + name + '.json', proof);
      report[{ F10: 'f10_pause', KEYBOARD_SHIFT: 'keyboard_takeover', MOUSE_MOVE: 'mouse_takeover' }[name]] = proof.after;
    }
    persist('running-task-takeovers.json', report.running_task_takeovers);
  }
  persist('physical-input-needed.json', { phase: 'COMPLETE' });
}
async function craftProbe() {
  report.crafting_tasks = []; report.placement_checks = []; report.crafting_supply_tasks = [];
  const kinds = ['birch', 'oak', 'spruce'];
  const total = kind => manager.state.view().inventory.filter(item => item.item_id === 'minecraft:' + kind + '_log')
    .reduce((sum, item) => sum + item.count, 0);
  let log = kinds.find(kind => total(kind) >= 4) ?? kinds.find(kind => total(kind) > 0);
  if (!log) {
    for (const kind of kinds) {
      const check = await operation('check_action', { goal: { skill: 'gather', item_id: 'minecraft:' + kind + '_log', count: 1 } });
      if (check.state === 'succeeded' && check.result.allowed) { log = kind; break; }
    }
  }
  assert.ok(log, 'ACTUAL_COLLECTABLE_LOG_REQUIRED_FOR_CRAFT_CHAIN');
  const plank = 'minecraft:' + log + '_planks';
  await auto();
  for (let attempt = 0; total(log) < 4 && attempt < 4; attempt++) {
    const goal = { skill: 'gather', item_id: 'minecraft:' + log + '_log', count: 1 };
    const checked = await operation('check_action', { goal });
    assert.equal(checked.state, 'succeeded'); assert.equal(checked.result.allowed, true, JSON.stringify(checked));
    const completed = await terminal(await task('native-craft-supply-' + attempt, goal, 90000), 95000);
    report.crafting_supply_tasks.push({ goal, checked, task: completed });
    assert.equal(completed.state, 'succeeded', JSON.stringify(completed)); assert.equal(completed.effect_status, 'verified');
  }
  assert.ok(total(log) >= 4, 'ACTUAL_LOG_STOCK_REQUIRED_FOR_CRAFT_CHAIN');
  async function craft(item_id, count) {
    const goal = { skill: 'craft', item_id, count }, before = manager.state.view();
    const checked = await operation('check_action', { goal });
    assert.equal(checked.state, 'succeeded'); assert.equal(checked.result.allowed, true, JSON.stringify(checked));
    const completed = await terminal(await task('native-real-craft-' + report.crafting_tasks.length, goal, 90000), 95000);
    const row = { goal, before, checked, task: completed }; report.crafting_tasks.push(row);
    assert.equal(completed.state, 'succeeded', JSON.stringify(completed)); assert.equal(completed.effect_status, 'verified');
    assert.ok(completed.evidence.some(e => e.kind === 'craft_result'));
    await until(() => {
      const proof = facts().control_proof.native_craft;
      return proof.task_id === completed.task_id && proof.clean_end && !proof.active && proof.cursor_empty;
    }, 4000);
    row.after = manager.state.view(); row.client_proof = facts();
    const proof = row.client_proof.control_proof.native_craft;
    assert.equal(proof.confirmed_batches, proof.planned_batches); assert.ok(proof.server_full_packets > 0);
    assert.ok(proof.clicks > 0); assert.ok(proof.produced >= count);
    return completed;
  }
  await craft(plank, 12);
  await craft('minecraft:stick', 1);
  await craft('minecraft:crafting_table', 1);
  await craft(plank, 1); // Existing output is a baseline; count remains an increment and rounds to one full batch.
  report.workstation_precheck = await operation('check_action', { goal: { skill: 'craft', item_id: 'minecraft:wooden_pickaxe', count: 1 } });
  report.pause_for_placement = await control('PAUSED'); assert.equal(report.pause_for_placement.state, 'succeeded');
  const place = { skill: 'use_item', item_id: 'minecraft:crafting_table', purpose: 'activate' };
  let placementAllowed = false;
  for (let index = 0; index <= 20; index++) {
    const checked = await operation('check_action', { goal: place }); report.placement_checks.push(checked);
    if (checked.state === 'succeeded' && checked.result.allowed) { placementAllowed = true; break; }
    if (index === 20) break;
    const number = String(index + 1).padStart(2, '0'), phase = 'AIM_PLACEMENT_' + number;
    const state = manager.state.view(); assert.equal(state.mode, 'PAUSED'); assert.equal(state.active_task_id, null);
    persist('physical-input-needed.json', { phase, probe_run_id: report.probe_run_id, state });
    await until(() => {
      try {
        const proof = JSON.parse(readFileSync(join(output, 'placement-aimed-' + number + '.json'), 'utf8'));
        return proof.phase === phase && proof.probe_run_id === report.probe_run_id
          && proof.world_session_id === state.world_session_id && proof.control_epoch === state.control_epoch
          && proof.foreground_pid_verified && proof.creation_ticks_verified && proof.relative_y === 36;
      } catch { return false; }
    }, 20000);
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  assert.ok(placementAllowed, 'NO_ACTUAL_CROSSHAIR_PLACEMENT_FOR_CRAFT_TABLE');
  await auto(); report.table_placement_task = await terminal(await task('native-real-place-crafting-table', place));
  assert.equal(report.table_placement_task.state, 'succeeded', JSON.stringify(report.table_placement_task));
  assert.equal(report.table_placement_task.effect_status, 'verified');
  await craft('minecraft:wooden_pickaxe', 1);
  await craft('minecraft:wooden_axe', 1);
  report.pause_after_crafting = await control('PAUSED'); assert.equal(report.pause_after_crafting.state, 'succeeded');
  persist('physical-input-needed.json', { phase: 'COMPLETE' });
}
async function smeltProbe() {
  report.smelting_tasks=[];report.smelting_supply_tasks=[];report.smelting_prechecks=[];report.placement_checks=[];
  const total=item=>manager.state.view().inventory.filter(v=>v.item_id===item).reduce((n,v)=>n+v.count,0);
  const home=manager.state.view();
  const registered=await api('/worlds/'+home.world_id+'/bases',{request_id:'native-smelt-home-'+report.probe_run_id,
    bridge_boot_id:home.bridge_boot_id,world_session_id:home.world_session_id,expected_world_revision:manager.worlds.get(home.world_id).revision,
    label:'实际熔炉工程测试起点',radius:1});
  assert.equal(registered.status,201,JSON.stringify(registered));report.smelting_base=registered.value;
  await auto();
  report.workstation_placement_tasks=[];report.placement_aim_steps=0;
  const placementMoves=[[0,-600],[0,-180],[300,0],[300,0],[300,0],[300,0],
    [0,360],[300,0],[300,0],[300,0],[300,0],[0,180],[300,0],[300,0],[300,0],[300,0],
    [0,-720],[300,0],[300,0],[300,0]];
  async function placeStation(item_id,label){
    const paused=await control('PAUSED');assert.equal(paused.state,'succeeded');
  const place={skill:'use_item',item_id,purpose:'activate'};let allowed=false;
  for(let index=0;index<=20;index++){
    const checked=await operation('check_action',{goal:place});report.placement_checks.push(checked);
    if(checked.result?.allowed){allowed=true;break;}if(index===20 || report.placement_aim_steps>=20)break;
    const move=placementMoves[report.placement_aim_steps];
    const number=String(++report.placement_aim_steps).padStart(2,'0'),phase='AIM_PLACEMENT_'+number,state=manager.state.view();
    assert.equal(state.mode,'PAUSED');assert.equal(state.active_task_id,null);
    persist('physical-input-needed.json',{phase,probe_run_id:report.probe_run_id,state});
    await until(()=>{try{const p=JSON.parse(readFileSync(join(output,'placement-aimed-'+number+'.json'),'utf8'));
      return p.phase===phase && p.probe_run_id===report.probe_run_id && p.world_session_id===state.world_session_id
        && p.control_epoch===state.control_epoch && p.foreground_pid_verified && p.creation_ticks_verified
        && p.relative_x===move[0] && p.relative_y===move[1];
    }catch{return false;}},20000);await new Promise(r=>setTimeout(r,300));
  }
  assert.ok(allowed,'ACTUAL_WORKSTATION_PLACEMENT_CROSSHAIR_NOT_AVAILABLE');await auto();
  const completed=await terminal(await task('native-real-place-'+label,place));
  assert.equal(completed.state,'succeeded',JSON.stringify(completed));
  assert.equal(completed.effect_status,'verified');
  report.workstation_placement_tasks.push(completed);return completed;
  }
  async function gather(item_id,count,label){
    if(!manager.state.view().automation_ready)await auto();
    const goal={skill:'gather',item_id,count},checked=await operation('check_action',{goal});
    if(!checked.result?.allowed){report.smelting_prechecks.push({goal,checked});return false;}
    const completed=await terminal(await task('native-smelt-supply-'+label+'-'+report.smelting_supply_tasks.length,goal,90000),95000);
    report.smelting_supply_tasks.push({goal,checked,task:completed,client_proof:facts()});
    return completed.state==='succeeded' && completed.effect_status==='verified';
  }
  async function craft(item_id,count,cooking=false){
    const goal={skill:'craft',item_id,count},before=manager.state.view(),checked=await operation('check_action',{goal});
    assert.equal(checked.result?.allowed,true,JSON.stringify(checked));
    const completed=await terminal(await task('native-smelt-craft-'+report.smelting_tasks.length,goal,180000),185000);
    const row={goal,before,checked,task:completed,cooking};report.smelting_tasks.push(row);
    assert.equal(completed.state,'succeeded',JSON.stringify(completed));assert.equal(completed.effect_status,'verified');
    await until(()=>{const p=facts().control_proof[cooking?'native_cooking':'native_craft'];return p.task_id===completed.task_id && p.clean_end && !p.active && p.cursor_empty;},5000);
    row.after=manager.state.view();row.client_proof=facts();
    const p=row.client_proof.control_proof[cooking?'native_cooking':'native_craft'];
    assert.ok(p.server_full_packets>0 && p.clicks>0 && p.produced>=count);
    assert.ok(total(item_id)>=before.inventory.filter(v=>v.item_id===item_id).reduce((n,v)=>n+v.count,0)+p.produced);
  }
  for(let attempt=0;total('minecraft:birch_log')<3 && attempt<4;attempt++)assert.ok(await gather('minecraft:birch_log',1,'logs'),'ACTUAL_LOG_SUPPLY_NOT_AVAILABLE');
  if(total('minecraft:birch_planks')<4)await craft('minecraft:birch_planks',4);
  report.smelting_without_workstation=await operation('check_action',{goal:{skill:'craft',item_id:'minecraft:charcoal',count:2}});
  if(total('minecraft:furnace')===0){
    for(let attempt=0;total('minecraft:cobblestone')<8 && attempt<9;attempt++){
      const obtained=await gather('minecraft:cobblestone',8-total('minecraft:cobblestone'),'stone');
      if(obtained)break;
      if(attempt===8)break;
      // A fresh ordinary task may expose the next loaded stone face. Each real mutation stays journalled.
      assert.ok(await gather('minecraft:dirt',1,'expose-stone'),'ACTUAL_STONE_OR_BOUNDED_SOIL_PATH_UNAVAILABLE');
    }
    assert.ok(total('minecraft:cobblestone')>=8,'ACTUAL_COBBLESTONE_REQUIRED_FOR_FURNACE');
  }
  report.smelting_return=await terminal(await task('native-smelt-return',{skill:'return_base',base_id:registered.value.base_id},90000),95000);
  assert.equal(report.smelting_return.state,'succeeded',JSON.stringify(report.smelting_return));
  if(total('minecraft:furnace')===0){
    const goal={skill:'craft',item_id:'minecraft:furnace',count:1},checked=await operation('check_action',{goal});
    report.furnace_table_precheck=checked;
    if(checked.result?.reason==='GAME_CRAFT_WORKSTATION_UNAVAILABLE'){
      if(total('minecraft:crafting_table')===0)await craft('minecraft:crafting_table',1);
      await placeStation('minecraft:crafting_table','smelt-table');
    }
    await craft('minecraft:furnace',1);
  }
  report.furnace_placement_task=await placeStation('minecraft:furnace','furnace');
  await craft('minecraft:charcoal',2,true);
  // A positive baseline is part of the second conversion receipt; count stays an increment.
  await craft('minecraft:charcoal',1,true);
  report.pause_after_smelting=await control('PAUSED');assert.equal(report.pause_after_smelting.state,'succeeded');
  persist('physical-input-needed.json',{phase:'COMPLETE'});
}
async function toolsProbe(){
  report.tool_crafting_tasks=[];report.tool_supply_tasks=[];report.tool_equipment_tasks=[];report.ore_checks=[];
  const total=item=>manager.state.view().inventory.filter(v=>v.item_id===item).reduce((n,v)=>n+v.count,0);
  const facts=()=>JSON.parse(readFileSync(resolve(import.meta.dirname,
    '../runtime/minecraft/mc-friends-s1-neoforge-21.1.248/work/logs/ai-talk-streamer-native.json'),'utf8'));
  await auto();
  async function craft(item_id,count){
    const goal={skill:'craft',item_id,count},before=manager.state.view(),checked=await operation('check_action',{goal});
    assert.equal(checked.result?.allowed,true,JSON.stringify(checked));
    const completed=await terminal(await task('native-tool-craft-'+report.tool_crafting_tasks.length,goal,90000),95000);
    const row={goal,before,checked,task:completed};report.tool_crafting_tasks.push(row);
    assert.equal(completed.state,'succeeded',JSON.stringify(completed));assert.equal(completed.effect_status,'verified');
    await until(()=>{const p=facts().control_proof.native_craft;return p.task_id===completed.task_id && p.clean_end && !p.active && p.cursor_empty;},5000);
    row.after=manager.state.view();row.client_proof=facts();
    assert.ok(total(item_id)>=before.inventory.filter(v=>v.item_id===item_id).reduce((n,v)=>n+v.count,0)+count);
  }
  async function gather(item_id,count,label){
    if(!manager.state.view().automation_ready)await auto();
    const goal={skill:'gather',item_id,count},before=manager.state.view(),checked=await operation('check_action',{goal});
    if(!checked.result?.allowed)return {available:false,checked,goal};
    const completed=await terminal(await task('native-tool-gather-'+label+'-'+report.tool_supply_tasks.length,goal,90000),95000);
    await until(()=>{const p=facts().control_proof;return p.native_travel.task_id===completed.task_id
      && !p.native_travel.active && p.native_input.all_owned_inputs_clear;},5000);
    const row={available:true,goal,before,checked,task:completed,after:manager.state.view(),client_proof:facts()};report.tool_supply_tasks.push(row);
    return row;
  }
  report.existing_pickaxe_count=total('minecraft:stone_pickaxe');
  // Reuse actual inventory from earlier confirmed tasks when it already contains both
  // required tools. A quarry can leave the player outside workstation reach.
  if(report.existing_pickaxe_count<2){
    if(total('minecraft:stick')<8)await craft('minecraft:stick',8-total('minecraft:stick'));
    if(total('minecraft:cobblestone')<4){const row=await gather('minecraft:cobblestone',4-total('minecraft:cobblestone'),'prepare');assert.equal(row.task?.state,'succeeded',JSON.stringify(row));}
    if(total('minecraft:wooden_shovel')===0)await craft('minecraft:wooden_shovel',1);
    await craft('minecraft:stone_pickaxe',1);
  }
  // Earlier actual attempts can leave a usable pickaxe in the hotbar. Use the ordinary
  // equipment task to place that one in the offhand; retain its full server receipt.
  {
    const goal={skill:'use_item',item_id:'minecraft:stone_pickaxe',purpose:'equip'},before=manager.state.view();
    const checked=await operation('check_action',{goal});assert.equal(checked.result?.allowed,true,JSON.stringify(checked));
    const completed=await terminal(await task('native-tool-equip-offhand',goal));
    assert.equal(completed.state,'succeeded',JSON.stringify(completed));assert.equal(completed.effect_status,'verified');
    await until(()=>{const p=facts();return p.offhand_item==='minecraft:stone_pickaxe' && p.control_proof.native_input.all_owned_inputs_clear;},5000);
    report.tool_equipment_tasks.push({goal,before,checked,task:completed,after:manager.state.view(),client_proof:facts()});
  }
  report.final_pickaxe_gather=await gather('minecraft:cobblestone',3,'stone-pickaxe');
  assert.equal(report.final_pickaxe_gather.task?.state,'succeeded',JSON.stringify(report.final_pickaxe_gather));
  assert.equal(report.final_pickaxe_gather.task.effect_status,'verified');
  // A prior real run may already have crafted a backpack pickaxe. Material collection can
  // therefore exercise the swap before this run's next pickaxe is crafted; keep both receipts.
  report.pickaxe_gather=report.tool_supply_tasks.find(r=>r.task.state==='succeeded'
    && r.task.effect_status==='verified' && r.client_proof.control_proof.native_travel.tool_belt.confirmed_swaps>0);
  assert.ok(report.pickaxe_gather,'NO_SERVER_CONFIRMED_BACKPACK_TOOL_GATHER');
  const belt=report.pickaxe_gather.client_proof.control_proof.native_travel.tool_belt;
  assert.ok(belt.confirmed_swaps>0 && belt.source_slot>=9 && belt.source_slot<36 && belt.server_full_packets>=belt.confirmed_swaps);
  assert.equal(belt.pending,false);assert.equal(belt.closed,true);
  assert.ok(report.pickaxe_gather.client_proof.control_proof.native_input.all_owned_inputs_clear);
  report.backpack_tool_swap_verified=true;
  for(const item_id of ['minecraft:raw_iron','minecraft:coal']){
    const goal={skill:'gather',item_id,count:1},checked=await operation('check_action',{goal});
    const row={goal,checked,available:checked.result?.allowed===true};report.ore_checks.push(row);
    // Record the actual loaded-world result. An unavailable ore is not invented or counted as mined.
    if(row.available){row.gather=await gather(item_id,1,'ore');row.verified=row.gather.task?.state==='succeeded' && row.gather.task.effect_status==='verified';}
  }
  report.pause_after_tools=await control('PAUSED');assert.equal(report.pause_after_tools.state,'succeeded');
  persist('physical-input-needed.json',{phase:'COMPLETE'});
}
async function exitProbe() {
  report.exit_navigation_checks=[];
  async function choose(points,label){
    for(const [x,y,z] of points){
      const goal={skill:'navigate',target:{dimension:'minecraft:overworld',x,y,z},radius:.5};
      const checked=await operation('check_action',{goal});report.exit_navigation_checks.push({label,goal,checked});
      if(checked.result?.allowed)return {goal,checked};
    }
    throw Error('NO_ACTUAL_STANDABLE_ROUTE_FOR_'+label);
  }
  async function walk(selected,label){
    const before=manager.state.view();if(!before.automation_ready)await auto();
    const completed=await terminal(await task('native-real-'+label,selected.goal,180000),185000);
    const row={...selected,before,task:completed};report.exit_paths??=[];report.exit_paths.push(row);
    await until(()=>{const p=facts().control_proof;return p.native_travel.task_id===completed.task_id && !p.native_travel.active && p.native_input.all_owned_inputs_clear;},5000);
    row.after=manager.state.view();row.client_proof=facts();
    assert.equal(completed.state,'succeeded',JSON.stringify(completed));assert.equal(completed.effect_status,'verified');return row;
  }
  // Both endpoints were observed on this same player's prior real run. Recheck the current world.
  report.exit_pit_entry=await walk(await choose([[-687,73,999]],'pit-entry'),'pit-entry');
  report.exit_navigation=await walk(await choose([[-683,77,1001]],'opened-stair-exit'),'opened-stair-exit');
  report.exit_navigation.previously_opened_corridor=true;
  assert.ok(report.exit_navigation.client_proof.y-report.exit_navigation.before.player.position.y>=3,'ACTUAL_QUARRY_RISE_NOT_OBSERVED');
  report.exit_workstation_navigation=await walk(await choose([[-685,75,1001],[-684,75,1001],[-685,75,1000],[-684,76,1001]],'workstation'),'workstation-approach');
  const craftGoal={skill:'craft',item_id:'minecraft:stone_axe',count:1},craftBefore=manager.state.view();
  const craftCheck=await operation('check_action',{goal:craftGoal});report.exit_craft={goal:craftGoal,before:craftBefore,checked:craftCheck};
  assert.equal(craftCheck.result?.allowed,true,JSON.stringify(craftCheck));
  const crafted=await terminal(await task('native-real-post-exit-stone-axe',craftGoal,90000),95000);report.exit_craft.task=crafted;
  assert.equal(crafted.state,'succeeded',JSON.stringify(crafted));assert.equal(crafted.effect_status,'verified');
  await until(()=>{const p=facts().control_proof;return p.native_craft.task_id===crafted.task_id && p.native_craft.clean_end && !p.native_craft.active && p.native_input.all_owned_inputs_clear;},5000);
  report.exit_craft.after=manager.state.view();report.exit_craft.client_proof=facts();
  report.pause_before_exit_base=await control('PAUSED');assert.equal(report.pause_before_exit_base.state,'succeeded');
  await until(()=>manager.state.view().mode==='PAUSED' && manager.state.view().inputs_released,5000);
  const home=manager.state.view();
  const registered=await api('/worlds/'+home.world_id+'/bases',{request_id:'native-post-exit-home-'+report.probe_run_id,
    bridge_boot_id:home.bridge_boot_id,world_session_id:home.world_session_id,
    expected_world_revision:manager.worlds.get(home.world_id).revision,label:'实际出坑后的工作台落脚点',radius:1});
  assert.equal(registered.status,201,JSON.stringify(registered));report.exit_base=registered.value;
  const away=await walkingGoal(2);report.exit_away_goal=away;
  await auto();
  report.exit_away_task=await terminal(await task('native-post-exit-walk',away,90000),95000);
  assert.equal(report.exit_away_task.state,'succeeded',JSON.stringify(report.exit_away_task));
  report.exit_return_task=await terminal(await task('native-post-exit-return',{skill:'return_base',base_id:registered.value.base_id},90000),95000);
  assert.equal(report.exit_return_task.state,'succeeded',JSON.stringify(report.exit_return_task));assert.equal(report.exit_return_task.effect_status,'verified');
  await until(()=>facts().control_proof.native_input.all_owned_inputs_clear,4000);
  report.exit_return_proof=facts();
  report.pause_after_exit=await control('PAUSED');assert.equal(report.pause_after_exit.state,'succeeded');
  persist('physical-input-needed.json',{phase:'COMPLETE'});
}
try {
  await new Promise((accept, reject) => { server.once('error', reject); server.listen(18974, '127.0.0.1', accept); });
  base = 'http://127.0.0.1:' + server.address().port; manager.start();
  persist('host-ready.json', { endpoint: base.replace('http:', 'ws:') + '/api/dsh/game/bridge', pid: process.pid });
  await until(() => manager.state.view().freshness === 'fresh' && manager.state.value.inputs_released, 660000);
  if (executeItems) {
    persist('physical-input-needed.json', { phase: 'MANUAL_RESPAWN_OR_FOCUS', state: manager.state.view() });
    await until(() => {
      if (manager.state.value.screen !== 'gameplay' || manager.state.value.player?.health <= 0) return false;
      try {
        const facts = JSON.parse(readFileSync(resolve(import.meta.dirname,
          '../runtime/minecraft/mc-friends-s1-neoforge-21.1.248/work/logs/ai-talk-streamer-native.json'), 'utf8'));
        return facts.alive && facts.gameplay_executor_bound && facts.missing_native_hooks.length === 0;
      } catch { return false; }
    }, 120000);
    // The native adapter itself renegotiates readiness; the engineering host cannot repair it.
    await until(() => manager.state.view().freshness === 'fresh'
      && manager.capabilities.execution_profile === 'native_core', 20000);
    if (executeTravel || executeCraft || executeSmelt || executeTools || executeExit) {
      const state = manager.state.view();
      persist('physical-input-needed.json', { phase: 'WINDOWS_FOREGROUND_REQUIRED',
        probe_run_id: report.probe_run_id, state });
      await until(() => {
        try {
          const proof = JSON.parse(readFileSync(join(output, 'foreground-ready.json'), 'utf8'));
          const current = manager.state.view();
          const age = Date.now() - Date.parse(proof.observed_at);
          if (proof.probe_run_id !== report.probe_run_id || proof.world_session_id !== current.world_session_id
              || proof.control_epoch !== current.control_epoch || current.mode !== 'PAUSED'
              || !current.inputs_released || !proof.foreground_pid_verified || !proof.creation_ticks_verified
              || typeof proof.creation_ticks !== 'string' || !/^[0-9]{17,20}$/.test(proof.creation_ticks)
              || !Number.isFinite(age) || age < 0 || age >= 2000)
            return false;
          report.foreground_preflight = proof; return true;
        } catch { return false; }
      }, 120000);
    }
  }
  report.capabilities = structuredClone(manager.capabilities); report.initial_state = manager.state.view();
  assert.equal(manager.capabilities.adapter, 'minecraft.neoforge');
  assert.ok(['none', 'native_core'].includes(manager.capabilities.execution_profile));
  if (executeItems) assert.equal(manager.capabilities.execution_profile, 'native_core');
  assert.equal(manager.state.value.mode, 'PAUSED');
  const frame = await operation('frame', {});
  assert.equal(frame.state, 'succeeded', JSON.stringify(frame));
  const response = await fetch(base + '/api/dsh/game/frames/' + frame.result.frame_id);
  assert.equal(response.status, 200); const bytes = Buffer.from(await response.arrayBuffer());
  writeFileSync(join(output, 'native-bridge-frame.jpg'), bytes);
  report.frame_sha256 = createHash('sha256').update(bytes).digest('hex');
  const recipe = await operation('recipe', { item_id: 'minecraft:oak_planks', count: 8 });
  report.recipe_available = recipe.state === 'succeeded';
  assert.equal(recipe.state, 'succeeded', JSON.stringify(recipe)); assert.equal(recipe.result.recipe_known, true);
  const checked = await operation('check_action', { goal: { skill: 'use_item', item_id: 'minecraft:bread', purpose: 'eat' } });
  assert.equal(checked.state, 'succeeded', JSON.stringify(checked));
  if (manager.capabilities.execution_profile === 'none') {
    assert.equal(checked.result.allowed, false); assert.equal(checked.result.reason, 'GAME_EXECUTOR_ADAPTER_NOT_BOUND');
  }
  // Force a non-gameplay precondition out of the AUTO check by testing capability rejection only when gameplay is observed.
  if (manager.capabilities.execution_profile === 'none' && manager.state.value.screen === 'gameplay') {
    report.auto = await control('AUTO'); assert.equal(report.auto.status, 503, JSON.stringify(report.auto));
    assert.equal(report.auto.value.error, 'GAME_CAPABILITY_UNAVAILABLE');
  } else report.auto = { not_attempted: executeItems ? 'EXPLICIT_ITEM_PROBE_FOLLOWS' : 'PASSIVE_PROBE_DOES_NOT_GRANT_INPUTS', current_screen: manager.state.value.screen };
  if (executeItems) {
    await until(() => manager.state.value.screen === 'gameplay', 120000);
    const inventory = manager.state.value.inventory;
    const item = inventory.find(value => value.item_id === 'integrateddynamics:on_the_dynamics_of_integration') || inventory.find(value => value.count > 0);
    assert.ok(item, 'NO_EXISTING_ITEM_FOR_ACTUAL_EQUIPMENT_PROBE');
    const goal = { skill: 'use_item', item_id: item.item_id, purpose: 'equip' }; report.actual_equipment_goal = goal;
    const check = await operation('check_action', { goal });
    assert.equal(check.state, 'succeeded', JSON.stringify(check)); assert.equal(check.result.allowed, true, JSON.stringify(check));
    report.auto = await auto();
    report.equipment_task = await terminal(await task('native-real-offhand-equip', goal));
    assert.equal(report.equipment_task.state, 'succeeded', JSON.stringify(report.equipment_task));
    assert.equal(report.equipment_task.effect_status, 'verified');
    assert.ok(report.equipment_task.evidence.some(value => value.kind === 'item_effect'));
    report.idempotent_equipment_task = await terminal(await task('native-real-offhand-already-equipped', goal));
    assert.equal(report.idempotent_equipment_task.state, 'succeeded', JSON.stringify(report.idempotent_equipment_task));
    const id = await task('native-real-immediate-cancel', goal);
    report.cancel_request = await api('/tasks/' + id + '/cancel', { request_id: 'native-real-cancel', reason: 'engineering_explicit_cancel' });
    report.cancel_race_task = await terminal(id);
    assert.ok(['succeeded', 'cancelled'].includes(report.cancel_race_task.state));
    // A completed task can win this race; record the actual outcome, never invent an interruption.
    report.pause_after_items = await control('PAUSED'); assert.equal(report.pause_after_items.state, 'succeeded');
    if (executeExit) await exitProbe();
    else if (executeTools) await toolsProbe();
    else if (executeSmelt) await smeltProbe();
    else if (executeCraft) await craftProbe();
    else if (executeTravel) await travelProbe();
    else {
    if (process.argv.includes('--diagnose-remote-shortcut'))
      report.remote_shortcut_probe = await physicalGate('MCP_F10_PACKET', 'MANUAL_COMMENTARY', 'PHYSICAL_KEYBOARD_INPUT');
    report.f10_pause = await physicalGate('F10', 'PAUSED', 'LOCAL_PANIC_KEY');
    report.keyboard_takeover = await physicalGate('KEYBOARD_SHIFT', 'MANUAL_COMMENTARY', 'PHYSICAL_KEYBOARD_INPUT');
    report.mouse_takeover = await physicalGate('MOUSE_MOVE', 'MANUAL_COMMENTARY', 'PHYSICAL_MOUSE_INPUT');
    persist('physical-input-needed.json', { phase: 'COMPLETE' });
    }
  }
  report.commentary = await control('MANUAL_COMMENTARY'); assert.equal(report.commentary.state, 'succeeded');
  report.pause = await control('PAUSED'); assert.equal(report.pause.state, 'succeeded');
  const before = manager.state.view(); manager.socket.terminate();
  await until(() => {
    const state = manager.state.view(); return state.freshness === 'fresh'
      && state.connection_generation > before.connection_generation && state.mode === 'PAUSED' && state.inputs_released;
  }, 20000);
  report.reconnected_state = manager.state.view();
  assert.equal(report.reconnected_state.bridge_boot_id, before.bridge_boot_id);
  assert.equal(report.reconnected_state.world_session_id, before.world_session_id);
  report.task_ledger_query = executeExit ? 'ACTUAL_SERVER_CONFIRMED_QUARRY_STAIRS_WORKSTATION_CRAFT_AND_RETURN' : executeTools ? 'ACTUAL_CRAFTED_BACKPACK_TOOL_SWAP_AND_HARVEST_CHAIN' : executeSmelt ? 'ACTUAL_SERVER_CONFIRMED_RESOURCE_FURNACE_AND_COOKING_CHAIN' : executeCraft ? 'ACTUAL_SERVER_CONFIRMED_EQUIPMENT_CRAFT_CHAIN_AND_TABLE_PLACEMENT'
    : executeItems ? 'ACTUAL_SERVER_CONFIRMED_EQUIPMENT_AND_RECORDED_CANCEL_RACE' : 'NO_ACTUAL_TASKS_ACCEPTED';
  report.health = manager.healthView(); assert.ok(!manager.faulted);
  assert.equal(manager.state.value.automation_ready, false); report.ok = true;
} catch (error) { report.error = String(error.stack || error); report.health = manager.healthView(); report.state = manager.state.view(); }
finally {
  persist('physical-input-needed.json',{phase:'COMPLETE',probe_ok:report.ok});
  await manager.close(); for (const socket of sockets) socket.destroy();
  await new Promise(resolve => server.close(resolve)); report.closed_at = new Date().toISOString();
  persist('native-bridge-integration.json', report);
}
process.exitCode = report.ok ? 0 : 1;
