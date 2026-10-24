'use strict';
class LocalAvatarStream {
 constructor(audioContext,onClose){
  this.audioContext=audioContext;this.onClose=onClose;
  this.canvas=document.createElement('canvas');this.canvas.width=720;this.canvas.height=1280;
  this.context=this.canvas.getContext('2d',{alpha:false});
  this.timers=new Map();this.sources=new Set();this.running=true;this.next=0;
  this.frames=0;this.receivedFrames=0;this.presentedFrames=0;this.samples=0;this.energy=0;
  this.previousFrames=0;this.previousTime=performance.now();this.fps=0;
  this.decode=Promise.resolve();this.pendingDecodes=0;this.skippedVideo=0;this.decodeErrors=0;
  this.audioUnderruns=0;this.missingPackets=0;this.serverSkippedVideo=0;this.lastSequence=null;this.lastArrival=null;this.maxArrivalGap=0;
  this.bufferSeconds=2.4;this.imageTimers=new Set();this.video=null;this.videoCallback=null;
  this.presentationRevision=0;this.dsh=window.DSHPlayback?new DSHPlayback(this):null;
 }
 async connect(){
  await this.audioContext.resume();this.destination=this.audioContext.createMediaStreamDestination();
  this.stream=this.canvas.captureStream(0);this.videoTrack=this.stream.getVideoTracks()[0];
  if(typeof this.videoTrack.requestFrame!=='function'){
   this.videoTrack.stop();this.stream=this.canvas.captureStream(25);this.videoTrack=this.stream.getVideoTracks()[0];
  }
  this.stream.addTrack(this.destination.stream.getAudioTracks()[0]);
  await new Promise((resolve,reject)=>{
   let settled=false;const finish=error=>{if(settled)return;settled=true;clearTimeout(timeout);error?reject(error):resolve()};
   const timeout=setTimeout(()=>finish(Error('人物准备超过三分钟，请检查服务后重试。')),180000);this.ws=new WebSocket(location.origin.replace(/^http/,'ws')+'/api/studio/stream?v=2');this.ws.binaryType='arraybuffer';
   this.ws.onmessage=event=>{if(typeof event.data==='string'){try{this.dsh?.control(JSON.parse(event.data))}catch{finish(Error('音视频状态协议异常。'))}return}this.receive(event.data).then(()=>finish()).catch(error=>finish(error))};
   this.ws.onerror=()=>finish(Error('本地音视频连接未建立。'));
   this.ws.onclose=()=>{finish(Error('人物画面连接已关闭。'));if(this.running)this.onClose?.()};
  });
  return this.stream;
 }
 attachVideo(video){
  if(this.video&&this.videoCallback!==null)this.video.cancelVideoFrameCallback?.(this.videoCallback);
  this.video=video;this.presentedFrames=0;this.previousFrames=0;this.previousTime=performance.now();this.fps=0;
  if(!video.requestVideoFrameCallback)return;
  const presented=()=>{if(!this.running||this.video!==video)return;this.presentedFrames++;this.videoCallback=video.requestVideoFrameCallback(presented)};
  this.videoCallback=video.requestVideoFrameCallback(presented);
 }
 async receive(packet){
  if(!this.running)return;
  const header=new DataView(packet),sequence=header.getUint32(0,true),length=header.getUint32(4,true),rate=header.getUint32(8,true);
  const metadata=this.dsh?.take(sequence);
  const arrival=performance.now();
  if(this.lastArrival!==null)this.maxArrivalGap=Math.max(this.maxArrivalGap,arrival-this.lastArrival);
  this.lastArrival=arrival;this.receivedFrames++;
  if(this.lastSequence!==null)this.missingPackets+=Math.max(0,sequence-this.lastSequence-1);
  this.lastSequence=sequence;
  // Schedule PCM immediately; JPEG decoding must not hold back sound.
  const pcm=new Int16Array(packet.slice(12+length)),buffer=this.audioContext.createBuffer(1,pcm.length,rate),data=buffer.getChannelData(0);let energy=0;
  for(let i=0;i<pcm.length;i++){data[i]=pcm[i]/32768;energy+=data[i]*data[i]}
  const now=this.audioContext.currentTime;
  if(!this.next||this.next<now-.000001){if(this.next)this.audioUnderruns++;this.next=now+this.bufferSeconds}
  const at=this.next;this.next+=pcm.length/rate;
  const source=this.audioContext.createBufferSource();source.buffer=buffer;source.connect(this.destination);this.sources.add(source);source.onended=()=>{this.sources.delete(source);source.disconnect()};source.start(at);
  this.dsh?.schedule(source,metadata,at,pcm.length,rate);
  this.samples+=pcm.length;this.energy+=energy/rate;
  if(!length){this.serverSkippedVideo++;return}
  // Keep compressed pictures until close to playout, rather than retaining
  // seconds of decoded 720x1280 bitmaps in the viewing computer's memory.
  const delay=(at-this.audioContext.currentTime-.12)*1000;
  if(delay>0){const timer=setTimeout(()=>{this.imageTimers.delete(timer);this.enqueuePicture(packet,at)},delay);this.imageTimers.add(timer);return}
  await this.enqueuePicture(packet,at);
 }
 async enqueuePicture(packet,at){
  if(!this.running)return;
  const presentationRevision=this.presentationRevision;
  const length=new DataView(packet).getUint32(4,true);
  // Bound picture work while preserving every audio chunk on a busy viewing PC.
  if(this.pendingDecodes>=4){this.skippedVideo++;return}
  this.pendingDecodes++;
  this.decode=this.decode.then(async()=>{
   if(!this.running)return;
   // Skip expired work before spending time decoding it, allowing the decoder
   // to catch up to fresh pictures after a viewing-computer CPU stall.
   if(at<this.audioContext.currentTime-.04){this.skippedVideo++;return}
   const picture=await createImageBitmap(new Blob([packet.slice(12,12+length)],{type:'image/jpeg'}));
   if(!this.running||this.presentationRevision!==presentationRevision){picture.close();return}
   if(at<this.audioContext.currentTime-.12){picture.close();this.skippedVideo++;return}
   const timer=setTimeout(()=>{
    this.timers.delete(timer);
    if(this.running&&this.presentationRevision===presentationRevision){
     if(this.canvas.width!==picture.width||this.canvas.height!==picture.height){this.canvas.width=picture.width;this.canvas.height=picture.height}
     this.context.drawImage(picture,0,0,this.canvas.width,this.canvas.height);
     // Capture this draw explicitly; another 25 Hz sampler can miss frames.
     this.videoTrack.requestFrame?.();this.frames++;
    }
    picture.close();
   },Math.max(0,(at-this.audioContext.currentTime)*1000));
   this.timers.set(timer,picture);
  }).catch(()=>{this.decodeErrors++}).finally(()=>{this.pendingDecodes--});
  await this.decode;
 }
 metrics(){
  const now=performance.now(),usesPresentation=!!this.video?.requestVideoFrameCallback,count=usesPresentation?this.presentedFrames:this.frames;
  if(now-this.previousTime>=800){this.fps=(count-this.previousFrames)/(now-this.previousTime)*1000;this.previousFrames=count;this.previousTime=now}
  return {frames:this.frames,received_frames:this.receivedFrames,presented_frames:usesPresentation?this.presentedFrames:null,fps:this.fps,fps_source:usesPresentation?'video_presentation':'canvas_draw',width:this.canvas.width,height:this.canvas.height,audio_samples:this.samples,audio_energy:this.energy,audio_underruns:this.audioUnderruns,target_audio_buffer_ms:this.bufferSeconds*1000,audio_buffer_ms:Math.max(0,(this.next-this.audioContext.currentTime)*1000),missing_packets:this.missingPackets,server_skipped_video_frames:this.serverSkippedVideo,skipped_video_frames:this.skippedVideo,decode_errors:this.decodeErrors,max_arrival_gap_ms:this.maxArrivalGap,connected:this.ws?.readyState===WebSocket.OPEN};
 }
 close(){
  this.dsh?.close();this.clearPlayback();
  this.running=false;this.ws?.close();
  if(this.video&&this.videoCallback!==null)this.video.cancelVideoFrameCallback?.(this.videoCallback);
  for(const timer of this.imageTimers)clearTimeout(timer);this.imageTimers.clear();
  for(const [timer,picture] of this.timers){clearTimeout(timer);picture.close()}this.timers.clear();
  for(const source of this.sources)try{source.stop()}catch{}
  this.stream?.getTracks().forEach(track=>track.stop());this.destination?.disconnect();
 }
 clearPlayback(){
  this.presentationRevision++;this.next=0;
  for(const timer of this.imageTimers)clearTimeout(timer);this.imageTimers.clear();
  for(const [timer,picture] of this.timers){clearTimeout(timer);picture.close()}this.timers.clear();
  for(const source of this.sources){source._dshCancelled=true;try{source.stop()}catch{}}this.sources.clear();
 }
}
window.LocalAvatarStream=LocalAvatarStream;
