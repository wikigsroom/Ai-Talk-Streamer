import test from 'node:test';
import assert from 'node:assert/strict';
import {hostToolNames} from '../backend/dsh-bridge/host.mjs';
import {DshMcCandidate,candidateModelResult} from '../backend/game/dsh-candidate.mjs';

test('real blocked/no-harvest outcomes never become success just because the SDK envelope has isError=false',()=>{
 const after={position:{x:1,y:75,z:2},health:20,food:20,inventory:[]};
 const blocked=candidateModelResult({isError:false,text:'⛔ 走不动',value:{status:'blocked'}},after);
 assert.equal(blocked.isError,true);assert.equal(blocked.outcome,'blocked');
 assert.equal(candidateModelResult({isError:false,text:'❌ 动作失败（挖到 0/3 个）',value:{text:'original'}},after).isError,true);
 assert.equal(candidateModelResult({isError:false,text:'✅ 已确认成功',value:{outcome:'confirmed'}},after).isError,false);
});

test('large upstream map and usage payloads remain outside the live planning and speech context',()=>{
 const enormous='map value that must not be replayed '.repeat(20000);
 const after={position:{x:1,y:75,z:2},health:20,food:20,inventory:[{name:'dirt',count:1}]};
 const result=candidateModelResult({isError:false,text:'actual nearest blocks '.repeat(1000),value:{map:enormous}},after);
 assert(JSON.stringify(result).length<2300);assert(!('value' in result));assert.equal(result.truncated,true);
 const c=Object.create(DshMcCandidate.prototype);c.view=()=>({...after,mode:'AUTO',connected:true,vision:{description:{caption:'stone wall'},captured_at:'2026-11-03T00:00:00Z',source:'dsh_mc_observe_reconstruction',usage:{attribution:enormous}}});
 const view=c.modelView();assert.equal(view.vision.description.caption,'stone wall');assert(!('usage' in view.vision));assert.deepEqual(view.inventory,after.inventory);
});

test('candidate capabilities remain limited to planning; speech and vision never gain game actions or plugin administration',()=>{
 const catalogue=['game_mc_status','game_mc_dig','game_mc_command','mc_admin_config'].map(name=>({name}));
 assert.deepEqual(hostToolNames('game_plan',catalogue),['game_mc_status','game_mc_dig']);
 assert(!hostToolNames('speech',catalogue).some(x=>x.includes('mc_')));
 assert.deepEqual(hostToolNames('vision',catalogue),[]);
});
test('candidate AUTO rejects creative mode and a programme without an official local playback session',async()=>{
 const c=Object.create(DshMcCandidate.prototype);
 Object.assign(c,{ready:true,mode:'PAUSED',generation:0,config:{},bridge:{state:{current:()=>null}},registry:{peek:()=>({bot:{online:true,bot:{username:'NAIMEI',game:{gameMode:'creative'}}}})},agent:{id:'a'},log:()=>{}});
 await assert.rejects(()=>c.setMode('AUTO'),/SURVIVAL_REQUIRED/);
 c.registry.peek=()=>({bot:{online:true,bot:{username:'NAIMEI',game:{gameMode:'survival'}}}});
 await assert.rejects(()=>c.setMode('AUTO'),/LOCAL_PROGRAMME_REQUIRED/);
 assert.equal(c.mode,'PAUSED');assert.equal(c.generation,0);
});
test('candidate pause cancels the current decision and releases movement and mining without a game input path',async()=>{
 const c=Object.create(DshMcCandidate.prototype),calls=[],controller=new AbortController();
 const bot={clearControlStates:()=>calls.push('release'),pathfinder:{setGoal:x=>calls.push(x)},stopDigging:()=>calls.push('stop-dig')};
 Object.assign(c,{generation:1,turnController:controller,log:()=>{},view:()=>({}),registry:{peek:()=>({bot:{bot}})},agent:{id:'a'}});
 await c.setMode('PAUSED');assert(controller.signal.aborted);assert.equal(c.generation,2);assert.equal(c.mode,'PAUSED');assert.deepEqual(calls,['release',null,'stop-dig']);
});
