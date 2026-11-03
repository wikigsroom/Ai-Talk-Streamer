'use strict';
// A programme scene can observe the game; it cannot grant control or issue a task.
class MCGameClient extends EventTarget{
 constructor(){super();this.connected=false;this.closed=false;this.state=null;this.revision=0}
 async refresh(){const revision=++this.revision;try{const response=await fetch('/api/dsh/game/state',{cache:'no-store',signal:this.abort.signal});if(!response.ok)throw Error('GAME_UNAVAILABLE');const value=await response.json();if(this.closed||revision!==this.revision)return;this.state=value;this.connected=true}catch{if(this.closed)return;this.connected=false}this.dispatchEvent(new Event('change'))}
 start(){this.abort=new AbortController();void this.refresh();this.events=new EventSource('/api/dsh/game/events');for(const name of ['snapshot','state','health'])this.events.addEventListener(name,()=>void this.refresh());this.events.onerror=()=>{this.connected=false;this.dispatchEvent(new Event('change'))};this.timer=setInterval(()=>void this.refresh(),3000);return this}
 close(){this.closed=true;this.revision++;this.abort?.abort();this.events?.close();clearInterval(this.timer)}
}
window.MCGameClient=MCGameClient;
