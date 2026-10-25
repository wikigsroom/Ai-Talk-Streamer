'use strict';
(()=>{
 const $=id=>document.getElementById(id);
 const bar=document.createElement('section');bar.className='dsh-control-bar';
 bar.innerHTML='<div><b>人格与记忆</b> <span id="dshLiveState">正在检查会话…</span> <small id="dshIdentity">直接使用</small></div><div class="dsh-control-actions"><button id="dshStart">开始网页会话</button><button id="dshObsStart">使用 OBS 开始</button><button id="dshTake">接管播放确认</button><button id="dshPause">暂停会话</button><button id="dshEnd">结束会话</button><a href="/memory">记忆管理 ↗</a></div><p id="dshFeedback" role="status">连接预览后自动开始会话，即可发送文字。</p>';
 const main=document.querySelector('main');main?.insertBefore(bar,main.children[1]||null);
 const hint=document.createElement('p');hint.id='dshSendHint';hint.className='mode-help';hint.setAttribute('role','status');$('feedback').after(hint);
 let status=null,busy=false,available=null,refreshPromise=null,closed=false;
 const mode=()=>$('echoTab').getAttribute('aria-selected')==='true'?'echo':'chat';
 const note=(text,error=false)=>{$('dshFeedback').textContent=text;$('dshFeedback').classList.toggle('error',error);window.studio?.notice(text,error);};
 const messages={
  BROADCAST_NOT_LIVE:'当前会话尚未开始或已暂停。请连接预览，或点击「恢复网页会话」后发送。',
  BROADCAST_ALREADY_OPEN:'另一页面已开始会话，状态已刷新，请重新操作。',
  BROADCAST_REVISION_CONFLICT:'会话状态刚刚发生变化，状态已刷新，请重新操作。',
  BROADCAST_NOT_STARTABLE:'当前会话正在结束或已开始，请根据最新状态操作。',
  AUTHORITY_ALREADY_HELD:'另一播放端正在播报；继续使用原端，或点击「接管播放确认」。',
  PLAYBACK_LEASE_EXPIRED:'播放连接已过期，请连接预览并点击「接管播放确认」后重试。',
  DEPENDENCIES_NOT_READY:'人物、语音或播放端尚未就绪，请保持预览连接，稍后重新开始。',
  CHANNEL_COMPATIBILITY_REQUIRED:'AI 渠道尚未通过验证，请点击「开始网页会话」验证渠道。',
  DSH_BRIDGE_UNAVAILABLE:'会话服务暂时无法连接，请稍后重试。',
  QUEUE_FULL:'待播队列已满，请等当前内容播完后再发送。'
 };
 const errorMessage=error=>messages[error?.message||error]||error?.message||String(error);
 async function call(path,body){
  const r=await fetch('/api/dsh/'+path,{method:body===undefined?'GET':'POST',cache:'no-store',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  let v;try{v=await r.json();}catch{const error=Error('会话服务返回异常，请刷新页面后重试。');error.status=r.status;throw error;}
  if(!r.ok){const error=Error(v.error||'会话请求未完成。');error.status=r.status;throw error;}return v;
 }
 function sendBlockReason(selectedMode=mode()){
  if(available===false)return '';
  if(!status)return '正在检查会话状态，请稍候。';
  if(busy)return '正在切换会话状态，请稍候。';
  const state=status.broadcast?.state||'OFFAIR';
  if(state==='PAUSED')return '会话已暂停。请点击「恢复网页会话」后再发送。';
  if(state==='DRAINING')return '正在结束会话，当前内容播完后可开始新会话。';
  if(state!=='LIVE')return '';
  if(!status.health.authority_ready)return '播放端尚未就绪。请连接预览并点击「接管播放确认」，或检查 OBS。';
  if(selectedMode==='chat'&&!status.health.persona_injection_ready)return messages.CHANNEL_COMPATIBILITY_REQUIRED;
  return '';
 }
 function render(){
  const state=status?.broadcast?.state||'OFFAIR',connected=!!window.studio?.connected;
  const labels={OFFAIR:'未开始',CREATED:'准备中',STARTING:'准备中',RECOVERING:'等待恢复',LIVE:'会话进行中',PAUSED:'已暂停',DRAINING:'正在结束'};
  $('dshLiveState').textContent=status?(labels[state]||state)+' · '+(status.health.channel.model||'未配置模型'):'会话服务连接中';
  $('dshLiveState').dataset.state=state;
  $('dshStart').textContent=['PAUSED','RECOVERING'].includes(state)?'恢复网页会话':state==='LIVE'?'网页会话已开始':'开始网页会话';
  $('dshStart').disabled=busy||!status||!connected||state==='DRAINING'||state==='LIVE'&&!!status.health.persona_injection_ready;
  $('dshObsStart').disabled=busy||!status||['DRAINING','LIVE'].includes(state);
  $('dshTake').disabled=busy||!connected||!status?.broadcast||state==='DRAINING';
  $('dshPause').disabled=busy||state!=='LIVE';
  $('dshEnd').disabled=busy||!status?.broadcast||state==='DRAINING';
  hint.hidden=available===false;hint.textContent=sendBlockReason()||(state==='OFFAIR'?'连接预览后自动开始会话；结束后再次发送可开始新会话。':'会话已开始，可以发送文字。');
  window.dispatchEvent(new Event('dsh:state'));
 }
 async function refresh(){
  if(refreshPromise)return refreshPromise;
  refreshPromise=(async()=>{
   try{status=await call('status');available=true;bar.hidden=false;render();return status;}
   catch(error){status=null;if(error.status===404){available=false;bar.hidden=true;}render();throw error;}
   finally{refreshPromise=null;}
  })();return refreshPromise;
 }
 async function act(fn){
  if(busy)return false;busy=true;render();let succeeded=false;
  try{await refresh();await fn();succeeded=true;}
  catch(error){note(errorMessage(error),true);}
  finally{busy=false;try{await refresh();}catch{}render();}
  return succeeded;
 }
 async function prepare(selectedMode=mode()){
  if(selectedMode==='chat'&&!status.health.persona_injection_ready){note('正在验证所配置模型的人格与工具调用…');await call('probe',{});await refresh();}
  if(status.broadcast?.state==='DRAINING')throw Error('BROADCAST_NOT_STARTABLE');
  return status.broadcast||await call('broadcast/start',{});
 }
 async function beginWeb(selectedMode=mode()){
  const player=window.avatarTransport?.dsh;if(!window.studio?.connected||!player)throw Error('请先连接预览。');
  const b=await prepare(selectedMode);
  if(b.state==='LIVE'&&status.health.authority_ready){note('会话已开始，可以发送文字。');return;}
  await player.claim(b.broadcast_id,false);await refresh();
  if(status.broadcast?.broadcast_id!==b.broadcast_id)throw Error('BROADCAST_REVISION_CONFLICT');
  if(status.broadcast.state!=='LIVE'){const live=await call('broadcast/ready',{broadcast_id:b.broadcast_id,expected_revision:status.broadcast.revision,mode:selectedMode});if(live.runtime_epoch!==player.lease.runtime_epoch)await player.claim(b.broadcast_id,false);}
  note('网页会话已开始。现在可以输入文字并发送；保持此页面连接以完成语音播放。');
 }
 $('dshStart').onclick=()=>act(()=>beginWeb());
 $('dshObsStart').onclick=()=>act(async()=>{
  const b=await prepare();note('等待 OBS 连接播放…');
  for(let i=0;i<12;i++){
   await new Promise(resolve=>setTimeout(resolve,1000));if(closed)return;await refresh();
   if(status.broadcast?.broadcast_id!==b.broadcast_id)throw Error('直播场次已变化，请重新操作。');
   if(status.health.authority_ready){if(status.broadcast.state!=='LIVE')await call('broadcast/ready',{broadcast_id:b.broadcast_id,expected_revision:status.broadcast.revision,mode:mode()});note('会话已开始，OBS 负责播放；此网页可发送文字和观看预览。');return;}
  }
  throw Error('请打开 OBS 浏览器源 http://127.0.0.1:8010/obs.html，再点击「使用 OBS 开始」。');
 });
 $('dshTake').onclick=()=>act(async()=>{if(!status.broadcast)throw Error('请先开始会话。');await window.avatarTransport.dsh.claim(status.broadcast.broadcast_id,true);note('当前网页已接管播放。');});
 const target=()=>{if(!status?.broadcast)throw Error('当前没有进行中的会话。');return {broadcast_id:status.broadcast.broadcast_id,expected_revision:status.broadcast.revision};};
 $('dshPause').onclick=()=>act(async()=>{await call('broadcast/pause',target());note('会话已暂停，保留本场上下文。继续时点击「恢复网页会话」。');});
 $('dshEnd').onclick=()=>act(async()=>{await call('broadcast/end',target());note('正在结束会话；当前句播完后等待两分钟，再整理记忆。');});
 window.dshStudio={
  refresh,sendBlockReason,errorMessage,connectionChanged:render,
  async afterConnect(){
   await refresh();
   if(!['PAUSED','DRAINING'].includes(status.broadcast?.state))await act(()=>beginWeb());
  },
  async beforeSend(selectedMode){
   if(available===false)return;
   await refresh();
   if(!status.broadcast||['STARTING','RECOVERING'].includes(status.broadcast.state)){
    if(!await act(()=>beginWeb(selectedMode)))throw Error($('dshFeedback').textContent);
   }
   const reason=sendBlockReason(selectedMode);if(reason)throw Error(reason);
  }
 };
 void refresh().catch(error=>note(errorMessage(error),true));
 const timer=setInterval(()=>void refresh().catch(()=>{}),1500);
 addEventListener('beforeunload',()=>{closed=true;clearInterval(timer);});
})();
