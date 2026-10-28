'use strict';
class RoomClient extends EventTarget {
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
  blocked(m) { const p = this.state?.settings.moderation; return m.hidden || m.blocked || !!p && (p.blocked_words.some(w => (m.text || '').toLocaleLowerCase().includes(w.toLocaleLowerCase())) || p.blocked_names.includes(m.nickname) || p.blocked_users.includes(m.user_key)); }
  now() { return Date.now() + this.offset; }
  close() { this.closed = true; this.events?.close(); clearInterval(this.timer); }
}
window.RoomClient = RoomClient;
