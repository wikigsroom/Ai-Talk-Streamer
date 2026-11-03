import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { fixture } from './room-fixture.mjs';
import { until } from './game-fixture.mjs';
import { normalizeEvent } from '../backend/platforms/events.mjs';
const root=resolve('.'),require=createRequire(import.meta.url),{chromium}=require(process.env.PLATFORM_PLAYWRIGHT_MODULE||join(root,'node_modules/playwright-core'));
const {WebSocketServer}=createRequire(join(root,'backend/game/manager.mjs'))('ws');
const output=resolve(process.env.MC_PROGRAMME_UI_EVIDENCE_ROOT||join(root,'outputs/mc-programme-ui'));mkdirSync(output,{recursive:true});
let environmentSequence=0;
const pictures=new Map([[640,readFileSync('tests/fixtures/stream-green-640x640.h264')],[960,readFileSync('tests/fixtures/stream-blue-960x540.h264')]]);
function media(width=640){
 const annex=pictures.get(width);
 const starts=[];for(let i=0;i<annex.length-2;i++)if(annex[i]===0&&annex[i+1]===0&&(annex[i+2]===1||annex[i+2]===0&&annex[i+3]===1)){const n=annex[i+2]===1?3:4;starts.push([i,i+n]);i+=n-1}
 const units=starts.map((s,i)=>annex.subarray(s[1],starts[i+1]?.[0]??annex.length)),sps=units.find(b=>(b[0]&31)===7),pps=units.find(b=>(b[0]&31)===8),size=n=>{const b=Buffer.alloc(2);b.writeUInt16BE(n);return b};
 const avcc=Buffer.concat(units.flatMap(b=>{const h=Buffer.alloc(4);h.writeUInt32BE(b.length);return[h,b]}));
 return {init:{type:'media.init',protocol_version:3,stream_id:'fixture-'+width,media_profile_id:'fixture-'+width,width,height:width===640?640:540,fps_num:25,fps_den:1,codec:'avc1.'+sps.subarray(1,4).toString('hex'),avc_description_base64:Buffer.concat([Buffer.from([1]),sps.subarray(1,4),Buffer.from([255,225]),size(sps.length),sps,Buffer.from([1]),size(pps.length),pps]).toString('base64'),audio:{format:'s16le',sample_rate:16000,channels:1},time_base_num:1,time_base_den:1000000,pts_origin_us:0},picture:Buffer.concat([Buffer.from([65,86,67,49,1,0,0,0]),avcc])};
}
async function environment({formal=false,reduced=false,occupied=false,claimDelay=0,readyDelay=0,holdReady=false}={}){
 const posts=[],errors=[],external=[],sessions=new Set();let width=640,speech=false,held=occupied,releaseReady=null;
 const f=await fixture({handle:async(req,res,url,bridge,send)=>{
  if(req.method==='POST'&&url.pathname.startsWith('/api/dsh/game/')){posts.push({path:url.pathname});req.resume();send(res,{error:'PROGRAMME_MUST_NOT_CONTROL_GAME'},409);return true}
  if(req.method==='POST'&&['/api/dsh/platforms/output/player','/api/dsh/room/player','/api/dsh/playback/claim','/api/dsh/playback/ready','/api/dsh/playback/receipt','/api/dsh/playback/heartbeat','/api/dsh/playback/cancel-ack'].includes(url.pathname)){
   let text='';for await(const b of req)text+=b;const body=JSON.parse(text);posts.push({path:url.pathname,body});
   if(url.pathname.endsWith('output/player'))send(res,{claim:false});
   else if(url.pathname.endsWith('/claim')){speech=!body.defer_ready;held=true;if(claimDelay)await new Promise(done=>setTimeout(done,claimDelay));send(res,{lease_id:'fixture-lease',broadcast_id:'fixture-broadcast',consumer_id:body.consumer_id,authority_epoch:1,runtime_epoch:1,ready:!body.defer_ready,expires_at:new Date(Date.now()+6000).toISOString()})}else if(url.pathname.endsWith('/ready')){speech=true;if(holdReady)await new Promise(done=>{releaseReady=done});if(readyDelay)await new Promise(done=>setTimeout(done,readyDelay));send(res,{lease_id:'fixture-lease',broadcast_id:'fixture-broadcast',consumer_id:body.consumer_id,authority_epoch:1,runtime_epoch:1,ready:true,expires_at:new Date(Date.now()+6000).toISOString()})}else if(url.pathname.endsWith('/heartbeat'))send(res,{expires_at:new Date(Date.now()+6000).toISOString()});else send(res,{accepted:true});return true;
  }
  if(url.pathname==='/api/dsh/status'){send(res,{broadcast:formal?{broadcast_id:'fixture-broadcast',state:'LIVE'}:null,health:{authority_ready:held}});return true}
  if(url.pathname==='/api/dsh/game/state'){send(res,{connected:true,freshness:'fresh',mode:'MANUAL_COMMENTARY'});return true}
  if(url.pathname==='/api/dsh/game/events'){res.writeHead(200,{'Content-Type':'text/event-stream'});res.write('event: snapshot\ndata: {}\n\n');req.on('close',()=>res.end());return true}
 }});
 const wss=new WebSocketServer({server:f.server,path:'/api/studio/stream'});
 wss.on('connection',ws=>{
  const session={ws,seq:0,speechSamples:0,current:width,sent:false};sessions.add(session);
  const timer=setInterval(()=>{
   if(ws.readyState!==1)return;
   const data=media(width);
   if(session.current!==width){ws.send(JSON.stringify({type:'media.reset',protocol_version:3,old_stream_id:'fixture-'+session.current,new_stream_id:'fixture-'+width,reason:'fixture resize'}));session.current=width;session.sent=false;session.speechSamples=0}
   if(!session.sent){ws.send(JSON.stringify(data.init));session.sent=true}
   const seq=session.seq++,packet=Buffer.alloc(12+data.picture.length+1280);packet.writeUInt32LE(seq);packet.writeUInt32LE(data.picture.length,4);packet.writeUInt32LE(16000,8);data.picture.copy(packet,12);
   for(let i=0;i<640;i++)packet.writeInt16LE(Math.round(Math.sin(i*2*Math.PI*440/16000)*4000),12+data.picture.length+i*2);
   if(speech||!formal){ws.send(JSON.stringify({type:'media.map',protocol:2,request_id:'fixture-speech',utterance_id:'fixture-utterance-'+width,runtime_epoch:1,generation:1,transport_instance_id:'fixture-transport',valid_sample_count:1600000,ranges:[{packet_seq:seq,packet_offset:0,sample_start:session.speechSamples,sample_count:640}],final:false}));session.speechSamples+=640}ws.send(packet);
  },40);
  ws.on('close',()=>{clearInterval(timer);sessions.delete(session)});ws.on('error',()=>{});
 });
 const index=++environmentSequence,temp=join(root,'cache/mc-programme-browser');mkdirSync(temp,{recursive:true});
 let browser,context,page,closed=false;
 const close=async()=>{
  if(closed)return;closed=true;releaseReady?.();const cleanupErrors=[];
  const playbackDiagnostic=await page?.evaluate(()=>{const t=window.avatarTransport,d=t?.dsh;return t?{transport:t.metrics(),audio_state:t.audioContext.state,audible:t.audible,playback:d?.metrics(),utterances:d?[...d.utterances.values()].map(u=>({id:u.utterance_id,enqueued:u.enqueued,played:u.played,lost:u.lost,cancelled:u.cancelled,first_sample:u.spans[0]?.sampleStart??null})):[]}:null}).catch(()=>null);
  for(const work of [()=>context?.close(),()=>browser?.close(),async()=>{for(const s of sessions)s.ws.terminate();await new Promise(r=>wss.close(r))},()=>f.close()])try{await work()}catch(error){cleanupErrors.push(error.message)}
  const receipt=posts.find(p=>p.path.endsWith('/receipt')&&p.body.contiguous_played_samples>0)?.body||null;
  const report={classification:'LOCAL_PROGRAMME_TRANSPORT_FIXTURE_CLEANUP_ONLY',browser_started:!!browser,browser_closed:!browser?.isConnected(),page_errors:errors,external_requests:external,cleanup_errors:cleanupErrors,playback_receipt_observation:receipt,playback_diagnostic:playbackDiagnostic,real_minecraft:false,real_models:false};
  writeFileSync(join(output,'programme-cleanup-'+index+'.json'),JSON.stringify(report,null,2)+'\n');
  assert.equal(report.browser_closed,true);assert.deepEqual(cleanupErrors,[]);assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 };
 try{
  browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,env:{...process.env,TEMP:temp,TMP:temp},args:['--autoplay-policy=no-user-gesture-required','--disable-background-networking']});
  context=await browser.newContext({viewport:{width:1920,height:1080},reducedMotion:reduced?'reduce':'no-preference'});
  await context.route(/^https?:\/\//,async route=>{if(route.request().url().startsWith(f.base+'/'))await route.continue();else{external.push(route.request().url());await route.abort()}});
  page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(f.base+(formal?'/mc/programme?renderer=livehime':'/mc/preview?renderer=livehime')+'&buffer_ms=800');await page.waitForFunction(()=>window.avatarTransport?.frames>2&&window.mcOverlay?.room.connected);
 }catch(error){await close();throw error}
 const emit=(id,text,type='comment')=>f.manager.acceptPlatformEvent(normalizeEvent('bilibili',{event_id:id,type,uid:id,nickname:'观众'+id,room_id:'1',text,gift_name:'小花',gift_count:1}));
 return {f,page,posts,errors,external,sessions,emit,resize:()=>{width=960},releaseReady:()=>releaseReady?.(),close};
}

test('operator source refresh reloads the page and releases its old media connection',async()=>{
 const e=await environment();try{
  const old=await e.page.evaluate(()=>{window.oldSourceMarker=true;return avatarTransport.metricsTransportId});
  const loaded=e.page.waitForEvent('load');for(const session of e.sessions)session.ws.close(4001,'Operator requested source refresh');
  await loaded;await e.page.waitForFunction(()=>window.avatarTransport?.frames>2);
  const current=await e.page.evaluate(()=>({marker:window.oldSourceMarker,id:avatarTransport.metricsTransportId}));
  assert.equal(current.marker,undefined);assert.notEqual(current.id,old);
  await until(()=>e.sessions.size===1);assert.deepEqual(e.posts,[]);
 }finally{await e.close()}
});

test('an ordinary media interruption reconnects without reloading the programme',async()=>{
 const e=await environment();try{
  const old=await e.page.evaluate(()=>{window.keptSourceMarker=true;return avatarTransport.metricsTransportId});
  for(const session of e.sessions)session.ws.close(1012,'Upstream disconnected; reconnect');
  await e.page.waitForFunction(old=>window.avatarTransport?.frames>2&&avatarTransport.metricsTransportId!==old,old);
  assert.equal(await e.page.evaluate(()=>window.keptSourceMarker),true);await until(()=>e.sessions.size===1);
 }finally{await e.close()}
});

test('formal MC programme uses actual v3 H264, sole PCM authority and safe transparent geometry',async()=>{
 const e=await environment({formal:true});try{
  await e.page.waitForFunction(()=>avatarTransport.audible&&avatarTransport.frames>5);
  const state=await e.page.evaluate(()=>({canvas:[avatarTransport.canvas.width,avatarTransport.canvas.height],description:avatarTransport.avcConfig.description.length,protocol:avatarTransport.protocolVersion,authority:!!avatarTransport.dsh.lease,frames:avatarTransport.frames,stage:getComputedStyle(mcOverlay.stage).backgroundColor,body:getComputedStyle(document.body).backgroundColor,iframes:document.querySelectorAll('iframe,video').length,avatar:mcOverlay.avatar.getBoundingClientRect().toJSON()}));
  assert.deepEqual(state.canvas,[640,640]);assert.ok(state.description>10);assert.equal(state.protocol,3);assert.equal(state.authority,true);assert.equal(state.iframes,0);assert.equal(state.stage,'rgba(0, 0, 0, 0)');assert.equal(state.body,'rgba(0, 0, 0, 0)');assert.equal(state.avatar.x,1624);assert.equal(state.avatar.width,264);
  const player=e.posts.find(p=>p.path.endsWith('output/player')).body;
  assert.match(player.consumer_id,/^browser-/);assert.match(player.stream_metrics.transport_id,/^avatar-/);
  assert.equal(player.stream_metrics.media_stream_id,'fixture-640');assert.equal(player.stream_metrics.media_protocol_version,3);
  e.f.manager.caption={request_id:'fixture-speech',text:'这是已经提交播报的完整文字。人物字幕只跟随实际有效的声音样本。'};e.f.manager.emit();
  await e.page.waitForFunction(()=>!mcOverlay.caption.hidden&&mcOverlay.caption.textContent.length>0);
  const receipt=await until(()=>e.posts.find(p=>p.path.endsWith('/receipt')&&p.body.contiguous_played_samples>0));
  assert.ok(e.posts.some(p=>p.path.endsWith('/claim')));assert.ok(e.posts.filter(p=>p.path.endsWith('/claim')).every(p=>p.body.replace===false));
  assert.equal(receipt.body.lease_id,'fixture-lease');assert.equal(receipt.body.authority_epoch,1);assert.equal(receipt.body.generation,1);assert.equal(receipt.body.transport_instance_id,'fixture-transport');assert.equal(receipt.body.natural_end,false);
  await e.f.post('config',{expected_revision:e.f.manager.store.revision,patch:{audio:{muted:true}}});
  await e.page.waitForFunction(()=>!avatarTransport.audible&&mcOverlay.caption.hidden);
  assert.equal(await e.page.evaluate(()=>avatarTransport.outputGain.gain.value),0);
 }finally{await e.close()}
});

test('preview ignores renderer authority hints and keeps real PCM output and captions silent',async()=>{
 const e=await environment();try{
  const state=await e.page.evaluate(()=>({dsh:avatarTransport.dsh,gain:avatarTransport.outputGain.gain.value,audible:avatarTransport.audible,mixer:avatarTransport.roomMixer.audible,caption:mcOverlay.caption.hidden,preview:mcProgramme.preview}));
  assert.deepEqual(state,{dsh:null,gain:0,audible:false,mixer:false,caption:true,preview:true});assert.deepEqual(e.posts,[]);
  await e.page.setViewportSize({width:960,height:540});
  await e.page.waitForFunction(()=>mcOverlay.avatar.getBoundingClientRect().width===132);
  assert.equal(await e.page.evaluate(()=>mcOverlay.avatar.getBoundingClientRect().width),132);
 }finally{await e.close()}
});

test('formal programme preserves the first valid speech samples while the claim response is delayed',async()=>{
 const e=await environment({formal:true,claimDelay:350});try{
  const receipt=await until(()=>e.posts.find(p=>p.path.endsWith('/receipt')&&p.body.contiguous_played_samples>0));
  assert.ok(receipt.body.contiguous_played_samples>0);
  const diagnostic=await e.page.evaluate(()=>{const u=[...avatarTransport.dsh.utterances.values()][0];return{first:u?.spans[0]?.sampleStart,lost:u?.lost}});
  assert.deepEqual(diagnostic,{first:0,lost:false});
  assert.equal(e.posts.find(p=>p.path.endsWith('/claim')).body.defer_ready,true);
  assert.equal(e.posts.filter(p=>p.path.endsWith('/ready')).length,1);
 }finally{await e.close()}
});

test('closing a formal programme aborts pending readiness and a late response cannot revive authority',async()=>{
 const e=await environment({formal:true,holdReady:true});try{
  await e.page.waitForFunction(()=>avatarTransport.dsh.lease?.ready===false&&avatarTransport.dsh.requests.size===1);
  const stopped=await e.page.evaluate(()=>{window.retiredPlayer=avatarTransport.dsh;mcProgramme.close();return{ready:retiredPlayer.ready,lease:retiredPlayer.lease,requests:retiredPlayer.requests.size}});
  assert.equal(stopped.ready,false);assert.equal(stopped.lease,null);
  e.releaseReady();
  await e.page.waitForFunction(()=>retiredPlayer.requests.size===0);
  assert.equal(await e.page.evaluate(()=>retiredPlayer.lease),null);
  assert.equal(e.posts.some(p=>p.path.endsWith('/receipt')),false);
 }finally{await e.close()}
});

test('muting while readiness is pending keeps output and captions silent after the late ready response',async()=>{
 const e=await environment({formal:true,holdReady:true});try{
  await e.page.waitForFunction(()=>avatarTransport.dsh.lease?.ready===false&&avatarTransport.dsh.requests.size===1);
  await e.f.post('config',{expected_revision:e.f.manager.store.revision,patch:{audio:{muted:true}}});
  await e.page.waitForFunction(()=>roomClient.state.settings.audio.muted&&!avatarTransport.audible);
  e.releaseReady();
  await e.page.waitForFunction(()=>avatarTransport.dsh.requests.size===0&&avatarTransport.dsh.lease?.ready===true);
  const state=await e.page.evaluate(()=>({audible:avatarTransport.audible,gain:avatarTransport.outputGain.gain.value,captionHidden:mcOverlay.caption.hidden}));
  assert.deepEqual(state,{audible:false,gain:0,captionHidden:true});
  assert.equal(e.posts.some(p=>p.path.endsWith('/receipt')&&p.body.contiguous_played_samples>0),false);
 }finally{await e.close()}
});

test('four-row comments preserve nodes and queue across persisted left/right changes; hide removes active and pending text',async()=>{
 const e=await environment();try{
  for(let i=0;i<6;i++)e.emit(String(i),'一起挖矿吧！这条留言只在滚动列显示。');
  await e.page.waitForFunction(()=>mcOverlay.visible.length===4);
  await e.page.evaluate(()=>{window.kept=mcOverlay.visible.at(-1).el;window.queueBefore=mcOverlay.pending.length});
  for(const side of ['left','right']){
   await e.f.post('config',{expected_revision:e.f.manager.store.revision,patch:{overlay:{mc_chat_side:side}}});
   await e.page.waitForFunction(side=>mcOverlay.stage.dataset.chatSide===side,side);
   const s=await e.page.evaluate(()=>({same:kept.isConnected,queue:mcOverlay.pending.length,chat:mcOverlay.chat.style.left,gift:mcOverlay.gift.style.left}));assert.equal(s.same,true);assert.equal(s.chat,side==='left'?'32px':'1480px');assert.equal(s.chat,s.gift);
   await e.page.screenshot({path:join(output,'programme-'+side+'-transparent.png'),omitBackground:true});
  }
  const id=await e.page.evaluate(()=>mcOverlay.visible[0].message.id);await e.f.post('messages',{action:'hide',id});
  await e.page.waitForFunction(id=>!document.querySelector(`[data-message-id="${id}"]`),id);
  await e.f.post('config',{expected_revision:e.f.manager.store.revision,patch:{moderation:{blocked_words:['一起挖矿']}}});
  await e.page.waitForFunction(()=>mcOverlay.visible.length===0&&mcOverlay.pending.length===0);
  assert.equal(await e.page.locator('.room-board,.room-featured,iframe').count(),0);
 }finally{await e.close()}
});

test('snapshot reconnect does not replay gifts; stale/duplicate/overflow messages and real elapsed TTL are bounded',async()=>{
 const e=await environment();try{
  e.emit('gift','', 'gift');await e.page.waitForFunction(()=>!!mcOverlay.activeGift);
  await e.page.evaluate(()=>{mcOverlay.activeGift.until=performance.now()-1;mcOverlay.tick();roomClient.apply({...roomClient.state,messages:roomClient.messages});roomClient.dispatchEvent(new Event('change'))});
  assert.equal(await e.page.evaluate(()=>!!mcOverlay.activeGift),false);
  await e.page.evaluate(()=>{
   const room=roomClient,o=mcOverlay;for(let i=0;i<100;i++){const m={id:'bounded-'+i,type:'comment',nickname:'<img src=x onerror=alert(1)>',text:'🙂'.repeat(60)+'<script>bad()</script>',received_at:room.now()};room.messages.push(m);o.accept(m);o.accept(m)}
   o.accept({id:'stale',type:'comment',received_at:room.now()-30000,text:'过期'});
   window.bounds={pending:o.pending.length,seen:o.seen.size,html:o.chat.querySelectorAll('img,script').length};
   for(const e of o.pending)e.expires=performance.now()-1;for(const e of o.visible)e.until=performance.now()-1;document.dispatchEvent(new Event('visibilitychange'));
  });
  const s=await e.page.evaluate(()=>({bounds,visible:mcOverlay.visible.length,pending:mcOverlay.pending.length}));assert.equal(s.bounds.pending,24);assert.equal(s.bounds.html,0);assert.equal(s.visible,0);assert.equal(s.pending,0);
 }finally{await e.close()}
});

test('media reset resizes the real decoder, clears old PCM and captions; flying mode and scenes never post game control',async()=>{
 const e=await environment({formal:true});try{
  await e.page.waitForFunction(()=>avatarTransport.audible);const initial=await e.page.evaluate(()=>{window.oldSources=[...avatarTransport.sources].map(source=>{const state={source,ended:false};source.addEventListener('ended',()=>state.ended=true,{once:true});return state});window.oldRevision=avatarTransport.presentationRevision;return avatarTransport.mediaInit.stream_id});
  const initialTransport=await e.page.evaluate(()=>avatarTransport.metrics().transport_id);
  e.resize();await e.page.waitForFunction(()=>avatarTransport.canvas.width===960&&avatarTransport.canvas.height===540&&avatarTransport.frames>8);
  const resized=await e.page.evaluate(()=>({id:avatarTransport.mediaInit.stream_id,oldStopped:oldSources.every(s=>s.source._dshCancelled||s.ended),revision:avatarTransport.presentationRevision,decoderErrors:avatarTransport.decodeErrors}));assert.notEqual(resized.id,initial);assert.ok(resized.revision>0);assert.equal(resized.oldStopped,true);assert.equal(resized.decoderErrors,0);
  const resetReport=await until(()=>e.posts.find(p=>p.path.endsWith('output/player')&&p.body.stream_metrics.media_stream_id==='fixture-960'));
  assert.equal(resetReport.body.stream_metrics.transport_id,initialTransport);
  await e.f.post('config',{expected_revision:e.f.manager.store.revision,patch:{overlay:{danmaku:true,mc_avatar_variant:'landscape',mc_scene:'break',mc_chat_side:'left'}}});
  for(let i=0;i<6;i++)e.emit('fly'+i,'向着下一个山坡出发');
  await e.page.waitForFunction(()=>mcOverlay.visible.length>=2&&mcOverlay.visible.every(e=>e.el.classList.contains('mc-flying')));
  const s=await e.page.evaluate(()=>({feed:mcOverlay.chat.hidden,fly:mcOverlay.fly.hidden,scene:mcOverlay.stage.dataset.scene,avatar:[mcOverlay.avatar.style.left,mcOverlay.avatar.style.width],count:mcOverlay.visible.length}));assert.equal(s.feed,true);assert.equal(s.fly,false);assert.equal(s.scene,'break');assert.deepEqual(s.avatar,['1568px','320px']);assert.ok(s.count<=6);
  assert.equal(e.posts.some(p=>p.path.startsWith('/api/dsh/game/')),false);
  await e.page.screenshot({path:join(output,'programme-landscape-fly.png'),omitBackground:true});
 }finally{await e.close()}
});

test('reduced motion keeps two flying messages stationary and bounds the wait queue',async()=>{
 const e=await environment({reduced:true});try{
  await e.f.post('config',{expected_revision:e.f.manager.store.revision,patch:{overlay:{danmaku:true}}});
  for(let i=0;i<30;i++)e.emit('still'+i,'安静地一起看风景');
  await e.page.waitForFunction(()=>mcOverlay.visible.length===2&&mcOverlay.mode==='fly');
  const before=await e.page.locator('.mc-flying').first().getAttribute('style');await e.page.waitForTimeout(300);assert.equal(await e.page.locator('.mc-flying').first().getAttribute('style'),before);
  assert.ok(await e.page.evaluate(()=>mcOverlay.pending.length<=24));assert.equal(await e.page.locator('.mc-comment').count(),0);
 }finally{await e.close()}
});

test('a second formal window stays silent and cannot replace an occupied programme lease',async()=>{
 const e=await environment({formal:true,occupied:true});try{await e.page.waitForTimeout(1600);assert.equal(await e.page.evaluate(()=>avatarTransport.audible),false);assert.equal(await e.page.evaluate(()=>avatarTransport.dsh.lease),null);assert.deepEqual(e.posts,[])}finally{await e.close()}
});
