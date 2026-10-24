'use strict';
(() => {
  const catalog=JSON.parse(document.getElementById('voiceCatalog').textContent);
  const $=id=>document.getElementById(id),player=$('player'),key='female-a-voice-shortlist-v1';
  const all=[...catalog.benchmarks,...catalog.voices];
  const lookup=new Map(all.map(item=>[item.id,item]));
  let selected=new Set(),current=null;
  try{selected=new Set(JSON.parse(localStorage.getItem(key)||'[]').filter(id=>catalog.voices.some(item=>item.id===id)));}catch{}
  const escape=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const clock=value=>Number.isFinite(value)?Math.floor(value/60)+':'+String(Math.floor(value%60)).padStart(2,'0'):'0:00';
  function wave(values){return '<svg class="waveform" viewBox="0 0 160 38" aria-label="实际音频波形" role="img">'+values.map((v,i)=>{const height=Math.max(2,v*34);return `<rect x="${i*4}" y="${(38-height)/2}" width="2" height="${height}" rx="1" fill="currentColor"/>`;}).join('')+'</svg>';}
  $('auditionText').textContent=catalog.text;
  if(location.protocol==='file:')$('archiveLink').hidden=true;
  $('voiceGrid').innerHTML=catalog.voices.map(item=>`<article class="voice-card" id="card-${escape(item.id)}"><div class="card-head"><span class="voice-id">${escape(item.number)}</span><button class="pick" data-pick="${escape(item.id)}" aria-pressed="false" aria-label="加入候选 ${escape(item.number)}">＋ 候选</button></div><h3>${escape(item.label)}</h3><p class="casting">${escape(item.engine)} · 独立参考声 ${escape(item.number)}</p>${wave(item.waveform)}<div class="voice-meta"><span>${item.seconds.toFixed(1)} 秒</span><span>${escape(item.pitch_label)}</span></div><div class="card-controls"><button class="play" data-play="${escape(item.id)}" aria-label="试听 ${escape(item.number)} ${escape(item.label)}">▶ 试听</button><a class="card-download" href="${escape(item.url)}" download>WAV ↓</a></div></article>`).join('');
  $('engineRows').innerHTML=catalog.benchmarks.map(item=>`<tr><td>${escape(item.engine)}</td><td>${escape(item.precision)}</td><td>${item.seconds.toFixed(2)} 秒</td><td>${item.wall_seconds.toFixed(1)} 秒</td><td><button class="play" data-play="${escape(item.id)}" aria-label="试听 ${escape(item.engine)}">▶ 试听</button></td></tr>`).join('');
  $('benchmarkNote').textContent=catalog.benchmark_note||'';
  function save(){try{localStorage.setItem(key,JSON.stringify([...selected]));}catch{}render();}
  function render(){
    $('shortlistCount').textContent='已选 '+selected.size+' 款';$('exportSelection').disabled=!selected.size;
    document.querySelectorAll('[data-pick]').forEach(button=>{const yes=selected.has(button.dataset.pick);button.setAttribute('aria-pressed',String(yes));button.textContent=yes?'✓ 已加入':'＋ 候选';button.closest('article').classList.toggle('selected',yes);});
    document.querySelectorAll('[data-play]').forEach(button=>{const playing=current?.id===button.dataset.play&&!player.paused;button.textContent=playing?'Ⅱ 暂停':'▶ 试听';button.closest('article')?.classList.toggle('playing',playing);});
    $('transportPlay').textContent=player.paused?'▶':'Ⅱ';
  }
  async function play(id){
    const item=lookup.get(id);if(!item)return;
    if(current?.id===id&&!player.paused){player.pause();return;}
    if(current?.id!==id){current=item;player.src=item.url;player.load();}
    player.playbackRate=Number($('rate').value);player.preservesPitch=true;player.volume=Number($('volume').value);
    $('nowTitle').textContent=item.number?item.number+' · '+item.label:item.engine+' · 参考声 01';
    $('nowSubtitle').textContent=item.engine+' / '+(Number($('rate').value)===1?'原速':'试听变速，保持音高');
    $('downloadCurrent').hidden=false;$('downloadCurrent').href=item.url;$('transportPlay').disabled=false;
    try{await player.play();$('playerStatus').textContent='正在播放 '+$('nowTitle').textContent;}catch(error){$('playerStatus').textContent='播放失败：'+error.message;$('nowSubtitle').textContent='无法加载音频，请检查文件或连接';}
    render();
  }
  document.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;if(button.dataset.play)play(button.dataset.play);if(button.dataset.pick){const id=button.dataset.pick;selected.has(id)?selected.delete(id):selected.add(id);save();}});
  $('listenFirst').onclick=()=>{if(catalog.voices[0])play(catalog.voices[0].id);};
  $('transportPlay').onclick=()=>{if(current)play(current.id);};
  $('clearSelection').onclick=()=>{selected.clear();save();};
  $('rate').onchange=()=>{player.playbackRate=Number($('rate').value);if(current)$('nowSubtitle').textContent=current.engine+' / '+(Number($('rate').value)===1?'原速':'试听变速，保持音高');};
  $('volume').oninput=()=>{player.volume=Number($('volume').value);};
  $('seek').oninput=()=>{if(Number.isFinite(player.duration))player.currentTime=Number($('seek').value)/1000*player.duration;};
  player.addEventListener('timeupdate',()=>{$('seek').value=Number.isFinite(player.duration)&&player.duration>0?Math.round(player.currentTime/player.duration*1000):0;$('time').textContent=clock(player.currentTime)+' / '+clock(player.duration);});
  player.addEventListener('loadedmetadata',()=>{$('seek').disabled=false;$('time').textContent=clock(player.currentTime)+' / '+clock(player.duration);});
  for(const event of ['play','pause','ended'])player.addEventListener(event,render);
  player.addEventListener('error',()=>{$('nowSubtitle').textContent='音频加载失败，请检查连接或下载完整包';render();});
  $('exportSelection').onclick=()=>{
    const output={schema_version:1,character:'female-a',character_name:'林知夏',purpose:'Audition shortlist only; does not activate a live TTS engine',exported_at:new Date().toISOString(),text:catalog.text,selected:catalog.voices.filter(item=>selected.has(item.id)).map(item=>({id:item.id,label:item.label,engine:item.engine,reference:item.reference,reference_text:item.reference_text,workflow:item.workflow,audio:item.repository_audio,sha256:item.sha256})),audition_playback:{rate:Number($('rate').value),volume:Number($('volume').value)}};
    const url=URL.createObjectURL(new Blob([JSON.stringify(output,null,2)+'\n'],{type:'application/json'}));const anchor=document.createElement('a');anchor.href=url;anchor.download='female-a-voice-shortlist.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  window.addEventListener('pagehide',()=>{player.pause();player.removeAttribute('src');player.load();});
  render();
})();
