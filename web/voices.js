'use strict';
(() => {
  const catalog=JSON.parse(document.getElementById('voiceCatalog').textContent);
  const $=id=>document.getElementById(id),player=$('player'),key='female-a-voice-shortlist-v1';
  const lookup=new Map([...catalog.benchmarks,...catalog.voices].map(item=>[item.id,item]));
  const samples=[...lookup.values()],valid=new Set(catalog.voices.map(item=>item.id));
  let selected=new Set(),current=null,activeEngine=catalog.default_engine||'MOSS',playEpoch=0;
  try{selected=new Set(JSON.parse(localStorage.getItem(key)||'[]').filter(id=>valid.has(id)));}catch{}
  const escape=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const clock=value=>Number.isFinite(value)?Math.floor(value/60)+':'+String(Math.floor(value%60)).padStart(2,'0'):'0:00';
  const visible=()=>catalog.voices.filter(item=>item.engine===activeEngine);
  function wave(values){return '<svg class="waveform" viewBox="0 0 160 38" aria-label="实际音频波形" role="img">'+values.map((v,i)=>{const height=Math.max(2,v*34);return `<rect x="${i*4}" y="${(38-height)/2}" width="2" height="${height}" rx="1" fill="currentColor"/>`;}).join('')+'</svg>';}
  $('auditionText').textContent=catalog.text;
  if(location.protocol==='file:'){$('archiveLink').hidden=true;$('mossDownload').hidden=true;}
  $('compareVoice').innerHTML=Array.from({length:10},(_,i)=>{const id='v'+String(i+1).padStart(2,'0');return `<option value="${id}">${id.slice(1)}${i===0?' · 三个模型':' · MOSS / SoulX'}</option>`;}).join('');
  function drawCards(){
    const otherEngine=activeEngine==='MOSS'?'SoulX':'MOSS';
    $('voiceGrid').innerHTML=visible().map(item=>{
      const other=catalog.voices.find(other=>other.voice_id===item.voice_id&&other.engine===otherEngine);
      return `<article class="voice-card" id="card-${escape(item.id)}" data-voice="${escape(item.voice_id)}"><div class="card-head"><span class="voice-id">${escape(item.number)}</span><button class="pick" data-pick="${escape(item.id)}" aria-pressed="false" aria-label="加入候选 ${escape(item.engine)} ${escape(item.number)}">＋ 候选</button></div><h3>${escape(item.label)}</h3><p class="casting"><strong>${escape(item.engine)}</strong> · 独立参考声 ${escape(item.number)}</p>${wave(item.waveform)}<div class="voice-meta"><span>${item.seconds.toFixed(1)} 秒</span><span>${escape(item.pitch_label)}</span></div><div class="card-controls"><button class="play" data-play="${escape(item.id)}" aria-label="试听 ${escape(item.engine)} ${escape(item.number)}">▶ 试听</button><a class="card-download" href="${escape(item.url)}" download>WAV ↓</a></div>${other?`<button class="compare-play" data-play="${escape(other.id)}" data-compare="true" aria-label="对照试听 ${escape(otherEngine)} ${escape(item.number)}">听 ${escape(otherEngine)} 对照 ↔</button>`:''}</article>`;
    }).join('');
    $('listenFirst').textContent='试听 '+activeEngine+' 01 ↗';
    $('engineNote').textContent=activeEngine+' 的 10 款完整试听。同号使用相同参考声、相同台词；每张卡片可直接播放另一模型对照。加入候选会记录模型与音色编号。';
    document.querySelectorAll('[data-engine]').forEach(button=>{const yes=button.dataset.engine===activeEngine;button.classList.toggle('active',yes);button.setAttribute('aria-pressed',String(yes));});
    render();
  }
  function drawComparison(){
    const items=samples.filter(item=>item.voice_id===$('compareVoice').value).sort((a,b)=>['MOSS','SoulX','FireRed'].indexOf(a.engine)-['MOSS','SoulX','FireRed'].indexOf(b.engine));
    $('engineRows').innerHTML=items.map(item=>`<tr><td>${escape(item.engine)}</td><td>${escape(item.precision)}</td><td>${item.seconds.toFixed(2)} 秒</td><td>${item.wall_seconds.toFixed(1)} 秒</td><td><button class="play" data-play="${escape(item.id)}" aria-label="试听对照表 ${escape(item.engine)} ${escape(item.voice_id)}">▶ 试听</button></td></tr>`).join('');
    $('benchmarkNote').textContent=catalog.benchmark_note||'';render();
  }
  function save(){try{localStorage.setItem(key,JSON.stringify([...selected]));}catch{}render();}
  function render(){
    const moss=[...selected].filter(id=>lookup.get(id)?.engine==='MOSS').length;
    $('shortlistCount').textContent='已选 '+selected.size+' 款'+(selected.size?' · MOSS '+moss+' / SoulX '+(selected.size-moss):'');$('exportSelection').disabled=!selected.size;
    document.querySelectorAll('[data-pick]').forEach(button=>{const yes=selected.has(button.dataset.pick);button.setAttribute('aria-pressed',String(yes));button.textContent=yes?'✓ 已加入':'＋ 候选';button.closest('article').classList.toggle('selected',yes);});
    document.querySelectorAll('.voice-card').forEach(card=>card.classList.toggle('playing',current?.voice_id===card.dataset.voice&&!player.paused));
    document.querySelectorAll('[data-play]').forEach(button=>{const item=lookup.get(button.dataset.play),playing=current?.id===button.dataset.play&&!player.paused;button.textContent=button.dataset.compare?(playing?'Ⅱ 暂停 '+item.engine:'听 '+item.engine+' 对照 ↔'):(playing?'Ⅱ 暂停':'▶ 试听');});
    $('transportPlay').textContent=player.paused?'▶':'Ⅱ';
  }
  async function play(id){
    const item=lookup.get(id);if(!item)return;
    const epoch=++playEpoch;
    if(current?.id===id&&!player.paused){player.pause();return;}
    if(current?.id!==id){current=item;player.src=item.url;player.load();}
    player.playbackRate=Number($('rate').value);player.preservesPitch=true;player.volume=Number($('volume').value);
    $('nowTitle').textContent=item.engine+' · '+(item.number||item.voice_id.slice(1))+' · '+(item.label||'同声对照');
    $('nowSubtitle').textContent=item.engine+' / '+(Number($('rate').value)===1?'原速':'试听变速，保持音高');
    $('downloadCurrent').hidden=false;$('downloadCurrent').href=item.url;$('transportPlay').disabled=false;
    try{await player.play();if(epoch!==playEpoch)return;$('playerStatus').textContent='正在播放 '+$('nowTitle').textContent;}catch(error){if(epoch!==playEpoch)return;$('playerStatus').textContent='播放失败：'+error.message;$('nowSubtitle').textContent='无法加载音频，请检查文件或连接';}
    render();
  }
  document.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;if(button.dataset.play)play(button.dataset.play);if(button.dataset.pick){const id=button.dataset.pick;selected.has(id)?selected.delete(id):selected.add(id);save();}if(button.dataset.engine){activeEngine=button.dataset.engine;drawCards();}});
  $('compareVoice').onchange=drawComparison;
  $('listenFirst').onclick=()=>{if(visible()[0])play(visible()[0].id);};
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
    const output={schema_version:2,revision:catalog.revision,character:'female-a',character_name:'林知夏',purpose:'Audition shortlist only; does not activate a live TTS engine',exported_at:new Date().toISOString(),text:catalog.text,selected:catalog.voices.filter(item=>selected.has(item.id)).map(item=>({id:item.id,voice_id:item.voice_id,label:item.label,engine:item.engine,reference:item.reference,reference_text:item.reference_text,workflow:item.workflow,audio:item.repository_audio,sha256:item.sha256})),audition_playback:{rate:Number($('rate').value),volume:Number($('volume').value)}};
    const url=URL.createObjectURL(new Blob([JSON.stringify(output,null,2)+'\n'],{type:'application/json'}));const anchor=document.createElement('a');anchor.href=url;anchor.download='female-a-voice-shortlist.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  window.addEventListener('pagehide',()=>{player.pause();player.removeAttribute('src');player.load();});
  drawCards();drawComparison();
})();
