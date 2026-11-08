'use strict';
const $=id=>document.getElementById(id);
let status,streamStatus,roomState,polling=false,playbackWindow=null,preparingPlayback=null,operation=null,preparationCancelled=false;
let extensionState,extensionCheckedAt=0;
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const errors={
 NAIMEI_PLAYBACK_SOURCE_REQUIRED:'有声播放页尚未启用。请在播放页点击“启用画面与声音”，再播报。',
 DEPENDENCIES_NOT_READY:'播放正在准备，请在有声播放页启用声音后重试。',
 CUE_IN_PROGRESS:'上一条节目仍在准备，请等待完成，或先点击“停止说话”。',
 SPEECH_IN_PROGRESS:'奶妹正在说话，请播完后再切换。',
 NAIMEI_BRIDGE_UNAVAILABLE:'本地播放服务暂时未连接，请稍后重试。',
 NAIMEI_LOCAL_MODEL_REQUIRED:'请连接这台电脑或局域网中的模型服务。',
 CHANNEL_NOT_CONFIGURED:'原有对话配置尚未就绪，请检查保存的渠道。',
 CHANNEL_COMPATIBILITY_REQUIRED:'奶妹原有对话渠道尚未通过检查，请先检查连接。',
 MODEL_RESPONSE_INVALID:'模型回复没有完成，请检查模型服务后重试。'
};
async function api(path,value){
 const response=await fetch(path,{method:value===undefined?'GET':'POST',headers:value===undefined?{}:{'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value)});
 const body=await response.json();if(!response.ok)throw Error(errors[body.error]||body.error||'操作暂时没有完成');return body;
}
function message(text,error=false){$('feedback').textContent=text;$('feedback').style.color=error?'#a4432f':'#7e7468';}
function playbackMessage(text,error=false){$('playback-state').textContent=text;message(text,error);}
function modelsReady(){return !!status?.manual_speech_ready&&status?.voice_contract_ready===true;}
function hasPlayback(data=streamStatus){return data?.health?.authority_ready===true;}
function resumePreview(){try{$('preview').contentWindow.avatarAudioContext?.resume().catch(()=>{});}catch{}}
function openPlayback(){
 resumePreview();
 if(hasPlayback())return;
 if(playbackWindow&&!playbackWindow.closed){playbackWindow.focus();return;}
 playbackWindow=window.open($('output-link').href,'naimei-live-source');
 if(!playbackWindow)throw Error('浏览器拦截了播放页，请点击“打开有声播放页”，允许打开后重试。');
}
async function preparePlayback(){
 if(preparingPlayback)return preparingPlayback;
 preparationCancelled=false;
 preparingPlayback=(async()=>{
  let data=await api('/api/dsh/status');
  if(!data.broadcast||['ENDED','FAILED'].includes(data.broadcast.state)){
   await api('/api/dsh/broadcast/start',{});data=await api('/api/dsh/status');
  }
  // A LIVE broadcast can outlive its player. Check playback on every click.
  if(!hasPlayback(data)){
   playbackMessage('有声播放页已打开；如有提示，请在该页点击“启用画面与声音”。启用后会继续本次操作。');
   const deadline=Date.now()+60000;
   while(!hasPlayback(data)&&Date.now()<deadline){
    if(preparationCancelled)throw Error('本次待播已取消。');
    if(playbackWindow?.closed)throw Error('有声播放页已关闭，本次台词尚未提交。重新点击播报即可继续。');
    await wait(500);data=await api('/api/dsh/status');
   }
   if(!hasPlayback(data))throw Error('有声播放页尚未启用，本次台词尚未提交。请启用声音后重试。');
  }
  if(preparationCancelled)throw Error('本次待播已取消。');
  if(data.broadcast.state!=='LIVE')await api('/api/dsh/broadcast/ready',{broadcast_id:data.broadcast.broadcast_id,expected_revision:data.broadcast.revision,mode:'echo'});
  streamStatus=await api('/api/dsh/status');
  // Preparing a rehearsal advances the playback generation. Wait for the
  // player to reconnect to that generation before accepting a line.
  const readyDeadline=Date.now()+15000;
  while(!hasPlayback(streamStatus)||streamStatus.broadcast?.state!=='LIVE'){
   if(preparationCancelled)throw Error('本次待播已取消。');
   if(playbackWindow?.closed)throw Error('有声播放页已关闭，本次台词尚未提交。');
   if(Date.now()>=readyDeadline)throw Error('有声播放仍在恢复，本次台词尚未提交。请稍后重试。');
   await wait(250);streamStatus=await api('/api/dsh/status');
  }
 })().finally(()=>{preparingPlayback=null;});
 return preparingPlayback;
}
function action(button,fn,{playback=false,check=null}={}){
 button.addEventListener('click',async()=>{
  button.dataset.busy='true';button.disabled=true;
  try{
   resumePreview();
   if(check)check();
   if(playback){
    if(!modelsReady())throw Error('本地语音正在准备，请稍后重试。');
    // Open during the original click so browsers can allow the playback tab.
    openPlayback();await preparePlayback();
    if(preparationCancelled)throw Error('本次待播已取消。');
   }
   await fn();
  }catch(error){playbackMessage(error.message,true);}
  finally{delete button.dataset.busy;button.disabled=false;void refresh();}
 });
}
function trackRequest(result,label,text){
 const requestId=result.request_id||result.request?.request_id;
 if(!requestId)throw Error('本次台词未能进入播放，请重试。');
 operation={request_id:requestId,label,text};$('current-line').textContent=text;
 playbackMessage(label+'：正在准备声音。');
}
async function updateOperation(){
 const current=operation;if(!current)return;
 if(current.cue_run_id&&!current.request_id){
  const event=status.events?.findLast(item=>item.cue_run_id===current.cue_run_id);
  if(event?.type==='programme_cue_failed'){
   operation=null;playbackMessage(current.label+'未播出：'+(errors[event.error]||event.error),true);return;
  }
  if(event?.request_id)current.request_id=event.request_id;
  else{
   const scheduled=status.scheduled_cue;
   playbackMessage(scheduled?.cue_run_id===current.cue_run_id?
    current.label+'：将在 '+Math.max(0,Math.ceil(scheduled.due_at-Date.now()/1000))+' 秒后播出。':
    current.label+'：正在准备节目动作与台词。');return;
  }
 }
 const request=await api('/api/dsh/requests/'+encodeURIComponent(current.request_id));
 if(operation!==current)return;
 if(request.final_text){current.text=request.final_text;$('current-line').textContent=request.final_text;}
 const states={QUEUED:'已排队',THINKING:'正在准备台词',TEXT_READY:'正在准备声音',SYNTHESIZING:'正在生成声音',AUDIO_READY:'声音已准备',BUFFERING:'正在准备播放',PLAYING:'正在播放',COMPLETED:'已播完',CANCELLED:'已取消',INTERRUPTED:'已停止',UNKNOWN:'播放连接已中断，请重试',FAILED:'播报失败，请重试',EXPIRED:'等待超时，请重新播报',REJECTED:'未能播出，请重试'};
 const failed=['UNKNOWN','FAILED','EXPIRED','REJECTED'].includes(request.status);
 const waiting=request.status==='QUEUED'&&!hasPlayback()?'等待启用有声播放页':states[request.status]||request.status;
 playbackMessage(current.label+'：'+waiting+'。',failed);
 if(['COMPLETED','CANCELLED','INTERRUPTED','UNKNOWN','FAILED','EXPIRED','REJECTED'].includes(request.status))operation=null;
}
async function refresh(){
 if(polling)return;polling=true;
 try{
  [status,streamStatus]=await Promise.all([api('/api/studio/status'),api('/api/dsh/status')]);
  const modelReady=modelsReady(),playerReady=modelReady&&hasPlayback(),liveReady=playerReady&&streamStatus.broadcast?.state==='LIVE';
  $('voice-selection').textContent=modelReady?'当前：'+status.voice_label:'奶妹的定稿声音正在准备…';
  $('health').textContent=liveReady?'可以有声播报':playerReady?'播放页已连接 · 待准备':modelReady?'等待启用有声播放':'正在准备本地服务';
  $('integration-status').textContent=liveReady?'有声播放已连接，点击播报即可看到台词与字幕。口型与角色细节仍待验收。':
   playerReady?'有声播放页已连接。点击准备排练、播报或节目按钮，即可开始本地排练。':
   modelReady?'当前为静音预览。点击播报会打开有声播放页；如有提示，请在该页启用声音，随后自动继续。':'本地语音和人物画面正在准备。';
  $('health').classList.toggle('ready',liveReady);
  for(const button of [$('ready'),$('speak'),...$('cues').querySelectorAll('button')])button.disabled=!modelReady||!!preparingPlayback||button.dataset.busy==='true';
  const states={idle:'自然待机',thinking:'准备台词',speaking:'正在说话',returning:'回到待机',listening:'倾听',reaction:'互动动作',emotion:'表情'};
  $('state').textContent=states[status.state]||status.state;
  $('quality').textContent=status.character_quality_accepted?'口型与角色细节：已验收':'口型与角色细节：待验收';
  if(!window.actionsBuilt&&status.actions?.length){
   for(const item of status.actions){const button=document.createElement('button');button.textContent=item.label;action(button,()=>api('/api/naimei/action',{action_id:item.id}).then(()=>message('已安排：'+item.label)));$('actions').append(button);}
   window.actionsBuilt=true;
  }
  await updateOperation();
  if(Date.now()-extensionCheckedAt>5000){extensionCheckedAt=Date.now();await refreshExtensions();}
 }catch(error){$('health').textContent='本地服务连接中';message(error.message,true);}
 finally{polling=false;}
}
action($('ready'),()=>playbackMessage('有声排练已准备，可以播报台词。'),{playback:true});
action($('speak'),async()=>{
 const text=$('speech').value.trim();if(!text)throw Error('先写一句想说的话。');
 trackRequest(await api('/api/dsh/requests',{text,mode:'echo',idempotency_key:crypto.randomUUID()}),'本次播报',text);
},{playback:true,check:()=>{const text=$('speech').value.trim();if(!text)throw Error('先写一句想说的话。');$('current-line').textContent=text;}});
for(const[id,path]of[['pause','pause'],['end','end']])action($(id),async()=>{
 preparationCancelled=true;
 const data=await api('/api/dsh/status');if(!data.broadcast)throw Error('当前没有进行中的排练');
 await api('/api/dsh/broadcast/'+path,{broadcast_id:data.broadcast.broadcast_id,expected_revision:data.broadcast.revision});
 message(id==='end'?'排练已结束。':'排练已暂停。');
});
action($('cancel'),async()=>{preparationCancelled=true;await api('/api/naimei/stop',{});operation=null;playbackMessage('已停止当前台词及待播条目，奶妹正在回到待机。');});
for(const[id,playing]of[['bgm-play',true],['bgm-stop',false]])action($(id),async()=>{
 roomState=await api('/api/dsh/room/state');
 await api('/api/dsh/room/music',{action:playing?'play':'pause',...(playing?{track_id:$('music-track').value}:{}),expected_version:roomState.music.version});
 message(playing?'音乐已安排到有声播放页。':'音乐已暂停。');
});
$('music-volume').addEventListener('change',async()=>{try{
 const data=await api('/api/dsh/room/state');await api('/api/dsh/room/config',{expected_revision:data.revision,patch:{audio:{music_volume:Number($('music-volume').value)}}});
}catch(error){message(error.message,true);}});
function updateLayout(){
 const layout=$('layout').value,scene=$('scene').value;
 $('preview').src='/output.html?renderer=preview&codec=jpeg&buffer_ms=800&layout='+layout+'&scene='+scene;
 $('preview').style.aspectRatio=layout==='portrait'?'720/1280':'1280/720';
 $('output-link').href='/output.html?renderer=livehime&codec=jpeg&buffer_ms=800&layout='+layout+'&scene='+scene;
}
$('layout').addEventListener('change',updateLayout);$('scene').addEventListener('change',updateLayout);
async function loadContent(){
 for(const item of await api('/naimei-assets/programme-cues.json')){
  const button=document.createElement('button');button.textContent=item.label;button.disabled=!modelsReady();
  action(button,async()=>{
   const result=await api('/api/naimei/cue',{cue_id:item.id,delay_seconds:Number($('cue-delay').value)});
   operation={cue_run_id:result.cue_run_id,label:item.label,text:item.text};$('current-line').textContent=item.text;
   playbackMessage(item.label+'：节目已安排，正在准备。');
  },{playback:true,check:()=>{$('current-line').textContent=item.text;}});$('cues').append(button);
 }
 try{
  const profile=await api('/api/naimei/voice-profile');
  for(const voice of profile.voices){
   const card=document.createElement('div');card.className='voice-card';
   const title=document.createElement('h3');title.textContent=voice.label;
   const audio=document.createElement('audio');audio.controls=true;audio.preload='none';audio.src='/api/naimei/voice-audition/'+encodeURIComponent(voice.id);
   const button=document.createElement('button');button.textContent=voice.id===profile.default_voice_id?'使用定稿声音':'使用此声音';
   action(button,()=>api('/api/naimei/voice',{voice_id:voice.id}).then(()=>message('已选择：'+voice.label+'；下一句生效。')));
   card.append(title,audio,button);$('voices').append(card);
  }
 }catch{$('voices').textContent='本地声线正在准备，稍后刷新即可试听。';}
}
const timer=setInterval(refresh,1000);window.addEventListener('beforeunload',()=>clearInterval(timer));
refresh();loadContent().catch(error=>message(error.message,true));
for(const[id,label]of[['gentle-arrival','轻提示音'],['gentle-close','收束提示音']]){
 const button=document.createElement('button');button.className='secondary';button.textContent=label;
 action(button,()=>api('/api/naimei/sfx',{id}).then(()=>message('已发送到有声播放页。')));$('bgm-play').parentNode.append(button);
}
fetch('/naimei-assets/speech-tests.json').then(r=>r.json()).then(tests=>{
 for(const item of tests){const option=document.createElement('option');option.value=item.text;option.textContent=item.id+' · '+item.purpose;$('speech-test').append(option);}
}).catch(()=>{});
$('speech-test').addEventListener('change',()=>{if($('speech-test').value){$('speech').value=$('speech-test').value;message('测试句已填入，可以播报。');}});

async function refreshExtensions(){
 try{
  extensionState=await api('/api/dsh/extensions');
  const state=extensionState;
  $('extensions-status').textContent=(state.loaded?'七项聊天能力已载入':'聊天能力正在准备')+' · 心情：'+(state.mood?.label||'平常')+' · '+(state.channel_ready?'对话模型已连接':'等待原对话渠道连接')+(state.proactive_armed?(state.proactive_ready?' · 可在空闲时搭话':' · 空闲搭话已开，等待合适时机'):' · 空闲搭话未开');
  $('proactive').textContent=state.proactive_armed?'关闭空闲搭话':'开启空闲搭话';
 }catch{$('extensions-status').textContent='聊天能力尚未连接，请检查本地服务。';}
}
action($('chat'),async()=>{
 const text=$('speech').value.trim();
 const result=await api('/api/dsh/requests',{text,mode:'chat',public_input:true,idempotency_key:crypto.randomUUID()});
 trackRequest(result,'奶妹回应','正在回应：'+text);
},{playback:true,check:()=>{if(!$('speech').value.trim())throw Error('先在上方输入想跟奶妹说的话。');if(!extensionState?.channel_ready)throw Error(errors.CHANNEL_COMPATIBILITY_REQUIRED);}});
action($('proactive'),async()=>{
 const enabled=!extensionState?.proactive_armed;
 if(enabled){
  if(!extensionState?.channel_ready)throw Error(errors.CHANNEL_COMPATIBILITY_REQUIRED);
  if(!modelsReady())throw Error('本地声音与人物画面正在准备。');
  openPlayback();await preparePlayback();
 }
 await api('/api/dsh/extensions/proactive',{enabled});await refreshExtensions();
 message(enabled?'空闲搭话已开启。奶妹会等当前内容结束，偶尔自然起个话题。':'空闲搭话已关闭。');
});
action($('local-model-save'),async()=>{
 const result=await api('/api/dsh/probe',{});
 if(!result.passed)throw Error('模型已连接，但还不能正确使用奶妹的人格和工具，请检查模型兼容性。');
 await refreshExtensions();message('原有对话渠道检查通过，可以让奶妹回应。');
});
action($('meme-search'),async()=>{
 const value=await api('/api/dsh/extensions/meme',{query:$('meme-query').value.trim()});
 $('meme-result').textContent=value.found?value.results.map(item=>item.text).join('\n\n'):'两个本地词库都没有收录这个词。';
});
api('/api/dsh/extensions/model').then(value=>{
 $('channel-summary').textContent=value.configured?'当前模型：'+value.model+' · '+value.protocol+' · 沿用已保存的渠道':'原有对话渠道尚未配置。';
}).catch(()=>{});
