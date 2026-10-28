export class RoomError extends Error {
  constructor(code, status = 400) { super(code); this.code = code; this.status = status; }
}
export const check = (ok, code, status = 400) => { if (!ok) throw new RoomError(code, status); };
export const THEMES = ['daylight', 'paper', 'evening'];
export const DEFAULTS = {
  identity: { title: '知夏的日光宿舍', topic: '一起聊聊今天的小事', announcement: '欢迎来到知夏的小房间 · 我是虚拟主播林知夏', show_virtual_label: true },
  audio: { music_volume: 0.22, speech_volume: 1, muted: false, ducking: true, duck_level: 0.23, attack_ms: 90, release_ms: 650 },
  filters: { preset: 'daylight', brightness: 1, contrast: 1, saturation: 1, warmth: 0, softness: 0, vignette: 0.06 },
  overlay: { theme: 'daylight', embedded: true, brand: true, chat: true, danmaku: false, messages: true, gifts: true, captions: true, announcement: true, opacity: 0.92, font_scale: 1, max_comments: 3, comment_lifetime: 20, danmaku_speed: 12, gift_seconds: 7, auto_board: false },
  moderation: { blocked_words: [], blocked_names: [], blocked_users: [] },
};
const string = (v, n) => typeof v === 'string' && v.length <= n && !/[\u0000-\u0008]/.test(v);
const range = (lo, hi) => v => typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi;
const boolean = v => typeof v === 'boolean';
const one = values => v => values.includes(v);
const rules = {
  identity: { title: v => string(v, 40), topic: v => string(v, 80), announcement: v => string(v, 240), show_virtual_label: boolean },
  audio: { music_volume: range(0, 1), speech_volume: range(0, 1.5), muted: boolean, ducking: boolean, duck_level: range(0, 1), attack_ms: range(20, 1000), release_ms: range(100, 3000) },
  filters: { preset: one(['daylight', 'clean', 'warm', 'soft', 'custom']), brightness: range(0.65, 1.35), contrast: range(0.7, 1.4), saturation: range(0, 1.6), warmth: range(-0.5, 0.5), softness: range(0, 1.2), vignette: range(0, 0.6) },
  overlay: { theme: one(THEMES), embedded: boolean, brand: boolean, chat: boolean, danmaku: boolean, messages: boolean, gifts: boolean, captions: boolean, announcement: boolean, opacity: range(0.3, 1), font_scale: range(0.8, 1.3), max_comments: v => Number.isInteger(v) && v >= 1 && v <= 5, comment_lifetime: range(5, 90), danmaku_speed: range(6, 24), gift_seconds: range(3, 20), auto_board: boolean },
  moderation: Object.fromEntries(['blocked_words', 'blocked_names', 'blocked_users'].map(k => [k, v => Array.isArray(v) && v.length <= 200 && v.every(s => string(s, k === 'blocked_users' ? 100 : 80) && s.trim())])),
};
export function patchSettings(current, patch) {
  check(patch && typeof patch === 'object' && !Array.isArray(patch), 'ROOM_CONFIG_INVALID');
  const result = structuredClone(current);
  for (const [group, values] of Object.entries(patch)) {
    check(Object.hasOwn(rules, group) && values && typeof values === 'object' && !Array.isArray(values), 'ROOM_CONFIG_GROUP_INVALID');
    for (const [key, value] of Object.entries(values)) {
      check(Object.hasOwn(rules[group], key) && rules[group][key](value), 'ROOM_CONFIG_VALUE_INVALID:' + group + '.' + key);
      result[group][key] = typeof value === 'string' ? value.trim() : Array.isArray(value) ? [...new Set(value.map(s => s.trim()))] : value;
    }
  }
  return result;
}
export function isBlocked(settings, event) {
  const m = settings.moderation, text = (event.text || '').toLocaleLowerCase();
  return m.blocked_words.some(w => text.includes(w.toLocaleLowerCase())) || m.blocked_names.includes(event.nickname) || !!event.user_key && m.blocked_users.includes(event.user_key);
}
export const FILTERS = {
  daylight: { preset: 'daylight', brightness: 1, contrast: 1, saturation: 1, warmth: 0, softness: 0, vignette: 0.06 },
  clean: { preset: 'clean', brightness: 1.04, contrast: 0.98, saturation: 0.92, warmth: -0.04, softness: 0, vignette: 0 },
  warm: { preset: 'warm', brightness: 1.02, contrast: 0.97, saturation: 0.97, warmth: 0.16, softness: 0, vignette: 0.1 },
  soft: { preset: 'soft', brightness: 1.04, contrast: 0.94, saturation: 0.94, warmth: 0.06, softness: 0.25, vignette: 0.08 },
};
