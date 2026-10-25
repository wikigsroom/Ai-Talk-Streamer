import { test } from 'node:test';
import assert from 'node:assert/strict';
import { StateStore } from '../backend/memory/store.mjs';
import { StreamState } from '../backend/dsh-bridge/state.mjs';
import { StreamBridge } from '../backend/dsh-bridge/server.mjs';
import { MemoryService, validateExtraction } from '../backend/memory/service.mjs';
import { MaintenanceScheduler } from '../backend/memory/scheduler.mjs';
import { loadPolicy } from '../backend/dsh-bridge/policy.mjs';
import { digest } from '../backend/dsh-bridge/channel.mjs';
import { resolve } from 'node:path';
import { createServer } from 'node:http';

const root = resolve(process.cwd());
const op = { role: 'operator', principal_id: 'op', viewer_id: 'viewer-op' };
const viewer = { role: 'viewer', principal_id: 'user-a', viewer_id: 'viewer-a' };
const other = { role: 'viewer', principal_id: 'user-b', viewer_id: 'viewer-b' };
const connector = () => ({ mirrorRevision: 0, setNativeMemoryInjection() {}, setVerifiedMirrorRevision(revision) { this.mirrorRevision = revision; }, inspectProjection() { return null; } });
function fixture() {
  let now = Date.now();
  const db = new StateStore(':memory:', { now: () => now, heartbeat: false });
  const policy = structuredClone(loadPolicy(root)); policy.maintenance.post_broadcast_quiet_ms = 0;
  const state = new StreamState(db, policy, 'persona-test'), memory = new MemoryService(db, state, policy, connector());
  const start = () => { const b = state.createBroadcast(op); const lease = state.claimAuthority(op, b.broadcast_id, 'browser-test'); state.readyBroadcast(b.broadcast_id, true); return lease; };
  return { db, state, memory, policy, start, advance: ms => { db.tx(()=>db.run('UPDATE bridge_owner SET lease_until=?',now+ms+30000));now += ms; }, close: () => db.close() };
}
function accept(state, principal = viewer, text = '我喜欢茶。', key = 'key-' + Math.random()) { return state.accept(principal, { text, idempotency_key: key }); }
function spoken(f, count = 1000) {
  const request = f.state.activate();
  const utterance = f.state.textReady(request.request_id, '你好，我是林知夏。', request.runtime_epoch, request.generation);
  f.state.audioReady({ ...utterance, valid_sample_count: count, audio_sha256: digest('audio') });
  const ranges = [{ packet_seq: 1, packet_offset:0, sample_start: 0, sample_count: Math.min(640, count) }];
  if (count > 640) ranges.push({ packet_seq: 2, packet_offset:0, sample_start: 640, sample_count: count - 640 });
  f.state.mediaMap({ ...utterance, valid_sample_count:count,transport_instance_id: 'transport-test', ranges, final: true });
  return utterance;
}
function receipt(f, utterance, lease, n, natural = false, sequence = 1) { return f.state.receipt(op, { ...utterance, consumer_id: lease.consumer_id, lease_id: lease.lease_id, authority_epoch: lease.authority_epoch, contiguous_played_samples: n, natural_end: natural, receipt_sequence: sequence, transport_instance_id: 'transport-test' }); }

test('SQLite rolls back an event and refuses asynchronous business transactions', () => {
  const f = fixture(); try {
    const before = f.db.all('SELECT * FROM stream_events').length;
    assert.throws(() => f.db.tx(() => { f.db.event(f.state.scope(), 'test.rollback', {}); throw new Error('inject'); }));
    assert.equal(f.db.all('SELECT * FROM stream_events').length, before);
    assert.throws(() => f.db.tx(() => Promise.resolve()), /ASYNC/);
    assert.deepEqual(f.db.integrity(), { integrity: 'ok', foreign_keys: [] });
  } finally { f.close(); }
});
test('A04/A05: request retry is idempotent; changing its payload conflicts', () => {
  const f=fixture(); try {
    f.start(); const request=accept(f.state,viewer,'你好','same-key-123');
    for(let i=0;i<10;i++) assert.equal(accept(f.state,viewer,'你好','same-key-123').request_id,request.request_id);
    assert.equal(f.db.get('SELECT COUNT(*) n FROM requests').n,1);
    assert.throws(()=>accept(f.state,viewer,'别的话','same-key-123'),/IDEMPOTENCY/);
  } finally { f.close(); }
});
test('A06: FIFO has one active request; cancelling a queued viewer cannot interrupt it', () => {
  const f=fixture(); try {
    f.start(); accept(f.state); const active=f.state.activate(), gen=f.state.room().generation;
    const queued=accept(f.state,other); f.state.cancel(queued.request_id);
    assert.equal(f.state.active().request_id,active.request_id); assert.equal(f.state.room().generation,gen);
    for(let i=0;i<4;i++) accept(f.state,other);
    assert.throws(()=>accept(f.state,other),/QUEUE_FULL/); assert.equal(f.state.activate(),null);
  } finally { f.close(); }
});
test('A07/A08: audio generation and sending are not played assistant history', () => {
  const f=fixture(); try {
    f.start(); accept(f.state); const utterance=spoken(f);
    assert.equal(f.state.request(utterance.request_id).status,'BUFFERING');
    assert.equal(f.memory.eligibleEvents(utterance.broadcast_id,viewer.viewer_id).filter(e=>e.event_type==='playback.completed').length,0);
    f.state.fail(utterance.request_id,'tts_injected_failure');
    assert.equal(f.memory.eligibleEvents(utterance.broadcast_id,viewer.viewer_id).length,1);
  } finally { f.close(); }
});
test('A08/A11: only contiguous mapped natural completion produces completed history', () => {
  const f=fixture(); try {
    const lease=f.start();accept(f.state);const u=spoken(f);
    assert.equal(receipt(f,u,lease,500,false).completed,false);
    assert.equal(f.state.request(u.request_id).status,'PLAYING');
    assert.equal(receipt(f,u,lease,500,true,2).accepted,false);
    assert.equal(receipt(f,u,lease,1000,true,3).completed,true);
    assert.equal(f.state.request(u.request_id).status,'COMPLETED');
    assert.equal(f.memory.eligibleEvents(u.broadcast_id,viewer.viewer_id).filter(e=>e.event_type==='playback.completed').length,1);
  } finally { f.close(); }
});

test('A07: media failure fences and flushes once; a late prefix ACK preserves FAILED', () => {
  const f=fixture();try {
    const lease=f.start();accept(f.state);const u=spoken(f);receipt(f,u,lease,400);
    const generation=f.state.room().generation,barriers=[];f.state.on('cancel',barrier=>barriers.push(barrier));
    const barrier=f.state.fail(u.request_id,'TTS_FAILED');
    assert.equal(f.state.request(u.request_id).status,'FAILED');assert.equal(f.state.room().generation,generation+1);
    assert.deepEqual(barriers,[barrier]);assert.equal(f.state.fail(u.request_id,'other').already_terminal,true);assert.equal(barriers.length,1);
    assert.equal(receipt(f,u,lease,1000,true,2).accepted,false);
    assert.throws(()=>f.state.audioReady({...u,valid_sample_count:1000,audio_sha256:digest('late')}),/STALE_GENERATION/);
    f.state.cancelAck(op,{...barrier,...lease,contiguous_played_samples:450,transport_instance_id:'transport-test'});
    assert.equal(f.state.request(u.request_id).status,'FAILED');
    const after=f.db.get('SELECT * FROM utterances WHERE utterance_id=?',u.utterance_id);
    assert.equal(after.status,'FAILED');assert.equal(after.contiguous_played_samples,450);assert.ok(after.observation_revision>0);
    assert.equal(f.memory.eligibleEvents(u.broadcast_id,viewer.viewer_id).length,1);
    assert.equal(f.db.all("SELECT * FROM stream_events WHERE event_type='request.failed'").length,1);
  }finally{f.close()}
});

test('A07: the Bridge TTS watchdog records FAILED and starts the next request at a newer generation',async()=>{
  const f=fixture();try{
    const lease=f.start();accept(f.state);const active=f.state.activate();
    const u=f.state.textReady(active.request_id,'等待超时的语音',active.runtime_epoch,active.generation);
    f.policy.conversation.tts_timeout_ms=1000;f.advance(1100);f.state.heartbeat(lease.lease_id,lease.consumer_id);
    const queued=accept(f.state,other),started=[],barriers=[];f.state.on('cancel',b=>barriers.push(b));
    const bridge={closed:false,ready:true,administration:{locked:false},db:f.db,state:f.state,policy:f.policy,processRequest:async request=>started.push(request)};
    await StreamBridge.prototype.tick.call(bridge);
    assert.equal(f.state.request(u.request_id).status,'FAILED');assert.equal(barriers.length,1);
    const event=f.db.get("SELECT event_seq FROM stream_events WHERE request_id=? AND event_type='request.failed'",u.request_id);
    assert.equal(f.db.payload(event.event_seq).reason,'TTS_TIMEOUT');
    assert.equal(started[0].request_id,queued.request_id);assert.ok(started[0].generation>barriers[0].new_generation);
  }finally{f.close()}
});

test('request deadline is a failure and emits the same media flush barrier',()=>{
  const f=fixture();try{
    f.start();accept(f.state);f.policy.conversation.active_request_deadline_ms=1000;const r=f.state.activate(),barriers=[];
    f.state.on('cancel',b=>barriers.push(b));f.advance(1001);f.state.tick();
    assert.equal(f.state.request(r.request_id).status,'FAILED');assert.equal(barriers.length,1);
    const event=f.db.get("SELECT event_seq FROM stream_events WHERE request_id=? AND event_type='request.failed'",r.request_id);
    assert.equal(f.db.payload(event.event_seq).reason,'REQUEST_DEADLINE_EXCEEDED');
  }finally{f.close()}
});

test('media HTTP commands are serialized; stale speech is never sent and a failed command does not poison the queue',async()=>{
  let announce,release;const started=new Promise(done=>announce=done),held=new Promise(done=>release=done),wire=[];
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);
    wire.push({path:req.url,body:JSON.parse(Buffer.concat(chunks))});
    if(wire.length===1){announce();await held}
    res.writeHead(wire.at(-1).body.inject_failure?503:200,{'Content-Type':'application/json'});res.end('{"accepted":true}');
  });
  await new Promise(done=>server.listen(0,'127.0.0.1',done));
  const bridge={mediaChain:Promise.resolve(),avatarUrl:'http://127.0.0.1:'+server.address().port,auth:{mediaKey:'fixture'},state:{matches:(_id,_epoch,generation)=>generation===10}};
  const send=(action,body)=>StreamBridge.prototype.mediaCommand.call(bridge,action,body);
  try{
    const cancel=send('cancel',{request_id:'old'});await started;
    const speak=send('speak',{request_id:'new',runtime_epoch:1,generation:10});await new Promise(done=>setImmediate(done));
    assert.equal(wire.length,1);release();await Promise.all([cancel,speak]);
    assert.deepEqual(wire.map(item=>item.path),['/internal/dsh/cancel','/internal/dsh/speak']);
    await assert.rejects(send('speak',{request_id:'old',runtime_epoch:1,generation:8}),/STALE_GENERATION/);assert.equal(wire.length,2);
    await assert.rejects(send('cancel',{inject_failure:true}),/MEDIA_COMMAND_FAILED/);
    assert.deepEqual(await send('cancel',{}),{accepted:true});assert.equal(wire.length,4);
  }finally{release();server.closeAllConnections();await new Promise(done=>server.close(done))}
});
test('A09/A10/A12: cancel fences old generation and accepts bounded partial ack without exact text', () => {
  const f=fixture(); try {
    const lease=f.start();accept(f.state);const u=spoken(f);receipt(f,u,lease,400);
    const barrier=f.state.cancel(u.request_id);
    assert.equal(f.state.request(u.request_id).status,'INTERRUPTED');
    assert.equal(receipt(f,u,lease,1000,true,2).accepted,false);
    f.state.cancelAck(op,{...barrier,...lease,consumer_id:lease.consumer_id,contiguous_played_samples:450,transport_instance_id:'transport-test'});
    assert.equal(f.memory.eligibleEvents(u.broadcast_id,viewer.viewer_id).length,1);
  } finally { f.close(); }
});
test('A13/A14: a second browser has no completion authority; leases cannot be combined', () => {
  const f=fixture(); try {
    const lease=f.start();accept(f.state);const u=spoken(f);receipt(f,u,lease,400);
    assert.throws(()=>f.state.claimAuthority(op,u.broadcast_id,'browser-second'),/ALREADY_HELD/);
    const next=f.state.claimAuthority(op,u.broadcast_id,'browser-second',true);
    assert.notEqual(next.runtime_epoch,lease.runtime_epoch);
    assert.equal(f.state.request(u.request_id).status,'UNKNOWN');
    assert.equal(receipt(f,u,next,1000,true,2).accepted,false);
  } finally { f.close(); }
});
test('A15: losing preview does not implicitly end a broadcast', () => {
  const f=fixture();try{const lease=f.start(); f.advance(9000); f.state.tick(); assert.equal(f.state.current().state,'LIVE');assert.equal(f.state.authorityReady(lease.broadcast_id),false);}finally{f.close();}
});
test('A18/A38: recent events are partitioned before any context or summary assembly', () => {
  const f=fixture();try{f.start();const a=accept(f.state,viewer,'专属于甲的私事');accept(f.state,other,'专属于乙的私事');
    const context=JSON.parse(f.memory.context({...a,input_event_seq:99999},{revision:'test'}));
    assert.ok(JSON.stringify(context).includes('专属于甲'));assert.ok(!JSON.stringify(context).includes('专属于乙'));
  }finally{f.close();}
});
test('A19/A39: quoting real words cannot remove negation, time, or change the subject', () => {
  const source={event_id:'e1',event_seq:1,event_type:'input.accepted',text:'以前喜欢茶，现在不喝了',partition_key:'v'};
  const candidate={fact_key:'preference.drink',value:'tea',polarity:'positive',evidence_kind:'viewer_statement',source_refs:[{event_id:'e1',quote:'喜欢茶'}],validity:'persistent_candidate'};
  assert.equal(validateExtraction({schema_version:1,summary:'',open_questions:[],candidate_facts:[candidate]},[source],'v')[0].state,'proposed');
  assert.throws(()=>validateExtraction({schema_version:1,summary:'',open_questions:[],candidate_facts:[{...candidate,subject_key:'another'}]},[source],'v'),/SUBJECT_FORGED/);
  source.text='我喜欢茶。'; assert.equal(validateExtraction({schema_version:1,summary:'',open_questions:[],candidate_facts:[candidate]},[source],'v')[0].state,'active');
});
test('A20: repeated end has one closed watermark and one job per partition', () => {
  const f=fixture();try{f.start();accept(f.state);f.state.end(op);f.state.tick();const b=f.db.get('SELECT * FROM broadcasts');
    f.state.end(op);f.state.tick();assert.equal(f.db.get('SELECT COUNT(*) n FROM compaction_jobs').n,1);assert.equal(b.state,'ENDED');assert.ok(b.ended_event_seq);
  }finally{f.close();}
});
test('A21/A22: chunk results, facts, outbox, summary and cursor commit atomically; opening live revokes old worker', () => {
  const f=fixture();try{f.start();accept(f.state);f.state.end(op);f.state.tick();const scheduler=new MaintenanceScheduler(f.db,f.state,f.memory,f.policy,null);
    const job=scheduler.claim(),chunk=scheduler.chunk(job),result={schema_version:1,summary:'偏好',open_questions:[],candidate_facts:[{fact_key:'preference.drink',value:'tea',polarity:'positive',evidence_kind:'viewer_statement',source_refs:[{event_id:chunk.fresh[0].event_id,quote:'我喜欢茶。'}],validity:'persistent_candidate'}]};
    const candidates=validateExtraction(result,chunk.sources,job.partition_key);
    f.db.tx(()=>f.db.run("INSERT INTO job_chunks(job_id,chunk_index,input_sha256,source_start_seq,source_end_seq,state) VALUES (?,0,?,?,?,'PENDING')",job.job_id,chunk.inputHash,chunk.start,chunk.end));
    scheduler.commit(job,chunk,0,result,candidates);assert.equal(f.db.get('SELECT state FROM memory_entries').state,'active');assert.equal(f.db.get('SELECT consumed_through_seq FROM compaction_jobs').consumed_through_seq,chunk.end);
    f.state.createBroadcast(op);assert.throws(()=>scheduler.commit(job,chunk,0,result,candidates),/FENCED/);
  }finally{f.close();}
});
test('A26: opposite preference suspends certainty instead of latest-wins', () => {
  const f=fixture();try{f.start();const a=accept(f.state,viewer,'我喜欢茶。'),b=accept(f.state,viewer,'我喜欢咖啡。');
    const sources=f.memory.eligibleEvents(a.broadcast_id,viewer.viewer_id);
    const make=(source,value)=>validateExtraction({schema_version:1,summary:'',open_questions:[],candidate_facts:[{fact_key:'preference.drink',value,polarity:'positive',evidence_kind:'viewer_statement',source_refs:[{event_id:source.event_id,quote:source.text}],validity:'persistent_candidate'}]},[source],viewer.viewer_id)[0];
    f.db.tx(()=>f.memory.mergeInTransaction(make(sources[0],'tea'),'unit',0));
    f.db.tx(()=>f.memory.mergeInTransaction(make(sources[1],'coffee'),'unit',1));
    assert.equal(f.db.get("SELECT COUNT(*) n FROM memory_entries WHERE state='active'").n,0);assert.equal(f.db.get("SELECT COUNT(*) n FROM memory_entries WHERE state='conflicted'").n,2);
  }finally{f.close();}
});
