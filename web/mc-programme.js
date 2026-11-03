'use strict';
(async()=>{
 const preview=location.pathname==='/mc/preview',host=document.getElementById('programme');
 let closed=false,transport=null,retry=null,authorityBusy=false,context=null,overlay=null,candidateState=null,candidateFrame=null,candidateHud=null;
 const room=window.roomClient=new RoomClient(),game=window.mcGameClient=new MCGameClient();
 const abort=new AbortController();
 const fetchJSON=async(path,body)=>{const request=new AbortController(),stop=()=>request.abort(),timeout=setTimeout(stop,6000);abort.signal.addEventListener('abort',stop,{once:true});if(abort.signal.aborted)stop();try{const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},...(body?{body:JSON.stringify(body)}:{}),cache:'no-store',signal:request.signal});if(!response.ok)throw Error('PROGRAMME_SERVICE_UNAVAILABLE');return await response.json()}finally{clearTimeout(timeout);abort.signal.removeEventListener('abort',stop)}};
 const authority=value=>{if(!transport)return;if(transport.audible!==value)transport.setAudible(value);overlay?.setPlaybackAuthority(value)};
 function status(){if(!overlay)return;const healthy=candidateState?candidateState.connected:game.connected&&game.state?.connected&&game.state.freshness==='fresh';const mode=candidateState?.mode||game.state?.mode;overlay.setStatus(preview?'静音预览 · 虚拟主播':!transport?.running?'人物重新连接中':!transport?.dsh?.ready?'等待正式播放':!healthy?'游戏连接待恢复':mode==='AUTO'?'知夏 · 自主游玩':mode==='MANUAL_COMMENTARY'?'知夏 · 陪伴解说':'知夏 · 已暂停',!preview&&!!transport?.dsh?.ready&&healthy)}
 async function candidate(){
  try{
   const value=await fetchJSON('/api/dsh/mc-candidate/status');if(closed||!value.connected||!value.viewer?.ready)return;
   candidateState=value;
   if(!candidateFrame){candidateFrame=document.createElement('iframe');candidateFrame.className='mc-candidate-game';candidateFrame.title='Minecraft 实时区块视图';candidateFrame.src='http://127.0.0.1:'+value.viewer.port+'/';host.prepend(candidateFrame);candidateHud=document.createElement('div');candidateHud.className='mc-candidate-hud';overlay.stage.append(candidateHud)}
   candidateHud.textContent='❤ '+value.health+' / 20　饱食 '+value.food+' / 20　'+(value.inventory.map(x=>x.name.replace(/^minecraft:/,'')+' ×'+x.count).join('　')||'空背包');
   status();
  }catch{}
 }
 async function report(){
  if(closed||preview||authorityBusy||!transport?.running||!transport.dsh)return;authorityBusy=true;const current=transport;
  try{
   if(!room.state||room.state.settings.audio.muted||context.state!=='running'){authority(false);return}
   const state=await fetchJSON('/api/dsh/status');if(closed||current!==transport)return;
   if(!state.broadcast||state.broadcast.state==='DRAINING'){authority(false);return}
   if(current.dsh.lease?.broadcast_id&&current.dsh.lease.broadcast_id!==state.broadcast.broadcast_id){current.dsh.lease=null;authority(false)}
   // A second window waits for the existing consumer; page parameters never
   // authorize replacing a live lease. Operator replacement remains explicit.
   if(!current.dsh.lease&&state.health?.authority_ready){authority(false);return}
   const player=await fetchJSON('/api/dsh/platforms/output/player',{consumer_id:current.dsh.consumerId,renderer:'livehime',programme:'mc',layout_id:'mc-landscape-v1',frames:current.frames,width:1920,height:1080,audio_state:context.state,stream_metrics:current.metrics()});
   if(closed||current!==transport)return;
   if(player.ignored){authority(false);return}
   if(!current.dsh.lease||!state.health?.authority_ready){authority(false);await current.dsh.claim(state.broadcast.broadcast_id,false,{deferReady:true})}
   if(closed||current!==transport)return;
   if(!room.state||room.state.settings.audio.muted||context.state!=='running'){authority(false);return}
   // The backend waits for this local output preparation before it can start
   // a new utterance, so the claim response cannot consume its first samples.
   if(!current.dsh.ready){current.setAudible(true);overlay?.setPlaybackAuthority(false);await current.dsh.activate()}
   if(closed||current!==transport)return;
   authority(current.dsh.ready&&!room.state.settings.audio.muted&&context.state==='running');
   if(current.dsh.ready&&current.roomMixer)await fetchJSON('/api/dsh/room/player',{consumer_id:current.dsh.consumerId,...current.roomMixer.metrics()});
  }catch{if(!closed&&current===transport)authority(false)}finally{authorityBusy=false;status()}
 }
 async function connect(){
  if(closed)return;const old=transport;transport=null;old?.close();overlay.avatar.replaceChildren();
  const current=new LocalAvatarStream(context,()=>{if(closed||current!==transport)return;authority(false);clearTimeout(retry);retry=setTimeout(()=>void connect(),3000);status()},{directOutput:true,protocolVersion:3,playbackAuthority:!preview,audible:false,receiptsRequired:!preview});
  transport=window.avatarTransport=current;current.onAuthorityLost=()=>{if(current===transport){authority(false);status()}};overlay.setTransport(current);
  try{await current.connect();if(closed||current!==transport)return;await report();status()}catch{if(!closed&&current===transport){current.close();status();clearTimeout(retry);retry=setTimeout(()=>void connect(),3000)}}
 }
 function close(){if(closed)return;closed=true;abort.abort();clearTimeout(retry);clearInterval(reportTimer);transport?.close();overlay?.close();room.close();game.close();void context?.close()}
 const reportTimer=setInterval(()=>{void report();void candidate()},1500);window.addEventListener('pagehide',close,{once:true});window.addEventListener('beforeunload',close,{once:true});window.mcProgramme={close,get overlay(){return overlay},preview};
 try{
  const layout=await fetchJSON('/mc/layout.json');if(closed)return;
  overlay=window.mcOverlay=new MCProgrammeOverlay(host,room,layout);context=new AudioContext();game.addEventListener('change',status);game.start();
  let previousSpeechVolume;
  room.addEventListener('change',()=>{const audio=room.state?.settings.audio;if(audio?.muted)authority(false);if(audio?.speech_volume===0&&previousSpeechVolume!==0){transport?.dsh?.resetMedia();transport?.clearPlayback()}previousSpeechVolume=audio?.speech_volume;status()});context.addEventListener('statechange',()=>{if(context.state!=='running')authority(false)});await room.start();if(closed)return;await connect();
 }catch{if(!closed){host.textContent='节目页面尚未准备好，请稍后刷新。';close()}}
})();
