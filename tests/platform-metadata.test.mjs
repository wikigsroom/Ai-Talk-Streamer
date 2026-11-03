import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { brotliCompressSync, deflateSync } from 'node:zlib';
import { normalizeEvent, eventPrincipal } from '../backend/platforms/events.mjs';
import { PlatformStore } from '../backend/platforms/store.mjs';
import { encodePacket, decodePackets, parsePlatformJson } from '../backend/platforms/bilibili.mjs';
import { validate } from '../backend/game/protocol.mjs';
import { narrationFixture } from './game-narration-fixture.mjs';
import { until } from './game-fixture.mjs';

const now = 1793350000000;
const event = (data, source = 'blivedm') => normalizeEvent('bilibili', { room_id:'100', timestamp:now, ...data }, { now, source });
const sc = (f, id, text = '现在有多少木头？', extra = {}) => f.platforms.ingest('bilibili', {
  type:'comment', notice_kind:'superchat', message_id:String(id), event_id:'sc-'+id, room_id:'100',
  timestamp:f.manager.wall(), user_id:'sc-viewer-'+id, nickname:'留言观众', text, sc_amount_yuan:30, ...extra,
}, { source:'blivedm' }).results[0].event_key;
const remove = (f, ids, extra = {}) => f.platforms.ingest('bilibili', { type:'delete', room_id:'100',
  timestamp:f.manager.wall(), event_id:'delete-'+ids.join('-'), deletion_target_ids:ids, ...extra }, { source:'blivedm' });

test('missing and invalid raw gift facts remain unknown rather than fabricated counts or clamped values', () => {
  const absent = event({type:'gift'});
  assert.equal(absent.gift_count,null); assert.equal(absent.gift_name,null);
  assert.equal(absent.platform_fields.field_status['gift.count'],'missing');
  for (const value of [0,-1,1.5,true,'',{},'1.5',100001,Number.MAX_SAFE_INTEGER+1]) {
    const e = event({type:'gift',gift_count:value,gift_name:'小花'});
    assert.equal(e.gift_count,null,JSON.stringify(value)); assert.equal(e.platform_fields.field_status['gift.count'],'invalid');
  }
  for (const value of [1,'2',100000]) assert.equal(event({type:'gift',gift_count:value}).gift_count,Number(value));
});

test('web SC uses original start time, exact fen and explicit false/zero roles', () => {
  const e = normalizeEvent('bilibili',{cmd:'SUPER_CHAT_MESSAGE',data:{room_id:'100',id:'45',uid:8,message:'你好',price:'30.01',start_time:(now-20000)/1000,time:60,user_info:{uname:'观众',guard_level:0,admin:0}}},{now,source:'blivedm'});
  assert.equal(e.occurred_at,now-20000); assert.equal(e.platform_fields.superchat.amount_fen,3001);
  assert.equal(e.platform_fields.roles.moderator,false); assert.equal(e.platform_fields.roles.guard_level,0);
  assert.equal(event({type:'comment',notice_kind:'superchat',message_id:'46',price:0}).platform_fields.superchat.amount_fen,0);
  for (const price of ['1.001',-1,true,{},Infinity]) assert.equal(event({type:'comment',notice_kind:'superchat',price}).platform_fields.superchat.amount_fen,null);
});

test('actual open-live command names and all three collectors share the same SC identity without rounding 64-bit strings', () => {
  const id = '9223372036854775801', data = {room_id:'100',message_id:id,msg_id:'transport-unique',open_id:'opaque/viewer+==',uname:'观众',message:'你好',rmb:30,timestamp:now/1000,guard_level:3};
  const open = normalizeEvent('bilibili',{cmd:'LIVE_OPEN_PLATFORM_SUPER_CHAT',data},{now,source:'open_live'});
  const web = normalizeEvent('bilibili',{cmd:'SUPER_CHAT_MESSAGE',data:{...data,id}},{now,source:'blivedm'});
  const normalized = event({type:'comment',notice_kind:'superchat',message_id:id,event_id:'sc-'+id});
  assert.equal(open.event_key,web.event_key); assert.equal(open.event_key,normalized.event_key);
  assert.equal(open.platform_message_id,id); assert.equal(open.user_id,data.open_id);
  assert.equal(normalizeEvent('bilibili',{cmd:'LIVE_OPEN_PLATFORM_DM',data:{...data,msg:'开采木头'}},{now,source:'open_live'}).type,'comment');
  assert.equal(normalizeEvent('bilibili',{cmd:'LIVE_OPEN_PLATFORM_SEND_GIFT',data:{...data,gift_name:'花',gift_num:2}},{now,source:'open_live'}).gift_count,2);
});

test('relay data cannot promote fake platform roles, paid amounts, image hosts or operator rights', () => {
  const e = event({type:'comment',notice_kind:'superchat',message_id:'9',user_id:'9',admin:1,guard_level:1,price:30,dm_type:1,emoji_url:'https://i0.hdslb.com/a.png',platform_fields:{quality:'platform_reported'}},'local_relay');
  assert.equal(e.platform_fields.quality,'unverified'); assert.equal(e.platform_fields.roles.moderator,null);
  assert.equal(e.platform_fields.superchat.amount_fen,null); assert.equal(e.platform_fields.emoji.image_url,null);
  assert.equal(e.platform_fields.field_status['roles.moderator'],'untrusted'); assert.equal(eventPrincipal(e).role,'viewer');
  assert.throws(()=>event({type:'delete',deletion_target_ids:['9']},'local_relay'),{code:'PLATFORM_DELETE_SOURCE_UNTRUSTED'});
});

test('emoji metadata permits only bounded HTTPS Bilibili image hosts and keeps a plain text alternative', () => {
  for (const url of ['javascript:alert(1)','https://evil.example/a.png','https://hdslb.com.evil.example/a','https://x@i0.hdslb.com/a','http://i0.hdslb.com/a','https://i0.hdslb.com:444/a']) {
    const e = event({type:'comment',dm_type:1,emoji_url:url,emoji_text:'[笑]'}); assert.equal(e.platform_fields.emoji.image_url,null,url);
  }
  const e = event({type:'comment',dm_type:1,emoji_url:'https://i0.hdslb.com/bfs/emote/a.png',emoji_text:'[笑]'});
  assert.equal(e.platform_fields.emoji.text,'[笑]'); assert.match(e.platform_fields.emoji.image_url,/hdslb\.com/);
});

test('deletion targets are bounded, canonical, deduplicated and reject already-rounded numeric IDs', () => {
  const a = event({type:'delete',deletion_target_ids:['42','sc-42','9223372036854775801']});
  assert.deepEqual(a.deletion_target_ids,['42','9223372036854775801']);
  for (const ids of [[],new Array(101).fill('1'),[Number.MAX_SAFE_INTEGER+1],[''],[{}]]) assert.throws(()=>event({type:'delete',deletion_target_ids:ids}),{code:'PLATFORM_DELETE_TARGETS_INVALID'});
});

test('platform SQLite upgrades an actual old table, retains old records and persists whitelisted metadata across reopen', async t => {
  const f = await narrationFixture(t), path = join(f.folder,'legacy-platform.sqlite3'), old = new DatabaseSync(path);
  old.exec('CREATE TABLE events(event_key TEXT PRIMARY KEY,platform TEXT NOT NULL,room_id TEXT NOT NULL,event_id TEXT NOT NULL,type TEXT NOT NULL,user_id TEXT,nickname TEXT NOT NULL,text TEXT NOT NULL,occurred_at INTEGER NOT NULL,received_at INTEGER NOT NULL,identity_quality TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,request_id TEXT,reason TEXT,session_id TEXT,UNIQUE(platform,room_id,event_id)); PRAGMA user_version=1');
  old.prepare('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)').run('old','bilibili','100','old','comment','1','旧观众','历史',now,now,'platform_id','blivedm','COMPLETED',null,null,null); old.close();
  let store = new PlatformStore(path,()=>now);
  try {
    assert.equal(store.recent()[0].status,'COMPLETED'); assert.equal(store.recent()[0].text,'历史');
    const e = event({type:'gift',gift_count:3,gift_name:'小花'}); store.insert(e,'OBSERVED'); store.close(); store = new PlatformStore(path,()=>now);
    const saved = store.recent().find(row=>row.event_key===e.event_key); assert.equal(saved.gift_count,3); assert.deepEqual(saved.platform_fields,e.platform_fields);
    assert.equal(store.get('PRAGMA user_version').user_version,3);
    store.run('UPDATE events SET detail=? WHERE event_key=?',JSON.stringify({event_key:'forged',status:'PENDING',user_id:'forged'}),'old');
    assert.equal(store.expand(store.get('SELECT * FROM events WHERE event_key=?','old')).status,'COMPLETED');
  } finally { store.close(); }
});

test('legacy Room gift values without provenance are read as unknown without rewriting the stored original', async t => {
  const f = await narrationFixture(t), value = {id:'old-gift',event_key:'old-gift',platform:'bilibili',room_id:'100',type:'gift',gift_name:'礼物',gift_count:1,nickname:'旧观众',text:'',received_at:now,occurred_at:now};
  f.room.store.run('INSERT INTO messages(id,event_key,received_at,value) VALUES (?,?,?,?)',value.id,value.id,now,JSON.stringify(value));
  const read = f.room.store.message(value.id); assert.equal(read.gift_count,null); assert.equal(read.gift_name,null);
  assert.equal(JSON.parse(f.room.store.one('SELECT value FROM messages WHERE id=?',value.id).value).gift_count,1);
});

test('known and unknown gift counts remain consistent through platform persistence, Room, merged facts and a real DSH request', async t => {
  const f = await narrationFixture(t);
  await f.comment('',{type:'gift',user_id:'same-giver',gift_name:'小花',gift_count:2});
  const added = await f.comment('',{type:'gift',user_id:'same-giver',gift_name:'小花'}), item = f.manager.narration.get(added.item.narration_id), source = f.manager.narration.source(item);
  assert.equal(source.gift_count,null); assert.equal(source.platform_fields.gift.count,null);
  assert(source.aggregation.unknown_fields.includes('gift_count'));
  await f.run(); const context = JSON.parse(f.calls[0].context); assert.equal(context.narration.source.gift_count,null); assert.equal(f.media.length,1);
});

test('SC deletion before arrival survives a platform-store restart and never becomes visible or a reply', async t => {
  const f = await narrationFixture(t); remove(f,['51']);
  f.platforms.store.close(); f.platforms.store = new PlatformStore(join(f.folder,'platforms.sqlite3'),()=>f.manager.wall());
  const key = sc(f,'51'); await f.platforms.dispatch();
  assert.equal(f.room.store.message(key).platform_deleted,true); assert.equal(f.room.store.message(key).hidden,true);
  assert.equal(f.platforms.store.get('SELECT status FROM events WHERE event_key=?',key).status,'DROPPED');
  assert.equal(f.manager.narration.all().length,0); assert.equal(f.calls.length,0);
});

test('same viewer and gift from different provenance remain separate through actual DSH facts', async t => {
  const f = await narrationFixture(t);
  const reported = await f.comment('',{type:'gift',user_id:'same-giver',gift_name:'小花',gift_count:2});
  const key = f.platforms.ingest('bilibili',{type:'gift',room_id:'100',timestamp:f.manager.wall(),event_id:'relay-gift',user_id:'same-giver',gift_name:'小花',gift_count:99},{source:'local_relay'}).results[0].event_key;
  await f.platforms.dispatch();
  const forwarded = f.manager.narration.all().find(item => (item.source_ids || [item.source_id]).includes(key));
  assert(forwarded); assert.notEqual(forwarded.narration_id,reported.item.narration_id);
  assert.equal(f.room.store.message(key).user_key,f.room.store.message(reported.key).user_key);
  assert.equal(f.manager.narration.source(reported.item).gift_count,2);
  assert.equal(f.manager.narration.source(forwarded).platform_fields.quality,'unverified');
  await f.run(); let source=JSON.parse(f.calls.at(-1).context).narration.source;
  assert.equal(source.platform_fields.quality,'platform_reported'); assert.equal(source.gift_count,2);
  f.complete(); await f.run(); source=JSON.parse(f.calls.at(-1).context).narration.source;
  assert.equal(source.platform_fields.quality,'unverified'); assert.equal(source.gift_count,99);
});

test('an untrusted recall rolls back its entire platform input batch before any Room or tombstone projection', async t => {
  const f = await narrationFixture(t), existing=sc(f,'rollback-kept'), before=f.platforms.store.get('SELECT COUNT(*) n FROM events').n;
  const creation={type:'comment',notice_kind:'superchat',message_id:'rollback-new',room_id:'100',timestamp:f.manager.wall(),text:'整批不应可见'};
  const aborted=normalizeEvent('bilibili',creation,{now:f.manager.wall(),source:'local_relay'}).event_key;
  assert.throws(()=>f.platforms.ingest('bilibili',[creation,{type:'delete',room_id:'100',deletion_target_ids:['rollback-kept']}],{source:'local_relay'}),{code:'PLATFORM_DELETE_SOURCE_UNTRUSTED'});
  assert.equal(f.platforms.store.get('SELECT COUNT(*) n FROM events').n,before);
  assert.equal(f.platforms.store.get('SELECT COUNT(*) n FROM platform_deletions').n,0);
  assert.equal(f.platforms.store.get('SELECT * FROM events WHERE event_key=?',aborted),undefined);
  assert.equal(f.room.store.message(aborted),null); assert.equal(f.room.store.message(existing).hidden,false);
});

test('a mixed creation/deletion batch is tombstoned before Room delivery and ordinary same-number comments remain intact', async t => {
  const f = await narrationFixture(t), wall = f.manager.wall();
  const ordinary = await f.comment('普通留言',{event_id:'52'});
  const results = f.platforms.ingest('bilibili',[{type:'comment',notice_kind:'superchat',message_id:'52',text:'醒目内容',timestamp:wall,room_id:'100'},
    {type:'delete',deletion_target_ids:['52'],timestamp:wall,room_id:'100'}],{source:'blivedm'});
  assert.equal(f.room.store.message(results.results[0].event_key).hidden,true); assert.equal(f.room.store.message(ordinary.key).hidden,false);
});

test('deletion scope is platform plus room and deleted SC cannot be restored or newly marked answered', async t => {
  const f = await narrationFixture(t), key = sc(f,'53'), other = sc(f,'53','另一房间',{room_id:'200'});
  await f.platforms.dispatch(); remove(f,['53']);
  assert.equal(f.room.store.message(key).hidden,true); assert.equal(f.room.store.message(other).hidden,false);
  assert.equal(f.room.store.message(key).answered,false);
  assert.throws(()=>f.room.messageControl({action:'restore',id:key}),{code:'MESSAGE_PLATFORM_DELETED'});
  assert.equal(remove(f,['53']).results[0].duplicate,true);
});

test('persisted deletion is reconciled after Room becomes available even when replies are disabled', async t => {
  const f = await narrationFixture(t), key = sc(f,'54'); f.platforms.config.value.interaction.enabled = false;
  f.bridge.room = null; remove(f,['54']);
  assert.equal(f.room.store.message(key).hidden,false);
  f.bridge.room = f.room; await f.platforms.dispatch(); assert.equal(f.room.store.message(key).platform_deleted,true);
  assert.equal(f.platforms.store.recent().find(row=>row.type==='delete').status,'RECONCILED');
});

test('deleting a merged SC during generation cancels stale text and reuses only the remaining real viewer identity', async t => {
  let entered = false, release, first = true;
  const gate = new Promise(resolve=>release=resolve);
  const f = await narrationFixture(t,async()=>{ if(first){first=false;entered=true;await gate;} return {text:'根据当前游戏信息回应。'}; });
  const key = sc(f,'55'); await f.platforms.dispatch(); const ordinary = await f.comment();
  const processing = f.run(); await until(()=>entered); remove(f,['55']); release(); await processing;
  assert.equal(f.media.length,0); assert.equal(f.room.store.message(key).answered,false);
  const item = f.manager.narration.get(ordinary.item.narration_id); assert.equal(item.state,'pending');
  const request = await f.run(); assert.equal(f.state.input(request).source.event_id,ordinary.key);
  f.complete(); await f.platforms.dispatch(); assert.equal(f.room.store.message(ordinary.key).answered,true);
  assert.equal(f.platforms.store.get('SELECT status FROM events WHERE event_key=?',key).status,'DROPPED');
});

test('deletion after a partial formal PCM receipt interrupts its generation without manufacturing completion', async t => {
  const f = await narrationFixture(t), key = sc(f,'56'); await f.platforms.dispatch(); const request = await f.run();
  const u = f.media.at(-1);
  f.state.audioReady({...u,valid_sample_count:640,audio_sha256:createHash('sha256').update('fixture-audio').digest('hex')});
  f.state.mediaMap({...u,valid_sample_count:640,transport_instance_id:'fixture-transport',ranges:[{packet_seq:1,packet_offset:0,sample_start:0,sample_count:640}],final:true});
  f.state.receipt(f.bridge.auth.resolve(),{...u,consumer_id:f.lease.consumer_id,lease_id:f.lease.lease_id,authority_epoch:f.lease.authority_epoch,receipt_sequence:1,contiguous_played_samples:320,natural_end:false,transport_instance_id:'fixture-transport'});
  assert.equal(f.state.request(request.request_id).status,'PLAYING');
  remove(f,['56']); assert.equal(f.state.request(request.request_id).status,'INTERRUPTED');
  assert.equal(f.room.store.message(key).answered,false); assert.equal(f.manager.narration.all()[0].state,'failed');
  assert.equal(f.db.get("SELECT completion_event_seq FROM utterances WHERE request_id=?",request.request_id)?.completion_event_seq,null);
});

test('an SC with unknown original time stays displayable but does not become fresh MC narration', async t => {
  const f = await narrationFixture(t); const key = sc(f,'57','旧时间未知',{timestamp:null});
  await f.platforms.dispatch(); assert.equal(f.room.store.message(key).hidden,false); assert.equal(f.manager.narration.all().length,0);
});

test('deleting a ballot retracts exactly one active vote, permits a new event and invalidates a closed promoted result', async t => {
  const f = await narrationFixture(t), state = f.manager.state.value;
  const vote = f.manager.votes.create({request_id:'metadata-vote-001',bridge_boot_id:state.bridge_boot_id,world_session_id:state.world_session_id,title:'采什么',duration_seconds:60,options:[{option_id:'wood',label:'木头',goal:{skill:'gather',item_id:'minecraft:oak_log',count:2}},{option_id:'stone',label:'石头',goal:{skill:'gather',item_id:'minecraft:cobblestone',count:2}}]}).value;
  const key = sc(f,'58','投票 wood'); assert.equal(f.manager.votes.get(vote.vote_id).options[0].votes,1);
  remove(f,['58']); let current = f.manager.votes.get(vote.vote_id); assert.equal(current.options[0].votes,0); assert.equal(current.state,'active');
  sc(f,'59','投票 stone',{user_id:'sc-viewer-58'}); current = f.manager.votes.get(vote.vote_id); assert.equal(current.options[1].votes,1);
  current = f.manager.votes.close(vote.vote_id,{request_id:'metadata-close-001',expected_revision:current.revision,action:'close',reason:'结束投票'});
  const suggestion = f.manager.votes.promote(vote.vote_id,{request_id:'metadata-promote-001',bridge_boot_id:state.bridge_boot_id,world_session_id:state.world_session_id,expected_revision:current.revision}).value;
  remove(f,['59']); current = f.manager.votes.get(vote.vote_id);
  assert.equal(current.state,'cancelled'); assert.equal(current.winning_option_id,null); assert.equal(current.options[1].votes,0);
  assert.equal(f.manager.suggestions.get(suggestion.suggestion_id).state,'cancelled'); assert.equal(f.manager.tasks.active(),null);
});

test('pending suggestions retain other visible support and cancel when their last platform source is withdrawn', async t => {
  const f = await narrationFixture(t), a = sc(f,'60','建议 采集 minecraft:oak_log 4'), b = sc(f,'61','建议 采集 minecraft:oak_log 4');
  const suggestion = f.manager.suggestions.page().items.find(value=>value.source_event_ids.includes(a)); assert(suggestion.source_event_ids.includes(b));
  remove(f,['60']); assert.equal(f.manager.suggestions.get(suggestion.suggestion_id).state,'proposed');
  remove(f,['61']); assert.equal(f.manager.suggestions.get(suggestion.suggestion_id).state,'cancelled');
});

test('32 merged viewers retain individual SC amounts within the existing model fact budget', async t => {
  const f = await narrationFixture(t);
  for(let i=0;i<32;i++) sc(f,String(100+i),'同一个问题',{nickname:'观众'.repeat(40),sc_amount_yuan:i});
  await f.platforms.dispatch(); assert.equal(f.manager.narration.open().length,1);
  await f.run(); assert.equal(f.media.length,1);
  const source = JSON.parse(f.calls[0].context).narration.source;
  assert.equal(source.aggregation.messages.length,32); assert.equal(source.aggregation.messages.at(-1).superchat.amount_fen,3100);
});

test('installed Python SDK handler NDJSON reaches the actual Node store and Room without precision loss or fake gift counts', async t => {
  const f = await narrationFixture(t), result = spawnSync(join(process.cwd(),'runtime/platforms/Scripts/python.exe'),['-X','utf8','-B','tests/platform_blivedm_protocol_checks.py','--vectors',String(f.manager.wall())],{encoding:'utf8',windowsHide:true});
  assert.equal(result.status,0,result.stderr); const values = JSON.parse(result.stdout);
  const ingested = f.platforms.ingest('bilibili',values,{source:'blivedm'});
  const messages = ingested.results.slice(0,4).map(value=>f.room.store.message(value.event_key));
  assert.equal(messages[0].platform_fields.roles.moderator,true); assert.equal(messages[0].platform_fields.roles.guard_level,3);
  assert.equal(messages[1].gift_count,3); assert.equal(messages[2].gift_count,null);
  assert.equal(messages[3].platform_message_id,'9223372036854775801'); assert.equal(messages[3].hidden,true);
});

test('deletion matches legacy numeric SC records while leaving ordinary numeric-ID messages untouched', async t => {
  const f = await narrationFixture(t), legacy = event({type:'comment',event_id:'legacy-source',text:'历史SC'});
  legacy.event_id='63'; legacy.notice_kind='superchat';
  f.platforms.store.insert(legacy,'PENDING'); f.platforms.store.run("UPDATE events SET detail='{}' WHERE event_key=?",legacy.event_key);
  f.room.acceptPlatformEvent(legacy);
  const value = f.room.store.message(legacy.event_key); delete value.platform_fields; delete value.platform_message_id;
  f.room.store.run('UPDATE messages SET value=? WHERE id=?',JSON.stringify(value),legacy.event_key);
  remove(f,['63']); assert.equal(f.room.store.message(legacy.event_key).platform_deleted,true);
  assert.equal(f.platforms.store.get('SELECT status FROM events WHERE event_key=?',legacy.event_key).status,'DROPPED');
});

test('deletion after proven completion hides the source while preserving the actual past playback history', async t => {
  const f = await narrationFixture(t), key = sc(f,'64'); await f.platforms.dispatch(); await f.run(); f.complete(); await f.platforms.dispatch();
  remove(f,['64']); assert.equal(f.room.store.message(key).hidden,true); assert.equal(f.room.store.message(key).answered,true);
  assert.equal(f.platforms.store.get('SELECT status FROM events WHERE event_key=?',key).status,'COMPLETED');
  assert.equal(f.manager.narration.all()[0].state,'answered');
});

test('raw and compressed open-live JSON preserves 64-bit numeric SC/delete IDs while leaving strings and small numbers intact', async t => {
  const f = await narrationFixture(t), seconds = Math.trunc(f.manager.wall()/1000);
  const raw = `{"cmd":"LIVE_OPEN_PLATFORM_SUPER_CHAT","data":{"room_id":100,"message_id":9223372036854775801,"uid":9223372036854775802,"uname":"观众","message":"文本里的 9223372036854775801 保持原文","rmb":30,"timestamp":${seconds}}}`;
  const packet = encodePacket(5,raw);
  for (const [version,compress] of [[2,deflateSync],[3,brotliCompressSync]]) {
    const compressed = Buffer.concat([packet.subarray(0,16),compress(packet)]); compressed.writeUInt32BE(compressed.length,0); compressed.writeUInt16BE(version,6);
    assert.equal(decodePackets(compressed)[0].data.data.message_id,'9223372036854775801');
  }
  const created = decodePackets(packet)[0].data, decoded = parsePlatformJson('{"quoted":"\\\"9223372036854775801","integer":2,"fraction":1.25,"large":9223372036854775801}');
  assert.equal(created.data.uid,'9223372036854775802'); assert.equal(decoded.integer,2); assert.equal(decoded.fraction,1.25); assert.equal(decoded.quoted,'"9223372036854775801');
  const key = f.platforms.ingest('bilibili',created,{source:'open_live'}).results[0].event_key;
  const deleted = decodePackets(encodePacket(5,'{"cmd":"LIVE_OPEN_PLATFORM_SUPER_CHAT_DEL","data":{"room_id":100,"message_ids":[9223372036854775801]}}'))[0].data;
  f.platforms.ingest('bilibili',deleted,{source:'open_live'}); assert.equal(f.room.store.message(key).hidden,true);
  assert.throws(()=>event({type:'comment',notice_kind:'superchat',message_id:Number.MAX_SAFE_INTEGER+1}),{code:'PLATFORM_SC_ID_INVALID'});
  assert.throws(()=>parsePlatformJson('{"bad":01}'));
});

test('actual public Room and normalized deletion objects satisfy the published contract without exposing raw platform identities', async t => {
  const f = await narrationFixture(t), key = sc(f,'65');
  const message = f.room.store.message(key); validate('RoomMessage',message); assert.equal(message.user_id,undefined);
  validate('PlatformDeletion',event({type:'delete',deletion_target_ids:['65']}));
  remove(f,['65']); validate('RoomMessage',f.room.store.message(key));
});

test('withdrawing a vote already converted to an approved game task preserves that task and its historical link', async t => {
  const f = await narrationFixture(t); await f.game.auto(); const state = f.manager.state.value;
  let vote = f.manager.votes.create({request_id:'metadata-history-vote',bridge_boot_id:state.bridge_boot_id,world_session_id:state.world_session_id,title:'游戏任务',duration_seconds:60,options:[{option_id:'wood',label:'木头',goal:{skill:'gather',item_id:'minecraft:oak_log',count:2}},{option_id:'stone',label:'石头',goal:{skill:'gather',item_id:'minecraft:cobblestone',count:2}}]}).value;
  sc(f,'66','投票 wood'); vote=f.manager.votes.close(vote.vote_id,{request_id:'metadata-history-close',expected_revision:vote.revision,action:'close',reason:'导播结束'});
  let suggestion = f.manager.votes.promote(vote.vote_id,{request_id:'metadata-history-promote',bridge_boot_id:state.bridge_boot_id,world_session_id:state.world_session_id,expected_revision:vote.revision}).value;
  suggestion=f.manager.suggestions.decision(suggestion.suggestion_id,{request_id:'metadata-history-approve',expected_revision:suggestion.revision,action:'accept',reason:'导播确认目标'});
  const operation = (await f.api('/suggestions/'+suggestion.suggestion_id+'/dispatch',{request_id:'metadata-history-dispatch',bridge_boot_id:state.bridge_boot_id,world_session_id:state.world_session_id,expected_control_epoch:state.control_epoch,expected_revision:suggestion.revision})).value;
  const query = await f.game.next('query',frame=>frame.payload.request.kind==='check_action'), check = f.manager.operation(query.payload.operation_id);
  f.game.send('query_result',{...check,state:'succeeded',result:{kind:'check_action',world_session_id:state.world_session_id,allowed:true}});
  await until(()=>f.manager.operation(operation.operation_id).state==='succeeded');
  const taskId=f.manager.operation(operation.operation_id).result.task_id, cancels=f.game.messages.filter(frame=>frame.type==='cancel').length;
  remove(f,['66']); assert.equal(f.manager.votes.get(vote.vote_id).state,'cancelled');
  assert.equal(f.manager.suggestions.get(suggestion.suggestion_id).state,'converted'); assert.equal(f.manager.suggestions.get(suggestion.suggestion_id).task_id,taskId);
  assert.equal(f.manager.tasks.active().task_id,taskId); assert.equal(f.game.messages.filter(frame=>frame.type==='cancel').length,cancels);
});

test('maximum bounded SC names, IDs, shared text and emote metadata fit the unchanged 16Ki model fact limit', async t => {
  const f = await narrationFixture(t);
  for(let i=0;i<32;i++) sc(f,String(i).padStart(3,'0')+'9'.repeat(197),'问'.repeat(1500),{nickname:'观'.repeat(80),admin:1,guard_level:3,dm_type:1,emoji_text:'[笑]',emoji_url:'https://i0.hdslb.com/'+ 'a'.repeat(900)});
  await f.platforms.dispatch(); assert.equal(f.manager.narration.open().length,1);
  const source = f.manager.narration.source(f.manager.narration.open()[0]); assert(JSON.stringify(source).length<=16384);
  await f.run(); assert.equal(f.media.length,1); assert.equal(JSON.parse(f.calls[0].context).narration.source.aggregation.messages.length,32);
});
