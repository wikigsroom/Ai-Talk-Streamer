'use strict';
(()=>{
 const bar=document.createElement('section');bar.className='dsh-control-bar';
 bar.innerHTML='<div><b>人格与记忆</b> <span id="dshLiveState">正在连接…</span></div><div class="dsh-control-actions"><button id="dshObsStart">OBS 开播</button><button id="dshStart">网页测试开播</button><button id="dshTake">接管播放确认</button><button id="dshPause">暂停</button><button id="dshEnd">下播</button><a href="/memory">记忆管理 ↗</a></div><p id="dshFeedback" role="status">先连接画面；管理员登录后可控制直播。</p>';
 const main=document.querySelector('main');main?.insertBefore(bar,main.children[1]||null);
 const note=text=>{document.getElementById('dshFeedback').textContent=text};
 const call=async(path,body)=>{const r=await fetch('/api/dsh/'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error);return v;};
 let status;
 async function refresh(){try{status=await call('status');document.getElementById('dshLiveState').textContent=(status.broadcast?.state||'OFFAIR')+' · '+(status.health.channel.model||'未配置模型')+' · '+(status.active_request?.status||'空闲');}catch{document.getElementById('dshLiveState').textContent='人格服务未连接';}}
 async function act(fn){try{await fn();await refresh();}catch(error){note(/OPERATOR|AUTHENTICATION/.test(error.message)?'请先到记忆管理页登录管理员。':error.message);}}
 document.getElementById('dshStart').onclick=()=>act(async()=>{
  const player=window.avatarTransport?.dsh;if(!player)throw Error('请先连接预览。');
  const mode=document.getElementById('echoTab').getAttribute('aria-selected')==='true'?'echo':'chat';
  await refresh();if(mode==='chat'&&!status.health.persona_injection_ready){note('正在验证所配置模型的人格与工具调用…');await call('probe',{});}
  const b=status.broadcast||await call('broadcast/start',{});
  await player.claim(b.broadcast_id,false);if(b.state!=='LIVE'){const live=await call('broadcast/ready',{broadcast_id:b.broadcast_id,mode});if(live.runtime_epoch!==player.lease.runtime_epoch)await player.claim(b.broadcast_id,false);}
  note('已开播（'+(mode==='echo'?'原文播报':'AI 对话')+'），当前网页负责播放确认。普通输入按顺序处理。');
 });
 document.getElementById('dshObsStart').onclick=()=>act(async()=>{
  const mode=document.getElementById('echoTab').getAttribute('aria-selected')==='true'?'echo':'chat';
  await refresh();if(mode==='chat'&&!status.health.persona_injection_ready){note('正在验证模型…');await call('probe',{});}
  const b=status.broadcast||await call('broadcast/start',{});note('等待本机 OBS 取得播放确认权…');
  for(let i=0;i<12;i++){await new Promise(resolve=>setTimeout(resolve,1000));await refresh();if(status.health.authority_ready){const live=status.broadcast.state==='LIVE'?status.broadcast:await call('broadcast/ready',{broadcast_id:b.broadcast_id,mode});note(live.state==='LIVE'?'已开播，OBS 负责播放确认；此网页为预览。':'等待 OBS 重新确认租约。');return;}}
  throw Error('请打开本机 OBS 浏览器源 http://127.0.0.1:8010/obs.html，再点击 OBS 开播。');
 });
 document.getElementById('dshTake').onclick=()=>act(async()=>{await refresh();if(!status.broadcast)throw Error('请先开播。');await window.avatarTransport.dsh.claim(status.broadcast.broadcast_id,true);note('当前网页已取得播放确认权。');});
 document.getElementById('dshPause').onclick=()=>act(async()=>{await call('broadcast/pause',{});note('已暂停，保留本场上下文。');});
 document.getElementById('dshEnd').onclick=()=>act(async()=>{await call('broadcast/end',{});note('正在排空当前句子；正式下播后等待两分钟，再整理记忆。');});
 void call('session',{}).then(refresh);const timer=setInterval(refresh,1500);addEventListener('beforeunload',()=>clearInterval(timer));
})();
