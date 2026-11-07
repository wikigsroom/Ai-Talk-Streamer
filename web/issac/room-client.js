'use strict';
class RoomClient extends EventTarget {
  static giftText(m) {
    const count = m.platform_fields?.field_status?.['gift.count'] === 'known' && Number.isSafeInteger(m.gift_count) && m.gift_count > 0 ? m.gift_count : null;
    return (m.gift_name || '礼物') + (count === null ? ' · 数量未知' : ' × ' + count);
  }
  static amount(m) {
    const f = m.platform_fields, value = f?.superchat?.amount_fen;
    return f?.quality === 'platform_reported' && f?.field_status?.['superchat.amount_fen'] === 'known' && Number.isSafeInteger(value) && value >= 0 ? '¥' + Math.floor(value / 100) + '.' + String(value % 100).padStart(2, '0') : '';
  }
  static displayName(m) {
    const f = m.platform_fields, roles = [];
    if (f?.quality === 'platform_reported') {
      if (f.roles?.moderator === true) roles.push('房管');
      const guard = {1:'总督',2:'提督',3:'舰长'}[f.roles?.guard_level]; if (guard) roles.push(guard);
    }
    return (roles.length ? roles.join('·') + ' · ' : '') + m.nickname;
  }
  static visibleGift(entry, room) {
    const sources = (entry.sources || [entry]).map(value => room.messages.find(m => m.id === value.id)).filter(value => value && !room.blocked(value));
    if (!sources.length) return null;
    const first = sources[0]; if (first.type !== 'gift') return { ...first, sources };
    const known = sources.every(value => value.platform_fields?.field_status?.['gift.count'] === 'known' && Number.isSafeInteger(value.gift_count) && value.gift_count > 0);
    const sum = sources.reduce((total, value) => total + (value.gift_count || 0), 0), valid = known && Number.isSafeInteger(sum);
    return { ...first, sources, gift_count: valid ? sum : null, platform_fields: { ...first.platform_fields, gift: { ...first.platform_fields?.gift, count: valid ? sum : null }, field_status: { ...first.platform_fields?.field_status, 'gift.count': valid ? 'known' : 'missing' } } };
  }
  static content(m) {
    if (m.platform_deleted) return '平台已撤回';
    if (m.type === 'gift') return '送来 ' + RoomClient.giftText(m);
    if (m.type === 'follow') return '关注了直播间';
    const text = m.text || m.platform_fields?.emoji?.text || (m.platform_fields?.emoji ? '[表情]' : '来到直播间');
    return m.notice_kind === 'superchat' ? RoomClient.noticeLabel(m) + (RoomClient.amount(m) ? ' ' + RoomClient.amount(m) : '') + ' · ' + text : text;
  }
  static noticeLabel(m) { return m.platform_fields?.quality === 'platform_reported' ? '醒目留言' : '转发留言'; }
  static renderText(parent, m, text = RoomClient.content(m)) {
    const raw = m.platform_fields?.quality === 'platform_reported' ? m.platform_fields?.emoji?.image_url : null;
    let safe = null; try { const u = new URL(raw); if (u.protocol === 'https:' && !u.username && !u.password && !u.port && /(?:^|\.)(?:hdslb\.com|biliimg\.com)$/u.test(u.hostname)) safe = u.href; } catch { /* use the supplied text alternative */ }
    parent.textContent = text;
    if (!safe || m.platform_deleted) return;
    const img = document.createElement('img'); img.alt = m.platform_fields.emoji.text || m.text || '[表情]'; img.src = safe; img.loading = 'lazy'; img.decoding = 'async'; img.referrerPolicy = 'no-referrer';
    Object.assign(img.style, { height:'1.4em', maxWidth:'2.4em', objectFit:'contain', verticalAlign:'middle' });
    img.addEventListener('error', () => img.remove(), { once:true }); parent.append(' ', img);
  }
  constructor() { super(); this.state = null; this.offset = 0; this.connected = false; this.closed = false; this.messages = []; }
  async start() {
    await this.refresh().catch(() => {}); if (this.closed) return this;
    this.events = new EventSource('/api/dsh/room/events');
    for (const type of ['snapshot', 'state', 'agent', 'message']) this.events.addEventListener(type, e => {
      try {
        const value = JSON.parse(e.data); this.connected = true;
        if (type === 'message') { this.messages = [...this.messages.filter(m => m.id !== value.id), value].slice(-100); if (this.state) this.state.messages = this.messages; this.dispatchEvent(new CustomEvent('message', { detail: value })); }
        else this.apply(value);
        this.dispatchEvent(new CustomEvent('change', { detail: this.state }));
      } catch { this.connected = false; }
    });
    this.events.onopen = () => { this.connected = true; this.dispatchEvent(new Event('connection')); };
    this.events.onerror = () => { this.connected = false; this.dispatchEvent(new Event('connection')); };
    this.timer = setInterval(() => { void this.refresh().catch(() => {}); }, 12000); return this;
  }
  apply(value) {
    if (!value?.settings) return;
    this.offset = value.server_time - Date.now(); if (Array.isArray(value.messages)) this.messages = value.messages;
    this.state = { ...this.state, ...value, messages: this.messages };
  }
  async refresh() { const r = await fetch('/api/dsh/room/state', { cache: 'no-store' }); if (!r.ok) throw Error('ROOM_UNAVAILABLE'); this.apply(await r.json()); this.dispatchEvent(new CustomEvent('change', { detail: this.state })); return this.state; }
  async post(path, body) {
    const response = await fetch('/api/dsh/room/' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); const value = await response.json();
    if (!response.ok) { if (response.status === 409 && value.error === 'ROOM_CONFIG_CONFLICT_REFRESH') await this.refresh(); throw Error(value.error || 'ROOM_REQUEST_FAILED'); }
    if (value.settings) { this.apply(value); this.dispatchEvent(new CustomEvent('change', { detail: this.state })); } return value;
  }
  configure(patch) { return this.post('config', { expected_revision: this.state.revision, patch }); }
  blocked(m) { const p = this.state?.settings.moderation; return m.hidden || m.blocked || m.platform_deleted || !!p && (p.blocked_words.some(w => (m.text || '').toLocaleLowerCase().includes(w.toLocaleLowerCase())) || p.blocked_names.includes(m.nickname) || p.blocked_users.includes(m.user_key)); }
  now() { return Date.now() + this.offset; }
  close() { this.closed = true; this.events?.close(); clearInterval(this.timer); }
}
window.RoomClient = RoomClient;
