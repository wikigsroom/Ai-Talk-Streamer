'use strict';
// A programme scene can observe the game; it cannot grant control or issue a task.
class MCGameClient extends EventTarget{
 constructor(){super();this.connected=false;this.closed=false;this.state=null;this.revision=0;this.pending=null;this.refreshAgain=false;this.lastEventAt=null}
 valid(value){return value&&typeof value==='object'&&!Array.isArray(value)&&typeof value.connected==='boolean'&&typeof value.mode==='string'&&['fresh','stale','unavailable'].includes(value.freshness)}
 apply(value){if(this.closed||!this.valid(value))return false;this.state=value;this.connected=true;this.revision++;this.dispatchEvent(new Event('change'));return true}
 refresh(){
  if(this.closed)return Promise.resolve();
  if(this.pending){this.refreshAgain=true;return this.pending}
  const revision=++this.revision,request=this.request=new AbortController(),timeout=setTimeout(()=>request.abort(),6000);
  this.pending=Promise.resolve().then(async()=>{
   try{
    if(this.closed||request.signal.aborted)return;
    const response=await fetch('/api/dsh/game/state',{cache:'no-store',signal:request.signal});if(!response.ok)throw Error('GAME_UNAVAILABLE');
    const value=await response.json();if(this.closed||request.signal.aborted||revision!==this.revision)return;
    if(!this.apply(value))throw Error('GAME_STATE_INVALID');
   }catch{if(this.closed||revision!==this.revision)return;this.connected=false;this.dispatchEvent(new Event('change'))}
  }).finally(()=>{
   clearTimeout(timeout);this.pending=null;if(this.request===request)this.request=null;
   if(!this.closed&&this.refreshAgain){this.refreshAgain=false;void this.refresh()}
  });
  return this.pending;
 }
 event(name,event){
  if(this.closed)return;
  try{
   const value=JSON.parse(event.data),state=name==='snapshot'?value.state:name==='state'?value:null;
   if(this.apply(state)){this.lastEventAt=performance.now();this.refreshAgain=false;return}
  }catch{/* An incomplete event can trigger one bounded state read. */}
  void this.refresh();
 }
 start(){
  if(this.closed||this.events)return this;
  void this.refresh();this.events=new EventSource('/api/dsh/game/events');
  for(const name of ['snapshot','state','health'])this.events.addEventListener(name,event=>this.event(name,event));
  this.events.onerror=()=>{if(this.closed)return;this.connected=false;this.lastEventAt=null;this.dispatchEvent(new Event('change'))};
  this.timer=setInterval(()=>{if(this.lastEventAt===null||performance.now()-this.lastEventAt>=3000)void this.refresh()},3000);return this;
 }
 close(){this.closed=true;this.revision++;this.refreshAgain=false;this.request?.abort();this.events?.close();clearInterval(this.timer)}
}
window.MCGameClient=MCGameClient;
