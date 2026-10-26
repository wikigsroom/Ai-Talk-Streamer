import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

export class PlatformError extends Error {
  constructor(code, status = 409) { super(code); this.code = code; this.status = status; }
}
export function check(value, code, status = 400) { if (!value) throw new PlatformError(code, status); }
export const PLATFORM_IDS = ['bilibili', 'douyin', 'custom'];
const SECRET_FIELDS = ['stream_key', 'cookie', 'access_key', 'access_secret', 'identity_code', 'callback_secret'];
export function defaults() {
  return { version: 1, obs: { url: 'ws://127.0.0.1:4457', scene: 'AiTalk Vertical', input: 'AiTalk Avatar', width: 720, height: 1280, fps: 25, bitrate: 5000 },
    interaction: { enabled: true, mode: 'chat', minimum_interval_ms: 8000, viewer_cooldown_ms: 15000, ttl_ms: 45000, max_pending: 50 },
    platforms: Object.fromEntries(PLATFORM_IDS.map(platform => [platform, { room_id: '', room_url: '', output_mode: platform === 'bilibili' ? 'livehime' : platform === 'douyin' ? 'companion' : 'obs', client_location: 'same_device', receiver_url: 'http://127.0.0.1:8020', comment_mode: platform==='bilibili'?'blivedm':platform==='custom'?'relay':'browser', stream_server: '', stream_key: '', cookie: '', access_key: '', access_secret: '', identity_code: '', app_id: '', callback_secret: '', relay_url: '', item_selector: '', user_selector: '', text_selector: '' }])) };
}
export function roomUrl(platform, value) {
  const text = String(value || '').trim();
  if (!text) return '';
  if (/^\d{1,24}$/.test(text)) return `https://${platform === 'bilibili' ? 'live.bilibili.com' : 'live.douyin.com'}/${text}`;
  let url; try { url = new URL(text); } catch { throw new PlatformError('ROOM_URL_INVALID', 400); }
  check(['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !url.port && (platform === 'bilibili' ? url.hostname === 'live.bilibili.com' : url.hostname === 'live.douyin.com'), 'ROOM_URL_INVALID');
  url.protocol='https:';
  return url.origin + url.pathname;
}
export class PlatformConfig {
  constructor(root) { this.root = root; this.path = join(root, 'configs/platforms.private.json'); this.value = defaults(); this.reload(); }
  reload() {
    if (!existsSync(this.path)) return;
    const saved = JSON.parse(readFileSync(this.path, 'utf8').replace(/^\uFEFF/, ''));
    const base = defaults();
    this.value = { ...base, ...saved, obs: { ...base.obs, ...saved.obs }, interaction: { ...base.interaction, ...saved.interaction }, platforms: Object.fromEntries(PLATFORM_IDS.map(p => [p, { ...base.platforms[p], ...saved.platforms?.[p] }])) };
  }
  update(patch) {
    check(patch && typeof patch === 'object' && !Array.isArray(patch), 'PLATFORM_CONFIG_INVALID');
    const next = structuredClone(this.value);
    if (patch.interaction) {
      for (const key of ['enabled']) if (key in patch.interaction) { check(typeof patch.interaction[key] === 'boolean', 'INTERACTION_CONFIG_INVALID'); next.interaction[key] = patch.interaction[key]; }
      if ('mode' in patch.interaction) { check(['chat', 'echo'].includes(patch.interaction.mode), 'INTERACTION_MODE_INVALID'); next.interaction.mode = patch.interaction.mode; }
      for (const [key, min, max] of [['minimum_interval_ms', 0, 600000], ['viewer_cooldown_ms', 0, 3600000], ['ttl_ms', 1000, 300000], ['max_pending', 1, 200]]) if (key in patch.interaction) { check(Number.isSafeInteger(patch.interaction[key]) && patch.interaction[key] >= min && patch.interaction[key] <= max, 'INTERACTION_CONFIG_INVALID'); next.interaction[key] = patch.interaction[key]; }
    }
    for (const platform of PLATFORM_IDS) {
      const incoming = patch.platforms?.[platform]; if (!incoming) continue;
      const target = next.platforms[platform];
      if ('room_id' in incoming && !('room_url' in incoming)) target.room_url='';
      for (const key of Object.keys(target)) if (key in incoming) {
        const val = incoming[key];
        if (SECRET_FIELDS.includes(key) && val === '') continue;
        if (SECRET_FIELDS.includes(key) && val === null) { target[key] = ''; continue; }
        check(typeof val === 'string' && val.length <= (key === 'cookie' ? 16000 : 4096), 'PLATFORM_CONFIG_INVALID'); target[key] = val.trim();
      }
      check(['obs', 'companion', 'livehime'].includes(target.output_mode) && (target.output_mode !== 'livehime' || platform === 'bilibili'), 'OUTPUT_MODE_INVALID');
      check(['same_device', 'receiver'].includes(target.client_location) && (target.client_location !== 'receiver' || platform === 'bilibili' && target.output_mode === 'livehime'), 'CLIENT_LOCATION_INVALID');
      if (target.receiver_url) {
        let receiver; try { receiver = new URL(target.receiver_url); } catch { throw new PlatformError('RECEIVER_URL_INVALID', 400); }
        check(['http:', 'https:'].includes(receiver.protocol) && !receiver.username && !receiver.password && receiver.pathname === '/' && !receiver.search && !receiver.hash, 'RECEIVER_URL_INVALID');
        target.receiver_url = receiver.origin;
      }
      check(['browser', 'blivedm', 'open_live', 'official_callback', 'relay', 'disabled'].includes(target.comment_mode), 'COMMENT_MODE_INVALID');
      if (platform !== 'custom') {
        target.room_url = roomUrl(platform, target.room_url || target.room_id);
        const id = target.room_url && new URL(target.room_url).pathname.match(/\/(\d+)\/?$/);
        if(id)target.room_id=id[1];
      }
      if (target.stream_server) { let url; try { url = new URL(target.stream_server); } catch { throw new PlatformError('STREAM_SERVER_INVALID', 400); } check(['rtmp:', 'rtmps:'].includes(url.protocol), 'STREAM_SERVER_INVALID'); }
      if (target.relay_url) check(/^wss?:\/\//.test(target.relay_url), 'RELAY_URL_INVALID');
      if (target.app_id) check(/^\d{1,16}$/.test(target.app_id) && Number.isSafeInteger(Number(target.app_id)), 'BILIBILI_APP_ID_INVALID');
    }
    mkdirSync(dirname(this.path), { recursive: true });
    writeFileSync(this.path + '.tmp', JSON.stringify(next, null, 2), { mode: 0o600 }); renameSync(this.path + '.tmp', this.path); this.value = next;
    return this.public();
  }
  public() {
    const result = structuredClone(this.value);
    for (const p of PLATFORM_IDS) for (const key of SECRET_FIELDS) { result.platforms[p]['has_' + key] = !!result.platforms[p][key]; delete result.platforms[p][key]; }
    return result;
  }
}
