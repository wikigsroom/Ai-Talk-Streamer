'use strict';
const $=id=>document.getElementById(id);let status,streamStatus,roomState,polling=false;
async function api(path,value){const response=await fetch(path,{method:value===undefined?'GET':'POST',headers:value===undefined?{}:{'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value)});const body=await response.json();if(!response.ok)throw Error(body.error||'操作暂时没有完成');return body;}
function message(text,error=false){$('feedback').textContent=text;$('feedback').style.color=error?'#a4432f':'#7e7468';}
function action(button,fn){button.addEventListener('click',async()=>{button.disabled=true;try{await fn()}catch(error){message(error.message,true)}finally{button.disabled=false}});}
async function refresh(){if(polling)return;polling=true;try{[status,streamStatus]=await Promise.all([api('/api/studio/status'),api('/api/dsh/status')]);const speechReady=!!status.manual_speech_ready&&status.voice_contract_ready===true;$('voice-selection').textContent=speechReady?'当前：'+status.voice_id+' · '+status.voice_label+'（'+status.voice_engine+'）':'正在恢复原选 O07 / F07 音色…';$('health').textContent=speechReady?'本地播报已就绪':status.ready?'可预览 · 播报接入待完成':'正在准备本地服务';$('integration-status').textContent=speechReady?'本地人工播报已接入；口型与角色细节仍待验收。':'当前可预览、试听和查看动作，正式播报正在完成接入。';$('speak').disabled=!speechReady;$('ready').disabled=!speechReady;for(const b of $('cues').querySelectorAll('button'))b.disabled=!speechReady;$('health').classList.toggle('ready',status.ready);const states={idle:'自然待机',thinking:'准备台词',speaking:'正在说话',returning:'回到待机',listening:'倾听',reaction:'互动动作',emotion:'表情'};$('state').textContent=states[status.state]||status.state;$('quality').textContent=status.character_quality_accepted?'口型与角色细节：已验收':'口型与角色细节：待验收';if(!window.actionsBuilt&&status.actions?.length){for(const item of status.actions){const button=document.createElement('button');button.textContent=item.label;action(button,()=>api('/api/naimei/action',{action_id:item.id}).then(()=>message('已安排：'+item.label)));$('actions').append(button)}window.actionsBuilt=true;}}catch(error){$('health').textContent='本地服务连接中';message(error.message,true)}finally{polling=false;}}
action($('ready'),async()=>{
 let data=await api('/api/dsh/status');
 if(!data.broadcast||['ENDED','FAILED'].includes(data.broadcast.state)){
  await api('/api/dsh/broadcast/start',{});data=await api('/api/dsh/status');
 }
 if(data.broadcast.state!=='LIVE'&&!data.health.authority_ready){
  message('请打开正式播放源并启用声音，正在等待播放权限…');
  for(let attempt=0;attempt<40&&!data.health.authority_ready;attempt++){
   await new Promise(resolve=>setTimeout(resolve,500));data=await api('/api/dsh/status');
  }
  if(!data.health.authority_ready)throw Error('请先打开正式播放源并启用声音，再点准备排练。');
 }
 if(data.broadcast.state!=='LIVE')await api('/api/dsh/broadcast/ready',{broadcast_id:data.broadcast.broadcast_id,expected_revision:data.broadcast.revision,mode:'echo'});
 message('排练已准备，可以播报台词。');await refresh();
});
for(const [id,path]of[['pause','pause'],['end','end']])action($(id),async()=>{const data=await api('/api/dsh/status');if(!data.broadcast)throw Error('当前没有进行中的排练');await api('/api/dsh/broadcast/'+path,{broadcast_id:data.broadcast.broadcast_id,expected_revision:data.broadcast.revision});message(id==='end'?'排练已结束。':'排练已暂停。');});
action($('speak'),async()=>{const text=$('speech').value.trim();if(!text)throw Error('先写一句想说的话。');await api('/api/dsh/requests',{text,mode:'echo',idempotency_key:crypto.randomUUID()});message('台词已进入待播队列，以正式播放源实际播完为准。');});
action($('cancel'),async()=>{await api('/api/naimei/stop',{});message('已停止当前台词，奶妹正在回到待机。');});
for(const[id,playing]of[['bgm-play',true],['bgm-stop',false]])action($(id),async()=>{roomState=await api('/api/dsh/room/state');await api('/api/dsh/room/music',{action:playing?'play':'pause',...(playing?{track_id:$('music-track').value}:{}),expected_version:roomState.music.version});message(playing?'音乐已安排到正式播放源。':'音乐已暂停。');});
$('music-volume').addEventListener('change',async()=>{try{const data=await api('/api/dsh/room/state');await api('/api/dsh/room/config',{expected_revision:data.revision,patch:{audio:{music_volume:Number($('music-volume').value)}}});}catch(error){message(error.message,true)}});
function updateLayout(){const layout=$('layout').value,scene=$('scene').value;$('preview').src='/output.html?renderer=preview&codec=jpeg&buffer_ms=800&layout='+layout+'&scene='+scene;$('preview').style.aspectRatio=layout==='portrait'?'720/1280':'1280/720';$('output-link').href='/output.html?renderer=livehime&codec=jpeg&buffer_ms=800&layout='+layout+'&scene='+scene;}
$('layout').addEventListener('change',updateLayout);$('scene').addEventListener('change',updateLayout);
async function loadContent(){const cues=await api('/naimei-assets/programme-cues.json');for(const item of cues){const button=document.createElement('button');button.textContent=item.label;button.disabled=!(status?.manual_speech_ready&&status?.voice_contract_ready);action(button,()=>api('/api/naimei/cue',{cue_id:item.id,delay_seconds:Number($('cue-delay').value)}).then(()=>message('已安排：'+item.label)));$('cues').append(button)}try{const profile=await api('/naimei-assets/voice/profile.json');for(const voice of profile.voices){const card=document.createElement('div');card.className='voice-card';const title=document.createElement('h3');title.textContent=voice.label;const audio=document.createElement('audio');audio.controls=true;audio.preload='none';audio.src='/naimei-assets/'+voice.audition.slice('assets/naimei/live-v1/'.length);const button=document.createElement('button');button.textContent=voice.id==='O07'?'使用原选主音色 O07':'使用原选备用 F07';action(button,()=>api('/api/naimei/voice',{voice_id:voice.id}).then(()=>message('已选择：'+voice.label+'；下一句生效。')));card.append(title,audio,button);$('voices').append(card)}}catch{$('voices').textContent='本地声线正在准备，稍后刷新即可试听。';}}
const timer=setInterval(refresh,2000);window.addEventListener('beforeunload',()=>clearInterval(timer));refresh();loadContent().catch(error=>message(error.message,true));
for(const[id,label]of[['gentle-arrival','轻提示音'],['gentle-close','收束提示音']]){const button=document.createElement('button');button.className='secondary';button.textContent=label;action(button,()=>api('/api/naimei/sfx',{id}).then(()=>message('已发送到正式播放源。')));$('bgm-play').parentNode.append(button)}

fetch('/naimei-assets/speech-tests.json').then(r=>r.json()).then(tests=>{for(const item of tests){const option=document.createElement('option');option.value=item.text;option.textContent=item.id+' · '+item.purpose;$('speech-test').append(option)}}).catch(()=>{});
$('speech-test').addEventListener('change',()=>{if($('speech-test').value){$('speech').value=$('speech-test').value;message('测试句已填入，可以播报。')}});
