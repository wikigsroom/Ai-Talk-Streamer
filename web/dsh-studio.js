'use strict';
(()=>{
 const $=id=>document.getElementById(id);
 const bar=document.createElement('section');bar.className='dsh-control-bar';
 bar.innerHTML='<div><b>人格与记忆</b> <span id="dshLiveState">正在检查会话…</span> <small id="dshIdentity"></small></div><div class="dsh-control-actions"><button id="dshStart">开始网页会话</button><button id="dshObsStart">使用 OBS 开始</button><button id="dshTake">接管播放确认</button><button id="dshPause">暂停会话</button><button id="dshEnd">结束会话</button><a href="/memory">记忆管理 ↗</a></div><p id="dshFeedback" role="status">连接预览后，开始会话，再发送文字；开始网页会话不会向直播平台推流。</p><details id="dshLogin"><summary>管理员登录</summary><form id="dshLoginForm"><label for="dshLoginToken">管理员令牌</label><input id="dshLoginToken" type="password" autocomplete="off" required><button type="submit">登录</button><p>使用 3080 项目 configs/dsh-operator.token 中的令牌。已在记忆管理页登录的浏览器无需重复登录。</p></form></details>';
 const main=document.querySelector('main');main?.insertBefore(bar,main.children[1]||null);
 const hint=document.createElement('p');hint.id='dshSendHint';hint.className='mode-help';hint.setAttribute('role','status');$('feedback').after(hint);
 let status=null,principal=null,busy=false,available=null,refreshPromise=null,closed=false;
 const mode=()=>$('echoTab').getAttribute('aria-selected')==='true'?'echo':'chat';
 const note=(text,error=false)=>{$('dshFeedback').textContent=text;$('dshFeedback').classList.toggle('error',error);window.studio?.notice(text,error);};
 const messages={
  BROADCAST_NOT_LIVE:'当前会话尚未开始或已暂停。请点击「开始网页会话」或「恢复网页会话」，再发送文字。',
  BROADCAST_ALREADY_OPEN:'另一页面已开始会话，状态已刷新，请重新操作。',
  BROADCAST_REVISION_CONFLICT:'会话状态刚刚发生变化，状态已刷新，请重新操作。',
  BROADCAST_NOT_STARTABLE:'当前会话正在结束或已开始，请根据最新状态操作。',
  OPERATOR_REQUIRED:'此操作需要管理员登录，请展开下方「管理员登录」。',
  AUTHENTICATION_REQUIRED:'登录已失效，请重新登录后操作。',
  LOGIN_INVALID:'管理员令牌不正确，请核对后重试。',
  AUTHORITY_ALREADY_HELD:'另一播放端正在负责播报；继续使用原端，或明确点击「接管播放确认」。',
  PLAYBACK_LEASE_EXPIRED:'播放连接已过期，请保持预览连接，点击「接管播放确认」后重试。',
  DEPENDENCIES_NOT_READY:'人物、语音或播放端尚未就绪，请保持预览连接，稍后重新开始。',
  CHANNEL_COMPATIBILITY_REQUIRED:'AI 渠道尚未通过验证，请由管理员点击「开始网页会话」验证渠道。',
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
  if(state!=='LIVE')return principal?.role==='operator'?'尚未开始会话。连接预览后，点击上方「开始网页会话」。':'尚未开始会话。请先登录管理员，再点击「开始网页会话」。';
  if(!status.health.authority_ready)return '播放端尚未就绪。主持人请连接预览并点击「接管播放确认」，或检查 OBS。';
  if(selectedMode==='chat'&&!status.health.persona_injection_ready)return messages.CHANNEL_COMPATIBILITY_REQUIRED;
  return '';
 }
 function render(){
  const state=status?.broadcast?.state||'OFFAIR',connected=!!window.studio?.connected;
  const labels={OFFAIR:'未开始',CREATED:'准备中',STARTING:'准备中',RECOVERING:'等待恢复',LIVE:'会话进行中',PAUSED:'已暂停',DRAINING:'正在结束'};
  $('dshLiveState').textContent=status?(labels[state]||state)+' · '+(status.health.channel.model||'未配置模型'):'会话服务连接中';
  $('dshLiveState').dataset.state=state;
  $('dshIdentity').textContent=principal?.role==='operator'?'管理员已登录':'观众模式';
  $('dshLogin').hidden=principal?.role==='operator';
  $('dshStart').textContent=['PAUSED','RECOVERING'].includes(state)?'恢复网页会话':state==='LIVE'?'网页会话已开始':'开始网页会话';
  $('dshStart').disabled=busy||!status||!connected||state==='DRAINING'||state==='LIVE'&&!!status.health.persona_injection_ready;
  $('dshObsStart').disabled=busy||!status||['DRAINING','LIVE'].includes(state);
  $('dshTake').disabled=busy||!connected||!status?.broadcast||state==='DRAINING';
  $('dshPause').disabled=busy||state!=='LIVE';
  $('dshEnd').disabled=busy||!status?.broadcast||state==='DRAINING';
  hint.hidden=available===false;hint.textContent=sendBlockReason()||'会话已开始，可以发送文字。';
  window.dispatchEvent(new Event('dsh:state'));
 }
 async function refresh(){
  if(refreshPromise)return refreshPromise;
  refreshPromise=(async()=>{
   try{const [next,identity]=await Promise.all([call('status'),call('whoami').catch(error=>{if(error.status!==401)throw error;return call('session',{}).then(value=>value.principal);})]);status=next;principal=identity;available=true;bar.hidden=false;render();return status;}
   catch(error){status=null;if(error.status===404){available=false;bar.hidden=true;}render();throw error;}
   finally{refreshPromise=null;}
  })();return refreshPromise;
 }
 function showLogin(){if(principal?.role==='operator')return;$('dshLogin').open=true;$('dshLoginToken').focus();}
 async function act(fn){
  if(busy)return;busy=true;render();
  try{await refresh();if(principal?.role!=='operator'){showLogin();throw Error('OPERATOR_REQUIRED');}await fn();}
  catch(error){note(errorMessage(error),true);if(/OPERATOR|AUTHENTICATION/.test(error.message))showLogin();}
  finally{busy=false;try{await refresh();}catch{}render();}
 }
 async function prepare(){
  if(mode()==='chat'&&!status.health.persona_injection_ready){note('正在验证所配置模型的人格与工具调用…');await call('probe',{});await refresh();}
  if(status.broadcast?.state==='DRAINING')throw Error('BROADCAST_NOT_STARTABLE');
  return status.broadcast||await call('broadcast/start',{});
 }
 $('dshStart').onclick=()=>act(async()=>{
  const player=window.avatarTransport?.dsh;if(!window.studio?.connected||!player)throw Error('请先连接预览。');
  const b=await prepare();await player.claim(b.broadcast_id,false);
  if(b.state!=='LIVE'){const live=await call('broadcast/ready',{broadcast_id:b.broadcast_id,expected_revision:b.revision,mode:mode()});if(live.runtime_epoch!==player.lease.runtime_epoch)await player.claim(b.broadcast_id,false);}
  note('网页会话已开始。现在可以输入文字并发送；保持此页面连接以完成语音播放。');
 });
 $('dshObsStart').onclick=()=>act(async()=>{
  const b=await prepare();note('等待本机 OBS 连接播放…');
  for(let i=0;i<12;i++){
   await new Promise(resolve=>setTimeout(resolve,1000));if(closed)return;await refresh();
   if(status.broadcast?.broadcast_id!==b.broadcast_id)throw Error('直播场次已变化，请重新操作。');
   if(status.health.authority_ready){if(status.broadcast.state!=='LIVE')await call('broadcast/ready',{broadcast_id:b.broadcast_id,expected_revision:status.broadcast.revision,mode:mode()});note('会话已开始，OBS 负责播放；此网页可发送文字和观看预览。');return;}
  }
  throw Error('请打开本机 OBS 浏览器源 http://127.0.0.1:8010/obs.html，再点击「使用 OBS 开始」。');
 });
 $('dshTake').onclick=()=>act(async()=>{if(!status.broadcast)throw Error('请先开始会话。');await window.avatarTransport.dsh.claim(status.broadcast.broadcast_id,true);note('当前网页已接管播放。');});
 const target=()=>{if(!status?.broadcast)throw Error('当前没有进行中的会话。');return {broadcast_id:status.broadcast.broadcast_id,expected_revision:status.broadcast.revision};};
 $('dshPause').onclick=()=>act(async()=>{await call('broadcast/pause',target());note('会话已暂停，保留本场上下文。继续时点击「恢复网页会话」。');});
 $('dshEnd').onclick=()=>act(async()=>{await call('broadcast/end',target());note('正在结束会话；当前句播完后等待两分钟，再整理记忆。');});
 $('dshLoginForm').onsubmit=async event=>{
  event.preventDefault();const input=$('dshLoginToken'),token=input.value.trim();input.value='';
  try{await call('login',{token});await refresh();$('dshLogin').open=false;note('管理员登录成功。连接预览后，点击「开始网页会话」。');}
  catch(error){note(errorMessage(error),true);}
 };
 window.dshStudio={
  refresh,sendBlockReason,errorMessage,connectionChanged:render,
  async beforeSend(selectedMode){
   if(available===false)return;
   await call('session',{});await refresh();const reason=sendBlockReason(selectedMode);if(reason)throw Error(reason);
  }
 };
 void call('session',{}).then(refresh).catch(error=>note(errorMessage(error),true));
 const timer=setInterval(()=>void refresh().catch(()=>{}),1500);
 addEventListener('beforeunload',()=>{closed=true;clearInterval(timer);});
})();
