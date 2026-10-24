// Real abrupt termination exercises the on-disk WAL, without closing SQLite.
import {join} from 'node:path';
import {StateStore} from '../../backend/memory/store.mjs';
import {StreamState} from '../../backend/dsh-bridge/state.mjs';
import {loadPolicy} from '../../backend/dsh-bridge/policy.mjs';
import {MemoryService,validateExtraction} from '../../backend/memory/service.mjs';
import {MaintenanceScheduler} from '../../backend/memory/scheduler.mjs';
const [root,point]=process.argv.slice(2),db=new StateStore(join(root,'state/female-a/stream.sqlite3'));
const policy=structuredClone(loadPolicy(root));policy.maintenance.post_broadcast_quiet_ms=0;
const state=new StreamState(db,policy,'test'),memory=new MemoryService(db,state,policy,{});
const scheduler=new MaintenanceScheduler(db,state,memory,policy,null),job=scheduler.claim();
if(!job)throw Error('No crash-test job');
const chunk=scheduler.chunk(job),source=chunk.fresh[0];
const result={schema_version:1,summary:'明确饮品偏好',open_questions:[],candidate_facts:[{fact_key:'preference.drink',value:'tea',polarity:'positive',evidence_kind:'viewer_statement',validity:'persistent_candidate',source_refs:[{event_id:source.event_id,quote:source.text}]}]};
db.tx(()=>db.run("INSERT INTO job_chunks(job_id,chunk_index,input_sha256,source_start_seq,source_end_seq,state,attempt_count) VALUES (?,0,?,?,?,'PENDING',1)",job.job_id,chunk.inputHash,chunk.start,chunk.end));
if(point==='before_commit'){
 const run=db.run.bind(db);db.run=(sql,...args)=>{if(sql.startsWith('UPDATE compaction_jobs SET consumed_through_seq'))process.exit(17);return run(sql,...args);};
}
scheduler.commit(job,chunk,0,result,validateExtraction(result,chunk.sources,job.partition_key));
process.exit(19);
