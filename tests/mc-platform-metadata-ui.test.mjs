import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fixture, root } from './room-fixture.mjs';
import { PlatformManager } from '../backend/platforms/manager.mjs';
import { PlatformStore } from '../backend/platforms/store.mjs';

const executablePath='C:/Program Files/Google/Chrome/Application/chrome.exe';
const playwright=join(root,'node_modules/playwright-core');
const skip=!existsSync(executablePath)||!existsSync(playwright);
const output=resolve(process.env.MC_PLATFORM_UI_EVIDENCE_ROOT||'outputs/mc-platform-ui'); mkdirSync(output,{recursive:true});
const html='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/mc-programme.css"><body style="margin:0;background:#172b22"><div id="host" style="position:fixed;inset:0"></div><script src="/room-client.js"></script><script src="/mc-chat-position.js"></script><script src="/mc-programme-overlay.js"></script><script>const room=window.testRoom=new RoomClient();fetch("/mc/layout.json").then(r=>r.json()).then(layout=>{window.testOverlay=new MCProgrammeOverlay(document.querySelector("#host"),room,layout);room.start()});addEventListener("beforeunload",()=>{window.testOverlay?.close();room.close()});</script></body></html>';
async function withBrowser(name, work) {
  const f=await fixture({handle:async(req,res,url)=>{if(url.pathname!=='/metadata-mc')return false;res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});res.end(html);return true;}});
  const report={classification:'LOCAL_PRODUCTION_OVERLAY_CLASSES_AND_ROOM_SSE_ONLY',result:'FAIL',browser_closed:false,page_errors:[],external_requests:[],intercepted_fixture_images:0,real_minecraft:false,real_models:false,public_broadcast:false};
  let browser,context,platforms;
  try {
    platforms=new PlatformManager(f.folder,f.bridge,{config:{value:{interaction:{enabled:false,ttl_ms:30000,max_pending:100},platforms:{bilibili:{room_id:'100'}}}},store:new PlatformStore(join(f.folder,'metadata-platforms.sqlite3'))});
    let sequence=0;
    f.ingest=(data,source='blivedm')=>platforms.ingest('bilibili',{room_id:'100',timestamp:Date.now(),event_id:'ui-'+(++sequence),nickname:'观众',user_id:'viewer',...data},{source}).results[0].event_key;
    f.remove=ids=>f.ingest({type:'delete',deletion_target_ids:ids});
    const temp=join(root,'cache/mc-platform-browser');mkdirSync(temp,{recursive:true});
    browser=await createRequire(import.meta.url)(playwright).chromium.launch({executablePath,headless:true,env:{...process.env,TEMP:temp,TMP:temp},args:['--disable-gpu','--disable-background-networking']});
    context=await browser.newContext({viewport:{width:1920,height:1080},reducedMotion:'reduce'});
    await context.route(/^https?:\/\//,async route=>{
      const url=route.request().url();
      if(url.startsWith(f.base+'/'))return route.continue();
      if(url==='https://i0.hdslb.com/bfs/emote/fixture.gif'){report.intercepted_fixture_images++;return route.fulfill({contentType:'image/gif',body:Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7','base64')});}
      report.external_requests.push(url);return route.abort();
    });
    const page=await context.newPage();page.on('pageerror',error=>report.page_errors.push(error.message));
    await work(f,page,report);
    assert.deepEqual(report.page_errors,[]);assert.deepEqual(report.external_requests,[]);report.result='PASS';
  } finally {
    try {await context?.close();} finally {
      try {await browser?.close();report.browser_closed=!browser?.isConnected();}
      finally {platforms?.store.close();await f.close();writeFileSync(join(output,name+'.json'),JSON.stringify(report,null,2)+'\n');}
    }
  }
}
async function openMC(f,page) {await page.goto(f.base+'/metadata-mc');await page.waitForFunction(()=>window.testRoom?.connected&&window.testRoom?.state);}
async function configure(f,patch) {const response=await f.post('config',{expected_revision:f.manager.store.revision,patch});assert.equal(response.status,200);}

test('MC gift layer shows unknown quantities honestly, preserves plain text and keeps live content when the backend changes sides',{skip},async()=>withBrowser('mc-gift-fields',async(f,page,report)=>{
  await openMC(f,page);
  const unknown=f.ingest({type:'gift',gift_name:'<img onerror=BAD()>',guard_level:3});
  await page.waitForFunction(()=>document.querySelector('.mc-gift').textContent.includes('数量未知'));
  assert.equal(await page.locator('.mc-gift img').count(),0);assert(!(await page.locator('.mc-gift').innerText()).includes('× 1'));
  const before=await page.locator('.mc-gift').innerText();
  await configure(f,{overlay:{mc_chat_side:'left'}});await page.waitForFunction(()=>document.querySelector('.mc-stage').dataset.chatSide==='left');
  assert.equal(await page.locator('.mc-gift').innerText(),before);
  f.manager.messageControl({action:'hide',id:unknown});f.ingest({type:'gift',gift_name:'小花',gift_count:3});
  await page.waitForFunction(()=>document.querySelector('.mc-gift').textContent.includes('× 3'));
  await page.screenshot({path:join(output,'mc-gift-fields.png')});
  report.checks=['unknown_not_one','plain_text','backend_side_preserves_active_gift','known_quantity'];
}));

test('MC feed renders reported SC roles and emotes, suppresses relay claims and removes withdrawn feed and flying comments',{skip},async()=>withBrowser('mc-sc-emote-delete',async(f,page,report)=>{
  await openMC(f,page);
  const sc=f.ingest({type:'comment',notice_kind:'superchat',message_id:'701',text:'有多少木头？',sc_amount_yuan:'30.01',guard_level:3});
  const row=page.locator(`.mc-comment[data-message-id="${sc}"]`);await row.waitFor();assert.match(await row.innerText(),/舰长/u);assert.match(await row.innerText(),/¥30\.01/u);
  const emoji=f.ingest({type:'comment',text:'[笑]',dm_type:1,emoji_text:'[笑]',emoji_url:'https://i0.hdslb.com/bfs/emote/fixture.gif',admin:1});
  const emote=page.locator(`.mc-comment[data-message-id="${emoji}"] img`);await emote.waitFor();await page.waitForFunction(()=>[...document.querySelectorAll('.mc-comment img')].some(image=>image.naturalWidth>0));
  const untrusted=f.ingest({type:'comment',notice_kind:'superchat',message_id:'702',text:'金额未知的转发',sc_amount_yuan:999,guard_level:1,admin:1},'local_relay');
  const relay=page.locator(`.mc-comment[data-message-id="${untrusted}"]`);await relay.waitFor();assert(!/总督|房管|¥999/u.test(await relay.innerText()));assert.match(await relay.innerText(),/转发留言/u);
  await page.screenshot({path:join(output,'mc-sc-emote-fields.png')});f.remove(['701']);await row.waitFor({state:'detached'});
  await configure(f,{overlay:{danmaku:true}});const flying=f.ingest({type:'comment',notice_kind:'superchat',message_id:'703',text:'滚动留言',sc_amount_yuan:30});
  const fly=page.locator(`.mc-flying[data-message-id="${flying}"]`);await fly.waitFor();f.remove(['703']);await fly.waitFor({state:'detached'});
  assert.equal(report.intercepted_fixture_images,1);report.checks=['reported_role_and_fen','safe_emote_fixture','relay_claims_suppressed','feed_and_fly_deletion'];
}));

test('admin shows platform details as text, marks withdrawn SC and offers no restore or reply action',{skip},async()=>withBrowser('admin-platform-delete',async(f,page,report)=>{
  await page.goto(f.base+'/admin');await page.waitForFunction(()=>window.adminRoom?.connected);
  await page.locator('[data-page="messages"]').click();
  const key=f.ingest({type:'comment',notice_kind:'superchat',message_id:'704',nickname:'<script>BAD()</script>',text:'<img src=x onerror=BAD()>',sc_amount_yuan:'30.01',guard_level:3});
  await page.waitForFunction(()=>document.querySelector('#inbox').textContent.includes('¥30.01'));
  assert.equal(await page.locator('#inbox img,#inbox script').count(),0);assert.equal(await page.evaluate(()=>window.BAD),undefined);
  assert.match(await page.locator('#inbox').innerText(),/舰长/u);
  f.remove(['704']);await page.waitForFunction(()=>document.querySelector('#inbox').textContent.includes('平台已撤回'));
  assert.equal(await page.locator('#inbox [data-action="message-restore"],#inbox [data-action="message-reply"]').count(),0);
  const restored=await f.post('messages',{action:'restore',id:key});assert.equal(restored.status,400);assert.equal(restored.value.error,'MESSAGE_PLATFORM_DELETED');
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  await page.screenshot({path:join(output,'admin-platform-delete-phone.png'),fullPage:true});report.checks=['real_room_sse','plain_text_details','deleted_no_restore_or_reply','actual_restore_refused','phone_no_overflow'];
}));

test('legacy overlay separates identical nicknames and recomputes merged gifts after a source is hidden',{skip},async()=>withBrowser('legacy-gift-source-visibility',async(f,page,report)=>{
  await page.goto(f.base+'/overlay');await page.waitForFunction(()=>typeof roomClient!=='undefined'&&roomClient.connected);
  const unknown=f.ingest({type:'gift',nickname:'同名观众',gift_name:'小花'});await page.waitForFunction(()=>document.querySelector('.room-gift small').textContent.includes('数量未知'));
  const first=f.ingest({type:'gift',nickname:'同名观众',user_id:'viewer-a',gift_name:'小花',gift_count:2});
  const second=f.ingest({type:'gift',nickname:'同名观众',user_id:'viewer-b',gift_name:'小花',gift_count:3});
  const third=f.ingest({type:'gift',nickname:'同名观众',user_id:'viewer-b',gift_name:'小花',gift_count:4});
  const forwarded=f.ingest({type:'gift',nickname:'同名观众',user_id:'viewer-b',gift_name:'小花',gift_count:99},'local_relay');
  f.manager.messageControl({action:'hide',id:unknown});await page.waitForFunction(()=>document.querySelector('.room-gift small').textContent.includes('× 2'));
  f.manager.messageControl({action:'hide',id:first});await page.waitForFunction(()=>document.querySelector('.room-gift small').textContent.includes('× 7'));
  f.manager.messageControl({action:'hide',id:second});await page.waitForFunction(()=>document.querySelector('.room-gift small').textContent.includes('× 4'));
  f.manager.messageControl({action:'hide',id:third});await page.waitForFunction(()=>document.querySelector('.room-gift small').textContent.includes('× 99'));
  f.manager.messageControl({action:'hide',id:forwarded});await page.waitForFunction(()=>document.querySelector('.room-gift').hidden);
  report.checks=['unknown_quantity','identity_not_nickname','known_sum','hidden_member_recomputed','last_source_removed'];
}));
