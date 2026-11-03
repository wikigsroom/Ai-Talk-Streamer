'use strict';
(() => {
 const node=(tag,cls,text)=>{const el=document.createElement(tag);el.className=cls;if(text!==undefined)el.textContent=text;return el};
 const truncate=(value,count)=>{const a=Array.from(String(value||''));return a.length>count?a.slice(0,count-1).join('')+'…':a.join('')};
 const place=(el,r)=>Object.assign(el.style,{left:r.x+'px',top:r.y+'px',width:r.width+'px',height:r.height+'px'});
 class MCProgrammeOverlay{
  constructor(host,room,layout){
   this.host=host;this.room=room;this.layout=layout;this.pending=[];this.visible=[];this.giftQueue=[];this.seen=new Map();this.lastAdmit=-Infinity;this.authority=false;this.closed=false;this.reduced=matchMedia('(prefers-reduced-motion: reduce)');
   this.stage=node('div','mc-stage');this.stage.style.width=layout.canvas.width+'px';this.stage.style.height=layout.canvas.height+'px';this.stage.style.setProperty('--mc-row-height',layout.chat.row_height_px+'px');this.stage.style.setProperty('--mc-transition',layout.chat.transition_ms+'ms');this.stage.dataset.scene='play';host.append(this.stage);
   const region=(name,cls='mc-'+name)=>{const el=node('div','mc-region '+cls);el.dataset.region=name;this.stage.append(el);if(layout.regions[name])place(el,layout.regions[name]);return el};
   this.header=region('header');this.brand=node('div','mc-brand');this.brandTitle=node('strong','');this.virtual=node('span','','虚拟主播');this.brand.append(this.brandTitle,this.virtual);this.topic=node('div','mc-topic');this.header.append(this.brand,this.topic);
   this.chat=region('chat');this.fly=region('danmaku','mc-fly');this.gift=region('gift');this.caption=region('caption');this.avatar=region('avatar');this.status=region('status');this.statusText=node('span','','人物准备中');this.status.append(this.statusText);
   this.message=e=>this.accept(e.detail);this.changed=()=>this.sync();this.speech=e=>{this.speechState=e.detail;this.renderCaption()};this.onMedia=e=>this.setMedia(e.detail);this.reset=()=>{this.speechState=null;this.renderCaption();this.avatar.hidden=true};this.visibility=()=>this.tick();
   room.addEventListener('message',this.message);room.addEventListener('change',this.changed);window.addEventListener('room-speech',this.speech);window.addEventListener('avatar-media-init',this.onMedia);window.addEventListener('avatar-media-reset',this.reset);document.addEventListener('visibilitychange',this.visibility);
   this.unbindSide=McChatPosition.bind(room,this.stage,layout);this.resize=new ResizeObserver(()=>this.fit());this.resize.observe(host);this.timer=setInterval(()=>this.tick(),100);this.fit();this.sync();
  }
  fit(){const {width,height}=this.layout.canvas,scale=Math.min(this.host.clientWidth/width,this.host.clientHeight/height);this.stage.style.transform=`translate(${(this.host.clientWidth-width*scale)/2}px,${(this.host.clientHeight-height*scale)/2}px) scale(${scale})`}
  allowed(entry){const current=this.room.messages.find(m=>m.id===entry.message.id);return !!current&&!this.room.blocked(current)}
  accept(message){
   const now=performance.now(),received=Number(message.received_at),age=Math.max(0,this.room.now()-received);
   for(const [id,until] of this.seen)if(until<=now)this.seen.delete(id);
   if(!message.id||!Number.isFinite(received)||this.seen.has(message.id)||this.seen.size>=4096)return;
   this.seen.set(message.id,now+30000);
   if(age>=this.layout.chat.pending_ttl_ms||this.room.blocked(message))return;
   const entry={message,expires:now+this.layout.chat.pending_ttl_ms-age};
   if(message.type==='comment'||message.type==='note'){this.pending.push(entry);if(this.pending.length>this.layout.chat.pending_limit)this.pending.shift()}
   else if(['gift','follow','fansclub'].includes(message.type)){this.giftQueue.push(entry);if(this.giftQueue.length>this.layout.chat.pending_limit)this.giftQueue.shift()}
   this.tick();
  }
  sync(){
   const state=this.room.state;if(!state||this.closed)return;
   const o=state.settings.overlay,identity=state.settings.identity,mode=o.danmaku?'fly':'feed';
   if(this.mode&&mode!==this.mode){for(const v of this.visible)v.el.remove();this.visible=[]}this.mode=mode;
   this.stage.dataset.scene=o.mc_scene||'play';this.stage.dataset.commentMode=mode;
   this.brandTitle.textContent=truncate(identity.title,16);this.virtual.hidden=!identity.show_virtual_label;this.brand.hidden=!o.brand;const scene={interact:'和大家聊聊',break:'休息片刻',recover:'稍候继续'}[o.mc_scene];this.topic.textContent=truncate(scene?scene+' · '+identity.topic:identity.topic,20);this.topic.hidden=!o.brand||!identity.topic;
   this.chat.hidden=!o.chat||mode!=='feed';this.fly.hidden=!o.chat||mode!=='fly';this.header.hidden=!o.embedded;
   this.variant=o.mc_avatar_variant||'circle';const v=this.layout.avatar_variants[this.variant];place(this.avatar,v.region);place(this.status,v.status_region);this.avatar.dataset.variant=this.variant;this.crop();
   this.tick();this.renderCaption();
  }
  tick(){
   if(this.closed||!this.room.state)return;
   const now=performance.now(),o=this.room.state.settings.overlay,enabled=o.embedded&&o.chat;
   this.pending=this.pending.filter(e=>e.expires>now&&this.allowed(e));this.giftQueue=this.giftQueue.filter(e=>e.expires>now&&this.allowed(e));
   this.visible=this.visible.filter(e=>{const keep=enabled&&e.until>now&&this.allowed(e);if(!keep)e.el.remove();return keep});
   if(!enabled)this.pending=[];
   if(enabled&&this.pending.length&&now-this.lastAdmit>=this.layout.chat.minimum_interval_ms){if(this.mode==='feed')this.addFeed(now);else this.addFly(now)}
   const gap=this.layout.chat.row_gap_px,stride=this.layout.chat.row_height_px+gap;
   if(this.mode==='feed')this.visible.forEach((e,i)=>{e.el.style.transform=`translateY(${this.layout.regions.chat.height-(this.visible.length-i)*stride+gap}px)`});else {this.moveFlying(now);this.animate()}
   if(this.activeGift&&(!o.gifts||!o.embedded||this.activeGift.until<=now||!this.allowed(this.activeGift)))this.activeGift=null;
   if(!o.gifts||!o.embedded)this.giftQueue=[];
   if(!this.activeGift&&this.giftQueue.length){this.activeGift=this.giftQueue.shift();this.activeGift.until=now+this.layout.gift.seconds*1000;const m=this.activeGift.message;this.gift.replaceChildren(node('strong','',(m.test?'[测试] ':'')+truncate(RoomClient.displayName(m),this.layout.chat.max_nickname_characters)),node('span','',m.type==='gift'?RoomClient.giftText({...m,gift_name:truncate(m.gift_name||'礼物',8)}):'谢谢你的陪伴'))}
   this.gift.hidden=!this.activeGift;this.chat.hidden=!enabled||this.mode!=='feed';this.fly.hidden=!enabled||this.mode!=='fly';
   this.renderCaption();
  }
  makeComment(entry,flying=false){const m=entry.message,config=flying?this.layout.danmaku:this.layout.chat,el=node('article',flying?'mc-flying':'mc-comment'),body=node(flying?'span':'p','');el.dataset.messageId=m.id;el.dataset.test=String(!!m.test);RoomClient.renderText(body,m,truncate(RoomClient.content(m),config.max_text_characters));el.append(node('strong','',truncate(RoomClient.displayName(m),config.max_nickname_characters)),body);return el}
  addFeed(now){const e=this.pending.shift();e.el=this.makeComment(e);e.until=now+this.layout.chat.display_ttl_ms;this.chat.append(e.el);this.visible.push(e);if(this.visible.length>this.layout.chat.max_visible)this.visible.shift().el.remove();this.lastAdmit=now}
  addFly(now){
   const config=this.layout.danmaku,speed=config.speed_px_per_second,width=this.layout.regions.danmaku.width,reduced=this.reduced.matches;
   if(this.visible.length>=(reduced?config.lanes:config.max_visible))return;
   let lane=-1;for(let i=0;i<config.lanes;i++){const tail=this.visible.filter(e=>e.lane===i).at(-1);if(!tail||!reduced&&width-speed*(now-tail.start)/1000+tail.width<=width-config.gap_px){lane=i;break}}
   if(lane<0)return;
   const e=this.pending.shift();e.el=this.makeComment(e,true);e.lane=lane;e.start=now;this.fly.append(e.el);e.width=e.el.offsetWidth;e.reduced=reduced;e.until=now+(reduced?this.layout.chat.display_ttl_ms:(width+e.width)/speed*1000);this.visible.push(e);this.lastAdmit=now;
  }
  moveFlying(now){const width=this.layout.regions.danmaku.width,config=this.layout.danmaku;for(const e of this.visible){const x=e.reduced?Math.max(0,width-e.width):width-config.speed_px_per_second*(now-e.start)/1000;e.el.style.transform=`translate(${x}px,${e.lane*config.lane_pitch_px}px)`}}
  animate(){if(this.animation||document.hidden||this.mode!=='fly'||!this.visible.length||this.reduced.matches)return;this.animation=requestAnimationFrame(()=>{this.animation=null;if(this.closed)return;this.moveFlying(performance.now());this.animate()})}
  setPlaybackAuthority(value){this.authority=!!value;if(!value)this.speechState=null;this.renderCaption()}
  renderCaption(){
   const state=this.room.state,c=state?.caption,speech=this.speechState;
   const show=this.authority&&state?.settings.overlay.embedded&&state.settings.overlay.captions&&!state.settings.audio.muted&&state.settings.audio.speech_volume>0&&c?.request_id===speech?.request_id&&typeof c?.text==='string'&&!!speech?.request_id;
   this.caption.hidden=!show;if(!show){this.caption.textContent='';return}
   const text=Array.from(c.text),index=Math.min(Math.max(0,Math.floor(Math.max(0,Math.min(1,speech.progress||0))*text.length/64)),Math.max(0,Math.ceil(text.length/64)-1));this.caption.textContent=text.slice(index*64,(index+1)*64).join('');
  }
  setTransport(transport){this.transport=transport;this.avatar.replaceChildren(transport.canvas);if(transport.mediaInit)this.setMedia(transport.mediaInit)}
  setMedia(init){this.media=init;this.avatar.hidden=false;this.avatar.dataset.mediaProfile=init.media_profile_id;this.crop()}
  crop(){
   const canvas=this.transport?.canvas;if(!canvas)return;
   const legacy=(this.media?.width===720&&this.media?.height===1280),crop=legacy?this.layout.avatar_variants[this.variant||'circle'].preview_crop:null;
   this.avatar.dataset.material=legacy?'legacy-preview-crop':'source-profile';
   Object.assign(canvas.style,crop?{left:(-crop.x/crop.width*100)+'%',top:(-crop.y/crop.height*100)+'%',width:(720/crop.width*100)+'%',height:(1280/crop.height*100)+'%'}:{left:'0',top:'0',width:'100%',height:'100%'});
  }
  setStatus(text,ready=false){this.statusText.textContent=text;this.status.dataset.ready=String(ready)}
  close(){if(this.closed)return;this.closed=true;clearInterval(this.timer);cancelAnimationFrame(this.animation);this.resize.disconnect();this.unbindSide?.();this.room.removeEventListener('message',this.message);this.room.removeEventListener('change',this.changed);window.removeEventListener('room-speech',this.speech);window.removeEventListener('avatar-media-init',this.onMedia);window.removeEventListener('avatar-media-reset',this.reset);document.removeEventListener('visibilitychange',this.visibility);this.host.replaceChildren()}
 }
 window.MCProgrammeOverlay=MCProgrammeOverlay;
})();
