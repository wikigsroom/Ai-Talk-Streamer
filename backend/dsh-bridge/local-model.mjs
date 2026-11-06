import { isIP } from 'node:net';
import { mkdirSync, writeFileSync, renameSync } from 'node:fs';
import { dirname } from 'node:path';
import { ChannelConfig } from './channel.mjs';

export function requireLocalModel(snapshot) {
  let url; try { url = new URL(snapshot.baseUrl); } catch { /* rejected below */ }
  const host = url?.hostname.toLowerCase() || '';
  const privateV4 = isIP(host) === 4 && (/^(127\.|10\.|192\.168\.)/.test(host)
    || /^172\.(1[6-9]|2\d|3[01])\./.test(host));
  if (!url || !['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.hash
      || !(host === 'localhost' || host === '[::1]' || privateV4)) {
    const error = new Error('NAIMEI_LOCAL_MODEL_REQUIRED');
    error.code = error.message; error.status = 409; throw error;
  }
}

export class NaimeiLocalChannel extends ChannelConfig {
  constructor(root) {
    super(root); this.file = this.file.replace(/channel\.env$/, 'naimei/channel.env');
  }
  snapshot() {
    const snapshot = super.snapshot(); requireLocalModel(snapshot);
    return Object.freeze({ ...snapshot, source: 'naimei_private_local_channel' });
  }
  save({ base_url: baseUrl, model, protocol = 'chat_completions', api_key: key = 'local-only' }) {
    requireLocalModel({ baseUrl });
    if (typeof model !== 'string' || !model.trim() || model.length > 200 || /[\r\n]/.test(model)
        || typeof key !== 'string' || !key || key.length > 1024 || /[^\x21-\x7e]/.test(key)
        || !['chat_completions', 'responses'].includes(protocol)) {
      const error = new Error('LOCAL_MODEL_CONFIG_INVALID'); error.code = error.message; error.status = 400; throw error;
    }
    const url = new URL(baseUrl);
    mkdirSync(dirname(this.file), { recursive: true });
    const temporary = this.file + '.' + process.pid + '.tmp';
    writeFileSync(temporary, `AVATAR_LLM_BASE_URL=${url.href.replace(/\/$/, '')}\nAVATAR_LLM_MODEL=${model.trim()}\nAVATAR_LLM_API_KEY=${key}\nAVATAR_LLM_PROTOCOL=${protocol}\n`);
    renameSync(temporary, this.file); return this.settings();
  }
  settings() {
    try {
      const value = this.snapshot();
      return { configured: true, base_url: value.baseUrl, model: value.model, protocol: value.protocol, local_only: true };
    } catch { return { configured: false, local_only: true }; }
  }
}
