'use strict';
class LocalAvatarStream {
 constructor(audioContext,onClose){this.audioContext=audioContext;this.onClose=onClose;this.canvas=document.createElement('canvas');this.canvas.width=720;this.canvas.height=1280;this.context=this.canvas.getContext('2d',{alpha:false});this.timers=new Set();this.sources=new Set();this.running=true;this.next=0;this.frames=0;this.samples=0;this.energy=0;this.previousFrames=0;this.previousTime=performance.now();this.fps=0;this.decode=Promise.resolve();}
 async connect(){
  await this.audioContext.resume();this.destination=this.audioContext.createMediaStreamDestination();this.stream=this.canvas.captureStream(25);this.stream.addTrack(this.destination.stream.getAudioTracks()[0]);
  await new Promise((resolve,reject)=>{
   let settled=false;const finish=error=>{if(settled)return;settled=true;clearTimeout(timeout);error?reject(error):resolve()};
   const timeout=setTimeout(()=>finish(Error('人物准备超过三分钟，请检查服务后重试。')),180000);this.ws=new WebSocket(location.origin.replace(/^http/,'ws')+'/api/studio/stream');this.ws.binaryType='arraybuffer';
   this.ws.onmessage=event=>{this.decode=this.decode.then(()=>this.receive(event.data)).then(()=>finish()).catch(error=>finish(error))};
   this.ws.onerror=()=>finish(Error('本地音视频连接未建立。'));
   this.ws.onclose=()=>{finish(Error('人物画面连接已关闭。'));if(this.running)this.onClose?.()};
  });
  return this.stream;
 }
 async receive(packet){
  if(!this.running)return;
  const header=new DataView(packet),length=header.getUint32(4,true),rate=header.getUint32(8,true);
  const picture=await createImageBitmap(new Blob([packet.slice(12,12+length)],{type:'image/jpeg'}));
  if(!this.running){picture.close();return;}
  const pcm=new Int16Array(packet.slice(12+length)),buffer=this.audioContext.createBuffer(1,pcm.length,rate),data=buffer.getChannelData(0);let energy=0;
  for(let i=0;i<pcm.length;i++){data[i]=pcm[i]/32768;energy+=data[i]*data[i]}
  const now=this.audioContext.currentTime;if(this.next<now||this.next>now+.6)this.next=now+.12;
  const at=this.next;this.next+=pcm.length/rate;
  const source=this.audioContext.createBufferSource();source.buffer=buffer;source.connect(this.destination);this.sources.add(source);source.onended=()=>{this.sources.delete(source);source.disconnect()};source.start(at);
  const timer=setTimeout(()=>{this.timers.delete(timer);if(this.running){if(this.canvas.width!==picture.width||this.canvas.height!==picture.height){this.canvas.width=picture.width;this.canvas.height=picture.height}this.context.drawImage(picture,0,0,this.canvas.width,this.canvas.height);this.frames++;this.samples+=pcm.length;this.energy+=energy/rate}picture.close()},Math.max(0,(at-now)*1000));this.timers.add(timer);
 }
 metrics(){const now=performance.now();if(now-this.previousTime>=800){this.fps=(this.frames-this.previousFrames)/(now-this.previousTime)*1000;this.previousFrames=this.frames;this.previousTime=now}return {frames:this.frames,fps:this.fps,width:this.canvas.width,height:this.canvas.height,audio_samples:this.samples,audio_energy:this.energy,connected:this.ws?.readyState===WebSocket.OPEN};}
 close(){this.running=false;this.ws?.close();for(const timer of this.timers)clearTimeout(timer);for(const source of this.sources)try{source.stop()}catch{}this.stream?.getTracks().forEach(track=>track.stop());this.destination?.disconnect();}
}
window.LocalAvatarStream=LocalAvatarStream;
