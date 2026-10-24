'use strict';
(()=>{
 const $=id=>document.getElementById(id);let operator=false,status,persona,editing;
 async function api(path,body){const r=await fetch('/api/dsh/'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'请求失败');return data;}
 const note=text=>{$('feedback').textContent=text;};
 const attempt=fn=>async event=>{event?.preventDefault();try{await fn();}catch(error){note(error.message);}};
 function cell(row,text){const td=document.createElement('td');td.textContent=text;row.append(td);return td;}
 function button(td,label,fn,danger=false){const b=document.createElement('button');b.textContent=label;if(danger)b.className='danger';b.onclick=attempt(fn);td.append(b);}
 async function loadMemory(){if(!operator)return;const result=await api('memory');$('memoryRows').replaceChildren();$('emptyMemory').hidden=!!result.entries.length;
  for(const entry of result.entries){const row=document.createElement('tr');cell(row,entry.visibility==='public'?'公共':entry.subject_key);cell(row,entry.fact_key);cell(row,entry.state==='deleted'?'已删除':entry.content);cell(row,entry.state+' / r'+entry.revision);const actions=cell(row,'');
   button(actions,'来源',async()=>{const data=await api('memory/source?memory_id='+encodeURIComponent(entry.memory_id));$('sourceContent').textContent=JSON.stringify(data,null,2);$('sourceDialog').showModal();});
   if(entry.state!=='deleted'){button(actions,'更正',async()=>{editing=entry;$('editValue').value=entry.value_json;$('editContent').value=entry.content;$('editPolarity').value=entry.polarity;$('editDialog').showModal();});
    button(actions,'删除',async()=>{const r=await api('memory/delete',{operation_id:window.streamUUID(),memory_id:entry.memory_id,subject_key:entry.subject_key});note('已删除相关内容与来源副本，删除屏障版本 '+r.generation);await loadMemory();},true);}
   $('memoryRows').append(row);
  }
 }
 async function loadJobs(){if(!operator)return;const data=await api('jobs');$('jobRows').replaceChildren();$('jobCount').textContent=data.jobs.filter(j=>!['COMPLETED','CANCELLED'].includes(j.state)).length+' 项待处理';
  for(const job of data.jobs){const row=document.createElement('tr');cell(row,job.job_kind+'\n'+job.partition_key);cell(row,job.state+' / '+job.stage);cell(row,job.consumed_through_seq+' / '+job.source_end_seq);cell(row,(job.reason||'—')+'\n'+new Date(job.not_before).toLocaleString());const td=cell(row,'');
   if(!['RUNNING','COMPLETED'].includes(job.state))button(td,'继续',async()=>{await api('jobs/resume',{job_id:job.job_id});await loadJobs();});if(!['COMPLETED','CANCELLED'].includes(job.state))button(td,'取消',async()=>{await api('jobs/cancel',{job_id:job.job_id});await loadJobs();});$('jobRows').append(row);
  }
  const maintenance=data.attempts.filter(a=>a.budget_scope==='maintenance');$('budget').textContent='最近后台尝试 '+maintenance.length+' 次；用量未知 '+maintenance.filter(a=>a.status==='USAGE_UNKNOWN').length+' 次。每日上限 20 次，每轮最多 8 次。';$('occurrences').textContent=JSON.stringify(data.occurrences,null,2);
 }
 async function refresh(){status=await api('status');$('liveState').textContent=status.broadcast?.state||'OFFAIR';$('model').textContent=status.health.channel.model||'尚未配置';$('channel').textContent='演播台渠道 · '+(status.health.channel.protocol||'—');$('personaVersion').textContent=status.health.persona_version;$('projection').textContent=status.health.projection_synced?'已同步':'等待同步';$('memoryRevision').textContent='主账本 r'+status.room.memory_revision+' · 删除屏障 '+status.room.deletion_generation;}
 async function signedIn(){const p=await api('whoami');operator=p.role==='operator';$('identity').textContent=(operator?'管理员':p.display_name)+' · 已登录';if(operator){persona=await api('persona');$('personaDocument').value=JSON.stringify(persona.document,null,2);await loadMemory();await loadJobs();}}
 $('loginForm').onsubmit=attempt(async()=>{await api('login',{token:$('loginToken').value.trim()});$('loginToken').value='';await signedIn();note('已登录。模型 API 沿用演播台设置，无需重复填写。');});
 $('refreshMemory').onclick=attempt(loadMemory);$('closeSource').onclick=()=>$('sourceDialog').close();$('cancelEdit').onclick=()=>$('editDialog').close();
 $('editForm').onsubmit=attempt(async()=>{await api('memory/correct',{operation_id:window.streamUUID(),memory_id:editing.memory_id,expected_revision:editing.revision,value:JSON.parse($('editValue').value),content:$('editContent').value,polarity:$('editPolarity').value});$('editDialog').close();await loadMemory();note('更正已保存，旧版本保留修订关系。');});
 $('publishPersona').onclick=attempt(async()=>{const result=await api('persona',{expected_version:status.health.persona_version,document:JSON.parse($('personaDocument').value)});note('已发布 '+result.persona_version);await refresh();});
 $('inviteForm').onsubmit=attempt(async()=>{const result=await api('viewers',{label:$('viewerLabel').value});$('invitation').value=result.invitation_token;note('已创建独立观众身份。相同昵称不会合并记忆。');});
 $('copyInvitation').onclick=attempt(async()=>{await navigator.clipboard.writeText($('invitation').value);note('邀请码已复制。');});
 $('backup').onclick=attempt(async()=>{const result=await api('backup',{});$('backupResult').textContent=JSON.stringify(result.manifest,null,2);note('已创建备份：'+result.backup_id);});
 for(const b of document.querySelectorAll('[data-tab]'))b.onclick=()=>{for(const tab of document.querySelectorAll('.tab'))tab.hidden=tab.id!==b.dataset.tab;for(const item of document.querySelectorAll('[data-tab]'))item.classList.toggle('selected',item===b);};
 void api('session',{}).then(refresh).then(()=>signedIn().catch(()=>{})).catch(error=>note(error.message));
 const fast=setInterval(()=>refresh().catch(()=>{}),2000),slow=setInterval(()=>{void loadJobs().catch(()=>{});},10000);addEventListener('beforeunload',()=>{clearInterval(fast);clearInterval(slow);});
})();
