'use strict';
const params=new URLSearchParams(location.search),renderer=params.get('renderer')||'preview',preview=renderer==='preview';
document.body.dataset.layout=params.get('layout')==='landscape'?'landscape':'portrait';
document.title='奶妹 · '+(preview?'静音预览':'正式直播画面');
const scene=params.get('scene')==='backup'?'backup':'main';
document.documentElement.style.setProperty('--scene-image','url("/naimei-assets/scenes/'+scene+'.jpg")');
const context=new AudioContext(),room=window.roomClient=new RoomClient({pollOnly:true});
window.avatarAudioContext=context;room.start().catch(()=>{});
let transport,stopped=false,connecting=false,reconnectTimer,authorityBusy=false,lastSfx=0,live=false,authorityProof=0,authorityEpoch=null;
const captionCache=new Map(),captionPending=new Set();
function notice(text){const node=document.getElementById('notice');node.textContent=text;node.hidden=!text;}
async function post(path,body){
 const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const value=await r.json();if(!r.ok)throw Error(value.error);return value;
}
async function authority(){
 if(preview||authorityBusy||!transport?.dsh||context.state!=='running')return;authorityBusy=true;
 try{
  let state=await fetch('/api/dsh/status').then(r=>r.json());
  live=state.broadcast?.state==='LIVE';
  if(transport.dsh.lease?.runtime_epoch!==state.room?.runtime_epoch){transport.dsh.lease=null;authorityProof=0;authorityEpoch=null}
  if(['STARTING','LIVE','RECOVERING','PAUSED'].includes(state.broadcast?.state)&&!state.health.authority_ready){
   await transport.dsh.claim(state.broadcast.broadcast_id,false);
   state=await fetch('/api/dsh/status').then(r=>r.json());live=state.broadcast?.state==='LIVE';
  }
  if(transport.dsh.lease){
   const consumer_id=transport.dsh.consumerId;
   const lease=transport.dsh.lease;
   const proof=await transport.dsh.api('playback/heartbeat',{lease_id:lease.lease_id,consumer_id});
   if(proof.runtime_epoch!==lease.runtime_epoch||proof.runtime_epoch!==state.room?.runtime_epoch)throw Error('STALE_PLAYBACK_AUTHORITY');
   authorityEpoch=proof.runtime_epoch;authorityProof=performance.now();
   await post('/api/dsh/platforms/output/player',{consumer_id,renderer:'livehime',frames:transport.frames,
    width:document.body.dataset.layout==='portrait'?720:1280,height:document.body.dataset.layout==='portrait'?1280:720,audio_state:context.state});
   if(transport.roomMixer)await post('/api/dsh/room/player',{consumer_id,...transport.roomMixer.metrics()});
  }
 }catch{live=false;authorityProof=0;authorityEpoch=null;}finally{authorityBusy=false}
}
function audibleAuthority(){return !preview&&live&&!!transport?.dsh?.lease&&authorityEpoch===transport.dsh.lease.runtime_epoch&&performance.now()-authorityProof<2000}
async function connect(){
 if(stopped||connecting)return;connecting=true;authorityProof=0;authorityEpoch=null;transport?.close();document.getElementById('avatar-frame').replaceChildren();
 try{
  const resumed=context.resume();
  if(context.state!=='running')notice(preview?'点击这里启用预览':'点击这里启用画面与声音');
  await resumed;
  if(stopped)return;
  transport=new LocalAvatarStream(context,()=>{notice('连接已断开，正在恢复…');if(!stopped)reconnectTimer=setTimeout(connect,2000)},{directOutput:true,audible:false});
  window.avatarTransport=transport;transport.bufferSeconds=.8;document.getElementById('avatar-frame').append(transport.canvas);
  await transport.connect();notice('');await authority();
 }catch{notice(preview?'点击这里启用预览':'点击这里启用画面与声音')}finally{connecting=false}
}
async function enablePlayback(){
 await context.resume();if(!transport?.running)await connect();else{notice('');await authority()}
}
document.getElementById('notice').addEventListener('click',enablePlayback);
document.getElementById('notice').addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();void enablePlayback()}});
function getCaptions(requestId){
 if(captionCache.has(requestId)||captionPending.has(requestId))return;captionPending.add(requestId);
 fetch('/api/naimei/captions/'+encodeURIComponent(requestId)).then(r=>r.ok?r.json():null).then(value=>{
  if(value){captionCache.set(requestId,value);while(captionCache.size>8)captionCache.delete(captionCache.keys().next().value)}
 }).catch(()=>{}).finally(()=>captionPending.delete(requestId));
}
function captions(){
 if(transport?.roomMixer){const audible=audibleAuthority();if(transport.roomMixer.audible!==audible){transport.roomMixer.audible=audible;transport.roomMixer.sync()}}
 const utterances=transport?.dsh?.utterances,now=context.currentTime;let text='';
 if(utterances)for(const value of utterances.values()){
  if(value.cancelled)continue;const span=value.spans.find(s=>s.start<=now&&now<s.end);if(!span)continue;
  getCaptions(value.request_id);
  const sample=span.sampleStart+Math.floor((now-span.start)*span.rate);
  const segment=captionCache.get(value.request_id)?.segments.find(s=>s.sample_start<=sample&&sample<s.sample_end);
  text=segment?.text||'';
  if(!captionCache.has(value.request_id)&&room.state?.caption?.request_id===value.request_id)text=room.state.caption.text.length<=36?room.state.caption.text:'';
  break;
 }
 document.getElementById('caption').textContent=text;
}
async function updateProgramme(){
 try{const a=await fetch('/api/studio/status').then(r=>r.json());
  if(a.programme){document.getElementById('programme-title').textContent=a.programme.title;document.getElementById('programme-subtitle').textContent=a.programme.subtitle}
  if(a.sfx&&a.sfx.sequence>lastSfx){lastSfx=a.sfx.sequence;
   if(audibleAuthority()&&Date.now()/1000-a.sfx.time<2){
    const data=await fetch('/naimei-assets/audio/'+a.sfx.id+'.wav').then(r=>r.arrayBuffer());
    const source=context.createBufferSource(),gain=context.createGain();source.buffer=await context.decodeAudioData(data);
    gain.gain.value=.45;source.connect(gain);gain.connect(transport.roomMixer.master);
    source.addEventListener('ended',()=>{source.disconnect();gain.disconnect()},{once:true});source.start();
    window.naimeiSfxCount=(window.naimeiSfxCount||0)+1;
   }
  }
 }catch{}
}
const timers=[setInterval(authority,500),setInterval(updateProgramme,1000),setInterval(captions,50)];
addEventListener('beforeunload',()=>{stopped=true;clearTimeout(reconnectTimer);timers.forEach(clearInterval);transport?.close();room.close();context.close()});
connect();
