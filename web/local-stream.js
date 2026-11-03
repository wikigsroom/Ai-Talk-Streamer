'use strict';
class LocalAvatarStream {
 constructor(audioContext,onClose,{directOutput=false,protocolVersion=2,playbackAuthority=true,audible=new URLSearchParams(location.search).get('renderer')!=='preview',receiptsRequired=false}={}){
  this.audioContext=audioContext;this.onClose=onClose;this.directOutput=directOutput;
  this.protocolVersion=protocolVersion;this.audible=audible;this.receiptsRequired=receiptsRequired;
  this.mediaInit=null;this.pendingStream=null;this.retiredStreams=new Set();this.incoming=Promise.resolve();
  this.canvas=document.createElement('canvas');this.canvas.width=720;this.canvas.height=1280;
  this.context=this.canvas.getContext('2d',{alpha:false});
  this.timers=new Map();this.sources=new Set();this.running=true;this.next=0;
  this.frames=0;this.receivedFrames=0;this.presentedFrames=0;this.samples=0;this.energy=0;
  this.previousFrames=0;this.previousTime=performance.now();this.fps=0;
  this.decode=Promise.resolve();this.pendingDecodes=0;this.skippedVideo=0;this.decodeErrors=0;
  this.audioUnderruns=0;this.missingPackets=0;this.serverSkippedVideo=0;this.lastSequence=null;this.lastArrival=null;this.maxArrivalGap=0;
  // A VPN can pause for seconds even when its average throughput is adequate.
  // Preserve every PCM sample; the split receiver trades 4 s of delay for continuity.
  const requestedBuffer=Number(new URLSearchParams(location.search).get('buffer_ms'));
  this.bufferSeconds=requestedBuffer>=800&&requestedBuffer<=10000?requestedBuffer/1000:4;
  this.imageTimers=new Set();this.video=null;this.videoCallback=null;
  this.presentationRevision=0;this.dsh=playbackAuthority&&window.DSHPlayback?new DSHPlayback(this):null;
  this.codec='jpeg';this.avcDecoder=null;this.avcFrames=new Map();
 }
 async connect(){
  await this.audioContext.resume();
  // Browser-source hosts already capture their DOM and Web Audio output.
  // Sending that output through another MediaStream/video element can stall
  // in an offscreen CEF renderer, so Livehime consumes the canvas directly.
  this.destination=this.directOutput?this.audioContext.destination:this.audioContext.createMediaStreamDestination();
  this.outputGain=this.audioContext.createGain();this.outputGain.gain.value=this.audible?1:0;this.outputGain.connect(this.destination);
  if(window.RoomAudioMixer&&window.roomClient)this.roomMixer=new RoomAudioMixer(this.audioContext,this.outputGain,window.roomClient,{audible:this.audible});
  if(!this.directOutput){
   this.stream=this.canvas.captureStream(0);this.videoTrack=this.stream.getVideoTracks()[0];
   if(typeof this.videoTrack.requestFrame!=='function'){
    this.videoTrack.stop();this.stream=this.canvas.captureStream(25);this.videoTrack=this.stream.getVideoTracks()[0];
   }
   this.stream.addTrack(this.destination.stream.getAudioTracks()[0]);
  }
  if(new URLSearchParams(location.search).get('codec')!=='jpeg'&&typeof VideoDecoder==='function'){
   // The offscreen Livehime CEF decoder can accept hardware configuration
   // without returning pictures. Prefer its native software H264 decoder;
   // this does not run an avatar model or change A's inference precision.
   try{const config={codec:'avc1.42c01f',codedWidth:720,codedHeight:1280,optimizeForLatency:true,hardwareAcceleration:this.directOutput?'prefer-software':'prefer-hardware'};
    if((await VideoDecoder.isConfigSupported(config)).supported){
     if(this.protocolVersion===2)this.configureAVC(config);this.codec='h264_nvenc';
    }
   }catch{this.avcDecoder?.close();this.avcDecoder=null}
  }
  if(this.protocolVersion===3&&this.codec!=='h264_nvenc')throw Error('横屏人物需要支持 H.264 的浏览器，请更新直播姬。');
  await new Promise((resolve,reject)=>{
   let settled=false;const finish=error=>{if(settled)return;settled=true;clearTimeout(timeout);error?reject(error):resolve()};
   const timeout=setTimeout(()=>finish(Error('人物准备超过三分钟，请检查服务后重试。')),180000);this.finishConnect=finish;this.ws=new WebSocket(location.origin.replace(/^http/,'ws')+'/api/studio/stream?v='+this.protocolVersion+(this.codec==='h264_nvenc'?'&codec=h264':''));this.ws.binaryType='arraybuffer';
   this.ws.onmessage=event=>{this.incoming=this.incoming.then(async()=>{if(!this.running)return;if(typeof event.data==='string')await this.control(JSON.parse(event.data));else{await this.receive(event.data);finish()}}).catch(error=>{this.decodeErrors++;finish(error);this.failVideo('Invalid media or control')})};
   this.ws.onerror=()=>finish(Error('本地音视频连接未建立。'));
   this.ws.onclose=event=>{const reconnect=this.running;finish(Error('人物画面连接已关闭。'));this.close();if(reconnect)this.onClose?.({code:event.code,reason:event.reason})};
  });
  return this.stream;
 }
 async control(message){
  if(this.protocolVersion!==3){this.dsh?.control(message);return}
  if(message.type==='media.reset'){
   if(message.protocol_version!==3||!this.mediaInit||message.old_stream_id!==this.mediaInit.stream_id||typeof message.new_stream_id!=='string'||message.new_stream_id===message.old_stream_id||this.retiredStreams.has(message.new_stream_id))throw Error('MEDIA_RESET_INVALID');
   this.retiredStreams.add(message.old_stream_id);if(this.retiredStreams.size>64)throw Error('MEDIA_RESET_LIMIT');
   this.pendingStream=message.new_stream_id;this.mediaInit=null;this.dsh?.resetMedia();this.clearPlayback(false);
   if(this.avcDecoder&&this.avcDecoder.state!=='closed')this.avcDecoder.close();this.avcDecoder=null;
   this.context.clearRect(0,0,this.canvas.width,this.canvas.height);window.dispatchEvent(new CustomEvent('avatar-media-reset'));return;
  }
  if(message.type!=='media.init'){if(!['media.map','playback.cancel'].includes(message.type))throw Error('MEDIA_CONTROL_INVALID');if(!this.mediaInit&&message.type==='media.map')throw Error('MEDIA_INIT_REQUIRED');this.dsh?.control(message);return}
  const integer=(value,min,max)=>Number.isSafeInteger(value)&&value>=min&&value<=max;
  const id=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value);
  if(message.protocol_version!==3||!id(message.stream_id)||!id(message.media_profile_id)||this.retiredStreams.has(message.stream_id)||!integer(message.width,64,4096)||!integer(message.height,64,4096)||!integer(message.fps_num,1,120000)||!integer(message.fps_den,1,10000)||message.fps_num/message.fps_den>120||!/^avc1\.[0-9a-f]{6}$/i.test(message.codec)||message.time_base_num!==1||message.time_base_den!==1000000||!integer(message.pts_origin_us,0,Number.MAX_SAFE_INTEGER)||message.audio?.format!=='s16le'||message.audio.channels!==1||!integer(message.audio.sample_rate,8000,96000))throw Error('MEDIA_INIT_INVALID');
  if(this.pendingStream&&this.pendingStream!==message.stream_id)throw Error('MEDIA_RESET_TARGET_MISMATCH');
  if(this.mediaInit){if(JSON.stringify(this.mediaInit)!==JSON.stringify(message))throw Error('MEDIA_INIT_REQUIRES_RESET');return}
  const encoded=message.avc_description_base64;
  if(typeof encoded!=='string'||encoded.length>65536||!encoded.length||encoded.length%4||!/^[A-Za-z0-9+/]+={0,2}$/.test(encoded))throw Error('MEDIA_AVCC_INVALID');
  const description=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
  if(description.length<11||description[0]!==1||description[4]!==255||description[5]!==225||[...description.slice(1,4)].map(n=>n.toString(16).padStart(2,'0')).join('')!==message.codec.slice(5).toLowerCase())throw Error('MEDIA_AVCC_INVALID');
  let offset=6;for(let kind=0;kind<2;kind++){if(kind&&description[offset++]!==1)throw Error('MEDIA_AVCC_INVALID');const length=(description[offset]<<8)|description[offset+1];offset+=2;if(length<1||offset+length>description.length||(description[offset]&31)!==(kind?8:7))throw Error('MEDIA_AVCC_INVALID');offset+=length}if(offset!==description.length)throw Error('MEDIA_AVCC_INVALID');
  const config={codec:message.codec,codedWidth:message.width,codedHeight:message.height,description,optimizeForLatency:true,hardwareAcceleration:this.directOutput?'prefer-software':'prefer-hardware'};
  if(!(await VideoDecoder.isConfigSupported(config)).supported)throw Error('MEDIA_CODEC_UNSUPPORTED');
  if(!this.running)return;
  this.canvas.width=message.width;this.canvas.height=message.height;this.configureAVC(config);this.mediaInit=message;this.pendingStream=null;
  this.lastSequence=null;window.dispatchEvent(new CustomEvent('avatar-media-init',{detail:message}));
 }
 setAudible(value){
  this.audible=!!value;
  if(this.outputGain)this.outputGain.gain.setValueAtTime(this.audible?1:0,this.audioContext.currentTime);
  if(this.roomMixer){this.roomMixer.audible=this.audible;this.roomMixer.sync()}
  if(!this.audible){this.dsh?.resetMedia();this.clearPlayback()}
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
  if(!(packet instanceof ArrayBuffer)||packet.byteLength<12)throw Error('MEDIA_PACKET_INVALID');
  if(this.protocolVersion===3&&!this.mediaInit)throw Error('MEDIA_INIT_REQUIRED');
  const header=new DataView(packet),sequence=header.getUint32(0,true),length=header.getUint32(4,true),rate=header.getUint32(8,true);
  if(length>packet.byteLength-12||(packet.byteLength-12-length)%2||!rate||rate>96000||this.protocolVersion===3&&(rate!==this.mediaInit.audio.sample_rate||length<9||header.getUint32(12,false)!==0x41564331||this.lastSequence!==null&&sequence<=this.lastSequence))throw Error('MEDIA_PACKET_INVALID');
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
  const source=this.audioContext.createBufferSource();source.buffer=buffer;source.connect(this.roomMixer?.speech||this.outputGain);this.sources.add(source);source.onended=()=>{this.sources.delete(source);source.disconnect()};
  if(this.receiptsRequired&&(!this.audible||window.roomClient?.state?.settings.audio.speech_volume===0))source._dshCancelled=true;else source.start(at);
  this.dsh?.schedule(source,metadata,at,pcm.length,rate);
  this.roomMixer?.schedule(source,metadata,at,rate);
  if(source._dshCancelled){this.sources.delete(source);source.disconnect()}
  this.samples+=pcm.length;this.energy+=energy/rate;
  if(!length){this.serverSkippedVideo++;return}
  // Keep compressed pictures until close to playout, rather than retaining
  // seconds of decoded 720x1280 bitmaps in the viewing computer's memory.
  const delay=(at-this.audioContext.currentTime-.12)*1000;
  if(delay>0){const timer=setTimeout(()=>{this.imageTimers.delete(timer);this.enqueuePicture(packet,at).catch(()=>{this.decodeErrors++;this.failVideo('Media decode failed')})},delay);this.imageTimers.add(timer);return}
  await this.enqueuePicture(packet,at);
 }
 async enqueuePicture(packet,at){
  if(!this.running)return;
  const presentationRevision=this.presentationRevision;
  const length=new DataView(packet).getUint32(4,true);
  if(length>=8&&new DataView(packet).getUint32(12,false)===0x41564331){
   if(!this.avcDecoder||this.avcDecoder.state!=='configured')throw Error('H264 decoder unavailable');
   if(this.avcDecoder.decodeQueueSize>8||this.avcFrames.size>16){this.failVideo('Video decoder too slow');return}
   const duration=this.mediaInit?1000000*this.mediaInit.fps_den/this.mediaInit.fps_num:40000;
   const header=new DataView(packet),timestamp=Math.round(header.getUint32(0,true)*duration+(this.mediaInit?.pts_origin_us||0));
   const keyframe=!!header.getUint32(16,true);
   if(this.waitingAVCKeyframe&&!keyframe){this.skippedVideo++;return}this.waitingAVCKeyframe=false;
   this.avcFrames.set(timestamp,{at,revision:this.presentationRevision});
   this.avcDecoder.decode(new EncodedVideoChunk({type:keyframe?'key':'delta',timestamp,duration:Math.round(duration),data:new Uint8Array(packet,20,length-8)}));return;
  }
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
     this.videoTrack?.requestFrame?.();this.frames++;
    }
    picture.close();
   },Math.max(0,(at-this.audioContext.currentTime)*1000));
   this.timers.set(timer,picture);
  }).catch(()=>{this.decodeErrors++}).finally(()=>{this.pendingDecodes--});
  await this.decode;
 }
 configureAVC(config=this.avcConfig){
  if(this.avcDecoder&&this.avcDecoder.state!=='closed')this.avcDecoder.close();
  this.avcConfig=config;this.waitingAVCKeyframe=true;this.avcFrames.clear();
  const revision=this.presentationRevision;
  this.avcDecoder=new VideoDecoder({output:frame=>{if(revision!==this.presentationRevision){frame.close();return}this.presentAVC(frame)},error:()=>{this.decodeErrors++;this.failVideo('Video decoder failed')}});
  this.avcDecoder.configure(config);
 }
 failVideo(reason){
  // Browser JavaScript permits only 1000 or application codes 3000–4999.
  // 1011 throws before closing, leaving a failed decoder permanently stuck.
  if(this.ws?.readyState===WebSocket.OPEN)this.ws.close(4001,reason);
 }
 presentAVC(picture){
  const timing=this.avcFrames.get(picture.timestamp);this.avcFrames.delete(picture.timestamp);
  if(!timing||!this.running||timing.revision!==this.presentationRevision){picture.close();return}
  if(this.protocolVersion===3&&(picture.displayWidth!==this.mediaInit?.width||picture.displayHeight!==this.mediaInit?.height)){picture.close();this.decodeErrors++;this.failVideo('Video dimensions disagree with media.init');return}
  if(timing.at<this.audioContext.currentTime-.12){picture.close();this.skippedVideo++;return}
  const timer=setTimeout(()=>{
   this.timers.delete(timer);
   if(this.running&&timing.revision===this.presentationRevision){this.context.drawImage(picture,0,0,this.canvas.width,this.canvas.height);this.videoTrack?.requestFrame?.();this.frames++}
   picture.close();
  },Math.max(0,(timing.at-this.audioContext.currentTime)*1000));this.timers.set(timer,picture);
 }
 metrics(){
  const now=performance.now(),usesPresentation=!!this.video?.requestVideoFrameCallback,count=usesPresentation?this.presentedFrames:this.frames;
  if(now-this.previousTime>=800){this.fps=(count-this.previousFrames)/(now-this.previousTime)*1000;this.previousFrames=count;this.previousTime=now}
  return {codec:this.codec,output_mode:this.directOutput?'direct_canvas_audio':'media_stream',frames:this.frames,received_frames:this.receivedFrames,presented_frames:usesPresentation?this.presentedFrames:null,fps:this.fps,fps_source:usesPresentation?'video_presentation':'canvas_draw',width:this.canvas.width,height:this.canvas.height,audio_clock_seconds:this.audioContext.currentTime,decoder_queue:this.avcDecoder?.decodeQueueSize||0,pending_video_frames:this.avcFrames.size,audio_samples:this.samples,audio_energy:this.energy,audio_underruns:this.audioUnderruns,target_audio_buffer_ms:this.bufferSeconds*1000,audio_buffer_ms:Math.max(0,(this.next-this.audioContext.currentTime)*1000),missing_packets:this.missingPackets,server_skipped_video_frames:this.serverSkippedVideo,skipped_video_frames:this.skippedVideo,decode_errors:this.decodeErrors,max_arrival_gap_ms:this.maxArrivalGap,connected:this.ws?.readyState===WebSocket.OPEN};
 }
 close(){
  this.running=false;this.dsh?.close();this.clearPlayback();
  this.ws?.close();
  if(this.avcDecoder&&this.avcDecoder.state!=='closed')this.avcDecoder.close();this.avcFrames.clear();
  if(this.video&&this.videoCallback!==null)this.video.cancelVideoFrameCallback?.(this.videoCallback);
  for(const timer of this.imageTimers)clearTimeout(timer);this.imageTimers.clear();
  for(const [timer,picture] of this.timers){clearTimeout(timer);picture.close()}this.timers.clear();
  for(const source of this.sources)try{source.stop()}catch{}
  this.stream?.getTracks().forEach(track=>track.stop());if(!this.directOutput)this.destination?.disconnect();
  this.roomMixer?.close();
  this.outputGain?.disconnect();this.finishConnect?.(Error('人物播放已关闭。'));
 }
 clearPlayback(reconfigure=true){
  this.presentationRevision++;this.next=0;
  this.roomMixer?.clear();
  this.avcFrames.clear();
  if(reconfigure&&this.running&&this.avcDecoder){this.configureAVC();if(this.ws?.readyState===WebSocket.OPEN)this.ws.send(JSON.stringify({type:'video.keyframe'}))}
  for(const timer of this.imageTimers)clearTimeout(timer);this.imageTimers.clear();
  for(const [timer,picture] of this.timers){clearTimeout(timer);picture.close()}this.timers.clear();
  for(const source of this.sources){source._dshCancelled=true;try{source.stop()}catch{}}this.sources.clear();
 }
}
window.LocalAvatarStream=LocalAvatarStream;
