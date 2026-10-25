import { check } from './config.mjs';
export class RelayAdapter {
  constructor(config, { onEvent, onState }) { this.config = config; this.onEvent = onEvent; this.onState = onState; this.stopped = true; this.attempt = 0; }
  async start() { check(this.config.relay_url, 'RELAY_URL_REQUIRED'); this.stopped = false; this.connect(); }
  connect() {
    if (this.stopped) return; this.onState('CONNECTING');
    const ws = this.ws = new WebSocket(this.config.relay_url);
    ws.addEventListener('open', () => { this.attempt = 0; this.onState('CONNECTED'); });
    ws.addEventListener('message', event => { try { this.onEvent(JSON.parse(String(event.data)), { roomId: this.config.room_id }); this.onState('RECEIVING'); } catch { this.onState('DEGRADED', 'RELAY_MESSAGE_INVALID'); } });
    ws.addEventListener('error', () => this.onState('RECONNECTING', 'RELAY_UNAVAILABLE'));
    ws.addEventListener('close', () => { if (!this.stopped) { this.onState('RECONNECTING'); this.retry = setTimeout(() => this.connect(), Math.min(30000, 1000 * 2 ** Math.min(5, this.attempt++))); this.retry.unref(); } });
  }
  async stop() { this.stopped = true; clearTimeout(this.retry); this.ws?.close(); this.onState('STOPPED'); }
}
