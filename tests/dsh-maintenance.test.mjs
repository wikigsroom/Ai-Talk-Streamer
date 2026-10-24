import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync,mkdtempSync,readFileSync,copyFileSync,unlinkSync} from 'node:fs';
import {resolve,join,relative} from 'node:path';
import {StateStore} from '../backend/memory/store.mjs';
import {StreamState} from '../backend/dsh-bridge/state.mjs';
import {MemoryService,validateExtraction} from '../backend/memory/service.mjs';
import {MaintenanceScheduler} from '../backend/memory/scheduler.mjs';
import {MemoryAdministration} from '../backend/memory/administration.mjs';
import {prepareRestore} from '../backend/memory/restore.mjs';
import {loadPolicy} from '../backend/dsh-bridge/policy.mjs';
import {initialPersona} from '../backend/dsh-bridge/persona.mjs';
import {canonical,digest} from '../backend/dsh-bridge/channel.mjs';
import {spawnSync} from 'node:child_process';

const op={role:'operator',principal_id:'op',viewer_id:'viewer-a'};
function fixture() {
 const parent=resolve('../outputs/dsh-humanity/unit');mkdirSync(parent,{recursive:true});const root=mkdtempSync(join(parent,'case-'));
 mkdirSync(join(root,'configs/characters'),{recursive:true});copyFileSync(resolve('configs/characters/female-a.json'),join(root,'configs/characters/female-a.json'));
 let now=Date.parse('2026-10-26T04:11:00+08:00');
 const db=new StateStore(join(root,'state/female-a/stream.sqlite3'),{now:()=>now,heartbeat:false}),policy=structuredClone(loadPolicy(root));policy.maintenance.post_broadcast_quiet_ms=0;
 const state=new StreamState(db,policy,'test'),projection=new Map();
 const port={mirrorRevision:0,injectionEnabled:false,setNativeMemoryInjection({enabled}){this.injectionEnabled=enabled},setVerifiedMirrorRevision(v){this.mirrorRevision=v},inspectProjection(id){return projection.get(id)},async applyPublicProjection(p){projection.set(p.memory_id,{memory_revision:p.memory_revision,entry:p.action==='UPSERT'?{content:p.content,status:'active'}:null});return {entry_id:p.memory_id}},async flush(){},readPersona(){const p=initialPersona(root);return {document:p.document,publication:{persona_version:p.version}}}};
 const memory=new MemoryService(db,state,policy,port),host={port,active:new Map(),ctx:{sessionPersistence:{async flush(){}}}};
 const admin=new MemoryAdministration(root,db,state,memory,host,async()=>{});
 const advance=ms=>{db.tx(()=>db.run('UPDATE bridge_owner SET lease_until=?',now+ms+30000));now+=ms};
 const start=()=>{const b=state.createBroadcast(op);state.claimAuthority(op,b.broadcast_id,'browser-unit');state.readyBroadcast(b.broadcast_id,true);return b};
 const accept=(text='我喜欢茶。',isPublic=false)=>state.accept(op,{text,mode:'echo',public_input:isPublic,idempotency_key:crypto.randomUUID()});
 const end=()=>{state.end(op);state.tick()};
 const extract=(source,value='tea')=>({schema_version:1,summary:'明确饮品偏好',open_questions:[],candidate_facts:[{fact_key:'preference.drink',value,polarity:'positive',evidence_kind:'viewer_statement',validity:'persistent_candidate',source_refs:[{event_id:source.event_id,quote:source.text}]}]});
 const seed=(isPublic=false)=>{start();const r=accept('我喜欢茶。',isPublic),partition=isPublic?'public':op.viewer_id,source=memory.eligibleEvents(r.broadcast_id,partition)[0];const candidate=validateExtraction(extract(source),[source],partition)[0];const result=db.tx(()=>memory.mergeInTransaction(candidate,'unit',0));return db.get('SELECT * FROM memory_entries WHERE memory_id=?',result.memory_id)};
 return {root,db,policy,state,memory,admin,port,projection,advance,start,accept,end,extract,seed,close:()=>db.close()};
}
test('A01: legacy Windows migration hashes survive newline conversion; content mismatch still fails closed',()=>{
 const f=fixture();let reopened;
 try{
  f.db.tx(()=>{
   for(const [version,file] of [[1,'001-init.sql'],[2,'002-runtime.sql']]){
    const lf=readFileSync(resolve('backend/memory/migrations',file),'utf8').replace(/\r\n/g,'\n');
    assert.equal(f.db.get('SELECT migration_sha256 FROM schema_migrations WHERE version=?',version).migration_sha256,digest(lf));
    f.db.run('UPDATE schema_migrations SET migration_sha256=? WHERE version=?',digest(lf.replace(/\n/g,'\r\n')),version);
   }
  });
  f.close();reopened=new StateStore(f.db.file,{heartbeat:false});assert.equal(reopened.integrity().integrity,'ok');
  reopened.tx(()=>reopened.run("UPDATE schema_migrations SET migration_sha256=? WHERE version=1",'0'.repeat(64)));
  reopened.close();assert.throws(()=>new StateStore(f.db.file,{heartbeat:false}),/STORE_MIGRATION_HASH/);
 }finally{reopened?.close();f.close()}
});

test('A23/A30: failed extraction keeps cursor; daily budget includes unknown usage and resets by local date',async()=>{
 const f=fixture();try{f.start();f.accept();f.end();const s=new MaintenanceScheduler(f.db,f.state,f.memory,f.policy,async()=>{throw Error('429')});const job=s.claim();await s.runJob(job);
  const failed=f.db.get('SELECT * FROM compaction_jobs');assert.equal(failed.state,'RETRY_WAIT');assert.equal(failed.consumed_through_seq,failed.source_start_seq-1);
  f.policy.maintenance.max_model_calls_per_day=1;const attempt=s.reserveModel({jobId:job.job_id,inputHash:digest('x'),providerRevision:'x',maxTokens:10});s.settleModel(attempt,null,true,true);
  assert.throws(()=>s.reserveModel({jobId:job.job_id,inputHash:digest('x'),providerRevision:'x',maxTokens:10}),/DAILY_BUDGET/);
  f.advance(86400000);assert.ok(s.reserveModel({jobId:job.job_id,inputHash:digest('x'),providerRevision:'x',maxTokens:10}));
 }finally{f.close()}
});
test('A24: canonical commit is retained while projection retries; no second model extraction',async()=>{
 const f=fixture();try{f.start();f.accept('我喜欢茶。',true);f.end();let calls=0;
  const s=new MaintenanceScheduler(f.db,f.state,f.memory,f.policy,async({chunk})=>{calls++;return f.extract(chunk.fresh[0])});
  const apply=f.port.applyPublicProjection;f.port.applyPublicProjection=async()=>{throw Error('mirror unavailable')};await s.runJob(s.claim());
  const pending=f.db.get('SELECT * FROM compaction_jobs');assert.equal(pending.stage,'PROJECTING');assert.equal(pending.reason,'projection_lag');assert.equal(pending.consumed_through_seq,pending.source_end_seq);
  f.port.applyPublicProjection=apply;f.advance(11000);await s.runJob(s.claim());assert.equal(calls,1);assert.equal(f.db.get('SELECT state FROM compaction_jobs').state,'COMPLETED');assert.equal(f.port.injectionEnabled,true);
 }finally{f.close()}
});
test('A24: loss of an acknowledged mirror entry is repaired from canonical outbox',async()=>{
 const f=fixture();try{const m=f.seed(true);await f.memory.project();assert.equal(f.port.injectionEnabled,true);f.projection.delete(m.memory_id);await f.memory.project();assert.equal(f.projection.get(m.memory_id).entry.content,m.content);assert.equal(f.db.get("SELECT state FROM mirror_outbox").state,'APPLIED');}finally{f.close()}
});
test('A25/A33: corrections have source revisions and compensating undo cannot overwrite a later edit',()=>{
 const f=fixture();try{const m=f.seed();const first=f.admin.correct(op,{operation_id:'correction-first',memory_id:m.memory_id,expected_revision:1,value:'coffee',content:'我现在明确更正为喜欢咖啡。',polarity:'positive'});
  assert.equal(f.memory.recall(op.viewer_id).viewer[0].value,'coffee');assert.ok(f.memory.sourceValid(first));
  f.admin.correct(op,{operation_id:'correction-second',memory_id:m.memory_id,expected_revision:2,value:'tea',content:'再次确认喜欢茶。',polarity:'positive'});
  assert.throws(()=>f.admin.undo(op,{operation_id:'correction-first'}),/LATER_REVISION/);
 }finally{f.close()}
});
test('A27/A28: restoring an old backup replays latest deletion identities before recall',async()=>{
 const f=fixture();try{const m=f.seed();f.end();const backup=await f.admin.backup();await f.admin.delete(op,{operation_id:'delete-test',subject_key:op.viewer_id,memory_id:m.memory_id});assert.equal(f.memory.recall(op.viewer_id).viewer.length,0);
  const receipt=prepareRestore(f.root,'backups/'+backup.backup_id);assert.equal(receipt.replayed_deletions,1);assert.equal(receipt.deletion_generation,1);
  const restored=new StateStore(receipt.database);try{assert.equal(restored.get('SELECT state FROM memory_entries').state,'deleted');assert.equal(restored.get('SELECT content FROM memory_entries').content,'');assert.deepEqual(restored.integrity(),{integrity:'ok',foreign_keys:[]});}finally{restored.close()}
  unlinkSync(join(f.root,'state/deletion-ledger.jsonl'));assert.throws(()=>prepareRestore(f.root,'backups/'+backup.backup_id),/LEDGER_MISSING/);
 }finally{f.close()}
});
test('A29/A34: restart catch-up occurrences deduplicate and only one worker claims a job',()=>{
 const f=fixture();try{f.start();f.accept();f.end();const s=new MaintenanceScheduler(f.db,f.state,f.memory,f.policy,null);s.scheduleOccurrences();const n=f.db.get('SELECT COUNT(*) n FROM schedule_occurrences').n;assert.ok(n>=2);
  const second=new MaintenanceScheduler(f.db,f.state,f.memory,f.policy,null);second.scheduleOccurrences();assert.equal(f.db.get('SELECT COUNT(*) n FROM schedule_occurrences').n,n);assert.ok(s.claim());assert.equal(second.claim(),null);
 }finally{f.close()}
});
test('A16/A38: twenty rounds retain initial topic, bounded rolling body and no repeated recent tail',()=>{
 const f=fixture();try{const b=f.start();for(let i=0;i<20;i++){const r=f.accept(i===0?'我的项目叫星河，主题是宿舍学习。':'第'+i+'轮问题？');f.state.cancel(r.request_id)}
  const r=f.accept('最开始的项目是什么？');const context=JSON.parse(f.memory.context(r,{revision:'test'}));assert.ok(canonical(context).includes('星河'));
  const summary=context.rolling_summary;assert.ok(canonical(summary).length<=f.policy.conversation.rolling_summary_max_chars);const ids=new Set(summary.confirmed_events.map(e=>e.event_id));assert.ok(context.recent_confirmed_events.every(e=>!ids.has(e.event_id)));
 }finally{f.close()}
});
test('A01/A34: a second live SQLite owner cannot start over the first',()=>{
 const f=fixture();try{assert.throws(()=>new StateStore(f.db.file),/OWNER_ACTIVE/)}finally{f.close()}
});
test('A31: an unwritable database stops accepting writes without replacing the canonical file',()=>{
 const f=fixture();try{f.start();const before=f.db.get('SELECT COUNT(*) n FROM requests').n;f.db.tx(()=>f.db.run('PRAGMA query_only=ON'));
  assert.throws(()=>f.accept());assert.equal(f.db.faulted,true);assert.equal(f.db.get('SELECT COUNT(*) n FROM requests').n,before);assert.throws(()=>f.db.tx(()=>{}),/STORAGE_FAULT/);
 }finally{f.close()}
});

test('A22: a real process exit before/after WAL commit preserves the atomic cursor and facts',()=>{
 for(const point of ['before_commit','after_commit']){
  const f=fixture();f.start();f.accept();f.end();
  // Use real wall time in the child; make the already closed broadcast eligible.
  f.db.tx(()=>f.db.run("UPDATE broadcasts SET consolidation_not_before='2000-01-01T00:00:00.000Z'"));
  f.db.tx(()=>f.db.run("UPDATE compaction_jobs SET not_before='2000-01-01T00:00:00.000Z'"));f.close();
  const child=spawnSync(process.execPath,['tests/fixtures/dsh-crash-worker.mjs',f.root,point],{encoding:'utf8',windowsHide:true});
  assert.equal(child.status,point==='before_commit'?17:19,child.stderr);
  const db=new StateStore(join(f.root,'state/female-a/stream.sqlite3'));
  try{
   const job=db.get('SELECT * FROM compaction_jobs');
   assert.equal(db.get('SELECT COUNT(*) n FROM memory_entries').n,point==='before_commit'?0:1);
   assert.equal(db.get("SELECT COUNT(*) n FROM job_chunks WHERE state='COMMITTED'").n,point==='before_commit'?0:1);
   assert.equal(job.consumed_through_seq,point==='before_commit'?job.source_start_seq-1:job.source_end_seq);
   assert.deepEqual(db.integrity(),{integrity:'ok',foreign_keys:[]});
  }finally{db.close()}
 }
});
