'use strict';
(async()=>{
 try{
  const response=await fetch('/api/studio/character');
  if(!response.ok)throw Error('无法读取角色档案');
  const {character,archive,download_ready}=await response.json();
  document.title=character.archive_label+' · '+character.name+' · 角色与素材档案';
  const target=document.getElementById('archiveGroups');target.replaceChildren();
  if(!archive)throw Error('素材清单尚未生成');
  for(const group of archive.groups){const row=document.createElement('tr');for(const text of [group.label,String(group.files)]){const cell=document.createElement('td');cell.textContent=text;row.append(cell)}target.append(row)}
  document.getElementById('archiveStatus').textContent=archive.file_count+' 个来源文件 · '+(archive.total_bytes/1024/1024).toFixed(1)+' MiB · '+(download_ready?'归档包已就绪':'归档包准备中');
  if(!download_ready){const link=document.getElementById('archiveDownload');link.removeAttribute('href');link.textContent='归档包准备中';}
 }catch(error){document.getElementById('archiveStatus').textContent=error.message;document.getElementById('archiveDownload').removeAttribute('href');}
})();
