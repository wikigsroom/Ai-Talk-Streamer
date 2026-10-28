'use strict';
class RoomOverlay {
  constructor(host, room, { standalone = false, layer = 'all', visual = null } = {}) {
    this.host = host; this.room = room; this.standalone = standalone; this.layer = layer; this.visual = visual; this.giftQueue = []; this.activeGift = null; this.closed = false;
    host.classList.add('room-overlay-host'); host.innerHTML = '<div class="room-scene"><div class="room-brand"><span class="room-monogram">夏</span><div><strong></strong><small>ZHIXIA · DAYLIGHT ROOM</small></div></div><span class="room-virtual">虚拟主播 · 女A</span><div class="room-topic"></div><div class="room-pin" hidden></div><div class="room-lane"></div><div class="room-chat"></div><div class="room-board" hidden><div class="label">给知夏的留言 / MESSAGE</div><div class="who"></div><div class="body"></div></div><div class="room-gift" hidden><span class="flower">✧</span><div><strong></strong><small></small></div></div><div class="room-caption" hidden></div><div class="room-announcement"></div><span class="room-mute-label" hidden>声音已静音</span><span class="room-offline" hidden></span></div>';
    this.scene = host.firstElementChild; this.find = selector => this.scene.querySelector(selector);
    this.changed = () => this.render(); this.message = e => this.incoming(e.detail); this.speech = e => { this.requestId = e.detail.request_id; this.progress = e.detail.progress || 0; this.renderCaption(); };
    room.addEventListener('change', this.changed); room.addEventListener('message', this.message); room.addEventListener('connection', this.changed); window.addEventListener('room-speech', this.speech);
    this.resize = new ResizeObserver(() => this.fit()); this.resize.observe(host); this.timer = setInterval(() => this.render(), 1000); this.render(); this.fit();
  }
  fit() { const w = this.host.clientWidth, h = this.host.clientHeight, scale = Math.min(w / 720, h / 1280); this.scene.style.transform = 'scale(' + scale + ')'; this.scene.style.left = ((w - 720 * scale) / 2) + 'px'; this.scene.style.top = ((h - 1280 * scale) / 2) + 'px'; }
  allows(name) { return this.layer === 'all' || this.layer === name; }
  incoming(message) {
    if (this.room.blocked(message)) return;
    const s = this.room.state?.settings.overlay; if (!s || !this.standalone && !s.embedded) return;
    if (s.gifts && this.allows('gifts') && (['gift', 'follow', 'fansclub'].includes(message.type) || message.notice_kind === 'superchat')) {
      const merge = this.giftQueue.find(m => m.nickname === message.nickname && m.gift_name === message.gift_name && m.type === message.type);
      if (merge && message.type === 'gift') merge.gift_count += message.gift_count;
      else this.giftQueue.push({ ...message }); if (this.giftQueue.length > 12) this.giftQueue.shift();
    }
    if (s.danmaku && message.type === 'comment' && this.allows('chat')) {
      const lane = this.find('.room-lane'); if (lane.childElementCount >= 8 || performance.now() - (this.lastFly || 0) < 1800) return;
      this.lastFly = performance.now(); const span = document.createElement('span'); span.className = 'room-fly'; span.textContent = (message.test ? '[测试] ' : '') + message.nickname + '：' + message.text.slice(0, 60); span.style.setProperty('--duration', s.danmaku_speed + 's'); lane.append(span); setTimeout(() => span.remove(), s.danmaku_speed * 1000 + 200);
    }
    this.render();
  }
  render() {
    const state = this.room.state; if (!state || this.closed) return;
    const { settings, board } = state, s = settings.overlay;
    this.host.hidden = !this.standalone && !s.embedded; this.scene.dataset.theme = s.theme; this.scene.style.opacity = s.opacity; this.scene.style.setProperty('--room-scale', s.font_scale);
    this.find('.room-brand').hidden = !s.brand || !this.allows('brand'); this.find('.room-brand strong').textContent = settings.identity.title || '林知夏'; this.find('.room-topic').textContent = settings.identity.topic;
    this.find('.room-topic').hidden = !s.brand || !this.allows('brand'); this.find('.room-virtual').hidden = !settings.identity.show_virtual_label || !this.allows('brand');
    this.find('.room-announcement').textContent = settings.identity.announcement; this.find('.room-announcement').hidden = !s.announcement || !this.allows('brand');
    this.find('.room-mute-label').hidden = !settings.audio.muted || !this.allows('brand'); this.find('.room-offline').hidden = this.room.connected;
    const pinned = board.pinned && !this.room.blocked(board.pinned) ? board.pinned : null;
    this.find('.room-pin').hidden = !pinned || !s.messages || !this.allows('messages'); this.find('.room-pin').textContent = pinned ? '置顶 · ' + pinned.nickname + '：' + pinned.text : '';
    const featured = board.featured && !this.room.blocked(board.featured) ? board.featured : null;
    this.find('.room-board').hidden = !featured || !s.messages || !this.allows('messages');
    if (featured) { this.find('.room-board .who').textContent = featured.nickname + (featured.test ? ' · 本地测试' : ''); this.find('.room-board .body').textContent = featured.text; }
    const chat = this.find('.room-chat'); chat.hidden = !s.chat || !this.allows('chat');
    const rows = this.room.messages.filter(m => m.type === 'comment' && !this.room.blocked(m) && this.room.now() - m.received_at < s.comment_lifetime * 1000).slice(-s.max_comments);
    const signature = rows.map(m => m.id).join('|');
    if (signature !== this.chatSignature) { this.chatSignature = signature; chat.replaceChildren(...rows.map(m => { const node = document.createElement('div'); node.className = 'room-comment'; const who = document.createElement('div'); who.className = 'who'; who.textContent = m.nickname + (m.test ? ' · 测试' : ''); const body = document.createElement('div'); body.className = 'body'; body.textContent = m.text; node.append(who, body); return node; })); }
    this.find('.room-lane').hidden = !s.danmaku || !this.allows('chat');
    if (!s.gifts || !this.allows('gifts')) { this.giftQueue = []; this.activeGift = null; }
    if (this.activeGift && (this.room.now() >= this.giftUntil || this.room.blocked(this.activeGift))) this.activeGift = null;
    if (!this.activeGift) { this.activeGift = this.giftQueue.shift() || null; this.giftUntil = this.room.now() + s.gift_seconds * 1000; }
    const gift = this.activeGift; this.find('.room-gift').hidden = !gift;
    if (gift) { this.find('.room-gift strong').textContent = (gift.test ? '[本地测试] ' : '') + gift.nickname; this.find('.room-gift small').textContent = gift.type === 'gift' ? '送来 ' + gift.gift_name + ' × ' + gift.gift_count : gift.notice_kind === 'superchat' ? '醒目留言 · ' + gift.text.slice(0, 32) : '谢谢你的关注与陪伴'; }
    if (this.visual) {
      const f = settings.filters; this.visual.style.filter = `brightness(${f.brightness}) contrast(${f.contrast}) saturate(${f.saturation}) sepia(${Math.max(0, f.warmth)}) hue-rotate(${Math.min(0, f.warmth) * 35}deg) blur(${f.softness}px)`;
      this.visual.style.setProperty('--vignette', f.vignette);
    }
    this.renderCaption();
  }
  renderCaption() {
    if (!this.room.state) return;
    const state = this.room.state, id = this.requestId || (this.standalone && state.player?.connected ? state.player.speaking_request_id : null), c = state.caption;
    const visible = state.settings.overlay.captions && this.allows('captions') && id && id === c?.request_id;
    let text = '';
    if (visible) {
      const chunks = c.text.match(/.{1,42}(?:[，。！？；、\s]|$)|.{1,42}/gu) || [c.text];
      const progress = this.standalone ? state.player?.speech_progress || 0 : this.progress || 0;
      const position = Math.floor(progress * c.text.length); let through = 0; text = chunks.at(-1);
      for (const chunk of chunks) { through += chunk.length; if (through > position) { text = chunk; break; } }
    }
    this.find('.room-caption').hidden = !visible; this.find('.room-caption').textContent = text;
  }
  close() { this.closed = true; clearInterval(this.timer); this.resize.disconnect(); this.room.removeEventListener('change', this.changed); this.room.removeEventListener('connection', this.changed); this.room.removeEventListener('message', this.message); window.removeEventListener('room-speech', this.speech); this.host.replaceChildren(); }
}
window.RoomOverlay = RoomOverlay;
