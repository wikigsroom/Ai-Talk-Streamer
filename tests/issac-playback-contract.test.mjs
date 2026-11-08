import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {StateStore} from '../backend/memory/store.mjs';
import {StreamState} from '../backend/dsh-bridge/state.mjs';
import {StreamBridge} from '../backend/dsh-bridge/server.mjs';
import {loadPolicy} from '../backend/dsh-bridge/policy.mjs';
import {digest} from '../backend/dsh-bridge/channel.mjs';

const operator={role:'operator',principal_id:'test-op',viewer_id:'test-viewer'};
function fixture(){
 let now=Date.now();const db=new StateStore(':memory:',{now:()=>now,heartbeat:false});
 const policy=structuredClone(loadPolicy(process.cwd()));policy.deployment.state_relative_path='state/issac-stream';
 const state=new StreamState(db,policy,'naimei-test');
 return {db,state,policy,now:()=>now,advance(ms){db.tx(()=>db.run('UPDATE bridge_owner SET lease_until=?',now+ms+30000));now+=ms}};
}

test('actual Isaac browser and HTTP bridge prepare, renew and complete one lease',async()=>{
 const f=fixture(),bridge=Object.create(StreamBridge.prototype);
 Object.assign(bridge,{db:f.db,state:f.state,policy:f.policy,auth:{resolve:()=>operator},
  platforms:{player:{consumer_id:'browser-contract',programme:'issac',at:Date.now()}},tick:async()=>{}});
 const server=createServer((req,res)=>bridge.handle(req,res));
 let player;
 try{
  await new Promise(done=>server.listen(0,'127.0.0.1',done));const base='http://127.0.0.1:'+server.address().port;
  const audio={currentTime:0},transport={audioContext:audio,receiptsRequired:true,clearPlayback(){}};
  const scope={window:{streamUUID:()=> 'contract',roomClient:{now:f.now}},
   performance:{now:f.now},setInterval:()=>1,clearInterval(){},setTimeout,clearTimeout,AbortController,
   fetch:(path,options)=>fetch(base+path,options)};
  vm.runInNewContext(readFileSync(new URL('../web/issac/dsh-playback.js',import.meta.url),'utf8'),scope);
  player=new scope.window.DSHPlayback(transport);const broadcast=f.state.createBroadcast(operator);
  const lease=await player.claim(broadcast.broadcast_id,false,{deferReady:true});
  assert.equal(lease.ready,false);assert.equal(f.state.authorityReady(broadcast.broadcast_id),false);
  assert.throws(()=>f.state.readyBroadcast(broadcast.broadcast_id,true),/DEPENDENCIES_NOT_READY/);
  assert.throws(()=>f.state.claimAuthority(operator,broadcast.broadcast_id,'second-browser',false,true),/AUTHORITY_ALREADY_HELD/);
  assert.equal(f.state.claimAuthority(operator,broadcast.broadcast_id,player.consumerId,false,true).lease_id,lease.lease_id);
  await player.activate();assert.equal(player.ready,true);assert.equal(f.state.authorityReady(broadcast.broadcast_id),true);
  f.state.readyBroadcast(broadcast.broadcast_id,true);
  for(let i=0;i<12;i++){
   f.advance(2000);player.tick();await player.postChain;
   assert.equal(player.lastError,null);assert.equal(f.state.authorityReady(broadcast.broadcast_id),true);
  }
  assert.equal(f.db.get('SELECT COUNT(*) n FROM playback_history').n,1);
  f.state.accept(operator,{mode:'echo',text:'奶妹的播放协议检查。',idempotency_key:'actual-browser-contract'});
  const request=f.state.activate(),utterance=f.state.textReady(request.request_id,'这句需要实际播完。',request.runtime_epoch,request.generation);
  f.state.audioReady({...utterance,valid_sample_count:640,audio_sha256:digest('fixture-generated-audio')});
  const metadata={...utterance,protocol:2,valid_sample_count:640,transport_instance_id:'contract-wire',
   ranges:[{packet_seq:1,packet_offset:0,sample_start:0,sample_count:640}],final:true};
  f.state.mediaMap(metadata);player.control({type:'media.map',...metadata});
  let ended;const source={addEventListener(_name,callback){ended=callback}};
  player.schedule(source,player.take(1),1,640,16000);audio.currentTime=1.04;ended();await player.postChain;
  assert.equal(player.lastError,null);assert.equal(f.state.request(request.request_id).status,'COMPLETED');
  assert.equal(f.db.get("SELECT COUNT(*) n FROM stream_events WHERE event_type='playback.completed'").n,1);
  // Repeated preparation acknowledges the same lease without new epochs/events.
  await player.activate();assert.equal(f.db.get("SELECT COUNT(*) n FROM stream_events WHERE event_type='playback.authority_ready'").n,1);
 }finally{player?.close();server.closeAllConnections();await new Promise(done=>server.close(done));f.db.close()}
});

test('pending playback cannot be readied by a foreign consumer, after expiry or after restart',()=>{
 const f=fixture();try{
  const b=f.state.createBroadcast(operator),lease=f.state.claimAuthority(operator,b.broadcast_id,'browser-original',false,true);
  assert.throws(()=>f.state.activateAuthority(lease.lease_id,'browser-foreign'),/PLAYBACK_LEASE_EXPIRED/);
  f.advance(f.policy.playback.lease_timeout_ms+1);
  assert.throws(()=>f.state.activateAuthority(lease.lease_id,lease.consumer_id),/PLAYBACK_LEASE_EXPIRED/);
  const replacement=f.state.claimAuthority(operator,b.broadcast_id,'browser-original',false,true);
  assert.notEqual(lease.lease_id,replacement.lease_id);
  new StreamState(f.db,f.policy,'naimei-test');
  assert.throws(()=>f.state.activateAuthority(replacement.lease_id,replacement.consumer_id),/PLAYBACK_LEASE_EXPIRED/);
 }finally{f.db.close()}
});
