'use strict';
class DSHPlayback {
 constructor(transport){
  this.transport=transport;this.audio=transport.audioContext;this.consumerId='browser-'+window.streamUUID();
  this.maps=new Map();this.utterances=new Map();this.lease=null;this.receiptSequence=0;this.postChain=Promise.resolve();
  this.heartbeatMs=1000;this.lastHeartbeat=0;this.closed=false;this.timer=setInterval(()=>this.tick(),250);this.lastError=null;
  this.fence={runtime_epoch:0,generation:0};
  this.requests=new Set();this.claimVersion=0;this.requestTimeoutMs=6000;
 }
 async api(path,data){
  if(this.closed)throw Error('PLAYBACK_CLOSED');
  const controller=new AbortController();this.requests.add(controller);
  let rejectAbort;
  const aborted=new Promise((_,reject)=>{rejectAbort=()=>reject(Error(this.closed?'PLAYBACK_CLOSED':'PLAYBACK_REQUEST_TIMEOUT'));controller.signal.addEventListener('abort',rejectAbort,{once:true})});
  const timer=setTimeout(()=>controller.abort(),this.requestTimeoutMs);
  try{return await Promise.race([(async()=>{const response=await fetch('/api/dsh/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal:controller.signal});const value=await response.json();if(controller.signal.aborted)throw Error(this.closed?'PLAYBACK_CLOSED':'PLAYBACK_REQUEST_TIMEOUT');if(!response.ok)throw Error(value.error||'DSH_REQUEST_FAILED');return value})(),aborted])}
  finally{clearTimeout(timer);controller.signal.removeEventListener('abort',rejectAbort);this.requests.delete(controller)}
 }
 get ready(){return !this.closed&&!!this.lease&&this.lease.ready!==false}
 async claim(broadcastId,replace=false,{deferReady=false}={}){
  const version=++this.claimVersion,previous=this.lease;
  const lease=await this.api('playback/claim',{broadcast_id:broadcastId,consumer_id:this.consumerId,replace,...(deferReady?{defer_ready:true}:{})});
  if(this.closed||version!==this.claimVersion)throw Error('PLAYBACK_LEASE_CHANGED');
  if(!lease||typeof lease.lease_id!=='string'||lease.broadcast_id!==broadcastId||lease.consumer_id!==this.consumerId||!Number.isSafeInteger(lease.authority_epoch)||lease.authority_epoch<1||!Number.isSafeInteger(lease.runtime_epoch)||lease.runtime_epoch<1)throw Error('PLAYBACK_LEASE_INVALID');
  if(deferReady&&(typeof lease.ready!=='boolean'||lease.ready&&previous?.lease_id!==lease.lease_id))throw Error('PLAYBACK_READY_PROTOCOL_REQUIRED');
  this.updateDeadline(lease);
  if(previous&&previous.lease_id!==lease.lease_id){this.resetMedia();this.transport.clearPlayback()}
  this.lease=lease;const timing=lease.playback_timing;if(timing){this.heartbeatMs=timing.heartbeat_interval_ms;clearInterval(this.timer);this.timer=setInterval(()=>this.tick(),timing.progress_interval_ms)}this.lastHeartbeat=0;return lease;
 }
 async activate(){
  const lease=this.lease,version=this.claimVersion;if(!lease||this.closed)throw Error('PLAYBACK_LEASE_CHANGED');if(lease.ready!==false)return lease;
  const value=await this.api('playback/ready',{lease_id:lease.lease_id,consumer_id:this.consumerId});
  if(this.closed||version!==this.claimVersion||this.lease!==lease)throw Error('PLAYBACK_LEASE_CHANGED');
  if(!value||value.ready!==true||['lease_id','consumer_id','broadcast_id','authority_epoch','runtime_epoch'].some(key=>value[key]!==lease[key]))throw Error('PLAYBACK_LEASE_INVALID');
  this.updateDeadline(value);this.lease={...lease,...value};this.lastHeartbeat=0;return this.lease;
 }
 updateDeadline(value){const expiry=Date.parse(value.expires_at);if(!Number.isFinite(expiry)&&this.transport.receiptsRequired)throw Error('PLAYBACK_LEASE_INVALID');this.leaseDeadline=Number.isFinite(expiry)?performance.now()+Math.max(0,expiry-(window.roomClient?.now()||Date.now())):Infinity}
 control(message){
  if(message.type==='media.map'){
   if(message.protocol!==2||!Array.isArray(message.ranges))throw Error('MEDIA_PROTOCOL_INVALID');
   const seq=message.ranges[0]?.packet_seq;if(!Number.isSafeInteger(seq))throw Error('MEDIA_MAP_INVALID');
   this.maps.set(seq,message);if(this.maps.size>250)throw Error('MEDIA_MAP_BACKLOG');
  }else if(message.type==='playback.cancel')this.cancel(message);
 }
 take(sequence){const value=this.maps.get(sequence);this.maps.delete(sequence);return value;}
 schedule(source,metadata,at,pcmSamples,rate){
  if(!metadata||source._dshCancelled)return;
  if(metadata.runtime_epoch<this.fence.runtime_epoch||metadata.runtime_epoch===this.fence.runtime_epoch&&metadata.generation<this.fence.generation){source._dshCancelled=true;try{source.stop()}catch{}return;}
  let utterance=this.utterances.get(metadata.utterance_id);
  if(!utterance){utterance={...metadata,spans:[],enqueued:0,played:0,lastSent:0,final:false,cancelled:false,lost:false,naturalEnded:false};this.utterances.set(metadata.utterance_id,utterance);}
  if(utterance.cancelled){source._dshCancelled=true;try{source.stop()}catch{}return;}
  const spans=[];
  for(const range of metadata.ranges){
   if(range.sample_start!==utterance.enqueued||range.packet_offset<0||range.packet_offset+range.sample_count>pcmSamples){utterance.lost=true;continue;}
   const span={sampleStart:range.sample_start,count:range.sample_count,start:at+range.packet_offset/rate,end:at+(range.packet_offset+range.sample_count)/rate,rate,source,ended:false};
   utterance.spans.push(span);spans.push(span);utterance.enqueued+=range.sample_count;
  }
  if(metadata.final)utterance.final=true;
  source.addEventListener('ended',()=>{
   if(source._dshCancelled||utterance.cancelled)return;
   spans.forEach(span=>{span.ended=true});
   if(utterance.final&&utterance.spans.every(span=>span.ended))this.progress(utterance);
  },{once:true});
  while(this.utterances.size>5){const first=this.utterances.keys().next().value;if(first===metadata.utterance_id)break;this.utterances.delete(first);}
 }
 prefix(utterance){
  let through=0;const now=this.audio.currentTime;
  for(const span of utterance.spans){
   if(span.sampleStart!==through)break;
   const played=Math.max(0,Math.min(span.count,Math.floor((now-span.start)*span.rate+0.001)));
   through+=played;if(played<span.count)break;
  }
  return Math.min(utterance.valid_sample_count,Math.max(utterance.played,through));
 }
 send(path,data){
  this.postChain=this.postChain.then(()=>this.closed?null:this.api(path,data)).then(value=>{
   if(value&&value.accepted===false)this.lastError=value.reason;
   if(value&&path==='playback/heartbeat'&&this.lease?.lease_id===data.lease_id)this.updateDeadline(value);
   return value;
  }).catch(error=>{this.lastError=error.message;if(/LEASE|AUTHORITY|OPERATOR/.test(error.message)&&this.lease?.lease_id===data.lease_id){this.lease=null;this.transport.onAuthorityLost?.()}});
 }
 progress(utterance){
  const lease=this.lease;if(!this.ready||utterance.cancelled||utterance.runtime_epoch!==lease.runtime_epoch)return;
  utterance.played=this.prefix(utterance);
  const natural=!utterance.lost&&utterance.final&&utterance.enqueued===utterance.valid_sample_count&&utterance.played===utterance.valid_sample_count&&utterance.spans.every(span=>span.ended);
  if(utterance.played===utterance.lastSent&&!natural||utterance.naturalEnded)return;
  utterance.lastSent=utterance.played;if(natural)utterance.naturalEnded=true;
  this.send('playback/receipt',{receipt_id:window.streamUUID(),utterance_id:utterance.utterance_id,consumer_id:this.consumerId,lease_id:lease.lease_id,
   authority_epoch:lease.authority_epoch,runtime_epoch:utterance.runtime_epoch,generation:utterance.generation,receipt_sequence:++this.receiptSequence,
   contiguous_played_samples:utterance.played,natural_end:natural,transport_instance_id:utterance.transport_instance_id});
 }
 cancel(barrier){
  if(barrier.runtime_epoch>this.fence.runtime_epoch||barrier.runtime_epoch===this.fence.runtime_epoch&&barrier.new_generation>this.fence.generation)this.fence={runtime_epoch:barrier.runtime_epoch,generation:barrier.new_generation};
  let target=null;
  for(const utterance of this.utterances.values())if(utterance.request_id===barrier.request_id){utterance.played=this.prefix(utterance);utterance.cancelled=true;target=utterance;}
  // Starting the next turn after natural completion must not freeze an idle
  // picture for another full jitter-buffer interval. Reuse only silent queued
  // media; interruption or any unfinished speech still clears everything.
  const idleTransition=barrier.reason==='generation_advanced'&&barrier.request_id===null&&[...this.utterances.values()].every(u=>u.naturalEnded||u.cancelled);
  if(!idleTransition)this.transport.clearPlayback();this.maps.clear();
  if(this.lease&&target&&this.lease.runtime_epoch===barrier.runtime_epoch&&target.runtime_epoch===this.lease.runtime_epoch)this.send('playback/cancel-ack',{barrier_id:barrier.barrier_id,lease_id:this.lease.lease_id,consumer_id:this.consumerId,
   transport_instance_id:target.transport_instance_id,contiguous_played_samples:target.played});
 }
 tick(){
  if(this.closed||!this.lease)return;
  if(performance.now()>=this.leaseDeadline){this.lease=null;this.transport.onAuthorityLost?.();return}
  if(!this.ready)return;
  if(performance.now()-this.lastHeartbeat>=this.heartbeatMs){this.lastHeartbeat=performance.now();this.send('playback/heartbeat',{lease_id:this.lease.lease_id,consumer_id:this.consumerId});}
  for(const utterance of this.utterances.values())this.progress(utterance);
 }
 metrics(){return {authority:this.ready,authority_held:!!this.lease,ready:this.ready,pending_requests:this.requests.size,consumer_id:this.consumerId,lease_id:this.lease?.lease_id||null,playback_error:this.lastError,
  utterances:[...this.utterances.values()].map(u=>({utterance_id:u.utterance_id,played_samples:u.played,valid_sample_count:u.valid_sample_count,natural_end:u.naturalEnded,cancelled:u.cancelled,lost:u.lost}))};}
 resetMedia(){this.maps.clear();for(const utterance of this.utterances.values()){utterance.cancelled=true;utterance.lost=true}}
 close(){this.closed=true;this.claimVersion++;for(const controller of this.requests)controller.abort();clearInterval(this.timer);this.lease=null;this.maps.clear();for(const utterance of this.utterances.values())utterance.cancelled=true;}
}
window.DSHPlayback=DSHPlayback;
