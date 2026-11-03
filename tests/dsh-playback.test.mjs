import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

function fixture() {
  const sent=[],audio={currentTime:0},transport={audioContext:audio,clearPlayback(){for(const source of sources){source._dshCancelled=true;source.stop();}}},sources=[];
  const scope={window:{streamUUID:()=>globalThis.crypto.randomUUID()},crypto:globalThis.crypto,performance:{now:()=>0},setInterval:()=>1,clearInterval(){},setTimeout,clearTimeout,AbortController};
  vm.runInNewContext(readFileSync(new URL('../web/dsh-playback.js',import.meta.url),'utf8'),scope);
  const player=new scope.window.DSHPlayback(transport);
  player.lease={lease_id:'lease',authority_epoch:1,runtime_epoch:1};
  player.send=(path,data)=>sent.push({path,...data});
  const source=()=>{let ended;const value={addEventListener(_name,fn){ended=fn},stop(){ended?.()},end(){ended?.()}};sources.push(value);return value;};
  const metadata={protocol:2,request_id:'r',utterance_id:'u',runtime_epoch:1,generation:2,valid_sample_count:640,transport_instance_id:'transport',ranges:[{packet_seq:1,sample_start:0,sample_count:640,packet_offset:0}],final:true};
  return {player,sent,audio,source,metadata,scope};
}
test('A08/A11: elapsed audio clock alone cannot acknowledge natural completion',()=>{
  const f=fixture(),s=f.source();f.player.schedule(s,f.metadata,1,640,16000);f.audio.currentTime=1.04;f.player.progress(f.player.utterances.get('u'));
  assert.equal(f.sent.at(-1).natural_end,false);s.end();assert.equal(f.sent.at(-1).natural_end,true);
});
test('A09/A10/A11: stop-generated ended remains interrupted with a partial sample prefix',()=>{
  const f=fixture(),s=f.source();f.player.schedule(s,f.metadata,1,640,16000);f.audio.currentTime=1.02;
  f.player.cancel({barrier_id:'c',request_id:'r',runtime_epoch:1,new_generation:3});
  assert.equal(f.sent.at(-1).path,'playback/cancel-ack');assert.equal(f.sent.at(-1).contiguous_played_samples,320);
  assert.equal(f.sent.some(x=>x.natural_end),false);f.audio.currentTime=3;s.end();f.player.progress(f.player.utterances.get('u'));assert.equal(f.sent.some(x=>x.natural_end),false);
});
test('A12: cancel before first map blocks a late old source even when its utterance is unknown',()=>{
  const f=fixture();f.player.cancel({barrier_id:'c',request_id:'r',runtime_epoch:1,new_generation:3});const s=f.source();f.player.schedule(s,f.metadata,1,640,16000);
  assert.equal(s._dshCancelled,true);assert.equal(f.player.utterances.size,0);
});
test('A13: preview has no acknowledgement authority',()=>{
  const f=fixture();f.player.lease=null;const s=f.source();f.player.schedule(s,f.metadata,1,640,16000);f.audio.currentTime=2;s.end();assert.equal(f.sent.length,0);
});
test('A11: a gap in mapped samples cannot produce natural completion',()=>{
  const f=fixture();f.metadata.ranges[0].sample_start=320;const s=f.source();f.player.schedule(s,f.metadata,1,640,16000);f.audio.currentTime=2;s.end();assert.equal(f.sent.some(x=>x.natural_end),false);
});

test('A14: a delayed cancel for the old epoch cannot acknowledge with the newly acquired lease',()=>{
  const f=fixture(),s=f.source();f.player.schedule(s,f.metadata,1,640,16000);f.audio.currentTime=1.02;
  f.player.lease={lease_id:'new-lease',authority_epoch:2,runtime_epoch:2};
  f.player.cancel({barrier_id:'old-cancel',request_id:'r',runtime_epoch:1,new_generation:3});
  assert.equal(s._dshCancelled,true);assert.equal(f.sent.length,0);assert.equal(f.player.lease.lease_id,'new-lease');
});

test('A14: an old heartbeat failure cannot revoke a replacement lease',async()=>{
  const f=fixture();f.player.send=Object.getPrototypeOf(f.player).send;
  f.player.api=async()=>{throw Error('PLAYBACK_LEASE_EXPIRED')};
  f.player.send('playback/heartbeat',{lease_id:'lease'});
  f.player.lease={lease_id:'new-lease',runtime_epoch:2};await f.player.postChain;
  assert.equal(f.player.lease.lease_id,'new-lease');
  f.player.send('playback/heartbeat',{lease_id:'new-lease'});await f.player.postChain;
  assert.equal(f.player.lease,null);
});

test('a new generation preserves silent idle media after a naturally completed turn',()=>{
  const f=fixture(),s=f.source();f.player.schedule(s,f.metadata,1,640,16000);f.audio.currentTime=2;s.end();
  assert.equal(f.player.utterances.get('u').naturalEnded,true);
  const idle=f.source();f.player.cancel({request_id:null,runtime_epoch:1,new_generation:3,reason:'generation_advanced'});
  assert.equal(idle._dshCancelled,undefined);
  assert.equal(f.player.fence.generation,3);
  const late=f.source();f.player.schedule(late,f.metadata,3,640,16000);assert.equal(late._dshCancelled,true);
});

test('a new generation still flushes unfinished speech even without a target request',()=>{
  const f=fixture(),s=f.source();f.player.schedule(s,f.metadata,1,640,16000);f.audio.currentTime=1.02;
  f.player.cancel({request_id:null,runtime_epoch:1,new_generation:3,reason:'generation_advanced'});
  assert.equal(s._dshCancelled,true);f.audio.currentTime=3;s.end();assert.equal(f.sent.some(x=>x.natural_end),false);
});

const readyLease=(player,broadcast='broadcast-ready',id='lease-ready')=>({lease_id:id,broadcast_id:broadcast,consumer_id:player.consumerId,authority_epoch:2,runtime_epoch:1,ready:false,expires_at:new Date(Date.now()+6000).toISOString()});

test('closing during a delayed claim prevents the returned authority from being installed',async()=>{
 const f=fixture();f.player.lease=null;let resolve;
 f.player.api=()=>new Promise(done=>{resolve=done});
 const pending=f.player.claim('broadcast-ready',false,{deferReady:true});
 f.player.close();resolve(readyLease(f.player));
 await assert.rejects(pending,/PLAYBACK_LEASE_CHANGED/);
 assert.equal(f.player.lease,null);assert.equal(f.player.ready,false);
});

test('a late older claim cannot replace the lease installed by a newer claim',async()=>{
 const f=fixture();f.player.lease=null;const pending=[];
 f.player.api=()=>new Promise(done=>pending.push(done));
 const old=f.player.claim('broadcast-old',false,{deferReady:true});
 const next=f.player.claim('broadcast-new',false,{deferReady:true});
 pending[1](readyLease(f.player,'broadcast-new','lease-new'));await next;
 pending[0](readyLease(f.player,'broadcast-old','lease-old'));await assert.rejects(old,/PLAYBACK_LEASE_CHANGED/);
 assert.equal(f.player.lease.lease_id,'lease-new');f.player.close();
});

test('pending authority cannot send played samples or heartbeats, and a mismatched ready response is rejected',async()=>{
 const f=fixture();f.player.lease=readyLease(f.player);const lease=f.player.lease;
 const source=f.source();f.player.schedule(source,f.metadata,1,640,16000);f.audio.currentTime=2;source.end();f.player.tick();
 assert.equal(f.sent.length,0);assert.equal(f.player.ready,false);
 f.player.api=async()=>({...lease,lease_id:'different-lease',ready:true});
 await assert.rejects(f.player.activate(),/PLAYBACK_LEASE_INVALID/);
 assert.equal(f.player.lease,lease);assert.equal(f.player.ready,false);f.player.close();
});

test('pending readiness expires locally without renewing itself',()=>{
 const f=fixture();f.player.lease=readyLease(f.player);f.player.leaseDeadline=0;let lost=false;
 f.player.transport.onAuthorityLost=()=>{lost=true};f.player.tick();
 assert.equal(f.player.lease,null);assert.equal(lost,true);assert.equal(f.sent.length,0);f.player.close();
});

test('playback HTTP timeout completes even when an underlying request ignores its abort signal',async()=>{
 const f=fixture();f.player.requestTimeoutMs=10;f.scope.fetch=()=>new Promise(()=>{});
 await assert.rejects(f.player.api('playback/ready',{}),/PLAYBACK_REQUEST_TIMEOUT/);
 assert.equal(f.player.requests.size,0);f.player.close();
});

test('closing aborts playback HTTP and its late response cannot restore the closed player',async()=>{
 const f=fixture();let finish;
 f.scope.fetch=()=>new Promise(done=>{finish=done});
 const request=f.player.api('playback/claim',{});f.player.close();
 await assert.rejects(request,/PLAYBACK_CLOSED/);
 finish({ok:true,json:async()=>readyLease(f.player)});
 assert.equal(f.player.requests.size,0);assert.equal(f.player.lease,null);
 await assert.rejects(f.player.api('playback/ready',{}),/PLAYBACK_CLOSED/);
});
