(()=>{
 const select=document.getElementById('motionSelect'),feedback=document.getElementById('motionFeedback');
 if(!select)return;
 let catalog='';
 async function refresh(){
  try{
   const state=await(await fetch('/api/studio/motion')).json();
   document.querySelectorAll('[data-motion-control]').forEach(b=>b.disabled=!state.available);
   select.disabled=!state.available;
   if(!state.available){feedback.textContent='连接预览后，可选择人物动作。';return;}
   const signature=state.clips.map(c=>c.id).join(',');
   if(signature!==catalog){
    select.replaceChildren(...state.clips.map(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=c.title;return o;}));catalog=signature;
   }
   const next=state.clips.find(c=>c.id===state.pending);
   feedback.textContent='当前：'+state.active_title+(next?' · 接下来：'+next.title:'');
   document.querySelectorAll('[data-motion-mode]').forEach(b=>b.classList.toggle('selected',b.dataset.motionMode===state.mode));
  }catch{feedback.textContent='正在等待动作服务…';}
 }
 async function send(id){
  try{
   const r=await fetch('/api/studio/motion',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
   const data=await r.json();if(!r.ok)throw Error(data.error||'动作暂不可用');
   await refresh();
  }catch(e){feedback.textContent=e.message;}
 }
 document.getElementById('playMotionBtn').addEventListener('click',()=>send(select.value));
 document.querySelectorAll('[data-motion-mode]').forEach(b=>b.addEventListener('click',()=>send(b.dataset.motionMode)));
 refresh();const timer=setInterval(()=>{if(!document.hidden)refresh();},2500);
 addEventListener('beforeunload',()=>clearInterval(timer));
})();
