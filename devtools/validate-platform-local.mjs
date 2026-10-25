/** Exercise actual OBS -> loopback RTMP -> H.264/AAC, local speech and DSH.
 * Never publishes to an external platform. Run on the native media workstation.
 * Requires an idle broadcast/OBS and the project's prepared OBS scene.
 */
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync, copyFileSync, openSync, closeSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { ObsClient } from '../backend/platforms/obs.mjs';
import { PlatformConfig } from '../backend/platforms/config.mjs';

const root = resolve(process.argv[2] || join(dirname(fileURLToPath(import.meta.url)), '..'));
const folder = join(root, 'outputs/platforms/local-validation'); mkdirSync(folder, { recursive: true });
const base = 'http://127.0.0.1:8010', runId = 'platform-validation-'+randomUUID();
const report = { schema_version: 1, run_id: runId, started_at: new Date().toISOString(), scope: 'real native Windows, loopback RTMP, local MOSS 04/MuseTalk and DSH; no external platform publishing', platform_audience_verified: false, steps: [], ok: false };
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const check = (ok, code) => { if (!ok) throw Error(code); };
const save = stage => { report.stage = stage; writeFileSync(join(folder, 'result.json'), JSON.stringify(report, null, 2)); };
async function api(path, body) {
  const response = await fetch(base+'/api/dsh'+path, { ...(body !== undefined ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}), signal: AbortSignal.timeout(95000) });
  const data = await response.json(); if (!response.ok) throw Error(data.error || 'HTTP_'+response.status); return data;
}
function find(folder, name) { for (const item of readdirSync(folder, { withFileTypes: true })) { if (item.isFile() && item.name === name) return join(folder, name); if (item.isDirectory()) { const result = find(join(folder, item.name), name); if (result) return result; } } }
async function until(fn, timeout, code) { const end = Date.now()+timeout; while (Date.now()<end) { const value = await fn(); if(value)return value; await wait(250); } throw Error(code); }
async function exit(child, timeout) { if(child.exitCode !== null)return child.exitCode; return await Promise.race([new Promise(resolve=>child.once('exit',resolve)),wait(timeout).then(()=>null)]); }
const config = new PlatformConfig(root), obs = new ObsClient(root, config);
let originalConfig, previousTarget, receiver, receiverLog, touchedOutput=false, ownedCollector=false;
const cases = [];
async function message(id, platform, text) {
  const event = { type: 'comment', event_id: runId+':'+id, room_id: platform==='bilibili'?'595139':'local-validation', user_id: runId+':'+platform, nickname: '本地验收观众', text, timestamp: Date.now() };
  const started = Date.now(), ack = await api('/platforms/events', { platform, event });
  const key = ack.results[0].event_key;
  const row = await until(async () => {
    const state = await api('/platforms/status'), found = state.events.find(row=>row.event_key===key);
    if(found&&['FAILED','EXPIRED','DROPPED','IGNORED','UNKNOWN','CANCELLED','INTERRUPTED','REJECTED'].includes(found.status))throw Error('EVENT_'+found.status+'_'+(found.reason||''));
    return found?.status==='COMPLETED'?found:null;
  }, 110000, 'SPEECH_COMPLETION_TIMEOUT');
  const request = await api('/requests/'+row.request_id);
  check(request.status==='COMPLETED','PLAYBACK_NOT_COMPLETED');
  const result = { id, platform, event_key:key, request_id:row.request_id, text, status:request.status, elapsed_ms:Date.now()-started };
  report.steps.push(result); cases.push({event,platform,result}); save('completed_'+id); return result;
}

try {
  save('checking_idle_state');
  const state = await api('/status'), platforms = await api('/platforms/status');
  check(!state.broadcast,'EXISTING_BROADCAST_LEFT_UNCHANGED');
  check(!platforms.outputs.some(row=>['STARTING','STREAMING','COMPANION_READY','MANUAL_LIVE'].includes(row.state)||row.owned_output),'EXISTING_PLATFORM_OUTPUT_LEFT_UNCHANGED');
  const obsBefore = await obs.status(); check(!obsBefore.streaming&&!obsBefore.recording,'EXISTING_OBS_OUTPUT_LEFT_UNCHANGED');
  check(obsBefore.video.baseWidth===720&&obsBefore.video.baseHeight===1280,'PREPARE_OBS_FIRST');
  originalConfig = structuredClone(config.value); previousTarget = await obs.call('GetStreamServiceSettings');
  report.obs_version = obsBefore.version; report.video = obsBefore.video; report.stats_before = obsBefore.stats;
  await api('/platforms/config', { interaction: { enabled:true,mode:'echo',minimum_interval_ms:1000,viewer_cooldown_ms:0,ttl_ms:120000 }, platforms: { custom:{output_mode:'obs',comment_mode:'disabled',stream_server:'rtmp://127.0.0.1:19350/live',stream_key:'platform-validation'} } });
  const ffmpeg = find(join(root,'tools/ffmpeg'),'ffmpeg.exe'); check(ffmpeg,'FFMPEG_NOT_INSTALLED');
  receiverLog = openSync(join(folder,'rtmp-receiver.log'),'w');
  receiver = spawn(ffmpeg,['-hide_banner','-loglevel','warning','-y','-listen','1','-i','rtmp://127.0.0.1:19350/live/platform-validation','-c','copy','-f','matroska',join(folder,'native-rtmp.mkv')],{cwd:root,windowsHide:true,stdio:['pipe',receiverLog,receiverLog]});
  receiver.stdin.on('error',()=>{}); await wait(750); check(receiver.exitCode===null,'RTMP_LISTENER_FAILED');
  touchedOutput=true; const started=await api('/platforms/custom/start',{}); report.broadcast_id=started.broadcast_id;
  check(started.state==='STREAMING','OBS_NOT_STREAMING'); save('local_rtmp_streaming');
  const screenshot=await obs.call('GetSourceScreenshot',{sourceName:config.value.obs.scene,imageFormat:'png',imageWidth:720,imageHeight:1280});
  writeFileSync(join(folder,'obs-local-output.png'),Buffer.from(screenshot.imageData.split(',')[1],'base64'));
  if(!platforms.collectors.bilibili||['STOPPED','ERROR'].includes(platforms.collectors.bilibili.state)){
    await api('/platforms/bilibili/collector/start',{});ownedCollector=true;
  }
  await until(async()=>['CONNECTED','RECEIVING'].includes((await api('/platforms/status')).collectors.bilibili?.state),20000,'BILIBILI_HEARTBEAT_NOT_RECEIVED');
  report.real_bilibili_room={room_id:'595139',websocket_connected:true,new_comment_verified:false};
  await message('s01_bilibili_echo','bilibili','这是 B站接入链路的本地验收。我是林知夏，画面与声音都在这台电脑上生成。');
  const duplicatesBefore=(await api('/platforms/status')).counters.duplicates||0;
  const duplicate=await api('/platforms/events',{platform:cases[0].platform,event:cases[0].event});
  check(duplicate.results[0].duplicate===true,'DUPLICATE_ACCEPTED_TWICE');
  check((await api('/platforms/status')).counters.duplicates===duplicatesBefore+1,'DUPLICATE_NOT_COUNTED');
  report.steps.push({id:'s02_duplicate',duplicate:true,original_request_id:cases[0].result.request_id});save('duplicate_verified');
  await message('s03_douyin_echo','douyin','这是抖音接入链路的本地验收。人物在本机运行，不同平台的观众身份会分别保存。');
  const current=(await api('/status')).broadcast;await api('/broadcast/pause',{broadcast_id:current.broadcast_id,expected_revision:current.revision});
  const pending={type:'comment',event_id:runId+':paused',room_id:'595139',user_id:runId+':paused',nickname:'暂停验收观众',text:'暂停后已经恢复。这条评论只会在播放端准备好之后播出。',timestamp:Date.now()};
  const pauseAck=await api('/platforms/events',{platform:'bilibili',event:pending}); await wait(1800);
  check((await api('/platforms/status')).events.find(row=>row.event_key===pauseAck.results[0].event_key)?.status==='PENDING','PAUSED_MESSAGE_WAS_CONSUMED');
  await api('/platforms/custom/resume',{});
  const resumed=await until(async()=>{const row=(await api('/platforms/status')).events.find(row=>row.event_key===pauseAck.results[0].event_key);if(row&&['FAILED','UNKNOWN','EXPIRED'].includes(row.status))throw Error('RESUMED_EVENT_'+row.status);return row?.status==='COMPLETED'?row:null;},110000,'RESUMED_MESSAGE_NOT_COMPLETED');
  check((await api('/status')).broadcast.broadcast_id===current.broadcast_id,'RESUME_CHANGED_BROADCAST');
  report.steps.push({id:'s04_pause_resume',paused_message_not_consumed:true,broadcast_id:current.broadcast_id,request_id:resumed.request_id,status:'COMPLETED'}); save('resume_verified');
  if(!(await api('/status')).health.persona_injection_ready){save('probing_saved_llm_channel');const probe=await api('/probe',{});check(probe.passed,'CHANNEL_COMPATIBILITY_NOT_PASSED');}
  await api('/platforms/config',{interaction:{mode:'chat'}});
  await message('s05_real_ai','bilibili','请用一句话告诉我你叫什么，并和来自 B站的观众打个招呼。');
  report.stats_after=(await obs.status()).stats;
  report.local_stream=await obs.call('GetStreamStatus');
  check(report.local_stream.outputActive&&report.local_stream.outputBytes>10000,'RTMP_NOT_TRANSMITTING');
  save('stopping_local_output');
  await api('/platforms/custom/stop',{});touchedOutput=false;
  let receiverExit=await exit(receiver,10000);
  if(receiverExit===null){receiver.stdin.write('q\n');receiverExit=await exit(receiver,5000);}
  check(receiverExit===0,'RTMP_RECEIVER_DID_NOT_CLOSE_CLEANLY');
  const target=join(folder,'platform-local-validation.mp4');
  const remux=spawnSync(ffmpeg,['-nostdin','-hide_banner','-v','error','-y','-i',join(folder,'native-rtmp.mkv'),'-c','copy','-movflags','+faststart',target],{windowsHide:true,timeout:45000});
  check(remux.status===0,'VIDEO_REMUX_FAILED');
  const ffprobe=join(dirname(ffmpeg),'ffprobe.exe');
  const probe=spawnSync(ffprobe,['-v','error','-show_entries','stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate:format=duration','-of','json',target],{windowsHide:true,timeout:30000});check(probe.status===0,'FFPROBE_FAILED');
  report.media=JSON.parse(probe.stdout.toString());
  const video=report.media.streams.find(s=>s.codec_type==='video'),audio=report.media.streams.find(s=>s.codec_type==='audio');
  check(video?.codec_name==='h264'&&video.width===720&&video.height===1280&&video.r_frame_rate==='25/1'&&audio?.codec_name==='aac','ENCODED_STREAM_CONTRACT_FAILED');
  const decoded=spawnSync(ffmpeg,['-nostdin','-v','error','-i',target,'-vn','-ac','1','-ar','16000','-f','f32le','pipe:1'],{windowsHide:true,timeout:30000,maxBuffer:32*1024*1024});
  check(decoded.status===0,'AUDIO_DECODE_FAILED');let square=0,peak=0,active=0;
  for(let i=0;i+4<=decoded.stdout.length;i+=4){const value=decoded.stdout.readFloatLE(i);square+=value*value;peak=Math.max(peak,Math.abs(value));if(Math.abs(value)>.001)active++;}
  const samples=decoded.stdout.length/4;report.audio={sample_rate:16000,samples,rms:Math.sqrt(square/Math.max(1,samples)),peak,active_fraction:active/Math.max(1,samples)};
  check(report.audio.rms>.001&&report.audio.peak>.01,'ENCODED_AUDIO_IS_SILENT');
  const packets=spawnSync(ffprobe,['-v','error','-select_streams','a:0','-show_entries','packet=pts_time,duration_time','-of','json',target],{windowsHide:true,timeout:30000,maxBuffer:8*1024*1024});
  check(packets.status===0,'AUDIO_PACKET_INSPECTION_FAILED');
  const timestamps=JSON.parse(packets.stdout).packets;let maximumGap=0;
  for(let i=1;i<timestamps.length;i++)maximumGap=Math.max(maximumGap,Number(timestamps[i].pts_time)-Number(timestamps[i-1].pts_time));
  report.audio.max_packet_interval_seconds=maximumGap;check(maximumGap<.05,'ENCODED_AUDIO_TIMESTAMP_GAPS');
  const publicFolder=join(root,'src/LiveTalking/web/platform-evidence');mkdirSync(publicFolder,{recursive:true});
  copyFileSync(target,join(publicFolder,'platform-local-validation.mp4'));copyFileSync(join(folder,'obs-local-output.png'),join(publicFolder,'obs-local-output.png'));
  report.video_file='outputs/platforms/local-validation/platform-local-validation.mp4';report.video_url='/platform-evidence/platform-local-validation.mp4';report.ok=true;save('passed');
} catch(error){report.error=error.code||error.message;save('failed');process.exitCode=1;}
finally {
  if(touchedOutput)try{const row=(await api('/platforms/status')).outputs.find(r=>r.platform==='custom');if(row&&(row.owned_output||['STARTING','STREAMING','COMPANION_READY','MANUAL_LIVE'].includes(row.state)))await api('/platforms/custom/stop',{});}catch(e){report.cleanup_error=e.message;report.ok=false;}
  if(ownedCollector)try{await api('/platforms/bilibili/collector/stop',{});}catch(e){report.collector_cleanup_error=e.message;report.ok=false;}
  if(receiver&&receiver.exitCode===null){receiver.stdin.write('q\n');if(await exit(receiver,3000)===null)receiver.kill();}
  if(receiverLog!==undefined)closeSync(receiverLog);
  if(previousTarget)try{if(!(await obs.call('GetStreamStatus')).outputActive)await obs.call('SetStreamServiceSettings',previousTarget);}catch(e){report.obs_restore_error=e.message;report.ok=false;}
  if(originalConfig)try{await api('/platforms/config',{interaction:originalConfig.interaction,platforms:{custom:originalConfig.platforms.custom}});}catch(e){report.config_restore_error=e.message;report.ok=false;}
  await obs.close();report.finished_at=new Date().toISOString();save(report.ok?'passed':'failed');
  console.log(JSON.stringify({ok:report.ok,stage:report.stage,steps:report.steps.length,error:report.error,report:'outputs/platforms/local-validation/result.json'}));
}
