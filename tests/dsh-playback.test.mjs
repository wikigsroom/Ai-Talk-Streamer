import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

function fixture() {
  const sent=[],audio={currentTime:0},transport={audioContext:audio,clearPlayback(){for(const source of sources){source._dshCancelled=true;source.stop();}}},sources=[];
  const scope={window:{streamUUID:()=>globalThis.crypto.randomUUID()},crypto:globalThis.crypto,performance:{now:()=>0},setInterval:()=>1,clearInterval(){}};
  vm.runInNewContext(readFileSync(new URL('../web/dsh-playback.js',import.meta.url),'utf8'),scope);
  const player=new scope.window.DSHPlayback(transport);
  player.lease={lease_id:'lease',authority_epoch:1,runtime_epoch:1};
  player.send=(path,data)=>sent.push({path,...data});
  const source=()=>{let ended;const value={addEventListener(_name,fn){ended=fn},stop(){ended?.()},end(){ended?.()}};sources.push(value);return value;};
  const metadata={protocol:2,request_id:'r',utterance_id:'u',runtime_epoch:1,generation:2,valid_sample_count:640,transport_instance_id:'transport',ranges:[{packet_seq:1,sample_start:0,sample_count:640,packet_offset:0}],final:true};
  return {player,sent,audio,source,metadata};
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
