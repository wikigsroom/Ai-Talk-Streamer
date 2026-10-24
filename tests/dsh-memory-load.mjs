// Synthetic approved records exercise real SQLite retrieval. No model/GPU calls.
import {mkdtempSync,mkdirSync,statSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import assert from 'node:assert/strict';
import {StateStore} from '../backend/memory/store.mjs';
import {StreamState} from '../backend/dsh-bridge/state.mjs';
import {MemoryService} from '../backend/memory/service.mjs';
import {loadPolicy} from '../backend/dsh-bridge/policy.mjs';
const parent=resolve('../outputs/dsh-humanity/load');mkdirSync(parent,{recursive:true});
const root=mkdtempSync(join(parent,'run-')),file=join(root,'state/female-a/stream.sqlite3'),db=new StateStore(file);
const policy=loadPolicy(root),state=new StreamState(db,policy,'test'),memory=new MemoryService(db,state,policy,{});
try{
 db.tx(()=>{
  for(const subject of ['viewer-load-a','viewer-load-b']){
   const seq=db.event(state.scope({}, {actor_kind:'operator',actor_id:'synthetic-fixture'}),'operator.load_seed',{text:'Synthetic approved load fixture',partition_key:subject});
   const event=db.get('SELECT * FROM stream_events WHERE event_seq=?',seq);
   for(let i=0;i<5000;i++)memory.mergeInTransaction({subject_key:subject,visibility:'viewer',fact_key:'load.fact_'+i,value:i,polarity:'positive',content:subject+' synthetic record '+i,state:'active',reason:'synthetic_approved_fixture',evidence_kind:'viewer_statement',sources:[{...event,text:'Synthetic approved load fixture',quote:'Synthetic approved load fixture'}]},'load',0);
  }
 });
 const times=[];
 for(let i=0;i<20;i++){
  const start=performance.now(),result=memory.recall('viewer-load-a','fact');times.push(performance.now()-start);
  assert.ok(result.viewer.every(row=>row.subject_key==='viewer-load-a'));assert.ok(result.viewer.length<=3);assert.equal(result.public.length,0);
 }
 times.sort((a,b)=>a-b);
 const report={schema_version:1,kind:'synthetic_partition_retrieval',records_per_partition:5000,partitions:2,samples:times.length,p50_ms:times[9],p95_ms:times[18],target_p95_ms:150,target_met:times[18]<=150,rss_bytes:process.memoryUsage().rss,database_bytes:statSync(file).size,wal_bytes:statSync(file+'-wal').size,claims_long_duration_stability:false};
 writeFileSync(resolve('../outputs/dsh-humanity/memory-load.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{db.close()}
