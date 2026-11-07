'use strict';
// Position-only projection. It never mounts messages, owns media, or writes settings.
(() => {
  const sideFromSettings=settings=>settings?.overlay?.mc_chat_side==='left'?'left':'right';
  function apply(stage,layout,value){
    const side=value==='left'?'left':'right',preset=layout.chat.side_presets[side];
    for(const name of ['chat','gift']){
      const r=preset[name];
      for(const el of stage.querySelectorAll('[data-region="'+name+'"],[data-guide="'+name+'"]'))
        Object.assign(el.style,{left:r.x+'px',top:r.y+'px',width:r.width+'px',height:r.height+'px'});
    }
    stage.dataset.chatSide=side;
    return side;
  }
  function bind(room,stage,layout,onChange){
    const sync=()=>{if(room.state?.settings){const side=apply(stage,layout,sideFromSettings(room.state.settings));onChange?.(side);}};
    room.addEventListener('change',sync);sync();
    return ()=>room.removeEventListener('change',sync);
  }
  window.McChatPosition=Object.freeze({apply,bind,sideFromSettings});
})();
