'use strict';
(()=>{
 const $=id=>document.getElementById(id),abort=new AbortController();let room=null,closed=false,timer,polling=false;
 const errors={WAIT_FOR_SPEECH_AND_NATURAL_ACTION:'请等说话和当前动作结束后再切换。',LOCAL_REHEARSAL_NOT_READY:'正式节目源还没有就绪，请检查直播姬的节目页面。',NAIMEI_PLAYBACK_SOURCE_REQUIRED:'尚未连接正式播放源，请先准备本地播报。',OPERATOR_CONTROL_REVISION_CHANGED:'游戏控制已发生变化，请刷新状态后重试。',CURRENT_LOCAL_MODEL_QUALIFICATION_REQUIRED:'本地判断模型尚未通过当前版本核验。',MODE_SWITCH_NOT_CONFIRMED:'形态切换未确认，请暂停并检查运行情况。'};
 async function api(path,body){const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:abort.signal,cache:'no-store'});const value=await response.json();if(!response.ok)throw Error(errors[value.error]||'暂未完成，请查看运行状态。');return value}
 async function action(work,button){if(button)button.disabled=true;try{$('notice').textContent='正在处理……';await work();$('notice').textContent='操作已完成。';await poll()}catch(e){if(!closed)$('notice').textContent=e.message}finally{if(button)button.disabled=false}}
 const native=body=>api('/api/issac/native',body);
 async function patch(value){if(!room)throw Error('房间设置尚未就绪。');room=await api('/api/dsh/room/config',{expected_revision:room.revision,patch:value})}
 function tile(label,value){const box=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;box.append(dt,dd);return box}
 async function poll(){if(closed||polling)return;polling=true;try{const [s,r,d]=await Promise.all([api('/api/studio/status'),api('/api/dsh/room/state'),api('/api/dsh/status')]);room=r;
  const active=d.broadcast?.state==='LIVE';$('sessionBadge').textContent=active?'本地排练中':'等待排练';$('rehearsalState').textContent=active?'播报已准备':'未开始';
  $('health').replaceChildren(tile('人物',s.ready?'就绪':'准备中'),tile('声音',s.tts_ready?'NCM01 · 就绪':'NCM01 · 准备中'),tile('游戏',s.game.armed?'自主游玩':s.game.connected?'已暂停':'未连接'),tile('人物输出',`${(s.output_fps_measured||0).toFixed(1)} 帧 / 秒`),tile('当前动作',s.body.drinking?'喝水':s.speaking?'说话':'持柄与自然动作'),tile('画质复核',s.quality_accepted?'已通过':'待验收'));
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('selected',b.dataset.mode===s.mode));
  const a=r.settings.audio,o=r.settings.overlay;for(const [id,val]of Object.entries({scene:o.mc_scene,side:o.mc_chat_side,avatar:o.mc_avatar_variant,chat:o.danmaku?'fly':o.chat?'feed':'off',speechVolume:a.speech_volume,gameVolume:a.game_volume})){if(document.activeElement!==$(id))$(id).value=val}
  $('mute').textContent=a.muted?'恢复节目声音':'静音节目';$('lastUpdate').textContent=new Date().toLocaleTimeString();
 }catch(e){if(!closed)$('notice').textContent='连接暂不可用，正在等待服务恢复。'}finally{polling=false}}
 document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>action(async()=>{const k=b.dataset.action;let value;if(k==='rehearsal')value=await api('/api/dsh/issac/rehearsal/start',{});else if(k==='launch')value=await api('/api/issac/application',{action:'launch_game'});else value=await native({action:k});if(k==='observe')$('gameDetail').textContent=JSON.stringify(value.observation||value,null,2)},b));
 document.querySelectorAll('[data-key]').forEach(b=>b.onclick=()=>action(()=>native({action:'menu',key:b.dataset.key}),b));
 document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>action(()=>api('/api/issac/mode',{mode:b.dataset.mode}),b));
 $('speak').onclick=()=>action(async()=>{const text=$('speech').value.trim();if(!text)throw Error('请先填写台词。');const r=await api('/api/dsh/room/speak',{text,mode:'echo',idempotency_key:crypto.randomUUID()});$('speechResult').textContent='已排队，等待正式节目播放。';const end=Date.now()+120000;while(!closed&&Date.now()<end){await new Promise(done=>setTimeout(done,1000));const row=await api('/api/dsh/requests/'+encodeURIComponent(r.request_id));if(row.status==='COMPLETED'){$('speechResult').textContent='台词已完整播放。';return}if(['FAILED','CANCELLED','UNKNOWN','INTERRUPTED','EXPIRED','REJECTED'].includes(row.status))throw Error('本次播报未完成，请检查正式节目源。')}throw Error('播报尚未确认，请查看节目状态。')},$('speak'));
 for(const [id,key]of [['scene','mc_scene'],['side','mc_chat_side'],['avatar','mc_avatar_variant']])$(id).onchange=()=>action(()=>patch({overlay:{[key]:$(id).value}}));
 $('chat').onchange=()=>action(()=>patch({overlay:{chat:$('chat').value==='feed',danmaku:$('chat').value==='fly'}}));
 for(const [id,key]of [['speechVolume','speech_volume'],['gameVolume','game_volume']])$(id).onchange=()=>action(()=>patch({audio:{[key]:Number($(id).value)}}));
 $('mute').onclick=()=>action(()=>patch({audio:{muted:!room.settings.audio.muted}}),$('mute'));
 function resize(){const box=$('preview').parentElement;$('preview').style.transform=`scale(${box.clientWidth/1920})`}
 const observer=new ResizeObserver(resize);observer.observe($('preview').parentElement);
 $('previewToggle').onclick=()=>{const show=$('preview').src==='about:blank';$('preview').src=show?'/issac/preview?renderer=preview':'about:blank';$('previewToggle').textContent=show?'关闭预览':'打开预览'};
 function close(){if(closed)return;closed=true;clearInterval(timer);abort.abort();observer.disconnect();$('preview').src='about:blank'}
 window.addEventListener('pagehide',close,{once:true});window.addEventListener('beforeunload',close,{once:true});timer=setInterval(()=>void poll(),2000);void poll();resize();
})();
