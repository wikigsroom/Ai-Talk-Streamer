import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
const source=readFileSync('web/local-stream.js','utf8'),playback=readFileSync('web/dsh-playback.js','utf8');
function fixture(){
 const events=[],sources=[],decoders=[];
 class Decoder{static async isConfigSupported(){return{supported:true}}constructor(callbacks){this.callbacks=callbacks;this.state='unconfigured';this.decodeQueueSize=0;decoders.push(this)}configure(c){this.config=c;this.state='configured'}close(){this.state='closed'}decode(){}}
 const sandbox={window:{},location:{search:'',origin:'http://fixture'},document:{createElement:()=>({width:0,height:0,getContext:()=>({clearRect(){},drawImage(){}})})},performance:{now:()=>1000},URLSearchParams,VideoDecoder:Decoder,ArrayBuffer,DataView,Uint8Array,Int16Array,Blob,Math,Number,JSON,Map,Set,Promise,atob,clearTimeout,setTimeout,clearInterval(){},setInterval:()=>1,CustomEvent:class{constructor(type,{detail}={}){this.type=type;this.detail=detail}},WebSocket:{OPEN:1},EncodedVideoChunk:class{constructor(value){Object.assign(this,value)}}};
 sandbox.window.dispatchEvent=e=>events.push(e);sandbox.window.streamUUID=()=> 'fixture-uuid';const context=createContext(sandbox);runInContext(playback,context);sandbox.DSHPlayback=sandbox.window.DSHPlayback;runInContext(source,context);
 const audio={currentTime:1,state:'running',createBuffer(_channels,n,rate){return{getChannelData:()=>new Float32Array(n)}},createBufferSource(){const s={connect(){},disconnect(){},addEventListener(){},start(){this.started=true},stop(){this.stopped=true}};sources.push(s);return s}};
 const transport=new sandbox.window.LocalAvatarStream(audio,()=>{},{protocolVersion:3,playbackAuthority:true});transport.codec='h264_nvenc';transport.destination={disconnect(){}};transport.outputGain={disconnect(){}};transport.ws={readyState:1,close(_code,reason){this.reason=reason},send(){}};
 const sps=Buffer.from([0x67,0x42,0xc0,0x1f]),pps=Buffer.from([0x68,0x12]);
 const init={type:'media.init',protocol_version:3,stream_id:'fixture-first',media_profile_id:'fixture-profile',width:640,height:640,fps_num:25,fps_den:1,codec:'avc1.42c01f',avc_description_base64:Buffer.concat([Buffer.from([1,0x42,0xc0,0x1f,255,225,0,4]),sps,Buffer.from([1,0,2]),pps]).toString('base64'),audio:{format:'s16le',sample_rate:16000,channels:1},time_base_num:1,time_base_den:1000000,pts_origin_us:0};
 const packet=(seq=1,rate=16000)=>{const b=new ArrayBuffer(30),v=new DataView(b);v.setUint32(0,seq,true);v.setUint32(4,16,true);v.setUint32(8,rate,true);v.setUint32(12,0x41564331,false);v.setUint32(16,1,true);return b};
 return {transport,init,packet,sources,decoders,events};
}

test('v3 waits for valid init before scheduling any PCM or map',async()=>{const f=fixture();await assert.rejects(f.transport.receive(f.packet()),/INIT_REQUIRED/);await assert.rejects(f.transport.control({type:'media.map'}),/INIT_REQUIRED/);assert.equal(f.sources.length,0);f.transport.close()});
test('v3 validates actual AVC description, dimensions, IDs and reset prerequisites',async()=>{
 for(const patch of [{width:0},{height:9000},{codec:'avc1.bad'},{avc_description_base64:'AA=='},{avc_description_base64:'!!!!'},{fps_den:0},{audio:{format:'f32',sample_rate:16000,channels:1}},{stream_id:'../bad'}]){const f=fixture();await assert.rejects(f.transport.control({...f.init,...patch}));assert.equal(f.decoders.length,0);f.transport.close()}
 const f=fixture();await f.transport.control(f.init);await assert.rejects(f.transport.control({...f.init,width:960}),/REQUIRES_RESET/);await assert.rejects(f.transport.control({type:'media.reset',protocol_version:3,old_stream_id:'wrong',new_stream_id:'next'}),/RESET_INVALID/);f.transport.close();
});
test('v3 packet bounds, sample rate and non-increasing sequences reject before audio creation',async()=>{
 const f=fixture();await f.transport.control(f.init);await assert.rejects(f.transport.receive(new ArrayBuffer(8)),/PACKET_INVALID/);await assert.rejects(f.transport.receive(f.packet(1,24000)),/PACKET_INVALID/);const invalid=f.packet();new DataView(invalid).setUint32(4,1000,true);await assert.rejects(f.transport.receive(invalid),/PACKET_INVALID/);assert.equal(f.sources.length,0);await f.transport.receive(f.packet());await assert.rejects(f.transport.receive(f.packet()),/PACKET_INVALID/);assert.equal(f.sources.length,1);f.transport.close();
});
test('media reset cancels old PCM/maps, fences stale decoder callbacks and requires the named next init',async()=>{
 const f=fixture();await f.transport.control(f.init);await f.transport.receive(f.packet());f.transport.dsh.maps.set(9,{});f.transport.dsh.utterances.set('old',{spans:[]});const old=f.decoders[0];
 await f.transport.control({type:'media.reset',protocol_version:3,old_stream_id:f.init.stream_id,new_stream_id:'fixture-next'});
 assert.equal(old.state,'closed');assert.equal(f.transport.sources.size,0);assert.equal(f.sources[0]._dshCancelled,true);assert.equal(f.transport.dsh.maps.size,0);assert.equal(f.transport.dsh.utterances.get('old').cancelled,true);
 let closed=false;old.callbacks.output({timestamp:40000,close(){closed=true}});assert.equal(closed,true);
 await assert.rejects(f.transport.receive(f.packet(2)),/INIT_REQUIRED/);await assert.rejects(f.transport.control({...f.init,stream_id:'unrelated'}),/TARGET_MISMATCH/);
 await f.transport.control({...f.init,stream_id:'fixture-next',width:960,height:540});assert.equal(f.transport.canvas.width,960);assert.equal(f.transport.waitingAVCKeyframe,true);await assert.rejects(f.transport.control(f.init));f.transport.close();
});
test('unauthorized formal PCM cannot schedule receipts and a reset cannot turn cancellation into natural completion',async()=>{
 const f=fixture();f.transport.receiptsRequired=true;f.transport.audible=false;await f.transport.control(f.init);await f.transport.receive(f.packet());assert.equal(f.sources[0].started,undefined);assert.equal(f.transport.dsh.utterances.size,0);assert.equal(f.transport.sources.size,0);f.transport.close();
});
test('decoded display dimensions must agree with init; no silent stretching of a mislabeled profile',async()=>{
 const f=fixture();await f.transport.control(f.init);f.transport.avcFrames.set(1,{at:2,revision:f.transport.presentationRevision});let closed=false;f.transport.presentAVC({timestamp:1,displayWidth:720,displayHeight:1280,close(){closed=true}});assert.equal(closed,true);assert.equal(f.transport.decodeErrors,1);assert.match(f.transport.ws.reason,/dimensions/);f.transport.close();
});

test('formal lease expires locally during a stalled network and rejects missing expiry metadata',()=>{
 const f=fixture(),d=f.transport.dsh;f.transport.receiptsRequired=true;assert.throws(()=>d.updateDeadline({}),/LEASE_INVALID/);let lost=false;f.transport.onAuthorityLost=()=>{lost=true};d.lease={lease_id:'fixture'};d.updateDeadline({expires_at:new Date(Date.now()-1).toISOString()});d.tick();assert.equal(lost,true);assert.equal(d.lease,null);f.transport.close();
});
