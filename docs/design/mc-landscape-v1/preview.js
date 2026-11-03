'use strict';
(() => {
  const stage=document.querySelector('#programme'),holder=document.querySelector('#frame-holder'),config=window.MC_LAYOUT;
  const applyRect=(element,r)=>Object.assign(element.style,{left:r.x+'px',top:r.y+'px',width:r.width+'px',height:r.height+'px'});
  for(const element of document.querySelectorAll('[data-region]'))applyRect(element,config.regions[element.dataset.region]);
  for(const element of document.querySelectorAll('[data-protected]'))applyRect(element,config.protected_game_regions[element.dataset.protected]);
  for(const element of document.querySelectorAll('[data-guide]'))applyRect(element,config.regions[element.dataset.guide]);
  const setText=(id,text)=>{document.getElementById(id).textContent=text;};
  const scenes={
    play:{task:'带16块橡木回营地',count:'12 / 16',caption:'好，先带够木头回营地，再看大家想做什么。',status:'林间采集 · 边玩边聊',avatarLabel:'林知夏 · 虚拟主播',description:'全屏游戏＋可左右切换的连续留言＋右下小人物。留言按到达顺序上滚，不展示“正在看哪条”。'},
    interact:{task:'带16块橡木回营地',count:'12 / 16',caption:'河边建个小营地？好呀，我们先去看看地方。',status:'边玩边聊',avatarLabel:'林知夏 · 虚拟主播',description:'回应观众时仍保留游戏全屏；只改变当前口播字幕，不放大人物、不另建提问卡。'},
    break:{task:'带16块橡木回营地',count:'12 / 16',caption:'我先休息一下，回来继续陪大家。',status:'暂离中 · 游戏已暂停',avatarLabel:'林知夏 · 虚拟主播',cover:true,coverEyebrow:'先把冒险放一放',coverTitle:'去补杯水，马上回来。',coverDescription:'游戏已暂停，回来接着聊。',coverFoot:'上一件小事：带木头回营地',description:'暂离样稿假设已收到游戏暂停确认；留言仍可展示，实际未确认时应显示“正在暂停”。'},
    recover:{task:'本轮目标暂存',count:'待恢复',caption:'',status:'画面恢复中',avatarLabel:'暂用静态形象',cover:true,coverEyebrow:'正在恢复连接',coverTitle:'画面暂时中断，正在恢复。',coverDescription:'稍等片刻，回来继续今天的冒险。',coverFoot:'今天的小目标暂时保留',description:'恢复时遮住旧游戏帧、清失效字幕；平台留言通道正常时仍可展示。'}
  };
  function selectScene(name){
    const s=scenes[name];if(!s)return;stage.dataset.scene=name;
    for(const button of document.querySelectorAll('button[data-scene]'))button.setAttribute('aria-pressed',String(button.dataset.scene===name));
    for(const [id,key]of [['task-title','task'],['task-count','count'],['caption-text','caption'],['avatar-label','avatarLabel'],['status-text','status'],['scene-description','description']])setText(id,s[key]);
    document.querySelector('#caption').hidden=!s.caption;document.querySelector('#game-cover').hidden=!s.cover;
    if(s.cover)for(const [id,key]of [['cover-eyebrow','coverEyebrow'],['cover-title','coverTitle'],['cover-description','coverDescription'],['cover-foot','coverFoot']])setText(id,s[key]);
    document.querySelector('.bookmark-steps').hidden=name==='recover';
  }
  function selectAvatar(mode){
    const variant=config.avatar_variants[mode];if(!variant)return;
    stage.dataset.avatarMode=mode;document.querySelector('#avatar-mode').value=mode;
    applyRect(document.querySelector('.avatar'),variant.region);applyRect(document.querySelector('#avatar-safe'),variant.region);
    applyRect(document.querySelector('[data-region="status"]'),variant.status_region);
    const crop=variant.preview_crop,im=document.querySelector('#avatar-image'),source=config.avatar_reference;
    Object.assign(im.style,{width:source.width/crop.width*100+'%',height:source.height/crop.height*100+'%',left:-crop.x/crop.width*100+'%',top:-crop.y/crop.height*100+'%'});
    im.alt='林知夏现有静态参考的'+(mode==='circle'?'圆形':'横向')+'裁切示意，未生成新素材';
    setText('avatar-safe-label',mode==='circle'?'圆形可见面积约2.64%':'横窗面积约2.78%');
    setText('avatar-description',mode==='circle'?'圆形：264像素直径，强调面部表情。':'横窗：320×180，当前旧图仅展示头肩裁切。');
  }
  function selectChatSide(value){
    const side=window.McChatPosition.apply(stage,config,value);
    document.querySelector('#chat-side').value=side;
  }

  const feedRules=config.chat,flyRules=config.danmaku,list=document.querySelector('#chat-list');
  const lanes=[...document.querySelectorAll('.danmaku-lane')],queue=[],seen=new Set(),nextAt=[0,0];
  const media=matchMedia('(prefers-reduced-motion: reduce)'),animations=new Set();
  const bounded=(value,length)=>Array.from(String(value)).slice(0,length).join('');
  let manualPause=false,captureFrozen=false,pausedAt=null,sequence=0,lastFeedAt=0,clock=0,giftUntil=0,previousTick=performance.now();
  const stats={shown:0,dropped:0,duplicates:0,maxVisible:0};
  const isPaused=()=>manualPause||captureFrozen||media.matches||document.hidden;
  const activeFly=()=>document.querySelectorAll('.danmaku-item');
  function updatePause(){
    const paused=isPaused(),now=performance.now();
    if(paused&&pausedAt===null)pausedAt=now;
    if(!paused&&pausedAt!==null){const elapsed=now-pausedAt;nextAt[0]+=elapsed;nextAt[1]+=elapsed;pausedAt=null;}
    stage.classList.toggle('motion-paused',paused);
    for(const animation of animations){if(paused)animation.pause();else animation.play();}
    const button=document.querySelector('#motion-toggle');button.disabled=media.matches;
    button.setAttribute('aria-pressed',String(paused));button.textContent=media.matches?'已减少动态':paused?'继续滚动':'暂停滚动';
  }
  function animate(node,keyframes){
    if(isPaused())return;
    const animation=node.animate(keyframes,{duration:320,easing:'cubic-bezier(.2,.7,.2,1)'});
    animations.add(animation);animation.finished.catch(()=>{}).finally(()=>animations.delete(animation));
  }
  function mountFeed(message,animated=true){
    const before=new Map([...list.children].map(el=>[el,el.getBoundingClientRect().top]));
    const node=document.createElement(message.kind==='superchat'?'yt-live-chat-paid-message-renderer':'yt-live-chat-text-message-renderer');
    node.className='zhixia-message';node.dataset.message=String(++sequence);node.dataset.kind=message.kind;node.dataset.entered=String(clock);
    const role=message.verifiedRole||'';
    node.setAttribute('author-type',role);node.setAttribute('blc-guard-level',role==='member'?'3':'0');
    const photo=document.createElement('span');photo.className='zhixia-photo';photo.textContent=Array.from(message.nickname)[0]||'友';
    const content=document.createElement('div');content.className='zhixia-content';
    const meta=document.createElement('div');meta.className='zhixia-meta';
    const name=document.createElement('span');name.className='zhixia-name';name.textContent=message.nickname;meta.append(name);
    const badgeText=message.kind==='superchat'?'醒目留言':role==='moderator'?'房管':role==='member'?'舰长':'';
    if(badgeText){const badge=document.createElement('span');badge.className='zhixia-badge'+(message.kind==='superchat'?' zhixia-paid-badge':'');badge.textContent=badgeText;meta.append(badge);}
    const body=document.createElement('p');body.className='zhixia-message-text';body.textContent=message.text;body.title=message.text;
    content.append(meta,body);node.append(photo,content);
    while(list.children.length>=feedRules.max_visible)list.firstElementChild.remove();
    list.append(node);
    if(animated){
      const scale=holder.clientWidth/config.canvas.width;
      for(const child of list.children){
        if(child===node)animate(child,[{opacity:0,transform:'translateY(24px)'},{opacity:1,transform:'translateY(0)'}]);
        else if(before.has(child))animate(child,[{transform:'translateY('+((before.get(child)-child.getBoundingClientRect().top)/scale)+'px)'},{transform:'translateY(0)'}]);
      }
    }
    stats.shown++;stats.maxVisible=Math.max(stats.maxVisible,list.children.length);
  }
  function mountFly(message,laneIndex,startX){
    const width=config.regions.danmaku.width,now=performance.now(),node=document.createElement('span');
    node.className='danmaku-item';node.dataset.message=String(++sequence);
    const nickname=document.createElement('strong');nickname.textContent=bounded(message.nickname,flyRules.max_nickname_characters)+'：';
    node.append(nickname,document.createTextNode(bounded(message.text,flyRules.max_text_characters)));lanes[laneIndex].append(node);
    const itemWidth=node.offsetWidth,travel=width+itemWidth,speed=flyRules.speed_px_per_second;
    node.style.setProperty('--travel',travel+'px');node.style.setProperty('--duration',travel/speed+'s');node.style.animationDelay=(-(width-startX)/speed)+'s';
    nextAt[laneIndex]=now+Math.max(0,(startX+itemWidth+flyRules.gap_px-width)/speed)*1000;
    node.addEventListener('animationend',()=>node.remove(),{once:true});stats.shown++;stats.maxVisible=Math.max(stats.maxVisible,activeFly().length);
  }
  const examples=[
    {nickname:'小林同学',text:'河边建个小营地吧，风景好看',kind:'comment'},
    {nickname:'一颗橡木',text:'先带够木头，天黑前回家',kind:'comment',verifiedRole:'member'},
    {nickname:'晚风路过',text:'慢慢玩，我们陪着你～',kind:'comment',verifiedRole:'moderator'},
    {nickname:'下课以后',text:'背包里记得留一点食物呀',kind:'comment'},
    {nickname:'方块旅行者',text:'今天想看你探索森林',kind:'comment'},
    {nickname:'小麦同学',text:'营地旁边可以种小麦吗',kind:'comment'}
  ];
  function showGift(message){
    setText('gift-text',message.nickname+' 送出小花花 × '+(message.count||1));
    document.querySelector('#gift-notice').hidden=false;giftUntil=clock+config.gift.seconds*1000;
  }
  function enqueue(nickname,text,options={}){
    const clean=String(text).replace(/[\u0000-\u001f\u007f]/g,'').trim();if(!clean)return false;
    if(options.id&&seen.has(options.id)){stats.duplicates++;return false;}
    if(queue.length>=feedRules.pending_limit){stats.dropped++;return false;}
    if(options.id){seen.add(options.id);if(seen.size>256)seen.delete(seen.values().next().value);}
    queue.push({nickname:bounded(nickname,feedRules.max_nickname_characters),text:bounded(clean,feedRules.max_text_characters),kind:['gift','superchat'].includes(options.kind)?options.kind:'comment',at:Date.now(),id:options.id});
    return true;
  }
  function selectChat(mode){
    if(!['feed','fly'].includes(mode))return;stage.dataset.chatMode=mode;document.querySelector('#chat-mode').value=mode;
    for(const animation of animations)animation.cancel();animations.clear();
    queue.length=0;list.replaceChildren();for(const lane of lanes)lane.replaceChildren();
    nextAt.fill(performance.now());lastFeedAt=clock;
    if(mode==='feed')for(const example of examples.slice(0,4))mountFeed(example,false);
    else{mountFly(examples[0],0,100);mountFly(examples[1],0,1080);mountFly(examples[2],1,400);mountFly(examples[3],1,1430);}
    // Fixtures are local examples; changing the view never submits platform or AI input.
    showGift({nickname:'一颗橡木',count:3});updatePause();
  }
  function drain(){
    const now=performance.now(),elapsed=now-previousTick;previousTick=now;if(isPaused())return;clock+=elapsed;
    if(giftUntil&&clock>=giftUntil){document.querySelector('#gift-notice').hidden=true;giftUntil=0;}
    if(stage.dataset.chatMode==='feed')for(const node of [...list.children])if(clock-Number(node.dataset.entered)>feedRules.display_ttl_ms)node.remove();
    while(queue.length&&Date.now()-queue[0].at>feedRules.pending_ttl_ms){queue.shift();stats.dropped++;}
    if(!queue.length)return;
    if(queue[0].kind==='gift'){showGift(queue.shift());return;}
    if(stage.dataset.chatMode==='feed'){
      if(clock-lastFeedAt>=feedRules.minimum_interval_ms){mountFeed(queue.shift());lastFeedAt=clock;}
    }else for(let lane=0;lane<lanes.length;lane++){
      if(!queue.length||activeFly().length>=flyRules.max_visible)return;
      if(queue[0].kind==='gift'){showGift(queue.shift());continue;}
      if(performance.now()>=nextAt[lane])mountFly(queue.shift(),lane,config.regions.danmaku.width);
    }
  }
  let demoIndex=4;
  const queueTimer=setInterval(drain,100);
  const demoTimer=setInterval(()=>{if(!isPaused()){const example=examples[demoIndex++%examples.length];enqueue(example.nickname,example.text);}},4200);
  document.querySelector('#demo-form').addEventListener('submit',event=>{
    event.preventDefault();const accepted=enqueue('预览观众',document.querySelector('#demo-text').value,{kind:document.querySelector('#demo-kind').value});
    setText('demo-feedback',accepted?'示例已进入展示队列':'请输入文字，或等队列空出');drain();
  });
  document.querySelector('#avatar-mode').addEventListener('change',event=>selectAvatar(event.target.value));
  document.querySelector('#chat-mode').addEventListener('change',event=>selectChat(event.target.value));
  document.querySelector('#chat-side').addEventListener('change',event=>selectChatSide(event.target.value));
  document.querySelector('#motion-toggle').addEventListener('click',()=>{manualPause=!manualPause;updatePause();});
  media.addEventListener('change',updatePause);document.addEventListener('visibilitychange',updatePause);
  for(const button of document.querySelectorAll('button[data-scene]'))button.addEventListener('click',()=>selectScene(button.dataset.scene));
  document.querySelector('#safe-toggle').addEventListener('change',event=>stage.classList.toggle('show-guides',event.target.checked));
  document.querySelector('#resolution-toggle').addEventListener('change',event=>{
    holder.classList.toggle('small-output',event.target.checked);setText('size-label',event.target.checked?'1280 × 720 · 同比例查看':'1920 × 1080 · 16:9设计画布');fit();
  });
  document.querySelector('#clean-toggle').addEventListener('click',event=>{
    const clean=document.body.classList.toggle('clean-view');event.currentTarget.setAttribute('aria-pressed',String(clean));fit();
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){document.body.classList.remove('clean-view');document.querySelector('#clean-toggle').setAttribute('aria-pressed','false');fit();}});
  function fit(){stage.style.transform='scale('+holder.clientWidth/config.canvas.width+')';}
  const resize=new ResizeObserver(fit);resize.observe(holder);fit();selectAvatar(config.avatar_default);selectChat(config.chat.default_mode);selectChatSide(config.chat.default_side);selectScene('play');updatePause();
  let settingsRoom=null,unbindPosition=null;
  const positionSource=()=>setText('chat-position-source',settingsRoom?.connected?'位置由后台控制':'后台暂未连接 · 保留当前位置');
  if(new URLSearchParams(location.search).get('room_control')==='1'&&/^https?:$/.test(location.protocol)){
    document.querySelector('#chat-side').disabled=true;
    setText('chat-position-source','正在读取后台位置…');
    settingsRoom=new RoomClient();
    unbindPosition=window.McChatPosition.bind(settingsRoom,stage,config,side=>{document.querySelector('#chat-side').value=side;});
    settingsRoom.addEventListener('connection',positionSource);
    void settingsRoom.start();
  }
  window.addEventListener('beforeunload',()=>{
    clearInterval(queueTimer);clearInterval(demoTimer);resize.disconnect();
    for(const animation of animations)animation.cancel();animations.clear();
    media.removeEventListener('change',updatePause);document.removeEventListener('visibilitychange',updatePause);
    unbindPosition?.();settingsRoom?.removeEventListener('connection',positionSource);settingsRoom?.close();
  },{once:true});
  window.mcDesign={
    selectScene,selectAvatar,selectChat,selectChatSide,config,enqueue,
    freezeForCapture(){captureFrozen=true;updatePause();},
    resumeAfterCapture(){captureFrozen=false;updatePause();},
    inspectChat(){return {mode:stage.dataset.chatMode,visible:stage.dataset.chatMode==='feed'?list.children.length:activeFly().length,pending:queue.length,paused:isPaused(),stats:{...stats}};}
  };
})();
