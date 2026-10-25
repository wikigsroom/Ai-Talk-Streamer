/** Real Livehime browser-source acceptance. Operate local recording in the
 * official client; this script never starts a public stream or calls OBS.
 * Requires an idle DSH session and the prepared 720x1280 Livehime source.
 */
import { existsSync, mkdirSync, writeFileSync, readFileSync, renameSync, openSync, closeSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { PlatformConfig } from '../backend/platforms/config.mjs';

const root = resolve(process.argv.slice(2).find(arg => !arg.startsWith('--')) || join(dirname(fileURLToPath(import.meta.url)), '..'));
const folder = join(root, 'outputs/platforms/livehime-validation');
mkdirSync(folder, { recursive: true });
if (existsSync(join(folder, 'result.json'))) renameSync(join(folder, 'result.json'), join(folder, 'result-' + Date.now() + '.json'));
const runId = 'livehime-validation-' + randomUUID();
const echoOnly = process.argv.includes('--echo-only');
const report = { schema_version: 1, run_id: runId, started_at: new Date().toISOString(),
  scope: 'official Livehime browser material, local MOSS 04/MuseTalk, DSH; local injected comments; no public streaming',
  obs_used: false, platform_audience_verified: false, cloud_llm_exercised: false, echo_only: echoOnly, steps: [], ok: false };
const wait = ms => new Promise(done => setTimeout(done, ms));
const check = (ok, code) => { if (!ok) throw Error(code); };
const save = stage => { report.stage = stage; writeFileSync(join(folder, 'result.json'), JSON.stringify(report, null, 2)); };
async function api(path, body) {
  const response = await fetch('http://127.0.0.1:8010/api/dsh' + path, {
    ...(body !== undefined ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
    signal: AbortSignal.timeout(95000),
  });
  const data = await response.json(); if (!response.ok) throw Error(data.error || 'HTTP_' + response.status); return data;
}
async function until(fn, timeout, code) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const value = await fn(); if (value) return value; await wait(300); }
  throw Error(code);
}
async function completed(key) {
  return until(async () => {
    const row = (await api('/platforms/status')).events.find(item => item.event_key === key);
    if (row && ['FAILED', 'EXPIRED', 'DROPPED', 'IGNORED', 'UNKNOWN', 'CANCELLED', 'INTERRUPTED', 'REJECTED'].includes(row.status)) throw Error('EVENT_' + row.status + '_' + (row.reason || ''));
    return row?.status === 'COMPLETED' ? row : null;
  }, 150000, 'SPEECH_COMPLETION_TIMEOUT');
}
let original, ownedOutput = false, ownedCollector = false;
let sampler, sampleLog;
const events = [];
async function message(id, text) {
  const event = { type: 'comment', event_id: runId + ':' + id, room_id: '595139', user_id: runId + ':' + id,
    nickname: '本地验收观众', text, timestamp: Date.now() };
  const started = Date.now(), ack = await api('/platforms/events', { platform: 'bilibili', event });
  const row = await completed(ack.results[0].event_key), request = await api('/requests/' + row.request_id);
  check(request.status === 'COMPLETED', 'PLAYBACK_NOT_COMPLETED');
  report.steps.push({ id, text, event_key: row.event_key, request_id: row.request_id, status: request.status,
    started_at: new Date(started).toISOString(), completed_at: new Date().toISOString(), elapsed_ms: Date.now() - started });
  events.push(event); save('completed_' + id); return row;
}
try {
  save('checking_idle');
  const state = await api('/status'), platforms = await api('/platforms/status');
  check(!state.broadcast, 'EXISTING_BROADCAST_LEFT_UNCHANGED');
  check(!platforms.outputs.some(row => ['STARTING', 'STREAMING', 'COMPANION_READY', 'MANUAL_LIVE'].includes(row.state) || row.owned_output), 'EXISTING_PLATFORM_OUTPUT_LEFT_UNCHANGED');
  original = structuredClone(new PlatformConfig(root).value);
  check(original.platforms.bilibili.output_mode === 'livehime', 'SELECT_LIVEHIME_FIRST');
  sampleLog = openSync(join(folder, 'gpu.csv'), 'w');
  sampler = spawn('nvidia-smi', ['--query-gpu=memory.used,memory.free,utilization.gpu', '--format=csv,noheader,nounits', '--loop-ms=1000'],
    { windowsHide: true, stdio: ['ignore', sampleLog, sampleLog] });
  sampler.on('error', () => {});
  await api('/platforms/config', { interaction: { enabled: true, mode: 'echo', minimum_interval_ms: 1000, viewer_cooldown_ms: 0, ttl_ms: 180000 } });
  const preflight = await api('/platforms/bilibili/preflight');
  report.preflight = preflight;
  const started = await api('/platforms/bilibili/start', {}); ownedOutput = true;
  check(started.state === 'COMPANION_READY', 'LIVEHIME_NOT_READY');
  report.broadcast_id = started.broadcast_id; save('native_source_ready');
  if (!platforms.collectors.bilibili || ['STOPPED', 'ERROR'].includes(platforms.collectors.bilibili.state)) {
    await api('/platforms/bilibili/collector/start', {}); ownedCollector = true;
  }
  await until(async () => ['CONNECTED', 'RECEIVING'].includes((await api('/platforms/status')).collectors.bilibili?.state), 25000, 'BILIBILI_HEARTBEAT_NOT_RECEIVED');
  report.real_bilibili_room = { room_id: '595139', websocket_connected: true, new_comment_verified: false };
  await message('s01_greeting', '大家好，我是林知夏。这是直播姬本地录制，人物、口型和声音都在这台电脑上生成。');
  const before = (await api('/platforms/status')).counters.duplicates || 0;
  const duplicate = await api('/platforms/events', { platform: 'bilibili', event: events[0] });
  check(duplicate.results[0].duplicate === true, 'DUPLICATE_ACCEPTED_TWICE');
  check((await api('/platforms/status')).counters.duplicates === before + 1, 'DUPLICATE_NOT_COUNTED');
  report.steps.push({ id: 's02_deduplication', duplicate: true, status: 'PASSED' }); save('duplicate_verified');
  await message('s03_explanation', '欢迎来到我的小小直播间。你可以在网页留言，我会记住当前的对话，再用自己的声音回答。');
  const current = (await api('/status')).broadcast;
  await api('/broadcast/pause', { broadcast_id: current.broadcast_id, expected_revision: current.revision });
  const pending = { type: 'comment', event_id: runId + ':paused', room_id: '595139', user_id: runId + ':paused',
    nickname: '暂停验收观众', text: '现在已经恢复互动。暂停期间的留言会等待，不会突然丢失，也不会重复播放。', timestamp: Date.now() };
  const pausedAt = Date.now(), ack = await api('/platforms/events', { platform: 'bilibili', event: pending });
  await wait(1800);
  check((await api('/platforms/status')).events.find(row => row.event_key === ack.results[0].event_key)?.status === 'PENDING', 'PAUSED_MESSAGE_WAS_CONSUMED');
  await api('/platforms/bilibili/resume', {});
  const resumed = await completed(ack.results[0].event_key);
  check((await api('/status')).broadcast.broadcast_id === current.broadcast_id, 'RESUME_CHANGED_BROADCAST');
  report.steps.push({ id: 's04_pause_resume', paused_message_not_consumed: true, same_broadcast: true,
    request_id: resumed.request_id, status: 'COMPLETED', started_at: new Date(pausedAt).toISOString(), completed_at: new Date().toISOString() }); save('resume_verified');
  if (echoOnly) {
    const queued = [
      { type: 'comment', event_id: runId + ':queue-1', room_id: '595139', user_id: runId + ':queue', nickname: '排队验收观众', text: '第一条留言，欢迎回来。', timestamp: Date.now() },
      { type: 'comment', event_id: runId + ':queue-2', room_id: '595139', user_id: runId + ':queue', nickname: '排队验收观众', text: '第二条留言，声音按顺序播放。', timestamp: Date.now() },
    ];
    const ack = await api('/platforms/events', { platform: 'bilibili', event: queued });
    const requests = [];
    for (const item of ack.results) {
      const row = await completed(item.event_key), request = await api('/requests/' + row.request_id);
      check(request.status === 'COMPLETED', 'QUEUED_PLAYBACK_NOT_COMPLETED');
      requests.push({ request_id: request.request_id, created_at: request.created_at, status: request.status });
    }
    check(requests[0].request_id !== requests[1].request_id && requests[0].created_at <= requests[1].created_at, 'QUEUE_ORDER_INVALID');
    report.steps.push({ id: 's05_ordered_queue', status: 'COMPLETED', requests, simultaneous_submission: true }); save('queue_verified');
  } else {
  if (!(await api('/status')).health.persona_injection_ready) {
    save('probing_saved_channel'); check((await api('/probe', {})).passed, 'CHANNEL_COMPATIBILITY_NOT_PASSED');
  }
  await api('/platforms/config', { interaction: { mode: 'chat' } });
  await message('s05_cloud_persona', '请只用一句简短的话，介绍你的名字，并欢迎来自B站直播间的观众。');
  report.cloud_llm_exercised = true;
  }
  report.output_player_after = (await api('/platforms/status')).output_player;
  check(report.output_player_after?.connected && report.output_player_after.audio_state === 'running', 'LIVEHIME_DISCONNECTED');
  report.ok = true;
} catch (error) { report.error = error.code || error.message; process.exitCode = 1; }
finally {
  if (sampler?.exitCode === null) { sampler.kill(); await Promise.race([new Promise(done => sampler.once('exit', done)), wait(3000)]); }
  if (sampleLog !== undefined) {
    closeSync(sampleLog);
    const samples = readFileSync(join(folder, 'gpu.csv'), 'utf8').trim().split(/\r?\n/).map(line => line.split(',').map(Number)).filter(row => row.length === 3 && row.every(Number.isFinite));
    report.gpu = { interval_ms: 1000, samples: samples.length, peak_used_mib: Math.max(0, ...samples.map(row => row[0])), minimum_free_mib: samples.length ? Math.min(...samples.map(row => row[1])) : null };
  }
  if (ownedOutput) try { await api('/platforms/bilibili/stop', {}); } catch (e) { report.cleanup_error = e.message; report.ok = false; }
  if (ownedCollector) try { await api('/platforms/bilibili/collector/stop', {}); } catch (e) { report.collector_cleanup_error = e.message; report.ok = false; }
  if (original) try { await api('/platforms/config', { interaction: original.interaction }); } catch (e) { report.restore_error = e.message; report.ok = false; }
  report.finished_at = new Date().toISOString(); save(report.ok ? 'passed' : 'failed');
  console.log(JSON.stringify({ ok: report.ok, steps: report.steps.length, error: report.error, report: 'outputs/platforms/livehime-validation/result.json' }));
}
