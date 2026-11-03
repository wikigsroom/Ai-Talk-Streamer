import { test } from 'node:test';
import assert from 'node:assert/strict';
import { narrationFixture } from './game-narration-fixture.mjs';
import { until } from './game-fixture.mjs';
import { validate } from '../backend/game/protocol.mjs';
import { SUPPORT_LIMITS } from '../backend/game/audience-sources.mjs';

const command = '建议 采集 minecraft:oak_log 4';
const settings = (f, moderation) => f.room.configure({ expected_revision:f.room.store.revision, patch:{moderation} });
async function source(f, user='viewer-a', extra={}) {
  const result=await f.comment(command,{user_id:user,nickname:user,...extra});
  const value=f.manager.suggestions.page().items.find(value=>value.source_event_ids.includes(result.key));
  return {key:result.key,value};
}
function vote(f) {
  const state=f.manager.state.value;
  return f.manager.votes.create({request_id:'support-vote-'+f.manager.votes.page().items.length,bridge_boot_id:state.bridge_boot_id,world_session_id:state.world_session_id,title:'采什么',duration_seconds:60,options:[{option_id:'wood',label:'木头',goal:{skill:'gather',item_id:'minecraft:oak_log',count:4}},{option_id:'stone',label:'石头',goal:{skill:'gather',item_id:'minecraft:cobblestone',count:4}}]}).value;
}
const decide=(f,v)=>f.manager.suggestions.decision(v.suggestion_id,{request_id:'approve-'+v.suggestion_id,expected_revision:v.revision,action:'accept',reason:'导播核对来源'});
const dispatch=(f,v)=>f.api('/suggestions/'+v.suggestion_id+'/dispatch',{request_id:'dispatch-'+v.suggestion_id,bridge_boot_id:f.manager.state.value.bridge_boot_id,world_session_id:f.manager.state.value.world_session_id,expected_control_epoch:f.manager.state.value.control_epoch,expected_revision:v.revision});

test('current support separates repeated events, distinct stable accounts and unknown identities without nickname deduplication',async t=>{
  const f=await narrationFixture(t);
  for(let i=0;i<3;i++)await source(f,'viewer-a',{nickname:'同名'});
  for(let i=0;i<2;i++)await source(f,'viewer-b',{nickname:'同名'});
  const {value}=await source(f,null,{nickname:'同名'}), current=f.manager.suggestions.get(value.suggestion_id);
  assert.equal(current.support_count,6);assert.equal(current.support.visible_events,6);assert.equal(current.support.visible_viewers,2);assert.equal(current.support.unidentified_events,1);
  assert.equal(current.support.tracked_events,6);assert.equal(current.support.coverage,'complete');validate('Suggestion',current);
});

test('support beyond the32 public source preview remains usable when every previewed source is filtered',async t=>{
  const f=await narrationFixture(t), entries=[];
  for(let i=0;i<40;i++)entries.push(await source(f,'viewer-'+i));
  let value=f.manager.suggestions.get(entries[0].value.suggestion_id);assert.equal(value.source_event_ids.length,32);assert.equal(value.support.tracked_events,40);
  settings(f,{blocked_users:entries.slice(8).map(e=>f.room.store.message(e.key).user_key)});
  value=f.manager.suggestions.get(value.suggestion_id);assert.equal(value.state,'proposed');assert.equal(value.support.visible_events,8);assert.equal(value.support.visible_viewers,8);
  assert.equal(value.support_count,40);assert.equal(f.manager.suggestions.sourceAvailable(value),true);
});

for(const [name,patch] of [['words',{blocked_words:['minecraft:oak_log']}],['names',{blocked_names:['viewer-a']}],['accounts',null]])test('changing '+name+' filters immediately retracts the final source and cancels its pending suggestion',async t=>{
  const f=await narrationFixture(t), {key,value}=await source(f);
  settings(f,patch||{blocked_users:[f.room.store.message(key).user_key]});
  const current=f.manager.suggestions.get(value.suggestion_id);assert.equal(current.state,'cancelled');assert.equal(current.support.visible_events,0);assert.equal(current.support_count,1);
  assert.equal(f.manager.tasks.active(),null);assert.equal(f.room.store.message(key).answered,false);
});

test('partial filtering recomputes support and removing the filter restores counts without replaying a ballot or task',async t=>{
  const f=await narrationFixture(t), a=await source(f), b=await source(f,'viewer-b');
  settings(f,{blocked_names:['viewer-a']});let value=f.manager.suggestions.get(a.value.suggestion_id);assert.equal(value.support.visible_events,1);assert.equal(value.state,'proposed');
  settings(f,{blocked_names:[]});value=f.manager.suggestions.get(value.suggestion_id);assert.equal(value.support.visible_events,2);assert.equal(value.support_count,2);
  assert.equal(value.source_event_ids.includes(b.key),true);assert.equal(f.manager.tasks.active(),null);
});

test('restoring the last hidden message does not reopen a previously cancelled suggestion',async t=>{
  const f=await narrationFixture(t), {key,value}=await source(f);
  f.room.messageControl({action:'hide',id:key});f.room.messageControl({action:'restore',id:key});
  const current=f.manager.suggestions.get(value.suggestion_id);assert.equal(current.state,'cancelled');assert.equal(current.support.visible_events,1);
  assert.throws(()=>decide(f,current),{code:'GAME_SUGGESTION_CLOSED'});assert.equal(f.manager.tasks.active(),null);
});

test('filtering an active ballot retracts exactly that source and unblocking never recasts the old event',async t=>{
  const f=await narrationFixture(t), v=vote(f), a=await f.comment('投票 wood',{user_id:'viewer-a',nickname:'viewer-a'});
  await f.comment('投票 stone',{user_id:'viewer-b',nickname:'viewer-b'});settings(f,{blocked_users:[f.room.store.message(a.key).user_key]});
  let current=f.manager.votes.get(v.vote_id);assert.deepEqual(current.options.map(o=>o.votes),[0,1]);assert.equal(current.state,'active');
  settings(f,{blocked_users:[]});assert.deepEqual(f.manager.votes.get(v.vote_id).options.map(o=>o.votes),[0,1]);
  await f.comment('投票 wood',{user_id:'viewer-a'});assert.deepEqual(f.manager.votes.get(v.vote_id).options.map(o=>o.votes),[1,1]);
});

test('filter changes invalidate a closed promoted winner instead of selecting another goal',async t=>{
  const f=await narrationFixture(t);let v=vote(f);await f.comment('投票 wood',{nickname:'winner'});
  v=f.manager.votes.close(v.vote_id,{request_id:'support-close',expected_revision:v.revision,action:'close',reason:'导播结束'});
  const proposal=f.manager.votes.promote(v.vote_id,{request_id:'support-promote',bridge_boot_id:f.manager.state.value.bridge_boot_id,world_session_id:f.manager.state.value.world_session_id,expected_revision:v.revision}).value;
  settings(f,{blocked_names:['winner']});v=f.manager.votes.get(v.vote_id);assert.equal(v.state,'cancelled');assert.equal(v.winning_option_id,null);
  assert.equal(f.manager.suggestions.get(proposal.suggestion_id).state,'cancelled');assert.equal(f.manager.tasks.active(),null);
});

test('current support changes advance the actual suggestion revision and reject a stale approval',async t=>{
  const f=await narrationFixture(t), a=await source(f);await source(f,'viewer-b');const before=f.manager.suggestions.get(a.value.suggestion_id);
  settings(f,{blocked_names:['viewer-a']});const after=f.manager.suggestions.get(before.suggestion_id);assert.equal(after.revision,before.revision+1);
  assert.throws(()=>decide(f,before),{code:'GAME_SUGGESTION_CONFLICT'});assert.equal(decide(f,after).state,'accepted');
});

test('filtering the final source while a real preflight query is pending prevents task submission',async t=>{
  const f=await narrationFixture(t);await f.game.auto();const {value}=await source(f), approved=decide(f,value), operation=(await dispatch(f,approved)).value;
  const frame=await f.game.next('query',m=>m.payload.request.kind==='check_action'), pending=f.manager.operation(frame.payload.operation_id);
  settings(f,{blocked_names:['viewer-a']});f.game.send('query_result',{...pending,state:'succeeded',result:{kind:'check_action',world_session_id:f.manager.state.value.world_session_id,allowed:true}});
  await until(()=>f.manager.operation(operation.operation_id).state==='failed');assert.equal(f.manager.tasks.active(),null);
  assert.equal(f.game.messages.filter(m=>m.type==='task_start').length,0);
});

test('missing Room rows are reconciled through the existing host tick rather than remaining counted indefinitely',async t=>{
  const f=await narrationFixture(t), {key,value}=await source(f), v=vote(f), ballot=await f.comment('投票 wood');
  f.room.store.run('DELETE FROM messages WHERE id IN (?,?)',key,ballot.key);f.advanceClock(1100);f.manager.tick();
  assert.equal(f.manager.suggestions.get(value.suggestion_id).state,'cancelled');assert.equal(f.manager.votes.get(v.vote_id).options[0].votes,0);
});

test('temporary Room unavailability preserves ballot ownership and reports support as unknown rather than zero',async t=>{
  const f=await narrationFixture(t), {value}=await source(f), v=vote(f);await f.comment('投票 wood');
  f.bridge.room=null;f.manager.reconcileAudienceSources();let current=f.manager.suggestions.get(value.suggestion_id);
  assert.equal(current.state,'proposed');assert.equal(current.support.source_availability,'unavailable');assert.equal(current.support.visible_events,null);
  assert.equal(f.manager.votes.get(v.vote_id).options[0].votes,1);validate('Suggestion',current);
  f.bridge.room=f.room;f.manager.reconcileAudienceSources();current=f.manager.suggestions.get(value.suggestion_id);assert.equal(current.support.visible_events,1);
});

test('actual GameStore reopen retains all support beyond the public preview and submits no automatic task',async t=>{
  const f=await narrationFixture(t);let value;
  for(let i=0;i<34;i++)value=(await source(f,'viewer-'+i)).value;
  await f.restartHost();const current=f.manager.suggestions.get(value.suggestion_id);
  assert.equal(current.support.tracked_events,34);assert.equal(current.support.visible_events,34);assert.equal(current.source_event_ids.length,32);assert.equal(f.manager.tasks.active(),null);
});

test('legacy truncated records explicitly expose incomplete coverage without inventing missing supporters',async t=>{
  const f=await narrationFixture(t), a=await source(f);await source(f,'viewer-b');let value=f.manager.suggestions.get(a.value.suggestion_id);
  const prefix=value.suggestion_id+':';f.manager.store.run("DELETE FROM objects WHERE kind='audience_support' AND id>=? AND id<?",prefix,prefix+'\uffff');
  f.manager.store.run("DELETE FROM objects WHERE kind='audience_support_manifest' AND id=?",value.suggestion_id);
  delete value.support;value.support_count=50;f.manager.store.put('suggestion',value);value=f.manager.suggestions.get(value.suggestion_id);
  assert.equal(value.support.coverage,'legacy_partial');assert.equal(value.support.historical_events,50);assert.equal(value.support.tracked_events,2);assert.equal(value.support.visible_viewers,2);
});

test('repeated platform dispatch and unchanged source reconciliation do not increment support or revision',async t=>{
  const f=await narrationFixture(t), {value}=await source(f);const before=f.manager.suggestions.get(value.suggestion_id);
  for(let i=0;i<3;i++){await f.platforms.dispatch();f.manager.reconcileAudienceSources();}
  assert.deepEqual(f.manager.suggestions.get(value.suggestion_id),before);
});

test('unrelated layout edits preserve the support revision and do not call the audience reconciler',async t=>{
  const f=await narrationFixture(t), {value}=await source(f), before=f.manager.suggestions.get(value.suggestion_id), original=f.manager.reconcileAudienceSources;
  f.manager.reconcileAudienceSources=()=>assert.fail('unrelated layout must not scan supporter storage');
  try{f.room.configure({expected_revision:f.room.store.revision,patch:{overlay:{mc_chat_side:'left'}}});}finally{f.manager.reconcileAudienceSources=original;}
  assert.equal(f.manager.suggestions.get(value.suggestion_id).revision,before.revision);
});

test('terminal support details expire after the bounded retention window without erasing suggestion history',async t=>{
  const f=await narrationFixture(t), {value}=await source(f);f.advanceClock(120001);f.manager.suggestions.expire();
  f.advanceClock(SUPPORT_LIMITS.terminal_retention_ms);f.manager.audienceSources.prune();const current=f.manager.suggestions.get(value.suggestion_id);
  assert.equal(current.state,'expired');assert.equal(current.support_count,1);assert.equal(current.support.coverage,'retained_window_expired');assert.equal(current.support.tracked_events,0);
  assert.equal(f.manager.audienceSources.total(),0);assert.equal(current.source_event_ids.length,1);
});

test('a full per-suggestion ledger rejects extra merging without fabricating historical support or losing the existing proposal',async t=>{
  const f=await narrationFixture(t), {value}=await source(f), sources=f.manager.audienceSources;
  f.manager.store.transaction(()=>{for(let i=1;i<SUPPORT_LIMITS.per_suggestion;i++)sources.record(value,'retained-fixture-'+i);});
  const seeded={...f.manager.suggestions.get(value.suggestion_id),support_count:4096};f.manager.store.put('suggestion',seeded);
  await source(f,'over-capacity');const current=f.manager.suggestions.get(value.suggestion_id);
  assert.equal(current.support_count,4096);assert.equal(current.support.tracked_events,4096);assert.equal(current.state,'proposed');assert.equal(f.manager.suggestions.page().items.length,1);
});

test('the global support budget is bounded in the real store and unavailable capacity leaves input as ordinary chat',async t=>{
  const f=await narrationFixture(t), sources=f.manager.audienceSources, insert=f.manager.store.db.prepare('INSERT INTO objects VALUES(?,?,?,?,?)');
  f.manager.store.transaction(()=>{for(let i=0;i<SUPPORT_LIMITS.total;i++)insert.run('audience_support','fixture-capacity-'+i,null,1,JSON.stringify({event_id:'fixture-'+i}));});
  await source(f);assert.equal(f.manager.suggestions.page().items.length,0);assert.equal(sources.total(),SUPPORT_LIMITS.total);
  validate('AudienceSupportBudget',f.manager.suggestions.summary().support_budget);
});

test('a legacy saturated historical counter refuses additional support rather than accepting an event without counting it',async t=>{
  const f=await narrationFixture(t), {value}=await source(f);
  f.manager.store.run("DELETE FROM objects WHERE kind='audience_support_manifest' AND id=?",value.suggestion_id);
  f.manager.store.put('suggestion',{...value,support_count:1000000});await source(f,'over-historical-capacity');
  const current=f.manager.suggestions.get(value.suggestion_id);
  assert.equal(current.support_count,1000000);assert.equal(current.support.tracked_events,1);assert.equal(current.support.coverage,'legacy_partial');
  assert.equal(f.manager.tasks.active(),null);
});

test('counts and source lookup stay scoped to the selected platform room even when another room uses the same account and text',async t=>{
  const f=await narrationFixture(t), {value}=await source(f);await source(f,'viewer-a',{room_id:'200'});
  assert.equal(f.manager.suggestions.get(value.suggestion_id).support.visible_events,1);assert.equal(f.manager.audienceSources.rows(value.suggestion_id).length,1);
});

test('source storage failure refuses continued game control while retaining the saved moderation settings for recovery',async t=>{
  const f=await narrationFixture(t);await source(f);const original=f.manager.votes.reconcileSources;
  f.manager.votes.reconcileSources=()=>{throw new Error('fixture storage unavailable')};
  assert.throws(()=>settings(f,{blocked_names:['viewer-a']}),/fixture storage unavailable/);
  f.manager.votes.reconcileSources=original;assert.equal(f.manager.faulted,true);assert.deepEqual(f.room.store.settings.moderation.blocked_names,['viewer-a']);assert.equal(f.manager.tasks.active(),null);
});

test('approval feedback beyond the32-item preview uses surviving real sources and completes only their actual speech links',async t=>{
  const f=await narrationFixture(t), entries=[];
  for(let i=0;i<40;i++)entries.push(await source(f,'feedback-'+i));
  for(const item of f.manager.narration.open())f.manager.narration.finish(item,'cancelled','FIXTURE_CLEAR_QUESTIONS');
  settings(f,{blocked_users:entries.slice(8).map(e=>f.room.store.message(e.key).user_key)});
  const approved=decide(f,f.manager.suggestions.get(entries[0].value.suggestion_id));
  const request=await f.run();assert(request);const context=JSON.parse(f.calls.at(-1).context);
  assert.equal(context.narration.kind,'suggestion_result');assert.equal(context.narration.source.support.visible_events,8);
  assert.equal(f.room.speechLinks[request.request_id].length,8);const {result}=f.complete();assert.equal(result.accepted,true);await new Promise(resolve=>queueMicrotask(resolve));
  assert(entries.slice(0,8).every(e=>f.room.store.message(e.key).answered));assert(entries.slice(8).every(e=>!f.room.store.message(e.key).answered));
  assert.equal(f.manager.suggestions.get(approved.suggestion_id).state,'accepted');assert.equal(f.manager.tasks.active(),null);
});

test('filtering all bounded speech links during generation rechecks surviving support and never emits the old response',async t=>{
  let entered=false,first=true,release;const gate=new Promise(resolve=>release=resolve);
  const f=await narrationFixture(t,async()=>{if(first){first=false;entered=true;await gate;}return{text:'我会按当前有效来源继续核对。'}});let value;
  for(let i=0;i<40;i++)value=(await source(f,'retry-'+i)).value;
  for(const item of f.manager.narration.open())f.manager.narration.finish(item,'cancelled','FIXTURE_CLEAR_QUESTIONS');
  decide(f,f.manager.suggestions.get(value.suggestion_id));const processing=f.run();await until(()=>entered);
  const old=f.state.active(), links=f.room.speechLinks[old.request_id];assert.equal(links.length,32);
  settings(f,{blocked_users:links.map(id=>f.room.store.message(id).user_key)});release();await processing;
  assert.equal(f.media.length,0);assert.equal(f.state.request(old.request_id).status,'CANCELLED');
  const request=await f.run();assert(request);assert.equal(JSON.parse(f.calls.at(-1).context).narration.source.support.visible_events,8);
  assert.equal(f.room.speechLinks[request.request_id].length,8);f.complete();assert(links.every(id=>!f.room.store.message(id).answered));
});

test('filtering a source after task conversion preserves the approved task and does not send a game cancellation',async t=>{
  const f=await narrationFixture(t);await f.game.auto();const {value}=await source(f), approved=decide(f,value), operation=(await dispatch(f,approved)).value;
  const frame=await f.game.next('query',m=>m.payload.request.kind==='check_action'), pending=f.manager.operation(frame.payload.operation_id);
  f.game.send('query_result',{...pending,state:'succeeded',result:{kind:'check_action',world_session_id:f.manager.state.value.world_session_id,allowed:true}});
  await until(()=>f.manager.operation(operation.operation_id).state==='succeeded');const task=f.manager.tasks.active(), cancels=f.game.messages.filter(m=>m.type==='cancel').length;
  settings(f,{blocked_names:['viewer-a']});const current=f.manager.suggestions.get(value.suggestion_id);
  assert.equal(current.state,'converted');assert.equal(current.task_id,task.task_id);assert.equal(f.manager.tasks.active().task_id,task.task_id);
  assert.equal(current.support.visible_events,0);assert.equal(f.game.messages.filter(m=>m.type==='cancel').length,cancels);
});

test('approved vote feedback uses the real vote record rather than requiring a synthetic vote ID to exist as a Room comment',async t=>{
  const f=await narrationFixture(t);let v=vote(f);await f.comment('投票 wood');
  v=f.manager.votes.close(v.vote_id,{request_id:'support-feedback-close',expected_revision:v.revision,action:'close',reason:'导播结束'});
  const proposal=f.manager.votes.promote(v.vote_id,{request_id:'support-feedback-promote',bridge_boot_id:f.manager.state.value.bridge_boot_id,world_session_id:f.manager.state.value.world_session_id,expected_revision:v.revision}).value;
  for(const item of f.manager.narration.open())f.manager.narration.finish(item,'cancelled','FIXTURE_CLEAR_EXISTING');
  decide(f,proposal);const request=await f.run();assert(request);const context=JSON.parse(f.calls.at(-1).context);
  assert.equal(context.narration.kind,'suggestion_result');assert.equal(context.narration.source.origin.kind,'vote');assert.equal(f.media.length,1);
  assert.equal(f.manager.tasks.active(),null);f.complete();
});
