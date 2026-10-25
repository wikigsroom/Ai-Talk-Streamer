'use strict';
(()=>{
 const $=id=>document.getElementById(id);
 let status,persona,editing,archiving,eventSource,eventTimer,cursor=null,nextCursor=null,pageStack=[],selected=new Map(),broadcasts=[];
 async function api(path,body){const r=await fetch('/api/dsh/'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'请求失败');return data;}
 const note=text=>{$('feedback').textContent=text;};
 const attempt=fn=>async event=>{event?.preventDefault();try{await fn();}catch(error){note(error.message==='MEMORY_PAGE_CHANGED'?'记忆已更新，请刷新后重新分页。':error.message);}};
 const resetPage=()=>{cursor=null;pageStack=[];selected.clear();};
 function cell(row,text){const td=document.createElement('td');td.textContent=text;row.append(td);return td;}
 function button(td,label,fn,danger=false){const b=document.createElement('button');b.textContent=label;if(danger)b.className='danger';b.onclick=attempt(fn);td.append(b);}
 function selection(){ $('selectionCount').textContent='已选 '+selected.size+' 条';$('mergeSelected').disabled=selected.size<2||selected.size>20; }
 function operationSaved(id){$('undoOperation').value=id;note('操作已保存：'+id+'。可使用下方补偿撤销。');}
 async function loadMemory(){

  const parameters=new URLSearchParams({limit:'50'});
  for(const [key,id] of [['subject_key','filterSubject'],['fact_key','filterFact'],['state','filterState']])if($(id).value.trim())parameters.set(key,$(id).value.trim());
  if(cursor)parameters.set('cursor',cursor);
  const result=await api('memory?'+parameters);nextCursor=result.next_cursor;selected.clear();selection();
  $('memoryRows').replaceChildren();$('emptyMemory').hidden=!!result.entries.length;
  $('pageInfo').textContent='第 '+(pageStack.length+1)+' 页 · 本页 '+result.entries.length+' 条 · r'+result.revision;
  $('previousPage').disabled=!pageStack.length;$('nextPage').disabled=!nextCursor;
  for(const entry of result.entries){
   const row=document.createElement('tr'),select=cell(row,'');
   if(!['deleted','superseded','retracted'].includes(entry.state)){const check=document.createElement('input');check.type='checkbox';check.setAttribute('aria-label','选择 '+entry.fact_key+' '+entry.subject_key);check.onchange=()=>{if(check.checked)selected.set(entry.memory_id,entry);else selected.delete(entry.memory_id);selection();};select.append(check);}
   cell(row,entry.visibility==='public'?'公共':entry.subject_key);cell(row,entry.fact_key);cell(row,entry.state==='deleted'?'已删除':entry.content);cell(row,entry.state+' / r'+entry.revision);const actions=cell(row,'');
   button(actions,'来源',async()=>{const data=await api('memory/source?memory_id='+encodeURIComponent(entry.memory_id));$('sourceContent').textContent=JSON.stringify(data,null,2);$('sourceDialog').showModal();});
   if(entry.state!=='deleted'){
    button(actions,'更正',async()=>{editing=entry;$('editValue').value=entry.value_json;$('editContent').value=entry.content;$('editPolarity').value=entry.polarity;$('editDialog').showModal();});
    if(!['archived','superseded','retracted'].includes(entry.state))button(actions,'归档',async()=>{archiving=entry;$('archiveReason').value='';$('archiveDialog').showModal();});
    button(actions,'删除',async()=>{const r=await api('memory/delete',{operation_id:window.streamUUID(),memory_id:entry.memory_id,subject_key:entry.subject_key});note('已删除相关内容与来源副本，删除屏障版本 '+r.generation);resetPage();await loadMemory();},true);
   }
   $('memoryRows').append(row);
  }
 }
 async function loadJobs(){
const data=await api('jobs');$('jobRows').replaceChildren();$('jobCount').textContent=data.jobs.filter(j=>!['COMPLETED','CANCELLED'].includes(j.state)).length+' 项待处理';
  for(const job of data.jobs){const row=document.createElement('tr');cell(row,job.job_kind+'\n'+job.partition_key);cell(row,job.state+' / '+job.stage);cell(row,job.consumed_through_seq+' / '+job.source_end_seq);cell(row,(job.reason||'—')+'\n'+new Date(job.not_before).toLocaleString());const td=cell(row,'');
   if(!['RUNNING','COMPLETED'].includes(job.state))button(td,'继续',async()=>{await api('jobs/resume',{job_id:job.job_id});await loadJobs();});if(!['COMPLETED','CANCELLED'].includes(job.state))button(td,'取消',async()=>{await api('jobs/cancel',{job_id:job.job_id});await loadJobs();});$('jobRows').append(row);
  }
  const maintenance=data.attempts.filter(a=>a.budget_scope==='maintenance');$('budget').textContent='最近后台尝试 '+maintenance.length+' 次；用量未知 '+maintenance.filter(a=>a.status==='USAGE_UNKNOWN').length+' 次。每日上限 20 次，每轮最多 8 次。';$('occurrences').textContent=JSON.stringify(data.occurrences,null,2);
 }
 function selectBroadcast(){const b=broadcasts.find(b=>b.broadcast_id===$('rebuildBroadcast').value);$('rebuildStart').value=b?.source_start_seq||'';$('rebuildEnd').value=b?.ended_event_seq||'';}
 async function loadBroadcasts(){const data=await api('broadcasts');broadcasts=data.broadcasts.filter(b=>b.state==='ENDED');const prior=$('rebuildBroadcast').value;$('rebuildBroadcast').replaceChildren();for(const b of broadcasts){const option=document.createElement('option');option.value=b.broadcast_id;option.textContent=new Date(b.ended_at).toLocaleString()+' · '+b.broadcast_id;$('rebuildBroadcast').append(option);}if(broadcasts.some(b=>b.broadcast_id===prior))$('rebuildBroadcast').value=prior;else selectBroadcast();}
 async function refresh(){status=await api('status');$('liveState').textContent=status.broadcast?.state||'OFFAIR';$('model').textContent=status.health.channel.model||'尚未配置';$('channel').textContent='演播台渠道 · '+(status.health.channel.protocol||'—');$('personaVersion').textContent=status.health.persona_version;$('projection').textContent=status.health.projection_synced?'已同步':'等待同步';$('memoryRevision').textContent='主账本 r'+status.room.memory_revision+' · 删除屏障 '+status.room.deletion_generation;}
 function subscribe(){eventSource?.close();eventSource=new EventSource('/api/dsh/events');eventSource.addEventListener('state',()=>{if(eventTimer)return;eventTimer=setTimeout(()=>{eventTimer=null;void refresh().catch(()=>{});void loadJobs().catch(()=>{});},300);});}
 async function initialize(){
  $('identity').textContent='直接使用';subscribe();persona=await api('persona');$('personaDocument').value=JSON.stringify(persona.document,null,2);resetPage();await loadMemory();await loadJobs();await loadBroadcasts();
 }
 $('refreshMemory').onclick=attempt(async()=>{resetPage();await loadMemory();});$('memoryFilters').onsubmit=attempt(async()=>{resetPage();await loadMemory();});
 $('previousPage').onclick=attempt(async()=>{const oldCursor=cursor,oldStack=[...pageStack];cursor=pageStack.pop()??null;try{await loadMemory();}catch(error){cursor=oldCursor;pageStack=oldStack;throw error;}});
 $('nextPage').onclick=attempt(async()=>{if(!nextCursor)return;const old=cursor;pageStack.push(cursor);cursor=nextCursor;try{await loadMemory();}catch(error){cursor=old;pageStack.pop();throw error;}});
 $('closeSource').onclick=()=>$('sourceDialog').close();$('cancelEdit').onclick=()=>$('editDialog').close();for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>$(b.dataset.close).close();
 $('editForm').onsubmit=attempt(async()=>{const id=window.streamUUID();await api('memory/correct',{operation_id:id,memory_id:editing.memory_id,expected_revision:editing.revision,value:JSON.parse($('editValue').value),content:$('editContent').value,polarity:$('editPolarity').value});$('editDialog').close();resetPage();await loadMemory();operationSaved(id);});
 $('archiveForm').onsubmit=attempt(async()=>{const id=window.streamUUID();await api('memory/archive',{operation_id:id,memory_id:archiving.memory_id,expected_revision:archiving.revision,reason:$('archiveReason').value});$('archiveDialog').close();resetPage();await loadMemory();operationSaved(id);});
 $('mergeSelected').onclick=attempt(async()=>{$('mergeTarget').replaceChildren();for(const entry of selected.values()){const o=document.createElement('option');o.value=entry.memory_id;o.textContent=entry.content+' / r'+entry.revision;$('mergeTarget').append(o);}$('mergeReason').value='';$('mergeDialog').showModal();});
 $('mergeForm').onsubmit=attempt(async()=>{const id=window.streamUUID();await api('memory/merge',{operation_id:id,target_memory_id:$('mergeTarget').value,inputs:[...selected.values()].map(entry=>({memory_id:entry.memory_id,expected_revision:entry.revision})),reason:$('mergeReason').value});$('mergeDialog').close();resetPage();await loadMemory();operationSaved(id);});
 $('undoForm').onsubmit=attempt(async()=>{await api('memory/undo',{operation_id:$('undoOperation').value.trim(),undo_operation_id:window.streamUUID()});resetPage();await loadMemory();note('补偿修订已保存；后续修改和已删除来源受到保护。');});
 $('rebuildBroadcast').onchange=selectBroadcast;
 $('rebuildForm').onsubmit=attempt(async()=>{const b=broadcasts.find(b=>b.broadcast_id===$('rebuildBroadcast').value);if(!b)throw Error('没有可选择的已结束场次。');const r=await api('jobs/rebuild',{operation_id:window.streamUUID(),broadcast_id:b.broadcast_id,expected_source_revision:b.source_revision,partition_key:$('rebuildPartition').value.trim(),source_start_seq:Number($('rebuildStart').value),source_end_seq:Number($('rebuildEnd').value),reason:$('rebuildReason').value});note('已创建 '+r.job_id+'；按静默时间、渠道和预算条件执行。');await loadJobs();});
 $('publishPersona').onclick=attempt(async()=>{const result=await api('persona',{expected_version:status.health.persona_version,document:JSON.parse($('personaDocument').value)});note('已发布 '+result.persona_version);await refresh();});
 $('backup').onclick=attempt(async()=>{const result=await api('backup',{});$('backupResult').textContent=JSON.stringify(result.manifest,null,2);note('已创建备份：'+result.backup_id);});
 for(const b of document.querySelectorAll('[data-tab]'))b.onclick=()=>{for(const tab of document.querySelectorAll('.tab'))tab.hidden=tab.id!==b.dataset.tab;for(const item of document.querySelectorAll('[data-tab]'))item.classList.toggle('selected',item===b);if(b.dataset.tab==='jobs')void loadBroadcasts().catch(error=>note(error.message));};
 void refresh().then(initialize).catch(error=>note(error.message));
 const fast=setInterval(()=>refresh().catch(()=>{}),15000),slow=setInterval(()=>{void loadJobs().catch(()=>{});},10000);
 addEventListener('beforeunload',()=>{clearInterval(fast);clearInterval(slow);clearTimeout(eventTimer);eventSource?.close();});
})();
