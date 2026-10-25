import { createRequire } from 'node:module';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { check } from './config.mjs';

export const CHAT_SELECTORS = {
  bilibili: { item: '.chat-item.danmaku-item', user: '.user-name', text: '.danmaku-content' },
  douyin: { item: '.webcast-chatroom___item', user: '.webcast-chatroom___user-name', text: '.webcast-chatroom___content-with-emoji-text' }
};
// Runs inside an ordinary logged-in browser page. It reads rendered comments;
// it does not call private signing services or modify platform requests.
export function observeChat({ selectors, roomId, sessionId, binding = 'aiTalkPlatformMessage' }) {
  window.__aiTalkChatObserver?.stop();
  const seen = new WeakMap(); let sequence = 0,observed=0;
  const instanceId=sessionId+':'+(globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+Math.random().toString(36).slice(2));
  function read(node, initial = false) {
    const user = node.querySelector(selectors.user), content = node.querySelector(selectors.text);
    if (!user || !content) return;
    const nickname = (user.textContent || '').trim().replace(/[：:]$/, '');
    const text = (content.textContent || '').trim(); if (!nickname || !text) return;
    const stableId = node.getAttribute('data-msg-id') || node.getAttribute('data-id') || '';
    const fingerprint = stableId + '\0' + nickname + '\0' + text;
    if (seen.get(node) === fingerprint) return; seen.set(node, fingerprint); if (initial) return;
    let uid = node.getAttribute('data-uid') || user.getAttribute('data-uid') || '';
    const href = user.getAttribute('href') || user.querySelector('a')?.getAttribute('href') || '';
    const match = href.match(/(?:space\.bilibili\.com\/|\/user\/)([A-Za-z0-9._-]+)/); if (!uid && match) uid = match[1];
    observed++;
    void window[binding]({ type: 'comment', event_id: stableId || instanceId + ':' + (++sequence), room_id: roomId, user_id: uid, nickname, text, timestamp: Date.now(), identity_quality: uid && uid !== '0' ? 'platform_id' : 'display_only' });
  }
  for (const node of document.querySelectorAll(selectors.item)) read(node, true);
  const scan = () => { for (const node of [...document.querySelectorAll(selectors.item)].slice(-100)) read(node); };
  const observer = new MutationObserver(scan); observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  const timer = setInterval(scan, 1500);
  window.__aiTalkChatObserver = { stop: () => { observer.disconnect(); clearInterval(timer); }, get observed() { return observed; } };
  return { matched_nodes: document.querySelectorAll(selectors.item).length, selectors };
}
export function playwrightFor(root) {
  const candidates = [join(root, 'tools/dsh-browser/node_modules/playwright-core'), join(root, 'node_modules/playwright-core')];
  const module = candidates.find(existsSync); check(module, 'PLAYWRIGHT_NOT_INSTALLED', 503);
  return createRequire(import.meta.url)(module);
}
export class BrowserChatAdapter {
  constructor(root, platform, config, { onEvent, onState }) { this.root = root; this.platform = platform; this.config = config; this.onEvent = onEvent; this.onState = onState; this.stopped = true; }
  async start({ visible = false } = {}) {
    check(this.config.room_url, 'ROOM_URL_REQUIRED'); this.stopped = false; this.sessionId = randomUUID();
    const { chromium } = playwrightFor(this.root); this.onState('CONNECTING');
    const executablePath = [process.env.PROGRAMFILES && join(process.env.PROGRAMFILES, 'Google/Chrome/Application/chrome.exe'), process.env['PROGRAMFILES(X86)'] && join(process.env['PROGRAMFILES(X86)'], 'Microsoft/Edge/Application/msedge.exe')].filter(Boolean).find(existsSync);
    check(executablePath, 'BROWSER_NOT_INSTALLED', 503);
    try {
      this.context = await chromium.launchPersistentContext(join(this.root, 'cache/platforms', this.platform), { executablePath, headless: !visible, viewport: { width: 1000, height: 900 }, args: ['--mute-audio', '--disable-background-networking', '--disable-gpu'], acceptDownloads: false });
      await this.context.route('**/*', route => ['media', 'image', 'font'].includes(route.request().resourceType()) || /\.(?:flv|m3u8)(?:[?]|$)/i.test(route.request().url()) ? route.abort() : route.continue());
      await this.context.exposeBinding('aiTalkPlatformMessage', (_source, data) => { if (!this.stopped) { this.onEvent(data, { roomId: this.config.room_id || this.config.room_url.split('/').filter(Boolean).at(-1), sessionId: this.sessionId }); this.onState('RECEIVING'); } });
      this.page = this.context.pages()[0] || await this.context.newPage(); for (const page of this.context.pages()) if (page !== this.page) await page.close();
      this.page.on('close', () => { if (!this.stopped) { this.onState('STOPPED', 'COLLECTOR_WINDOW_CLOSED'); void this.stop(); } });
      const attach = async () => {
        const selectors = { ...CHAT_SELECTORS[this.platform] };
        for (const [field, key] of [['item', 'item_selector'], ['user', 'user_selector'], ['text', 'text_selector']]) if (this.config[key]) selectors[field] = this.config[key];
        const info = await this.page.evaluate(observeChat, { selectors, roomId: this.config.room_id || new URL(this.config.room_url).pathname.split('/').filter(Boolean).at(-1), sessionId: this.sessionId });
        this.onState(info.matched_nodes ? 'WATCHING' : 'WAITING_FOR_CHAT', null, info);
      };
      this.page.on('load', () => { if (!this.stopped) void attach().catch(() => this.onState('WAITING_FOR_CHAT')); });
      await this.page.goto(this.config.room_url, { waitUntil: 'domcontentloaded', timeout: 45000 }); await attach();
    } catch (error) { await this.stop(); this.onState('ERROR', error.code || 'BROWSER_COLLECTOR_FAILED'); throw error; }
  }
  async stop() { this.stopped = true; await this.context?.close().catch(() => {}); this.context = null; this.onState('STOPPED'); }
}
