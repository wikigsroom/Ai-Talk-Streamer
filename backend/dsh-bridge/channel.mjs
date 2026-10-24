import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { inside } from './policy.mjs';

export function digest(value) {
  return createHash('sha256').update(typeof value === 'string' || Buffer.isBuffer(value) ? value : canonical(value)).digest('hex');
}

export function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('NON_JSON_NUMBER');
  if (value === undefined) throw new Error('NON_JSON_UNDEFINED');
  return JSON.stringify(value);
}

export function parseChannel(text) {
  const values = {};
  for (const line of text.replace(/^\uFEFF/, '').split(/\r?\n/)) {
    if (!line.trim() || line.trimStart().startsWith('#')) continue;
    const at = line.indexOf('=');
    if (at < 1) throw new Error('CHANNEL_INVALID_LINE');
    const name = line.slice(0, at).trim(), value = line.slice(at + 1).trim();
    if (name in values) throw new Error('CHANNEL_DUPLICATE_SETTING');
    if (name.startsWith('AVATAR_')) values[name] = value;
  }
  return values;
}

// The studio's existing channel.env is the only source of endpoint and credentials.
// A snapshot captures a key in a closure, so accidental JSON logging never exposes it.
export class ChannelConfig {
  constructor(projectRoot) {
    this.file = inside(projectRoot, 'configs/channel.env');
  }
  snapshot() {
    let values;
    try { values = parseChannel(readFileSync(this.file, 'utf8')); }
    catch (error) { if (error.code === 'ENOENT') throw new Error('CHANNEL_NOT_CONFIGURED'); throw error; }
    const baseUrl = values.AVATAR_LLM_BASE_URL || '';
    const model = values.AVATAR_LLM_MODEL || '';
    const key = values.AVATAR_LLM_API_KEY || '';
    const protocol = values.AVATAR_LLM_PROTOCOL || 'chat_completions';
    if (!baseUrl || !model || !key) throw new Error('CHANNEL_NOT_CONFIGURED');
    if (!['responses', 'chat_completions'].includes(protocol)) throw new Error('CHANNEL_PROTOCOL');
    let url;
    try { url = new URL(baseUrl); } catch { throw new Error('CHANNEL_URL'); }
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.hash) throw new Error('CHANNEL_URL');
    if (/[^\x21-\x7e]/.test(key)) throw new Error('CHANNEL_KEY_ENCODING');
    const revision = digest({ baseUrl, model, key, protocol, prompt: values.AVATAR_SYSTEM_PROMPT || '' });
    return Object.freeze({
      source: 'studio_channel_env', revision, provider: 'studio-default', model,
      protocol, baseUrl: baseUrl.replace(/\/$/, ''), systemPrompt: values.AVATAR_SYSTEM_PROMPT || '',
      getApiKey: () => key,
    });
  }
  publicInfo() {
    try {
      const snapshot = this.snapshot();
      return { configured: true, has_key: true, source: snapshot.source, provider: snapshot.provider, model: snapshot.model, protocol: snapshot.protocol, revision: snapshot.revision };
    } catch (error) {
      return { configured: false, has_key: false, source: 'studio_channel_env', error: /^CHANNEL_/.test(error.message) ? error.message : 'CHANNEL_READ_FAILED' };
    }
  }
}
