import { createHash, createHmac, randomUUID } from 'node:crypto';
import { brotliDecompressSync, inflateSync } from 'node:zlib';
import { PlatformError, check } from './config.mjs';

export function signBilibili(body, key, secret, { timestamp = Math.floor(Date.now() / 1000), nonce = randomUUID() } = {}) {
  const headers = { 'x-bili-accesskeyid': key, 'x-bili-content-md5': createHash('md5').update(body).digest('hex'), 'x-bili-signature-method': 'HMAC-SHA256', 'x-bili-signature-nonce': nonce, 'x-bili-signature-version': '1.0', 'x-bili-timestamp': String(timestamp) };
  const signing = Object.keys(headers).sort().map(key => key + ':' + headers[key]).join('\n');
  return { ...headers, Authorization: createHmac('sha256', secret).update(signing).digest('hex'), 'Content-Type': 'application/json', Accept: 'application/json' };
}
export function encodePacket(operation, value = '') {
  const body = Buffer.from(typeof value === 'string' ? value : JSON.stringify(value));
  const packet = Buffer.alloc(16 + body.length); packet.writeUInt32BE(packet.length, 0); packet.writeUInt16BE(16, 4); packet.writeUInt16BE(1, 6); packet.writeUInt32BE(operation, 8); packet.writeUInt32BE(1, 12); body.copy(packet, 16); return packet;
}
export function decodePackets(value, depth = 0) {
  const bytes = Buffer.from(value); check(bytes.length <= 8 * 1024 * 1024 && depth <= 4, 'BILIBILI_PACKET_LIMIT');
  const result = []; let offset = 0;
  while (offset < bytes.length) {
    check(bytes.length - offset >= 16, 'BILIBILI_PACKET_TRUNCATED');
    const length = bytes.readUInt32BE(offset), header = bytes.readUInt16BE(offset + 4), version = bytes.readUInt16BE(offset + 6), operation = bytes.readUInt32BE(offset + 8);
    check(length >= header && header >= 16 && length <= bytes.length - offset, 'BILIBILI_PACKET_LENGTH');
    const body = bytes.subarray(offset + header, offset + length); offset += length;
    if (version === 2 || version === 3) { const decode = version === 2 ? inflateSync : brotliDecompressSync; result.push(...decodePackets(decode(body, { maxOutputLength: 8 * 1024 * 1024 }), depth + 1)); }
    else if (operation === 5 || operation === 8) { try { result.push({ operation, data: JSON.parse(body.toString('utf8')) }); } catch { throw new PlatformError('BILIBILI_PACKET_JSON'); } }
    else result.push({ operation, data: null });
  }
  return result;
}
export class BilibiliOpenAdapter {
  constructor(config, { onEvent, onState, fetcher = fetch, WebSocketClass = WebSocket }) { this.config = config; this.onEvent = onEvent; this.onState = onState; this.fetcher = fetcher; this.WebSocketClass = WebSocketClass; this.stopped = true; this.cluster = 0; this.attempt = 0; }
  async api(path, payload) {
    const body = JSON.stringify(payload);
    const response = await this.fetcher('https://live-open.biliapi.com' + path, { method: 'POST', headers: signBilibili(body, this.config.access_key, this.config.access_secret), body, signal: AbortSignal.timeout(10000) });
    check(response.ok, 'BILIBILI_HTTP_' + response.status, 502);
    const result = await response.json(); check(result.code === 0, 'BILIBILI_API_' + String(result.code), 502); return result.data;
  }
  async start() {
    check(this.stopped, 'COLLECTOR_ALREADY_RUNNING');
    check(this.config.access_key && this.config.access_secret && this.config.identity_code && this.config.app_id, 'BILIBILI_OPEN_CREDENTIALS_MISSING');
    this.stopped = false; this.onState('CONNECTING');
    try {
      this.game = await this.api('/v2/app/start', { app_id: Number(this.config.app_id), code: this.config.identity_code });
      if (this.stopped) { await this.api('/v2/app/end', { app_id: Number(this.config.app_id), game_id: this.game.game_info.game_id }); return; }
      this.heartbeat = setInterval(() => { if (!this.heartbeatBusy) { this.heartbeatBusy = true; void this.api('/v2/app/heartbeat', { game_id: this.game.game_info.game_id }).catch(e => this.onState('DEGRADED', e.code || 'BILIBILI_HEARTBEAT_FAILED')).finally(() => { this.heartbeatBusy = false; }); } }, 20000);
      this.heartbeat.unref(); this.connectSocket();
    } catch (error) { await this.stop(); this.onState('ERROR', error.code || 'BILIBILI_CONNECTION_FAILED'); throw error; }
  }
  connectSocket() {
    if (this.stopped) return;
    const addresses = this.game?.websocket_info?.wss_link || []; if (!addresses.length) { this.onState('ERROR', 'BILIBILI_WSS_MISSING'); return; }
    const ws = this.ws = new this.WebSocketClass(addresses[this.cluster++ % addresses.length]); ws.binaryType = 'arraybuffer';
    let authenticated = false;
    const authDeadline = setTimeout(() => { if (!authenticated) ws.close(); }, 10000);
    ws.addEventListener('open', () => ws.send(encodePacket(7, this.game.websocket_info.auth_body)));
    ws.addEventListener('message', event => {
      try {
        for (const packet of decodePackets(event.data)) {
          if (packet.operation === 8) { check(packet.data.code === 0, 'BILIBILI_WSS_AUTH_FAILED'); authenticated = true; clearTimeout(authDeadline); this.attempt = 0; this.onState('CONNECTED'); }
          else if (packet.operation === 5) this.onEvent(packet.data, { roomId: String(this.game.anchor_info?.room_id || this.config.room_id) });
        }
      } catch (error) { this.onState('DEGRADED', error.code || 'BILIBILI_PACKET_INVALID'); ws.close(); }
    });
    clearInterval(this.socketHeartbeat); this.socketHeartbeat = setInterval(() => { if (ws.readyState === 1) ws.send(encodePacket(2)); }, 30000); this.socketHeartbeat.unref();
    ws.addEventListener('error', () => this.onState('RECONNECTING', 'BILIBILI_WSS_ERROR'));
    ws.addEventListener('close', () => {
      clearTimeout(authDeadline); clearInterval(this.socketHeartbeat);
      if (this.stopped) return; this.onState('RECONNECTING');
      this.reconnect = setTimeout(() => this.connectSocket(), Math.min(30000, 1000 * 2 ** Math.min(5, this.attempt++)) + Math.random() * 500); this.reconnect.unref();
    });
  }
  async stop() {
    this.stopped = true; clearInterval(this.heartbeat); clearInterval(this.socketHeartbeat); clearTimeout(this.reconnect); this.ws?.close();
    const game = this.game; this.game = null;
    if (game) await this.api('/v2/app/end', { app_id: Number(this.config.app_id), game_id: game.game_info.game_id }).catch(() => this.onState('ERROR', 'BILIBILI_END_NOT_ACKNOWLEDGED'));
    this.onState('STOPPED');
  }
}
