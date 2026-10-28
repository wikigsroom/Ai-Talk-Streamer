import { createHash } from 'node:crypto';
import { check } from './config.mjs';
const hash = value => createHash('sha256').update(String(value)).digest('hex');
const types = { live_comment: 'comment', live_gift: 'gift', live_like: 'like', live_fansclub: 'follow', OPEN_LIVE_DM: 'comment', OPEN_LIVE_SEND_GIFT: 'gift', OPEN_LIVE_SUPER_CHAT: 'comment', OPEN_LIVE_LIVE_START: 'live_start', OPEN_LIVE_LIVE_END: 'live_end', DANMU_MSG: 'comment', SEND_GIFT: 'gift', LIVE: 'live_start', PREPARING: 'live_end' };
export function normalizeEvent(platform, payload, { roomId = '', source = 'local_relay', sessionId = '', now = Date.now() } = {}) {
  check(['bilibili', 'douyin', 'custom'].includes(platform), 'PLATFORM_INVALID');
  check(payload && typeof payload === 'object' && !Array.isArray(payload), 'PLATFORM_EVENT_INVALID');
  const data = payload.data || payload;
  const cmd = payload.cmd?.split(':')[0];
  let type = cmd === 'SUPER_CHAT_MESSAGE' ? 'comment' : types[cmd] || types[payload.msg_type_str] || types[payload.type] || payload.type;
  let text = data.msg ?? data.content ?? data.text ?? '';
  let uid = data.open_id || data.sec_open_id || data.sec_openid || data.uid || data.user_id || data.User?.Id || '';
  let nickname = data.uname || data.nickname || data.user_name || data.User?.Nickname || '观众';
  let eventId = data.msg_id || data.message_id || data.event_id || data.dm_id || data.id_str || '';
  let timestamp = Number(data.timestamp || data.time || data.occurred_at || now);
  if (cmd === 'SUPER_CHAT_MESSAGE') { text = data.message || text; nickname = data.user_info?.uname || nickname; eventId = data.id || eventId; }
  if (payload.cmd?.startsWith('DANMU_MSG') && payload.info) { text = payload.info[1]; uid = payload.info[2]?.[0]; nickname = payload.info[2]?.[1]; timestamp = Number(payload.info[0]?.[4] || now); eventId = payload.info[0]?.[5] || ''; }
  if (payload.Type != null) { const d = typeof payload.Data === 'string' ? JSON.parse(payload.Data) : payload.Data || {}; type = ({ 1: 'comment', 2: 'like', 3: 'enter', 4: 'follow', 5: 'gift', 6: 'statistics', 7: 'fansclub', 8: 'live_end' })[payload.Type] || 'other'; text = d.Content || ''; uid = d.User?.Id || ''; nickname = d.User?.Nickname || '观众'; eventId = d.MsgId || ''; timestamp = Number(d.Timestamp || now); }
  check(['comment', 'gift', 'like', 'follow', 'enter', 'statistics', 'fansclub', 'live_start', 'live_end', 'other'].includes(type), 'PLATFORM_EVENT_TYPE_INVALID');
  const room = String(data.room_id || roomId || payload.room_id || '');
  check(room.length > 0 && room.length <= 100, 'PLATFORM_ROOM_REQUIRED');
  if (timestamp < 1e12) timestamp *= 1000;
  if (!Number.isFinite(timestamp) || timestamp < 0) timestamp = now;
  check(Math.abs(timestamp - now) <= 7 * 86400000, 'PLATFORM_EVENT_TIME_INVALID');
  const stable = uid && String(uid) !== '0' && data.identity_quality !== 'display_only';
  if (!eventId) eventId = 'derived-' + hash(JSON.stringify([room, type, uid, nickname, text, timestamp, sessionId])).slice(0, 40);
  check(String(eventId).length <= 200 && String(uid).length <= 300, 'PLATFORM_EVENT_ID_INVALID');
  return { platform, room_id: room, event_id: String(eventId), event_key: hash(JSON.stringify([platform, room, String(eventId)])), type, user_id: stable ? String(uid) : null, nickname: String(nickname).slice(0, 80), text: String(text).trim().slice(0, 1500), occurred_at: Math.trunc(timestamp), identity_quality: stable ? 'platform_id' : 'display_only', source, session_id: sessionId,
    notice_kind: ['SUPER_CHAT_MESSAGE', 'OPEN_LIVE_SUPER_CHAT'].includes(cmd) || data.notice_kind === 'superchat' ? 'superchat' : '',
    test: source === 'local_relay' && data.test === true,
    gift_count: Number.isFinite(Number(data.gift_num || data.gift_count || data.num || 1)) ? Math.min(100000, Math.max(1, Math.trunc(Number(data.gift_num || data.gift_count || data.num || 1)))) : 1, gift_name: String(data.gift_name || '礼物').slice(0, 80) };
}
export function eventPrincipal(event) {
  if (event.identity_quality !== 'platform_id') return { role: 'operator', principal_id: 'platform-public:' + event.platform + ':' + hash(event.room_id).slice(0, 20), viewer_id: 'public', public_input: true };
  const identity = event.platform + ':' + hash(JSON.stringify([event.room_id, event.user_id])).slice(0, 40);
  return { role: 'viewer', principal_id: identity, viewer_id: 'viewer:' + identity, display_name: event.nickname, public_input: false };
}
