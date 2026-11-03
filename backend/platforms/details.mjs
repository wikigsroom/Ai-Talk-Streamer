// A platform claim stays data. Only the selected collector supplies provenance;
// payload fields cannot grant moderator rights, playback rights or game control.
export const PLATFORM_COLLECTORS = new Set(['blivedm', 'open_live']);
const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
export function platformId(value) {
  if (typeof value === 'number') return Number.isSafeInteger(value) && value >= 0 ? String(value) : null;
  return typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/u.test(value) ? value : null;
}
export const superchatId = value => platformId(value)?.replace(/^sc-/u, '') || null;
export function imageUrl(value) {
  if (typeof value !== 'string' || value.length > 1024) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password && !url.port &&
      /(?:^|\.)(?:hdslb\.com|biliimg\.com)$/u.test(url.hostname) ? url.href : null;
  } catch { return null; }
}
const boundedText = value => typeof value === 'string' && value.trim() ? value.trim().slice(0, 80) : null;
const count = value => (typeof value === 'number' || typeof value === 'string' && /^\d+$/u.test(value)) &&
  Number.isSafeInteger(Number(value)) && Number(value) >= 1 && Number(value) <= 100000 ? Number(value) : null;
function fen(value) {
  if (!['number', 'string'].includes(typeof value)) return null;
  const match = String(value).match(/^(\d{1,9})(?:\.(\d{1,2}))?$/u);
  return match ? Number(match[1]) * 100 + Number((match[2] || '').padEnd(2, '0')) : null;
}
function flag(value) { return value === true || value === 1 ? true : value === false || value === 0 ? false : null; }
function guard(value) { return Number.isInteger(value) && value >= 0 && value <= 3 ? value : null; }

export function platformDetails(platform, data, { source, type, noticeKind, messageId, danmakuInfo } = {}) {
  const trusted = platform === 'bilibili' && PLATFORM_COLLECTORS.has(source), status = {};
  const read = (name, values, convert, applicable = true, needsTrust = false) => {
    if (!applicable) { status[name] = 'not_applicable'; return null; }
    const supplied = values.find(value => value !== undefined && value !== null);
    if (supplied === undefined) { status[name] = 'missing'; return null; }
    if (needsTrust && !trusted) { status[name] = 'untrusted'; return null; }
    const result = convert(supplied); status[name] = result === null ? 'invalid' : 'known'; return result;
  };
  const gift = { name: read('gift.name', [data.gift_name, data.giftName], boundedText, type === 'gift'),
    count: read('gift.count', [data.gift_num, data.gift_count, data.num], count, type === 'gift') };
  read('event.occurred_at', [data.timestamp, data.start_time, data.occurred_at, ...(noticeKind === 'superchat' ? [] : [data.time]), danmakuInfo?.[0]?.[4]],
    value => ['string', 'number'].includes(typeof value) && Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : null);
  const superchat = noticeKind === 'superchat' ? { id: messageId || null,
    amount_fen: read('superchat.amount_fen', [data.sc_amount_yuan, data.rmb, data.price], fen, true, true), currency: 'CNY' } : null;
  if (superchat) status['superchat.id'] = messageId ? 'known' : 'missing';
  const roles = {
    moderator: read('roles.moderator', [data.is_admin, data.admin, data.user_info?.admin, danmakuInfo?.[2]?.[2]], flag, true, true),
    guard_level: read('roles.guard_level', [data.guard_level, data.user_info?.guard_level, danmakuInfo?.[7]], guard, true, true),
  };
  const emojiType = data.dm_type ?? danmakuInfo?.[0]?.[12];
  const hasEmoji = emojiType === 1 || data.emoji_url != null || !!data.emoji_img_url;
  const emoji = hasEmoji ? {
    text: read('emoji.text', [data.emoji_text, data.msg, data.text, danmakuInfo?.[1]], boundedText),
    image_url: read('emoji.image_url', [data.emoji_url, data.emoji_img_url, data.emoticon_options?.url, danmakuInfo?.[0]?.[13]?.url], imageUrl, true, true),
  } : null;
  return { schema_version: 1, quality: trusted ? 'platform_reported' : 'unverified', gift, superchat, roles, emoji,
    field_status: status, unknown_fields: Object.keys(status).filter(key => !['known', 'not_applicable'].includes(status[key])) };
}

// Explicit whitelist for the additional JSON column; DB row identity/status is
// never overwritten by a stored JSON object, including legacy or damaged rows.
export function eventDetails(event) {
  return Object.fromEntries(['notice_kind', 'gift_name', 'gift_count', 'platform_message_id', 'platform_fields',
    'deletion_target_ids', 'platform_deleted', 'test'].filter(key => own(event, key)).map(key => [key, event[key]]));
}
