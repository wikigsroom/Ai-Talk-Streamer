'use strict';
(async()=>{
 const preview=location.pathname==='/issac/preview',host=document.getElementById('programme');
 let closed=false,transport=null,retry=null,authorityBusy=false,candidateBusy=false,context=null,overlay=null,candidateState=null,candidateFrame=null,candidateHud=null,mixBusy=false,mixAgain=false,mixTimer=null,lastMixAt=-Infinity;
 const room=window.roomClient=new RoomClient(),game=window.mcGameClient=new MCGameClient();
 const abort=new AbortController();
 const surfaceId='surface-'+window.streamUUID(),surfaceIntervals=[];
 let surfaceFrame=null,surfaceLast=null,surfaceAt=null,surfaceMono=null,surfaceCallbacks=0;
 function surfaceTick(at){
  if(closed)return;
  if(surfaceLast!==null){surfaceIntervals.push(at-surfaceLast);if(surfaceIntervals.length>180)surfaceIntervals.shift()}
  surfaceLast=at;surfaceMono=at;surfaceAt=Date.now();surfaceCallbacks++;
  surfaceFrame=requestAnimationFrame(surfaceTick);
 }
 surfaceFrame=requestAnimationFrame(surfaceTick);
 function surfaceMetrics(){
  const sorted=[...surfaceIntervals].sort((a,b)=>a-b),rank=ratio=>sorted.length?sorted[Math.ceil(sorted.length*ratio)-1]:null;
  return {source:'overlay_animation_callback',surface_id:surfaceId,programme_revision:transport?.programmeRevision??null,
   clock_basis:'browser_performance',sampled_at_ms:surfaceAt,sampled_monotonic_ms:surfaceMono,callbacks:surfaceCallbacks,
   width:host.clientWidth,height:host.clientHeight,visibility:document.visibilityState,
   count:Math.max(0,surfaceCallbacks-1),window:sorted.length,capacity:180,
   p50_ms:rank(.5),p95_ms:rank(.95),p99_ms:rank(.99),max_ms:rank(1)};
 }
 const fetchJSON=async(path,body)=>{const request=new AbortController(),stop=()=>request.abort(),timeout=setTimeout(stop,6000);abort.signal.addEventListener('abort',stop,{once:true});if(abort.signal.aborted)stop();try{const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},...(body?{body:JSON.stringify(body)}:{}),cache:'no-store',signal:request.signal});if(!response.ok)throw Error('PROGRAMME_SERVICE_UNAVAILABLE');return await response.json()}finally{clearTimeout(timeout);abort.signal.removeEventListener('abort',stop)}};
 const authority=value=>{if(!transport)return;if(transport.audible!==value)transport.setAudible(value);overlay?.setPlaybackAuthority(value)};
 function requestMix(){
  if(closed||preview)return;if(mixBusy){mixAgain=true;return}
  if(mixTimer===null)mixTimer=setTimeout(()=>{mixTimer=null;void reportMix()},Math.max(0,100-(performance.now()-lastMixAt)));
 }
 async function reportMix(){
  if(closed||preview||mixBusy||!transport?.running||!transport.dsh?.lease||!transport.roomMixer)return;
  mixBusy=true;lastMixAt=performance.now();const current=transport;
  try{
   const receipt=await fetchJSON('/api/dsh/room/player',{consumer_id:current.dsh.consumerId,...current.roomMixer.metrics(),overlay_receipts:current.dsh.ready&&current.audible?overlay.displayReceipts():[]});
   if(!closed&&current===transport)overlay.ackDisplay(receipt.overlay_receipts||[]);
  }catch{/* The native sound envelope expires when fresh official feedback stops. */}
  finally{mixBusy=false;if(mixAgain){mixAgain=false;requestMix()}}
 }
 function status(){if(!overlay)return;const healthy=game.connected&&game.state?.connected&&game.state.freshness==='fresh';overlay.setGameState(game.connected?game.state:null);overlay.setStatus('奶妹',!preview&&!!transport?.dsh?.ready&&healthy)}
 function clearCandidate(){
  if(!candidateState&&!candidateFrame&&!candidateHud)return;
  candidateState=null;candidateFrame?.remove();candidateHud?.remove();candidateFrame=null;candidateHud=null;status();
 }
 async function candidate(){
  // Isaac is captured by the official native game source, without an iframe.
  clearCandidate();
 }
 async function report(){
  if(closed||preview||authorityBusy||!transport?.running||transport.mediaFailed||!transport.dsh)return;authorityBusy=true;const current=transport;
  try{
   if(!room.state){authority(false);return}
   const state=await fetchJSON('/api/dsh/status');if(closed||current!==transport)return;
   if(!state.broadcast||state.broadcast.state==='DRAINING'){authority(false);return}
   if(current.dsh.lease?.broadcast_id&&current.dsh.lease.broadcast_id!==state.broadcast.broadcast_id){current.dsh.lease=null;authority(false)}
   // A second window waits for the existing consumer; page parameters never
   // authorize replacing a live lease. Operator replacement remains explicit.
   if(!current.dsh.lease&&state.health?.authority_ready){authority(false);return}
   const player=await fetchJSON('/api/dsh/platforms/output/player',{consumer_id:current.dsh.consumerId,renderer:'livehime',programme:'issac',layout_id:'mc-landscape-v1',programme_revision:current.programmeRevision,frames:current.frames,width:1920,height:1080,audio_state:context.state,stream_metrics:{...current.metrics(),programme_surface:surfaceMetrics()}});
   if(closed||current!==transport)return;
   if(player.ignored){authority(false);if(player.programme_reload_required){close();location.reload()}return}
   if(room.state.settings.audio.muted||context.state!=='running'){authority(false);requestMix();return}
   if(!current.dsh.lease||!state.health?.authority_ready){authority(false);await current.dsh.claim(state.broadcast.broadcast_id,false,{deferReady:true})}
   if(closed||current!==transport)return;
   if(!room.state||room.state.settings.audio.muted||context.state!=='running'){authority(false);return}
   // The backend waits for this local output preparation before it can start
   // a new utterance, so the claim response cannot consume its first samples.
   if(!current.dsh.ready){current.setAudible(true);overlay?.setPlaybackAuthority(false);await current.dsh.activate()}
   if(closed||current!==transport)return;
   authority(current.dsh.ready&&!room.state.settings.audio.muted&&context.state==='running');
   requestMix();
  }catch{if(!closed&&current===transport)authority(false)}finally{authorityBusy=false;status()}
 }
 async function connect(){
  if(closed)return;const old=transport;transport=null;old?.close();
  const current=new LocalAvatarStream(context,event=>{if(closed||current!==transport)return;authority(false);if(event?.code===4001){close();location.reload();return}clearTimeout(retry);retry=setTimeout(()=>void connect(),3000);status()},{directOutput:true,protocolVersion:3,playbackAuthority:!preview,audible:false,receiptsRequired:!preview});
  transport=window.avatarTransport=current;current.onAuthorityLost=()=>{if(current===transport){authority(false);status()}};overlay.setTransport(current);
  try{await current.connect();if(closed||current!==transport)return;await report();status()}catch{if(!closed&&current===transport){current.close();status();clearTimeout(retry);retry=setTimeout(()=>void connect(),3000)}}
 }
 function close(){if(closed)return;closed=true;cancelAnimationFrame(surfaceFrame);abort.abort();clearTimeout(retry);clearTimeout(mixTimer);clearInterval(mixInterval);window.removeEventListener('room-game-mix',requestMix);clearInterval(reportTimer);transport?.close();overlay?.close();room.close();game.close();void context?.close()}
 const mixInterval=setInterval(requestMix,750);window.addEventListener('room-game-mix',requestMix);
 const reportTimer=setInterval(()=>{void report();void candidate()},1500);window.addEventListener('pagehide',close,{once:true});window.addEventListener('beforeunload',close,{once:true});window.mcProgramme={close,get overlay(){return overlay},preview};
 try{
  const layout=await fetchJSON('/issac/layout.json');if(closed)return;
  overlay=window.mcOverlay=new MCProgrammeOverlay(host,room,layout);context=new AudioContext();game.addEventListener('change',status);game.start();
  let previousSpeechVolume;
  room.addEventListener('change',()=>{const audio=room.state?.settings.audio;if(audio?.muted)authority(false);if(audio?.speech_volume===0&&previousSpeechVolume!==0){transport?.dsh?.resetMedia();transport?.clearPlayback()}previousSpeechVolume=audio?.speech_volume;status()});context.addEventListener('statechange',()=>{if(context.state!=='running')authority(false)});await room.start();if(closed)return;await connect();
 }catch{if(!closed){host.textContent='节目页面尚未准备好，请稍后刷新。';close()}}
})();
