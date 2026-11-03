import { randomUUID } from 'node:crypto';
import { createMood,decay,applyDelta } from '../dsh-bridge/community/mood/core.mjs';
import { 算命中线 } from '../dsh-bridge/community/speak-up/probability.mjs';
import { speechState } from './model-state.mjs';
import taskFailures from '../../web/mc-task-failures.js';

/** Programme pacing and emotional context. The existing queue alone speaks. */
export class LivePerformance {
  constructor(queue,{random=Math.random}={}) {
    this.queue=queue;this.manager=queue.manager;this.random=random;this.misses=0;
    this.seen=new Set();this.mood=createMood(this.manager.wall());this.lastDecision=0;
  }
  task(task) {
    if(!['succeeded','failed','cancelled'].includes(task.state)||this.seen.has(task.task_id))return;
    if(task.world_session_id!==this.manager.state.value.world_session_id)return;
    this.seen.add(task.task_id);if(this.seen.size>128)this.seen.delete(this.seen.values().next().value);
    const success=task.state==='succeeded'&&task.effect_status==='verified';
    const failure=task.state==='failed';if(!success&&!failure)return;
    if(success && task.goal?.skill==='navigate')return;
    const old=this.manager.store.meta('live_mood_v1',null);
    if(this.moodWorld!==task.world_id){this.mood=createMood(this.manager.wall());this.moodWorld=task.world_id;}
    if(old?.world_id===task.world_id&&old.mood?.dims&&Array.isArray(old.mood.timeline))this.mood=old.mood;
    decay(this.mood,this.manager.wall());
    applyDelta(this.mood,{moodDelta:success?3:-3,dims:success?{happy:8,calm:3,worry:-4}:{happy:-2,worry:5},
      reason:success?'刚完成一项游戏目标':'刚才的尝试未做成',confidence:100,source_id:task.task_id},this.manager.wall());
    this.manager.store.setMeta('live_mood_v1',{world_id:task.world_id,mood:this.mood});
  }
  context() {
    decay(this.mood,this.manager.wall());
    const dominant=Object.entries(this.mood.dims).sort((a,b)=>b[1]-a[1])[0];
    const expression=dominant?.[1]>=8?(dominant[0]==='worry'?'thoughtful':'pleased'):'attentive';
    return {mood:Math.round(this.mood.mood),expression,reason:this.mood.lastReason||null,
      rule:'情绪只是角色表达状态，不是观众事实。自然体现一点，不报心情数字；不因重复失败持续抱怨。'};
  }
  tick() {
    const q=this.queue,m=this.manager,live=q.live(),state=m.state.view(),now=m.wall();
    if(live?.state!=='LIVE'||!m.config.planner.enabled||state.mode!=='AUTO'||state.freshness!=='fresh'||state.screen!=='gameplay')return;
    if(this.broadcast!==live.broadcast_id){this.broadcast=live.broadcast_id;this.startedAt=now;this.lastBeat=now;this.misses=0;}
    if(q.open().length||m.bridge.state.active()||m.bridge.state.status().queued.length)return;
    const answered=q.all().filter(x=>x.broadcast_id===live.broadcast_id&&x.state==='answered');
    const last=Math.max(this.startedAt,...answered.map(x=>Date.parse(x.updated_at)||0));
    const quiet=now-Math.max(last,this.lastBeat);
    if(quiet<18000||now-this.lastDecision<3000)return;
    this.lastDecision=now;
    const chance=算命中线(35,Math.min(1.7,quiet/20000),this.misses,15,60).线;
    if(quiet<32000&&this.random()*100>=chance){this.misses++;return;}
    const tasks=m.tasks.page({limit:8}).items.filter(x=>x.world_session_id===state.world_session_id);
    const results=tasks.filter(x=>['succeeded','failed'].includes(x.state)).slice(0,3).map(taskSpeechFacts);
    const current=tasks.find(x=>x.task_id===state.active_task_id);
    const id='beat-'+randomUUID();
    const source={programme_beat_id:id,revision:1,world_session_id:state.world_session_id,world_id:state.world_id,
      observed_at:new Date(now).toISOString(),kind:'programme_beat',producer:'autonomous_programme',
      observation:speechState(state),current_goal:current?.goal||m.planner.mindcraft?.lastPlan?.next_goal||null,
      recent_results:results,expression:this.context()};
    m.store.put('programme_beat',source);q.enqueue('programme_beat',id,'status');
    this.lastBeat=now;this.misses=0;
    m.store.run("DELETE FROM objects WHERE kind='programme_beat' AND rowid NOT IN (SELECT rowid FROM objects WHERE kind='programme_beat' ORDER BY rowid DESC LIMIT 64)");
  }
}

export function taskSpeechFacts(task) {
  const result=Object.fromEntries(['task_id','world_id','world_session_id','goal','state','effect_status','reason','updated_at'].filter(k=>Object.hasOwn(task,k)).map(k=>[k,structuredClone(task[k])]));
  // Keep the actual partial-effect evidence and fixed failure meaning. Long
  // histories remain in game_get_task instead of becoming repeated narration.
  if(Array.isArray(task.evidence)) {
    result.evidence=task.evidence.slice(-3).map(row=>({...row,summary:row.summary.slice(0,240)}));
    if(task.evidence.length>3||task.evidence.some(row=>row.summary.length>240))
      result.evidence_projection={truncated:true,query_tool:'game_get_task'};
  }
  return taskFailures.facts(result);
}
